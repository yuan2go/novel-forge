from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
from typing import Any, Mapping


class ArcStatus(StrEnum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    STALLED = "STALLED"
    AT_RISK = "AT_RISK"
    CLOSURE_PENDING = "CLOSURE_PENDING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class EndingReachability(StrEnum):
    REACHABLE = "REACHABLE"
    AT_RISK = "AT_RISK"
    UNREACHABLE = "UNREACHABLE"
    UNKNOWN = "UNKNOWN"


class SupervisorAction(StrEnum):
    RESOLVE_INPUT = "RESOLVE_INPUT"
    GENERATE_CHAPTER_GROUP = "GENERATE_CHAPTER_GROUP"
    FREEZE_CHAPTER_GROUP_PLAN = "FREEZE_CHAPTER_GROUP_PLAN"
    QUALIFY_NARRATIVE_REALIZATION = "QUALIFY_NARRATIVE_REALIZATION"
    START_CHAPTER_GROUP = "START_CHAPTER_GROUP"
    CLOSE_CHAPTER_GROUP = "CLOSE_CHAPTER_GROUP"
    WAIT_PLAN_APPROVAL = "WAIT_PLAN_APPROVAL"
    WAIT_CONTROL_DECISION = "WAIT_CONTROL_DECISION"
    WAIT_EXTERNAL_RECONCILIATION = "WAIT_EXTERNAL_RECONCILIATION"
    GENERATE_CHAPTER_PLAN = "GENERATE_CHAPTER_PLAN"
    FREEZE_CHAPTER_PLAN = "FREEZE_CHAPTER_PLAN"
    DISPATCH_CHAPTER = "DISPATCH_CHAPTER"
    RECONCILE_CHAPTER = "RECONCILE_CHAPTER"
    ACCEPT_CHAPTER = "ACCEPT_CHAPTER"
    ABORT_TERMINAL_CHAPTER = "ABORT_TERMINAL_CHAPTER"
    NORMALIZE_LEGACY_STATE = "NORMALIZE_LEGACY_STATE"
    UPDATE_CHECKPOINTS = "UPDATE_CHECKPOINTS"
    WAIT_REPLAN_SOURCE = "WAIT_REPLAN_SOURCE"
    START_REPLAN = "START_REPLAN"
    WAIT_REPLAN_APPROVAL = "WAIT_REPLAN_APPROVAL"
    APPROVE_REPLAN = "APPROVE_REPLAN"
    ACTIVATE_REPLAN = "ACTIVATE_REPLAN"
    RETIRE_SUPERSEDED_CHAPTER_GROUP = "RETIRE_SUPERSEDED_CHAPTER_GROUP"
    CONTINUE = "CONTINUE"
    PAUSE = "PAUSE"
    COMPLETE = "COMPLETE"
    NO_ACTION = "NO_ACTION"


@dataclass(frozen=True, slots=True)
class EndingReachabilityInput:
    evaluated_through_chapter: int
    target_chapter_count: int
    minimum_ending_chapters: int
    critical_arc_open_count: int
    critical_arc_closure_capacity: int
    required_event_count: int
    open_event_window_count: int
    unsettled_promise_count: int
    promise_settlement_capacity: int

    def __post_init__(self) -> None:
        if any(value < 0 for value in asdict(self).values()):
            raise ValueError("Ending reachability inputs cannot be negative")
        if self.evaluated_through_chapter > self.target_chapter_count:
            raise ValueError("evaluated chapter exceeds the target chapter count")


@dataclass(frozen=True, slots=True)
class EndingReachabilityReport:
    status: EndingReachability
    evaluated_through_chapter: int
    remaining_chapter_budget: int
    ending_contract_reachable: bool
    critical_arc_closure_path: bool
    chapter_budget_sufficient: bool
    required_event_windows_open: bool
    promise_capacity_sufficient: bool
    replan_required: bool
    reasons: tuple[str, ...]
    report_hash: str

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["status"] = self.status.value
        value["reasons"] = list(self.reasons)
        return value


def evaluate_ending_reachability(
    value: EndingReachabilityInput,
) -> EndingReachabilityReport:
    remaining = value.target_chapter_count - value.evaluated_through_chapter
    checks = {
        "chapter_budget_sufficient": remaining >= value.minimum_ending_chapters,
        "critical_arc_closure_path": (
            value.critical_arc_open_count <= value.critical_arc_closure_capacity
        ),
        "required_event_windows_open": (
            value.required_event_count <= value.open_event_window_count
        ),
        "promise_capacity_sufficient": (
            value.unsettled_promise_count <= value.promise_settlement_capacity
        ),
    }
    reasons = tuple(sorted(name for name, passed in checks.items() if not passed))
    reachable = all(checks.values())
    if reachable:
        status = EndingReachability.REACHABLE
    elif remaining == 0 or sum(checks.values()) <= 1:
        status = EndingReachability.UNREACHABLE
    else:
        status = EndingReachability.AT_RISK
    payload: dict[str, Any] = {
        "status": status.value,
        "evaluated_through_chapter": value.evaluated_through_chapter,
        "remaining_chapter_budget": remaining,
        "ending_contract_reachable": reachable,
        **checks,
        "replan_required": not reachable,
        "reasons": list(reasons),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return EndingReachabilityReport(
        status=status,
        evaluated_through_chapter=value.evaluated_through_chapter,
        remaining_chapter_budget=remaining,
        ending_contract_reachable=reachable,
        critical_arc_closure_path=checks["critical_arc_closure_path"],
        chapter_budget_sufficient=checks["chapter_budget_sufficient"],
        required_event_windows_open=checks["required_event_windows_open"],
        promise_capacity_sufficient=checks["promise_capacity_sufficient"],
        replan_required=not reachable,
        reasons=reasons,
        report_hash=f"sha256:{digest}",
    )


def required_arc_contributions(content: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    raw = content.get("required_arc_contributions") or ()
    result: dict[str, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, Mapping):
            raise ValueError("required Arc contribution must be an object")
        arc_id = str(item.get("arc_plan_version_id") or item.get("arc_id") or "")
        if not arc_id or arc_id in result:
            raise ValueError("required Arc contribution identity must be unique")
        result[arc_id] = dict(item)
    return result


__all__ = [
    "ArcStatus",
    "EndingReachability",
    "EndingReachabilityInput",
    "EndingReachabilityReport",
    "SupervisorAction",
    "evaluate_ending_reachability",
    "required_arc_contributions",
]
