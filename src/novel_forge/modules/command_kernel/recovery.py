from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.attempt_runtime import _cas_operation
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


@dataclass(frozen=True, slots=True)
class RecoverOperationCommand:
    operation_id: str
    project_id: str
    actor_id: str
    expected_version: int
    idempotency_key: str
    reason: str
    trace_id: str
    correlation_id: str
    gate_evidence_id: str = ""


def recover_operation(
    database_url: str, command: RecoverOperationCommand
) -> dict[str, object]:
    _validate(command)
    digest = hashlib.sha256(
        json.dumps(asdict(command), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """
            SELECT status, version, definition_name
            FROM authority_operation
            WHERE operation_id = %s AND project_id = %s
            FOR UPDATE
            """,
            [command.operation_id, command.project_id],
        )
        operation_row = uow.cursor.fetchone()
        if operation_row is None:
            raise KernelError(
                "OPERATION_NOT_FOUND", "operation does not exist in the project"
            )
        uow.cursor.execute(
            """
            SELECT recovery_command_id, request_digest, recovery_action
            FROM authority_recovery_command
            WHERE project_id = %s AND operation_id = %s AND idempotency_key = %s
            """,
            [command.project_id, command.operation_id, command.idempotency_key],
        )
        existing = uow.cursor.fetchone()
        if existing is not None:
            if existing[1] != digest:
                raise KernelError(
                    "RECOVERY_IDEMPOTENCY_CONFLICT",
                    "recovery idempotency key belongs to another command",
                )
            return {
                "recovery_command_id": str(existing[0]),
                "operation_id": command.operation_id,
                "action": str(existing[2]),
                "replayed": True,
            }
        operation_status, operation_version, definition_name = operation_row
        if int(operation_version) != command.expected_version:
            raise KernelError("OPERATION_VERSION_CONFLICT", "recovery expected version is stale")
        status = str(operation_status)
        if status == "FAILED_RETRYABLE":
            action = "READY_FOR_RETRY"
            _cas_operation(
                uow,
                operation_id=command.operation_id,
                project_id=command.project_id,
                expected_status=status,
                expected_version=command.expected_version,
                target_status="READY",
                actor_id=command.actor_id,
                reason=command.reason,
                trace_id=command.trace_id,
                correlation_id=command.correlation_id,
            )
        elif status == "EXECUTING":
            uow.cursor.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM authority_attempt AS attempt
                    JOIN authority_lease_acquisition AS lease
                      ON lease.attempt_id = attempt.attempt_id
                    WHERE attempt.operation_id = %s AND lease.status = 'HELD'
                      AND lease.expires_at > NOW()
                )
                """,
                [command.operation_id],
            )
            if bool(uow.cursor.fetchone()[0]):
                raise KernelError("RECOVERY_LEASE_ACTIVE", "active Attempt lease cannot be taken over")
            action = "LEASE_TAKEOVER_VISIBLE"
        elif status in {"WAITING_EXTERNAL_RESULT", "RECONCILIATION_REQUIRED"}:
            uow.cursor.execute("""SELECT checkpoint->>'error_code' FROM authority_attempt
                WHERE operation_id=%s AND status='CHECKPOINTED' ORDER BY attempt_number DESC LIMIT 1""", [command.operation_id])
            checkpoint = uow.cursor.fetchone()
            uow.cursor.execute("SELECT count(*) FROM authority_external_effect WHERE operation_id=%s", [command.operation_id])
            no_effect = int(uow.cursor.fetchone()[0]) == 0
            if checkpoint and checkpoint[0] in {"TASK_CONTEXT_MODEL_OUTPUT_CAPACITY_UNKNOWN", "TASK_CONTEXT_MODEL_CAPACITY_UNKNOWN"} and no_effect:
                action = "PRE_SEND_CHECKPOINT_RECONCILED"
                _cas_operation(uow, operation_id=command.operation_id, project_id=command.project_id,
                    expected_status=status, expected_version=command.expected_version, target_status="EXECUTING",
                    actor_id=command.actor_id, reason=command.reason, trace_id=command.trace_id, correlation_id=command.correlation_id)
            else:
                action = "RECONCILIATION_DISPATCHED"
            if status == "WAITING_EXTERNAL_RESULT" and action == "RECONCILIATION_DISPATCHED":
                _cas_operation(
                    uow,
                    operation_id=command.operation_id,
                    project_id=command.project_id,
                    expected_status=status,
                    expected_version=command.expected_version,
                    target_status="RECONCILIATION_REQUIRED",
                    actor_id=command.actor_id,
                    reason=command.reason,
                    trace_id=command.trace_id,
                    correlation_id=command.correlation_id,
                )
        elif status in {"WAITING_GATE", "WAITING_APPROVAL"}:
            if not command.gate_evidence_id:
                raise KernelError("RECOVERY_GATE_EVIDENCE_REQUIRED", "gate recovery needs evidence")
            uow.cursor.execute(
                """
                SELECT asset.asset_type, version.lifecycle, version.eligibility,
                       operation.definition_name
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id = version.asset_id
                JOIN authority_operation AS operation ON operation.operation_id = %s
                WHERE version.asset_version_id = %s
                  AND asset.project_id = %s AND operation.project_id = %s
                """,
                [
                    command.operation_id, command.gate_evidence_id,
                    command.project_id, command.project_id,
                ],
            )
            gate = uow.cursor.fetchone()
            if gate is None or gate[1:3] != ("ACTIVE", "ELIGIBLE"):
                raise KernelError("RECOVERY_GATE_EVIDENCE_INVALID", "gate evidence is not current and eligible")
            target_status = "EXECUTING"
            if definition_name == "chapter.slice.run":
                uow.cursor.execute(
                    "SELECT COUNT(*) FROM authority_canon_approval_request WHERE root_operation_id = %s AND status NOT IN ('APPROVED','REJECTED','EDITED_AND_APPROVED')",
                    [command.operation_id],
                )
                if int(uow.cursor.fetchone()[0]):
                    raise KernelError("CANON_APPROVAL_INCOMPLETE", "Canon gate cannot be bypassed by generic recovery")
                if gate[0] != "canon_approval_decision":
                    raise KernelError("RECOVERY_GATE_EVIDENCE_INVALID", "Canon recovery requires a decision AssetVersion")
                target_status = "WAITING_CHILDREN"
            action = "GATE_RESUMED"
            _cas_operation(
                uow,
                operation_id=command.operation_id,
                project_id=command.project_id,
                expected_status=status,
                expected_version=command.expected_version,
                target_status=target_status,
                actor_id=command.actor_id,
                reason=command.reason,
                trace_id=command.trace_id,
                correlation_id=command.correlation_id,
                causation_id=command.gate_evidence_id,
            )
        elif status == "SUCCEEDED":
            action = "ALREADY_COMPLETE"
        else:
            raise KernelError(
                "OPERATION_NOT_RECOVERABLE",
                f"operation cannot recover from {status}; create a new generation",
            )
        command_id = str(uuid4())
        uow.cursor.execute(
            """
            INSERT INTO authority_recovery_command (
                recovery_command_id, operation_id, project_id, actor_id,
                idempotency_key, request_digest, expected_version, reason,
                recovery_action, trace_id, correlation_id
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            [
                command_id, command.operation_id, command.project_id, command.actor_id,
                command.idempotency_key, digest, command.expected_version, command.reason,
                action, command.trace_id, command.correlation_id,
            ],
        )
        _record(uow, command, command_id, action)
        uow.commit()
    return {
        "recovery_command_id": command_id,
        "operation_id": command.operation_id,
        "action": action,
        "replayed": False,
    }


def _record(
    uow: AuthorityUnitOfWork,
    command: RecoverOperationCommand,
    command_id: str,
    action: str,
) -> None:
    event_id = str(uuid4())
    payload = {
        "recovery_command_id": command_id,
        "operation_id": command.operation_id,
        "action": action,
        "reason": command.reason,
        "trace_id": command.trace_id,
    }
    uow.cursor.execute(
        "SELECT COALESCE(MAX(sequence_number),0)+1 FROM state_event WHERE aggregate_type='authority_operation' AND aggregate_id=%s",
        [command.operation_id],
    )
    sequence = int(uow.cursor.fetchone()[0])
    uow.cursor.execute(
        """
        INSERT INTO state_event (
            event_id, project_id, aggregate_type, aggregate_id, event_type,
            event_version, sequence_number, payload, correlation_id, causation_id
        ) VALUES (%s,%s,'authority_operation',%s,'authority.operation.recovery_requested',1,%s,%s,%s,%s)
        """,
        [event_id, command.project_id, command.operation_id, sequence, Jsonb(payload), command.correlation_id, command.gate_evidence_id],
    )
    uow.cursor.execute(
        "INSERT INTO audit_log (audit_id,project_id,operation_id,action,payload) VALUES (%s,%s,%s,'authority.operation.recovery_requested',%s)",
        [str(uuid4()), command.project_id, command.operation_id, Jsonb(payload)],
    )
    uow.cursor.execute(
        "INSERT INTO outbox_event (outbox_id,event_id,project_id,topic,status,payload) VALUES (%s,%s,%s,'authority.operation.recovery_requested','pending',%s)",
        [str(uuid4()), event_id, command.project_id, Jsonb(payload)],
    )


def _validate(command: RecoverOperationCommand) -> None:
    if command.expected_version < 0 or any(
        not value
        for value in (
            command.operation_id,
            command.project_id,
            command.actor_id,
            command.idempotency_key,
            command.reason,
            command.trace_id,
            command.correlation_id,
        )
    ):
        raise KernelError("RECOVERY_COMMAND_INVALID", "recovery command is incomplete")


__all__ = ["RecoverOperationCommand", "recover_operation"]
