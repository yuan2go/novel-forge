from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from novel_forge.modules.book_authority import queries
from novel_forge.modules.book_authority.supervisor import (
    PostgresBookProductionSupervisor,
    SupervisorAction,
)
from novel_forge.modules.command_kernel import budget_runtime
from novel_forge.modules.command_kernel.errors import KernelError


def test_original_book_query_uses_book_scope_across_successor_root_names(monkeypatch):
    cursor = SimpleNamespace(
        execute=Mock(), fetchone=Mock(return_value=("project", "original-book"))
    )
    monkeypatch.setattr(
        queries,
        "AuthorityUnitOfWork",
        lambda _: nullcontext(SimpleNamespace(cursor=cursor)),
    )
    receipt = {
        "external_effect_id": "original-effect",
        "operation_id": "old-root-step",
        "process_receipt_ref": "original-process",
        "usage": "UNKNOWN",
    }
    read = Mock(return_value=[receipt])
    monkeypatch.setattr(budget_runtime, "unresolved_cli_outcomes", read)
    assert queries.PostgresBookProductionQuery("unused").unresolved_chapter_effects(
        book_run_id="original-run"
    ) == [receipt]
    read.assert_called_once_with(cursor, "project", book_id="original-book")
    assert cursor.execute.call_args_list[0].args[1] == ["original-run"]


def test_missing_book_scope_cannot_project_unknown_receipts_as_known(monkeypatch):
    cursor = SimpleNamespace(execute=Mock(), fetchone=Mock(return_value=None))
    monkeypatch.setattr(
        queries,
        "AuthorityUnitOfWork",
        lambda _: nullcontext(SimpleNamespace(cursor=cursor)),
    )
    read = Mock()
    monkeypatch.setattr(budget_runtime, "unresolved_cli_outcomes", read)
    with pytest.raises(KernelError, match="Original Book scope"):
        queries.PostgresBookProductionQuery("unused").unresolved_chapter_effects(
            book_run_id="missing"
        )
    read.assert_not_called()


def test_supervisor_original_unknown_wait_precedes_group_or_planning_mutation():
    book = {
        "book_run_id": "book-run",
        "state": "READY",
        "version": 1,
        "input_mode": "RESOLVED_AUTHORITY_INPUT",
    }
    supervisor = object.__new__(PostgresBookProductionSupervisor)
    supervisor.authority = SimpleNamespace(require=Mock(return_value=book))
    supervisor.query = SimpleNamespace(
        unresolved_chapter_effects=Mock(return_value=[{"usage": "UNKNOWN"}])
    )
    supervisor._active_group_run = Mock()
    result = supervisor.tick("book-run")
    assert result.action is SupervisorAction.WAIT_EXTERNAL_RECONCILIATION
    supervisor.query.unresolved_chapter_effects.assert_called_once_with(
        book_run_id="book-run"
    )
    supervisor._active_group_run.assert_not_called()


@pytest.mark.parametrize("production_row", [("book-run", "CHAPTER_RUNNING", 0, 3, 1, 0), None])
def test_author_status_projects_original_unknown_receipt_as_runtime_reconciliation(
    monkeypatch, production_row,
):
    from novel_forge.modules.book_authority import creation_runtime
    from novel_forge.storage import story_formation_repositories

    monkeypatch.setattr(
        creation_runtime, "creation_progress", lambda *args, **kwargs: ()
    )
    rows = iter([None, production_row])
    cursor = SimpleNamespace(execute=Mock(), fetchone=lambda: next(rows))
    run = {
        "project_id": "project", "book_id": "original-book",
        "lifecycle": "WAITING_APPROVAL",
        "recovery_instruction": {},
        "current_stage": "PLAN",
        "version": 1,
        "failure": {},
    }
    repository = SimpleNamespace(
        require=lambda _: run,
        cancellation=lambda _: None,
        approval_wait=lambda *args: {"candidate_asset_version_ids": []},
    )
    monkeypatch.setattr(
        story_formation_repositories, "StoryFormationRepository", lambda _: repository
    )
    monkeypatch.setattr(
        creation_runtime,
        "AuthorityUnitOfWork",
        lambda _: nullcontext(SimpleNamespace(cursor=cursor)),
    )
    receipt = {
        "external_effect_id": "original-effect",
        "operation_id": "original-operation",
        "process_receipt_ref": "original-process",
        "usage": "UNKNOWN",
    }
    read = Mock(return_value=[receipt])
    monkeypatch.setattr(
        queries,
        "PostgresBookProductionQuery",
        lambda _: SimpleNamespace(unresolved_chapter_effects=read),
    )
    monkeypatch.setattr(budget_runtime, "unresolved_cli_outcomes", read)
    status = creation_runtime.creation_status(
        "unused",
        project_id="project",
        formation_run_id="formation",
        principal=SimpleNamespace(require=Mock()),
    )
    assert status["unresolved_external_effects"] == [receipt]
    assert status["author_state"] == "RECONCILIATION_REQUIRED"
    assert status["responsible_party"] == "RUNTIME_OWNER"
    assert status["next_action"] == "RECONCILE_ORIGINAL_EXTERNAL_EFFECTS"
    if production_row:
        read.assert_called_once_with(book_run_id="book-run")
    else:
        read.assert_called_once_with(cursor, "project", book_id="original-book")


def test_current_v7_creation_binding_retains_original_actor_digest_and_scope(
    monkeypatch,
):
    cursor = SimpleNamespace(
        execute=Mock(),
        fetchall=Mock(
            return_value=[("formation", "original-digest", "original-author")]
        ),
    )
    monkeypatch.setattr(
        queries,
        "AuthorityUnitOfWork",
        lambda _: nullcontext(SimpleNamespace(cursor=cursor)),
    )
    binding = queries.PostgresBookProductionQuery("unused").creation_executor_binding(
        project_id="project", subject_id="chapter-root"
    )
    assert binding == {
        "formation_run_id": "formation",
        "frozen_input_digest": "original-digest",
        "operator_id": "original-author",
    }
    sql, parameters = cursor.execute.call_args.args
    assert "IN ('formation-generation.v5','formation-generation.v7')" in sql
    assert "formation-generation.v6" not in sql
    assert "auto_authorization,authorized_by_principal_id" in sql
    assert (
        "request.chapter_root_operation_id=%s" in sql
        and "production.project_id=run.project_id" in sql
    )
    assert parameters == [
        "chapter-root",
        "chapter-root",
        "project",
        "chapter-root",
        "project",
        "chapter-root",
        "project",
        "project",
    ]
