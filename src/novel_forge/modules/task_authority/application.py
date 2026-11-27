from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


@dataclass(frozen=True, slots=True)
class OutboxRecoveryCommand:
    outbox_id: str
    project_id: str
    actor_id: str
    expected_attempt_count: int
    idempotency_key: str
    reason: str
    trace_id: str
    correlation_id: str


def requeue_outbox_dead_letter(
    database_url: str,
    command: OutboxRecoveryCommand,
    *,
    principal: Principal | None = None,
) -> dict[str, object]:
    _validate(command)
    actor_id = command.actor_id
    if principal is not None:
        principal.require("task.authority.recover", command.project_id)
        actor_id = principal.principal_id
    normalized = OutboxRecoveryCommand(
        **{**asdict(command), "actor_id": actor_id}
    )
    digest = hashlib.sha256(
        json.dumps(asdict(normalized), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """
            SELECT event_id, topic, status, attempt_count, replay_count, payload
            FROM outbox_event
            WHERE outbox_id = %s AND project_id = %s
            FOR UPDATE
            """,
            [normalized.outbox_id, normalized.project_id],
        )
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "OUTBOX_NOT_FOUND", "outbox event does not exist in the project"
            )
        uow.cursor.execute(
            """
            SELECT recovery_command_id, request_digest, recovery_action,
                   replacement_outbox_id
            FROM authority_outbox_recovery_command
            WHERE project_id = %s AND outbox_id = %s AND idempotency_key = %s
            """,
            [
                normalized.project_id,
                normalized.outbox_id,
                normalized.idempotency_key,
            ],
        )
        existing = uow.cursor.fetchone()
        if existing is not None:
            if existing[1] != digest:
                raise KernelError(
                    "OUTBOX_RECOVERY_IDEMPOTENCY_CONFLICT",
                    "outbox recovery idempotency key belongs to another command",
                )
            return {
                "recovery_command_id": str(existing[0]),
                "outbox_id": normalized.outbox_id,
                "action": str(existing[2]),
                "replacement_outbox_id": str(existing[3]),
                "replayed": True,
            }
        if row[2] != "dead_letter":
            raise KernelError(
                "OUTBOX_NOT_RECOVERABLE",
                f"outbox event cannot be requeued from status {row[2]}",
            )
        if int(row[3]) != normalized.expected_attempt_count:
            raise KernelError(
                "OUTBOX_RECOVERY_VERSION_CONFLICT",
                "outbox attempt count changed after the recovery decision",
            )
        recovery_command_id = str(uuid4())
        replacement_outbox_id = str(uuid4())
        action = "REQUEUE_NEW_GENERATION"
        uow.cursor.execute(
            """
            INSERT INTO outbox_event (
                outbox_id, event_id, project_id, topic, status,
                attempt_count, replay_count, payload
            ) VALUES (%s, %s, %s, %s, 'pending', 0, %s, %s)
            """,
            [
                replacement_outbox_id,
                str(row[0]),
                normalized.project_id,
                str(row[1]),
                int(row[4]) + 1,
                Jsonb(dict(row[5] or {})),
            ],
        )
        uow.cursor.execute(
            """
            INSERT INTO authority_outbox_recovery_command (
                recovery_command_id, outbox_id, replacement_outbox_id,
                project_id, actor_id,
                expected_attempt_count, idempotency_key, request_digest,
                reason, recovery_action, trace_id, correlation_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                recovery_command_id,
                normalized.outbox_id,
                replacement_outbox_id,
                normalized.project_id,
                normalized.actor_id,
                normalized.expected_attempt_count,
                normalized.idempotency_key,
                digest,
                normalized.reason,
                action,
                normalized.trace_id,
                normalized.correlation_id,
            ],
        )
        replay_count = int(row[4]) + 1
        _record_recovery(
            uow,
            command=normalized,
            recovery_command_id=recovery_command_id,
            replacement_outbox_id=replacement_outbox_id,
            source_event_id=str(row[0]),
            source_payload=dict(row[5] or {}),
            previous_replay_count=int(row[4]),
            replay_count=replay_count,
        )
        uow.commit()
    return {
        "recovery_command_id": recovery_command_id,
        "outbox_id": normalized.outbox_id,
        "replacement_outbox_id": replacement_outbox_id,
        "action": action,
        "replay_count": replay_count,
        "replayed": False,
    }


def _record_recovery(
    uow: AuthorityUnitOfWork,
    *,
    command: OutboxRecoveryCommand,
    recovery_command_id: str,
    replacement_outbox_id: str,
    source_event_id: str,
    source_payload: dict[str, object],
    previous_replay_count: int,
    replay_count: int,
) -> None:
    event_id = str(uuid4())
    operation_id = str(source_payload.get("operation_id") or "")
    payload = {
        "recovery_command_id": recovery_command_id,
        "outbox_id": command.outbox_id,
        "replacement_outbox_id": replacement_outbox_id,
        "source_event_id": source_event_id,
        "action": "REQUEUE_NEW_GENERATION",
        "previous_attempt_count": command.expected_attempt_count,
        "previous_replay_count": previous_replay_count,
        "replay_count": replay_count,
        "reason": command.reason,
        "actor_id": command.actor_id,
        "trace_id": command.trace_id,
        "operation_id": operation_id,
    }
    uow.cursor.execute(
        """
        SELECT COALESCE(MAX(sequence_number), 0) + 1
        FROM state_event
        WHERE aggregate_type = 'authority_outbox' AND aggregate_id = %s
        """,
        [command.outbox_id],
    )
    sequence = int(uow.cursor.fetchone()[0])
    uow.cursor.execute(
        """
        INSERT INTO state_event (
            event_id, project_id, aggregate_type, aggregate_id, event_type,
            event_version, sequence_number, payload, correlation_id, causation_id
        ) VALUES (
            %s, %s, 'authority_outbox', %s, 'authority.outbox.requeued',
            1, %s, %s, %s, %s
        )
        """,
        [
            event_id,
            command.project_id,
            command.outbox_id,
            sequence,
            Jsonb(payload),
            command.correlation_id,
            source_event_id,
        ],
    )
    uow.cursor.execute(
        """
        INSERT INTO audit_log (audit_id, project_id, operation_id, action, payload)
        VALUES (%s, %s, %s, 'authority.outbox.requeued', %s)
        """,
        [str(uuid4()), command.project_id, operation_id, Jsonb(payload)],
    )
    uow.cursor.execute(
        """
        INSERT INTO outbox_event (
            outbox_id, event_id, project_id, topic, status, payload
        ) VALUES (%s, %s, %s, 'authority.outbox.requeued', 'pending', %s)
        """,
        [str(uuid4()), event_id, command.project_id, Jsonb(payload)],
    )


def _validate(command: OutboxRecoveryCommand) -> None:
    if command.expected_attempt_count < 0 or any(
        not value
        for value in (
            command.outbox_id,
            command.project_id,
            command.actor_id,
            command.idempotency_key,
            command.reason,
            command.trace_id,
            command.correlation_id,
        )
    ):
        raise KernelError(
            "OUTBOX_RECOVERY_COMMAND_INVALID", "outbox recovery command is incomplete"
        )


__all__ = ["OutboxRecoveryCommand", "requeue_outbox_dead_letter"]
