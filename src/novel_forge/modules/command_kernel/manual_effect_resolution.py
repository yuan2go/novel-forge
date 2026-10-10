from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.attempt_runtime import _cas_operation
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


DECISIONS = frozenset(
    {
        "MARK_SUCCEEDED",
        "MARK_NOT_FOUND",
        "MARK_FAILED_FINAL",
        "MARK_CANCELLED",
        "RETRY_WITH_NEW_GENERATION",
        "ISOLATE_PURE_GENERATION",
    }
)


@dataclass(frozen=True, slots=True)
class ExternalEffectManualResolutionCommand:
    external_effect_id: str
    operation_id: str
    project_id: str
    actor_id: str
    decision: str
    reason: str
    evidence: dict[str, Any]
    idempotency_key: str
    expected_operation_version: int
    trace_id: str
    correlation_id: str


def resolve_external_effect_manually(
    database_url: str,
    command: ExternalEffectManualResolutionCommand,
) -> dict[str, Any]:
    _validate(command)
    digest = hashlib.sha256(
        json.dumps(asdict(command), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    with AuthorityUnitOfWork(database_url) as uow:
        effect = uow.repositories.external_effects.get_for_update(command.external_effect_id)
        if effect["project_id"] != command.project_id or effect["operation_id"] != command.operation_id:
            raise KernelError("CROSS_PROJECT_REFERENCE", "manual effect resolution scope differs")
        uow.cursor.execute(
            """
            SELECT manual_resolution_id, request_digest, decision
            FROM authority_effect_manual_resolution
            WHERE project_id=%s AND external_effect_id=%s AND idempotency_key=%s
            """,
            [command.project_id, command.external_effect_id, command.idempotency_key],
        )
        replay = uow.cursor.fetchone()
        if replay is not None:
            if replay[1] != digest and not _same_isolation_replay(uow.cursor, command):
                raise KernelError("MANUAL_RESOLUTION_IDEMPOTENCY_CONFLICT", "manual resolution replay differs")
            return {"manual_resolution_id": str(replay[0]), "decision": str(replay[2]), "replayed": True}
        operation = uow.repositories.attempt_runtime.operation_state(
            command.operation_id, command.project_id
        )
        if int(operation["version"]) != command.expected_operation_version:
            raise KernelError("OPERATION_VERSION_CONFLICT", "manual resolution expected version is stale")
        from .cli_effect_reconciliation import historical_cli_dispatch, append_resolution
        original = historical_cli_dispatch(uow.cursor, effect)
        original_reconciled = original is not None
        if command.decision == "ISOLATE_PURE_GENERATION":
            from .generation_isolation import append_isolation
            append_isolation(uow, effect, command)
            target_operation = str(uow.repositories.attempt_runtime.operation_state(command.operation_id, command.project_id)["status"])
        elif _isolated_api(uow.cursor, effect):
            from .isolated_api_reconciliation import append_resolution as append_api_resolution
            append_api_resolution(uow, effect, command)
            target_operation = str(operation["status"])
        elif original_reconciled:
            append_resolution(uow, effect, original, command)
            target_operation = str(operation["status"])
        else:
            if effect["status"] not in {"UNKNOWN", "RECONCILIATION_REQUIRED"}:
                raise KernelError("EFFECT_STATUS_CONFLICT", "effect is not awaiting manual resolution")
            target_effect, target_operation = {
                "MARK_SUCCEEDED": ("SUCCEEDED", "EXECUTING"),
                "MARK_NOT_FOUND": ("FAILED_RETRYABLE", "FAILED_RETRYABLE"),
                "MARK_FAILED_FINAL": ("FAILED_FINAL", "FAILED_FINAL"),
                "MARK_CANCELLED": ("CANCELLED", "CANCELLED"),
                "RETRY_WITH_NEW_GENERATION": ("FAILED_RETRYABLE", "FAILED_RETRYABLE"),
            }[command.decision]
            if command.decision == "RETRY_WITH_NEW_GENERATION" and not command.evidence.get(
                "provider_not_executed"
            ):
                raise KernelError(
                    "MANUAL_RETRY_EVIDENCE_REQUIRED",
                    "new generation requires evidence that the Provider did not execute",
                )
            uow.cursor.execute(
                """
                SELECT dispatch.status
                FROM authority_external_receipt AS receipt
                JOIN authority_external_effect_dispatch AS dispatch
                  ON dispatch.dispatch_id = receipt.dispatch_id
                WHERE dispatch.external_effect_id=%s
                ORDER BY receipt.received_at DESC LIMIT 1
                """,
                [command.external_effect_id],
            )
            receipt = uow.cursor.fetchone()
            if receipt is not None and (
                (receipt[0] == "SUCCEEDED" and target_effect != "SUCCEEDED")
                or (receipt[0] != "SUCCEEDED" and target_effect == "SUCCEEDED")
            ):
                raise KernelError("MANUAL_RESOLUTION_RECEIPT_CONFLICT", "manual decision conflicts with an accepted receipt")
            uow.cursor.execute(
                "UPDATE authority_external_effect SET status=%s, reconciliation=%s WHERE external_effect_id=%s",
                [target_effect, Jsonb(command.evidence), command.external_effect_id],
            )
            current_status = str(operation["status"])
            if current_status != target_operation:
                _cas_operation(
                    uow,
                    operation_id=command.operation_id,
                    project_id=command.project_id,
                    expected_status=current_status,
                    expected_version=command.expected_operation_version,
                    target_status=target_operation,
                    actor_id=command.actor_id,
                    reason=command.reason,
                    trace_id=command.trace_id,
                    correlation_id=command.correlation_id,
                    causation_id=command.external_effect_id,
                )
        resolution_id = str(uuid4())
        uow.cursor.execute(
            """
            INSERT INTO authority_effect_manual_resolution (
                manual_resolution_id,external_effect_id,operation_id,project_id,
                actor_id,decision,reason,evidence,idempotency_key,request_digest,
                trace_id,correlation_id
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            [
                resolution_id, command.external_effect_id, command.operation_id,
                command.project_id, command.actor_id, command.decision, command.reason,
                Jsonb(command.evidence), command.idempotency_key, digest,
                command.trace_id, command.correlation_id,
            ],
        )
        _record(uow, command, resolution_id, target_operation)
        uow.commit()
    return {
        "manual_resolution_id": resolution_id,
        "decision": command.decision,
        "operation_status": target_operation,
        "replayed": False,
        "successor_required": original_reconciled and target_operation in {"FAILED_FINAL", "DEAD_LETTER", "CANCELLED"},
    }


def _record(uow: AuthorityUnitOfWork, command: ExternalEffectManualResolutionCommand, resolution_id: str, operation_status: str) -> None:
    event_id = str(uuid4())
    payload = {
        "manual_resolution_id": resolution_id,
        "external_effect_id": command.external_effect_id,
        "decision": command.decision,
        "operation_status": operation_status,
        "reason": command.reason,
        "trace_id": command.trace_id,
    }
    uow.cursor.execute(
        "SELECT COALESCE(MAX(sequence_number),0)+1 FROM state_event WHERE aggregate_type='authority_external_effect' AND aggregate_id=%s",
        [command.external_effect_id],
    )
    sequence = int(uow.cursor.fetchone()[0])
    uow.cursor.execute(
        """
        INSERT INTO state_event (event_id,project_id,aggregate_type,aggregate_id,event_type,event_version,sequence_number,payload,correlation_id,causation_id)
        VALUES (%s,%s,'authority_external_effect',%s,'external_effect.manually_resolved',1,%s,%s,%s,%s)
        """,
        [event_id, command.project_id, command.external_effect_id, sequence, Jsonb(payload), command.correlation_id, command.operation_id],
    )
    uow.cursor.execute(
        "INSERT INTO audit_log (audit_id,project_id,operation_id,action,payload) VALUES (%s,%s,%s,'external_effect.manually_resolved',%s)",
        [str(uuid4()), command.project_id, command.operation_id, Jsonb(payload)],
    )
    uow.cursor.execute(
        "INSERT INTO outbox_event (outbox_id,event_id,project_id,topic,status,payload) VALUES (%s,%s,%s,'external_effect.manually_resolved','pending',%s)",
        [str(uuid4()), event_id, command.project_id, Jsonb(payload)],
    )


def _validate(command: ExternalEffectManualResolutionCommand) -> None:
    if command.decision not in DECISIONS or command.expected_operation_version < 0:
        raise KernelError("MANUAL_RESOLUTION_COMMAND_INVALID", "manual effect resolution is invalid")
    if any(
        not item
        for item in (
            command.external_effect_id, command.operation_id, command.project_id,
            command.actor_id, command.reason, command.idempotency_key,
            command.trace_id, command.correlation_id,
        )
    ) or not command.evidence:
        raise KernelError("MANUAL_RESOLUTION_COMMAND_INVALID", "manual effect resolution is incomplete")


__all__ = ["ExternalEffectManualResolutionCommand", "resolve_external_effect_manually"]


def _same_isolation_replay(cursor, command):
    if command.decision != "ISOLATE_PURE_GENERATION":
        return False
    cursor.execute("""SELECT operation_id,actor_id,decision,reason,evidence,trace_id,correlation_id
        FROM authority_effect_manual_resolution WHERE project_id=%s AND external_effect_id=%s AND idempotency_key=%s""",
        [command.project_id, command.external_effect_id, command.idempotency_key])
    return cursor.fetchone() == (command.operation_id, command.actor_id, command.decision, command.reason,
        command.evidence, command.trace_id, command.correlation_id)


def _isolated_api(cursor, effect):
    from .generation_isolation import isolation
    proof = isolation(cursor, effect["external_effect_id"])
    return proof and proof.get("execution_transport") == "REMOTE_PROVIDER_API"
