from __future__ import annotations

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.longform_narrative import (
    ArcCheckpointDecision,
    ArcObservationStatus,
    build_arc_checkpoint,
    build_arc_progress,
    build_longform_projection_set,
    normalize_arc_evidence,
)


def test_missing_arc_evidence_is_not_observed_and_never_uses_plan_payload() -> None:
    declared = {
        "arc-plan:v1": {
            "arc_plan_version_id": "arc-plan:v1",
            "contribution_kind": "PRIMARY",
            "expected_progress": "hero confronts the cost",
        }
    }

    evidence = normalize_arc_evidence(declared=declared, raw_evidence=())

    assert evidence == (
        {
            "arc_plan_version_id": "arc-plan:v1",
            "observation_status": "NOT_OBSERVED",
            "contribution_kind": "UNOBSERVED",
            "progress_units": 0,
            "effect_dimensions": [],
            "milestone_ids": [],
            "actual_consequences": [],
            "obligation_ids": [],
            "resolution_evidence": [],
        },
    )
    assert "expected_progress" not in evidence[0]


def test_observed_arc_progress_requires_actual_resolution_evidence() -> None:
    declared = {"arc-plan:v1": {"arc_plan_version_id": "arc-plan:v1"}}

    with pytest.raises(KernelError, match="observed Arc evidence"):
        normalize_arc_evidence(
            declared=declared,
            raw_evidence=(
                {
                    "arc_plan_version_id": "arc-plan:v1",
                    "observation_status": "OBSERVED",
                    "progress_units": 1,
                },
            ),
        )


def test_progress_and_checkpoint_are_accepted_boundary_bound() -> None:
    progress = build_arc_progress(
        project_id="project:1",
        book_id="book:1",
        chapter_number=4,
        acceptance_operation_id="operation:accept:4",
        chapter_outcome_asset_version_id="outcome:v4",
        arc_plan_version_id="arc-plan:v1",
        previous_progress_units=2,
        evidence={
            "arc_plan_version_id": "arc-plan:v1",
            "observation_status": ArcObservationStatus.OBSERVED,
            "contribution_kind": "PRIMARY",
            "progress_units": 2,
            "effect_dimensions": ["CHARACTER", "CONFLICT"],
            "milestone_ids": ["milestone:crisis"],
            "actual_consequences": ["the alliance fractures"],
            "obligation_ids": ["obligation:promise:1"],
            "resolution_evidence": ["scene:4:2"],
        },
        expected_progress_units=1,
    )

    assert progress["accepted_boundary"]["chapter_number"] == 4
    assert progress["cumulative_progress_units"] == 4
    assert progress["deviation_units"] == 1
    assert progress["source"]["chapter_outcome_asset_version_id"] == "outcome:v4"

    checkpoint = build_arc_checkpoint(
        progress=progress,
        target_progress_units=4,
        completion_criteria_satisfied=True,
        overdue_obligation_ids=(),
        dependency_blockers=(),
    )
    assert checkpoint["decision"] == ArcCheckpointDecision.COMPLETED


def test_unknown_observation_cannot_advance_progress() -> None:
    with pytest.raises(KernelError, match="cannot advance"):
        build_arc_progress(
            project_id="project:1",
            book_id="book:1",
            chapter_number=2,
            acceptance_operation_id="operation:accept:2",
            chapter_outcome_asset_version_id="outcome:v2",
            arc_plan_version_id="arc-plan:v1",
            previous_progress_units=1,
            evidence={
                "arc_plan_version_id": "arc-plan:v1",
                "observation_status": ArcObservationStatus.UNKNOWN,
                "contribution_kind": "UNKNOWN",
                "progress_units": 1,
                "effect_dimensions": [],
                "milestone_ids": [],
                "actual_consequences": [],
                "obligation_ids": [],
                "resolution_evidence": [],
            },
        )


def test_projection_set_is_complete_and_marks_unscheduled_arc_not_materialized() -> None:
    projection = build_longform_projection_set(
        project_id="project:1",
        book_id="book:1",
        book_run_id="book-run:1",
        chapter_request_id="chapter-request:2",
        chapter_number=2,
        acceptance_id="acceptance:2",
        acceptance_operation_id="operation:accept:2",
        chapter_outcome_asset_version_id="outcome:v2",
        story_state_asset_version_id="story-state:v2",
        canon_snapshot_asset_version_id="canon:v2",
        active_arc_plan_version_ids=("arc-plan:v1", "arc-plan:v2"),
        expected_progress_units={"arc-plan:v1": 1},
        previous_arc_states={
            "arc-plan:v1": {"cumulative_progress_units": 2},
            "arc-plan:v2": {"cumulative_progress_units": 3},
        },
        chapter_outcome={
            "arc_evidence": [
                {
                    "arc_plan_version_id": "arc-plan:v1",
                    "observation_status": "OBSERVED",
                    "contribution_kind": "PRIMARY",
                    "progress_units": 1,
                    "effect_dimensions": ["CONFLICT"],
                    "milestone_ids": [],
                    "actual_consequences": ["pressure rises"],
                    "obligation_ids": [],
                    "resolution_evidence": ["scene:2:1"],
                }
            ]
        },
        story_state={
            "current_state": {
                "narrative_obligation": [
                    {
                        "entity_key": "obligation_id=promise:1",
                        "state": {"obligation_id": "promise:1", "status": "OPEN"},
                    }
                ]
            }
        },
    )

    assert projection["status"] == "COMPLETE"
    assert projection["projection_hash"].startswith("sha256:")
    by_arc = {item["arc_plan_version_id"]: item for item in projection["arc_progress"]}
    assert by_arc["arc-plan:v1"]["observation_status"] == "OBSERVED"
    assert by_arc["arc-plan:v2"]["observation_status"] == "NOT_MATERIALIZED"
    assert by_arc["arc-plan:v2"]["cumulative_progress_units"] == 3
    assert projection["obligation_states"][0]["accepted_through_chapter"] == 2
