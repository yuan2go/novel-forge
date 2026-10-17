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
from novel_forge.modules.context_builder.retrieval_campaign import (
    RetrievalCampaignPolicy,
    build_retrieval_coverage_contract,
)
from novel_forge.modules.context_builder.task_context import (
    fact_aliases, historical_endpoints, provider_visible_state, required_current_entry, task_references,
)
from psycopg.types.json import Jsonb
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .writer_projection import (
    WRITER_PROJECTION_VERSION, WRITER_PROSE_TYPES, bind_writer_history_source,
    project_writer_retrieval_history, provider_visible_data,
)


RETRIEVAL_POLICY_VERSION = "minimum-sufficient-retrieval-v8"
SEMANTIC_PROJECTION_VERSION = "accepted-retrieval-embedding-v2"
_SEMANTIC_POLICIES = frozenset({"REQUIRED", "FALLBACK_ALLOWED", "DISABLED"})
_TASK_DEPENDENCY_CONTRACT = "task-dependency-refs-v1"
_TASK_DEPENDENCY_REF_LIMIT = 2_048
_TASK_DEPENDENCY_CLOSURE_LIMIT = 32


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


def build_task_dependency_refs(
    *, plan: Mapping[str, Any], current_candidates: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    from novel_forge.modules.chapter_authority.provider_views import build_task_narrative_projection

    required = set(_ids(plan.get("required_long_distance_fact_ids")))
    projection = build_task_narrative_projection({"chapter": 0, **plan}, task_scoped=True)
    selectors = task_references(plan) | task_references(projection)
    obligations = set(_ids(plan.get("required_obligation_ids")))
    referenced_obligations = set(_ids(plan.get("obligation_refs"))) | set(_ids(projection.get("obligation_refs")))
    initial_obligations: list[dict[str, Any]] = []
    aliases: set[str] = set()
    bindings: set[tuple[str, str]] = set()
    for candidate in current_candidates:
        if candidate.get("asset_type") in {"creative_foundation", "world_bible", "character_cards", "character_cast"}:
            bindings.add((str(candidate["asset_version_id"]), str(candidate["content_hash"])))
            aliases.update(
                "foundation:" + str(identity)
                for identity in (candidate["asset_version_id"], dict(candidate.get("provenance") or {}).get("authority_asset_version_id"))
                if identity
            )
        if candidate.get("asset_type") not in {"canon_snapshot", "story_state_snapshot"}:
            continue
        bindings.add((str(candidate["asset_version_id"]), str(candidate["content_hash"])))
        for fact in candidate.get("structured_facts") or ():
            if not isinstance(fact, Mapping) or fact.get("provider_visibility") == "INTERNAL_QUALITY_ONLY":
                continue
            aliases.update(fact_aliases(fact))
            state = dict(fact.get("state") or {})
            if (fact.get("state_kind") == "narrative_obligation"
                and state.get("obligation_id")
                and state.get("provider_visibility") != "INTERNAL_QUALITY_ONLY"
                and required_current_entry("narrative_obligation", fact, selectors=selectors, required=required, chapter=int(plan.get("chapter") or 0))):
                obligations.add(str(state["obligation_id"]))
            initial_boundary = dict(candidate.get("accepted_boundary") or {})
            if (candidate.get("asset_type") == "story_state_snapshot"
                and initial_boundary.get("story_state_asset_version_id") == candidate["asset_version_id"]
                and fact.get("state_kind") == "narrative_obligation" and state.get("obligation_id")
                and fact.get("source_chapter") == 0 and fact.get("effective_from_chapter") == 0
                and provider_visible_state(fact)):
                initial_obligations.append(_initial_obligation_binding(fact, candidate, initial_boundary))
            transition = dict(dict(fact.get("state") or {}).get("world_transition") or {})
            required.update(_ids(transition.get("cause_refs")))
    if len(required) + len(obligations) > _TASK_DEPENDENCY_REF_LIMIT or len(initial_obligations) > _TASK_DEPENDENCY_REF_LIMIT:
        raise KernelError("RETRIEVAL_TASK_DEPENDENCY_LIMIT", "required task dependency set exceeds the bounded discovery contract")
    return {
        "contract_version": _TASK_DEPENDENCY_CONTRACT,
        "required_refs": sorted(required),
        "required_obligation_ids": sorted(obligations),
        "referenced_obligation_ids": sorted(referenced_obligations),
        "protected_initial_obligations": sorted(initial_obligations, key=lambda item: (item["obligation_id"], item["asset_version_id"], item["state_hash"])),
        "protected_fact_aliases": sorted(aliases),
        "source_bindings": [
            {"asset_version_id": identity, "content_hash": content_hash}
            for identity, content_hash in sorted(bindings)
        ],
        "dependency_ref_limit": _TASK_DEPENDENCY_REF_LIMIT,
        "closure_round_limit": _TASK_DEPENDENCY_CLOSURE_LIMIT,
    }


def build_retrieval_query_plan(
    *,
    intent: Mapping[str, Any],
    memo: Mapping[str, Any],
    semantic_policy: str = "FALLBACK_ALLOWED",
    campaign_policy: RetrievalCampaignPolicy | None = None,
    task_dependency_refs: Mapping[str, Any] | None = None,
    preserve_source_json: bool = False,
) -> dict[str, Any]:

    policy = semantic_policy.strip().upper()
    if policy not in _SEMANTIC_POLICIES:
        raise KernelError(
            "RETRIEVAL_SEMANTIC_POLICY_INVALID",
            "semantic retrieval policy must be REQUIRED, FALLBACK_ALLOWED, or DISABLED",
        )
    from novel_forge.modules.chapter_authority.execution_artifacts import MEMO_INPUT_QUALIFICATIONS
    if str(memo.get("qualification") or "") not in MEMO_INPUT_QUALIFICATIONS:
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
    policy_contract = campaign_policy or RetrievalCampaignPolicy()
    coverage_contract = build_retrieval_coverage_contract(intent=intent, memo=memo)
    boundary = int(intent_boundary.get("accepted_through_chapter") or 0)
    plan = {
        "contract_version": "retrieval-query-plan-v5",
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
        "writer_projection_version": "accepted-writer-history.v2",
        **({"source_json_projection": "source-json-values.v1"} if preserve_source_json else {}),
        "ranking_policy_version": RANKING_POLICY_VERSION,
        "ranking_weights": dict(RANKING_WEIGHTS),
        "semantic_policy": policy,
        "candidate_limit": 256,
        "semantic_rerank_limit": 64,
        "result_limit": 24,
        "temporal_range": {"from_chapter": 0, "to_chapter": boundary},
        "coverage_contract": coverage_contract,
        "campaign_policy": policy_contract.to_dict(),
    }
    if task_dependency_refs is not None:
        dependencies = dict(task_dependency_refs)
        if dependencies.get("contract_version") != _TASK_DEPENDENCY_CONTRACT:
            raise KernelError("RETRIEVAL_TASK_DEPENDENCY_CONTRACT_INVALID", "task dependency discovery requires its versioned frozen contract")
        if "required_obligation_ids" in dependencies:
            historical = {str(item.get("obligation_id") or (item.get("state") or {}).get("obligation_id") or "")
                          for item in intent.get("active_obligations") or () if isinstance(item, Mapping)}
            referenced = set(_ids(dependencies.get("referenced_obligation_ids"))) | {
                str(item.get("obligation_id") or "") for item in memo.get("obligation_actions") or () if isinstance(item, Mapping)
            }
            dependencies["required_obligation_ids"] = sorted(set(_ids(dependencies.get("required_obligation_ids"))) | (referenced & (historical - {""})))
        if len(_ids(dependencies.get("required_refs"))) + len(_ids(dependencies.get("required_obligation_ids"))) > _TASK_DEPENDENCY_REF_LIMIT:
            raise KernelError("RETRIEVAL_TASK_DEPENDENCY_LIMIT", "required task dependency set exceeds the bounded discovery contract")
        plan.update({
            "contract_version": "retrieval-query-plan-v6",
            "retrieval_policy_version": "minimum-sufficient-task-retrieval-v6",
            "task_dependency_refs": dependencies,
        })
    plan["query_plan_fingerprint"] = _hash(plan)
    return plan


def build_expanded_retrieval_query_plan(
    *,
    base_query_plan: Mapping[str, Any],
    expansion_plan: Mapping[str, Any],
) -> dict[str, Any]:
    queries = expansion_plan.get("queries")
    if not isinstance(queries, list) or not queries:
        raise KernelError(
            "RETRIEVAL_EXPANSION_PLAN_INVALID",
            "expanded retrieval requires a validated non-empty query plan",
        )
    base_boundary = dict(base_query_plan.get("accepted_boundary") or {})
    if base_boundary != dict(expansion_plan.get("accepted_boundary") or {}):
        raise KernelError(
            "RETRIEVAL_EXPANSION_BOUNDARY_MISMATCH",
            "expanded retrieval changed the frozen accepted boundary",
        )
    if str(base_query_plan.get("candidate_projection_cutoff") or "") == "":
        raise KernelError(
            "RETRIEVAL_EXPANSION_CUTOFF_MISSING",
            "expanded retrieval requires the round-zero projection cutoff",
        )
    texts = [str(item.get("text") or "") for item in queries]
    starts = [
        int(dict(item.get("temporal_range") or {}).get("from_chapter") or 0)
        for item in queries
    ]
    ends = [
        int(dict(item.get("temporal_range") or {}).get("to_chapter") or 0)
        for item in queries
    ]
    plan = {
        key: value
        for key, value in dict(base_query_plan).items()
        if key != "query_plan_fingerprint"
    }
    plan.update(
        {
            "contract_version": str(base_query_plan.get("contract_version") or "retrieval-query-plan-v5"),
            "queries": texts,
            "postgresql_fts_query": " ".join(texts),
            "entity_ids": _expanded_ids(plan, queries, "entity_ids"),
            "character_ids": _expanded_ids(plan, queries, "character_ids"),
            "relationship_ids": _expanded_ids(plan, queries, "relationship_ids"),
            "arc_plan_version_ids": _expanded_ids(
                plan, queries, "arc_plan_version_ids"
            ),
            "obligation_ids": _expanded_ids(plan, queries, "obligation_ids"),
            "temporal_range": {
                "from_chapter": min(starts),
                "to_chapter": max(ends),
            },
            "expansion_plan_fingerprint": str(
                expansion_plan.get("expansion_plan_fingerprint") or ""
            ),
            "retrieval_round": int(expansion_plan.get("round_number") or 0),
        }
    )
    plan["query_plan_fingerprint"] = _hash(plan)
    return plan


def build_campaign_final_query_plan(
    *,
    base_query_plan: Mapping[str, Any],
    round_query_plans: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    plans = tuple(dict(item) for item in round_query_plans)
    if not plans:
        raise KernelError(
            "RETRIEVAL_CAMPAIGN_EMPTY",
            "final retrieval ranking requires at least the frozen round-zero plan",
        )
    boundary = dict(base_query_plan.get("accepted_boundary") or {})
    cutoff = str(base_query_plan.get("candidate_projection_cutoff") or "")
    if not cutoff or any(
        dict(item.get("accepted_boundary") or {}) != boundary
        or str(item.get("candidate_projection_cutoff") or "") != cutoff
        for item in plans
    ):
        raise KernelError(
            "RETRIEVAL_CAMPAIGN_IDENTITY_DRIFT",
            "retrieval rounds changed the frozen accepted boundary or projection cutoff",
        )
    plan = {
        key: value
        for key, value in dict(base_query_plan).items()
        if key != "query_plan_fingerprint"
    }
    plan.update(
        {
            "queries": _ordered_unique(
                str(query)
                for item in plans
                for query in item.get("queries") or ()
                if str(query)
            ),
            "entity_ids": _union_plan_ids(plans, "entity_ids"),
            "character_ids": _union_plan_ids(plans, "character_ids"),
            "relationship_ids": _union_plan_ids(plans, "relationship_ids"),
            "arc_plan_version_ids": _union_plan_ids(plans, "arc_plan_version_ids"),
            "obligation_ids": _union_plan_ids(plans, "obligation_ids"),
            "temporal_range": {
                "from_chapter": min(
                    int(dict(item.get("temporal_range") or {}).get("from_chapter") or 0)
                    for item in plans
                ),
                "to_chapter": max(
                    int(dict(item.get("temporal_range") or {}).get("to_chapter") or 0)
                    for item in plans
                ),
            },
            "retrieval_round_query_fingerprints": [
                str(item.get("query_plan_fingerprint") or "") for item in plans
            ],
        }
    )
    plan["postgresql_fts_query"] = " ".join(plan["queries"])
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
    temporal_range = dict(query_plan.get("temporal_range") or {})
    temporal_from = int(temporal_range.get("from_chapter") or 0)
    temporal_to = int(
        temporal_range.get("to_chapter")
        if temporal_range.get("to_chapter") is not None
        else boundary
    )
    if temporal_from < 0 or temporal_to < temporal_from or temporal_to > boundary:
        raise KernelError(
            "RETRIEVAL_DISCOVERY_TEMPORAL_SCOPE_INVALID",
            "retrieval discovery temporal scope must stay within the accepted boundary",
        )
    limit = min(256, max(1, int(query_plan.get("candidate_limit") or 256)))
    policy = str(query_plan.get("semantic_policy") or "FALLBACK_ALLOWED")
    with AuthorityUnitOfWork(database_url) as uow:
        if query_plan.get("writer_projection_version") == "accepted-writer-history.v2":
            from .retrieval_rebuild import require_clean_writer_indexes
            require_clean_writer_indexes(uow.cursor, project_id=project_id, book_id=book_id, boundary=boundary)
        frozen_cutoff = str(query_plan.get("candidate_projection_cutoff") or "")
        uow.cursor.execute(
            "SELECT COALESCE(NULLIF(%s, '')::timestamptz, clock_timestamp())",
            [frozen_cutoff],
        )
        cutoff = uow.cursor.fetchone()[0]
        embedding_boundary = "AND projection.evidence->>'retrieval_document_projection_hash'=document.projection_hash AND projection.projection_version LIKE 'accepted-retrieval-embedding-v2:%%'" if query_plan.get("writer_projection_version") == "accepted-writer-history.v2" else ""
        uow.cursor.execute(
            f"""
            WITH eligible AS NOT MATERIALIZED (
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
                  AND document.accepted_from_chapter BETWEEN %s AND %s
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
                  {embedding_boundary}
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
                temporal_from,
                temporal_to,
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
        dependency_trace = None
        if query_plan.get("task_dependency_refs") is not None:
            dependency_documents, dependency_trace = _discover_task_dependencies(
                uow, project_id=project_id, book_id=book_id,
                boundary=boundary, cutoff=cutoff, query_plan=query_plan,
            )
        else:
            dependency_documents = ()
        writer_projections = (
            _load_writer_history_projections(
                uow, project_id=project_id,
                documents=(*(_document_from_row(row) for row in rows), *dependency_documents),
                projection_version=str(query_plan.get("writer_projection_version") or ""),
                preserve_json=query_plan.get("source_json_projection") == "source-json-values.v1",
            )
            if query_plan.get("writer_projection_version") in {WRITER_PROJECTION_VERSION, "accepted-writer-history.v2"}
            else {}
        )
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
    if dependency_trace is not None:
        frozen_query_plan["task_dependency_discovery"] = dependency_trace
        if "task_dependency_discovery" not in query_plan:
            initial_obligations = set(_ids(dependency_trace.get("protected_initial_obligation_ids")))
            coverage = dict(frozen_query_plan.get("coverage_contract") or {})
            required_obligations = set(_ids(dict(coverage.get("required") or {}).get("obligation_ids")))
            protected_initial = initial_obligations & required_obligations
            if protected_initial:
                protected = dict(coverage.get("protected_evidence") or {})
                protected["obligation_ids"] = sorted(set(_ids(protected.get("obligation_ids"))) | protected_initial)
                coverage["protected_evidence"] = protected
                coverage.pop("coverage_contract_fingerprint", None)
                coverage["coverage_contract_fingerprint"] = _hash(coverage)
                frozen_query_plan["coverage_contract"] = coverage
    frozen_query_plan.pop("query_plan_fingerprint", None)
    frozen_query_plan["query_plan_fingerprint"] = _hash(frozen_query_plan)
    documents = tuple(_document_from_row(row) for row in rows)
    if dependency_trace is not None:
        merged = {item["retrieval_document_id"]: item for item in documents}
        for item in dependency_documents:
            identity = item["retrieval_document_id"]
            if identity in merged:
                existing = merged[identity]
                item = {**item, **existing,
                        "candidate_channels": sorted(set(existing["candidate_channels"]) | set(item["candidate_channels"])),
                        "retrieval_reasons": item["retrieval_reasons"],
                        "task_dependency_matched_refs": item["task_dependency_matched_refs"],
                        **({"content_text": item["content_text"], "metadata": item["metadata"]}
                           if item["metadata"].get("task_dependency_projection") else {})}
            merged[identity] = item
        documents = tuple(merged[identity] for identity in sorted(merged))
    documents = tuple(
        {**item, "writer_history_projection": writer_projections[item["source_asset_version_id"]]}
        if item["source_asset_version_id"] in writer_projections else item
        for item in documents
    )
    if query_plan.get("source_json_projection") == "source-json-values.v1":
        documents = _bind_source_json_projections(database_url, project_id=project_id, documents=documents)
    inputs = tuple(
        {
            "asset_version_id": str(item["source_asset_version_id"]),
            "content_hash": str(item["source_content_hash"]),
        }
        for item in documents
    )
    # INVARIANT: one AssetVersion may have multiple memory-layer documents. Operations
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
        ] + (["TASK_DEPENDENCY"] if dependency_trace is not None else []),
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


def _initial_obligation_binding(fact: Mapping[str, Any], source: Mapping[str, Any], boundary: Mapping[str, Any]) -> dict[str, Any]:
    return {"obligation_id": str(fact["state"]["obligation_id"]), "entity_key": str(fact.get("entity_key") or ""),
        "asset_version_id": str(source["asset_version_id"]), "content_hash": str(source["content_hash"]),
        "state_hash": _hash(fact["state"]), "source_event_id": str(fact.get("source_event_id") or ""),
        "source_chapter": 0, "effective_from_chapter": 0, "accepted_through_chapter": boundary["accepted_through_chapter"]}


def _protected_initial_obligation_ids(dependencies: Mapping[str, Any], accepted_boundary: Mapping[str, Any]) -> set[str]:
    required = set(_ids(dependencies.get("required_obligation_ids")))
    bindings = {(str(item.get("asset_version_id") or ""), str(item.get("content_hash") or "")) for item in dependencies.get("source_bindings") or ()}
    protected: set[str] = set()
    for item in dependencies.get("protected_initial_obligations") or ():
        identity = str(item.get("obligation_id") or "")
        if identity not in required:
            continue
        source = str(item.get("asset_version_id") or "")
        content_hash = str(item.get("content_hash") or "")
        if (not source or not content_hash or not item.get("state_hash") or not item.get("entity_key")
            or item.get("source_chapter") != 0 or item.get("effective_from_chapter") != 0
            or item.get("accepted_through_chapter") != accepted_boundary.get("accepted_through_chapter")
            or source != accepted_boundary.get("story_state_asset_version_id") or (source, content_hash) not in bindings):
            raise KernelError("RETRIEVAL_TASK_SOURCE_BINDING_INVALID", "initial obligation requires its exact frozen State version and hash")
        protected.add(identity)
    return protected


def _validate_initial_obligation_sources(
    uow: AuthorityUnitOfWork, *, project_id: str, book_id: str,
    dependencies: Mapping[str, Any], accepted_boundary: Mapping[str, Any],
) -> set[str]:
    from novel_forge.modules.narrative_state import compact_current_state_facts

    protected = _protected_initial_obligation_ids(dependencies, accepted_boundary)
    if not protected:
        return set()
    declared = [item for item in dependencies["protected_initial_obligations"] if item["obligation_id"] in protected]
    uow.cursor.execute(
        """SELECT version.content_hash, version.content, asset.asset_type,
                  version.lifecycle, version.eligibility, version.governance
        FROM authority_asset_version version JOIN authority_asset asset ON asset.asset_id=version.asset_id
        WHERE version.asset_version_id=%s AND asset.project_id=%s""",
        [accepted_boundary["story_state_asset_version_id"], project_id],
    )
    row = uow.cursor.fetchone()
    if (row is None or row[2] != "story_state_snapshot" or row[3] not in {"ACTIVE", "SUPERSEDED"}
        or row[4] != "ELIGIBLE" or row[5] != "CLEAR" or any(item["content_hash"] != row[0] for item in declared)):
        raise KernelError("RETRIEVAL_TASK_SOURCE_BINDING_INVALID", "initial obligation source is not the exact eligible frozen State")
    content = dict(row[1])
    if (content.get("project_id") != project_id or content.get("book_id") != book_id
        or content.get("accepted_through_chapter") != accepted_boundary.get("accepted_through_chapter")):
        raise KernelError("RETRIEVAL_TASK_SOURCE_BINDING_INVALID", "initial obligation State changed its frozen scope or boundary")
    original = [entry for entry in content.get("current_state", {}).get("narrative_obligation", ())
                if provider_visible_state(entry) and entry.get("source_chapter") == 0 and entry.get("effective_from_chapter") == 0]
    facts = compact_current_state_facts({**content, "current_state": {"narrative_obligation": original}})
    actual = [_initial_obligation_binding(fact, {"asset_version_id": accepted_boundary["story_state_asset_version_id"], "content_hash": row[0]}, accepted_boundary) for fact in facts if provider_visible_state(fact)]
    if any(item not in actual for item in declared):
        raise KernelError("RETRIEVAL_TASK_SOURCE_BINDING_INVALID", "declared initial obligation does not match its original compact State and provenance")
    return protected


def _obligation_accepted_lineage(
    uow: AuthorityUnitOfWork, *, project_id: str, book_id: str,
    boundary: int, accepted_boundary: Mapping[str, Any], require_frozen: bool = False,
) -> str | None:
    state = str(accepted_boundary.get("story_state_asset_version_id") or "")
    canon = str(accepted_boundary.get("canon_snapshot_asset_version_id") or "")
    if not state and not canon:
        if require_frozen:
            raise KernelError("RETRIEVAL_TASK_SOURCE_BINDING_INVALID", "bound obligation sources require a frozen accepted State and Canon frontier")
        return None
    if not state or not canon:
        raise KernelError("RETRIEVAL_TASK_SOURCE_BINDING_INVALID", "obligation discovery requires both frozen accepted State and Canon")
    uow.cursor.execute(
        """
        SELECT DISTINCT revision.book_run_id
        FROM authority_narrative_reality_revision revision
        JOIN authority_book_chapter_acceptance accepted ON accepted.acceptance_id=revision.acceptance_id
        JOIN authority_book_narrative_projection_set projection ON projection.projection_set_id=revision.projection_set_id
        WHERE revision.project_id=%s AND revision.book_id=%s AND revision.chapter_number=%s
          AND revision.state_version_id=%s AND revision.canon_version_id=%s
          AND accepted.status='COMMITTED' AND projection.status='COMPLETE'
          AND accepted.chapter_outcome_asset_version_id=revision.outcome_version_id
          AND accepted.story_state_asset_version_id=revision.state_version_id
          AND accepted.canon_snapshot_asset_version_id=revision.canon_version_id
          AND accepted.longform_projection_set_id=revision.projection_set_id
        """,
        [project_id, book_id, boundary, state, canon],
    )
    rows = uow.cursor.fetchall()
    if len(rows) != 1:
        raise KernelError("RETRIEVAL_TASK_SOURCE_BINDING_INVALID", "frozen accepted State and Canon do not identify one exact source lineage")
    return str(rows[0][0])


def _discover_obligation_dependencies(
    uow: AuthorityUnitOfWork, *, project_id: str, book_id: str,
    boundary: int, cutoff: Any, obligation_ids: set[str], accepted_boundary: Mapping[str, Any], require_frozen: bool = False,
) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]]]:
    if not obligation_ids:
        return {}, {}
    lineage = _obligation_accepted_lineage(uow, project_id=project_id, book_id=book_id, boundary=boundary, accepted_boundary=accepted_boundary, require_frozen=require_frozen)
    uow.cursor.execute(
        """
        WITH eligible AS NOT MATERIALIZED (
            SELECT document.*, version.content_hash AS source_content_hash,
                   version.lifecycle AS source_lifecycle, version.eligibility AS source_eligibility,
                   version.governance AS source_governance,
                   version.content AS source_content
            FROM authority_narrative_retrieval_document document
            JOIN authority_asset_version version ON version.asset_version_id=document.source_asset_version_id
            JOIN authority_asset asset ON asset.asset_id=version.asset_id
            WHERE document.project_id=%s AND document.book_id=%s AND document.created_at<=%s
              AND document.accepted_from_chapter<=%s
              AND (document.accepted_to_chapter IS NULL OR document.accepted_to_chapter>=%s)
              AND asset.project_id=document.project_id AND asset.asset_type='chapter_outcome'
              AND document.source_artifact_type='chapter_outcome' AND document.memory_layer='L6'
              AND (%s::text IS NULL OR EXISTS (
                  SELECT 1 FROM authority_book_acceptance_lineage(%s) accepted
                  WHERE accepted.chapter_outcome_asset_version_id=document.source_asset_version_id
                    AND accepted.chapter_number=document.accepted_from_chapter
              ))
        ), events AS (
            SELECT document.retrieval_document_id, event.value AS event,
                   event.ordinality AS event_ordinal, ref.value AS obligation_id,
                   document.accepted_from_chapter AS source_chapter
            FROM eligible document CROSS JOIN LATERAL jsonb_array_elements(
                CASE WHEN jsonb_typeof(document.source_content->'state_events')='array'
                     THEN document.source_content->'state_events' ELSE '[]'::jsonb END
            ) WITH ORDINALITY event(value,ordinality)
            JOIN unnest(%s::text[]) ref(value) ON ref.value=event.value->'mutation'->'payload'->>'obligation_id'
            WHERE event.value->>'state_kind'='narrative_obligation'
              AND event.value->'coordinate'->>'source_chapter'=document.accepted_from_chapter::text
        ), boundaries AS (
            SELECT obligation_id, min(source_chapter) AS first_chapter, max(source_chapter) AS latest_chapter
            FROM events GROUP BY obligation_id
        ) SELECT document.retrieval_document_id, document.source_asset_version_id,
                 document.source_artifact_type, document.accepted_from_chapter, document.accepted_to_chapter,
                 document.memory_layer, document.content_text, document.entity_ids, document.relationship_ids,
                 document.character_ids, document.arc_plan_version_ids, document.obligation_ids,
                 document.temporal_coordinate, document.metadata, document.source_content_hash,
                 document.projection_hash, 0::double precision, '[]'::jsonb, '', '', 0, '', '', '',
                 ARRAY['TASK_DEPENDENCY']::text[], events.event, events.event_ordinal,
                 events.obligation_id, events.source_chapter=boundaries.first_chapter,
                 events.source_chapter=boundaries.latest_chapter,
                 document.source_content->>'accepted_draft_asset_version_id',
                 document.source_lifecycle, document.source_eligibility, document.source_governance
          FROM events JOIN eligible document USING(retrieval_document_id)
          JOIN boundaries USING(obligation_id)
          WHERE events.source_chapter=boundaries.first_chapter OR events.source_chapter=boundaries.latest_chapter
          ORDER BY events.obligation_id, document.accepted_from_chapter, events.event_ordinal
          LIMIT %s
        """,
        [project_id, book_id, cutoff, boundary, boundary, lineage, lineage, sorted(obligation_ids), _TASK_DEPENDENCY_REF_LIMIT * 2 + 1],
    )
    documents: dict[str, dict[str, Any]] = {}
    resolved: dict[str, set[str]] = {identity: set() for identity in obligation_ids}
    selected_events: dict[str, list[dict[str, Any]]] = {}
    prose_bindings: dict[str, set[str]] = {}
    rows = uow.cursor.fetchall()
    if len(rows) > _TASK_DEPENDENCY_REF_LIMIT * 2:
        raise KernelError("RETRIEVAL_TASK_DEPENDENCY_LIMIT", "obligation boundary events exceed the bounded discovery contract")
    endpoints = {obligation: {event["event_id"] for event in historical_endpoints([row[25] for row in rows if row[27] == obligation])}
                 for obligation in obligation_ids}
    for row in rows:
        if row[25]["event_id"] not in endpoints[str(row[27])]:
            continue
        document = documents.setdefault(str(row[0]), _document_from_row(row))
        event = dict(row[25])
        obligation = str(row[27])
        if (row[31] not in {"ACTIVE", "SUPERSEDED"} or row[32] != "ELIGIBLE" or row[33] != "CLEAR"
            or event.get("provider_visibility") == "INTERNAL_QUALITY_ONLY"
            or event["mutation"]["payload"].get("provider_visibility") == "INTERNAL_QUALITY_ONLY"):
            raise KernelError("RETRIEVAL_TASK_DEPENDENCY_UNAVAILABLE", "required obligation endpoint is outside the eligible Provider source scope")
        if not event.get("event_id") or not row[30]:
            raise KernelError("RETRIEVAL_TASK_DEPENDENCY_UNAVAILABLE", "required obligation event lacks its original accepted source identity")
        resolved[obligation].add(document["retrieval_document_id"])
        prose_bindings.setdefault(str(row[30]), set()).add(obligation)
        selected_events.setdefault(document["retrieval_document_id"], []).append({"ordinal": int(row[26]) - 1, "event": event})
        document["retrieval_reasons"] = sorted({
            *document.get("retrieval_reasons", ()), "required_task_dependency",
            *(("required_dependency_planting",) if row[28] else ()),
            *(("required_dependency_advance",) if row[29] else ()),
        })
    if any(not identities for identities in resolved.values()):
        raise KernelError("RETRIEVAL_TASK_DEPENDENCY_UNAVAILABLE", "a required obligation has no exact accepted planting or advance")
    for identity, rows in selected_events.items():
        document = documents[identity]
        unique = {str(row["event"]["event_id"]): row for row in rows}
        events = [unique[key]["event"] for key in sorted(unique)]
        content = {"state_events": events}
        document["content_text"] = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        document["task_dependency_matched_refs"] = sorted(unique)
        document["metadata"] = {
            **document["metadata"],
            "structured_facts": [{"state_kind": "narrative_obligation", "entity_key": event["identity"]["entity_key"],
                                  "source_event_id": event["event_id"], "source_chapter": event["coordinate"]["source_chapter"],
                                  "state": dict(event["mutation"]["payload"])} for event in events],
            "task_dependency_projection": {"contract_version": "obligation-event-projection-v1",
                "source_asset_version_id": document["source_asset_version_id"], "source_content_hash": document["source_content_hash"],
                "accepted_lineage_book_run_id": lineage,
                "source_projection_hash": document["projection_hash"], "event_ids": sorted(unique),
                "event_ordinals": [unique[key]["ordinal"] for key in sorted(unique)], "content_hash": _hash(content)},
        }
    uow.cursor.execute(
        """
        SELECT document.retrieval_document_id, document.source_asset_version_id,
               document.source_artifact_type, document.accepted_from_chapter, document.accepted_to_chapter,
               document.memory_layer, document.content_text, document.entity_ids, document.relationship_ids,
               document.character_ids, document.arc_plan_version_ids, document.obligation_ids,
               document.temporal_coordinate, document.metadata, version.content_hash,
               document.projection_hash, 0::double precision, '[]'::jsonb, '', '', 0, '', '', '',
               ARRAY['TASK_DEPENDENCY']::text[]
        FROM authority_narrative_retrieval_document document
        JOIN authority_asset_version version ON version.asset_version_id=document.source_asset_version_id
        JOIN authority_asset asset ON asset.asset_id=version.asset_id
        WHERE document.project_id=%s AND document.book_id=%s AND document.created_at<=%s
          AND document.accepted_from_chapter<=%s
          AND (document.accepted_to_chapter IS NULL OR document.accepted_to_chapter>=%s)
          AND version.lifecycle IN ('ACTIVE','SUPERSEDED') AND version.eligibility='ELIGIBLE' AND version.governance='CLEAR'
          AND asset.project_id=document.project_id AND asset.asset_type='best_draft_candidate'
          AND document.source_artifact_type='best_draft_candidate' AND document.memory_layer='L0'
          AND document.source_asset_version_id=ANY(%s::text[])
        ORDER BY document.source_asset_version_id, document.retrieval_document_id
        """,
        [project_id, book_id, cutoff, boundary, boundary, sorted(prose_bindings)],
    )
    found_prose: set[str] = set()
    for row in uow.cursor.fetchall():
        document = _document_from_row(row)
        source = document["source_asset_version_id"]
        found_prose.add(source)
        document["retrieval_reasons"] = ["required_task_dependency", "required_obligation_original_prose"]
        documents[document["retrieval_document_id"]] = document
        for obligation in prose_bindings[source]:
            resolved[obligation].add(document["retrieval_document_id"])
    if set(prose_bindings) - found_prose:
        raise KernelError("RETRIEVAL_TASK_DEPENDENCY_UNAVAILABLE", "required obligation original prose is unavailable at the frozen accepted boundary")
    return documents, {identity: sorted(documents) for identity, documents in sorted(resolved.items())}


def _discover_task_dependencies(
    uow: AuthorityUnitOfWork, *, project_id: str, book_id: str,
    boundary: int, cutoff: Any, query_plan: Mapping[str, Any],
) -> tuple[tuple[dict[str, Any], ...], dict[str, Any]]:
    dependencies = dict(query_plan.get("task_dependency_refs") or {})
    if dependencies.get("contract_version") != _TASK_DEPENDENCY_CONTRACT:
        raise KernelError("RETRIEVAL_TASK_DEPENDENCY_CONTRACT_INVALID", "task dependency discovery requires its versioned frozen contract")
    required = set(_ids(dependencies.get("required_refs")))
    obligations = set(_ids(dependencies.get("required_obligation_ids")))
    if len(required) + len(obligations) > _TASK_DEPENDENCY_REF_LIMIT:
        raise KernelError("RETRIEVAL_TASK_DEPENDENCY_LIMIT", "required task dependency set exceeds the bounded discovery contract")
    protected = set(_ids(dependencies.get("protected_fact_aliases")))
    initial_obligations = _validate_initial_obligation_sources(uow, project_id=project_id, book_id=book_id,
        dependencies=dependencies, accepted_boundary=dict(query_plan.get("accepted_boundary") or {}))
    documents, obligation_documents = _discover_obligation_dependencies(
        uow, project_id=project_id, book_id=book_id, boundary=boundary, cutoff=cutoff, obligation_ids=obligations - initial_obligations,
        accepted_boundary=dict(query_plan.get("accepted_boundary") or {}),
        require_frozen=bool(dependencies.get("source_bindings")),
    )
    for document in documents.values():
        document.setdefault("task_dependency_matched_refs", [])
        for fact in document["metadata"].get("structured_facts") or ():
            required.update(_ids(dict(dict(fact.get("state") or {}).get("world_transition") or {}).get("cause_refs")))
    pending = set(required)
    resolved: dict[str, list[str]] = {}
    rounds = 0
    while pending:
        rounds += 1
        if rounds > _TASK_DEPENDENCY_CLOSURE_LIMIT or len(required) + len(obligations) > _TASK_DEPENDENCY_REF_LIMIT:
            raise KernelError("RETRIEVAL_TASK_DEPENDENCY_LIMIT", "required causal closure exceeds the bounded discovery contract")
        refs = sorted(pending)
        pending.clear()
        uow.cursor.execute(
            """
            WITH eligible AS NOT MATERIALIZED (
                SELECT document.*, version.content_hash AS source_content_hash
                FROM authority_narrative_retrieval_document AS document
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=document.source_asset_version_id
                WHERE document.project_id=%s AND document.book_id=%s
                  AND document.created_at<=%s
                  AND document.accepted_from_chapter<=%s
                  AND (document.accepted_to_chapter IS NULL
                       OR document.accepted_to_chapter>=%s)
                  AND version.lifecycle IN ('ACTIVE','SUPERSEDED')
                  AND version.eligibility='ELIGIBLE' AND version.governance='CLEAR'
            ), matches AS (
                SELECT ref.value AS dependency_ref, document.retrieval_document_id,
                       ROW_NUMBER() OVER (PARTITION BY ref.value
                         ORDER BY document.accepted_from_chapter,
                                  document.retrieval_document_id) AS planting_rank,
                       ROW_NUMBER() OVER (PARTITION BY ref.value
                         ORDER BY document.accepted_from_chapter DESC,
                                  document.retrieval_document_id) AS advance_rank
                FROM unnest(%s::TEXT[]) AS ref(value)
                JOIN eligible AS document ON (
                    document.metadata->'fact_ids' ? ref.value OR EXISTS (
                        SELECT 1 FROM jsonb_array_elements(
                            CASE WHEN jsonb_typeof(document.metadata->'structured_facts')='array'
                                 THEN document.metadata->'structured_facts' ELSE '[]'::jsonb END
                        ) AS fact(value)
                        WHERE ref.value IN (
                            fact.value->>'source_event_id', fact.value->>'source_identity',
                            fact.value->>'fact_id', fact.value->>'proposition_id',
                            fact.value->'state'->>'fact_id', fact.value->'state'->>'proposition_id'
                        )
                    )
                )
            )
            SELECT document.retrieval_document_id, document.source_asset_version_id,
                   document.source_artifact_type, document.accepted_from_chapter,
                   document.accepted_to_chapter, document.memory_layer,
                   document.content_text, document.entity_ids, document.relationship_ids,
                   document.character_ids, document.arc_plan_version_ids,
                   document.obligation_ids, document.temporal_coordinate,
                   document.metadata, document.source_content_hash,
                   document.projection_hash, 0::DOUBLE PRECISION,
                   '[]'::jsonb, '', '', 0, '', '', '', ARRAY['TASK_DEPENDENCY']::TEXT[],
                   matches.dependency_ref, matches.planting_rank=1, matches.advance_rank=1
            FROM matches JOIN eligible AS document USING(retrieval_document_id)
            WHERE matches.planting_rank=1 OR matches.advance_rank=1
            ORDER BY matches.dependency_ref, document.accepted_from_chapter,
                     document.retrieval_document_id
            """,
            [project_id, book_id, cutoff, boundary, boundary, refs],
        )
        rows = uow.cursor.fetchall()
        for ref in refs:
            matching_rows = [row for row in rows if str(row[25]) == ref]
            if not matching_rows and ref not in protected:
                raise KernelError("RETRIEVAL_TASK_DEPENDENCY_UNAVAILABLE", "an exact required dependency is unavailable at the frozen accepted boundary")
            resolved[ref] = sorted({str(row[0]) for row in matching_rows})
            for row in matching_rows:
                document = _document_from_row(row)
                identity = document["retrieval_document_id"]
                previous = documents.get(identity, {})
                if dict(previous.get("metadata") or {}).get("task_dependency_projection"):
                    document.update({"content_text": previous["content_text"], "metadata": previous["metadata"]})
                document["task_dependency_matched_refs"] = sorted({*previous.get("task_dependency_matched_refs", ()), ref})
                document["retrieval_reasons"] = sorted({
                    *previous.get("retrieval_reasons", ()), "required_task_dependency",
                    *( ("required_dependency_planting",) if row[26] else () ),
                    *( ("required_dependency_advance",) if row[27] else () ),
                })
                documents[identity] = document
                for fact in document["metadata"].get("structured_facts") or ():
                    if not isinstance(fact, Mapping) or ref not in fact_aliases(fact):
                        continue
                    transition = dict(dict(fact.get("state") or {}).get("world_transition") or {})
                    for cause in _ids(transition.get("cause_refs")):
                        if cause not in required:
                            required.add(cause)
                            pending.add(cause)
    return tuple(documents[identity] for identity in sorted(documents)), {
        "contract_version": "task-dependency-discovery-v1",
        "required_refs": sorted(required),
        "protected_resolved_refs": sorted(required & protected),
        "matched_documents_by_ref": resolved,
        **({"required_obligation_ids": sorted(obligations), "matched_documents_by_obligation": obligation_documents}
           if "required_obligation_ids" in dependencies else {}),
        **({"protected_initial_obligation_ids": sorted(initial_obligations), "protected_initial_obligation_sources": [item for item in dependencies["protected_initial_obligations"] if item["obligation_id"] in initial_obligations]}
           if "protected_initial_obligations" in dependencies else {}),
        "closure_rounds": rounds,
        "required_document_count": len(documents),
    }


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
            embedding_boundary = "AND projection.evidence->>'retrieval_document_projection_hash'=document.projection_hash" if query_plan.get("writer_projection_version") == "accepted-writer-history.v2" else ""
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
                  {embedding_boundary}
                  AND projection.embedding_vector IS NOT NULL
                  AND projection.embedding_model=%s
                  AND projection.embedding_dimensions=%s
                  AND projection.projection_version LIKE %s
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
                    SEMANTIC_PROJECTION_VERSION + ":%" if query_plan.get("writer_projection_version") == "accepted-writer-history.v2" else "accepted-retrieval-embedding-v1",
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
                clean_projection=query_plan.get("writer_projection_version") == "accepted-writer-history.v2",
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
    raw: Mapping[str, Any], *, model: str, dimensions: int, clean_projection: bool = False
) -> dict[str, Any]:
    document = dict(raw)
    document["candidate_channels"] = sorted(
        {str(item) for item in document.get("candidate_channels") or ()}
    )
    if document.get("embedding") and (
        not model
        or str(document.get("embedding_model") or "") != model
        or int(document.get("embedding_dimensions") or 0) != dimensions
        or (not str(document.get("embedding_projection_version") or "").startswith(SEMANTIC_PROJECTION_VERSION + ":") if clean_projection else str(document.get("embedding_projection_version") or "") != "accepted-retrieval-embedding-v1")
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
    task_scoped = query_plan.get("task_dependency_refs") is not None
    all_ranked = hybrid_retrieve(
        HybridRetrievalQuery(
            text=str(query_plan.get("postgresql_fts_query") or ""),
            accepted_through_chapter=boundary,
            entity_ids=tuple(_ids(query_plan.get("entity_ids"))),
            relationship_ids=tuple(_ids(query_plan.get("relationship_ids"))),
            character_ids=tuple(_ids(query_plan.get("character_ids"))),
            arc_plan_version_ids=tuple(_ids(query_plan.get("arc_plan_version_ids"))),
            obligation_ids=tuple(_ids(query_plan.get("obligation_ids"))),
            query_embedding=query_vector,
            limit=len(frozen) if task_scoped else int(query_plan.get("result_limit") or 24),
        ),
        frozen,
    )
    if task_scoped:
        by_id = {str(item["retrieval_document_id"]): item for item in frozen}
        dependency_trace = dict(query_plan.get("task_dependency_discovery") or {})
        expected_required_ids = {
            str(identity)
            for identities in [*dict(dependency_trace.get("matched_documents_by_ref") or {}).values(),
                               *dict(dependency_trace.get("matched_documents_by_obligation") or {}).values()]
            for identity in identities
        }
        if expected_required_ids - set(by_id):
            raise KernelError("RETRIEVAL_TASK_DEPENDENCY_UNAVAILABLE", "the frozen candidate set omitted an exact required dependency document")
        required_ids = {
            identity for identity, item in by_id.items()
            if "TASK_DEPENDENCY" in item.get("candidate_channels", ())
        } | expected_required_ids
        ranked_ids = {str(item["retrieval_document_id"]) for item in all_ranked}
        if required_ids - ranked_ids:
            raise KernelError("RETRIEVAL_TASK_DEPENDENCY_UNAVAILABLE", "a frozen required dependency no longer satisfies the accepted boundary")
        required_documents = []
        optional_documents = []
        for item in all_ranked:
            identity = str(item["retrieval_document_id"])
            if identity in required_ids:
                required_documents.append({**item, "retrieval_reasons": sorted({
                    *item.get("retrieval_reasons", ()),
                    *by_id[identity].get("retrieval_reasons", ()),
                    "required_task_dependency",
                })})
            else:
                optional_documents.append(item)
        ranked = tuple(required_documents + optional_documents[:int(query_plan.get("result_limit") or 24)])
        dependencies = dict(query_plan.get("task_dependency_refs") or {})
        required_refs = set(_ids(dependencies.get("required_refs"))) | set(_ids(dependency_trace.get("required_refs")))
        available_refs = set(_ids(dependencies.get("protected_fact_aliases")))
        for item in ranked:
            metadata = dict(item.get("metadata") or {})
            available_refs.update(_ids(metadata.get("fact_ids")))
            for fact in metadata.get("structured_facts") or ():
                if isinstance(fact, Mapping) and fact.get("provider_visibility") != "INTERNAL_QUALITY_ONLY":
                    available_refs.update(fact_aliases(fact))
        if required_refs - available_refs:
            raise KernelError("RETRIEVAL_TASK_DEPENDENCY_UNAVAILABLE", "ranked task evidence omitted a required exact dependency alias")
        required_obligations = set(_ids(dependencies.get("required_obligation_ids")))
        initial_obligations = _protected_initial_obligation_ids(dependencies, dict(query_plan.get("accepted_boundary") or {}))
        initial_sources = [item for item in dependencies.get("protected_initial_obligations") or () if item["obligation_id"] in initial_obligations]
        if (initial_obligations != set(_ids(dependency_trace.get("protected_initial_obligation_ids")))
            or initial_sources != list(dependency_trace.get("protected_initial_obligation_sources") or ())):
            raise KernelError("RETRIEVAL_TASK_DEPENDENCY_UNAVAILABLE", "initial obligation coverage changed its frozen host source evidence")
        resolved_obligations = initial_obligations |  {identity for identity, documents in dict(dependency_trace.get("matched_documents_by_obligation") or {}).items() if documents}
        if required_obligations - resolved_obligations:
            raise KernelError("RETRIEVAL_TASK_DEPENDENCY_UNAVAILABLE", "required obligations lack frozen host endpoint discovery evidence")
        available_obligations = initial_obligations | {
            str(fact["state"]["obligation_id"])
            for item in ranked for fact in dict(item.get("metadata") or {}).get("structured_facts", ())
            if isinstance(fact, Mapping) and fact.get("state_kind") == "narrative_obligation"
            and (fact.get("state") or {}).get("obligation_id") and fact.get("provider_visibility") != "INTERNAL_QUALITY_ONLY"
        }
        if required_obligations - available_obligations:
            raise KernelError("RETRIEVAL_TASK_DEPENDENCY_UNAVAILABLE", "ranked task evidence omitted a required exact obligation event")
    else:
        ranked = all_ranked
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
    projection_version = str(query_plan.get("writer_projection_version") or "")
    if projection_version not in {"", WRITER_PROJECTION_VERSION, "accepted-writer-history.v2"}:
        raise KernelError("WRITER_HISTORY_PROJECTION_UNSUPPORTED", "frozen retrieval uses an unsupported Writer projection")
    selected = [_selected_document(item, preserve_text=task_scoped, clean_history=bool(projection_version), projection_version=projection_version, preserve_json=query_plan.get("source_json_projection") == "source-json-values.v1") for item in ranked]
    result = {
        "type": "RetrievalResult",
        "contract_version": "chapter-retrieval-result-v6" if task_scoped else "chapter-retrieval-result-v5",
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


def _load_writer_history_projections(
    uow: AuthorityUnitOfWork, *, project_id: str, documents: Iterable[Mapping[str, Any]], projection_version: str = WRITER_PROJECTION_VERSION, preserve_json: bool = False,
) -> dict[str, dict[str, str]]:
    bindings: dict[str, tuple[str, str]] = {}
    for item in documents:
        if item.get("source_artifact_type") not in WRITER_PROSE_TYPES:
            continue
        identity = str(item["source_asset_version_id"])
        binding = (str(item["source_content_hash"]), str(item["source_artifact_type"]))
        if identity in bindings and bindings[identity] != binding:
            raise KernelError("WRITER_HISTORY_SOURCE_BINDING_INVALID", "retrieval documents disagree on their exact prose source")
        bindings[identity] = binding
    if not bindings:
        return {}
    uow.cursor.execute(
        """SELECT version.asset_version_id, version.content_hash, version.content, asset.asset_type
        FROM authority_asset_version version JOIN authority_asset asset ON asset.asset_id=version.asset_id
        WHERE asset.project_id=%s AND version.asset_version_id=ANY(%s::text[])
          AND version.lifecycle IN ('ACTIVE','SUPERSEDED')
          AND version.eligibility='ELIGIBLE' AND version.governance='CLEAR'""",
        [project_id, sorted(bindings)],
    )
    projections = {}
    for identity, content_hash, content, artifact_type in uow.cursor.fetchall():
        if bindings.get(identity) != (content_hash, artifact_type) or not isinstance(content, Mapping):
            raise KernelError("WRITER_HISTORY_SOURCE_BINDING_INVALID", "accepted prose source differs from its frozen retrieval binding")
        projections[identity] = bind_writer_history_source(
            content, source_asset_version_id=identity, source_content_hash=content_hash,
            source_artifact_type=artifact_type, preserve_json=preserve_json,
        )
        if projection_version == "accepted-writer-history.v2":
            from .story_projection import story_history
            clean_text = story_history(json.dumps(content, ensure_ascii=False), physical_type=artifact_type, preserve_json=preserve_json)
            projections[identity].update(version=projection_version, text=clean_text,
                                         text_fingerprint="sha256:" + hashlib.sha256(clean_text.encode()).hexdigest())
    if set(projections) != set(bindings):
        raise KernelError("WRITER_HISTORY_SOURCE_BINDING_INVALID", "an exact eligible Writer history source is unavailable")
    return projections


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


def _selected_document(item: Mapping[str, Any], *, preserve_text: bool = False, clean_history: bool = False, projection_version: str = "", preserve_json: bool = False) -> dict[str, Any]:
    content = str(item.get("content_text") or "")
    json_binding = item.get("source_json_projection")
    if preserve_json:
        _validate_source_json_projection(item, json_binding)
        item = {**item, "content_text": json_binding["text"], "metadata": json_binding["metadata"]}
        content = json_binding["text"]
    if clean_history:
        binding = item.get("writer_history_projection")
        checked_item = item
        if isinstance(binding, Mapping) and binding.get("version") == "accepted-writer-history.v2":
            checked_item = {**item, "writer_history_projection": {**binding, "version": WRITER_PROJECTION_VERSION}}
        content = project_writer_retrieval_history(checked_item, preserve_json=preserve_json)
        if projection_version == "accepted-writer-history.v2":
            from .story_projection import story_history, visible_business_data
            content = story_history(str(binding["text"]) if isinstance(binding, Mapping) else str(item.get("content_text") or ""), physical_type=str(item.get("source_artifact_type") or ""), preserve_json=preserve_json)
            item = {**item, "metadata": visible_business_data(dict(item.get("metadata") or {}), stage="draft", history=True, preserve_json=preserve_json)}
        else:
            item = {**item, "metadata": provider_visible_data(dict(item.get("metadata") or {}))}
    maximum = len(content) if preserve_text or clean_history else 4_000
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
            *( ("task_dependency_matched_refs",) if preserve_text else () ),
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
            **({"source_json_projection": dict(json_binding)} if preserve_json else {}),
            **({"writer_projection_version": projection_version or WRITER_PROJECTION_VERSION,
                "source_text_fingerprint": "sha256:" + hashlib.sha256(str(item.get("content_text") or "").encode()).hexdigest(),
                **({"writer_source_text_fingerprint": item["writer_history_projection"]["source_text_fingerprint"]}
                   if item.get("writer_history_projection") else {})}
               if clean_history else {}),
            "method": "deterministic_bounded_extract" if compressed else "none",
            "input_characters": len(content),
            "output_characters": min(maximum, len(content)),
            "content_fingerprint": "sha256:"
            + hashlib.sha256(content.encode()).hexdigest(),
        },
    }


def _ids(values: Any) -> list[str]:
    return sorted({str(item) for item in values or () if str(item)})


def _expanded_ids(
    base: Mapping[str, Any], queries: Iterable[Mapping[str, Any]], field: str
) -> list[str]:
    return sorted(
        {
            *_ids(base.get(field)),
            *(
                identity
                for query in queries
                for identity in _ids(dict(query.get("selectors") or {}).get(field))
            ),
        }
    )


def _union_plan_ids(plans: Iterable[Mapping[str, Any]], field: str) -> list[str]:
    return sorted({identity for plan in plans for identity in _ids(plan.get(field))})


def _ordered_unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


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
    "build_task_dependency_refs",
    "build_expanded_retrieval_query_plan",
    "build_campaign_final_query_plan",
    "build_retrieval_result",
    "discover_accepted_retrieval_candidates",
    "freeze_retrieval_candidate_union",
    "load_frozen_retrieval_candidate_union",
]


def _bind_source_json_projections(database_url, *, project_id, documents):
    from .story_projection import SOURCE_JSON_PROJECTION, restore_source_json_fields, story_history, visible_business_data
    from novel_forge.modules.narrative_state.reality import narrative_hash

    identities = sorted({item["source_asset_version_id"] for item in documents})
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("SET TRANSACTION READ ONLY")
        uow.cursor.execute("""SELECT version.asset_version_id,version.content_hash,version.content,asset.asset_type
            FROM authority_asset_version version JOIN authority_asset asset USING(asset_id)
            WHERE asset.project_id=%s AND version.asset_version_id=ANY(%s::text[])
              AND version.lifecycle IN ('ACTIVE','SUPERSEDED') AND version.eligibility='ELIGIBLE' AND version.governance='CLEAR'""", [project_id, identities])
        sources = {row[0]: row[1:] for row in uow.cursor.fetchall()}
    result = []
    for item in documents:
        source = sources.get(item["source_asset_version_id"])
        if not source or source[0] != item["source_content_hash"] or source[2] != item["source_artifact_type"]:
            raise KernelError("CONTEXT_SOURCE_JSON_BINDING_CHANGED", "JSON projection requires its exact eligible original AssetVersion")
        if source[2] in WRITER_PROSE_TYPES:
            text, fields = story_history(json.dumps(source[1], ensure_ascii=False), physical_type=source[2], preserve_json=True), []
        else:
            text = story_history(str(item["content_text"]), physical_type=source[2], preserve_json=True)
            text, fields = restore_source_json_fields(text, source[1])
        metadata_text = visible_business_data(json.dumps(item.get("metadata") or {}, ensure_ascii=False), stage="draft", history=True, preserve_json=True)
        metadata_text, metadata_fields = restore_source_json_fields(metadata_text, source[1])
        metadata = visible_business_data(json.loads(metadata_text), stage="draft", history=True, preserve_json=True)
        binding = {"version": SOURCE_JSON_PROJECTION, "source_asset_version_id": item["source_asset_version_id"],
            "source_content_hash": source[0], "source_artifact_type": source[2], "source_projection_hash": item["projection_hash"],
            "input_text_hash": narrative_hash(item["content_text"]), "text": text, "text_hash": narrative_hash(text),
            "metadata": metadata, "metadata_hash": narrative_hash(metadata), "field_bindings": fields, "metadata_field_bindings": metadata_fields}
        result.append({**item, "source_json_projection": binding})
    return tuple(result)


def _validate_source_json_projection(item, binding):
    from .story_projection import SOURCE_JSON_PROJECTION
    from novel_forge.modules.narrative_state.reality import narrative_hash

    if (not isinstance(binding, Mapping) or binding.get("version") != SOURCE_JSON_PROJECTION
        or any(binding.get(key) != item.get(key) for key in ("source_asset_version_id", "source_content_hash", "source_artifact_type"))
        or binding.get("source_projection_hash") != item.get("projection_hash")
        or binding.get("input_text_hash") != narrative_hash(item.get("content_text"))
        or not isinstance(binding.get("text"), str) or binding.get("text_hash") != narrative_hash(binding["text"])
        or not isinstance(binding.get("metadata"), Mapping) or binding.get("metadata_hash") != narrative_hash(binding["metadata"])):
        raise KernelError("CONTEXT_SOURCE_JSON_BINDING_CHANGED", "frozen original-source JSON projection or its field scope changed")
