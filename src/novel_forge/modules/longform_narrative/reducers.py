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
) -> dict[str, Any]:
    boundary = dict(progress.get("accepted_boundary") or {})
    observation = ArcObservationStatus(
        str(progress.get("observation_status") or "UNKNOWN")
    )
    overdue = tuple(dict.fromkeys(str(item) for item in overdue_obligation_ids if str(item)))
    blockers = tuple(dict.fromkeys(str(item) for item in dependency_blockers if str(item)))
    cumulative = int(progress.get("cumulative_progress_units") or 0)
    reasons: list[str] = []
    if observation in {ArcObservationStatus.NOT_OBSERVED, ArcObservationStatus.UNKNOWN}:
        decision = ArcCheckpointDecision.UNKNOWN
        reasons.append(observation.value)
    elif observation is ArcObservationStatus.NOT_MATERIALIZED:
        decision = ArcCheckpointDecision.CONTINUE
        reasons.append("NOT_SCHEDULED_THIS_CHAPTER")
    elif completion_criteria_satisfied and cumulative >= target_progress_units:
        decision = ArcCheckpointDecision.COMPLETED
        reasons.append("COMPLETION_CRITERIA_SATISFIED")
    elif blockers:
        decision = ArcCheckpointDecision.REPLAN_REQUIRED
        reasons.append("DEPENDENCY_BLOCKED")
    elif overdue:
        decision = ArcCheckpointDecision.CORRECT
        reasons.append("OBLIGATION_OVERDUE")
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
        "dependency_blockers": list(blockers),
    }


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
    progress_rows: list[dict[str, Any]] = []
    arc_states: list[dict[str, Any]] = []
    checkpoints: list[dict[str, Any]] = []
    arc_outcomes: list[dict[str, Any]] = []
    expected = dict(expected_progress_units or {})
    for arc_plan_version_id in active_arcs:
        evidence = evidence_by_arc.get(
            arc_plan_version_id,
            {
                "arc_plan_version_id": arc_plan_version_id,
                "observation_status": ArcObservationStatus.NOT_MATERIALIZED.value,
                "contribution_kind": "NOT_SCHEDULED",
                "progress_units": 0,
                "effect_dimensions": [],
                "milestone_ids": [],
                "actual_consequences": [],
                "obligation_ids": [],
                "resolution_evidence": [],
            },
        )
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
        target_units = int(previous.get("target_progress_units") or 0)
        checkpoint = build_arc_checkpoint(
            progress=progress,
            target_progress_units=target_units,
            completion_criteria_satisfied=bool(
                evidence.get("completion_criteria_satisfied", False)
            ),
            overdue_obligation_ids=(),
            dependency_blockers=(),
        )
        decision = ArcCheckpointDecision(str(checkpoint["decision"]))
        lifecycle = (
            "COMPLETED"
            if decision is ArcCheckpointDecision.COMPLETED
            else "ACTIVE"
        )
        arc_states.append(
            {
                "type": "ArcActualState",
                "contract_version": "arc-actual-state-v1",
                "project_id": project_id,
                "book_id": book_id,
                "arc_plan_version_id": arc_plan_version_id,
                "accepted_through_chapter": chapter_number,
                "acceptance_operation_id": acceptance_operation_id,
                "observation_status": progress["observation_status"],
                "lifecycle_status": lifecycle,
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
                "latest_checkpoint_id": checkpoint["checkpoint_id"],
            }
        )
        progress_rows.append(progress)
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
        for entry in obligation_entries
    ]
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
]
