from __future__ import annotations

from types import SimpleNamespace

import pytest

from novel_forge.modules.book_authority.production import BookProductionState
from novel_forge.modules.book_authority.supervisor import (
    PostgresBookProductionSupervisor,
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
        "state": BookProductionState.READY.value,
        "input_mode": "RESOLVED_AUTHORITY_INPUT",
        "accepted_through_chapter": 0,
        "target_chapter_count": 3,
    }
    supervisor = object.__new__(PostgresBookProductionSupervisor)
    supervisor.authority = SimpleNamespace(require=lambda _book_run_id: dict(book))
    supervisor._checkpoint_if_needed = lambda _book: None
    supervisor._set_state = lambda _book, _state: "checkpoint-operation"
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


def test_supervisor_freezes_configured_context_budget_in_preparation_request() -> None:
    supervisor = object.__new__(PostgresBookProductionSupervisor)
    supervisor.context_token_budget = 28_000

    request = supervisor._chapter_preparation_request(
        book={
            "project_id": "project:1",
            "workspace_id": "workspace:1",
            "stable_idempotency_key": "book:1",
        },
        next_chapter=3,
        explicit_overrides={
            "chapter_plan": "chapter-plan:v3",
            "story_state_snapshot": "story-state:v2",
        },
    )

    assert request.context_token_budget == 28_000
    assert request.chapter == 3
    assert request.idempotency_key == "book:1:chapter:3"
    assert request.explicit_asset_version_overrides == {
        "chapter_plan": "chapter-plan:v3",
        "story_state_snapshot": "story-state:v2",
    }
