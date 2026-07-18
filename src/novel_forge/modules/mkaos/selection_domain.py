"""Storage-free explainable MKAOS production selection."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from novel_forge.modules.context_contracts import ContextCandidate


@dataclass(frozen=True, slots=True)
class KnowledgeCandidate:
    asset_version_id: str
    project_id: str
    asset_type: str
    estimated_tokens: int
    semantic_relevance: float
    stage_fit: float
    genre_fit: float
    narrative_function: float
    source_trust: float
    source_risk: float
    usage_history: float
    quality_score: float
    freshness: float
    redundancy: float
    conflict: float
    project_specificity: float
    qualification: str = "ELIGIBLE"
    governance_status: str = "CLEAR"
    source_use_mode: str = "generation"
    source_policy_version: str = ""
    content_digest: str = ""
    narrative_function_label: str = ""
    invalidation_keys: tuple[str, ...] = ()


_WEIGHTS = {
    "semantic_relevance": 0.22,
    "stage_fit": 0.16,
    "genre_fit": 0.08,
    "narrative_function": 0.12,
    "source_trust": 0.08,
    "usage_history": 0.05,
    "quality_score": 0.10,
    "freshness": 0.05,
    "project_specificity": 0.14,
    "source_risk": -0.12,
    "redundancy": -0.10,
    "conflict": -0.18,
}


def select_knowledge_pack(
    *,
    project_id: str,
    stage: str,
    query_intent: str,
    candidates: Iterable[KnowledgeCandidate],
    token_budget: int,
    minimum_score: float = 0.35,
) -> dict[str, Any]:
    if not project_id or not stage or not query_intent.strip() or token_budget <= 0:
        raise ValueError("project, stage, query intent and token budget are required")
    ranked: list[tuple[float, KnowledgeCandidate, dict[str, float]]] = []
    rejected: list[dict[str, Any]] = []
    for candidate in candidates:
        if candidate.project_id != project_id:
            rejected.append(_rejection(candidate, "cross_project"))
            continue
        if candidate.qualification != "ELIGIBLE":
            rejected.append(_rejection(candidate, f"qualification:{candidate.qualification}"))
            continue
        if candidate.governance_status != "CLEAR":
            rejected.append(_rejection(candidate, f"governance:{candidate.governance_status}"))
            continue
        components = {name: getattr(candidate, name) * weight for name, weight in _WEIGHTS.items()}
        score = max(0.0, min(1.0, sum(components.values())))
        if score < minimum_score:
            rejected.append(_rejection(candidate, "score_below_threshold", score, components))
            continue
        if candidate.conflict >= 0.8:
            rejected.append(_rejection(candidate, "blocking_conflict", score, components))
            continue
        ranked.append((score, candidate, components))
    ranked.sort(key=lambda row: (-row[0], row[1].asset_version_id))
    selected: list[dict[str, Any]] = []
    used = 0
    functions: set[str] = set()
    for score, candidate, components in ranked:
        if used + candidate.estimated_tokens > token_budget:
            rejected.append(_rejection(candidate, "token_budget", score, components))
            continue
        # High redundancy is only tolerated when it adds a new narrative function.
        if candidate.redundancy >= 0.7 and candidate.narrative_function_label in functions:
            rejected.append(_rejection(candidate, "redundant_narrative_function", score, components))
            continue
        used += candidate.estimated_tokens
        functions.add(candidate.narrative_function_label)
        selected.append(
            {
                "asset_version_id": candidate.asset_version_id,
                "asset_type": candidate.asset_type,
                "score": round(score, 6),
                "score_components": {key: round(value, 6) for key, value in components.items()},
                "selection_reason": "highest governed stage-fit value within budget",
                "allowed_use": candidate.source_use_mode,
                "narrative_function": candidate.narrative_function_label,
                "estimated_tokens": candidate.estimated_tokens,
                "source_policy_version": candidate.source_policy_version,
                "content_digest": candidate.content_digest,
                "invalidation_keys": list(candidate.invalidation_keys),
            }
        )
    return {
        "project_id": project_id,
        "stage": stage,
        "query_intent": query_intent,
        "selected": selected,
        "rejected": sorted(rejected, key=lambda item: item["asset_version_id"]),
        "estimated_tokens": used,
        "token_budget": token_budget,
        "selection_contract_version": "mkaos-selection-v1",
    }


def selection_to_context_candidates(selection: dict[str, Any]) -> tuple[ContextCandidate, ...]:
    project_id = str(selection["project_id"])
    return tuple(
        ContextCandidate(
            asset_version_id=str(item["asset_version_id"]),
            asset_type=str(item["asset_type"]),
            project_id=project_id,
            estimated_tokens=int(item["estimated_tokens"]),
            relevance_score=float(item["score"]),
            source_use_mode=str(item["allowed_use"]),
            policy_version=str(item.get("source_policy_version") or ""),
            content_digest=str(item.get("content_digest") or ""),
            invalidation_keys=tuple(item.get("invalidation_keys", [])),
            narrative_function=str(item.get("narrative_function") or ""),
        )
        for item in selection["selected"]
    )


def _rejection(
    candidate: KnowledgeCandidate,
    reason: str,
    score: float = 0.0,
    components: dict[str, float] | None = None,
) -> dict[str, Any]:
    return {
        "asset_version_id": candidate.asset_version_id,
        "reason": reason,
        "score": round(score, 6),
        "score_components": {key: round(value, 6) for key, value in (components or {}).items()},
        "allowed_use": candidate.source_use_mode,
    }


__all__ = ["KnowledgeCandidate", "select_knowledge_pack", "selection_to_context_candidates"]
