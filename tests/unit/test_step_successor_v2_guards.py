from unittest.mock import Mock
from datetime import datetime, timedelta, timezone

import pytest

from novel_forge.modules.command_kernel import step_successor_v2 as recovery
from novel_forge.modules.command_kernel.errors import KernelError


@pytest.mark.parametrize("facts", [(True, False, False), (False, True, False), (False, False, True)])
def test_unknown_accounting_lease_or_cancellation_prevents_successor_mutation(facts):
    cursor = Mock()
    cursor.fetchone.side_effect = [("project",), ("root", ""), facts]
    cursor.fetchall.return_value = []
    with pytest.raises(KernelError, match="STEP_SUCCESSOR_GRAPH_UNRECONCILED"):
        recovery._require_reconciled_graph(cursor, root_id="root", predecessor_id="source")


def test_old_settled_local_timeout_cannot_enable_a_pure_host_successor():
    cursor = Mock()
    cursor.fetchone.side_effect = [("project",), ("root", "original-book"), None, None]
    cursor.fetchall.return_value = [("old-effect", "old-operation", "FAILED_RETRYABLE", "old-process")]
    with pytest.raises(KernelError, match="EFFECT_CLI_OUTCOME_RECONCILIATION_REQUIRED"):
        recovery._require_reconciled_graph(cursor, root_id="root", predecessor_id="source")


@pytest.mark.parametrize("budget", [None, "RESERVED", "HELD_UNKNOWN"])
def test_raw_success_is_not_a_settled_verified_receipt(monkeypatch, budget):
    repository = Mock()
    repository.get_for_update.return_value = {"operation_id": "source", "request_hash": "request"}
    monkeypatch.setattr(recovery, "ExternalEffectRepository", lambda _: repository)
    monkeypatch.setattr(recovery, "_read_verified_success", lambda *_: None if budget is None else {"budget_reservation_status": budget})
    source = dict(operation_id="source", project_id="project", actor_id="actor", trace_id="trace", correlation_id="correlation")
    with pytest.raises(KernelError, match="STEP_SUCCESSOR_RECEIPT_UNSETTLED"):
        recovery._require_verified_receipts(Mock(), source=source, expected=[("effect", "request")])


def test_foreign_success_cannot_authorize_this_successor(monkeypatch):
    repository = Mock()
    repository.get_for_update.return_value = {"operation_id": "foreign", "request_hash": "request"}
    reader = Mock()
    monkeypatch.setattr(recovery, "ExternalEffectRepository", lambda _: repository)
    monkeypatch.setattr(recovery, "_read_verified_success", reader)
    source = dict(operation_id="source", project_id="project", actor_id="actor", trace_id="trace", correlation_id="correlation")
    with pytest.raises(KernelError, match="STEP_SUCCESSOR_RECEIPT_DRIFT"):
        recovery._require_verified_receipts(Mock(), source=source, expected=[("effect", "request")])
    reader.assert_not_called()


@pytest.mark.parametrize("explicit_deadline", [None, "business_deadline_at", "author_deadline_at"])
def test_unsent_transport_window_preserves_explicit_deadlines(explicit_deadline):
    cursor = Mock()
    cursor.fetchone.return_value = (False, False)
    deadline = datetime.now(timezone.utc) - timedelta(hours=2)
    root = {"operation_id": "root", "definition_snapshot": {"timeout_policy": {"operation_timeout_seconds": 3600}},
            "command_payload": {} if explicit_deadline is None else {explicit_deadline: deadline.isoformat()}}
    transport = {"contract_version": "chapter-unsent-context-transport.v1", "target_deployment_id": "pack", "release_sha": "sha"}
    policy = {**transport, "contract_version": "kernel-unsent-transport-window.v1"}
    if explicit_deadline:
        with pytest.raises(KernelError, match="STEP_SUCCESSOR_WINDOW_INVALID"):
            recovery._corrected_contract_window(cursor, root, {}, {}, deadline, policy, transport_policy=transport)
        cursor.execute.assert_not_called()
    else:
        result = recovery._corrected_contract_window(cursor, root, {}, {}, deadline, policy, transport_policy=transport)
        assert result["original_deadline"] == deadline.isoformat()
        assert datetime.fromisoformat(result["new_deadline"]) > datetime.now(timezone.utc)
        assert result["duration_seconds"] == 3600
        assert result["resource_authorization"] == "UNCHANGED"


def test_unsent_transport_window_rejects_release_drift():
    root = {"definition_snapshot": {"timeout_policy": {"operation_timeout_seconds": 3600}}, "command_payload": {}}
    transport = {"contract_version": "chapter-unsent-context-transport.v1", "target_deployment_id": "pack", "release_sha": "sha"}
    with pytest.raises(KernelError, match="STEP_SUCCESSOR_WINDOW_INVALID"):
        recovery._corrected_contract_window(Mock(), root, {}, {}, datetime.now(timezone.utc),
            {**transport, "contract_version": "kernel-unsent-transport-window.v1", "release_sha": "foreign"}, transport_policy=transport)
