"""Bounded operational recovery cycle for the Authority maintenance worker."""
from __future__ import annotations

from uuid import uuid4

from novel_forge.modules.command_kernel.deadline_runtime import (
    scan_expired_operation_deadlines,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


def run_maintenance_cycle(
    database_url: str, *, actor_id: str, limit: int = 100
) -> dict[str, object]:
    if not actor_id or limit <= 0:
        raise ValueError("maintenance actor and positive limit are required")
    cycle_id = f"maintenance-cycle:{uuid4()}"
    deadline = scan_expired_operation_deadlines(
        database_url, actor_id=actor_id, limit=limit
    )
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """
            WITH selected AS (
                SELECT lease_id
                FROM authority_lease_acquisition
                WHERE status='HELD' AND expires_at <= NOW()
                ORDER BY expires_at, lease_id
                FOR UPDATE SKIP LOCKED
                LIMIT %s
            )
            UPDATE authority_lease_acquisition AS lease
            SET status='EXPIRED', released_at=NOW(),
                release_reason='maintenance_lease_expired'
            FROM selected
            WHERE lease.lease_id=selected.lease_id
            RETURNING lease.lease_id, lease.attempt_id, lease.fencing_token
            """,
            [limit],
        )
        expired_attempt_leases = [
            {
                "lease_id": str(row[0]),
                "attempt_id": str(row[1]),
                "fencing_token": int(row[2]),
            }
            for row in uow.cursor.fetchall()
        ]
        uow.cursor.execute(
            """
            WITH selected AS (
                SELECT outbox_id
                FROM outbox_event
                WHERE LOWER(status)='claimed' AND lease_expires_at <= NOW()
                ORDER BY lease_expires_at, outbox_id
                FOR UPDATE SKIP LOCKED
                LIMIT %s
            )
            UPDATE outbox_event AS event
            SET status=CASE WHEN attempt_count >= 5 THEN 'dead_letter' ELSE 'failed' END,
                dead_letter_at=CASE WHEN attempt_count >= 5 THEN NOW() ELSE dead_letter_at END,
                available_at=NOW(), lease_expires_at=NULL,
                last_error='maintenance_outbox_lease_expired', updated_at=NOW()
            FROM selected
            WHERE event.outbox_id=selected.outbox_id
            RETURNING event.outbox_id, event.status, event.lease_id,
                      event.fencing_token, event.runtime_group
            """,
            [limit],
        )
        recovered_outbox = [
            {
                "outbox_id": str(row[0]),
                "status": str(row[1]),
                "lease_id": str(row[2]),
                "fencing_token": int(row[3]),
                "runtime_group": str(row[4]),
            }
            for row in uow.cursor.fetchall()
        ]
        uow.cursor.execute(
            """
            SELECT external_effect_id, operation_id, status
            FROM authority_external_effect
            WHERE status IN ('UNKNOWN','RECONCILIATION_REQUIRED')
            ORDER BY created_at, external_effect_id
            LIMIT %s
            """,
            [limit],
        )
        reconciliation_required = [
            {
                "external_effect_id": str(row[0]),
                "operation_id": str(row[1]),
                "status": str(row[2]),
                "action": "QUERY_OR_MANUAL_RECONCILIATION_REQUIRED",
            }
            for row in uow.cursor.fetchall()
        ]
        uow.commit()
    return {
        "cycle_id": cycle_id,
        "worker_id": actor_id,
        "deadline_recovery": deadline,
        "expired_attempt_leases": expired_attempt_leases,
        "recovered_outbox": recovered_outbox,
        "reconciliation_required": reconciliation_required,
        "external_effects_replayed": 0,
    }


__all__ = ["run_maintenance_cycle"]
