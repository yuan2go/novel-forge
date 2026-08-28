from __future__ import annotations

from dataclasses import asdict, dataclass
from uuid import uuid4

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.lifecycle import require_operation_transition
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


@dataclass(frozen=True)
class OperationTransitionCommand:
    operation_id: str
    project_id: str
    expected_version: int
    expected_status: str
    target_status: str
    actor_id: str
    reason: str
    trace_id: str
    correlation_id: str
    causation_id: str


def transition_operation(
    database_url: str,
    command: OperationTransitionCommand,
) -> dict[str, int | str]:
    with AuthorityUnitOfWork(database_url) as uow:
        result = transition_operation_in_uow(uow, command)
        uow.commit()
    return result


def transition_operation_in_uow(
    uow: AuthorityUnitOfWork,
    command: OperationTransitionCommand,
) -> dict[str, int | str]:
    """Apply one governed Operation CAS inside an owning Authority UoW."""

    _validate_transition_command(command)
    require_operation_transition(command.expected_status, command.target_status)
    row = asdict(command)
    result = uow.repositories.operation_lifecycle.compare_and_set(row)
    uow.repositories.runtime_evidence.record_operation_transition(
        {
            **row,
            "version": result["version"],
            "event_id": str(uuid4()),
            "audit_id": str(uuid4()),
            "outbox_id": str(uuid4()),
        }
    )
    return result


def _validate_transition_command(command: OperationTransitionCommand) -> None:
    required = {
        "operation_id": command.operation_id,
        "project_id": command.project_id,
        "expected_status": command.expected_status,
        "target_status": command.target_status,
        "actor_id": command.actor_id,
        "reason": command.reason,
        "trace_id": command.trace_id,
        "correlation_id": command.correlation_id,
    }
    missing = [name for name, value in required.items() if not value]
    if missing or command.expected_version < 0:
        raise KernelError(
            "KERNEL_COMMAND_INVALID",
            f"invalid operation transition command: {', '.join(missing)}",
        )
