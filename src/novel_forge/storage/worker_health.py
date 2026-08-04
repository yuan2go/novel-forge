from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

from novel_forge.modules.command_kernel.worker_execution import WorkerHealthSnapshot
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


class PostgresWorkerHealthObserver:
    """Persist supervisor state as a rebuildable operational projection."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def __call__(self, snapshot: WorkerHealthSnapshot) -> None:
        status = {
            "starting": "STARTING", "healthy": "BUSY", "idle": "READY",
            "degraded": "DEGRADED", "draining": "DRAINING",
            "fatal": "FATAL", "stopped": "STOPPED",
        }[snapshot.status.value]
        fatal = (
            {"message": snapshot.last_fatal_error, "exit_code": snapshot.exit_code}
            if snapshot.last_fatal_error else {}
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                INSERT INTO authority_worker_health_projection (
                    worker_id, worker_kind, status, last_poll_at,
                    last_successful_poll_at, last_fatal_error,
                    restart_expectation, active_operation_id, lease_count,
                    runtime_group, active_attempts, completed_count, failed_count,
                    database_status, drain_status, updated_at
                ) VALUES (
                    %s,%s,%s,NULLIF(%s,'')::timestamptz,
                    NULLIF(%s,'')::timestamptz,%s,%s,NULL,0,%s,0,%s,%s,
                    'READY',%s,NOW()
                )
                ON CONFLICT (worker_id, worker_kind) DO UPDATE SET
                    status=EXCLUDED.status, last_poll_at=EXCLUDED.last_poll_at,
                    last_successful_poll_at=EXCLUDED.last_successful_poll_at,
                    last_fatal_error=EXCLUDED.last_fatal_error,
                    restart_expectation=EXCLUDED.restart_expectation,
                    runtime_group=EXCLUDED.runtime_group,
                    active_attempts=EXCLUDED.active_attempts,
                    completed_count=EXCLUDED.completed_count,
                    failed_count=EXCLUDED.failed_count,
                    database_status=EXCLUDED.database_status,
                    drain_status=EXCLUDED.drain_status,
                    updated_at=NOW()
                """,
                [snapshot.worker_id, snapshot.worker_kind, status,
                 snapshot.last_poll_at, snapshot.last_successful_poll_at,
                 json.dumps(fatal), snapshot.restart_policy_expectation,
                 snapshot.worker_kind, snapshot.completed_batches,
                 snapshot.failed_tasks,
                 (
                     "DRAINING" if status == "DRAINING"
                     else "DRAINED" if status == "STOPPED"
                     else "ACCEPTING"
                 )],
            )
            uow.commit()


def runtime_health_report(database_url: str, *, freshness_seconds: int = 120) -> dict[str, Any]:
    if freshness_seconds <= 0:
        raise ValueError("worker freshness must be positive")
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            "SELECT worker_id, worker_kind, status, last_poll_at, "
            "last_successful_poll_at, last_fatal_error, restart_expectation, "
            "active_operation_id, lease_count, runtime_group, active_attempts, "
            "completed_count, failed_count, database_status, drain_status, "
            "updated_at, updated_at >= NOW() - (%s * INTERVAL '1 second') "
            "FROM authority_worker_health_projection ORDER BY worker_kind, worker_id",
            [freshness_seconds],
        )
        keys = (
            "worker_id", "worker_kind", "status", "last_poll_at",
            "last_successful_poll_at", "last_fatal_error", "restart_expectation",
            "active_operation_id", "lease_count", "runtime_group",
            "active_attempts", "completed_count", "failed_count",
            "database_status", "drain_status", "updated_at", "fresh",
        )
        workers = [dict(zip(keys, row, strict=True)) for row in uow.cursor.fetchall()]
        uow.cursor.execute("SELECT COUNT(*) FROM outbox_event WHERE published_at IS NULL")
        outbox_lag = int(uow.cursor.fetchone()[0])
        uow.cursor.execute("SELECT COUNT(*) FROM authority_operation WHERE status='DEAD_LETTER'")
        dead_letters = int(uow.cursor.fetchone()[0])
        uow.cursor.execute("SELECT COUNT(*) FROM authority_external_effect WHERE status='UNKNOWN'")
        unknown_effects = int(uow.cursor.fetchone()[0])
    ready = bool(workers) and all(
        item["fresh"] and item["status"] not in {"FATAL", "STOPPED"}
        for item in workers
    )
    return {
        "type": "RuntimeHealthReport", "database_ready": True,
        "liveness": "ALIVE", "readiness": "READY" if ready else "DEGRADED",
        "workers": workers, "worker_freshness_seconds": freshness_seconds,
        "outbox_lag": outbox_lag, "dead_letter_count": dead_letters,
        "unknown_effect_count": unknown_effects,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "contract_version": "runtime-health-report-v1",
    }


__all__ = ["PostgresWorkerHealthObserver", "runtime_health_report"]
