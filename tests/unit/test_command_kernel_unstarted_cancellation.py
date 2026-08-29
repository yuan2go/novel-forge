from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from novel_forge.modules.command_kernel.cancellation import (
    cancel_unstarted_operation_in_uow,
)


class _OperationStateRepository:
    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state

    def operation_state(self, operation_id: str, project_id: str) -> dict[str, Any]:
        assert operation_id == self.state["operation_id"]
        assert project_id == self.state["project_id"]
        return dict(self.state)


class _OperationLifecycleRepository:
    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state
        self.targets: list[str] = []

    def compare_and_set(self, command: dict[str, Any]) -> dict[str, Any]:
        assert command["expected_status"] == self.state["status"]
        assert command["expected_version"] == self.state["version"]
        self.state["status"] = command["target_status"]
        self.state["version"] += 1
        self.targets.append(command["target_status"])
        return {
            "operation_id": self.state["operation_id"],
            "status": self.state["status"],
            "version": self.state["version"],
        }


class _RuntimeEvidenceRepository:
    def record_operation_transition(self, _event: dict[str, Any]) -> None:
        return None


class _Cursor:
    def execute(self, sql: str, _parameters: list[str]) -> None:
        assert "authority_attempt" in sql
        assert "authority_external_effect" in sql

    def fetchone(self) -> tuple[bool, bool]:
        return False, False


class _UnitOfWork:
    def __init__(self, status: str) -> None:
        state = {
            "operation_id": "operation:replacement",
            "project_id": "project:test",
            "status": status,
            "version": 0,
        }
        lifecycle = _OperationLifecycleRepository(state)
        self.repositories = SimpleNamespace(
            attempt_runtime=_OperationStateRepository(state),
            operation_lifecycle=lifecycle,
            runtime_evidence=_RuntimeEvidenceRepository(),
        )
        self.cursor = _Cursor()
        self.lifecycle = lifecycle


@pytest.mark.parametrize("initial_status", ("ADMITTED", "READY"))
def test_unstarted_cancellation_accepts_both_pre_execution_states(
    initial_status: str,
) -> None:
    uow = _UnitOfWork(initial_status)

    result = cancel_unstarted_operation_in_uow(
        uow,  # type: ignore[arg-type]
        operation_id="operation:replacement",
        project_id="project:test",
        actor_id="book-opening-authority",
        trace_id="trace:test",
        correlation_id="correlation:test",
        reason="outer execution was aborted before semantic work started",
    )

    assert result == {
        "operation_id": "operation:replacement",
        "status": "CANCELLED",
        "version": 2,
        "replayed": False,
    }
    assert uow.lifecycle.targets == ["CANCELLATION_REQUESTED", "CANCELLED"]
