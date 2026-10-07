from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.operation_graph import GraphCommandContext, transition_saga_gate_in_uow


def owner(status="RUNNING"):
    repository = Mock()
    repository.saga_for_update.return_value = {"status": status, "version": 4, "root_operation_id": "root"}
    repository.acquire_coordinator.return_value = {"fencing_token": 9}
    uow = SimpleNamespace(repositories=SimpleNamespace(operation_graph=repository), commit=Mock())
    return uow, repository, GraphCommandContext("project", "actor", "trace", "correlation")


def test_domain_uow_owns_root_and_saga_commit_and_kernel_owns_fence_and_event():
    uow, repository, context = owner()
    result = transition_saga_gate_in_uow(uow, context, "saga", target_status="WAITING_GATE", reason="Exact technical admission failed")
    assert result == {"status": "WAITING_GATE", "version": 5, "replayed": False}
    uow.commit.assert_not_called()
    repository.update_saga.assert_called_once_with("saga", 4, "WAITING_GATE")
    repository.release_coordinator.assert_called_once_with("saga", "actor", 9)
    event = repository.record_event.call_args.args[0]
    assert event["payload"]["coordinator_fencing_token"] == 9


@pytest.mark.parametrize("status", ["SUCCEEDED", "CANCELLED", "FAILED_FINAL"])
def test_terminal_saga_cannot_be_revived_as_a_technical_wait(status):
    uow, repository, context = owner(status)
    with pytest.raises(KernelError, match="SAGA_STATUS_CONFLICT"):
        transition_saga_gate_in_uow(uow, context, "saga", target_status="WAITING_GATE", reason="Attempted revival")
    repository.acquire_coordinator.assert_not_called()
    uow.commit.assert_not_called()


def test_failed_saga_compare_and_set_cannot_commit_the_callers_root_transition():
    uow, repository, context = owner()
    repository.update_saga.side_effect = KernelError("SAGA_VERSION_CONFLICT", "The owner fence changed")
    with pytest.raises(KernelError, match="SAGA_VERSION_CONFLICT"):
        transition_saga_gate_in_uow(uow, context, "saga", target_status="WAITING_GATE", reason="Exact technical admission failed")
    uow.commit.assert_not_called()
    repository.record_event.assert_not_called()
