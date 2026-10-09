from unittest.mock import Mock

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
