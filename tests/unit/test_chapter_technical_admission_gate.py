from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from novel_forge.modules.chapter_authority.scheduler import ChapterAuthorityScheduler
from novel_forge.modules.command_kernel.errors import KernelError


def native(monkeypatch, *, failure=None, drift=None, expired=False):
    from novel_forge.modules.command_kernel import step_successor, step_successor_v2, derived_step_revalidation
    root = {"operation_id": "root", "project_id": "project", "workspace_id": "workspace", "actor_id": "author",
        "definition_name": "chapter.slice.run", "definition_version": "3.10.0", "status": "WAITING_GATE",
        "command_payload": {}, "input_asset_snapshot": [], "definition_snapshot": {}, "version": 1}
    actual = deepcopy(root)
    if drift:
        actual.update(drift)
    deadline = datetime.now(timezone.utc) + timedelta(seconds=-1 if expired else 60)
    calls = []
    class Cursor:
        def execute(self, sql, params):
            calls.append(("lock-root", params))
        def fetchone(self):
            return actual, deadline
    def checked(name):
        def guard(*args, **kwargs):
            calls.append((name, kwargs))
            if failure == name:
                raise KernelError("NATIVE_GUARD_REJECTED", name)
        return guard
    monkeypatch.setattr(step_successor, "require_live_chapter_frontier", checked("book-frontier"))
    monkeypatch.setattr(step_successor_v2, "_require_reconciled_graph", checked("graph-reconciliation"))
    monkeypatch.setattr(derived_step_revalidation, "_settled_graph", checked("exact-settlement"))
    def saga_lock(*args):
        calls.append(("lock-saga", args))
        return {"root_operation_id": "root"}
    uow = SimpleNamespace(cursor=Cursor(), repositories=SimpleNamespace(operation_graph=SimpleNamespace(saga_for_update=saga_lock)))
    scheduler = object.__new__(ChapterAuthorityScheduler)
    return scheduler, uow, root, {"saga_id": "saga"}, calls


def test_current_technical_gate_keeps_native_lock_order_and_all_guards(monkeypatch):
    scheduler, uow, root, saga, calls = native(monkeypatch)
    assert scheduler._require_technical_gate_frontier(uow, root, saga) == root
    assert [name for name, _ in calls] == ["lock-saga", "lock-root", "book-frontier", "graph-reconciliation", "exact-settlement"]
    assert calls[2][1] == {"root_id": "root", "project_id": "project"}


@pytest.mark.parametrize("failure", ["book-frontier", "graph-reconciliation", "exact-settlement"])
def test_technical_recheck_does_not_bypass_cancellation_unknown_lease_or_cost_guard(monkeypatch, failure):
    scheduler, uow, root, saga, _ = native(monkeypatch, failure=failure)
    with pytest.raises(KernelError, match="NATIVE_GUARD_REJECTED"):
        scheduler._require_technical_gate_frontier(uow, root, saga)


@pytest.mark.parametrize("drift", [{"actor_id": "foreign"}, {"workspace_id": "foreign"}, {"status": "CANCELLED"},
    {"definition_version": "3.9.0"}, {"command_payload": {"changed": True}}])
def test_technical_recheck_preserves_scope_and_historical_version(monkeypatch, drift):
    scheduler, uow, root, saga, _ = native(monkeypatch, drift=drift)
    with pytest.raises(KernelError, match="CHAPTER_TECHNICAL_GATE_SCOPE_DRIFT"):
        scheduler._require_technical_gate_frontier(uow, root, saga)


def test_implementation_change_cannot_extend_frozen_business_deadline(monkeypatch):
    scheduler, uow, root, saga, calls = native(monkeypatch, expired=True)
    with pytest.raises(KernelError, match="OPERATION_BUSINESS_TIMEOUT"):
        scheduler._require_technical_gate_frontier(uow, root, saga)
    assert [name for name, _ in calls] == ["lock-saga", "lock-root"]


def test_current_cancellation_only_visits_existing_cancelled_work(monkeypatch):
    from novel_forge.modules.chapter_authority import scheduler as module
    from novel_forge.modules.chapter_authority.contracts import ChapterNode
    from novel_forge.modules.book_authority import execution_recovery, execution_recovery_v2
    monkeypatch.setattr(execution_recovery, "require_dispatch", lambda *args, **kwargs: None)
    monkeypatch.setattr(execution_recovery_v2, "require_dispatch", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "coordinate_saga", lambda *args, **kwargs: {"status": "CANCELLATION_REQUESTED"})
    scheduler = object.__new__(ChapterAuthorityScheduler)
    scheduler.database_url, scheduler.worker_id = "unit-only", "worker"
    root = {"operation_id": "root", "project_id": "project", "definition_version": "3.10.0", "status": "CANCELLATION_REQUESTED",
        "command_payload": {}, "definition_snapshot": {"policy": {}}, "trace_id": "trace", "correlation_id": "correlation"}
    child = {"operation_id": "existing", "status": "CANCELLATION_REQUESTED"}
    scheduler._graph_state = lambda *args: (root, {"saga_id": "saga"}, {ChapterNode.DRAFT: child})
    scheduler._request_from_root = lambda root: root
    visited = []
    scheduler._execute_node = lambda request, node, operation: visited.append((node, operation["operation_id"]))
    scheduler._admit_node = lambda **kwargs: pytest.fail("Cancellation must not admit any new child")
    result = scheduler.tick(project_id="project", root_operation_id="root")
    assert result.recovery_mode == "cancel_existing_children_only"
    assert visited == [(ChapterNode.DRAFT, "existing")]
