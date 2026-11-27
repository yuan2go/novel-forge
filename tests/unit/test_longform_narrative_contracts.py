from __future__ import annotations

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.longform_narrative import (
    ArcCheckpointDecision,
    ArcObservationStatus,
    build_arc_checkpoint,
    build_arc_progress,
    build_arc_working_set,
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


def test_future_dependency_wait_does_not_force_semantic_replan() -> None:
    progress = build_arc_progress(
        project_id="project:1",
        book_id="book:1",
        chapter_number=1,
        acceptance_operation_id="operation:accept:1",
        chapter_outcome_asset_version_id="outcome:v1",
        arc_plan_version_id="arc:future",
        previous_progress_units=0,
        evidence={
            "observation_status": "NOT_MATERIALIZED",
            "progress_units": 0,
            "resolution_evidence": [],
        },
    )

    checkpoint = build_arc_checkpoint(
        progress=progress,
        target_progress_units=1,
        completion_criteria_satisfied=False,
        overdue_obligation_ids=(),
        dependency_blockers=("arc:dependency",),
        target_window_status="BEFORE_WINDOW",
    )

    assert checkpoint["decision"] == ArcCheckpointDecision.CONTINUE
    assert checkpoint["reasons"] == ["DEPENDENCY_WAITING_BEFORE_WINDOW"]
    assert checkpoint["dependency_blockers"] == ["arc:dependency"]


def test_projection_set_is_complete_and_marks_unscheduled_arc_not_materialized() -> (
    None
):
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

    assert normalized[0]["completion_criterion_ids"] == ["criterion:earned-choice"]
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
        item
        for item in projection["arc_checkpoints"]
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

    assert (
        projection["arc_checkpoints"][0]["decision"] == ArcCheckpointDecision.COMPLETED
    )
    assert projection["arc_outcomes"][0]["completion_evidence"][
        "resolution_evidence"
    ] == ["scene:2:1"]


def test_completed_arc_and_cumulative_criteria_never_regress() -> None:
    plan = normalize_frozen_arc_plan(
        arc_plan_version_id="arc:complete",
        content={
            "objective": "finish",
            "closure_conditions": ["choice", "cost"],
            "target_progress_units": 2,
        },
    )
    criteria = [item["criterion_id"] for item in plan["completion_criteria"]]
    projection = build_longform_projection_set(
        project_id="project:1",
        book_id="book:1",
        book_run_id="book-run:1",
        chapter_request_id="chapter-request:3",
        chapter_number=3,
        acceptance_id="acceptance:3",
        acceptance_operation_id="operation:accept:3",
        chapter_outcome_asset_version_id="outcome:v3",
        story_state_asset_version_id="story-state:v3",
        canon_snapshot_asset_version_id="canon:v3",
        active_arc_plan_version_ids=("arc:complete",),
        expected_progress_units={"arc:complete": 1},
        previous_arc_states={
            "arc:complete": {
                "cumulative_progress_units": 1,
                "lifecycle_status": "ACTIVE",
                "satisfied_completion_criterion_ids": [criteria[0]],
                "last_material_progress_chapter": 2,
            }
        },
        chapter_outcome={
            "arc_evidence": [
                {
                    "arc_plan_version_id": "arc:complete",
                    "observation_status": "OBSERVED",
                    "progress_units": 1,
                    "resolution_evidence": ["scene:3:1"],
                    "completion_criterion_ids": [criteria[1]],
                }
            ]
        },
        story_state={"current_state": {"narrative_obligation": []}},
        arc_plan_snapshots={
            "arc:complete": {
                "objective": "finish",
                "closure_conditions": ["choice", "cost"],
                "target_progress_units": 2,
            }
        },
    )
    state = projection["arc_states"][0]
    assert state["lifecycle_status"] == "COMPLETED"
    assert state["satisfied_completion_criterion_ids"] == criteria

    later = build_longform_projection_set(
        project_id="project:1",
        book_id="book:1",
        book_run_id="book-run:1",
        chapter_request_id="chapter-request:4",
        chapter_number=4,
        acceptance_id="acceptance:4",
        acceptance_operation_id="operation:accept:4",
        chapter_outcome_asset_version_id="outcome:v4",
        story_state_asset_version_id="story-state:v4",
        canon_snapshot_asset_version_id="canon:v4",
        active_arc_plan_version_ids=("arc:complete",),
        expected_progress_units={},
        previous_arc_states={"arc:complete": state},
        chapter_outcome={"arc_evidence": []},
        story_state={"current_state": {"narrative_obligation": []}},
        arc_plan_snapshots={
            "arc:complete": {
                "objective": "finish",
                "closure_conditions": ["choice", "cost"],
                "target_progress_units": 2,
            }
        },
    )
    assert later["arc_states"][0]["lifecycle_status"] == "COMPLETED"


def test_arc_working_set_corrects_static_cadence_from_accepted_debt() -> None:
    projection = {
        "projection_set_id": "projection:4",
        "projection_hash": "sha256:" + "a" * 64,
        "accepted_boundary": {"chapter_number": 4},
        "arc_states": [
            {
                "arc_plan_version_id": "arc:static",
                "lifecycle_status": "ACTIVE",
                "last_material_progress_chapter": 4,
            },
            {
                "arc_plan_version_id": "arc:overdue",
                "lifecycle_status": "ACTIVE",
                "last_material_progress_chapter": 1,
            },
        ],
        "arc_progress": [],
        "arc_checkpoints": [],
        "obligation_states": [
            {
                "entity_key": "promise:late",
                "state": {
                    "obligation_id": "promise:late",
                    "linked_arc_ids": ["arc:overdue"],
                    "accepted_evaluation": {"overdue": True},
                },
            }
        ],
    }
    working_set = build_arc_working_set(
        project_id="project:1",
        book_id="book:1",
        chapter_number=5,
        arc_plan_snapshots={
            "arc:static": {"objective": "static", "closure_conditions": ["done"]},
            "arc:overdue": {
                "objective": "pay debt",
                "closure_conditions": ["paid"],
            },
        },
        accepted_projection=projection,
        accepted_narrative_state={
            "asset_version_id": "story-state:v4",
            "content_hash": "sha256:" + "b" * 64,
            "content": {"accepted_through_chapter": 4, "current_state": {}},
        },
        narrative_load_policy={"limits": {"max_active_arcs": 1}},
        schedule_row={
            "narrative_density": "LOW",
            "arc_cadence": [{"arc_plan_version_id": "arc:static", "action": "ADVANCE"}],
        },
        reader_intent={"reward_mode": "PAYOFF"},
    )

    assert working_set["selected_contributions"] == [
        {
            "arc_plan_version_id": "arc:overdue",
            "role": "PRIMARY",
            "action": "PAYOFF",
            "score": 68,
            "reason_codes": [
                "OBLIGATION_OVERDUE",
                "STARVATION_PRESSURE",
                "READER_PAYOFF_INTENT",
            ],
        }
    ]
    assert working_set["schedule_correction"] == {
        "status": "CORRECTED_FROM_GROUP_CADENCE",
        "added_arc_plan_version_ids": ["arc:overdue"],
        "removed_arc_plan_version_ids": ["arc:static"],
    }
    assert working_set["authority_boundary"][
        "actual_progress_requires_accepted_chapter_outcome"
    ]


def test_arc_working_set_filters_terminal_and_dependency_illegal_arcs() -> None:
    working_set = build_arc_working_set(
        project_id="project:1",
        book_id="book:1",
        chapter_number=3,
        arc_plan_snapshots={
            "arc:root": {"objective": "root", "closure_conditions": ["done"]},
            "arc:dependent": {
                "objective": "dependent",
                "closure_conditions": ["done"],
                "dependencies": ["arc:root"],
            },
            "arc:finished": {
                "objective": "finished",
                "closure_conditions": ["done"],
            },
        },
        accepted_projection={
            "accepted_boundary": {"chapter_number": 2},
            "arc_states": [
                {
                    "arc_plan_version_id": "arc:root",
                    "lifecycle_status": "ACTIVE",
                    "current_phase": "CLIMAX",
                },
                {
                    "arc_plan_version_id": "arc:dependent",
                    "lifecycle_status": "BLOCKED",
                },
                {
                    "arc_plan_version_id": "arc:finished",
                    "lifecycle_status": "COMPLETED",
                },
            ],
        },
        accepted_narrative_state={
            "asset_version_id": "story-state:v2",
            "content_hash": "sha256:" + "c" * 64,
            "content": {"accepted_through_chapter": 2, "current_state": {}},
        },
        narrative_load_policy={"limits": {"max_active_arcs": 3}},
    )
    assert [
        item["arc_plan_version_id"] for item in working_set["selected_contributions"]
    ] == ["arc:root"]
    by_id = {item["arc_plan_version_id"]: item for item in working_set["candidates"]}
    assert working_set["selected_contributions"][0]["action"] == "PAYOFF"
    assert by_id["arc:root"]["payoff_readiness"] == "READY"
    assert by_id["arc:dependent"]["dependency_blockers"] == ["arc:root"]
    assert by_id["arc:finished"]["reasons"] == ["TERMINAL_COMPLETED"]
    assert working_set["accepted_reality"]["narrative_state"]["content_hash"] == (
        "sha256:" + "c" * 64
    )


def test_arc_working_set_rejects_a_stale_narrative_state_boundary() -> None:
    with pytest.raises(KernelError, match="Narrative State differs"):
        build_arc_working_set(
            project_id="project:1",
            book_id="book:1",
            chapter_number=2,
            arc_plan_snapshots={
                "arc:one": {"objective": "advance", "closure_conditions": ["done"]}
            },
            accepted_projection={"accepted_boundary": {"chapter_number": 1}},
            accepted_narrative_state={
                "asset_version_id": "story-state:v0",
                "content_hash": "sha256:" + "d" * 64,
                "content": {"accepted_through_chapter": 0, "current_state": {}},
            },
            narrative_load_policy={"limits": {"max_active_arcs": 1}},
        )


def _frozen_chapter_working_set(*, row=None, projection=None, maximum=3):
    return build_arc_working_set(
        project_id="project:1", book_id="book:1", chapter_number=1,
        arc_plan_snapshots={
            "arc:hero": {"objective": "earn wages", "closure_conditions": ["paid"]},
            "arc:teacher": {"objective": "teach later", "closure_conditions": ["taught"]},
        },
        accepted_projection=projection or {"accepted_boundary": {"chapter_number": 0}},
        accepted_narrative_state={
            "asset_version_id": "story-state:v0", "content_hash": "sha256:" + "a" * 64,
            "content": {"accepted_through_chapter": 0, "current_state": {}},
        },
        narrative_load_policy={"limits": {"max_active_arcs": maximum}},
        schedule_row=row,
    )


def _labor_chapter_row():
    return {
        "chapter_number": 1, "narrative_density": "MEDIUM",
        "required_arc_contributions": [{"arc_plan_version_id": "arc:hero", "contribution": "finish work"}],
        "arc_cadence": [{"arc_plan_version_id": "arc:hero", "action": "ADVANCE"}],
    }


def test_frozen_chapter_scope_does_not_fill_unused_capacity_or_pay_unplanned_debt():
    projection = {
        "accepted_boundary": {"chapter_number": 0},
        "arc_states": [{"arc_plan_version_id": "arc:hero", "current_phase": "CLIMAX"}],
        "obligation_states": [{"state": {
            "obligation_id": "promise:teacher", "linked_arc_ids": ["arc:teacher"],
            "accepted_evaluation": {"overdue": True},
        }}],
    }
    row = _labor_chapter_row()
    working = _frozen_chapter_working_set(row=row, projection=projection)
    assert [(x["arc_plan_version_id"], x["action"]) for x in working["selected_contributions"]] == [("arc:hero", "ADVANCE")]
    assert working["deferred_arc_plan_version_ids"] == ["arc:teacher"]
    assert working["policy_version"] == "frozen-chapter-arc-working-set-v2"
    assert working["capacity"]["source"] == "FROZEN_CHAPTER_SCHEDULE"
    assert working["schedule_correction"]["added_arc_plan_version_ids"] == []
    assert row == _labor_chapter_row()
    teacher = next(x for x in working["candidates"] if x["arc_plan_version_id"] == "arc:teacher")
    assert teacher["obligation_debt"]["overdue_count"] == 1


def test_frozen_chapter_contributions_are_not_dropped_by_density_hint():
    row = _labor_chapter_row()
    row["narrative_density"] = "LOW"
    row["required_arc_contributions"].append({"arc_plan_version_id": "arc:teacher", "contribution": "limited contact"})
    row["arc_cadence"].append({"arc_plan_version_id": "arc:teacher", "action": "TOUCH"})
    working = _frozen_chapter_working_set(row=row)
    assert {x["arc_plan_version_id"] for x in working["selected_contributions"]} == {"arc:hero", "arc:teacher"}
    with pytest.raises(KernelError, match="governed active-Arc capacity"):
        _frozen_chapter_working_set(row=row, maximum=1)


@pytest.mark.parametrize("defect", ["wrong_chapter", "foreign", "duplicate", "dormant", "extra_cadence"])
def test_invalid_frozen_chapter_scope_requires_planning_instead_of_rank_correction(defect):
    row = _labor_chapter_row()
    if defect == "wrong_chapter":
        row["chapter_number"] = 2
    elif defect == "foreign":
        row["required_arc_contributions"][0]["arc_plan_version_id"] = "arc:foreign"
    elif defect == "duplicate":
        row["required_arc_contributions"] *= 2
    elif defect == "dormant":
        row["arc_cadence"][0]["action"] = "DORMANT"
    else:
        row["arc_cadence"].append({"arc_plan_version_id": "arc:teacher", "action": "ADVANCE"})
    with pytest.raises(KernelError) as error:
        _frozen_chapter_working_set(row=row)
    assert error.value.code == "ARC_WORKING_SET_CHAPTER_SCHEDULE_INVALID"


def test_frozen_chapter_illegal_arc_cannot_be_replaced_with_another_portfolio_arc():
    with pytest.raises(KernelError) as error:
        _frozen_chapter_working_set(row=_labor_chapter_row(), projection={
            "accepted_boundary": {"chapter_number": 0},
            "arc_states": [{"arc_plan_version_id": "arc:hero", "lifecycle_status": "COMPLETED"}],
        })
    assert error.value.code == "ARC_WORKING_SET_CHAPTER_ARC_ILLEGAL"


def test_unfrozen_group_selection_keeps_v1_capacity_ranking():
    working = _frozen_chapter_working_set(row={"narrative_density": "MEDIUM"})
    assert working["policy_version"] == "accepted-reality-arc-working-set-v1"
    assert len(working["selected_contributions"]) == 2


def test_working_schedule_does_not_turn_acceptance_lag_into_absent_progress():
    from novel_forge.modules.book_authority.working_prose import WORKING_SCHEDULE_POLICY, project_working_sources, working_instruction
    from novel_forge.modules.narrative_state.working_memory import compile_working_memory, bind_packet_coverage
    from novel_forge.modules.chapter_authority.author_editor import text_hash
    from novel_forge.modules.story_planning_runtime.domain import canonical_hash
    policy = {"version": "working-prose-projection.v3", "history_chapters": 8,
        "recent_complete_chapters": 1, "max_characters": 1000, "queries": [], "guidance_mode": "COMBINED"}
    sources = [{"chapter": 1, "asset_version_id": "draft:1", "content_hash": "sha256:" + "b" * 64,
        "text_hash": text_hash("She paid. He could now leave."), "text": "She paid. He could now leave."}]
    memory = compile_working_memory(sources, queries=[], max_characters=1000)
    sources = project_working_sources(sources, target_chapter=2, policy=policy, memory=memory)
    working = {"version": "working-manuscript-context.v1", "project_id": "project:1", "book_id": "book:1",
        "book_run_id": "run:1", "target_chapter": 2, "accepted_through_chapter": 0,
        "authority": "AUTHOR_WORKING_PROSE_ONLY", "structured_facts": [], "projection_policy": policy,
        "instruction": working_instruction(policy), "sources": sources,
        "working_memory": bind_packet_coverage(memory, sources), "scheduling_policy": WORKING_SCHEDULE_POLICY}
    working["snapshot_hash"] = canonical_hash(working)
    arguments = dict(project_id="project:1", book_id="book:1", chapter_number=2,
        arc_plan_snapshots={"arc:a": {"objective": "earn wages", "closure_conditions": ["paid"]},
            "arc:b": {"objective": "leave after payment", "closure_conditions": ["departed"], "dependencies": ["arc:a"]}},
        accepted_projection={"accepted_boundary": {"chapter_number": 0}},
        accepted_narrative_state={"asset_version_id": "state:0", "content_hash": "sha256:" + "a" * 64,
            "content": {"accepted_through_chapter": 0, "current_state": {}}},
        narrative_load_policy={"limits": {"max_active_arcs": 1}}, working_manuscript=working,
        schedule_row={"chapter_number": 2, "narrative_density": "LOW",
            "required_arc_contributions": [{"arc_plan_version_id": "arc:b", "contribution": "depart"}],
            "arc_cadence": [{"arc_plan_version_id": "arc:b", "action": "ADVANCE"}]})
    result = build_arc_working_set(**arguments)
    candidate = next(row for row in result["candidates"] if row["arc_plan_version_id"] == "arc:b")
    assert candidate["eligible"] and candidate["dependency_blockers"] == []
    assert candidate["dependency_states"] == {"arc:a": "UNASSESSED"}
    assert candidate["working_progress"]["dependency_assessment_required"] == ["arc:a"]
    assert candidate["current_phase"] == candidate["payoff_readiness"] == "UNASSESSED"
    assert candidate["cumulative_progress_units"] is None
    assert result["accepted_reality"]["accepted_through_chapter"] == 0
    assert result["authority_boundary"]["actual_progress_requires_accepted_chapter_outcome"]
    assert result["selected_contributions"][0]["action"] == "ADVANCE"
    overdue = dict(arguments["arc_plan_snapshots"])
    overdue["arc:b"] = {**overdue["arc:b"], "target_window": {"from_chapter": 1, "to_chapter": 1}}
    provisional = build_arc_working_set(**{**arguments, "schedule_row": None, "arc_plan_snapshots": overdue})
    assert provisional["selected_contributions"][0]["action"] == "ADVANCE"
    legacy = dict(working)
    legacy.pop("scheduling_policy")
    legacy["snapshot_hash"] = canonical_hash({k:v for k,v in legacy.items() if k != "snapshot_hash"})
    with pytest.raises(KernelError, match="ARC_WORKING_SET_CHAPTER_ARC_ILLEGAL"):
        build_arc_working_set(**{**arguments, "working_manuscript": legacy})
    with pytest.raises(KernelError, match="WORKING_PROSE_PROJECTION_INVALID"):
        build_arc_working_set(**{**arguments, "working_manuscript": {**working, "sources": []}})
