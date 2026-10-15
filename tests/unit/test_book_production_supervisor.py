from __future__ import annotations

from types import SimpleNamespace

import pytest

from novel_forge.modules.book_authority.production import BookProductionState
from novel_forge.modules.book_authority.supervisor import (
    PostgresBookProductionSupervisor,
    _bounded_chapter_group_range,
)
from novel_forge.modules.book_replan import CoordinateBookReplanCommand
from novel_forge.modules.book_replan.coordinator import (
    BookReplanCoordinator,
    SCOPE_CONTRACT,
    SCOPE_GENERATOR,
)
from novel_forge.modules.book_production import SupervisorAction
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.hierarchical_planning import PlanExecutionScope
from novel_forge.modules.story_planning_runtime import PlanningGenerationStatus


def test_activated_chapter_projection_is_materialized_by_owner_once_and_resumes():
    supervisor = object.__new__(PostgresBookProductionSupervisor)
    supervisor.query = SimpleNamespace(unresolved_chapter_effects=lambda **_: [])
    supervisor.principal = object()
    result = {"asset_version_id": "execution:exact", "content_hash": "hash"}
    projections = []
    calls = []

    def query(candidate, **kwargs):
        assert candidate == "candidate:active"
        return projections[0] if projections else None

    def materialize(candidate, **kwargs):
        assert candidate == "candidate:active"
        calls.append(kwargs)
        projections.append(result)
        raise RuntimeError("process lost response after native projection commit")

    supervisor.query = SimpleNamespace(require_chapter_execution_plan=query)
    supervisor.planning = SimpleNamespace(materialize_activated_chapter_plan_projection=materialize)
    book = {"book_run_id": "run:one", "active_chapter_request_id": ""}
    plan = {"asset_version_id": "candidate:active"}
    with pytest.raises(RuntimeError, match="lost response"):
        supervisor._require_chapter_execution_plan(book, plan)
    assert supervisor._require_chapter_execution_plan(book, plan) == result
    assert len(calls) == 1
    assert calls[0]["idempotency_key"] == "book:run:one:active-chapter-projection:candidate:active"
    assert calls[0]["principal"] is supervisor.principal


@pytest.mark.parametrize("conflicting", [False, True])
def test_projection_recovery_does_not_replace_frozen_request_or_ambiguous_projection(conflicting):
    supervisor = object.__new__(PostgresBookProductionSupervisor)
    supervisor.query = SimpleNamespace(unresolved_chapter_effects=lambda **_: [])
    calls = []

    def query(*args, **kwargs):
        if conflicting:
            raise KernelError("BOOK_SUPERVISOR_CHAPTER_PLAN_PROJECTION_INVALID", "multiple active projections")
        return None

    supervisor.query = SimpleNamespace(require_chapter_execution_plan=query)
    supervisor.planning = SimpleNamespace(materialize_activated_chapter_plan_projection=lambda *args, **kwargs: calls.append(args))
    with pytest.raises(KernelError, match="BOOK_SUPERVISOR_CHAPTER_PLAN_PROJECTION_INVALID"):
        supervisor._require_chapter_execution_plan({"book_run_id": "run:one", "active_chapter_request_id": "frozen-request"}, {"asset_version_id": "candidate:active"})
    assert calls == []


@pytest.mark.parametrize("candidate_legal,history", [
    (True, []),
    (False, []),
    (True, [("p", "h", {}, "source", "ACTIVE", "ELIGIBLE", "QUARANTINED", "SUCCEEDED")]),
    (True, [("p", "h", {}, "source", "SUPERSEDED", "ELIGIBLE", "CLEAR", "SUCCEEDED")]),
    (True, [("p", "h", {}, "source", "ACTIVE", "ELIGIBLE", "CLEAR", "FAILED_FINAL")]),
    (True, [("p", "h", {}, "source", "ACTIVE", "ELIGIBLE", "CLEAR", "SUCCEEDED"),
            ("old", "h", {}, "source", "SUPERSEDED", "ELIGIBLE", "CLEAR", "SUCCEEDED")]),
])
def test_projection_query_only_recovers_a_legal_candidate_without_any_output(monkeypatch, candidate_legal, history):
    from contextlib import nullcontext
    from novel_forge.modules.book_authority import queries
    cursor = SimpleNamespace(execute=lambda *args: None, fetchall=lambda: history,
                             fetchone=lambda: (1,) if candidate_legal and not history else None)
    monkeypatch.setattr(queries, "AuthorityUnitOfWork", lambda database_url: nullcontext(SimpleNamespace(cursor=cursor)))
    query = queries.PostgresBookProductionQuery("unused")
    if candidate_legal and not history:
        assert query.require_chapter_execution_plan("candidate", allow_missing=True) is None
    else:
        with pytest.raises(KernelError, match="BOOK_SUPERVISOR_CHAPTER_PLAN_PROJECTION_INVALID"):
            query.require_chapter_execution_plan("candidate", allow_missing=True)


@pytest.mark.parametrize("history,expected", [
    ([], None),
    ([("projection", "hash", "ACTIVE", "ELIGIBLE", "CLEAR", "SUCCEEDED", "project", "generation", "original-operation")], "projection"),
    ([("projection", "hash", "ACTIVE", "ELIGIBLE", "QUARANTINED", "SUCCEEDED", "project", "generation", "original-operation")], "INVALID"),
    ([("projection", "hash", "ACTIVE", "ELIGIBLE", "CLEAR", "SUCCEEDED", "project", "generation", "original-operation")] * 2, "INVALID"),
])
def test_materialization_reuses_exact_projection_and_keeps_disposition(history, expected):
    from novel_forge.modules.story_planning_runtime.application import StoryPlanningGenerationApplication
    reads = iter([("book",), ("candidate-hash", "ACTIVE", "ELIGIBLE", "CLEAR", "ACTIVE", True)])
    queries = []
    cursor = SimpleNamespace(execute=lambda sql, params: queries.append(sql), fetchone=lambda: next(reads), fetchall=lambda: history)
    uow = SimpleNamespace(cursor=cursor)
    kwargs = {"generation": {"project_id": "project", "book_id": "book", "generation_operation_id": "generation"},
              "candidate_asset_version_id": "candidate", "content_hash": "candidate-hash"}
    if expected == "INVALID":
        with pytest.raises(KernelError, match="BOOK_SUPERVISOR_CHAPTER_PLAN_PROJECTION_INVALID"):
            StoryPlanningGenerationApplication._lock_chapter_projection_source(uow, **kwargs)
    else:
        result = StoryPlanningGenerationApplication._lock_chapter_projection_source(uow, **kwargs)
        assert (result["asset_version_id"] if result else None) == expected
    assert "authority_book" in queries[0] and "FOR UPDATE" in queries[0]
    assert "FOR UPDATE OF state, version" in queries[1]
    assert "FOR UPDATE OF projection" in queries[2]


def test_supervisor_derives_two_exact_four_chapter_horizons() -> None:
    assert _bounded_chapter_group_range(
        start_chapter=1, target_chapter_count=8, preferred_size=4
    ) == (1, 4)
    assert _bounded_chapter_group_range(
        start_chapter=5, target_chapter_count=8, preferred_size=4
    ) == (5, 8)


@pytest.mark.parametrize(
    ("target", "preferred", "expected"),
    (
        (1, 4, (1, 1)),
        (2, 4, (1, 2)),
        (6, 4, (1, 4)),
        (9, 8, (1, 8)),
        (10, 8, (1, 8)),
        (11, 8, (1, 8)),
    ),
)
def test_supervisor_chapter_group_horizon_allows_positive_terminal_windows(
    target: int, preferred: int, expected: tuple[int, int]
) -> None:
    assert (
        _bounded_chapter_group_range(
            start_chapter=1,
            target_chapter_count=target,
            preferred_size=preferred,
        )
        == expected
    )


def test_supervisor_execution_cap_is_configurable_and_independent_of_recap() -> None:
    assert _bounded_chapter_group_range(
        start_chapter=1, target_chapter_count=30, preferred_size=12, maximum_chapters=12
    ) == (1, 12)
    assert _bounded_chapter_group_range(
        start_chapter=29,
        target_chapter_count=30,
        preferred_size=12,
        maximum_chapters=12,
    ) == (29, 30)


@pytest.mark.parametrize("target", [30, 40, 50])
def test_volume_groups_cover_thirteen_and_short_final_group_without_next_volume(target):
    groups = [_bounded_chapter_group_range(start_chapter=start, target_chapter_count=target,
                                           preferred_size=3, maximum_chapters=3)
              for start in range(1, target + 1, 3)]
    assert (13, 15) in groups
    assert [chapter for start, end in groups for chapter in range(start, end + 1)] == list(range(1, target + 1))
    if target == 40:
        assert groups[-2:] == [(37, 39), (40, 40)]


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
    supervisor.query = SimpleNamespace(unresolved_chapter_effects=lambda **_: [])
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
    supervisor.query = SimpleNamespace(unresolved_chapter_effects=lambda **_: [])
    supervisor._active_group_run = lambda _book: None
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
    supervisor.query = SimpleNamespace(unresolved_chapter_effects=lambda **_: [])
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
        unresolved_chapter_effects=lambda **_: [],
        require_input_snapshot=lambda _snapshot_id: dict(snapshot)
    )
    supervisor._active_plan = lambda *_args: {"asset_version_id": "chapter-group:v1"}

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
    supervisor.query = SimpleNamespace(unresolved_chapter_effects=lambda **_: [])
    supervisor.context_token_budget = 16_000
    supervisor.quality_context_token_budget = 28_000
    supervisor.draft_context_profile_version = "draft-context-profile-v2"
    supervisor.production_preparation = SimpleNamespace(
        resolver=SimpleNamespace(
            resolve_override=lambda **_values: SimpleNamespace(
                asset_type="production_profile",
                content={},
                book_scope_ids=(),
            )
        )
    )

    request = supervisor._chapter_preparation_request(
        book={
            "project_id": "project:1",
            "workspace_id": "workspace:1",
            "book_id": "book:1",
            "stable_idempotency_key": "book:1",
            "production_profile_version": "production-profile:v1",
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
    assert request.knowledge_access_policy["mode"] == "PROJECT_DEFAULT"
    assert request.knowledge_access_policy["configured_explicitly"] is False
    frozen_book = {
        "project_id": "project:1", "workspace_id": "workspace:1", "book_id": "book:1",
        "stable_idempotency_key": "book:1", "production_profile_version": "production-profile:v1",
        "longform_context_versions": {"platform_profile_version": "platform:frozen-v7"},
    }
    frozen = supervisor._chapter_preparation_request(book=frozen_book, next_chapter=1,
        explicit_overrides={"chapter_plan": "chapter-plan:v1"})
    assert frozen.explicit_asset_version_overrides["platform_profile"] == "platform:frozen-v7"
    with pytest.raises(KernelError, match="BOOK_FROZEN_PLATFORM_PROFILE_MISMATCH"):
        supervisor._chapter_preparation_request(book=frozen_book, next_chapter=1,
            explicit_overrides={"platform_profile": "platform:project-latest"})

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
    supervisor.draft_context_profile_version = "draft-context-profile-v3"
    newer = supervisor._stage_budgeted_preparation_report(SimpleNamespace(preparation_report={"decision": "READY"}, context_token_budget=20_000))
    assert newer["stage_context_profile_versions"] == {"draft": "draft-context-profile-v3"}
    assert "stage_context_profile_versions" not in report


def test_supervisor_freezes_exact_character_and_reader_promise_foundation() -> None:
    snapshot = {
        "foundation_set": {
            "bindings": [
                {
                    "role": "CHARACTER_CAST",
                    "asset_version_id": "character-cast:v7",
                    "content_hash": "sha256:" + "1" * 64,
                },
                {
                    "role": "READER_PROMISE",
                    "asset_version_id": "reader-promise:v4",
                    "content_hash": "sha256:" + "2" * 64,
                },
            ]
        }
    }

    assert PostgresBookProductionSupervisor._chapter_foundation_overrides(snapshot) == {
        "character_cast": "character-cast:v7",
        "reader_promise": "reader-promise:v4",
    }

    with pytest.raises(KernelError, match="BOOK_SUPERVISOR_FOUNDATION_CONTEXT_MISSING"):
        PostgresBookProductionSupervisor._chapter_foundation_overrides(
            {"foundation_set": {"bindings": snapshot["foundation_set"]["bindings"][:1]}}
        )


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
    supervisor.query = SimpleNamespace(unresolved_chapter_effects=lambda **_: [])
    supervisor._active_group_run = lambda _book: None
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
        unresolved_chapter_effects=lambda **_: [],
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
    supervisor.query = SimpleNamespace(unresolved_chapter_effects=lambda **_: [])
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
    supervisor.query = SimpleNamespace(unresolved_chapter_effects=lambda **_: [])
    supervisor._active_group_run = lambda _book: None
    supervisor.authority = SimpleNamespace(require=lambda _book_run_id: dict(book))
    supervisor.replan = replan

    tick = supervisor.tick("book-run:1")

    assert tick.action is SupervisorAction.ACTIVATE_REPLAN
    assert tick.evidence_ref == "replan:1"
    assert activated == ["replan:1"]


def test_edition_planning_consumes_its_exact_accepted_frontier():
    supervisor = object.__new__(PostgresBookProductionSupervisor)
    supervisor.query = SimpleNamespace(unresolved_chapter_effects=lambda **_: [])
    snapshot = {key + "_version": key + ":snapshot" for key in ("book_plan", "character_state", "foreshadowing_state", "quality_trend", "reward_ledger", "promise_ledger")}
    supervisor.query = SimpleNamespace(unresolved_chapter_effects=lambda **_: [], require_input_snapshot=lambda _: snapshot)
    supervisor._active_plan = lambda *_: {"asset_version_id": "group:edition"}
    seen = []
    supervisor._latest_role_asset = lambda _, role: seen.append(role) or "unrelated-latest:" + role
    result = supervisor._resolve_generation_inputs({"input_snapshot_id": "snapshot", "accepted_through_chapter": 1,
        "active_story_state_version_id": "source-prefix-state:exact", "active_canon_snapshot_version_id": "source-prefix-canon:exact",
        "last_chapter_outcome_version_id": "source-prefix-outcome:exact"}, "chapter_plan.generate", primary_arc_version="arc", volume_plan_version="volume")
    assert result["story_state"] == "source-prefix-state:exact"
    assert result["canon_snapshot"] == "source-prefix-canon:exact"
    assert result["previous_chapter_outcome"] == "source-prefix-outcome:exact"
    assert not {"story_state", "canon_snapshot", "previous_chapter_outcome"}.intersection(seen)


def test_reader_planning_uses_effective_run_history_before_initial_profile():
    supervisor = object.__new__(PostgresBookProductionSupervisor)
    supervisor.query = SimpleNamespace(unresolved_chapter_effects=lambda **_: [])
    calls = []
    supervisor.query = SimpleNamespace(
        unresolved_chapter_effects=lambda **_: [],
        previous_reader_state=lambda **kwargs: calls.append(kwargs) or "reader-prefix:exact",
        latest_eligible_role_asset=lambda **kwargs: (_ for _ in ()).throw(AssertionError("Another edition's transition must not be queried")),
    )
    book = {"book_run_id": "edition:run", "accepted_through_chapter": 1}
    assert supervisor._latest_role_asset(book, "reader_state") == "reader-prefix:exact"
    assert calls == [{"book_run_id": "edition:run", "chapter_number": 2}]
    supervisor.query.previous_reader_state = lambda **_: "NONE"
    supervisor.query.latest_eligible_role_asset = lambda **kwargs: calls.append(kwargs) or "reader-initial"
    assert supervisor._latest_role_asset({**book, "project_id": "project", "book_id": "book"}, "reader_state") == "reader-initial"
    assert calls[-1]["asset_types"] == ("reader_state",)


def test_explicit_profile_context_survives_process_defaults_and_new_profile_selection() -> None:
    supervisor = object.__new__(PostgresBookProductionSupervisor)
    supervisor.query = SimpleNamespace(unresolved_chapter_effects=lambda **_: [])
    supervisor.context_token_budget = 6000
    supervisor.quality_context_token_budget = 7000
    supervisor.draft_context_profile_version = "draft-context-profile-v2"
    policies = {
        "profile:old": {"chapter_context_policy": {"version": "book-chapter-context.v1", "draft_profile": "draft-context-profile-v2", "draft_token_budget": 12000, "quality_token_budget": 18000}},
        "profile:new": {"chapter_context_policy": {"version": "book-chapter-context.v1", "draft_profile": "draft-context-profile-v3", "draft_token_budget": 20000, "quality_token_budget": 28000}},
    }
    supervisor.production_preparation = SimpleNamespace(resolver=SimpleNamespace(resolve_override=lambda **values: SimpleNamespace(asset_type="production_profile", content=policies[values["asset_version_id"]], book_scope_ids=())))
    book = {"project_id": "p", "workspace_id": "w", "book_id": "b", "stable_idempotency_key": "run:1", "production_profile_version": "profile:old"}
    old_request = supervisor._chapter_preparation_request(book=book, next_chapter=1, explicit_overrides={})
    old_report = supervisor._stage_budgeted_preparation_report(SimpleNamespace(preparation_report={}, context_token_budget=old_request.context_token_budget), book=book)
    new_book = {**book, "production_profile_version": "profile:new", "stable_idempotency_key": "run:2"}
    new_request = supervisor._chapter_preparation_request(book=new_book, next_chapter=1, explicit_overrides={})
    new_report = supervisor._stage_budgeted_preparation_report(SimpleNamespace(preparation_report={}, context_token_budget=new_request.context_token_budget), book=new_book)
    supervisor.context_token_budget = 24000
    supervisor.draft_context_profile_version = "draft-context-profile-v3"
    restored = supervisor._chapter_preparation_request(book=book, next_chapter=1, explicit_overrides={})
    assert restored == old_request
    assert old_request.context_token_budget == 12000
    assert old_report["stage_context_profile_versions"]["draft"] == "draft-context-profile-v2"
    assert old_report["stage_context_token_budgets"]["quality"] == 18000
    assert new_request.context_token_budget == 20000
    assert new_report["chapter_context_policy"]["production_profile_version"] == "profile:new"
    assert new_report["stage_context_profile_versions"]["draft"] == "draft-context-profile-v3"
    assert new_report["stage_context_token_budgets"]["quality"] == 28000
