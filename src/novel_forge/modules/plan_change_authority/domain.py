"""Pure semantic diff and approval policy for plan changes."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError


class PlanChangeSource(StrEnum):
    LONGFORM_RECAP = "LONGFORM_RECAP"
    PLAN_VS_ACTUAL = "PLAN_VS_ACTUAL"
    READER_OUTCOME = "READER_OUTCOME"
    HUMAN_FEEDBACK = "HUMAN_FEEDBACK"
    CANON_CHANGE = "CANON_CHANGE"
    STORY_STATE_CHANGE = "STORY_STATE_CHANGE"
    QUALITY_ISSUE = "QUALITY_ISSUE"
    PLATFORM_CHANGE = "PLATFORM_CHANGE"
    ENDING_REACHABILITY_RISK = "ENDING_REACHABILITY_RISK"
    ARC_CLOSURE_RISK = "ARC_CLOSURE_RISK"


class PlanChangeRisk(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


SEMANTIC_FIELDS = {
    "objective": "OBJECTIVE_CHANGED",
    "required_events": "REQUIRED_EVENT_CHANGED",
    "forbidden_events": "FORBIDDEN_EVENT_CHANGED",
    "required_payoffs": "PAYOFF_CHANGED",
    "forbidden_payoffs": "PAYOFF_CHANGED",
    "character_deltas": "CHARACTER_DELTA_CHANGED",
    "arc_contributions": "ARC_CONTRIBUTION_CHANGED",
    "chapter_range": "CHAPTER_RANGE_CHANGED",
    "ending_contract": "ENDING_CONTRACT_CHANGED",
    "canon_dependencies": "CANON_DEPENDENCY_CHANGED",
    "quality_targets": "QUALITY_TARGET_CHANGED",
}

HIGH_RISK_FIELDS = frozenset(
    {
        "ending_contract",
        "reader_promise",
        "central_conflict_engine",
        "protagonist_core_goal",
        "primary_antagonist",
        "world_rules",
        "canon_dependencies",
        "commercial_positioning",
    }
)


@dataclass(frozen=True, slots=True)
class SemanticFieldChange:
    field: str
    change_type: str
    before: Any
    after: Any


def semantic_plan_diff(
    before: dict[str, Any], after: dict[str, Any]
) -> tuple[SemanticFieldChange, ...]:
    changes: list[SemanticFieldChange] = []
    fields = sorted(set(SEMANTIC_FIELDS) | (set(before) & HIGH_RISK_FIELDS))
    for field in fields:
        old = before.get(field)
        new = after.get(field)
        if _canonical(old) != _canonical(new):
            changes.append(
                SemanticFieldChange(
                    field=field,
                    change_type=SEMANTIC_FIELDS.get(
                        field, f"{field.upper()}_CHANGED"
                    ),
                    before=old,
                    after=new,
                )
            )
    return tuple(changes)


def classify_plan_change_risk(
    changes: tuple[SemanticFieldChange, ...],
    *,
    target_execution_scope: str,
) -> PlanChangeRisk:
    changed_fields = {change.field for change in changes}
    if target_execution_scope in {"EXECUTED", "FROZEN"}:
        return PlanChangeRisk.HIGH
    if changed_fields & HIGH_RISK_FIELDS:
        return PlanChangeRisk.HIGH
    if changed_fields & {
        "objective",
        "required_events",
        "chapter_range",
        "character_deltas",
        "arc_contributions",
    }:
        return PlanChangeRisk.MEDIUM
    return PlanChangeRisk.LOW


def require_approvable_scope(target_execution_scope: str) -> None:
    if target_execution_scope == "EXECUTED":
        raise KernelError(
            "EXECUTED_PLAN_RETCON_ONLY",
            "executed plans may only receive a separate Retcon proposal",
        )


def _canonical(value: Any) -> str:
    import json

    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


__all__ = [
    "HIGH_RISK_FIELDS",
    "PlanChangeRisk",
    "PlanChangeSource",
    "SEMANTIC_FIELDS",
    "SemanticFieldChange",
    "classify_plan_change_risk",
    "require_approvable_scope",
    "semantic_plan_diff",
]
