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
from novel_forge.modules.command_kernel.service import (
    AdmissionContext,
    admit_command_in_uow,
)
from novel_forge.modules.command_kernel.runtime import (
    OperationTransitionCommand,
    transition_operation_in_uow,
)
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
        active_attempt = uow.repositories.cancellations.active_attempt(
            command.operation_id
        )
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
        uow.cursor.execute(
            "SELECT root_operation_id FROM authority_operation WHERE operation_id = %s AND project_id = %s",
            [command.operation_id, command.project_id],
        )
        root_operation_id = str(uow.cursor.fetchone()[0])
        if root_operation_id == command.operation_id:
            _propagate_root_cancellation(uow, command)
        uow.commit()
    return {
        "cancel_command_id": row["cancel_command_id"],
        "replayed": False,
        **result,
    }


def cancel_unstarted_operation_in_uow(
    uow: AuthorityUnitOfWork,
    *,
    operation_id: str,
    project_id: str,
    actor_id: str,
    trace_id: str,
    correlation_id: str,
    reason: str,
    causation_id: str = "",
) -> dict[str, Any]:
    """Cancel a READY Operation proven to have no Attempt or ExternalEffect."""

    if any(
        not value.strip()
        for value in (
            operation_id,
            project_id,
            actor_id,
            trace_id,
            correlation_id,
            reason,
        )
    ):
        raise KernelError(
            "KERNEL_COMMAND_INVALID",
            "unstarted cancellation identity and reason are required",
        )
    operation = uow.repositories.attempt_runtime.operation_state(
        operation_id, project_id
    )
    if str(operation["status"]) == "CANCELLED":
        return {
            "operation_id": operation_id,
            "status": "CANCELLED",
            "version": int(operation["version"]),
            "replayed": True,
        }
    if str(operation["status"]) != "READY":
        raise KernelError(
            "OPERATION_STATUS_CONFLICT",
            "only an unstarted READY Operation can be cancelled atomically",
        )
    uow.cursor.execute(
        """
        SELECT EXISTS(
                   SELECT 1 FROM authority_attempt WHERE operation_id=%s
               ),
               EXISTS(
                   SELECT 1 FROM authority_external_effect
                   WHERE operation_id=%s AND project_id=%s
               )
        """,
        [operation_id, operation_id, project_id],
    )
    attempt_exists, effect_exists = uow.cursor.fetchone()
    if bool(attempt_exists) or bool(effect_exists):
        raise KernelError(
            "UNSTARTED_CANCELLATION_EVIDENCE_CONFLICT",
            "Operation has Attempt or ExternalEffect evidence and cannot use unstarted cancellation",
        )
    requested = transition_operation_in_uow(
        uow,
        OperationTransitionCommand(
            operation_id=operation_id,
            project_id=project_id,
            expected_version=int(operation["version"]),
            expected_status="READY",
            target_status="CANCELLATION_REQUESTED",
            actor_id=actor_id,
            reason=reason,
            trace_id=trace_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        ),
    )
    cancelled = transition_operation_in_uow(
        uow,
        OperationTransitionCommand(
            operation_id=operation_id,
            project_id=project_id,
            expected_version=int(requested["version"]),
            expected_status="CANCELLATION_REQUESTED",
            target_status="CANCELLED",
            actor_id=actor_id,
            reason=reason,
            trace_id=trace_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        ),
    )
    return {
        "operation_id": operation_id,
        "status": "CANCELLED",
        "version": int(cancelled["version"]),
        "replayed": False,
    }


def _propagate_root_cancellation(
    uow: AuthorityUnitOfWork, command: CancelCommand
) -> None:
    """Cancel unstarted children and signal active children in the root graph."""
    uow.cursor.execute(
        """
        SELECT operation_id, status, version
        FROM authority_operation
        WHERE root_operation_id = %s AND project_id = %s AND operation_id <> %s
          AND status NOT IN ('SUCCEEDED','FAILED_FINAL','CANCELLED','DEAD_LETTER','COMPENSATED')
        ORDER BY created_at
        FOR UPDATE
        """,
        [command.operation_id, command.project_id, command.operation_id],
    )
    for operation_id, status, version in uow.cursor.fetchall():
        if status != "CANCELLATION_REQUESTED":
            result = _cas_operation(
                uow,
                operation_id=operation_id,
                project_id=command.project_id,
                expected_status=status,
                expected_version=int(version),
                target_status="CANCELLATION_REQUESTED",
                actor_id=command.actor_id,
                reason=f"root cancellation: {command.reason}",
                trace_id=command.trace_id,
                correlation_id=command.correlation_id,
                causation_id=command.operation_id,
            )
            version = int(result["version"])
        active_attempt = uow.repositories.cancellations.active_attempt(operation_id)
        if active_attempt is not None:
            uow.repositories.cancellations.signal_worker_cancel(
                str(uuid4()),
                operation_id,
                active_attempt[0],
                active_attempt[1],
                {
                    "actor_id": command.actor_id,
                    "reason": command.reason,
                    "trace_id": command.trace_id,
                },
            )
            continue
        uow.cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM authority_external_effect
                WHERE operation_id = %s AND project_id = %s
                  AND status NOT IN ('CANCELLED','FAILED_FINAL','FAILED_RETRYABLE','SUCCEEDED')
            )
            """,
            [operation_id, command.project_id],
        )
        if not bool(uow.cursor.fetchone()[0]):
            _cas_operation(
                uow,
                operation_id=operation_id,
                project_id=command.project_id,
                expected_status="CANCELLATION_REQUESTED",
                expected_version=int(version),
                target_status="CANCELLED",
                actor_id=command.actor_id,
                reason="cancelled before execution by root command",
                trace_id=command.trace_id,
                correlation_id=command.correlation_id,
                causation_id=command.operation_id,
            )


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
        raise KernelError(
            "CANCELLATION_RESOLUTION_INVALID", "unknown cancel resolution"
        )
    with AuthorityUnitOfWork(database_url) as uow:
        # ExternalEffect planning takes this same Operation row lock and
        # requires EXECUTING.  Locking it before inspecting evidence makes the
        # no-effect proof stable through the terminal CAS: a concurrent plan
        # either committed first and is observed here, or resumes after this
        # transaction and rejects the now-terminal Operation.
        uow.cursor.execute(
            """
            SELECT status,version
            FROM authority_operation
            WHERE operation_id=%s AND project_id=%s
            FOR UPDATE
            """,
            [operation_id, project_id],
        )
        operation = uow.cursor.fetchone()
        if operation is None:
            raise KernelError("OPERATION_NOT_FOUND", "operation does not exist")
        if resolution == "no_external_effect":
            uow.cursor.execute(
                """
                SELECT EXISTS(
                    SELECT 1
                    FROM authority_external_effect
                    WHERE operation_id=%s AND project_id=%s
                )
                """,
                [operation_id, project_id],
            )
            if bool(uow.cursor.fetchone()[0]):
                raise KernelError(
                    "CANCELLATION_NO_EFFECT_EVIDENCE_CONFLICT",
                    "no_external_effect resolution requires zero durable ExternalEffects",
                )
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
                command.worker_id,
                command.fencing_token,
            )
            uow.cursor.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM authority_external_effect
                    WHERE operation_id = %s AND project_id = %s
                      AND status NOT IN ('CANCELLED','FAILED_FINAL','FAILED_RETRYABLE')
                )
                """,
                [attempt["operation_id"], command.project_id],
            )
            external_state_may_exist = bool(uow.cursor.fetchone()[0])
            target_status = (
                "RECONCILIATION_REQUIRED" if external_state_may_exist else "CANCELLED"
            )
            result = _cas_operation(
                uow,
                operation_id=attempt["operation_id"],
                project_id=command.project_id,
                expected_status="CANCELLATION_REQUESTED",
                expected_version=expected_operation_version,
                target_status=target_status,
                actor_id=command.worker_id,
                reason=(
                    "worker acknowledged cancellation; external state requires reconciliation"
                    if external_state_may_exist
                    else "worker acknowledged cancellation before external effect"
                ),
                trace_id=command.trace_id,
                correlation_id=command.correlation_id,
            )
            uow.repositories.attempt_runtime.release(
                command.attempt_id,
                command.worker_id,
                command.fencing_token,
                "cancel_acknowledged",
            )
            uow.repositories.attempt_runtime.assert_lease_consistency(
                command.attempt_id,
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
    compensation_generation: int,
    actor_id: str,
    reason: str,
    trace_id: str,
    correlation_id: str,
    context: AdmissionContext,
) -> dict[str, Any]:
    if compensation_generation <= 0:
        raise KernelError(
            "COMMAND_SCHEMA_INVALID",
            "compensation generation must be positive",
        )
    idempotency_key = (
        f"compensate:{parent_operation_id}:{definition_name}:"
        f"{definition_version}:{compensation_generation}"
    )
    with AuthorityUnitOfWork(database_url) as uow:
        parent = uow.repositories.cancellations.compensation_parent_for_update(
            parent_operation_id,
            project_id,
        )
        command = {
            "definition_name": definition_name,
            "definition_version": definition_version,
            "project_id": project_id,
            "workspace_id": parent["workspace_id"] or f"workspace:{project_id}",
            "actor_id": actor_id,
            "idempotency_scope": "operation:compensation",
            "idempotency_key": idempotency_key,
            "trace_id": trace_id,
            "span_id": str(uuid4()),
            "correlation_id": correlation_id,
            "causation_id": parent_operation_id,
            "parent_operation_id": parent_operation_id,
            "root_operation_id": parent["root_operation_id"] or parent_operation_id,
            "causation_operation_id": parent_operation_id,
            "input": {
                "parent_operation_id": parent_operation_id,
                "compensation_generation": compensation_generation,
                "reason": reason,
            },
            "input_assets": [],
            "metadata": {
                "operation_role": "compensation",
                "parent_operation_id": parent_operation_id,
                "compensation_generation": compensation_generation,
            },
        }
        admitted = admit_command_in_uow(uow, command, context=context)
        uow.repositories.cancellations.require_compensation_child(
            admitted["operation_id"],
            parent_operation_id,
            project_id,
        )
        if admitted["replayed"]:
            uow.commit()
            return admitted
        if parent["version"] != expected_parent_version:
            raise KernelError(
                "OPERATION_VERSION_CONFLICT",
                f"expected version {expected_parent_version}, current version {parent['version']}",
            )
        if parent["status"] != "COMPENSATION_REQUIRED":
            raise KernelError(
                "OPERATION_STATUS_CONFLICT",
                f"expected COMPENSATION_REQUIRED, current status {parent['status']}",
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
            causation_id=admitted["operation_id"],
        )
        uow.commit()
    return admitted


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
        if state["parent_status"] == target:
            return {
                "status": target,
                "version": state["parent_version"],
                "replayed": True,
            }
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
    return {**result, "replayed": False}


def _validate_cancel(command: CancelCommand) -> None:
    if command.command_version != 1 or command.expected_version < 0:
        raise KernelError(
            "CANCEL_COMMAND_INVALID", "unsupported cancel command version"
        )
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
