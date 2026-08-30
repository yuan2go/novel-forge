"""INVARIANT: discovery freezes eligible source versions before ranking so replay cannot observe a changing projection head."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Iterable, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.context_builder.retrieval import (
    HybridRetrievalQuery,
    RANKING_POLICY_VERSION,
    RANKING_WEIGHTS,
    hybrid_retrieve,
)
from psycopg.types.json import Jsonb
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


RETRIEVAL_POLICY_VERSION = "accepted-lexical-first-retrieval-v4"
SEMANTIC_PROJECTION_VERSION = "accepted-retrieval-embedding-v1"
_SEMANTIC_POLICIES = frozenset({"REQUIRED", "FALLBACK_ALLOWED", "DISABLED"})


@dataclass(frozen=True, slots=True)
class RetrievalDiscovery:
    candidate_inputs: tuple[dict[str, str], ...]
    documents: tuple[dict[str, Any], ...]
    rejected_documents: tuple[dict[str, Any], ...]
    query_plan: dict[str, Any]
    semantic_status: dict[str, Any]


@dataclass(frozen=True, slots=True)
class FrozenRetrievalCandidateUnion:
    candidate_snapshot_id: str
    snapshot_hash: str
    documents: tuple[dict[str, Any], ...]
    query_embedding: tuple[float, ...]
    query_embedding_evidence: dict[str, Any]
    semantic_status: dict[str, Any]
    replayed: bool


def build_retrieval_query_plan(
    *,
    intent: Mapping[str, Any],
    memo: Mapping[str, Any],
    semantic_policy: str = "FALLBACK_ALLOWED",
) -> dict[str, Any]:

    policy = semantic_policy.strip().upper()
    if policy not in _SEMANTIC_POLICIES:
        raise KernelError(
            "RETRIEVAL_SEMANTIC_POLICY_INVALID",
            "semantic retrieval policy must be REQUIRED, FALLBACK_ALLOWED, or DISABLED",
        )
    if str(memo.get("qualification") or "") != "QUALIFIED":
        raise KernelError(
            "RETRIEVAL_MEMO_UNQUALIFIED",
            "retrieval requires a qualified ChapterMemo",
        )
    if int(intent.get("chapter") or 0) != int(memo.get("chapter") or 0):
        raise KernelError(
            "RETRIEVAL_INTENT_MEMO_MISMATCH",
            "ChapterMemo and ExecutionIntent chapter identities differ",
        )
    intent_boundary = dict(intent.get("accepted_boundary") or {})
    memo_boundary = dict(memo.get("accepted_boundary") or {})
    if intent_boundary != memo_boundary:
        raise KernelError(
            "RETRIEVAL_ACCEPTED_BOUNDARY_MISMATCH",
            "ChapterMemo changed the frozen accepted boundary",
        )
    queries = tuple(
        str(item).strip()
        for item in memo.get("retrieval_queries") or ()
        if str(item).strip()
    )
    if not queries:
        raise KernelError(
            "RETRIEVAL_QUERY_PLAN_EMPTY",
            "qualified ChapterMemo must contribute retrieval_queries",
        )
    arc_ids = sorted(
        {
            str(item.get("arc_plan_version_id") or item.get("arc_id") or "")
            for item in (
                *(intent.get("required_arc_contributions") or ()),
                *(memo.get("arc_actions") or ()),
            )
            if isinstance(item, Mapping)
            and str(item.get("arc_plan_version_id") or item.get("arc_id") or "")
        }
    )
    obligation_ids = sorted(
        {
            str(
                item.get("obligation_id")
                or (item.get("state") or {}).get("obligation_id")
                or item.get("entity_key")
                or ""
            )
            for item in (
                *(intent.get("active_obligations") or ()),
                *(memo.get("obligation_actions") or ()),
            )
            if isinstance(item, Mapping)
            and str(
                item.get("obligation_id")
                or (item.get("state") or {}).get("obligation_id")
                or item.get("entity_key")
                or ""
            )
        }
    )
    graph = dict(intent.get("retrieval_graph") or {})
    plan = {
        "contract_version": "retrieval-query-plan-v4",
        "queries": list(queries),
        "postgresql_fts_query": " ".join(queries),
        "entity_ids": _ids(graph.get("entity_ids")),
        "character_ids": _ids(graph.get("character_ids")),
        "relationship_ids": _ids(graph.get("relationship_ids")),
        "arc_plan_version_ids": arc_ids,
        "obligation_ids": obligation_ids,
        "accepted_boundary": intent_boundary,
        "intent_fingerprint": str(intent.get("intent_fingerprint") or ""),
        "memo_fingerprint": str(memo.get("memo_fingerprint") or ""),
        "retrieval_policy_version": RETRIEVAL_POLICY_VERSION,
        "ranking_policy_version": RANKING_POLICY_VERSION,
        "ranking_weights": dict(RANKING_WEIGHTS),
        "semantic_policy": policy,
        "candidate_limit": 256,
        "semantic_rerank_limit": 64,
        "result_limit": 24,
    }
    plan["query_plan_fingerprint"] = _hash(plan)
    return plan


def discover_accepted_retrieval_candidates(
    database_url: str,
    *,
    project_id: str,
    book_id: str,
    query_plan: Mapping[str, Any],
) -> RetrievalDiscovery:
    """INVARIANT: Discover a bounded accepted candidate set using PostgreSQL FTS.

    Exact structured channels may add legal accepted candidates to that bounded
    set. Semantic vectors never participate in discovery; they are consulted
    later only for members of this frozen set. PostgreSQL ``ts_rank`` is not
    described as BM25.
    """
    boundary = int(
        dict(query_plan.get("accepted_boundary") or {}).get("accepted_through_chapter")
        or 0
    )
    if boundary < 0 or not project_id or not book_id:
        raise KernelError(
            "RETRIEVAL_DISCOVERY_SCOPE_INVALID",
            "retrieval discovery requires Project, Book, and accepted boundary",
        )
    text = str(query_plan.get("postgresql_fts_query") or "")
    entity_ids = _ids(query_plan.get("entity_ids"))
    relationship_ids = _ids(query_plan.get("relationship_ids"))
    character_ids = _ids(query_plan.get("character_ids"))
    arc_ids = _ids(query_plan.get("arc_plan_version_ids"))
    obligation_ids = _ids(query_plan.get("obligation_ids"))
    limit = min(256, max(1, int(query_plan.get("candidate_limit") or 256)))
    policy = str(query_plan.get("semantic_policy") or "FALLBACK_ALLOWED")
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("SELECT clock_timestamp()")
        cutoff = uow.cursor.fetchone()[0]
        uow.cursor.execute(
            """
            WITH eligible AS MATERIALIZED (
                SELECT document.*,
                       version.content_hash AS source_content_hash,
                       ts_rank(document.search_vector,
                               plainto_tsquery('simple', %s)) AS fts_rank
                FROM authority_narrative_retrieval_document AS document
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=document.source_asset_version_id
                WHERE document.project_id=%s AND document.book_id=%s
                  AND document.created_at<=%s
                  AND document.accepted_from_chapter<=%s
                  AND (document.accepted_to_chapter IS NULL
                       OR document.accepted_to_chapter>=%s)
                  AND version.lifecycle IN ('ACTIVE','SUPERSEDED')
                  AND version.eligibility='ELIGIBLE'
                  AND version.governance='CLEAR'
            ), fts_candidates AS (
                SELECT retrieval_document_id, 'FTS'::TEXT AS channel
                FROM eligible
                WHERE %s<>'' AND search_vector @@ plainto_tsquery('simple', %s)
                ORDER BY fts_rank DESC, accepted_from_chapter DESC,
                         retrieval_document_id
                LIMIT %s
            ), temporal_candidates AS (
                SELECT retrieval_document_id, 'TEMPORAL'::TEXT AS channel
                FROM eligible
                WHERE accepted_from_chapter>=GREATEST(0, %s-12)
                ORDER BY accepted_from_chapter DESC, retrieval_document_id
                LIMIT %s
            ), entity_candidates AS (
                SELECT retrieval_document_id, 'ENTITY'::TEXT AS channel
                FROM eligible WHERE entity_ids ?| %s::TEXT[]
                ORDER BY accepted_from_chapter DESC, retrieval_document_id LIMIT %s
            ), relationship_candidates AS (
                SELECT retrieval_document_id, 'RELATIONSHIP'::TEXT AS channel
                FROM eligible WHERE relationship_ids ?| %s::TEXT[]
                ORDER BY accepted_from_chapter DESC, retrieval_document_id LIMIT %s
            ), character_candidates AS (
                SELECT retrieval_document_id, 'CHARACTER'::TEXT AS channel
                FROM eligible WHERE character_ids ?| %s::TEXT[]
                ORDER BY accepted_from_chapter DESC, retrieval_document_id LIMIT %s
            ), arc_candidates AS (
                SELECT retrieval_document_id, 'ARC'::TEXT AS channel
                FROM eligible WHERE arc_plan_version_ids ?| %s::TEXT[]
                ORDER BY accepted_from_chapter DESC, retrieval_document_id LIMIT %s
            ), obligation_candidates AS (
                SELECT retrieval_document_id, 'OBLIGATION'::TEXT AS channel
                FROM eligible WHERE obligation_ids ?| %s::TEXT[]
                ORDER BY accepted_from_chapter DESC, retrieval_document_id LIMIT %s
            ), channel_hits AS (
                SELECT * FROM fts_candidates
                UNION ALL SELECT * FROM temporal_candidates
                UNION ALL SELECT * FROM entity_candidates
                UNION ALL SELECT * FROM relationship_candidates
                UNION ALL SELECT * FROM character_candidates
                UNION ALL SELECT * FROM arc_candidates
                UNION ALL SELECT * FROM obligation_candidates
            ), channels AS (
                SELECT retrieval_document_id,
                       ARRAY_AGG(DISTINCT channel ORDER BY channel) AS values
                FROM channel_hits GROUP BY retrieval_document_id
            )
            SELECT document.retrieval_document_id,
                   document.source_asset_version_id,
                   document.source_artifact_type,
                   document.accepted_from_chapter,
                   document.accepted_to_chapter,
                   document.memory_layer,
                   document.content_text,
                   document.entity_ids, document.relationship_ids,
                   document.character_ids, document.arc_plan_version_ids,
                   document.obligation_ids, document.temporal_coordinate,
                   document.metadata, document.source_content_hash,
                   document.projection_hash, document.fts_rank,
                   COALESCE(embedding.embedding, '[]'::jsonb),
                   COALESCE(embedding.embedding_model, ''),
                   COALESCE(embedding.embedding_provider, ''),
                   COALESCE(embedding.embedding_dimensions, 0),
                   COALESCE(embedding.route_snapshot_id, ''),
                   COALESCE(embedding.receipt_id, ''),
                   COALESCE(embedding.projection_version, ''),
                   channels.values
            FROM eligible AS document
            JOIN channels USING(retrieval_document_id)
            LEFT JOIN LATERAL (
                SELECT projection.embedding, projection.embedding_model,
                       projection.embedding_provider,
                       projection.embedding_dimensions,
                       projection.route_snapshot_id, projection.receipt_id,
                       projection.projection_version
                FROM authority_retrieval_embedding_projection AS projection
                WHERE projection.retrieval_document_id=
                      document.retrieval_document_id
                  AND projection.status='READY'
                  AND projection.source_content_hash=document.source_content_hash
                  AND projection.updated_at<=%s
                ORDER BY projection.projection_version DESC
                LIMIT 1
            ) AS embedding ON TRUE
            ORDER BY document.fts_rank DESC,
                     document.accepted_from_chapter DESC,
                     document.retrieval_document_id
            LIMIT %s
            """,
            [
                text,
                project_id,
                book_id,
                cutoff,
                boundary,
                boundary,
                text,
                text,
                limit,
                boundary,
                limit,
                entity_ids,
                limit,
                relationship_ids,
                limit,
                character_ids,
                limit,
                arc_ids,
                limit,
                obligation_ids,
                limit,
                cutoff,
                limit,
            ],
        )
        rows = uow.cursor.fetchall()
        uow.cursor.execute(
            """
            SELECT document.retrieval_document_id,
                   document.source_asset_version_id,
                   version.content_hash,
                   document.accepted_from_chapter,
                   document.accepted_to_chapter
            FROM authority_narrative_retrieval_document AS document
            JOIN authority_asset_version AS version
              ON version.asset_version_id=document.source_asset_version_id
            WHERE document.project_id=%s AND document.book_id=%s
              AND (
                document.accepted_from_chapter>%s
                OR (document.accepted_to_chapter IS NOT NULL
                    AND document.accepted_to_chapter<%s)
              )
            ORDER BY document.accepted_from_chapter,
                     document.retrieval_document_id
            LIMIT 64
            """,
            [project_id, book_id, boundary, boundary],
        )
        excluded_rows = uow.cursor.fetchall()
        ready_projection_count = (
            sum(bool(row[17]) for row in rows) if policy != "DISABLED" else 0
        )
    frozen_query_plan = dict(query_plan)
    frozen_query_plan["candidate_projection_cutoff"] = cutoff.isoformat()
    frozen_query_plan.pop("query_plan_fingerprint", None)
    frozen_query_plan["query_plan_fingerprint"] = _hash(frozen_query_plan)
    documents = tuple(_document_from_row(row) for row in rows)
    inputs = tuple(
        {
            "asset_version_id": str(row[1]),
            "content_hash": str(row[14]),
        }
        for row in rows
    )
    # One AssetVersion may have multiple memory-layer documents.  Operations
    # freeze the source once while the result retains every document identity.
    deduped_inputs = tuple(
        dict(item)
        for _, item in sorted(
            {item["asset_version_id"]: item for item in inputs}.items()
        )
    )
    rejected = tuple(
        {
            "retrieval_document_id": str(row[0]),
            "source_asset_version_id": str(row[1]),
            "source_content_hash": str(row[2]),
            "accepted_from_chapter": int(row[3]),
            "accepted_to_chapter": int(row[4]) if row[4] is not None else None,
            "reason": "FUTURE_ACCEPTED_BOUNDARY"
            if int(row[3]) > boundary
            else "STALE_AT_ACCEPTED_BOUNDARY",
        }
        for row in excluded_rows
    )
    semantic_status = {
        "policy": policy,
        "status": (
            "RETRIEVAL_SEMANTIC_DISABLED"
            if policy == "DISABLED"
            else "RETRIEVAL_SEMANTIC_PROJECTION_READY"
            if ready_projection_count
            else "RETRIEVAL_SEMANTIC_PROJECTION_NOT_READY"
        ),
        "ready_document_count": ready_projection_count,
        "candidate_document_count": len(documents),
        "candidate_projection_cutoff": cutoff.isoformat(),
        "candidate_channels": [
            "FTS",
            "ENTITY",
            "RELATIONSHIP",
            "CHARACTER",
            "ARC",
            "OBLIGATION",
            "TEMPORAL",
        ],
        "fallback": (
            "LEXICAL_STRUCTURED_DETERMINISTIC"
            if not ready_projection_count and policy == "FALLBACK_ALLOWED"
            else "NONE"
        ),
    }
    return RetrievalDiscovery(
        candidate_inputs=deduped_inputs,
        documents=documents,
        rejected_documents=rejected,
        query_plan=frozen_query_plan,
        semantic_status=semantic_status,
    )


def load_frozen_retrieval_candidate_union(
    database_url: str,
    *,
    project_id: str,
    operation_id: str,
    query_plan_fingerprint: str,
) -> FrozenRetrievalCandidateUnion | None:

    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """
            SELECT candidate_snapshot_id, snapshot_hash, documents,
                   query_embedding, query_embedding_evidence, semantic_status,
                   query_plan_fingerprint, ranking_policy_version, book_id,
                   candidate_projection_cutoff, query_embedding_model,
                   query_embedding_dimensions, candidate_asset_versions
            FROM authority_retrieval_candidate_snapshot
            WHERE operation_id=%s AND project_id=%s
            """,
            [operation_id, project_id],
        )
        row = uow.cursor.fetchone()
    if row is None:
        return None
    if str(row[6]) != query_plan_fingerprint or str(row[7]) != RANKING_POLICY_VERSION:
        raise KernelError(
            "RETRIEVAL_CANDIDATE_SNAPSHOT_CONFLICT",
            "existing candidate snapshot differs from the frozen query/ranking policy",
        )
    snapshot_core = {
        "contract_version": "retrieval-candidate-snapshot-v4",
        "project_id": project_id,
        "book_id": str(row[8]),
        "operation_id": operation_id,
        "query_plan_fingerprint": str(row[6]),
        "candidate_projection_cutoff": row[9].isoformat(),
        "ranking_policy_version": str(row[7]),
        "query_embedding": list(row[3] or ()),
        "query_embedding_model": str(row[10]),
        "query_embedding_dimensions": int(row[11] or 0),
        "query_embedding_evidence": dict(row[4] or {}),
        "candidate_asset_versions": [dict(item) for item in row[12] or ()],
        "documents": [dict(item) for item in row[2] or ()],
        "semantic_status": dict(row[5] or {}),
    }
    if _hash(snapshot_core) != str(row[1]):
        raise KernelError(
            "RETRIEVAL_CANDIDATE_SNAPSHOT_CORRUPT",
            "candidate snapshot hash differs from its durable content",
        )
    return FrozenRetrievalCandidateUnion(
        candidate_snapshot_id=str(row[0]),
        snapshot_hash=str(row[1]),
        documents=tuple(dict(item) for item in row[2] or ()),
        query_embedding=tuple(float(item) for item in row[3] or ()),
        query_embedding_evidence=dict(row[4] or {}),
        semantic_status=dict(row[5] or {}),
        replayed=True,
    )


def freeze_retrieval_candidate_union(
    database_url: str,
    *,
    project_id: str,
    book_id: str,
    operation_id: str,
    attempt_id: str,
    fencing_token: int,
    worker_id: str,
    query_plan: Mapping[str, Any],
    base_documents: Iterable[Mapping[str, Any]],
    semantic_status: Mapping[str, Any],
    query_embedding: Iterable[float] = (),
    query_embedding_model: str = "",
    query_embedding_dimensions: int = 0,
    query_embedding_evidence: Mapping[str, Any] | None = None,
) -> FrozenRetrievalCandidateUnion:
    """INVARIANT: Freeze lexical/structured candidates and optional semantic rerank data.

    The vector query is restricted to the already-discovered document IDs
    before distance ordering. It cannot introduce a candidate. Replays consume
    the immutable snapshot rather than observing later index updates.
    """
    policy = str(query_plan.get("semantic_policy") or "FALLBACK_ALLOWED")
    vector = tuple(float(item) for item in query_embedding)
    if policy == "DISABLED" and vector:
        raise KernelError(
            "RETRIEVAL_SEMANTIC_DISABLED",
            "semantic-disabled retrieval cannot freeze a query embedding",
        )
    if bool(vector) != bool(query_embedding_model and query_embedding_dimensions > 0):
        raise KernelError(
            "RETRIEVAL_QUERY_EMBEDDING_INVALID",
            "query embedding identity and vector must be complete together",
        )
    if vector and len(vector) != query_embedding_dimensions:
        raise KernelError(
            "RETRIEVAL_QUERY_EMBEDDING_INVALID",
            "query embedding dimensions differ from its vector",
        )
    query_plan_fingerprint = str(query_plan.get("query_plan_fingerprint") or "")
    cutoff = str(query_plan.get("candidate_projection_cutoff") or "")
    if not query_plan_fingerprint or not cutoff:
        raise KernelError(
            "RETRIEVAL_QUERY_PLAN_NOT_FROZEN",
            "candidate discovery requires a fingerprinted projection cutoff",
        )
    existing = load_frozen_retrieval_candidate_union(
        database_url,
        project_id=project_id,
        operation_id=operation_id,
        query_plan_fingerprint=query_plan_fingerprint,
    )
    if existing is not None:
        return existing

    base_documents = tuple(dict(item) for item in base_documents)
    base_document_ids = sorted(
        {str(item["retrieval_document_id"]) for item in base_documents}
    )
    with AuthorityUnitOfWork(database_url) as uow:
        _lock_retrieval_attempt_fence(
            uow,
            project_id=project_id,
            operation_id=operation_id,
            attempt_id=attempt_id,
            fencing_token=fencing_token,
            worker_id=worker_id,
        )
        semantic_documents: tuple[dict[str, Any], ...] = ()
        if vector and base_document_ids:
            distance_expression = _vector_distance_expression(
                query_embedding_dimensions
            )
            uow.cursor.execute(
                f"""
                SELECT document.retrieval_document_id,
                       document.source_asset_version_id,
                       document.source_artifact_type,
                       document.accepted_from_chapter,
                       document.accepted_to_chapter,
                       document.memory_layer,
                       document.content_text,
                       document.entity_ids, document.relationship_ids,
                       document.character_ids, document.arc_plan_version_ids,
                       document.obligation_ids, document.temporal_coordinate,
                       document.metadata, version.content_hash,
                       document.projection_hash, 0::DOUBLE PRECISION,
                       projection.embedding, projection.embedding_model,
                       projection.embedding_provider,
                       projection.embedding_dimensions,
                       projection.route_snapshot_id, projection.receipt_id,
                       projection.projection_version,
                       ARRAY['VECTOR']::TEXT[]
                FROM authority_retrieval_embedding_projection AS projection
                JOIN authority_narrative_retrieval_document AS document
                  ON document.retrieval_document_id=projection.retrieval_document_id
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=document.source_asset_version_id
                WHERE projection.project_id=%s AND projection.book_id=%s
                  AND document.retrieval_document_id=ANY(%s::TEXT[])
                  AND projection.status='READY'
                  AND projection.embedding_vector IS NOT NULL
                  AND projection.embedding_model=%s
                  AND projection.embedding_dimensions=%s
                  AND projection.projection_version=%s
                  AND projection.source_content_hash=version.content_hash
                  AND projection.updated_at<=%s AND document.created_at<=%s
                  AND document.accepted_from_chapter<=%s
                  AND (document.accepted_to_chapter IS NULL
                       OR document.accepted_to_chapter>=%s)
                  AND version.lifecycle IN ('ACTIVE','SUPERSEDED')
                  AND version.eligibility='ELIGIBLE'
                  AND version.governance='CLEAR'
                ORDER BY {distance_expression}, document.retrieval_document_id
                LIMIT %s
                """,
                [
                    project_id,
                    book_id,
                    base_document_ids,
                    query_embedding_model,
                    query_embedding_dimensions,
                    SEMANTIC_PROJECTION_VERSION,
                    cutoff,
                    cutoff,
                    int(
                        dict(query_plan.get("accepted_boundary") or {}).get(
                            "accepted_through_chapter"
                        )
                        or 0
                    ),
                    int(
                        dict(query_plan.get("accepted_boundary") or {}).get(
                            "accepted_through_chapter"
                        )
                        or 0
                    ),
                    _pgvector_literal(vector),
                    min(
                        256,
                        max(
                            1,
                            int(query_plan.get("semantic_rerank_limit") or 64),
                        ),
                    ),
                ],
            )
            semantic_documents = tuple(
                _document_from_row(row) for row in uow.cursor.fetchall()
            )
        compatible_base = tuple(
            _compatible_document(
                item,
                model=query_embedding_model,
                dimensions=query_embedding_dimensions,
            )
            for item in base_documents
        )
        documents = _merge_candidate_channels(compatible_base, semantic_documents)
        semantic_used = sum(
            1 for item in documents if "VECTOR" in item.get("candidate_channels", ())
        )
        if policy == "REQUIRED" and semantic_used == 0:
            raise KernelError(
                "RETRIEVAL_SEMANTIC_PROJECTION_REQUIRED",
                "semantic-required retrieval has no compatible vector candidate",
            )
        frozen_semantic_status = {
            **dict(semantic_status),
            "status": (
                "RETRIEVAL_SEMANTIC_DISABLED"
                if policy == "DISABLED"
                else "RETRIEVAL_SEMANTIC_RERANK_READY"
                if semantic_used
                else "RETRIEVAL_SEMANTIC_PROJECTION_NOT_READY"
            ),
            "vector_candidate_count": semantic_used,
            "semantic_rerank_document_count": semantic_used,
            "candidate_document_count": len(documents),
            "semantic_candidate_expansion": False,
            "query_embedding_status": "READY" if vector else "NOT_READY",
            "query_embedding_model": query_embedding_model,
            "query_embedding_dimensions": query_embedding_dimensions,
            "ranking_policy_version": RANKING_POLICY_VERSION,
            "fallback": (
                "LEXICAL_STRUCTURED_DETERMINISTIC"
                if policy == "FALLBACK_ALLOWED" and not semantic_used
                else "NONE"
            ),
        }
        source_versions = sorted(
            {
                (
                    str(item["source_asset_version_id"]),
                    str(item["source_content_hash"]),
                )
                for item in documents
            }
        )
        query_embedding_evidence_value = dict(query_embedding_evidence or {})
        snapshot_core = {
            "contract_version": "retrieval-candidate-snapshot-v4",
            "project_id": project_id,
            "book_id": book_id,
            "operation_id": operation_id,
            "query_plan_fingerprint": query_plan_fingerprint,
            "candidate_projection_cutoff": cutoff,
            "ranking_policy_version": RANKING_POLICY_VERSION,
            "query_embedding": list(vector),
            "query_embedding_model": query_embedding_model,
            "query_embedding_dimensions": query_embedding_dimensions,
            "query_embedding_evidence": query_embedding_evidence_value,
            "candidate_asset_versions": [
                {"asset_version_id": identity, "content_hash": content_hash}
                for identity, content_hash in source_versions
            ],
            "documents": [dict(item) for item in documents],
            "semantic_status": frozen_semantic_status,
        }
        snapshot_hash = _hash(snapshot_core)
        snapshot_id = (
            "retrieval-candidates:" + hashlib.sha256(operation_id.encode()).hexdigest()
        )
        uow.cursor.execute(
            """
            INSERT INTO authority_retrieval_candidate_snapshot(
                candidate_snapshot_id, project_id, book_id, operation_id,
                attempt_id, fencing_token, query_plan_fingerprint,
                candidate_projection_cutoff, ranking_policy_version,
                query_embedding, query_embedding_model,
                query_embedding_dimensions, query_embedding_evidence,
                candidate_asset_versions, documents, semantic_status,
                snapshot_hash
            ) VALUES (
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
            )
            ON CONFLICT(operation_id) DO NOTHING
            """,
            [
                snapshot_id,
                project_id,
                book_id,
                operation_id,
                attempt_id,
                fencing_token,
                query_plan_fingerprint,
                cutoff,
                RANKING_POLICY_VERSION,
                Jsonb(list(vector)),
                query_embedding_model,
                query_embedding_dimensions or None,
                Jsonb(query_embedding_evidence_value),
                Jsonb(snapshot_core["candidate_asset_versions"]),
                Jsonb(snapshot_core["documents"]),
                Jsonb(frozen_semantic_status),
                snapshot_hash,
            ],
        )
        uow.commit()
    frozen = load_frozen_retrieval_candidate_union(
        database_url,
        project_id=project_id,
        operation_id=operation_id,
        query_plan_fingerprint=query_plan_fingerprint,
    )
    if frozen is None:
        raise KernelError(
            "RETRIEVAL_CANDIDATE_SNAPSHOT_MISSING",
            "candidate union was not persisted",
        )
    return FrozenRetrievalCandidateUnion(
        candidate_snapshot_id=frozen.candidate_snapshot_id,
        snapshot_hash=frozen.snapshot_hash,
        documents=frozen.documents,
        query_embedding=frozen.query_embedding,
        query_embedding_evidence=frozen.query_embedding_evidence,
        semantic_status=frozen.semantic_status,
        replayed=False,
    )


def _lock_retrieval_attempt_fence(
    uow: AuthorityUnitOfWork,
    *,
    project_id: str,
    operation_id: str,
    attempt_id: str,
    fencing_token: int,
    worker_id: str,
) -> None:
    uow.cursor.execute(
        """
        SELECT 1
        FROM authority_operation AS operation
        JOIN authority_attempt AS attempt
          ON attempt.operation_id=operation.operation_id
        JOIN authority_lease_acquisition AS lease
          ON lease.attempt_id=attempt.attempt_id
        WHERE operation.operation_id=%s AND operation.project_id=%s
          AND operation.status='EXECUTING'
          AND attempt.attempt_id=%s
          AND attempt.status IN ('LEASED','RUNNING','RESULT_SUBMITTED')
          AND lease.fencing_token=%s AND lease.owner=%s
          AND lease.status='HELD' AND lease.expires_at>NOW()
        FOR UPDATE OF attempt, lease
        """,
        [operation_id, project_id, attempt_id, fencing_token, worker_id],
    )
    if uow.cursor.fetchone() is None:
        raise KernelError(
            "RETRIEVAL_CANDIDATE_FENCE_STALE",
            "candidate snapshot requires the current Retrieval Attempt lease",
        )


def _vector_distance_expression(dimensions: int) -> str:
    if dimensions == 1024:
        return "(projection.embedding_vector::vector(1024) <=> %s::vector(1024))"
    if dimensions == 1536:
        return "(projection.embedding_vector::vector(1536) <=> %s::vector(1536))"
    if dimensions == 3072:
        return "(projection.embedding_vector::halfvec(3072) <=> %s::halfvec(3072))"
    return "(projection.embedding_vector <=> %s::vector)"


def _pgvector_literal(vector: Iterable[float]) -> str:
    return "[" + ",".join(format(float(item), ".17g") for item in vector) + "]"


def _compatible_document(
    raw: Mapping[str, Any], *, model: str, dimensions: int
) -> dict[str, Any]:
    document = dict(raw)
    document["candidate_channels"] = sorted(
        {str(item) for item in document.get("candidate_channels") or ()}
    )
    if document.get("embedding") and (
        not model
        or str(document.get("embedding_model") or "") != model
        or int(document.get("embedding_dimensions") or 0) != dimensions
        or str(document.get("embedding_projection_version") or "")
        != SEMANTIC_PROJECTION_VERSION
    ):
        for field, empty in (
            ("embedding", []),
            ("embedding_model", ""),
            ("embedding_provider", ""),
            ("embedding_dimensions", 0),
            ("embedding_route_snapshot_id", ""),
            ("embedding_receipt_id", ""),
            ("embedding_projection_version", ""),
        ):
            document[field] = empty
    return document


def _merge_candidate_channels(
    base: Iterable[Mapping[str, Any]], semantic: Iterable[Mapping[str, Any]]
) -> tuple[dict[str, Any], ...]:
    merged: dict[str, dict[str, Any]] = {}
    for raw in base:
        item = dict(raw)
        identity = str(item["retrieval_document_id"])
        item["candidate_channels"] = sorted(
            {str(value) for value in item.get("candidate_channels") or ()}
        )
        merged[identity] = item
    for raw in semantic:
        item = dict(raw)
        identity = str(item["retrieval_document_id"])
        existing = merged.get(identity)
        if existing is None:
            raise KernelError(
                "RETRIEVAL_SEMANTIC_CANDIDATE_ESCAPE",
                "semantic rerank attempted to introduce a document outside the "
                "frozen lexical/structured candidate set",
            )
        channels = sorted(
            {
                *(str(value) for value in existing.get("candidate_channels") or ()),
                *(str(value) for value in item.get("candidate_channels") or ()),
            }
        )
        if item.get("embedding"):
            existing.update(
                {
                    key: item[key]
                    for key in (
                        "embedding",
                        "embedding_model",
                        "embedding_provider",
                        "embedding_dimensions",
                        "embedding_route_snapshot_id",
                        "embedding_receipt_id",
                        "embedding_projection_version",
                    )
                }
            )
        existing["candidate_channels"] = channels
        existing["postgresql_fts_rank"] = max(
            float(existing.get("postgresql_fts_rank") or 0),
            float(item.get("postgresql_fts_rank") or 0),
        )
    return tuple(merged[key] for key in sorted(merged))


def build_retrieval_result(
    *,
    project_id: str,
    book_id: str,
    intent_asset_version_id: str,
    memo_asset_version_id: str,
    query_plan: Mapping[str, Any],
    documents: Iterable[Mapping[str, Any]],
    discovery_rejections: Iterable[Mapping[str, Any]],
    semantic_status: Mapping[str, Any],
    query_embedding: Iterable[float] = (),
    query_embedding_evidence: Mapping[str, Any] | None = None,
    candidate_snapshot_id: str = "",
    candidate_snapshot_hash: str = "",
) -> dict[str, Any]:

    if (
        str(query_plan.get("ranking_policy_version") or "") != RANKING_POLICY_VERSION
        or dict(query_plan.get("ranking_weights") or {}) != RANKING_WEIGHTS
    ):
        raise KernelError(
            "RETRIEVAL_RANKING_POLICY_DRIFT",
            "RetrievalResult ranking policy differs from the governed v3 weights",
        )
    frozen = tuple(dict(item) for item in documents)
    boundary = int(
        dict(query_plan.get("accepted_boundary") or {}).get("accepted_through_chapter")
        or 0
    )
    query_vector = tuple(float(item) for item in query_embedding)
    ranked = hybrid_retrieve(
        HybridRetrievalQuery(
            text=str(query_plan.get("postgresql_fts_query") or ""),
            accepted_through_chapter=boundary,
            entity_ids=tuple(_ids(query_plan.get("entity_ids"))),
            relationship_ids=tuple(_ids(query_plan.get("relationship_ids"))),
            character_ids=tuple(_ids(query_plan.get("character_ids"))),
            arc_plan_version_ids=tuple(_ids(query_plan.get("arc_plan_version_ids"))),
            obligation_ids=tuple(_ids(query_plan.get("obligation_ids"))),
            query_embedding=query_vector,
            limit=int(query_plan.get("result_limit") or 24),
        ),
        frozen,
    )
    selected_ids = {str(item["retrieval_document_id"]) for item in ranked}
    rejected = [dict(item) for item in discovery_rejections]
    rejected.extend(
        {
            "retrieval_document_id": str(item["retrieval_document_id"]),
            "source_asset_version_id": str(item["source_asset_version_id"]),
            "source_content_hash": str(item["source_content_hash"]),
            "reason": "RANK_LIMIT",
        }
        for item in frozen
        if str(item["retrieval_document_id"]) not in selected_ids
    )
    selected = [_selected_document(item) for item in ranked]
    result = {
        "type": "RetrievalResult",
        "contract_version": "chapter-retrieval-result-v4",
        "project_id": project_id,
        "book_id": book_id,
        "accepted_boundary": dict(query_plan.get("accepted_boundary") or {}),
        "intent_asset_version_id": intent_asset_version_id,
        "memo_asset_version_id": memo_asset_version_id,
        "intent_fingerprint": str(query_plan.get("intent_fingerprint") or ""),
        "memo_fingerprint": str(query_plan.get("memo_fingerprint") or ""),
        "query_plan": dict(query_plan),
        "retrieval_policy_version": str(
            query_plan.get("retrieval_policy_version") or ""
        ),
        "candidate_snapshot_id": candidate_snapshot_id,
        "candidate_snapshot_hash": candidate_snapshot_hash,
        "ranking": {
            "algorithm": RANKING_POLICY_VERSION,
            "ranking_policy_version": str(
                query_plan.get("ranking_policy_version") or ""
            ),
            "weights": dict(query_plan.get("ranking_weights") or {}),
            "lexical_signal": "PostgreSQL Full-Text Search / ts_rank",
            "semantic_signal": "cosine_similarity",
            "candidate_discovery": "LEXICAL_AND_EXACT_STRUCTURED_ONLY",
            "semantic_candidate_expansion": False,
            "graph_signals": [
                "entity",
                "character_timeline",
                "relationship",
                "arc",
                "obligation",
            ],
            "temporal_signal": "accepted_chapter_recency",
        },
        "semantic_status": dict(semantic_status),
        "query_embedding_evidence": dict(query_embedding_evidence or {}),
        "candidate_channels": sorted(
            {
                str(channel)
                for item in frozen
                for channel in item.get("candidate_channels") or ()
            }
        ),
        "candidate_asset_versions": [
            {"asset_version_id": asset_version_id, "content_hash": content_hash}
            for asset_version_id, content_hash in sorted(
                {
                    (
                        str(item["source_asset_version_id"]),
                        str(item["source_content_hash"]),
                    )
                    for item in frozen
                }
            )
        ],
        "selected_documents": selected,
        "selected_source_asset_versions": [
            {"asset_version_id": asset_version_id, "content_hash": content_hash}
            for asset_version_id, content_hash in sorted(
                {
                    (
                        str(item["source_asset_version_id"]),
                        str(item["source_content_hash"]),
                    )
                    for item in selected
                }
            )
        ],
        "rejected_documents": sorted(
            rejected,
            key=lambda item: (
                str(item.get("reason") or ""),
                str(item.get("retrieval_document_id") or ""),
            ),
        ),
    }
    result["result_fingerprint"] = _hash(result)
    return result


def _document_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "retrieval_document_id": str(row[0]),
        "source_asset_version_id": str(row[1]),
        "source_artifact_type": str(row[2]),
        "accepted_from_chapter": int(row[3]),
        "accepted_to_chapter": int(row[4]) if row[4] is not None else None,
        "memory_layer": str(row[5]),
        "content_text": str(row[6]),
        "entity_ids": list(row[7] or ()),
        "relationship_ids": list(row[8] or ()),
        "character_ids": list(row[9] or ()),
        "arc_plan_version_ids": list(row[10] or ()),
        "obligation_ids": list(row[11] or ()),
        "temporal_coordinate": dict(row[12] or {}),
        "metadata": dict(row[13] or {}),
        "source_content_hash": str(row[14]),
        "projection_hash": str(row[15]),
        "postgresql_fts_rank": float(row[16] or 0.0),
        "embedding": list(row[17] or ()),
        "embedding_model": str(row[18] or ""),
        "embedding_provider": str(row[19] or ""),
        "embedding_dimensions": int(row[20] or 0),
        "embedding_route_snapshot_id": str(row[21] or ""),
        "embedding_receipt_id": str(row[22] or ""),
        "embedding_projection_version": str(row[23] or ""),
        "candidate_channels": sorted(str(item) for item in row[24] or ()),
    }


def _selected_document(item: Mapping[str, Any]) -> dict[str, Any]:
    content = str(item.get("content_text") or "")
    maximum = 4_000
    compressed = len(content) > maximum
    return {
        key: item.get(key)
        for key in (
            "retrieval_document_id",
            "source_asset_version_id",
            "source_artifact_type",
            "source_content_hash",
            "projection_hash",
            "accepted_from_chapter",
            "accepted_to_chapter",
            "memory_layer",
            "entity_ids",
            "relationship_ids",
            "character_ids",
            "arc_plan_version_ids",
            "obligation_ids",
            "temporal_coordinate",
            "metadata",
            "retrieval_score",
            "retrieval_scores",
            "retrieval_reasons",
            "embedding_model",
            "embedding_provider",
            "embedding_dimensions",
            "embedding_route_snapshot_id",
            "embedding_receipt_id",
            "embedding_projection_version",
            "candidate_channels",
        )
    } | {
        "safe_summary": content[:maximum],
        "input_characters": len(content),
        "output_characters": min(maximum, len(content)),
        "compression_method": (
            "deterministic_bounded_extract" if compressed else "none"
        ),
        "compression_provenance": {
            "source_asset_version_id": str(item["source_asset_version_id"]),
            "source_content_hash": str(item["source_content_hash"]),
            "source_projection_hash": str(item["projection_hash"]),
            "method": "deterministic_bounded_extract" if compressed else "none",
            "input_characters": len(content),
            "output_characters": min(maximum, len(content)),
            "content_fingerprint": "sha256:"
            + hashlib.sha256(content.encode()).hexdigest(),
        },
    }


def _ids(values: Any) -> list[str]:
    return sorted({str(item) for item in values or () if str(item)})


def _hash(value: Mapping[str, Any]) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
    )


__all__ = [
    "RETRIEVAL_POLICY_VERSION",
    "SEMANTIC_PROJECTION_VERSION",
    "FrozenRetrievalCandidateUnion",
    "RetrievalDiscovery",
    "build_retrieval_query_plan",
    "build_retrieval_result",
    "discover_accepted_retrieval_candidates",
    "freeze_retrieval_candidate_union",
    "load_frozen_retrieval_candidate_union",
]
