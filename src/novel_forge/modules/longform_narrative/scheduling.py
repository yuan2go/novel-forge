from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError

from .reducers import normalize_frozen_arc_plan


ARC_WORKING_SET_POLICY_VERSION = "accepted-reality-arc-working-set-v1"
_CHAPTER_SCHEDULE_POLICY_VERSION = "frozen-chapter-arc-working-set-v2"
_TERMINAL_LIFECYCLES = frozenset({"COMPLETED", "ABANDONED"})
_REPLAN_DECISIONS = frozenset({"REPLAN_REQUIRED"})


def _hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _identity(value: Mapping[str, Any]) -> str:
    return str(value.get("arc_plan_version_id") or value.get("arc_id") or "")


def _schedule_preferences(
    schedule_row: Mapping[str, Any] | None,
) -> dict[str, str]:
    return {
        _identity(item): str(item.get("action") or "").upper()
        for item in (schedule_row or {}).get("arc_cadence") or ()
        if isinstance(item, Mapping) and _identity(item)
    }


def _capacity(
    *, limits: Mapping[str, Any], schedule_row: Mapping[str, Any] | None
) -> tuple[int, str]:
    maximum = int(limits.get("max_active_arcs") or 3)
    if maximum <= 0:
        raise KernelError(
            "ARC_WORKING_SET_CAPACITY_INVALID",
            "Narrative Load Policy must permit at least one active Arc",
        )
    density = str((schedule_row or {}).get("narrative_density") or "").upper()
    density_hint = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}.get(density, maximum)
    return min(maximum, density_hint), density or "POLICY_DEFAULT"


def _obligation_evaluation(item: Mapping[str, Any]) -> Mapping[str, Any]:
    state = item.get("state")
    if not isinstance(state, Mapping):
        return {}
    evaluation = state.get("accepted_evaluation")
    return evaluation if isinstance(evaluation, Mapping) else {}


def _linked_arc_ids(item: Mapping[str, Any]) -> set[str]:
    state = item.get("state")
    if not isinstance(state, Mapping):
        return set()
    return {str(value) for value in state.get("linked_arc_ids") or () if str(value)}


def _obligation_id(item: Mapping[str, Any]) -> str:
    state = item.get("state")
    if not isinstance(state, Mapping):
        state = {}
    return str(state.get("obligation_id") or item.get("entity_key") or "")


def _target_window_status(plan: Mapping[str, Any], chapter_number: int) -> str:
    window = plan.get("target_window")
    if not isinstance(window, Mapping) or window.get("status") != "SCHEDULED":
        return "UNKNOWN"
    start = int(window.get("from_chapter") or 0)
    end = int(window.get("to_chapter") or 0)
    if chapter_number > end:
        return "OVERDUE"
    if chapter_number < start:
        return "BEFORE_WINDOW"
    return "IN_WINDOW"


def _selected_action(candidate: Mapping[str, Any]) -> str:
    preferred = str(candidate.get("cadence_preference") or "")
    if candidate.get("working_progress", {}).get("status") == "UNASSESSED":
        return preferred if preferred in {"REACTIVATE", "SETUP", "ADVANCE", "TOUCH"} else "ADVANCE"
    debt = candidate.get("obligation_debt") or {}
    if int(debt.get("overdue_count") or 0) or (
        candidate.get("target_window_status") == "OVERDUE"
    ):
        return "PAYOFF"
    if candidate.get("payoff_readiness") == "READY":
        return "PAYOFF"
    if preferred in {"PAYOFF", "REACTIVATE", "SETUP", "ADVANCE", "TOUCH"}:
        return preferred
    if int(candidate.get("dormant_chapters") or 0) > 0:
        return "REACTIVATE"
    return "ADVANCE"


def _chapter_required_arc_ids(
    schedule_row: Mapping[str, Any] | None,
    *, chapter_number: int, arc_ids: set[str], maximum: int,
) -> set[str] | None:
    if schedule_row is None or "required_arc_contributions" not in schedule_row:
        return None
    contributions = schedule_row["required_arc_contributions"]
    cadence = schedule_row.get("arc_cadence")
    if (
        schedule_row.get("chapter_number") != chapter_number
        or not isinstance(contributions, list)
        or not isinstance(cadence, list)
        or any(not isinstance(item, Mapping) for item in contributions + cadence)
    ):
        raise KernelError("ARC_WORKING_SET_CHAPTER_SCHEDULE_INVALID", "Frozen Chapter row must match its target and declare contributions and cadence")
    required = [_identity(item) for item in contributions]
    cadence_ids = [_identity(item) for item in cadence]
    actions = {"PAYOFF", "REACTIVATE", "SETUP", "ADVANCE", "TOUCH", "DORMANT"}
    if (
        not required
        or "" in required
        or len(set(required)) != len(required)
        or not set(required) <= arc_ids
        or "" in cadence_ids
        or len(set(cadence_ids)) != len(cadence_ids)
        or not set(cadence_ids) <= arc_ids
        or any(str(item.get("action") or "").upper() not in actions for item in cadence)
        or set(required) != {
            _identity(item) for item in cadence
            if str(item.get("action") or "").upper() != "DORMANT"
        }
    ):
        raise KernelError("ARC_WORKING_SET_CHAPTER_SCHEDULE_INVALID", "Frozen Chapter contributions must be unique legal Arcs with matching non-dormant cadence")
    if len(required) > maximum:
        raise KernelError("ARC_WORKING_SET_CHAPTER_CAPACITY_EXCEEDED", "Frozen Chapter contributions exceed the governed active-Arc capacity; return to Planning/Plan Change")
    return set(required)


def build_arc_working_set(
    *,
    project_id: str,
    book_id: str,
    chapter_number: int,
    arc_plan_snapshots: Mapping[str, Mapping[str, Any]],
    accepted_projection: Mapping[str, Any] | None,
    accepted_narrative_state: Mapping[str, Any],
    narrative_load_policy: Mapping[str, Any],
    schedule_row: Mapping[str, Any] | None = None,
    reader_intent: Mapping[str, Any] | None = None,
    working_manuscript: Mapping[str, Any] | None = None,
) -> dict[str, Any]:

    if (
        not project_id.strip()
        or not book_id.strip()
        or chapter_number <= 0
        or not arc_plan_snapshots
    ):
        raise KernelError(
            "ARC_WORKING_SET_INPUT_INVALID",
            "Arc working-set selection requires Book scope, chapter, and Arc plans",
        )
    projection = dict(accepted_projection or {})
    boundary = dict(projection.get("accepted_boundary") or {})
    accepted_through = int(boundary.get("chapter_number") or 0)
    working_bound = working_manuscript and working_manuscript.get("target_chapter") == chapter_number and working_manuscript.get("accepted_through_chapter") == accepted_through and working_manuscript.get("book_id") == book_id and working_manuscript.get("project_id") == project_id
    if accepted_through != chapter_number - 1 and not (working_bound and accepted_through < chapter_number):
        raise KernelError(
            "ARC_WORKING_SET_BOUNDARY_STALE",
            "Arc working set must be computed from the immediately preceding accepted boundary",
        )
    working_schedule = bool(working_bound and accepted_through < chapter_number - 1
        and working_manuscript.get("scheduling_policy"))
    if working_schedule:
        from novel_forge.modules.book_authority.working_prose import WORKING_SCHEDULE_POLICY, WORKING_SCHEDULE_INSTRUCTION, validate_working_projection
        if (working_manuscript["scheduling_policy"] != WORKING_SCHEDULE_POLICY
                or working_manuscript.get("projection_policy", {}).get("version") not in {"working-prose-projection.v3", "working-prose-projection.v4"}):
            raise KernelError("ARC_WORKING_SCHEDULE_POLICY_INVALID", "Require the frozen working-story schedule contract")
        validate_working_projection(working_manuscript, project_id=project_id, book_id=book_id,
            target_chapter=chapter_number, accepted_through_chapter=accepted_through)
    state_content = accepted_narrative_state.get("content")
    if not isinstance(state_content, Mapping):
        raise KernelError(
            "ARC_WORKING_SET_NARRATIVE_STATE_INVALID",
            "Arc scheduling requires the frozen accepted Narrative State",
        )
    state_boundary = int(state_content.get("accepted_through_chapter") or 0)
    current_state = state_content.get("current_state")
    if (
        state_boundary != accepted_through
        or not str(accepted_narrative_state.get("asset_version_id") or "")
        or not str(accepted_narrative_state.get("content_hash") or "")
        or not isinstance(current_state, Mapping)
    ):
        raise KernelError(
            "ARC_WORKING_SET_NARRATIVE_STATE_STALE",
            "Arc scheduling Narrative State differs from the accepted projection boundary",
        )
    limits = narrative_load_policy.get("limits")
    if not isinstance(limits, Mapping):
        limits = narrative_load_policy
    capacity, capacity_source = _capacity(
        limits=limits, schedule_row=schedule_row
    )
    preferences = _schedule_preferences(schedule_row)
    required_ids = _chapter_required_arc_ids(
        schedule_row, chapter_number=chapter_number,
        arc_ids=set(arc_plan_snapshots), maximum=int(limits.get("max_active_arcs") or 3),
    )
    states = {
        _identity(item): dict(item)
        for item in projection.get("arc_states") or ()
        if isinstance(item, Mapping) and _identity(item)
    }
    checkpoints = {
        _identity(item): dict(item)
        for item in projection.get("arc_checkpoints") or ()
        if isinstance(item, Mapping) and _identity(item)
    }
    progress = {
        _identity(item): dict(item)
        for item in projection.get("arc_progress") or ()
        if isinstance(item, Mapping) and _identity(item)
    }
    obligations = [
        dict(item)
        for item in projection.get("obligation_states") or ()
        if isinstance(item, Mapping)
    ]
    lifecycle_by_arc = {
        arc_id: str(state.get("lifecycle_status") or "READY").upper()
        for arc_id, state in states.items()
    }
    max_dormant_age = int(limits.get("max_dormant_arc_age") or 30)
    candidates: list[dict[str, Any]] = []

    for arc_id, raw_plan in sorted(arc_plan_snapshots.items()):
        plan = normalize_frozen_arc_plan(
            arc_plan_version_id=arc_id, content=raw_plan
        )
        state = states.get(arc_id, {})
        checkpoint = checkpoints.get(arc_id, {})
        latest_progress = progress.get(arc_id, {})
        lifecycle = str(state.get("lifecycle_status") or "READY").upper()
        dependency_states = {
            dependency_id: lifecycle_by_arc.get(dependency_id, "UNKNOWN")
            for dependency_id in plan.get("dependency_arc_ids") or ()
        }
        accepted_dependency_blockers = sorted(
            dependency_id
            for dependency_id, status in dependency_states.items()
            if status != "COMPLETED"
        )
        dependency_assessments = accepted_dependency_blockers if working_schedule else []
        dependency_blockers = [identity for identity in accepted_dependency_blockers
            if dependency_states[identity] == "ABANDONED"] if working_schedule else accepted_dependency_blockers
        linked_obligations = [
            item for item in obligations if arc_id in _linked_arc_ids(item)
        ]
        overdue = sorted(
            _obligation_id(item)
            for item in linked_obligations
            if _obligation_evaluation(item).get("overdue")
        )
        due = sorted(
            _obligation_id(item)
            for item in linked_obligations
            if _obligation_evaluation(item).get("due")
        )
        stale = sorted(
            _obligation_id(item)
            for item in linked_obligations
            if _obligation_evaluation(item).get("stale")
        )
        violated = sorted(
            _obligation_id(item)
            for item in linked_obligations
            if _obligation_evaluation(item).get("violated")
        )
        last_material = int(state.get("last_material_progress_chapter") or 0)
        dormant_chapters = (
            accepted_through - last_material
            if accepted_through > 0 and last_material > 0
            else accepted_through
        )
        window_status = _target_window_status(plan, chapter_number)
        decision = str(checkpoint.get("decision") or "NOT_EVALUATED").upper()
        current_phase = str(state.get("current_phase") or "").upper()
        cumulative_progress = int(state.get("cumulative_progress_units") or 0)
        target_progress = int(
            state.get("target_progress_units")
            or plan.get("target_progress_units")
            or 0
        )
        payoff_readiness = (
            "READY"
            if current_phase in {"CRISIS", "CLIMAX", "PAYOFF"}
            or (
                target_progress > 1
                and cumulative_progress > 0
                and cumulative_progress / target_progress >= 0.75
            )
            else "NOT_READY"
        )
        eligible = True
        reasons: list[str] = []
        if lifecycle in _TERMINAL_LIFECYCLES:
            eligible = False
            reasons.append(f"TERMINAL_{lifecycle}")
        if dependency_blockers:
            eligible = False
            reasons.append("DEPENDENCY_NOT_COMPLETED")
        if decision in _REPLAN_DECISIONS and (
            (checkpoint.get("dependency_blockers") and not working_schedule)
            or checkpoint.get("violated_obligation_ids")
        ):
            eligible = False
            reasons.append("CHECKPOINT_REPLAN_REQUIRED")

        preferred = preferences.get(arc_id, "")
        score = 0
        if preferred and preferred != "DORMANT":
            score += {
                "PAYOFF": 35,
                "REACTIVATE": 30,
                "ADVANCE": 25,
                "SETUP": 18,
                "TOUCH": 10,
            }.get(preferred, 0)
            reasons.append(f"GROUP_CADENCE_{preferred}")
        elif preferred == "DORMANT":
            score -= 15
            reasons.append("GROUP_CADENCE_DORMANT")
        if overdue:
            score += 50 + min(20, len(overdue) * 5)
            reasons.append("OBLIGATION_OVERDUE")
        if due:
            score += 35 + min(15, len(due) * 5)
            reasons.append("OBLIGATION_DUE")
        if stale:
            score += 20
            reasons.append("OBLIGATION_STALE")
        if window_status == "OVERDUE":
            score += 40
            reasons.append("TARGET_WINDOW_OVERDUE")
        elif window_status == "IN_WINDOW":
            score += 15
            reasons.append("TARGET_WINDOW_ACTIVE")
        elif window_status == "BEFORE_WINDOW":
            score -= 10
            reasons.append("TARGET_WINDOW_NOT_OPEN")
        if decision == "CORRECT":
            score += 20
            reasons.append("CHECKPOINT_CORRECTION_DUE")
        if payoff_readiness == "READY" and not working_schedule:
            score += 12
            reasons.append("ACCEPTED_PHASE_PAYOFF_READY")
        if not working_schedule and dormant_chapters > 0 and lifecycle not in _TERMINAL_LIFECYCLES:
            score += min(25, dormant_chapters)
            reasons.append("STARVATION_PRESSURE")
        if (
            not working_schedule and max_dormant_age > 0
            and dormant_chapters >= max_dormant_age
            and lifecycle not in _TERMINAL_LIFECYCLES
        ):
            score += 25
            reasons.append("DORMANCY_LIMIT_REACHED")
        if int(latest_progress.get("progress_units") or 0) > 0:
            score += 5
            reasons.append("RECENT_CAUSAL_CONTINUITY")
        reader_reward = str((reader_intent or {}).get("reward_mode") or "").upper()
        if reader_reward == "PAYOFF" and (overdue or due or window_status == "OVERDUE"):
            score += 10
            reasons.append("READER_PAYOFF_INTENT")
        if not reasons:
            reasons.append("LEGAL_ARC_BASELINE")
        candidates.append(
            {
                "arc_plan_version_id": arc_id,
                "eligible": eligible,
                "score": score,
                "lifecycle_status": "UNASSESSED" if working_schedule and lifecycle not in _TERMINAL_LIFECYCLES else lifecycle,
                "observation_status": str(
                    state.get("observation_status") or "NOT_MATERIALIZED"
                ),
                "current_phase": "UNASSESSED" if working_schedule else current_phase,
                "cumulative_progress_units": None if working_schedule else cumulative_progress,
                "target_progress_units": target_progress,
                "payoff_readiness": "UNASSESSED" if working_schedule else payoff_readiness,
                "last_material_progress_chapter": None if working_schedule else last_material,
                "dormant_chapters": None if working_schedule else dormant_chapters,
                "dependency_states": {key: "UNASSESSED" if key in dependency_assessments else value
                    for key,value in dependency_states.items()} if working_schedule else dependency_states,
                "dependency_blockers": dependency_blockers,
                **({"working_progress": {"status": "UNASSESSED", "basis": "SELECTED_WORKING_PROSE",
                    "snapshot_hash": working_manuscript["snapshot_hash"],
                    "through_chapter": chapter_number - 1, "accepted_dependency_states": dependency_states,
                    "dependency_assessment_required": dependency_assessments,
                    "instruction": WORKING_SCHEDULE_INSTRUCTION}} if working_schedule else {}),
                "target_window_status": window_status,
                "checkpoint_decision": decision,
                "cadence_preference": preferred,
                "obligation_debt": {
                    "due_ids": due,
                    "overdue_ids": overdue,
                    "stale_ids": stale,
                    "violated_ids": violated,
                    "due_count": len(due),
                    "overdue_count": len(overdue),
                    "stale_count": len(stale),
                },
                "reasons": reasons,
            }
        )

    ranked = sorted(
        (item for item in candidates if item["eligible"]),
        key=lambda item: (-int(item["score"]), item["arc_plan_version_id"]),
    )
    if required_ids is not None:
        ranked = [item for item in ranked if item["arc_plan_version_id"] in required_ids]
        if {item["arc_plan_version_id"] for item in ranked} != required_ids:
            raise KernelError("ARC_WORKING_SET_CHAPTER_ARC_ILLEGAL", "A required frozen Chapter Arc is no longer eligible; return to Planning/Plan Change")
        capacity = len(required_ids)
        capacity_source = "FROZEN_CHAPTER_SCHEDULE"
    if not ranked:
        raise KernelError(
            "ARC_WORKING_SET_EMPTY",
            "No legal Arc is available at the accepted narrative boundary",
        )
    selected: list[dict[str, Any]] = []
    for ordinal, candidate in enumerate(ranked[:capacity]):
        role = "PRIMARY" if ordinal == 0 else "SECONDARY" if ordinal == 1 else "TOUCH"
        selected.append(
            {
                "arc_plan_version_id": candidate["arc_plan_version_id"],
                "role": role,
                "action": candidate["cadence_preference"] if required_ids is not None else _selected_action(candidate),
                "score": candidate["score"],
                "reason_codes": list(candidate["reasons"]),
            }
        )
    selected_ids = {item["arc_plan_version_id"] for item in selected}
    preferred_ids = {
        arc_id for arc_id, action in preferences.items() if action != "DORMANT"
    }
    correction = {
        "status": (
            "CORRECTED_FROM_GROUP_CADENCE"
            if preferred_ids and preferred_ids != selected_ids
            else "GROUP_CADENCE_CONFIRMED"
            if preferred_ids
            else "NO_GROUP_CADENCE"
        ),
        "added_arc_plan_version_ids": sorted(selected_ids - preferred_ids),
        "removed_arc_plan_version_ids": sorted(preferred_ids - selected_ids),
    }
    body = {
        "type": "ArcWorkingSet",
        "contract_version": "arc-working-set-v1",
        "policy_version": "working-story-schedule.v1" if working_schedule else _CHAPTER_SCHEDULE_POLICY_VERSION if required_ids is not None else ARC_WORKING_SET_POLICY_VERSION,
        "project_id": project_id,
        "book_id": book_id,
        "target_chapter": chapter_number,
        "accepted_reality": {
            "accepted_through_chapter": accepted_through,
            "projection_set_id": str(projection.get("projection_set_id") or ""),
            "projection_hash": str(projection.get("projection_hash") or ""),
            "source_story_state_asset_version_id": str(
                projection.get("source_story_state_asset_version_id") or ""
            ),
            "actual_only": True,
            "narrative_state": {
                "asset_version_id": str(
                    accepted_narrative_state.get("asset_version_id") or ""
                ),
                "content_hash": str(
                    accepted_narrative_state.get("content_hash") or ""
                ),
                "accepted_through_chapter": state_boundary,
                "state_kind_counts": {
                    str(kind): len(values) if isinstance(values, list) else 0
                    for kind, values in sorted(current_state.items())
                },
            },
        },
        "planning_horizon": {
            "scope": "CHAPTER",
            "chapter": chapter_number,
        },
        "capacity": {
            "maximum_active_arcs": capacity,
            "narrative_load_policy_hash": str(
                narrative_load_policy.get("policy_hash") or ""
            ),
            "source": capacity_source,
        },
        "reader_intent": dict(reader_intent or {}),
        "schedule_correction": correction,
        "selected_contributions": selected,
        "candidates": candidates,
        "deferred_arc_plan_version_ids": sorted(
            set(arc_plan_snapshots) - selected_ids
        ),
        "authority_boundary": {
            "selection_is_future_intent": True,
            "actual_progress_requires_accepted_chapter_outcome": True,
        },
    }
    if working_manuscript:
        body["working_manuscript"] = dict(working_manuscript)
    return {**body, "working_set_digest": _hash(body)}


__all__ = ["ARC_WORKING_SET_POLICY_VERSION", "build_arc_working_set"]
