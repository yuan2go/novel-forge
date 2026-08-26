from __future__ import annotations

from types import SimpleNamespace

import pytest

from novel_forge.modules.book_authority.production import BookProductionState
from novel_forge.modules.book_authority.supervisor import (
    PostgresBookProductionSupervisor,
)
from novel_forge.modules.book_replan import CoordinateBookReplanCommand
from novel_forge.modules.book_replan.coordinator import (
    BookReplanCoordinator,
    SCOPE_CONTRACT,
    SCOPE_GENERATOR,
)
from novel_forge.modules.book_production import SupervisorAction
from novel_forge.modules.hierarchical_planning import PlanExecutionScope
from novel_forge.modules.story_planning_runtime import PlanningGenerationStatus


@pytest.mark.parametrize(
    ("generated_contract", "expected_action"),
    (
        ("CHAPTER_GROUP", SupervisorAction.GENERATE_CHAPTER_GROUP),
        ("CHAPTER", SupervisorAction.GENERATE_CHAPTER_PLAN),
    ),
)
def test_supervisor_reports_planning_generation_operation_identity(
    generated_contract: str, expected_action: SupervisorAction
) -> None:
    book = {
        "book_run_id": "book-run:1",
        "project_id": "project:1",
        "book_id": "book:1",
        "version": 7,
        "state": BookProductionState.READY.value,
        "input_mode": "RESOLVED_AUTHORITY_INPUT",
        "accepted_through_chapter": 0,
        "target_chapter_count": 3,
    }
    supervisor = object.__new__(PostgresBookProductionSupervisor)
    transitions: list[BookProductionState] = []
    supervisor.authority = SimpleNamespace(
        require=lambda _book_run_id: dict(book),
        advance_supervisor_checkpoint=lambda _book_run_id, **values: (
            transitions.append(values["target_state"]) or "checkpoint-operation"
        ),
    )
    supervisor.principal = SimpleNamespace()
    supervisor.replan = SimpleNamespace(latest_for_book=lambda _book_run_id: None)
    supervisor.realizations = SimpleNamespace(
        require_current_for_chapter=lambda **_values: {
            "realization_id": "realization:v1",
            "contract_digest": "sha256:" + "b" * 64,
        }
    )
    supervisor._checkpoint_if_needed = lambda _book: None
    supervisor._active_group_run = lambda _book, *_args: (
        {"group_run_id": "group-run:1", "state": "RUNNING"}
        if generated_contract == "CHAPTER"
        else None
    )

    def active_plan(_book, contract_type, _chapter_number):
        if contract_type == "CHAPTER_GROUP" and generated_contract == "CHAPTER":
            return {
                "asset_version_id": "chapter-group:v1",
                "content_hash": "sha256:" + "a" * 64,
                "execution_scope": PlanExecutionScope.FROZEN.value,
            }
        return None

    supervisor._active_plan = active_plan
    supervisor._generate_plan = lambda *_args: SimpleNamespace(
        status=PlanningGenerationStatus.ACTIVE,
        generation_operation_id="planning-operation:1",
        candidate_asset_version_id="planning-candidate:1",
    )

    tick = supervisor.tick("book-run:1")

    assert tick.action is expected_action
    assert tick.operation_id == "planning-operation:1"
    assert tick.evidence_ref == "planning-candidate:1"
    assert transitions == [
        (
            BookProductionState.CHAPTER_PLAN_REQUIRED
            if generated_contract == "CHAPTER_GROUP"
            else BookProductionState.READY
        )
    ]


def test_checkpoint_pending_records_accepted_checkpoint_without_dispatching() -> None:
    book = {
        "book_run_id": "book-run:1",
        "state": BookProductionState.CHECKPOINT_PENDING.value,
        "input_mode": "RESOLVED_AUTHORITY_INPUT",
        "accepted_through_chapter": 4,
    }
    supervisor = object.__new__(PostgresBookProductionSupervisor)
    supervisor.authority = SimpleNamespace(require=lambda _book_run_id: dict(book))
    supervisor._checkpoint_if_needed = lambda _book: {
        "volume_checkpoint": {"checkpoint_id": "volume-checkpoint:4"}
    }

    tick = supervisor.tick("book-run:1")

    assert tick.action is SupervisorAction.UPDATE_CHECKPOINTS
    assert tick.state == BookProductionState.CHECKPOINT_PENDING.value
    assert tick.evidence_ref == "volume-checkpoint:4"


@pytest.mark.parametrize(
    ("scope", "contract", "generator"),
    (
        ("NARRATIVE_SEGMENT", "VOLUME", "volume_plan.generate"),
        ("ARC_SEGMENT", "ARC", "arc_plan.generate"),
    ),
)
def test_segment_replan_scopes_reuse_parent_plan_authorities(
    scope: str, contract: str, generator: str
) -> None:
    assert SCOPE_CONTRACT[scope] == contract
    assert SCOPE_GENERATOR[scope] == generator
    command = CoordinateBookReplanCommand(
        project_id="project:1",
        workspace_id="workspace:1",
        book_id="book:1",
        book_run_id="book-run:1",
        source_recap_asset_version_id="recap:v1",
        replan_request_asset_version_id="replan-request:v1",
        affected_scope=scope,
        idempotency_key=f"replan:{scope}",
        trace_id="trace:1",
        correlation_id="correlation:1",
        target_asset_version_id=f"{contract.lower()}:v1",
    )

    assert command.affected_scope == scope


def test_arc_replan_preserves_unaffected_portfolio_versions() -> None:
    assert BookReplanCoordinator._replace_portfolio_version(
        ["arc:v1", "arc:v2", "arc:v3"],
        target_version_id="arc:v2",
        replacement_version_id="arc:v2:replacement",
    ) == ["arc:v1", "arc:v2:replacement", "arc:v3"]


def test_replan_chapter_context_uses_only_scheduled_nondormant_arcs() -> None:
    assert BookReplanCoordinator._scheduled_arc_versions(
        group_content={
            "chapter_function_matrix": [
                {
                    "chapter_number": 4,
                    "arc_cadence": [
                        {"arc_plan_version_id": "arc:v1", "action": "ADVANCE"},
                        {"arc_plan_version_id": "arc:v2", "action": "DORMANT"},
                        {"arc_plan_version_id": "arc:v3", "action": "PAYOFF"},
                    ],
                }
            ]
        },
        chapter=4,
        active_arc_plan_ids=["arc:v1", "arc:v2", "arc:v3"],
    ) == ["arc:v1", "arc:v3"]


def test_chapter_plan_inputs_bind_matrix_row_to_active_chapter_group() -> None:
    supervisor = object.__new__(PostgresBookProductionSupervisor)
    snapshot = {
        "book_plan_version": "book-plan:v1",
        "character_state_version": "character-state:v1",
        "foreshadowing_state_version": "foreshadowing-state:v1",
        "quality_trend_version": "quality-trend:v1",
        "reward_ledger_version": "reward-ledger:v1",
        "promise_ledger_version": "promise-ledger:v1",
    }
    latest = {
        "previous_chapter_outcome": "chapter-outcome:v0",
        "story_state": "story-state:v0",
        "canon_snapshot": "canon:v0",
        "reader_state": "reader-state:v0",
    }
    looked_up_roles: list[str] = []
    supervisor.query = SimpleNamespace(
        require_input_snapshot=lambda _snapshot_id: dict(snapshot)
    )
    supervisor._active_plan = lambda *_args: {
        "asset_version_id": "chapter-group:v1"
    }

    def latest_role_asset(_book, role):
        looked_up_roles.append(role)
        return latest.get(role, "")

    supervisor._latest_role_asset = latest_role_asset

    resolved = supervisor._resolve_generation_inputs(
        {
            "input_snapshot_id": "snapshot:1",
            "accepted_through_chapter": 0,
        },
        "chapter_plan.generate",
        primary_arc_version="arc:v1",
        volume_plan_version="volume:v1",
    )

    assert resolved["chapter_group_plan"] == "chapter-group:v1"
    assert resolved["chapter_function_matrix_row"] == "chapter-group:v1"
    assert "chapter_function_matrix_row" not in looked_up_roles


def test_supervisor_keeps_draft_budget_separate_from_quality_evidence_budget() -> None:
    supervisor = object.__new__(PostgresBookProductionSupervisor)
    supervisor.context_token_budget = 16_000
    supervisor.quality_context_token_budget = 28_000

    request = supervisor._chapter_preparation_request(
        book={
            "project_id": "project:1",
            "workspace_id": "workspace:1",
            "book_id": "book:1",
            "stable_idempotency_key": "book:1",
        },
        next_chapter=3,
        explicit_overrides={
            "chapter_plan": "chapter-plan:v3",
            "story_state_snapshot": "story-state:v2",
        },
    )

    assert request.context_token_budget == 16_000
    assert supervisor.quality_context_token_budget == 28_000
    assert request.chapter == 3
    assert request.idempotency_key == "book:1:chapter:3"
    assert request.explicit_asset_version_overrides == {
        "chapter_plan": "chapter-plan:v3",
        "story_state_snapshot": "story-state:v2",
    }

    report = supervisor._stage_budgeted_preparation_report(
        SimpleNamespace(
            preparation_report={"decision": "READY"},
            context_token_budget=request.context_token_budget,
        )
    )
    assert report == {
        "decision": "READY",
        "stage_context_token_budgets": {"draft": 16_000, "quality": 28_000},
    }


def test_supervisor_starts_replan_once_and_waits_for_authority_approval() -> None:
    state = {"value": BookProductionState.REPLAN_REQUIRED.value}
    book = {
        "book_run_id": "book-run:1",
        "project_id": "project:1",
        "workspace_id": "workspace:1",
        "book_id": "book:1",
        "root_operation_id": "book-operation:1",
        "stable_idempotency_key": "book-key:1",
        "accepted_through_chapter": 1,
        "state": state["value"],
        "input_mode": "RESOLVED_AUTHORITY_INPUT",
    }
    commands: list[CoordinateBookReplanCommand] = []

    def require(_book_run_id: str):
        return {**book, "state": state["value"]}

    def start(command: CoordinateBookReplanCommand):
        commands.append(command)
        state["value"] = BookProductionState.REPLAN_APPROVAL_PENDING.value
        return {
            "replan_id": "replan:1",
            "generation_operation_id": "planning-operation:1",
            "status": "APPROVAL_PENDING",
        }

    supervisor = object.__new__(PostgresBookProductionSupervisor)
    supervisor.authority = SimpleNamespace(require=require)
    supervisor.replan = SimpleNamespace(
        start=start,
        latest_for_book=lambda _book_run_id: {
            "replan_id": "replan:1",
            "status": "APPROVAL_PENDING",
        },
    )
    supervisor._checkpoint_if_needed = lambda _book: None
    supervisor.query = SimpleNamespace(
        require_replan_source=lambda **_values: {
            "recap_asset_version_id": "recap:v1",
            "replan_request_asset_version_id": "request:v1",
            "recap_operation_id": "recap-operation:1",
            "affected_scope": "CHAPTER_GROUP",
        }
    )

    started = supervisor.tick("book-run:1")
    waiting = supervisor.tick("book-run:1")

    assert started.action is SupervisorAction.START_REPLAN
    assert started.operation_id == "planning-operation:1"
    assert started.evidence_ref == "replan:1"
    assert waiting.action is SupervisorAction.WAIT_REPLAN_APPROVAL
    assert len(commands) == 1
    assert commands[0].idempotency_key == ("book-key:1:replan:1:recap-operation:1")


def test_supervisor_activates_formally_approved_replan_and_resumes() -> None:
    state = {"value": BookProductionState.REPLAN_GENERATING.value}
    book = {
        "book_run_id": "book-run:1",
        "state": state["value"],
        "input_mode": "RESOLVED_AUTHORITY_INPUT",
    }
    activated: list[str] = []
    superseded: list[tuple[str, str, str]] = []

    def require(_book_run_id: str):
        return {**book, "state": state["value"]}

    def activate(replan_id: str):
        activated.append(replan_id)
        state["value"] = BookProductionState.READY.value
        return {"replan_id": replan_id, "status": "RESUMED"}

    supervisor = object.__new__(PostgresBookProductionSupervisor)
    supervisor.authority = SimpleNamespace(require=require)
    supervisor.replan = SimpleNamespace(
        latest_for_book=lambda _book_run_id: {
            "replan_id": "replan:1",
            "status": "ACTIVE",
            "affected_scope": "CHAPTER_GROUP",
            "target_asset_version_id": "chapter-group:v1",
        },
        activate=activate,
    )
    supervisor.principal = SimpleNamespace()
    supervisor._active_group_run = lambda _book: {
        "group_run_id": "group-run:1",
    }
    supervisor.chapter_groups = SimpleNamespace(
        supersede_for_approved_replan=lambda group_run_id, **kwargs: superseded.append(
            (
                group_run_id,
                kwargs["replan_id"],
                kwargs["target_group_plan_version_id"],
            )
        )
    )

    tick = supervisor.tick("book-run:1")

    assert tick.action is SupervisorAction.ACTIVATE_REPLAN
    assert tick.state == BookProductionState.READY.value
    assert tick.evidence_ref == "replan:1"
    assert activated == ["replan:1"]
    assert superseded == [("group-run:1", "replan:1", "chapter-group:v1")]


def test_supervisor_finishes_replan_resume_after_snapshot_binding_restart() -> None:
    book = {
        "book_run_id": "book-run:1",
        "state": BookProductionState.READY.value,
        "input_mode": "RESOLVED_AUTHORITY_INPUT",
    }
    activated: list[str] = []
    replan = SimpleNamespace(
        latest_for_book=lambda _book_run_id: {
            "replan_id": "replan:1",
            "status": "REGENERATING",
        },
        activate=lambda replan_id: (
            activated.append(replan_id) or {"replan_id": replan_id, "status": "RESUMED"}
        ),
    )
    supervisor = object.__new__(PostgresBookProductionSupervisor)
    supervisor.authority = SimpleNamespace(require=lambda _book_run_id: dict(book))
    supervisor.replan = replan

    tick = supervisor.tick("book-run:1")

    assert tick.action is SupervisorAction.ACTIVATE_REPLAN
    assert tick.evidence_ref == "replan:1"
    assert activated == ["replan:1"]
