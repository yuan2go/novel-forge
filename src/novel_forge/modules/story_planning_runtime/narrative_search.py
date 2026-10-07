from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from enum import StrEnum
import math
from typing import Any, Mapping, Sequence

from novel_forge.modules.command_kernel.errors import KernelError


NARRATIVE_SEARCH_CONTRACT_VERSION = "narrative-search.v1"
NARRATIVE_SEARCH_PROJECTION_VERSION = "narrative-search-projection.v1"
NARRATIVE_SEARCH_POLICY_VERSION = "narrative-search-comparison.v1"


class NarrativeSearchStatus(StrEnum):
    OPEN = "OPEN"
    GENERATING = "GENERATING"
    READY_FOR_SELECTION = "READY_FOR_SELECTION"
    SELECTED = "SELECTED"
    ACTIVATED = "ACTIVATED"
    STALE = "STALE"
    FAILED = "FAILED"


CREATIVE_INTELLIGENCE_DIMENSIONS = (
    "conflict_escalation",
    "character_agency",
    "choice_cost_consequence",
    "reversal_reveal",
    "setup_payoff",
    "emotional_progression",
    "pacing_variation",
    "relationship_evolution",
    "world_consequence",
    "pattern_diversity",
    "arc_momentum",
    "reader_promise",
    "future_optionality",
)

_DIMENSION_WEIGHTS = {
    "conflict_escalation": 1.15,
    "character_agency": 1.25,
    "choice_cost_consequence": 1.25,
    "reversal_reveal": 0.85,
    "setup_payoff": 1.10,
    "emotional_progression": 0.95,
    "pacing_variation": 0.85,
    "relationship_evolution": 0.75,
    "world_consequence": 0.75,
    "pattern_diversity": 1.05,
    "arc_momentum": 1.10,
    "reader_promise": 1.10,
    "future_optionality": 1.25,
}


@dataclass(frozen=True, slots=True)
class NarrativeSearchProjection:
    strategy_fingerprint: str
    assumptions: tuple[str, ...]
    projected_consequences: tuple[str, ...]
    narrative_opportunities: tuple[str, ...]
    narrative_risks: tuple[str, ...]
    irreversible_decisions: tuple[str, ...]
    future_options: tuple[str, ...]
    repetition_keys: tuple[str, ...]
    creative_intelligence: Mapping[str, float]
    selection_summary: str
    contract_version: str = NARRATIVE_SEARCH_PROJECTION_VERSION

    @classmethod
    def from_mapping(cls, value: Any) -> "NarrativeSearchProjection":
        if not isinstance(value, Mapping):
            raise KernelError(
                "NARRATIVE_SEARCH_PROJECTION_REQUIRED",
                "search candidate requires a structured future projection",
            )
        forbidden_source_fields = {
            "source_plot",
            "source_event_sequence",
            "source_character_replacement",
            "raw_expression",
            "ready_made_plot",
        }
        if forbidden_source_fields & set(value):
            raise KernelError(
                "NARRATIVE_SEARCH_SOURCE_ISOLATION_VIOLATION",
                "search projection cannot contain a source-specific plot template",
            )
        allowed = {
            "contract_version",
            "strategy_fingerprint",
            "assumptions",
            "projected_consequences",
            "narrative_opportunities",
            "narrative_risks",
            "irreversible_decisions",
            "future_options",
            "repetition_keys",
            "creative_intelligence",
            "selection_summary",
        }
        unexpected = sorted(set(value) - allowed)
        if unexpected:
            raise KernelError(
                "NARRATIVE_SEARCH_PROJECTION_INVALID",
                "future projection contains unsupported fields: "
                + ", ".join(unexpected),
            )
        if value.get("contract_version") != NARRATIVE_SEARCH_PROJECTION_VERSION:
            raise KernelError(
                "NARRATIVE_SEARCH_PROJECTION_VERSION_INVALID",
                "future projection contract version is unsupported",
            )
        fingerprint = str(value.get("strategy_fingerprint") or "").strip()
        summary = str(value.get("selection_summary") or "").strip()
        if not fingerprint or not summary:
            raise KernelError(
                "NARRATIVE_SEARCH_PROJECTION_INVALID",
                "future projection requires a strategy fingerprint and summary",
            )
        collections: dict[str, tuple[str, ...]] = {}
        for field in (
            "assumptions",
            "projected_consequences",
            "narrative_opportunities",
            "narrative_risks",
            "irreversible_decisions",
            "future_options",
            "repetition_keys",
        ):
            raw = value.get(field)
            if not isinstance(raw, list):
                raise KernelError(
                    "NARRATIVE_SEARCH_PROJECTION_INVALID",
                    f"future projection {field} must be an array",
                )
            normalized = tuple(str(item).strip() for item in raw)
            if any(not item for item in normalized) or len(set(normalized)) != len(
                normalized
            ):
                raise KernelError(
                    "NARRATIVE_SEARCH_PROJECTION_INVALID",
                    f"future projection {field} contains empty or duplicate values",
                )
            collections[field] = normalized
        for required in (
            "assumptions",
            "projected_consequences",
            "narrative_opportunities",
            "narrative_risks",
            "future_options",
        ):
            if not collections[required]:
                raise KernelError(
                    "NARRATIVE_SEARCH_PROJECTION_INVALID",
                    f"future projection {required} cannot be empty",
                )
        intelligence = value.get("creative_intelligence")
        if not isinstance(intelligence, Mapping) or set(intelligence) != set(
            CREATIVE_INTELLIGENCE_DIMENSIONS
        ):
            raise KernelError(
                "NARRATIVE_SEARCH_INTELLIGENCE_INVALID",
                "creative intelligence dimensions differ from the search policy",
            )
        normalized_intelligence: dict[str, float] = {}
        for dimension in CREATIVE_INTELLIGENCE_DIMENSIONS:
            score = intelligence.get(dimension)
            if (
                not isinstance(score, (int, float))
                or isinstance(score, bool)
                or not 0 <= float(score) <= 1
            ):
                raise KernelError(
                    "NARRATIVE_SEARCH_INTELLIGENCE_INVALID",
                    f"{dimension} must be a score between zero and one",
                )
            normalized_intelligence[dimension] = float(score)
        return cls(
            strategy_fingerprint=fingerprint,
            assumptions=collections["assumptions"],
            projected_consequences=collections["projected_consequences"],
            narrative_opportunities=collections["narrative_opportunities"],
            narrative_risks=collections["narrative_risks"],
            irreversible_decisions=collections["irreversible_decisions"],
            future_options=collections["future_options"],
            repetition_keys=collections["repetition_keys"],
            creative_intelligence=normalized_intelligence,
            selection_summary=summary,
        )

    @property
    def comparison_score(self) -> float:
        numerator = sum(
            self.creative_intelligence[dimension] * weight
            for dimension, weight in _DIMENSION_WEIGHTS.items()
        )
        denominator = sum(_DIMENSION_WEIGHTS.values())
        # WHY: Risk and irreversibility remain explainable soft pressure.  They do
        # not become universal literary prohibitions.
        risk_pressure = min(0.10, len(self.narrative_risks) * 0.01)
        irreversible_pressure = min(0.05, len(self.irreversible_decisions) * 0.01)
        option_credit = min(0.05, len(self.future_options) * 0.01)
        return round(
            max(
                0.0,
                min(
                    1.0,
                    numerator / denominator
                    - risk_pressure
                    - irreversible_pressure
                    + option_credit,
                ),
            ),
            6,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "strategy_fingerprint": self.strategy_fingerprint,
            "assumptions": list(self.assumptions),
            "projected_consequences": list(self.projected_consequences),
            "narrative_opportunities": list(self.narrative_opportunities),
            "narrative_risks": list(self.narrative_risks),
            "irreversible_decisions": list(self.irreversible_decisions),
            "future_options": list(self.future_options),
            "repetition_keys": list(self.repetition_keys),
            "creative_intelligence": dict(self.creative_intelligence),
            "selection_summary": self.selection_summary,
        }


@dataclass(frozen=True, slots=True)
class NarrativeSearchCandidate:
    candidate_asset_version_id: str
    generation_operation_id: str
    branch_key: str
    projection: NarrativeSearchProjection
    qualification_hash: str

    @property
    def score(self) -> float:
        return self.projection.comparison_score


@dataclass(frozen=True, slots=True)
class NarrativeSearchComparison:
    selected_candidate_asset_version_id: str
    ranked_candidates: tuple[dict[str, Any], ...]
    selection_reasons: tuple[str, ...]
    rejected_candidate_asset_version_ids: tuple[str, ...]
    policy_version: str = NARRATIVE_SEARCH_POLICY_VERSION
    selection_evidence: Mapping[str, Any] = dataclass_field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": NARRATIVE_SEARCH_CONTRACT_VERSION,
            "policy_version": self.policy_version,
            **(
                {"selection_evidence": dict(self.selection_evidence)}
                if self.selection_evidence
                else {}
            ),
            "selected_candidate_asset_version_id": (
                self.selected_candidate_asset_version_id
            ),
            "ranked_candidates": [dict(item) for item in self.ranked_candidates],
            "selection_reasons": list(self.selection_reasons),
            "rejected_candidate_asset_version_ids": list(
                self.rejected_candidate_asset_version_ids
            ),
        }


def compare_narrative_futures(
    candidates: Sequence[NarrativeSearchCandidate],
    *,
    selection_policy: Mapping[str, Any] | None = None,
) -> NarrativeSearchComparison:
    if len(candidates) < 2:
        raise KernelError(
            "NARRATIVE_SEARCH_CANDIDATE_SET_TOO_SMALL",
            "narrative search requires at least two qualified futures",
        )
    identities = [item.candidate_asset_version_id for item in candidates]
    branches = [item.branch_key for item in candidates]
    if len(set(identities)) != len(identities) or len(set(branches)) != len(branches):
        raise KernelError(
            "NARRATIVE_SEARCH_CANDIDATE_IDENTITY_INVALID",
            "search candidate and branch identities must be unique",
        )
    fingerprints = [item.projection.strategy_fingerprint for item in candidates]
    if len(set(fingerprints)) < 2:
        raise KernelError(
            "NARRATIVE_SEARCH_NOT_DIVERGENT",
            "search futures differ only superficially",
        )
    if selection_policy is not None:
        return _compare_work_futures(candidates, selection_policy)
    ranked = sorted(
        candidates,
        key=lambda item: (-item.score, item.candidate_asset_version_id),
    )
    selected = ranked[0]
    ranked_evidence = tuple(
        {
            "rank": ordinal,
            "candidate_asset_version_id": item.candidate_asset_version_id,
            "generation_operation_id": item.generation_operation_id,
            "branch_key": item.branch_key,
            "strategy_fingerprint": item.projection.strategy_fingerprint,
            "score": item.score,
            "qualification_hash": item.qualification_hash,
            "selection_summary": item.projection.selection_summary,
        }
        for ordinal, item in enumerate(ranked, start=1)
    )
    strongest = sorted(
        selected.projection.creative_intelligence.items(),
        key=lambda item: (-item[1], item[0]),
    )[:3]
    return NarrativeSearchComparison(
        selected_candidate_asset_version_id=selected.candidate_asset_version_id,
        ranked_candidates=ranked_evidence,
        selection_reasons=tuple(
            [
                f"highest qualified comparison score {selected.score:.6f}",
                *(f"{dimension}={score:.3f}" for dimension, score in strongest),
                (
                    f"preserves {len(selected.projection.future_options)} "
                    "explicit future options"
                ),
            ]
        ),
        rejected_candidate_asset_version_ids=tuple(
            item.candidate_asset_version_id for item in ranked[1:]
        ),
    )


def validate_search_selection_policy(value: Mapping[str, Any]) -> dict[str, Any]:
    weights = value.get("dimension_weights") if isinstance(value, Mapping) else None
    margin = value.get("uncertainty_margin") if isinstance(value, Mapping) else None
    if (
        not isinstance(value, Mapping)
        or set(value)
        != {"contract_version", "dimension_weights", "uncertainty_margin", "tie_break"}
        or value.get("contract_version") != "narrative-search-comparison.v2"
        or not isinstance(weights, Mapping)
        or set(weights) != set(CREATIVE_INTELLIGENCE_DIMENSIONS)
        or any(
            type(weight) not in {int, float}
            or not math.isfinite(weight)
            or not 0 <= weight <= 10
            for weight in weights.values()
        )
        or not any(weights.values())
        or type(margin) not in {int, float}
        or not math.isfinite(margin)
        or not 0 <= margin <= 1
        or value.get("tie_break") != "STABLE_ID"
    ):
        raise KernelError(
            "NARRATIVE_SEARCH_SELECTION_POLICY_INVALID",
            "Comparison requires frozen bounded work weights, uncertainty and authorized tie-breaking",
        )
    return {
        "contract_version": value["contract_version"],
        "dimension_weights": dict(weights),
        "uncertainty_margin": margin,
        "tie_break": value["tie_break"],
    }


def _compare_work_futures(
    candidates: Sequence[NarrativeSearchCandidate], policy: Mapping[str, Any]
) -> NarrativeSearchComparison:
    policy = validate_search_selection_policy(policy)
    weights = policy["dimension_weights"]
    scores = {
        item.candidate_asset_version_id: sum(
            item.projection.creative_intelligence[key] * weight
            for key, weight in weights.items()
        )
        / sum(weights.values())
        for item in candidates
    }
    ranked = sorted(
        candidates,
        key=lambda item: (
            -scores[item.candidate_asset_version_id],
            item.candidate_asset_version_id,
        ),
    )
    top = scores[ranked[0].candidate_asset_version_id]
    gap = top - scores[ranked[1].candidate_asset_version_id]
    tied = [
        item
        for item in ranked
        if top - scores[item.candidate_asset_version_id] <= policy["uncertainty_margin"]
    ]
    selected = (
        min(tied, key=lambda item: item.candidate_asset_version_id)
        if len(tied) > 1
        else ranked[0]
    )
    evidence = {
        "policy": policy,
        "evidence_class": "MODEL_ESTIMATES_AND_CANDIDATE_PROJECTIONS",
        "literary_superiority": "NOT_PROVEN",
        "score_gap": gap,
        "uncertainty": "INSUFFICIENT_MARGIN"
        if len(tied) > 1
        else "MODEL_ESTIMATED_PREFERENCE",
        "selection_basis": "AUTHORIZED_STABLE_TIE_BREAK"
        if len(tied) > 1
        else "WORK_WEIGHTED_PREFERENCE",
        "indistinguishable_candidate_asset_version_ids": [
            item.candidate_asset_version_id for item in tied
        ]
        if len(tied) > 1
        else [],
    }
    return NarrativeSearchComparison(
        selected_candidate_asset_version_id=selected.candidate_asset_version_id,
        ranked_candidates=tuple(
            {
                "rank": ordinal,
                "candidate_asset_version_id": item.candidate_asset_version_id,
                "generation_operation_id": item.generation_operation_id,
                "branch_key": item.branch_key,
                "strategy_fingerprint": item.projection.strategy_fingerprint,
                "score": scores[item.candidate_asset_version_id],
                "qualification_hash": item.qualification_hash,
                "selection_summary": item.projection.selection_summary,
                "assumptions": list(item.projection.assumptions),
                "risks": list(item.projection.narrative_risks),
                "future_options": list(item.projection.future_options),
            }
            for ordinal, item in enumerate(ranked, 1)
        ),
        selection_reasons=(
            evidence["selection_basis"],
            selected.projection.selection_summary,
            "Model judgment is uncertain evidence; this selection does not prove literary superiority.",
        ),
        rejected_candidate_asset_version_ids=tuple(
            item.candidate_asset_version_id for item in ranked if item is not selected
        ),
        policy_version=policy["contract_version"],
        selection_evidence=evidence,
    )


def narrative_search_projection_schema() -> dict[str, Any]:
    string = {"type": "string", "minLength": 1}
    string_array = {"type": "array", "items": string}
    return {
        "type": "object",
        "properties": {
            "contract_version": {
                "type": "string",
                "const": NARRATIVE_SEARCH_PROJECTION_VERSION,
            },
            "strategy_fingerprint": string,
            "assumptions": {**string_array, "minItems": 1},
            "projected_consequences": {**string_array, "minItems": 1},
            "narrative_opportunities": {**string_array, "minItems": 1},
            "narrative_risks": {**string_array, "minItems": 1},
            "irreversible_decisions": string_array,
            "future_options": {**string_array, "minItems": 1},
            "repetition_keys": string_array,
            "creative_intelligence": {
                "type": "object",
                "properties": {
                    item: {"type": "number", "minimum": 0, "maximum": 1}
                    for item in CREATIVE_INTELLIGENCE_DIMENSIONS
                },
                "required": list(CREATIVE_INTELLIGENCE_DIMENSIONS),
                "additionalProperties": False,
            },
            "selection_summary": string,
        },
        "required": [
            "contract_version",
            "strategy_fingerprint",
            "assumptions",
            "projected_consequences",
            "narrative_opportunities",
            "narrative_risks",
            "irreversible_decisions",
            "future_options",
            "repetition_keys",
            "creative_intelligence",
            "selection_summary",
        ],
        "additionalProperties": False,
    }


__all__ = [
    "CREATIVE_INTELLIGENCE_DIMENSIONS",
    "NARRATIVE_SEARCH_CONTRACT_VERSION",
    "NARRATIVE_SEARCH_POLICY_VERSION",
    "NARRATIVE_SEARCH_PROJECTION_VERSION",
    "NarrativeSearchCandidate",
    "NarrativeSearchComparison",
    "NarrativeSearchProjection",
    "NarrativeSearchStatus",
    "compare_narrative_futures",
    "narrative_search_projection_schema",
]
