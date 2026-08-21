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
    normalize_frozen_arc_plan,
    reduce_accepted_obligations,
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
            "completion_criterion_ids": [],
            "phase_to": "",
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


def test_overdue_obligation_requires_correction_without_model_decision() -> None:
    progress = build_arc_progress(
        project_id="project:1",
        book_id="book:1",
        chapter_number=6,
        acceptance_operation_id="operation:accept:6",
        chapter_outcome_asset_version_id="outcome:v6",
        arc_plan_version_id="arc-plan:v1",
        previous_progress_units=2,
        evidence={
            "observation_status": "OBSERVED",
            "progress_units": 1,
            "resolution_evidence": ["scene:6:1"],
        },
    )
    checkpoint = build_arc_checkpoint(
        progress=progress,
        target_progress_units=5,
        completion_criteria_satisfied=False,
        overdue_obligation_ids=("promise:late",),
        dependency_blockers=(),
    )

    assert checkpoint["decision"] == ArcCheckpointDecision.CORRECT
    assert checkpoint["reasons"] == ["OBLIGATION_OVERDUE"]


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


def test_normalization_preserves_accepted_completion_and_phase_evidence() -> None:
    normalized = normalize_arc_evidence(
        declared={"arc-plan:v1": {}},
        raw_evidence=(
            {
                "arc_plan_version_id": "arc-plan:v1",
                "observation_status": "OBSERVED",
                "progress_units": 1,
                "resolution_evidence": ["scene:3:2"],
                "completion_criterion_ids": ["criterion:earned-choice"],
                "phase_to": "CONSEQUENCE",
            },
        ),
    )

    assert normalized[0]["completion_criterion_ids"] == [
        "criterion:earned-choice"
    ]
    assert normalized[0]["phase_to"] == "CONSEQUENCE"


def test_accepted_obligation_lifecycle_is_deterministic() -> None:
    reduced = reduce_accepted_obligations(
        chapter_number=8,
        entries=(
            {
                "entity_key": "obligation_id=promise:late",
                "state": {
                    "obligation_id": "promise:late",
                    "status": "OPEN",
                    "opened_chapter": 1,
                    "target_window": {
                        "status": "SCHEDULED",
                        "from_chapter": 3,
                        "to_chapter": 6,
                    },
                    "linked_arc_ids": ["arc-plan:v1"],
                },
            },
        ),
    )

    evaluation = reduced[0]["state"]["accepted_evaluation"]
    assert evaluation["lifecycle"] == "OVERDUE"
    assert evaluation["overdue"] is True
    assert evaluation["policy_version"] == "accepted-obligation-lifecycle-v1"


def test_dependency_and_overdue_obligation_drive_real_checkpoint_inputs() -> None:
    plan_a = normalize_frozen_arc_plan(
        arc_plan_version_id="arc:a",
        content={"objective": "enable B", "closure_conditions": ["A paid"]},
    )
    projection = build_longform_projection_set(
        project_id="project:1",
        book_id="book:1",
        book_run_id="book-run:1",
        chapter_request_id="chapter-request:8",
        chapter_number=8,
        acceptance_id="acceptance:8",
        acceptance_operation_id="operation:accept:8",
        chapter_outcome_asset_version_id="outcome:v8",
        story_state_asset_version_id="story-state:v8",
        canon_snapshot_asset_version_id="canon:v8",
        active_arc_plan_version_ids=("arc:a", "arc:b"),
        expected_progress_units={"arc:b": 1},
        previous_arc_states={
            "arc:a": {"cumulative_progress_units": 1, "lifecycle_status": "ACTIVE"}
        },
        chapter_outcome={"arc_evidence": []},
        story_state={
            "current_state": {
                "narrative_obligation": [
                    {
                        "entity_key": "obligation_id=promise:late",
                        "state": {
                            "obligation_id": "promise:late",
                            "status": "OPEN",
                            "opened_chapter": 1,
                            "target_window": {
                                "status": "SCHEDULED",
                                "from_chapter": 2,
                                "to_chapter": 5,
                            },
                            "linked_arc_ids": ["arc:b"],
                        },
                    }
                ]
            }
        },
        arc_plan_snapshots={
            "arc:a": {
                "objective": plan_a["objective"],
                "closure_conditions": ["A paid"],
            },
            "arc:b": {
                "objective": "use A",
                "closure_conditions": ["B paid"],
                "dependencies": ["arc:a"],
                "target_window": {"from_chapter": 4, "to_chapter": 10},
            },
        },
    )

    checkpoint = next(
        item for item in projection["arc_checkpoints"]
        if item["arc_plan_version_id"] == "arc:b"
    )
    assert checkpoint["decision"] == ArcCheckpointDecision.REPLAN_REQUIRED
    assert checkpoint["dependency_blockers"] == ["arc:a"]
    assert checkpoint["overdue_obligation_ids"] == ["promise:late"]
    assert checkpoint["frozen_arc_plan"]["objective"] == "use A"


def test_completion_requires_frozen_criterion_ids_not_plan_assertion() -> None:
    plan = normalize_frozen_arc_plan(
        arc_plan_version_id="arc:complete",
        content={
            "objective": "finish",
            "closure_conditions": ["choice demonstrated"],
            "target_progress_units": 1,
            "target_window": {"from_chapter": 1, "to_chapter": 3},
        },
    )
    criterion = plan["completion_criteria"][0]["criterion_id"]
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
        active_arc_plan_version_ids=("arc:complete",),
        expected_progress_units={"arc:complete": 1},
        previous_arc_states={},
        chapter_outcome={
            "arc_evidence": [
                {
                    "arc_plan_version_id": "arc:complete",
                    "observation_status": "OBSERVED",
                    "contribution_kind": "PRIMARY",
                    "progress_units": 1,
                    "resolution_evidence": ["scene:2:1"],
                    "completion_criterion_ids": [criterion],
                }
            ]
        },
        story_state={"current_state": {"narrative_obligation": []}},
        arc_plan_snapshots={
            "arc:complete": {
                "objective": "finish",
                "closure_conditions": ["choice demonstrated"],
                "target_progress_units": 1,
                "target_window": {"from_chapter": 1, "to_chapter": 3},
            }
        },
    )

    assert projection["arc_checkpoints"][0]["decision"] == ArcCheckpointDecision.COMPLETED
    assert projection["arc_outcomes"][0]["completion_evidence"][
        "resolution_evidence"
    ] == ["scene:2:1"]
