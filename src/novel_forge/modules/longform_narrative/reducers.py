"""Deterministic accepted-evidence reducers for long-form narrative state."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError

from .contracts import ArcCheckpointDecision, ArcObservationStatus, ArcProgress


_OBSERVATION_ZERO_ONLY = frozenset(
    {
        ArcObservationStatus.NOT_OBSERVED,
        ArcObservationStatus.NOT_MATERIALIZED,
        ArcObservationStatus.UNKNOWN,
    }
)


def _text_items(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise KernelError("ARC_EVIDENCE_INVALID", "Arc evidence list field is invalid")
    items = [str(item).strip() for item in value if str(item).strip()]
    return list(dict.fromkeys(items))


def normalize_arc_evidence(
    *,
    declared: Mapping[str, Mapping[str, Any]],
    raw_evidence: Iterable[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Normalize actual observations without ever copying PLAN payload into ACTUAL."""

    declared_ids = tuple(str(key) for key in declared if str(key))
    observed: dict[str, dict[str, Any]] = {}
    for raw_value in raw_evidence:
        raw = dict(raw_value)
        arc_plan_version_id = str(
            raw.get("arc_plan_version_id") or raw.get("arc_id") or ""
        ).strip()
        if not arc_plan_version_id or arc_plan_version_id not in declared_ids:
            raise KernelError(
                "ARC_EVIDENCE_UNDECLARED",
                "actual Arc evidence must reference a declared ChapterPlan Arc",
            )
        if arc_plan_version_id in observed:
            raise KernelError("ARC_EVIDENCE_DUPLICATE", "Arc evidence is duplicated")
        try:
            status = ArcObservationStatus(
                str(raw.get("observation_status") or "UNKNOWN").upper()
            )
        except ValueError as exc:
            raise KernelError(
                "ARC_OBSERVATION_STATUS_INVALID",
                "Arc evidence observation status is invalid",
            ) from exc
        progress_units = int(raw.get("progress_units") or 0)
        if progress_units < 0:
            raise KernelError("ARC_PROGRESS_INVALID", "Arc progress cannot be negative")
        if status in _OBSERVATION_ZERO_ONLY and progress_units:
            raise KernelError(
                "ARC_UNOBSERVED_PROGRESS_FORBIDDEN",
                "unobserved Arc evidence cannot advance progress",
            )
        resolution_evidence = _text_items(raw.get("resolution_evidence"))
        if status is ArcObservationStatus.OBSERVED and not resolution_evidence:
            raise KernelError(
                "ARC_OBSERVED_EVIDENCE_REQUIRED",
                "observed Arc evidence requires actual resolution evidence",
            )
        contribution_kind = str(raw.get("contribution_kind") or "").upper()
        if not contribution_kind:
            contribution_kind = (
                "UNOBSERVED"
                if status is ArcObservationStatus.NOT_OBSERVED
                else status.value
            )
        observed[arc_plan_version_id] = {
            "arc_plan_version_id": arc_plan_version_id,
            "observation_status": status.value,
            "contribution_kind": contribution_kind,
            "progress_units": progress_units,
            "effect_dimensions": _text_items(raw.get("effect_dimensions")),
            "milestone_ids": _text_items(raw.get("milestone_ids")),
            "actual_consequences": _text_items(raw.get("actual_consequences")),
            "obligation_ids": _text_items(raw.get("obligation_ids")),
            "resolution_evidence": resolution_evidence,
            "completion_criterion_ids": _text_items(
                raw.get("completion_criterion_ids")
            ),
            "phase_to": str(raw.get("phase_to") or ""),
        }
    for arc_plan_version_id in declared_ids:
        observed.setdefault(
            arc_plan_version_id,
            {
                "arc_plan_version_id": arc_plan_version_id,
                "observation_status": ArcObservationStatus.NOT_OBSERVED.value,
                "contribution_kind": "UNOBSERVED",
                "progress_units": 0,
                "effect_dimensions": [],
                "milestone_ids": [],
                "actual_consequences": [],
                "obligation_ids": [],
                "resolution_evidence": [],
                "completion_criterion_ids": [],
                "phase_to": "",
            },
        )
    return tuple(observed[arc_id] for arc_id in declared_ids)


def build_arc_progress(
    *,
    project_id: str,
    book_id: str,
    chapter_number: int,
    acceptance_operation_id: str,
    chapter_outcome_asset_version_id: str,
    arc_plan_version_id: str,
    previous_progress_units: int,
    evidence: Mapping[str, Any],
    expected_progress_units: int | None = None,
) -> dict[str, Any]:
    try:
        observation = ArcObservationStatus(
            str(evidence.get("observation_status") or "UNKNOWN")
        )
    except ValueError as exc:
        raise KernelError("ARC_OBSERVATION_STATUS_INVALID", "Arc observation is invalid") from exc
    progress_units = int(evidence.get("progress_units") or 0)
    if previous_progress_units < 0 or progress_units < 0:
        raise KernelError("ARC_PROGRESS_INVALID", "Arc progress cannot be negative")
    if observation in _OBSERVATION_ZERO_ONLY and progress_units:
        raise KernelError(
            "ARC_UNOBSERVED_PROGRESS_FORBIDDEN",
            "unobserved or unknown Arc evidence cannot advance progress",
        )
    identity = "|".join(
        (
            project_id,
            book_id,
            arc_plan_version_id,
            str(chapter_number),
            acceptance_operation_id,
        )
    )
    progress = ArcProgress(
        progress_id="arc-progress:" + hashlib.sha256(identity.encode()).hexdigest(),
        project_id=project_id,
        book_id=book_id,
        arc_plan_version_id=arc_plan_version_id,
        chapter_number=chapter_number,
        acceptance_operation_id=acceptance_operation_id,
        chapter_outcome_asset_version_id=chapter_outcome_asset_version_id,
        observation_status=observation,
        contribution_kind=str(evidence.get("contribution_kind") or observation.value),
        progress_units=progress_units,
        cumulative_progress_units=previous_progress_units + progress_units,
        deviation_units=(
            progress_units - expected_progress_units
            if expected_progress_units is not None
            and observation not in _OBSERVATION_ZERO_ONLY
            else None
        ),
        evidence={
            "effect_dimensions": _text_items(evidence.get("effect_dimensions")),
            "milestone_ids": _text_items(evidence.get("milestone_ids")),
            "actual_consequences": _text_items(evidence.get("actual_consequences")),
            "obligation_ids": _text_items(evidence.get("obligation_ids")),
            "resolution_evidence": _text_items(evidence.get("resolution_evidence")),
            "completion_criterion_ids": _text_items(
                evidence.get("completion_criterion_ids")
            ),
        },
    )
    return progress.to_dict()


def build_arc_checkpoint(
    *,
    progress: Mapping[str, Any],
    target_progress_units: int,
    completion_criteria_satisfied: bool,
    overdue_obligation_ids: Iterable[str],
    dependency_blockers: Iterable[str],
    stale_obligation_ids: Iterable[str] = (),
    violated_obligation_ids: Iterable[str] = (),
    unknown_dependency_ids: Iterable[str] = (),
    plan_evaluation_status: str = "OBSERVED",
    target_window_status: str = "IN_WINDOW",
) -> dict[str, Any]:
    boundary = dict(progress.get("accepted_boundary") or {})
    observation = ArcObservationStatus(
        str(progress.get("observation_status") or "UNKNOWN")
    )
    overdue = tuple(dict.fromkeys(str(item) for item in overdue_obligation_ids if str(item)))
    blockers = tuple(dict.fromkeys(str(item) for item in dependency_blockers if str(item)))
    stale = tuple(dict.fromkeys(str(item) for item in stale_obligation_ids if str(item)))
    violated = tuple(
        dict.fromkeys(str(item) for item in violated_obligation_ids if str(item))
    )
    unknown_dependencies = tuple(
        dict.fromkeys(str(item) for item in unknown_dependency_ids if str(item))
    )
    cumulative = int(progress.get("cumulative_progress_units") or 0)
    reasons: list[str] = []
    if blockers:
        decision = ArcCheckpointDecision.REPLAN_REQUIRED
        reasons.append("DEPENDENCY_BLOCKED")
    elif violated:
        decision = ArcCheckpointDecision.REPLAN_REQUIRED
        reasons.append("OBLIGATION_VIOLATED")
    elif target_window_status == "OVERDUE":
        decision = ArcCheckpointDecision.REPLAN_REQUIRED
        reasons.append("ARC_TARGET_WINDOW_OVERDUE")
    elif overdue:
        decision = ArcCheckpointDecision.CORRECT
        reasons.append("OBLIGATION_OVERDUE")
    elif stale:
        decision = ArcCheckpointDecision.CORRECT
        reasons.append("OBLIGATION_STALE")
    elif unknown_dependencies:
        decision = ArcCheckpointDecision.UNKNOWN
        reasons.append("DEPENDENCY_UNKNOWN")
    elif plan_evaluation_status != "OBSERVED":
        decision = ArcCheckpointDecision.UNKNOWN
        reasons.append("ARC_PLAN_EVALUATION_UNKNOWN")
    elif observation in {ArcObservationStatus.NOT_OBSERVED, ArcObservationStatus.UNKNOWN}:
        decision = ArcCheckpointDecision.UNKNOWN
        reasons.append(observation.value)
    elif completion_criteria_satisfied and cumulative >= target_progress_units:
        decision = ArcCheckpointDecision.COMPLETED
        reasons.append("COMPLETION_CRITERIA_SATISFIED")
    elif observation is ArcObservationStatus.NOT_MATERIALIZED:
        decision = ArcCheckpointDecision.CONTINUE
        reasons.append("NOT_SCHEDULED_THIS_CHAPTER")
    elif int(progress.get("progress_units") or 0) == 0:
        decision = ArcCheckpointDecision.CORRECT
        reasons.append("NO_MATERIAL_PROGRESS")
    else:
        decision = ArcCheckpointDecision.CONTINUE
        reasons.append("PROGRESS_OBSERVED")
    progress_id = str(progress.get("progress_id") or "")
    checkpoint_identity = "|".join(
        (
            str(progress.get("arc_plan_version_id") or ""),
            str(boundary.get("chapter_number") or ""),
            str(boundary.get("acceptance_operation_id") or ""),
            progress_id,
        )
    )
    return {
        "type": "ArcCheckpoint",
        "contract_version": "arc-checkpoint-v1",
        "checkpoint_id": "arc-checkpoint:"
        + hashlib.sha256(checkpoint_identity.encode()).hexdigest(),
        "arc_plan_version_id": str(progress.get("arc_plan_version_id") or ""),
        "accepted_boundary": boundary,
        "progress_id": progress_id,
        "decision": decision,
        "reasons": reasons,
        "overdue_obligation_ids": list(overdue),
        "stale_obligation_ids": list(stale),
        "violated_obligation_ids": list(violated),
        "dependency_blockers": list(blockers),
        "unknown_dependency_ids": list(unknown_dependencies),
        "plan_evaluation_status": plan_evaluation_status,
        "target_window_status": target_window_status,
    }


def _criterion_id(arc_plan_version_id: str, ordinal: int, criterion: str) -> str:
    identity = f"{arc_plan_version_id}|{ordinal}|{criterion}"
    return "arc-criterion:" + hashlib.sha256(identity.encode()).hexdigest()


def normalize_frozen_arc_plan(
    *, arc_plan_version_id: str, content: Mapping[str, Any]
) -> dict[str, Any]:
    """Adapt the canonical Planning Arc asset without creating another Plan authority."""

    closure = tuple(
        str(item).strip() for item in content.get("closure_conditions") or ()
        if str(item).strip()
    )
    criteria = [
        {"criterion_id": _criterion_id(arc_plan_version_id, index, item), "text": item}
        for index, item in enumerate(closure, start=1)
    ]
    dependencies = list(
        dict.fromkeys(
            str(item).strip() for item in content.get("dependencies") or ()
            if str(item).strip()
        )
    )
    logical_key = str(content.get("logical_key") or "")
    for relation in content.get("arc_relations") or ():
        if not isinstance(relation, Mapping):
            continue
        source = str(relation.get("source_arc_ref") or "")
        target = str(relation.get("target_arc_ref") or "")
        if source and source != arc_plan_version_id and target in {
            logical_key,
            arc_plan_version_id,
        }:
            dependencies.append(source)
    dependencies = list(dict.fromkeys(dependencies))
    window = content.get("target_window")
    if isinstance(window, Mapping):
        start = int(window.get("from_chapter") or window.get("start_chapter") or 0)
        end = int(window.get("to_chapter") or window.get("end_chapter") or 0)
        window_status = "SCHEDULED" if start > 0 and end >= start else "UNKNOWN"
    else:
        start = end = 0
        window_status = "UNKNOWN"
    target_units = int(content.get("target_progress_units") or len(criteria) or 0)
    observed = bool(str(content.get("objective") or "").strip() and criteria)
    return {
        "arc_plan_version_id": arc_plan_version_id,
        "logical_key": logical_key,
        "objective": str(content.get("objective") or ""),
        "completion_criteria": criteria,
        "dependency_arc_ids": list(dependencies),
        "target_window": {
            "status": window_status,
            "from_chapter": start,
            "to_chapter": end,
        },
        "target_progress_units": target_units,
        "expected_milestone_ids": [
            str(item.get("segment_id") or "")
            for item in content.get("arc_segments") or ()
            if isinstance(item, Mapping) and str(item.get("segment_id") or "")
        ],
        "evaluation_status": "OBSERVED" if observed else "UNKNOWN",
        "source_contract_version": str(content.get("contract_version") or ""),
    }


def reduce_accepted_obligations(
    *, entries: Iterable[Mapping[str, Any]], chapter_number: int
) -> list[dict[str, Any]]:
    """Evaluate lifecycle from accepted state and chapter coordinates only."""

    source = [dict(item) for item in entries]
    base: dict[str, dict[str, Any]] = {}
    for entry in source:
        state = dict(entry.get("state") or {})
        obligation_id = str(state.get("obligation_id") or entry.get("entity_key") or "")
        if obligation_id:
            base[obligation_id] = state
    evaluations: dict[str, dict[str, Any]] = {}
    for obligation_id, state in base.items():
        status = str(state.get("status") or "UNKNOWN").upper()
        window = dict(state.get("target_window") or {})
        window_status = str(window.get("status") or "UNKNOWN").upper()
        start = int(window.get("from_chapter") or 0)
        end = int(window.get("to_chapter") or 0)
        payoff = dict(state.get("payoff_evidence") or state.get("actual_payoff") or {})
        resolution = state.get("resolution_evidence") or ()
        fulfilled = status == "FULFILLED" and bool(payoff or resolution)
        violated = status in {"VIOLATED", "CANCELLED"} and bool(
            state.get("violation_evidence") or resolution
        )
        overdue = bool(
            not fulfilled and not violated and window_status == "SCHEDULED"
            and end > 0 and chapter_number > end
        )
        due = bool(
            not fulfilled and not violated and window_status == "SCHEDULED"
            and start > 0 and start <= chapter_number <= end
        )
        history_chapters = [
            int(item.get("chapter") or 0)
            for item in state.get("development_history") or ()
            if isinstance(item, Mapping)
        ]
        last_observed = max(
            [int(state.get("opened_chapter") or 0), *history_chapters], default=0
        )
        stale_after = int(state.get("stale_after_chapters") or 3)
        stale = bool(
            not fulfilled and not violated and last_observed > 0
            and chapter_number - last_observed >= stale_after
        )
        lifecycle = (
            "FULFILLED" if fulfilled else "VIOLATED" if violated else
            "OVERDUE" if overdue else "STALE" if stale else "DUE" if due else
            "OPEN" if status != "UNKNOWN" else "UNKNOWN"
        )
        evaluations[obligation_id] = {
            "lifecycle": lifecycle,
            "due": due,
            "overdue": overdue,
            "stale": stale,
            "fulfilled": fulfilled,
            "violated": violated,
            "evaluated_at_chapter": chapter_number,
            "policy_version": "accepted-obligation-lifecycle-v1",
            "payoff_evidence": payoff,
        }
    result: list[dict[str, Any]] = []
    for entry in source:
        state = dict(entry.get("state") or {})
        obligation_id = str(state.get("obligation_id") or entry.get("entity_key") or "")
        evaluation = dict(evaluations.get(obligation_id) or {"lifecycle": "UNKNOWN"})
        dependency_ids = [str(item) for item in state.get("dependencies") or () if str(item)]
        unresolved: list[str] = []
        blocked: list[str] = []
        unknown: list[str] = []
        for dependency_id in dependency_ids:
            dependency = evaluations.get(dependency_id)
            if dependency is None or dependency.get("lifecycle") == "UNKNOWN":
                unknown.append(dependency_id)
            elif dependency.get("fulfilled"):
                continue
            elif dependency.get("violated"):
                blocked.append(dependency_id)
            else:
                unresolved.append(dependency_id)
        evaluation["dependency_state"] = (
            "BLOCKED" if blocked else "UNKNOWN" if unknown else
            "UNRESOLVED" if unresolved else "SATISFIED"
        )
        evaluation["unresolved_dependency_ids"] = unresolved
        evaluation["blocked_dependency_ids"] = blocked
        evaluation["unknown_dependency_ids"] = unknown
        result.append({**entry, "state": {**state, "accepted_evaluation": evaluation}})
    return result


def build_longform_projection_set(
    *,
    project_id: str,
    book_id: str,
    book_run_id: str,
    chapter_request_id: str,
    chapter_number: int,
    acceptance_id: str,
    acceptance_operation_id: str,
    chapter_outcome_asset_version_id: str,
    story_state_asset_version_id: str,
    canon_snapshot_asset_version_id: str,
    active_arc_plan_version_ids: Iterable[str],
    expected_progress_units: Mapping[str, int] | None,
    previous_arc_states: Mapping[str, Mapping[str, Any]],
    chapter_outcome: Mapping[str, Any],
    story_state: Mapping[str, Any],
    arc_plan_snapshots: Mapping[str, Mapping[str, Any]] | None = None,
    projector_version: str = "accepted-longform-projector-v1",
    chapter_plan_asset_version_id: str = "",
    source_content_hashes: Mapping[str, str] | None = None,
    contract_adaptation_evidence: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Build the complete deterministic long-form projection for one acceptance."""

    if chapter_number <= 0 or any(
        not str(value).strip()
        for value in (
            project_id,
            book_id,
            book_run_id,
            chapter_request_id,
            acceptance_id,
            acceptance_operation_id,
            chapter_outcome_asset_version_id,
            story_state_asset_version_id,
            canon_snapshot_asset_version_id,
        )
    ):
        raise KernelError(
            "LONGFORM_PROJECTION_BOUNDARY_INVALID",
            "long-form projection requires the complete accepted boundary",
        )
    active_arcs = tuple(
        dict.fromkeys(str(item) for item in active_arc_plan_version_ids if str(item))
    )
    evidence_by_arc = {
        str(item.get("arc_plan_version_id") or ""): dict(item)
        for item in chapter_outcome.get("arc_evidence") or ()
        if isinstance(item, Mapping) and str(item.get("arc_plan_version_id") or "")
    }
    unexpected = sorted(set(evidence_by_arc) - set(active_arcs))
    if unexpected:
        raise KernelError(
            "LONGFORM_PROJECTION_ARC_SCOPE_INVALID",
            "ChapterOutcome Arc evidence is outside the accepted Book Arc snapshot",
        )
    obligation_entries = [
        dict(item)
        for item in (story_state.get("current_state") or {}).get(
            "narrative_obligation", ()
        )
        if isinstance(item, Mapping)
    ]
    obligations = [
        {
            **entry,
            "accepted_through_chapter": chapter_number,
            "acceptance_operation_id": acceptance_operation_id,
            "story_state_asset_version_id": story_state_asset_version_id,
        }
        for entry in reduce_accepted_obligations(
            entries=obligation_entries, chapter_number=chapter_number
        )
    ]
    obligation_by_id = {
        str((item.get("state") or {}).get("obligation_id") or item.get("entity_key") or ""):
        dict(item)
        for item in obligations
        if str((item.get("state") or {}).get("obligation_id") or item.get("entity_key") or "")
    }
    raw_plans = dict(arc_plan_snapshots or {})
    plan_snapshots = {
        arc_id: normalize_frozen_arc_plan(
            arc_plan_version_id=arc_id,
            content=dict(raw_plans.get(arc_id) or {}),
        )
        for arc_id in active_arcs
    }
    progress_rows: list[dict[str, Any]] = []
    arc_states_by_id: dict[str, dict[str, Any]] = {}
    evidence_used: dict[str, dict[str, Any]] = {}
    checkpoints: list[dict[str, Any]] = []
    arc_outcomes: list[dict[str, Any]] = []
    expected = dict(expected_progress_units or {})
    for arc_plan_version_id in active_arcs:
        scheduled = arc_plan_version_id in expected
        evidence = evidence_by_arc.get(arc_plan_version_id) or {
            "arc_plan_version_id": arc_plan_version_id,
            "observation_status": (
                ArcObservationStatus.NOT_OBSERVED.value
                if scheduled else ArcObservationStatus.NOT_MATERIALIZED.value
            ),
            "contribution_kind": "UNOBSERVED" if scheduled else "NOT_SCHEDULED",
            "progress_units": 0,
            "effect_dimensions": [],
            "milestone_ids": [],
            "actual_consequences": [],
            "obligation_ids": [],
            "resolution_evidence": [],
            "completion_criterion_ids": [],
            "phase_to": "",
        }
        evidence_used[arc_plan_version_id] = dict(evidence)
        previous = dict(previous_arc_states.get(arc_plan_version_id) or {})
        progress = build_arc_progress(
            project_id=project_id,
            book_id=book_id,
            chapter_number=chapter_number,
            acceptance_operation_id=acceptance_operation_id,
            chapter_outcome_asset_version_id=chapter_outcome_asset_version_id,
            arc_plan_version_id=arc_plan_version_id,
            previous_progress_units=int(
                previous.get("cumulative_progress_units") or 0
            ),
            evidence=evidence,
            expected_progress_units=expected.get(arc_plan_version_id),
        )
        plan = plan_snapshots[arc_plan_version_id]
        target_units = int(
            plan.get("target_progress_units")
            or previous.get("target_progress_units")
            or 0
        )
        arc_states_by_id[arc_plan_version_id] = {
                "type": "ArcActualState",
                "contract_version": "arc-actual-state-v1",
                "project_id": project_id,
                "book_id": book_id,
                "arc_plan_version_id": arc_plan_version_id,
                "accepted_through_chapter": chapter_number,
                "acceptance_operation_id": acceptance_operation_id,
                "observation_status": progress["observation_status"],
                "lifecycle_status": "ACTIVE",
                "cumulative_progress_units": progress[
                    "cumulative_progress_units"
                ],
                "target_progress_units": target_units,
                "current_phase": str(
                    evidence.get("phase_to")
                    or previous.get("current_phase")
                    or ""
                ),
                "latest_progress_id": progress["progress_id"],
                "latest_checkpoint_id": "",
                "frozen_plan_evaluation": plan,
            }
        progress_rows.append(progress)

    for progress in progress_rows:
        arc_plan_version_id = str(progress["arc_plan_version_id"])
        evidence = evidence_used[arc_plan_version_id]
        plan = plan_snapshots[arc_plan_version_id]
        dependency_blockers: list[str] = []
        unknown_dependencies: list[str] = []
        dependency_states: dict[str, str] = {}
        for dependency_id in plan.get("dependency_arc_ids") or ():
            dependency = arc_states_by_id.get(dependency_id) or dict(
                previous_arc_states.get(dependency_id) or {}
            )
            lifecycle = str(dependency.get("lifecycle_status") or "UNKNOWN")
            dependency_states[dependency_id] = lifecycle
            if lifecycle == "COMPLETED":
                continue
            if lifecycle in {"BLOCKED", "ABANDONED"}:
                dependency_blockers.append(dependency_id)
            elif lifecycle == "UNKNOWN" or not dependency:
                unknown_dependencies.append(dependency_id)
            else:
                dependency_blockers.append(dependency_id)
        linked_obligations = set(str(item) for item in evidence.get("obligation_ids") or ())
        linked_obligations.update(
            obligation_id
            for obligation_id, item in obligation_by_id.items()
            if arc_plan_version_id in {
                str(value) for value in (item.get("state") or {}).get("linked_arc_ids") or ()
            }
        )
        overdue: list[str] = []
        stale: list[str] = []
        violated: list[str] = []
        obligation_evaluations: dict[str, Any] = {}
        for obligation_id in sorted(linked_obligations):
            evaluation = dict(
                (obligation_by_id.get(obligation_id, {}).get("state") or {}).get(
                    "accepted_evaluation"
                ) or {}
            )
            obligation_evaluations[obligation_id] = evaluation
            if evaluation.get("overdue"):
                overdue.append(obligation_id)
            if evaluation.get("stale"):
                stale.append(obligation_id)
            if evaluation.get("violated"):
                violated.append(obligation_id)
        window = dict(plan.get("target_window") or {})
        if window.get("status") != "SCHEDULED":
            target_window_status = "UNKNOWN"
        elif chapter_number > int(window.get("to_chapter") or 0):
            target_window_status = "OVERDUE"
        elif chapter_number < int(window.get("from_chapter") or 0):
            target_window_status = "BEFORE_WINDOW"
        else:
            target_window_status = "IN_WINDOW"
        required_criteria = {
            str(item.get("criterion_id") or "")
            for item in plan.get("completion_criteria") or ()
            if str(item.get("criterion_id") or "")
        }
        satisfied_criteria = {
            str(item) for item in evidence.get("completion_criterion_ids") or ()
            if str(item)
        }
        completion_satisfied = bool(
            required_criteria and required_criteria.issubset(satisfied_criteria)
        )
        checkpoint = build_arc_checkpoint(
            progress=progress,
            target_progress_units=int(
                arc_states_by_id[arc_plan_version_id].get(
                    "target_progress_units"
                ) or 0
            ),
            completion_criteria_satisfied=completion_satisfied,
            overdue_obligation_ids=overdue,
            stale_obligation_ids=stale,
            violated_obligation_ids=violated,
            dependency_blockers=dependency_blockers,
            unknown_dependency_ids=unknown_dependencies,
            plan_evaluation_status=str(plan.get("evaluation_status") or "UNKNOWN"),
            target_window_status=target_window_status,
        )
        checkpoint["frozen_arc_plan"] = plan
        checkpoint["dependency_states"] = dependency_states
        checkpoint["obligation_evaluations"] = obligation_evaluations
        checkpoint["completion_criterion_ids"] = sorted(satisfied_criteria)
        decision = ArcCheckpointDecision(str(checkpoint["decision"]))
        state = arc_states_by_id[arc_plan_version_id]
        state["lifecycle_status"] = (
            "COMPLETED" if decision is ArcCheckpointDecision.COMPLETED else
            "BLOCKED" if dependency_blockers else "ACTIVE"
        )
        state["latest_checkpoint_id"] = checkpoint["checkpoint_id"]
        checkpoints.append(checkpoint)
        if decision is ArcCheckpointDecision.COMPLETED:
            outcome_identity = "|".join(
                (
                    project_id,
                    book_id,
                    arc_plan_version_id,
                    acceptance_operation_id,
                )
            )
            arc_outcomes.append(
                {
                    "type": "ArcOutcome",
                    "contract_version": "arc-outcome-v1",
                    "arc_outcome_id": "arc-outcome:"
                    + hashlib.sha256(outcome_identity.encode()).hexdigest(),
                    "arc_plan_version_id": arc_plan_version_id,
                    "accepted_through_chapter": chapter_number,
                    "acceptance_operation_id": acceptance_operation_id,
                    "status": "COMPLETED",
                    "completion_evidence": {
                        "progress_id": progress["progress_id"],
                        "checkpoint_id": checkpoint["checkpoint_id"],
                        "milestone_ids": list(
                            progress["evidence"].get("milestone_ids") or ()
                        ),
                        "resolution_evidence": list(
                            progress["evidence"].get("resolution_evidence") or ()
                        ),
                    },
                }
            )
    arc_states = [arc_states_by_id[arc_id] for arc_id in active_arcs]
    projection = {
        "type": "AcceptedNarrativeProjectionSet",
        "contract_version": "accepted-narrative-projection-set-v1",
        "status": "COMPLETE",
        "projection_set_id": "longform-projection:"
        + hashlib.sha256(
            f"{acceptance_id}:{chapter_outcome_asset_version_id}".encode()
        ).hexdigest(),
        "project_id": project_id,
        "book_id": book_id,
        "book_run_id": book_run_id,
        "chapter_request_id": chapter_request_id,
        "accepted_boundary": {
            "chapter_number": chapter_number,
            "acceptance_id": acceptance_id,
            "acceptance_operation_id": acceptance_operation_id,
        },
        "source_versions": {
            "chapter_outcome_asset_version_id": chapter_outcome_asset_version_id,
            "story_state_asset_version_id": story_state_asset_version_id,
            "canon_snapshot_asset_version_id": canon_snapshot_asset_version_id,
            "chapter_plan_asset_version_id": chapter_plan_asset_version_id,
        },
        "arc_progress": progress_rows,
        "arc_states": arc_states,
        "arc_checkpoints": checkpoints,
        "arc_outcomes": arc_outcomes,
        "obligation_states": obligations,
        "projection_provenance": {
            "projector_version": projector_version,
            "source_content_hashes": dict(source_content_hashes or {}),
            "contract_adaptation_evidence": [
                dict(item) for item in contract_adaptation_evidence
            ],
            "actual_state_policy": "ACCEPTED_EVIDENCE_ONLY",
            "arc_plan_source": "FROZEN_PLANNING_ASSET_VERSION",
            "obligation_policy_version": "accepted-obligation-lifecycle-v1",
        },
    }
    digest_payload = {
        key: value for key, value in projection.items() if key != "projection_hash"
    }
    projection["projection_hash"] = "sha256:" + hashlib.sha256(
        json.dumps(
            digest_payload, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    return projection


__all__ = [
    "build_arc_checkpoint",
    "build_arc_progress",
    "build_longform_projection_set",
    "normalize_arc_evidence",
    "normalize_frozen_arc_plan",
    "reduce_accepted_obligations",
]
