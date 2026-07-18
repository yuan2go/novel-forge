"""Frozen business-deadline and cooperative cancellation probes."""
from __future__ import annotations

from datetime import datetime, timezone

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


def probe_operation_execution(
    database_url: str, *, operation_id: str, project_id: str
) -> dict[str, object]:
    """Fail without extending the immutable business deadline."""
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


__all__ = ["probe_external_effect_execution", "probe_operation_execution"]
