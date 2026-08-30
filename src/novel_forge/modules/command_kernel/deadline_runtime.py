from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


def probe_operation_execution(
    database_url: str, *, operation_id: str, project_id: str
) -> dict[str, object]:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """
            SELECT status, business_deadline_at
            FROM authority_operation
            WHERE operation_id = %s AND project_id = %s
            """,
            [operation_id, project_id],
        )
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("OPERATION_NOT_FOUND", "operation deadline target is missing")
        uow.cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM authority_worker_cancel_signal
                WHERE operation_id = %s AND acknowledged_at IS NULL
            )
            """,
            [operation_id],
        )
        cancelled = bool(uow.cursor.fetchone()[0])
    if cancelled or row[0] == "CANCELLATION_REQUESTED":
        raise KernelError("OPERATION_CANCELLATION_REQUESTED", "worker cancellation was requested")
    deadline = row[1]
    if deadline is not None and deadline <= datetime.now(timezone.utc):
        raise KernelError(
            "OPERATION_BUSINESS_TIMEOUT",
            "frozen operation business deadline has expired",
        )
    return {"status": str(row[0]), "business_deadline_at": deadline}


def probe_external_effect_execution(
    database_url: str, *, external_effect_id: str, project_id: str
) -> dict[str, object]:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """
            SELECT status, request_deadline_at
            FROM authority_external_effect
            WHERE external_effect_id = %s AND project_id = %s
            """,
            [external_effect_id, project_id],
        )
        row = uow.cursor.fetchone()
    if row is None:
        raise KernelError("EXTERNAL_EFFECT_NOT_FOUND", "effect deadline target is missing")
    deadline = row[1]
    if deadline is not None and deadline <= datetime.now(timezone.utc):
        raise KernelError(
            "EFFECT_REQUEST_TIMEOUT",
            "frozen ExternalEffect request deadline has expired",
        )
    return {"status": str(row[0]), "request_deadline_at": deadline}


def scan_expired_operation_deadlines(
    database_url: str,
    *,
    actor_id: str,
    limit: int = 100,
) -> dict[str, object]:
    if not actor_id or limit <= 0:
        raise ValueError("deadline scanner actor and positive limit are required")
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """
            SELECT operation_id, project_id, version, trace_id, correlation_id
            FROM authority_operation
            WHERE business_deadline_at <= NOW()
              AND status IN ('ADMITTED','READY','EXECUTING','WAITING_CHILDREN',
                             'WAITING_EXTERNAL_RESULT','WAITING_GATE','FAILED_RETRYABLE')
            ORDER BY business_deadline_at, operation_id
            LIMIT %s
            """,
            [limit],
        )
        expired = tuple(uow.cursor.fetchall())
    from novel_forge.modules.command_kernel.cancellation import CancelCommand, request_cancellation

    issued: list[str] = []
    conflicts: list[str] = []
    for operation_id, project_id, version, trace_id, correlation_id in expired:
        try:
            request_cancellation(
                database_url,
                CancelCommand(
                    operation_id=str(operation_id), project_id=str(project_id),
                    actor_id=actor_id, reason="frozen business deadline expired",
                    expected_version=int(version),
                    idempotency_key=f"deadline:{operation_id}:{version}",
                    trace_id=str(trace_id or f"trace:{uuid4()}"),
                    correlation_id=str(correlation_id or f"correlation:{uuid4()}"),
                    causation_id="deadline-scanner",
                ),
            )
            issued.append(str(operation_id))
        except KernelError as exc:
            if exc.code in {"OPERATION_VERSION_CONFLICT", "OPERATION_STATUS_CONFLICT", "IDEMPOTENCY_CONFLICT"}:
                conflicts.append(str(operation_id))
                continue
            raise
    return {"expired_count": len(expired), "cancellation_issued": issued, "concurrent_conflicts": conflicts}


__all__ = ["probe_external_effect_execution", "probe_operation_execution", "scan_expired_operation_deadlines"]
