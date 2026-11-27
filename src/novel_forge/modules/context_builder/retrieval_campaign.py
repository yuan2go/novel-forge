from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any, Iterable, Mapping

from novel_forge.modules.command_kernel.errors import KernelError


RETRIEVAL_CAMPAIGN_POLICY_VERSION = "coverage-progress-retrieval-campaign-v2"
RETRIEVAL_COVERAGE_CONTRACT_VERSION = "retrieval-coverage-contract-v1"
RETRIEVAL_EXPANSION_CONTRACT_VERSION = "retrieval-expansion-plan-v1"

_COVERAGE_DIMENSIONS = (
    "fact_ids",
    "historical_reference_ids",
    "relationship_ids",
    "arc_plan_version_ids",
    "obligation_ids",
)
_SELECTOR_DIMENSIONS = (
    "entity_ids",
    "character_ids",
    "relationship_ids",
    "arc_plan_version_ids",
    "obligation_ids",
)


@dataclass(frozen=True, slots=True)
class RetrievalCampaignPolicy:
    policy_version: str = RETRIEVAL_CAMPAIGN_POLICY_VERSION
    # COMPATIBILITY: Retired cumulative fields exist only to reproduce frozen v1 fingerprints.
    total_round_limit: int = 3
    additional_round_limit: int = 2
    queries_per_round_limit: int = 4
    total_query_limit: int = 10
    candidates_per_round_limit: int = 256
    total_candidate_limit: int = 768
    provider_call_limit: int = 4
    model_token_limit: int = 4096
    cost_limit: str = "1.00"
    result_limit: int = 24
    fallback_mode: str = "DETERMINISTIC_FALLBACK"

    def __post_init__(self) -> None:
        if (not self.policy_version or not 1 <= self.queries_per_round_limit <= 4
                or not 1 <= self.candidates_per_round_limit <= 256 or self.result_limit != 24
                or self.fallback_mode not in {"DETERMINISTIC_FALLBACK", "FAIL_CLOSED"}):
            raise ValueError("retrieval campaign policy exceeds its per-round scope bounds")

    def execution_policy(self) -> dict[str, Any]:
        return {"policy_version": RETRIEVAL_CAMPAIGN_POLICY_VERSION,
            **{key: getattr(self, key) for key in ("queries_per_round_limit", "candidates_per_round_limit",
                "result_limit", "fallback_mode")}}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) if self.policy_version == "minimum-sufficient-retrieval-campaign-v1" else self.execution_policy()


def build_retrieval_coverage_contract(
    *, intent: Mapping[str, Any], memo: Mapping[str, Any]
) -> dict[str, Any]:
    boundary = dict(intent.get("accepted_boundary") or {})
    if boundary != dict(memo.get("accepted_boundary") or {}):
        raise KernelError(
            "RETRIEVAL_COVERAGE_BOUNDARY_MISMATCH",
            "coverage requires the exact frozen Intent and Memo boundary",
        )
    accepted_through = int(boundary.get("accepted_through_chapter") or 0)
    if accepted_through < 0:
        raise KernelError(
            "RETRIEVAL_COVERAGE_BOUNDARY_INVALID",
            "coverage accepted boundary cannot be negative",
        )
    intent_fingerprint = str(intent.get("intent_fingerprint") or "")
    memo_fingerprint = str(memo.get("memo_fingerprint") or "")
    if not intent_fingerprint or not memo_fingerprint:
        raise KernelError(
            "RETRIEVAL_COVERAGE_IDENTITY_INVALID",
            "coverage requires frozen Intent and Memo fingerprints",
        )

    graph = dict(intent.get("retrieval_graph") or {})
    character_ids = {
        *_ids(graph.get("character_ids")),
        *(
            participant
            for scene in intent.get("scene_plans") or ()
            if isinstance(scene, Mapping)
            for participant in _ids(scene.get("participants"))
        ),
    }
    entity_ids = {*_ids(graph.get("entity_ids")), *character_ids}
    relationship_ids = _ids(graph.get("relationship_ids"))
    arc_ids = {
        str(item.get("arc_plan_version_id") or item.get("arc_id") or "")
        for item in (
            *(intent.get("required_arc_contributions") or ()),
            *(memo.get("arc_actions") or ()),
        )
        if isinstance(item, Mapping)
        and str(item.get("arc_plan_version_id") or item.get("arc_id") or "")
    }
    obligation_ids = {
        str(
            item.get("obligation_id")
            or dict(item.get("state") or {}).get("obligation_id")
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
            or dict(item.get("state") or {}).get("obligation_id")
            or item.get("entity_key")
            or ""
        )
    }
    fact_ids = set(_ids(intent.get("required_long_distance_fact_ids")))
    mission = dict(intent.get("chapter_mission") or {})
    knowledge = dict(mission.get("knowledge_and_disclosure_boundaries") or {})
    for item in knowledge.get("knowledge_boundaries") or ():
        if isinstance(item, Mapping) and bool(
            item.get("retrieval_required") or item.get("evidence_required")
        ):
            identity = str(item.get("fact_id") or item.get("proposition_id") or "")
            if identity:
                fact_ids.add(identity)
    historical: set[str] = set()
    hints: dict[str, str] = {}
    for item in intent.get("explicit_historical_references") or ():
        if not isinstance(item, Mapping):
            continue
        identity = str(item.get("reference_id") or "")
        if not identity:
            continue
        historical.add(identity)
        hint = str(item.get("query_hint") or "").strip()
        if hint:
            hints[f"history:{identity}"] = hint
    for identity in fact_ids:
        hints.setdefault(f"fact:{identity}", identity)

    historical_relationship_ids = relationship_ids if accepted_through > 0 else set()
    historical_arc_ids = arc_ids if accepted_through > 0 else set()
    historical_obligation_ids = obligation_ids if accepted_through > 0 else set()
    required = {
        "fact_ids": sorted(fact_ids),
        "historical_reference_ids": sorted(historical),
        "relationship_ids": sorted(historical_relationship_ids),
        "arc_plan_version_ids": sorted(historical_arc_ids),
        "obligation_ids": sorted(historical_obligation_ids),
    }
    protected_evidence = {
        "fact_ids": [],
        "historical_reference_ids": [],
        "relationship_ids": [],
        "arc_plan_version_ids": sorted(historical_arc_ids),
        "obligation_ids": [],
    }
    selectors = {
        "entity_ids": sorted(entity_ids),
        "character_ids": sorted(character_ids),
        "relationship_ids": sorted(relationship_ids),
        "arc_plan_version_ids": sorted(arc_ids),
        "obligation_ids": sorted(obligation_ids),
    }
    body = {
        "contract_version": RETRIEVAL_COVERAGE_CONTRACT_VERSION,
        "chapter": int(intent.get("chapter") or 0),
        "accepted_boundary": boundary,
        "intent_fingerprint": intent_fingerprint,
        "memo_fingerprint": memo_fingerprint,
        "required": required,
        "protected_evidence": protected_evidence,
        "selectors": selectors,
        "query_hints": dict(sorted(hints.items())),
        "sufficiency_policy": "ALL_REQUIRED_IDENTITIES_OBSERVED",
    }
    return {**body, "coverage_contract_fingerprint": _hash(body)}


def evaluate_retrieval_coverage(
    *, contract: Mapping[str, Any], documents: Iterable[Mapping[str, Any]]
) -> dict[str, Any]:
    boundary = int(
        dict(contract.get("accepted_boundary") or {}).get("accepted_through_chapter")
        or 0
    )
    required = dict(contract.get("required") or {})
    protected = dict(contract.get("protected_evidence") or {})
    observed = {
        dimension: set(_ids(protected.get(dimension)))
        for dimension in _COVERAGE_DIMENSIONS
    }
    if any(
        not observed[dimension].issubset(set(_ids(required.get(dimension))))
        for dimension in _COVERAGE_DIMENSIONS
    ):
        raise KernelError(
            "RETRIEVAL_COVERAGE_PROTECTED_EVIDENCE_INVALID",
            "protected evidence must be a subset of the frozen coverage requirements",
        )
    document_ids: set[str] = set()
    for raw in documents:
        document = dict(raw)
        identity = str(document.get("retrieval_document_id") or "")
        accepted_from = int(document.get("accepted_from_chapter") or 0)
        accepted_to_raw = document.get("accepted_to_chapter")
        accepted_to = int(accepted_to_raw) if accepted_to_raw is not None else None
        if (
            not identity
            or accepted_from > boundary
            or (accepted_to is not None and accepted_to < boundary)
        ):
            raise KernelError(
                "RETRIEVAL_COVERAGE_DOCUMENT_BOUNDARY_INVALID",
                "coverage cannot observe future, stale, or unidentified evidence",
            )
        document_ids.add(identity)
        metadata = dict(document.get("metadata") or {})
        observed["fact_ids"].update(_ids(document.get("fact_ids")))
        observed["fact_ids"].update(_ids(metadata.get("fact_ids")))
        observed["historical_reference_ids"].update(
            _ids(document.get("historical_reference_ids"))
        )
        observed["historical_reference_ids"].update(
            _ids(metadata.get("historical_reference_ids"))
        )
        for fact in metadata.get("structured_facts") or ():
            if isinstance(fact, Mapping):
                fact_id = str(
                    fact.get("fact_id")
                    or fact.get("proposition_id")
                    or dict(fact.get("state") or {}).get("fact_id")
                    or ""
                )
                if fact_id:
                    observed["fact_ids"].add(fact_id)
        for dimension in (
            "relationship_ids",
            "arc_plan_version_ids",
            "obligation_ids",
        ):
            observed[dimension].update(_ids(document.get(dimension)))

    missing = {
        dimension: sorted(set(_ids(required.get(dimension))) - observed[dimension])
        for dimension in _COVERAGE_DIMENSIONS
        if set(_ids(required.get(dimension))) - observed[dimension]
    }
    body = {
        "contract_version": "retrieval-coverage-assessment-v1",
        "coverage_contract_fingerprint": str(
            contract.get("coverage_contract_fingerprint") or ""
        ),
        "accepted_boundary": dict(contract.get("accepted_boundary") or {}),
        "sufficient": not missing,
        "required": {
            dimension: _ids(required.get(dimension))
            for dimension in _COVERAGE_DIMENSIONS
        },
        "protected_evidence": {
            dimension: _ids(protected.get(dimension))
            for dimension in _COVERAGE_DIMENSIONS
        },
        "observed": {
            dimension: sorted(observed[dimension]) for dimension in _COVERAGE_DIMENSIONS
        },
        "missing": missing,
        "evidence_document_ids": sorted(document_ids),
        "decision_owner": "DETERMINISTIC_CONTEXT_POLICY",
    }
    return {**body, "coverage_fingerprint": _hash(body)}


def validate_retrieval_expansion_plan(
    *,
    raw: Mapping[str, Any],
    contract: Mapping[str, Any],
    coverage: Mapping[str, Any],
    policy: RetrievalCampaignPolicy,
    round_number: int,
    prior_query_fingerprints: Iterable[str],
    existing_query_count: int = 0,
    prior_queries: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    if raw.get("contract_version") != RETRIEVAL_EXPANSION_CONTRACT_VERSION:
        raise KernelError(
            "RETRIEVAL_EXPANSION_SCHEMA_INVALID",
            "query expansion output has an unsupported contract version",
        )
    if coverage.get("sufficient") is not False:
        raise KernelError(
            "RETRIEVAL_EXPANSION_NOT_REQUIRED",
            "query expansion cannot run after deterministic sufficiency",
        )
    if type(round_number) is not int or round_number < 1:
        raise KernelError(
            "RETRIEVAL_EXPANSION_ROUND_INVALID",
            "query expansion requires a positive round number",
        )
    queries = raw.get("queries")
    if (
        not isinstance(queries, list)
        or not queries
        or len(queries) > policy.queries_per_round_limit
    ):
        raise KernelError(
            "RETRIEVAL_EXPANSION_QUERY_BUDGET_EXHAUSTED",
            "query expansion must contain a bounded non-empty query set",
        )
    if existing_query_count < 0:
        raise KernelError("RETRIEVAL_EXPANSION_QUERY_COUNT_INVALID", "Query observations cannot be negative")
    accepted_through = int(
        dict(contract.get("accepted_boundary") or {}).get("accepted_through_chapter")
        or 0
    )
    missing_targets = {
        f"{_target_prefix(dimension)}:{identity}"
        for dimension, values in dict(coverage.get("missing") or {}).items()
        for identity in _ids(values)
    }
    allowed_selectors = {
        dimension: set(_ids(dict(contract.get("selectors") or {}).get(dimension)))
        for dimension in _SELECTOR_DIMENSIONS
    }
    prior = {str(item) for item in prior_query_fingerprints if str(item)}
    prior_novelty = {_query_novelty(query) for query in prior_queries}
    normalized: list[dict[str, Any]] = []
    current_fingerprints: set[str] = set()
    for raw_query in queries:
        if not isinstance(raw_query, Mapping):
            raise KernelError(
                "RETRIEVAL_EXPANSION_SCHEMA_INVALID",
                "query expansion entries must be objects",
            )
        query_id = str(raw_query.get("query_id") or "").strip()
        text = " ".join(str(raw_query.get("text") or "").split())
        reason = " ".join(str(raw_query.get("reason") or "").split())
        targets = _ids(raw_query.get("targets"))
        if (
            not query_id
            or len(query_id) > 160
            or not text
            or len(text) > 512
            or not reason
            or len(reason) > 512
            or not targets
            or not set(targets).issubset(missing_targets)
        ):
            raise KernelError(
                "RETRIEVAL_EXPANSION_SCOPE_INVALID",
                "query expansion must target only current deterministic evidence gaps",
            )
        selectors_raw = raw_query.get("selectors") or {}
        if not isinstance(selectors_raw, Mapping) or any(
            key not in _SELECTOR_DIMENSIONS for key in selectors_raw
        ):
            raise KernelError(
                "RETRIEVAL_EXPANSION_SELECTOR_INVALID",
                "query expansion contains an ungoverned selector",
            )
        selectors = {
            dimension: _ids(selectors_raw.get(dimension))
            for dimension in _SELECTOR_DIMENSIONS
            if selectors_raw.get(dimension)
        }
        for dimension, values in selectors.items():
            if not set(values).issubset(allowed_selectors[dimension]):
                raise KernelError(
                    "RETRIEVAL_EXPANSION_SELECTOR_INVALID",
                    "query expansion selector escapes the frozen Mission scope",
                )
        temporal_raw = raw_query.get("temporal_range") or {}
        if not isinstance(temporal_raw, Mapping):
            raise KernelError(
                "RETRIEVAL_EXPANSION_TEMPORAL_INVALID",
                "query expansion temporal range must be an object",
            )
        start = int(temporal_raw.get("from_chapter") or 0)
        end = int(
            temporal_raw.get("to_chapter")
            if temporal_raw.get("to_chapter") is not None
            else accepted_through
        )
        if start < 0 or end < start or end > accepted_through:
            raise KernelError(
                "RETRIEVAL_EXPANSION_FUTURE_SCOPE_FORBIDDEN",
                "query expansion temporal range crosses the accepted boundary",
            )
        body = {
            "query_id": query_id,
            "text": text,
            "reason": reason,
            "targets": targets,
            "selectors": selectors,
            "temporal_range": {"from_chapter": start, "to_chapter": end},
        }
        fingerprint = _hash(body)
        novelty = _query_novelty(body)
        if fingerprint in prior or fingerprint in current_fingerprints or novelty in prior_novelty:
            raise KernelError(
                "RETRIEVAL_EXPANSION_NO_NOVEL_QUERY",
                "query expansion did not produce a novel query",
            )
        current_fingerprints.add(fingerprint)
        prior_novelty.add(novelty)
        normalized.append({**body, "query_fingerprint": fingerprint})
    body = {
        "contract_version": RETRIEVAL_EXPANSION_CONTRACT_VERSION,
        "round_number": round_number,
        "coverage_contract_fingerprint": str(
            contract.get("coverage_contract_fingerprint") or ""
        ),
        "coverage_before_fingerprint": str(coverage.get("coverage_fingerprint") or ""),
        "accepted_boundary": dict(contract.get("accepted_boundary") or {}),
        "policy_version": policy.policy_version,
        "queries": normalized,
    }
    return {**body, "expansion_plan_fingerprint": _hash(body)}


def _query_novelty(query: Mapping[str, Any]) -> str:
    return _hash({"text": " ".join(str(query.get("text") or "").split()),
        "targets": sorted(query.get("targets") or []),
        "selectors": {key: sorted(values) for key, values in dict(query.get("selectors") or {}).items()},
        "temporal_range": dict(query.get("temporal_range") or {})})


def decide_retrieval_campaign_transition(
    *,
    coverage: Mapping[str, Any],
    policy: RetrievalCampaignPolicy,
    completed_rounds: int,
    total_queries: int,
    provider_calls: int,
    model_tokens: int,
    cost_amount: str,
    last_round_new_evidence: int,
    expansion_available: bool,
    coverage_before: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if bool(coverage.get("sufficient")):
        return {"continue": False, "termination_reason": "REQUIRED_EVIDENCE_SATISFIED"}
    if completed_rounds > 1 and last_round_new_evidence <= 0:
        return {"continue": False, "termination_reason": "NO_NEW_EVIDENCE"}
    if completed_rounds > 1 and coverage_before is not None and coverage_before.get("missing") == coverage.get("missing"):
        return {"continue": False, "termination_reason": "NO_NEW_EVIDENCE"}
    if not expansion_available:
        return {"continue": False, "termination_reason": policy.fallback_mode}
    return {"continue": True, "termination_reason": "CONTINUE"}


def merge_retrieval_round_documents(
    rounds: Iterable[Iterable[Mapping[str, Any]]],
) -> tuple[dict[str, Any], ...]:
    merged: dict[str, dict[str, Any]] = {}
    identity_fields = (
        "source_asset_version_id",
        "source_content_hash",
        "projection_hash",
        "accepted_from_chapter",
        "accepted_to_chapter",
    )
    for round_documents in rounds:
        for raw in round_documents:
            document = dict(raw)
            identity = str(document.get("retrieval_document_id") or "")
            if not identity:
                raise KernelError(
                    "RETRIEVAL_ROUND_DOCUMENT_INVALID",
                    "round evidence requires a retrieval document identity",
                )
            existing = merged.get(identity)
            if existing is not None:
                if any(
                    existing.get(field) != document.get(field)
                    for field in identity_fields
                ):
                    raise KernelError(
                        "RETRIEVAL_ROUND_DOCUMENT_MUTATED",
                        "retrieval document immutable identity changed between rounds",
                    )
                existing["candidate_channels"] = sorted(
                    {
                        *_ids(existing.get("candidate_channels")),
                        *_ids(document.get("candidate_channels")),
                    }
                )
                continue
            document["candidate_channels"] = _ids(document.get("candidate_channels"))
            merged[identity] = document
    return tuple(merged[identity] for identity in sorted(merged))


def _target_prefix(dimension: str) -> str:
    return {
        "fact_ids": "fact",
        "historical_reference_ids": "history",
        "relationship_ids": "relationship",
        "arc_plan_version_ids": "arc",
        "obligation_ids": "obligation",
    }[dimension]


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
    "RETRIEVAL_CAMPAIGN_POLICY_VERSION",
    "RETRIEVAL_COVERAGE_CONTRACT_VERSION",
    "RETRIEVAL_EXPANSION_CONTRACT_VERSION",
    "RetrievalCampaignPolicy",
    "build_retrieval_coverage_contract",
    "decide_retrieval_campaign_transition",
    "evaluate_retrieval_coverage",
    "merge_retrieval_round_documents",
    "validate_retrieval_expansion_plan",
]
