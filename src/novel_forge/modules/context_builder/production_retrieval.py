"""PostgreSQL discovery and deterministic immutable retrieval artifacts.

Discovery is deliberately separate from ranking.  The Chapter scheduler runs
discovery only after a qualified ChapterMemo exists and freezes every eligible
source AssetVersion into the retrieval Operation.  The handler can therefore
replay ranking without observing a changing projection head.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Iterable, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.context_builder.retrieval import (
    HybridRetrievalQuery,
    hybrid_retrieve,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


RETRIEVAL_POLICY_VERSION = "accepted-hybrid-retrieval-v2"
_SEMANTIC_POLICIES = frozenset({"REQUIRED", "FALLBACK_ALLOWED", "DISABLED"})


@dataclass(frozen=True, slots=True)
class RetrievalDiscovery:
    candidate_inputs: tuple[dict[str, str], ...]
    documents: tuple[dict[str, Any], ...]
    rejected_documents: tuple[dict[str, Any], ...]
    query_plan: dict[str, Any]
    semantic_status: dict[str, Any]


def build_retrieval_query_plan(
    *,
    intent: Mapping[str, Any],
    memo: Mapping[str, Any],
    semantic_policy: str = "FALLBACK_ALLOWED",
) -> dict[str, Any]:
    """Compile the sole production query plan from Intent plus qualified Memo."""

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
        "contract_version": "retrieval-query-plan-v2",
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
        "semantic_policy": policy,
        "candidate_limit": 256,
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
    """Discover a bounded accepted candidate set using PostgreSQL FTS.

    Semantic vectors are read only from the governed 0095 projection table.
    The compatibility ``authority_narrative_retrieval_document.embedding``
    column is intentionally not canonical.
    """

    boundary = int(
        dict(query_plan.get("accepted_boundary") or {}).get(
            "accepted_through_chapter"
        )
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
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """
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
                   document.projection_hash,
                   ts_rank(document.search_vector,
                           plainto_tsquery('simple', %s)) AS fts_rank,
                   COALESCE(embedding.embedding, '[]'::jsonb),
                   COALESCE(embedding.embedding_model, ''),
                   COALESCE(embedding.embedding_provider, ''),
                   COALESCE(embedding.embedding_dimensions, 0),
                   COALESCE(embedding.route_snapshot_id, ''),
                   COALESCE(embedding.receipt_id, ''),
                   COALESCE(embedding.projection_version, '')
            FROM authority_narrative_retrieval_document AS document
            JOIN authority_asset_version AS version
              ON version.asset_version_id=document.source_asset_version_id
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
                  AND projection.source_content_hash=version.content_hash
                ORDER BY projection.projection_version DESC
                LIMIT 1
            ) AS embedding ON TRUE
            WHERE document.project_id=%s AND document.book_id=%s
              AND document.accepted_from_chapter<=%s
              AND (document.accepted_to_chapter IS NULL
                   OR document.accepted_to_chapter>=%s)
              AND (
                (%s<>'' AND document.search_vector @@
                  plainto_tsquery('simple', %s))
                OR document.accepted_from_chapter>=GREATEST(0, %s-12)
                OR document.entity_ids ?| %s::TEXT[]
                OR document.relationship_ids ?| %s::TEXT[]
                OR document.character_ids ?| %s::TEXT[]
                OR document.arc_plan_version_ids ?| %s::TEXT[]
                OR document.obligation_ids ?| %s::TEXT[]
              )
            ORDER BY fts_rank DESC, document.accepted_from_chapter DESC,
                     document.retrieval_document_id
            LIMIT %s
            """,
            [
                text,
                project_id,
                book_id,
                boundary,
                boundary,
                text,
                text,
                boundary,
                entity_ids,
                relationship_ids,
                character_ids,
                arc_ids,
                obligation_ids,
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
    semantic_ready = [item for item in documents if item["embedding"]]
    policy = str(query_plan.get("semantic_policy") or "FALLBACK_ALLOWED")
    semantic_status = {
        "policy": policy,
        "status": (
            "RETRIEVAL_SEMANTIC_PROJECTION_READY"
            if semantic_ready
            else "RETRIEVAL_SEMANTIC_PROJECTION_NOT_READY"
        ),
        "ready_document_count": len(semantic_ready),
        "candidate_document_count": len(documents),
        "fallback": (
            "POSTGRESQL_FTS_GRAPH_TEMPORAL"
            if not semantic_ready and policy == "FALLBACK_ALLOWED"
            else "NONE"
        ),
    }
    if policy == "REQUIRED" and not semantic_ready:
        raise KernelError(
            "RETRIEVAL_SEMANTIC_PROJECTION_REQUIRED",
            "retrieval profile requires a ready governed semantic projection",
        )
    return RetrievalDiscovery(
        candidate_inputs=deduped_inputs,
        documents=documents,
        rejected_documents=rejected,
        query_plan=dict(query_plan),
        semantic_status=semantic_status,
    )


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
) -> dict[str, Any]:
    """Rank one frozen candidate set into a replayable RetrievalResult."""

    frozen = tuple(dict(item) for item in documents)
    boundary = int(
        dict(query_plan.get("accepted_boundary") or {}).get(
            "accepted_through_chapter"
        )
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
            arc_plan_version_ids=tuple(
                _ids(query_plan.get("arc_plan_version_ids"))
            ),
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
        "contract_version": "chapter-retrieval-result-v2",
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
        "ranking": {
            "algorithm": "accepted-hybrid-ranking-v2",
            "lexical_signal": "PostgreSQL Full-Text Search / ts_rank",
            "semantic_signal": "cosine_similarity",
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
    return "sha256:" + hashlib.sha256(
        json.dumps(
            dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


__all__ = [
    "RETRIEVAL_POLICY_VERSION",
    "RetrievalDiscovery",
    "build_retrieval_query_plan",
    "build_retrieval_result",
    "discover_accepted_retrieval_candidates",
]
