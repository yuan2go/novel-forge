from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from .generation_policy import generation_graph


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
            raise KernelError(
                "OPERATION_NOT_FOUND", "operation deadline target is missing"
            )
        uow.cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM authority_worker_cancel_signal
                WHERE operation_id IN (%s, (SELECT root_operation_id FROM authority_operation WHERE operation_id=%s))
                  AND acknowledged_at IS NULL
            )
            """,
            [operation_id, operation_id],
        )
        cancelled = bool(uow.cursor.fetchone()[0])
        generation = generation_graph(uow.cursor, operation_id, project_id)
    if cancelled or row[0] == "CANCELLATION_REQUESTED":
        raise KernelError(
            "OPERATION_CANCELLATION_REQUESTED", "worker cancellation was requested"
        )
    deadline = row[1]
    if (
        not generation
        and deadline is not None
        and deadline <= datetime.now(timezone.utc)
    ):
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
            SELECT status, request_deadline_at, effect_type, operation_id
            FROM authority_external_effect
            WHERE external_effect_id = %s AND project_id = %s
            """,
            [external_effect_id, project_id],
        )
        row = uow.cursor.fetchone()
    if row is None:
        raise KernelError(
            "EXTERNAL_EFFECT_NOT_FOUND", "effect deadline target is missing"
        )
    probe_operation_execution(database_url, operation_id=row[3], project_id=project_id)
    deadline = row[1]
    if (
        row[2] != "model.invoke"
        and deadline is not None
        and deadline <= datetime.now(timezone.utc)
    ):
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
    """INVARIANT: Issue idempotent cancellation commands for expired business deadlines.

    A separate worker may call this while another worker is blocked. It never
    extends the business deadline and does not forcibly terminate Python threads.
    """
    if not actor_id or limit <= 0:
        raise ValueError("deadline scanner actor and positive limit are required")
    from novel_forge.modules.command_kernel.cancellation import (
        CancelCommand,
        request_cancellation,
    )

    issued: list[str] = []
    conflicts: list[str] = []
    expired_count = eligible_count = 0
    after = None
    scan_time = datetime.now(timezone.utc)
    while eligible_count < limit:
        with AuthorityUnitOfWork(database_url) as uow:
            uow.cursor.execute(
                """SELECT operation_id, project_id, version, trace_id, correlation_id, business_deadline_at
                FROM authority_operation
                WHERE business_deadline_at <= %s
                  AND status IN ('ADMITTED','READY','EXECUTING','WAITING_CHILDREN',
                                 'WAITING_EXTERNAL_RESULT','WAITING_GATE','FAILED_RETRYABLE')
                  AND (%s::timestamptz IS NULL OR (business_deadline_at,operation_id) > (%s,%s))
                ORDER BY business_deadline_at,operation_id LIMIT %s""",
                [
                    scan_time,
                    after[0] if after else None,
                    after[0] if after else None,
                    after[1] if after else None,
                    limit,
                ],
            )
            expired = tuple(uow.cursor.fetchall())
        if not expired:
            break
        for (
            operation_id,
            project_id,
            version,
            trace_id,
            correlation_id,
            deadline,
        ) in expired:
            after = (deadline, operation_id)
            expired_count += 1
            with AuthorityUnitOfWork(database_url) as uow:
                if generation_graph(uow.cursor, operation_id, project_id):
                    continue
            eligible_count += 1
            try:
                request_cancellation(
                    database_url,
                    CancelCommand(
                        operation_id=str(operation_id),
                        project_id=str(project_id),
                        actor_id=actor_id,
                        reason="frozen business deadline expired",
                        expected_version=int(version),
                        idempotency_key=f"deadline:{operation_id}:{version}",
                        trace_id=str(trace_id or f"trace:{uuid4()}"),
                        correlation_id=str(correlation_id or f"correlation:{uuid4()}"),
                        causation_id="deadline-scanner",
                    ),
                )
                issued.append(str(operation_id))
            except KernelError as exc:
                if exc.code in {
                    "OPERATION_VERSION_CONFLICT",
                    "OPERATION_STATUS_CONFLICT",
                    "IDEMPOTENCY_CONFLICT",
                }:
                    conflicts.append(str(operation_id))
                else:
                    raise
            if eligible_count >= limit:
                break
    return {
        "expired_count": expired_count,
        "cancellation_issued": issued,
        "concurrent_conflicts": conflicts,
    }


__all__ = [
    "probe_external_effect_execution",
    "probe_operation_execution",
    "scan_expired_operation_deadlines",
]
