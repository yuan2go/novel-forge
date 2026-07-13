from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any
from uuid import uuid4

from novel_forge.modules.command_kernel.attempt_runtime import (
    WorkerLeaseCommand,
    _cas_operation,
    _reject_stale,
    _transition_attempt,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


@dataclass(frozen=True)
class CancelCommand:
    operation_id: str
    project_id: str
    actor_id: str
    reason: str
    expected_version: int
    idempotency_key: str
    trace_id: str
    correlation_id: str
    causation_id: str = ""
    command_version: int = 1


def request_cancellation(database_url: str, command: CancelCommand) -> dict[str, Any]:
    _validate_cancel(command)
    digest = _cancel_digest(command)
    row = {
        **asdict(command),
        "cancel_command_id": str(uuid4()),
        "expected_operation_version": command.expected_version,
        "request_digest": digest,
    }
    with AuthorityUnitOfWork(database_url) as uow:
        operation = uow.repositories.attempt_runtime.operation_state(
            command.operation_id,
            command.project_id,
        )
        created = uow.repositories.cancellations.try_record(row)
        if not created:
            existing_id, existing_digest = uow.repositories.cancellations.existing(
                command.operation_id,
                command.idempotency_key,
            )
            if existing_digest != digest:
                raise KernelError(
                    "IDEMPOTENCY_CONFLICT",
                    "cancel idempotency key belongs to another request",
                )
            return {"cancel_command_id": existing_id, "replayed": True}
        if operation["version"] != command.expected_version:
            raise KernelError(
                "OPERATION_VERSION_CONFLICT",
                (
                    f"expected version {command.expected_version}, "
                    f"current version {operation['version']}"
                ),
            )
        cancelable_statuses = {
            "READY",
            "EXECUTING",
            "WAITING_CHILDREN",
            "WAITING_EXTERNAL_RESULT",
            "WAITING_GATE",
            "FAILED_RETRYABLE",
        }
        if operation["status"] not in cancelable_statuses:
            raise KernelError(
                "OPERATION_STATUS_CONFLICT",
                f"operation cannot be cancelled from {operation['status']}",
            )
        result = _cas_operation(
            uow,
            operation_id=command.operation_id,
            project_id=command.project_id,
            expected_status=operation["status"],
            expected_version=command.expected_version,
            target_status="CANCELLATION_REQUESTED",
            actor_id=command.actor_id,
            reason=command.reason,
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
            causation_id=command.causation_id,
        )
        active_attempt = uow.repositories.cancellations.active_attempt(command.operation_id)
        if active_attempt is not None:
            uow.repositories.cancellations.signal_worker_cancel(
                str(uuid4()),
                command.operation_id,
                active_attempt[0],
                active_attempt[1],
                {
                    "actor_id": command.actor_id,
                    "reason": command.reason,
                    "trace_id": command.trace_id,
                },
            )
        uow.commit()
    return {
        "cancel_command_id": row["cancel_command_id"],
        "replayed": False,
        **result,
    }


def resolve_cancellation(
    database_url: str,
    *,
    operation_id: str,
    project_id: str,
    expected_version: int,
    resolution: str,
    actor_id: str,
    reason: str,
    trace_id: str,
    correlation_id: str,
) -> dict[str, Any]:
    target = {
        "no_external_effect": "CANCELLED",
        "external_state_unknown": "RECONCILIATION_REQUIRED",
        "compensation_required": "COMPENSATION_REQUIRED",
    }.get(resolution)
    if target is None:
        raise KernelError("CANCELLATION_RESOLUTION_INVALID", "unknown cancel resolution")
    with AuthorityUnitOfWork(database_url) as uow:
        result = _cas_operation(
            uow,
            operation_id=operation_id,
            project_id=project_id,
            expected_status="CANCELLATION_REQUESTED",
            expected_version=expected_version,
            target_status=target,
            actor_id=actor_id,
            reason=reason,
            trace_id=trace_id,
            correlation_id=correlation_id,
        )
        uow.commit()
    return result


def acknowledge_worker_cancellation(
    database_url: str,
    command: WorkerLeaseCommand,
    *,
    expected_operation_version: int,
) -> dict[str, Any]:
    stale_error: KernelError | None = None
    result: dict[str, Any] = {}
    with AuthorityUnitOfWork(database_url) as uow:
        attempt = uow.repositories.attempt_runtime.get_for_update(
            command.attempt_id,
            command.project_id,
        )
        valid, current_token = uow.repositories.attempt_runtime.current_fence(
            command.attempt_id,
            command.worker_id,
            command.fencing_token,
        )
        if not valid:
            _reject_stale(
                uow,
                command,
                attempt,
                current_token,
                "cancel_acknowledgement",
                {},
            )
            stale_error = KernelError(
                "ATTEMPT_FENCING_TOKEN_STALE",
                "cancel acknowledgement carries a stale fencing token",
            )
        else:
            _transition_attempt(
                uow,
                attempt,
                "CANCELLED",
                worker_id=command.worker_id,
                fencing_token=command.fencing_token,
                trace_id=command.trace_id,
                correlation_id=command.correlation_id,
            )
            uow.repositories.cancellations.acknowledge_worker_cancel(
                command.attempt_id,
                command.fencing_token,
            )
            result = _cas_operation(
                uow,
                operation_id=attempt["operation_id"],
                project_id=command.project_id,
                expected_status="CANCELLATION_REQUESTED",
                expected_version=expected_operation_version,
                target_status="CANCELLED",
                actor_id=command.worker_id,
                reason="worker acknowledged cancellation before external effect",
                trace_id=command.trace_id,
                correlation_id=command.correlation_id,
            )
            uow.repositories.attempt_runtime.release(
                command.attempt_id,
                command.worker_id,
                command.fencing_token,
                "cancel_acknowledged",
            )
        uow.commit()
    if stale_error is not None:
        raise stale_error
    return result


def create_compensation_child(
    database_url: str,
    *,
    parent_operation_id: str,
    project_id: str,
    expected_parent_version: int,
    definition_name: str,
    definition_version: str,
    actor_id: str,
    reason: str,
    trace_id: str,
    correlation_id: str,
) -> str:
    child_operation_id = str(uuid4())
    idempotency_key = f"compensate:{parent_operation_id}:{expected_parent_version}"
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    with AuthorityUnitOfWork(database_url) as uow:
        uow.repositories.attempt_runtime.operation_state(parent_operation_id, project_id)
        uow.repositories.cancellations.create_compensation_child(
            {
                "child_operation_id": child_operation_id,
                "parent_operation_id": parent_operation_id,
                "project_id": project_id,
                "definition_name": definition_name,
                "definition_version": definition_version,
                "idempotency_scope": "operation:compensation",
                "idempotency_key": idempotency_key,
                "request_digest": digest,
                "actor_id": actor_id,
                "concurrency_key": f"operation:{parent_operation_id}:compensation",
                "trace_id": trace_id,
                "span_id": str(uuid4()),
                "correlation_id": correlation_id,
                "causation_id": parent_operation_id,
                "command_payload": {
                    "parent_operation_id": parent_operation_id,
                    "reason": reason,
                },
                "metadata": {
                    "operation_role": "compensation",
                    "parent_operation_id": parent_operation_id,
                },
            }
        )
        uow.repositories.runtime_evidence.record_operation_transition(
            {
                "operation_id": child_operation_id,
                "project_id": project_id,
                "expected_status": "NONE",
                "target_status": "ADMITTED",
                "version": 0,
                "actor_id": actor_id,
                "reason": reason,
                "trace_id": trace_id,
                "correlation_id": correlation_id,
                "causation_id": parent_operation_id,
                "event_id": str(uuid4()),
                "audit_id": str(uuid4()),
                "outbox_id": str(uuid4()),
            }
        )
        _cas_operation(
            uow,
            operation_id=parent_operation_id,
            project_id=project_id,
            expected_status="COMPENSATION_REQUIRED",
            expected_version=expected_parent_version,
            target_status="COMPENSATING",
            actor_id=actor_id,
            reason="compensation child admitted",
            trace_id=trace_id,
            correlation_id=correlation_id,
            causation_id=child_operation_id,
        )
        uow.commit()
    return child_operation_id


def complete_compensation_from_child(
    database_url: str,
    *,
    child_operation_id: str,
    project_id: str,
    actor_id: str,
    trace_id: str,
    correlation_id: str,
) -> dict[str, Any]:
    with AuthorityUnitOfWork(database_url) as uow:
        state = uow.repositories.cancellations.compensation_parent(
            child_operation_id,
            project_id,
        )
        target = {
            "SUCCEEDED": "COMPENSATED",
            "FAILED_FINAL": "COMPENSATION_FAILED",
            "DEAD_LETTER": "COMPENSATION_FAILED",
        }.get(state["child_status"])
        if target is None:
            raise KernelError(
                "COMPENSATION_CHILD_NOT_TERMINAL",
                "compensation child has no accepted terminal outcome",
            )
        result = _cas_operation(
            uow,
            operation_id=state["parent_operation_id"],
            project_id=project_id,
            expected_status="COMPENSATING",
            expected_version=state["parent_version"],
            target_status=target,
            actor_id=actor_id,
            reason=f"compensation child completed as {state['child_status']}",
            trace_id=trace_id,
            correlation_id=correlation_id,
            causation_id=child_operation_id,
        )
        uow.commit()
    return result


def _validate_cancel(command: CancelCommand) -> None:
    if command.command_version != 1 or command.expected_version < 0:
        raise KernelError("CANCEL_COMMAND_INVALID", "unsupported cancel command version")
    required = (
        command.operation_id,
        command.project_id,
        command.actor_id,
        command.reason,
        command.idempotency_key,
        command.trace_id,
        command.correlation_id,
    )
    if any(not value for value in required):
        raise KernelError("CANCEL_COMMAND_INVALID", "cancel command is incomplete")


def _cancel_digest(command: CancelCommand) -> str:
    payload = {
        "operation_id": command.operation_id,
        "project_id": command.project_id,
        "actor_id": command.actor_id,
        "reason": command.reason,
        "expected_version": command.expected_version,
        "command_version": command.command_version,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
