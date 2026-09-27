from types import SimpleNamespace
from copy import deepcopy
from dataclasses import replace

import pytest

from novel_forge.modules.book_authority.governed_scheduler import PostgresBookAuthorityScheduler
from novel_forge.modules.book_authority.supervisor import PostgresBookProductionSupervisor
from novel_forge.modules.book_production import SupervisorAction
from novel_forge.modules.chapter_group_authority.application import PostgresChapterGroupAuthority
from novel_forge.modules.command_kernel.errors import KernelError


def boundaries():
    group = {"group_run_id": "group", "book_run_id": "run", "project_id": "project", "group_plan_version_id": "plan",
        "accepted_through_chapter": 1, "chapter_start": 1, "chapter_end": 3, "state": "READY", "active_chapter_request_id": None}
    book = {"book_run_id": "run", "project_id": "project", "state": "CHAPTER_SUBMITTED", "accepted_through_chapter": 1,
        "active_chapter_request_id": "request", "input_mode": "RESOLVED_AUTHORITY_INPUT"}
    request = {"chapter_request_id": "request", "book_run_id": "run", "project_id": "project", "chapter_number": 2,
        "parent_group_version_id": "plan", "status_reference": "SUBMITTING", "chapter_root_operation_id": None,
        "command_payload": {"book_run_id": "run", "parent_group_version_id": "plan"}}
    return group, book, request


@pytest.mark.parametrize("scope,key,value", [("group", "book_run_id", "other"), ("group", "group_plan_version_id", "other"),
    ("group", "state", "PAUSED"), ("group", "active_chapter_request_id", "other"), ("book", "active_chapter_request_id", "later"),
    ("book", "accepted_through_chapter", 2), ("book", "state", "ABORTED"), ("request", "project_id", "other")])
def test_dispatch_recovery_rejects_foreign_stale_or_controlled_scope(scope, key, value):
    group, book, request = boundaries()
    PostgresChapterGroupAuthority._require_recoverable_dispatch(group, book, request)
    {"group": group, "book": book, "request": request}[scope][key] = value
    with pytest.raises(KernelError, match="CHAPTER_GROUP_DISPATCH_RECOVERY"):
        PostgresChapterGroupAuthority._require_recoverable_dispatch(group, book, request)


def test_ungrouped_scheduler_consumes_existing_frozen_reservation():
    _, book, request = boundaries()
    request["parent_group_version_id"] = None
    calls = []
    authority = SimpleNamespace(require=lambda _: book, require_chapter_request=lambda _: request,
        recover_chapter_submission=lambda request_id, **_: calls.append(request_id) or {"chapter_root_operation_id": "same-root"})
    scheduler = PostgresBookAuthorityScheduler(authority, query=None, principal=None)
    tick = scheduler.tick("run")
    assert (tick.action, tick.operation_id, calls) == ("DISPATCH_CHAPTER", "same-root", ["request"])


def test_supervisor_recovers_group_link_before_reconciliation():
    group, book, request = boundaries()
    supervisor = object.__new__(PostgresBookProductionSupervisor)
    supervisor.authority = SimpleNamespace(require=lambda _: book,
        require_chapter_request=lambda _: {**request, "chapter_root_operation_id": "same-root"})
    supervisor.principal = None
    supervisor._active_group_run = lambda _: group
    recovered = {**group, "active_chapter_request_id": "request", "state": "CHAPTER_RUNNING"}
    calls = []
    supervisor.chapter_groups = SimpleNamespace(recover_dispatch=lambda group_id, **_: calls.append(group_id) or recovered)
    tick = supervisor.tick("run")
    assert tick.action is SupervisorAction.DISPATCH_CHAPTER
    assert tick.operation_id == "same-root"
    assert calls == ["group"]


def frozen_chapter_admission():
    from novel_forge.modules.chapter_authority.orchestrator import SingleChapterRequest, _bind_context_candidate_scope, _command
    request = SingleChapterRequest(project_id="project", workspace_id="workspace", actor_id="original-operator",
        chapter=2, title="承诺", premise="延续已接纳承诺", trace_id="trace", correlation_id="correlation",
        application_build_id="frozen-build", commit_sha="e" * 40, book_id="book",
        chapter_plan_asset_version_id="plan:2", chapter_plan_content_hash="sha256:plan",
        idempotency_key="stable-chapter", context_candidates=({"asset_type": "chapter_plan",
            "asset_version_id": "plan:2", "content_hash": "sha256:plan"},))
    bound = _bind_context_candidate_scope(request)
    root_id, saga_id, plan_id = "root", "saga", "plan-operation"
    root_command = _command(bound, definition_name="chapter.slice.run", definition_version="1.0.0",
        idempotency_key=request.idempotency_key, input_assets=[{"asset_version_id": "plan:2", "content_hash": "sha256:plan"}])
    plan_refs = [{"asset_version_id": "plan:2", "content_hash": "sha256:plan"}]
    plan_command = _command(bound, definition_name="chapter.plan.materialize", definition_version="1.0.0",
        idempotency_key=request.idempotency_key + ":plan", input_assets=plan_refs,
        root_operation_id=root_id, parent_operation_id=root_id, causation_operation_id=root_id)
    common = {"project_id": "project", "workspace_id": "workspace", "actor_id": request.actor_id,
              "definition_version": "1.0.0", "idempotency_scope": "project:chapter-slice", "saga_id": saga_id}
    root = {**common, "operation_id": root_id, "root_operation_id": root_id, "status": "EXECUTING",
            "definition_name": "chapter.slice.run", "idempotency_key": request.idempotency_key,
            "command_payload": root_command["input"], "input_asset_snapshot": deepcopy(plan_refs)}
    plan = {**common, "operation_id": plan_id, "root_operation_id": root_id, "parent_operation_id": root_id,
            "causation_operation_id": root_id, "step_key": "plan", "definition_name": "chapter.plan.materialize",
            "idempotency_key": request.idempotency_key + ":plan", "command_payload": plan_command["input"],
            "input_asset_snapshot": plan_refs}
    return request, [root, {"saga_id": saga_id, "root_operation_id": root_id, "project_id": "project"},
                     {"operation_id": plan_id, "step_key": "plan", "ordinal": 1}, plan]


def recover_frozen(monkeypatch, request, row):
    from novel_forge.modules.chapter_authority import orchestrator
    statements = []
    class Uow:
        def __enter__(self):
            self.cursor = SimpleNamespace(execute=lambda sql, params: statements.append((sql, params)), fetchone=lambda: row)
            return self
        def __exit__(self, *args):
            return None
    monkeypatch.setattr(orchestrator, "AuthorityUnitOfWork", lambda _: Uow())
    result = orchestrator.recover_single_chapter_admission("unused", request=request)
    assert len(statements) == 1 and statements[0][0].lstrip().startswith("SELECT")
    assert statements[0][1][1:] == [request.project_id, request.idempotency_key]
    return result


def test_alternate_authorized_actor_reuses_frozen_admission_without_actor_rewrite(monkeypatch):
    request, row = frozen_chapter_admission()
    before = deepcopy(row)
    result = recover_frozen(monkeypatch, replace(request, actor_id="recovery-operator"), row)
    assert (result.root_operation_id, result.saga_id, result.first_operation_id, result.replayed) == ("root", "saga", "plan-operation", True)
    assert row == before
    assert recover_frozen(monkeypatch, request, None) is None


@pytest.mark.parametrize("damage", ["missing_saga", "missing_plan", "admitted_root", "foreign_workspace", "foreign_plan",
    "different_plan_hash", "changed_payload", "changed_context_budget", "changed_plan_payload"])
def test_existing_admission_rejects_partial_graph_scope_or_frozen_input_drift(monkeypatch, damage):
    request, row = frozen_chapter_admission()
    if damage == "missing_saga":
        row[1] = None
    elif damage == "missing_plan":
        row[3] = None
    elif damage == "admitted_root":
        row[0]["status"] = "ADMITTED"
    elif damage == "foreign_workspace":
        row[0]["workspace_id"] = "foreign"
    elif damage == "foreign_plan":
        row[3]["root_operation_id"] = "foreign"
    elif damage == "different_plan_hash":
        row[3]["input_asset_snapshot"][0]["content_hash"] = "sha256:changed"
    elif damage == "changed_payload":
        row[0]["command_payload"]["premise"] = "changed"
    elif damage == "changed_context_budget":
        request = replace(request, context_token_budget=1)
    else:
        row[3]["command_payload"]["preparation_report"] = {"book_edition": {"revision_id": "foreign"}}
    with pytest.raises(KernelError, match="CHAPTER_ADMISSION_(REQUIRES_RECOVERY|RECOVERY_SCOPE_DRIFT|RECOVERY_INPUT_DRIFT)"):
        recover_frozen(monkeypatch, request, row)


def test_admission_recovery_requires_current_chapter_permission_before_database(monkeypatch):
    from novel_forge.modules.chapter_authority.application import ChapterAuthorityApplication
    request, _ = frozen_chapter_admission()
    app = object.__new__(ChapterAuthorityApplication)
    def deny(*args): raise PermissionError("not authorized")
    with pytest.raises(PermissionError, match="not authorized"):
        app.recover_admission(request, principal=SimpleNamespace(require=deny))


@pytest.mark.parametrize("damage", [None, "partial", "scope", "payload", "input_hash"])
def test_group_recovery_reuses_only_complete_exact_dispatch_step(damage):
    group, _, request = boundaries()
    group.update(stable_idempotency_key="group-key", root_operation_id="group-root", saga_id="group-saga")
    request.update(chapter_plan_version="plan:2")
    request["command_payload"]["chapter_plan_content_hash"] = "sha256:plan"
    operation = {"status": "SUCCEEDED", "definition_name": "chapter_group.chapter.dispatch",
        "command_payload": {"project_id": "project", "input_asset_version_ids": ["plan:2"],
            "payload": {"group_run_id": "group", "chapter_number": 2}},
        "root_operation_id": "group-root", "parent_operation_id": "group-root", "causation_operation_id": "group-root",
        "saga_id": "group-saga", "input_asset_snapshot": [{"asset_version_id": "plan:2", "content_hash": "sha256:plan"}]}
    step = {"saga_id": "group-saga", "step_key": "chapter_group.chapter.dispatch:chapter:2", "ordinal": 120}
    if damage == "partial":
        operation["status"] = "ADMITTED"
    elif damage == "scope":
        step["saga_id"] = "foreign"
    elif damage == "payload":
        operation["command_payload"]["payload"]["chapter_number"] = 3
    elif damage == "input_hash":
        operation["input_asset_snapshot"][0]["content_hash"] = "sha256:other"
    cursor = SimpleNamespace(execute=lambda *args: None, fetchone=lambda: (operation, step))
    if damage:
        with pytest.raises(KernelError, match="CHAPTER_GROUP_DISPATCH_(REQUIRES_RECOVERY|RECOVERY_CONFLICT)"):
            PostgresChapterGroupAuthority._existing_dispatch_step(cursor, group, request)
    else:
        assert PostgresChapterGroupAuthority._existing_dispatch_step(cursor, group, request)
