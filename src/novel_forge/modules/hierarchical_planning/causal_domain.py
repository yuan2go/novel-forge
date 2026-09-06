from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any, Mapping, Sequence

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state.reality import narrative_hash
from novel_forge.modules.worldbuilding.dynamics import (
    WorldTransition,
    candidate_transition,
    require_contract_fields,
    require_text_fields,
)


DIRECTOR_DIMENSIONS = (
    "causal_plausibility",
    "character_consistency",
    "arc_progression",
    "pacing",
    "conflict",
    "emotion",
    "curiosity",
    "payoff",
    "novelty",
    "theme",
    "obligation_pressure",
)


@dataclass(frozen=True, slots=True)
class CandidateFuture:
    transition: WorldTransition
    dimensions: Mapping[str, float]
    affected_entities: tuple[str, ...]
    world_consequences: tuple[str, ...]
    arc_refs: tuple[str, ...]
    obligation_refs: tuple[str, ...]
    risks: tuple[str, ...]
    rationale: str

    def __post_init__(self) -> None:
        if (
            set(self.dimensions) != set(DIRECTOR_DIMENSIONS)
            or any(
                isinstance(v, bool)
                or not isinstance(v, (int, float))
                or not isfinite(v)
                or not 0 <= v <= 1
                for v in self.dimensions.values()
            )
            or not self.rationale.strip()
            or not self.affected_entities
            or not self.world_consequences
        ):
            raise KernelError(
                "NARRATIVE_DIRECTOR_EVIDENCE_INVALID",
                "Director candidates require all declared dimensions and consequence evidence",
            )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> CandidateFuture:
        require_contract_fields(
            value,
            required={
                "transition",
                "dimensions",
                "affected_entities",
                "world_consequences",
                "rationale",
            },
            optional={"arc_refs", "obligation_refs", "risks"},
        )
        require_text_fields(value, ("rationale",))
        if not isinstance(value["dimensions"], dict) or any(
            not isinstance(value.get(key, []), list)
            or any(not isinstance(item, str) or not item for item in value.get(key, []))
            for key in (
                "affected_entities",
                "world_consequences",
                "arc_refs",
                "obligation_refs",
                "risks",
            )
        ):
            raise KernelError(
                "NARRATIVE_DIRECTOR_EVIDENCE_INVALID",
                "Director dimensions and scoped reference arrays must be typed",
            )
        return cls(
            WorldTransition.from_mapping(value["transition"]),
            dict(value["dimensions"]),
            tuple(value["affected_entities"]),
            tuple(value["world_consequences"]),
            tuple(value.get("arc_refs", [])),
            tuple(value.get("obligation_refs", [])),
            tuple(value.get("risks", [])),
            str(value["rationale"]),
        )


@dataclass(frozen=True, slots=True)
class CausalDebt:
    debt_id: str
    candidate_id: str
    requirement_id: str
    reality_revision_id: str
    status: str
    preparation: Mapping[str, Any]
    discharge_evidence: str


def build_causal_plan(
    *,
    reality: Mapping[str, Any],
    candidates: Sequence[CandidateFuture],
    chapter_number: int,
    intent_revision_id: str,
) -> dict[str, Any]:
    if (
        chapter_number <= int(reality["chapter_number"])
        or not intent_revision_id
        or not candidates
        or len(candidates) > 32
    ):
        raise KernelError(
            "CAUSAL_PLAN_SCOPE_INVALID",
            "a bounded candidate portfolio requires future scope and revisioned Intent",
        )
    if len({c.transition.transition_id for c in candidates}) != len(candidates):
        raise KernelError(
            "CAUSAL_PLAN_DUPLICATE_FUTURE",
            "candidate transitions require distinct identities",
        )
    evaluated: list[dict[str, Any]] = []
    debts: list[dict[str, Any]] = []
    for candidate in candidates:
        try:
            result = candidate_transition(candidate.transition, reality)
        except KernelError as exc:
            evaluated.append(
                {
                    "transition_id": candidate.transition.transition_id,
                    "eligible": False,
                    "rejection": {"code": exc.code, "message": str(exc)},
                    "dimensions": dict(candidate.dimensions),
                }
            )
            continue
        for receipt in result["requirements"]:
            debt_id = "causal-debt:" + narrative_hash(
                {
                    "transition_id": candidate.transition.transition_id,
                    "requirement_id": receipt["requirement_id"],
                    "intent_revision_id": intent_revision_id,
                    "intent_constraints": dict(reality.get("intent_constraints") or {}),
                }
            )
            debt = CausalDebt(
                debt_id,
                result["candidate_id"],
                receipt["requirement_id"],
                str(reality["revision_id"]),
                "DISCHARGED_BY_ACCEPTED_REALITY"
                if receipt["satisfied"]
                else "PREPARATION_REQUIRED",
                receipt,
                str(receipt["source_event_id"]) if receipt["satisfied"] else "",
            )
            debts.append(asdict(debt))
        evaluated.append(
            {
                **result,
                "dimensions": dict(candidate.dimensions),
                "rationale": candidate.rationale,
                "affected_entities": list(candidate.affected_entities),
                "world_consequences": list(candidate.world_consequences),
                "arc_refs": list(candidate.arc_refs),
                "obligation_refs": list(candidate.obligation_refs),
                "risks": list(candidate.risks),
                "rank_value": sum(candidate.dimensions.values())
                / len(DIRECTOR_DIMENSIONS),
            }
        )
    eligible = sorted(
        (c for c in evaluated if c["eligible"]),
        key=lambda c: (-c["rank_value"], c["candidate_id"]),
    )
    body = {
        "contract_version": "causal-plan.v1",
        "authority": "PLANNING_PROPOSAL",
        "project_id": reality["project_id"],
        "book_id": reality["book_id"],
        "book_run_id": reality["book_run_id"],
        "reality_revision_id": reality["revision_id"],
        "accepted_through_chapter": reality["chapter_number"],
        "chapter_number": chapter_number,
        "intent_revision_id": intent_revision_id,
        "intent_constraints": dict(reality.get("intent_constraints") or {}),
        "director_policy": "causal-eligibility-then-balanced-dimensions.v1",
        "world_design_constraints": list(reality.get("world_rule_constraints", [])),
        "candidate_futures": evaluated,
        "causal_debts": debts,
        "selected_candidate_id": eligible[0]["candidate_id"] if eligible else "",
        "next_legal_action": "PROPOSE_SCENE_ARCHITECTURE"
        if eligible
        else "PREPARE_CAUSAL_CONDITIONS",
        "fact_mutation_allowed": False,
        "preserve_accepted_history": True,
    }
    return {**body, "plan_digest": narrative_hash(body)}
