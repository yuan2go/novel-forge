from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from typing import Any

from novel_forge.modules.command_kernel.worker_execution import WorkerHealthSnapshot
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.database_runtime import database_runtime_report


def derive_worker_database_status(
    *,
    fresh: bool,
    last_database_success_at: datetime | None,
    last_database_failure_at: datetime | None,
    now: datetime | None = None,
    degraded_window_seconds: int = 300,
) -> str:
    if degraded_window_seconds <= 0:
        raise ValueError("database degraded window must be positive")
    if not fresh:
        return "UNAVAILABLE"
    if last_database_success_at is None:
        return "UNKNOWN"
    current = now or datetime.now(timezone.utc)
    if (
        last_database_failure_at is not None
        and (current - last_database_failure_at).total_seconds()
        <= degraded_window_seconds
    ):
        return (
            "DEGRADED"
            if last_database_success_at >= last_database_failure_at
            else "UNAVAILABLE"
        )
    return "READY"


class PostgresWorkerHealthObserver:
    """Persist rebuildable worker, database, and fleet operational projections."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._last_database_failure_at: datetime | None = None
        self._last_database_error = ""

    def __call__(self, snapshot: WorkerHealthSnapshot) -> None:
        try:
            role = str(os.environ.get("NOVEL_FORGE_DATABASE_ROLE") or "api")
            database = database_runtime_report(self.database_url, role=role)
            self._persist(snapshot, database)
        except Exception as exc:
            # A fully unavailable database cannot update its own projection.
            # Retain only a non-sensitive process-local failure classification;
            # the API derives UNAVAILABLE from projection staleness. A later
            # successful observation persists this failure as DEGRADED evidence.
            self._last_database_failure_at = datetime.now(timezone.utc)
            self._last_database_error = type(exc).__name__

    def _persist(
        self,
        snapshot: WorkerHealthSnapshot,
        database: dict[str, Any],
    ) -> None:
        status = {
            "starting": "STARTING",
            "healthy": "BUSY",
            "idle": "READY",
            "degraded": "DEGRADED",
            "draining": "DRAINING",
            "fatal": "FATAL",
            "stopped": "STOPPED",
        }[snapshot.status.value]
        fatal = (
            {"message": snapshot.last_fatal_error, "exit_code": snapshot.exit_code}
            if snapshot.last_fatal_error
            else {}
        )
        now = datetime.now(timezone.utc)
        database_status = derive_worker_database_status(
            fresh=True,
            last_database_success_at=now,
            last_database_failure_at=self._last_database_failure_at,
            now=now,
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            command = self._command_execution(uow, snapshot.worker_id)
            runtime = self._runtime_job_execution(uow, snapshot.worker_id)
            outbox = self._outbox_execution(uow, snapshot.worker_id)
            snapshot_runtime_job = (
                snapshot.active_operation_id
                if snapshot.active_operation_id.startswith("runtime-job:")
                else ""
            )
            active_runtime_job_id = str(runtime[0] or snapshot_runtime_job)
            active_operation_id = str(command[0] or "")
            if not active_operation_id and not snapshot_runtime_job:
                active_operation_id = snapshot.active_operation_id
            if snapshot.worker_kind == "outbox" and not active_operation_id:
                active_operation_id = str(outbox[0] or snapshot.active_operation_id)
            active_attempt_id = str(runtime[1] or command[1] or "")
            active_attempts = int(command[2]) + int(runtime[2])
            lease_count = int(command[3]) + int(runtime[3]) + int(outbox[1])
            fencing_token = int(runtime[4] or outbox[4] or command[5] or 0)
            last_heartbeat_at = (
                runtime[5]
                or command[4]
                or outbox[5]
                or snapshot.last_heartbeat_at
                or None
            )
            completed_operations = snapshot.completed_operations
            failed_operations = snapshot.failed_operations
            if snapshot.worker_kind == "outbox":
                completed_operations = max(completed_operations, int(outbox[2]))
                failed_operations = max(failed_operations, int(outbox[3]))
            completed_runtime_jobs = int(runtime[6])
            failed_runtime_jobs = int(runtime[7])
            drain_status = (
                "DRAINING"
                if status == "DRAINING"
                else "DRAINED"
                if status == "STOPPED"
                else "ACCEPTING"
            )
            uow.cursor.execute(
                """
                INSERT INTO authority_worker_health_projection (
                    worker_id, worker_kind, status, last_poll_at,
                    last_successful_poll_at, last_fatal_error,
                    restart_expectation, active_operation_id, lease_count,
                    runtime_group, active_attempts, completed_count, failed_count,
                    database_status, drain_status, active_attempt_id,
                    last_heartbeat_at, completed_batch_count,
                    completed_operation_count, failed_operation_count,
                    last_database_error, active_runtime_job_id, fencing_token,
                    completed_runtime_job_count, failed_runtime_job_count,
                    last_database_success_at, last_database_failure_at, updated_at
                ) VALUES (
                    %s,%s,%s,NULLIF(%s,'')::timestamptz,
                    NULLIF(%s,'')::timestamptz,%s,%s,NULLIF(%s,''),%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),%s,NOW()
                )
                ON CONFLICT (worker_id, worker_kind) DO UPDATE SET
                    status=EXCLUDED.status,
                    last_poll_at=EXCLUDED.last_poll_at,
                    last_successful_poll_at=EXCLUDED.last_successful_poll_at,
                    last_fatal_error=EXCLUDED.last_fatal_error,
                    restart_expectation=EXCLUDED.restart_expectation,
                    active_operation_id=EXCLUDED.active_operation_id,
                    active_runtime_job_id=EXCLUDED.active_runtime_job_id,
                    active_attempt_id=EXCLUDED.active_attempt_id,
                    lease_count=EXCLUDED.lease_count,
                    fencing_token=EXCLUDED.fencing_token,
                    runtime_group=EXCLUDED.runtime_group,
                    active_attempts=EXCLUDED.active_attempts,
                    completed_count=EXCLUDED.completed_count,
                    failed_count=EXCLUDED.failed_count,
                    last_heartbeat_at=EXCLUDED.last_heartbeat_at,
                    completed_batch_count=EXCLUDED.completed_batch_count,
                    completed_operation_count=EXCLUDED.completed_operation_count,
                    failed_operation_count=EXCLUDED.failed_operation_count,
                    completed_runtime_job_count=EXCLUDED.completed_runtime_job_count,
                    failed_runtime_job_count=EXCLUDED.failed_runtime_job_count,
                    last_database_error=EXCLUDED.last_database_error,
                    last_database_success_at=EXCLUDED.last_database_success_at,
                    last_database_failure_at=COALESCE(
                        EXCLUDED.last_database_failure_at,
                        authority_worker_health_projection.last_database_failure_at
                    ),
                    database_status=EXCLUDED.database_status,
                    drain_status=EXCLUDED.drain_status,
                    updated_at=NOW()
                """,
                [
                    snapshot.worker_id,
                    snapshot.worker_kind,
                    status,
                    snapshot.last_poll_at,
                    snapshot.last_successful_poll_at,
                    json.dumps(fatal),
                    snapshot.restart_policy_expectation,
                    active_operation_id,
                    lease_count,
                    snapshot.worker_kind,
                    active_attempts,
                    snapshot.completed_batches,
                    snapshot.failed_tasks,
                    database_status,
                    drain_status,
                    active_attempt_id,
                    last_heartbeat_at,
                    snapshot.completed_batches,
                    completed_operations,
                    failed_operations,
                    self._last_database_error,
                    active_runtime_job_id,
                    fencing_token,
                    completed_runtime_jobs,
                    failed_runtime_jobs,
                    self._last_database_failure_at,
                ],
            )
            backlogs = self._backlogs(uow)
            metrics = database
            uow.cursor.execute(
                """
                INSERT INTO authority_worker_operational_metrics_projection(
                    worker_id, worker_kind, runtime_group,
                    database_identity_fingerprint, database_role, service,
                    pool_config_fingerprint, pool_size, pool_in_use, pool_waiting,
                    transaction_count, rollback_count, retry_count, timeout_count,
                    deadlock_count, serialization_failure_count,
                    long_transaction_count, runtime_job_backlog, outbox_backlog,
                    unknown_effect_backlog, stale_worker_count, recorded_at
                ) VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,NOW()
                )
                ON CONFLICT (worker_id, worker_kind) DO UPDATE SET
                    runtime_group=EXCLUDED.runtime_group,
                    database_identity_fingerprint=EXCLUDED.database_identity_fingerprint,
                    database_role=EXCLUDED.database_role,
                    service=EXCLUDED.service,
                    pool_config_fingerprint=EXCLUDED.pool_config_fingerprint,
                    pool_size=EXCLUDED.pool_size,
                    pool_in_use=EXCLUDED.pool_in_use,
                    pool_waiting=EXCLUDED.pool_waiting,
                    transaction_count=EXCLUDED.transaction_count,
                    rollback_count=EXCLUDED.rollback_count,
                    retry_count=EXCLUDED.retry_count,
                    timeout_count=EXCLUDED.timeout_count,
                    deadlock_count=EXCLUDED.deadlock_count,
                    serialization_failure_count=EXCLUDED.serialization_failure_count,
                    long_transaction_count=EXCLUDED.long_transaction_count,
                    runtime_job_backlog=EXCLUDED.runtime_job_backlog,
                    outbox_backlog=EXCLUDED.outbox_backlog,
                    unknown_effect_backlog=EXCLUDED.unknown_effect_backlog,
                    stale_worker_count=EXCLUDED.stale_worker_count,
                    recorded_at=NOW()
                """,
                [
                    snapshot.worker_id,
                    snapshot.worker_kind,
                    snapshot.worker_kind,
                    metrics["database_identity_fingerprint"],
                    metrics["role"],
                    metrics["service"],
                    metrics["pool_config_fingerprint"],
                    metrics["pool_size"],
                    metrics["pool_in_use"],
                    metrics["pool_waiting"],
                    metrics["transaction_count"],
                    metrics["rollback_count"],
                    metrics["retry_count"],
                    metrics["timeout_count"],
                    metrics["deadlock_count"],
                    metrics["serialization_failure_count"],
                    metrics["long_transaction_count"],
                    backlogs[0],
                    backlogs[1],
                    backlogs[2],
                    backlogs[3],
                ],
            )
            uow.commit()

    @staticmethod
    def _command_execution(
        uow: AuthorityUnitOfWork, worker_id: str
    ) -> tuple[Any, ...]:
        uow.cursor.execute(
            """
            SELECT COALESCE((
                       SELECT attempt.operation_id
                       FROM authority_attempt AS attempt
                       WHERE attempt.worker_id=%s
                         AND attempt.status IN (
                             'CREATED','QUEUED','LEASED','RUNNING',
                             'CHECKPOINTED','RESULT_SUBMITTED'
                         )
                       ORDER BY COALESCE(attempt.started_at,attempt.queued_at) DESC,
                                attempt.attempt_number DESC LIMIT 1
                   ), ''),
                   COALESCE((
                       SELECT attempt.attempt_id FROM authority_attempt AS attempt
                       WHERE attempt.worker_id=%s
                         AND attempt.status IN (
                             'CREATED','QUEUED','LEASED','RUNNING',
                             'CHECKPOINTED','RESULT_SUBMITTED'
                         )
                       ORDER BY COALESCE(attempt.started_at,attempt.queued_at) DESC,
                                attempt.attempt_number DESC LIMIT 1
                   ), ''),
                   (SELECT COUNT(*) FROM authority_attempt
                    WHERE worker_id=%s AND status IN (
                        'CREATED','QUEUED','LEASED','RUNNING',
                        'CHECKPOINTED','RESULT_SUBMITTED'
                    )),
                   (SELECT COUNT(*) FROM authority_lease_acquisition
                    WHERE owner=%s AND status='HELD' AND expires_at>NOW()),
                   (SELECT MAX(heartbeat_at) FROM authority_lease_acquisition
                    WHERE owner=%s),
                   COALESCE((SELECT MAX(fencing_token)
                             FROM authority_lease_acquisition
                             WHERE owner=%s AND status='HELD'),0)
            """,
            [worker_id] * 6,
        )
        return tuple(uow.cursor.fetchone())

    @staticmethod
    def _runtime_job_execution(
        uow: AuthorityUnitOfWork, worker_id: str
    ) -> tuple[Any, ...]:
        uow.cursor.execute(
            """
            SELECT COALESCE((
                       SELECT job.runtime_job_id
                       FROM authority_runtime_job AS job
                       JOIN authority_runtime_job_attempt AS attempt
                         ON attempt.attempt_id=job.current_attempt_id
                       WHERE attempt.worker_id=%s
                         AND job.status IN ('CLAIMED','RUNNING','CHECKPOINTED')
                       ORDER BY attempt.started_at DESC LIMIT 1
                   ), ''),
                   COALESCE((
                       SELECT attempt.attempt_id
                       FROM authority_runtime_job_attempt AS attempt
                       JOIN authority_runtime_job AS job
                         ON job.current_attempt_id=attempt.attempt_id
                       WHERE attempt.worker_id=%s
                         AND job.status IN ('CLAIMED','RUNNING','CHECKPOINTED')
                       ORDER BY attempt.started_at DESC LIMIT 1
                   ), ''),
                   (SELECT COUNT(*) FROM authority_runtime_job_attempt AS attempt
                    JOIN authority_runtime_job AS job
                      ON job.current_attempt_id=attempt.attempt_id
                    WHERE attempt.worker_id=%s
                      AND job.status IN ('CLAIMED','RUNNING','CHECKPOINTED')),
                   (SELECT COUNT(*) FROM authority_runtime_job_lease
                    WHERE worker_id=%s AND status='HELD' AND lease_expires_at>NOW()),
                   COALESCE((SELECT MAX(fencing_token)
                             FROM authority_runtime_job_lease
                             WHERE worker_id=%s AND status='HELD'
                               AND lease_expires_at>NOW()),0),
                   (SELECT MAX(heartbeat_at) FROM authority_runtime_job_lease
                    WHERE worker_id=%s),
                   (SELECT COUNT(*) FROM authority_runtime_job_attempt
                    WHERE worker_id=%s AND status='SUCCEEDED'),
                   (SELECT COUNT(*) FROM authority_runtime_job_attempt
                    WHERE worker_id=%s AND status IN ('FAILED','ABANDONED'))
            """,
            [worker_id] * 8,
        )
        return tuple(uow.cursor.fetchone())

    @staticmethod
    def _outbox_execution(
        uow: AuthorityUnitOfWork, worker_id: str
    ) -> tuple[Any, ...]:
        uow.cursor.execute(
            """
            SELECT COALESCE((SELECT outbox_id FROM outbox_event
                             WHERE claimed_by=%s AND LOWER(status)='claimed'
                               AND lease_expires_at>NOW()
                             ORDER BY claimed_at DESC LIMIT 1), ''),
                   COUNT(*) FILTER (WHERE LOWER(status)='claimed'
                                     AND lease_expires_at>NOW()),
                   COUNT(*) FILTER (WHERE LOWER(status)='acked'),
                   COUNT(*) FILTER (WHERE LOWER(status) IN ('failed','dead_letter')),
                   COALESCE(MAX(fencing_token) FILTER (
                       WHERE LOWER(status)='claimed' AND lease_expires_at>NOW()
                   ),0),
                   MAX(claimed_at)
            FROM outbox_event WHERE claimed_by=%s
            """,
            [worker_id, worker_id],
        )
        return tuple(uow.cursor.fetchone())

    @staticmethod
    def _backlogs(uow: AuthorityUnitOfWork) -> tuple[int, int, int, int]:
        uow.cursor.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM authority_runtime_job
                 WHERE status IN ('READY','RETRY_WAIT')),
                (SELECT COUNT(*) FROM outbox_event
                 WHERE LOWER(status) IN ('pending','queued','failed','claimed')),
                (SELECT COUNT(*) FROM authority_external_effect
                 WHERE status IN ('UNKNOWN','RECONCILIATION_REQUIRED')),
                (SELECT COUNT(*) FROM authority_worker_health_projection
                 WHERE updated_at < NOW()-INTERVAL '120 seconds'
                    OR database_status='UNAVAILABLE')
            """
        )
        return tuple(int(value) for value in uow.cursor.fetchone())


def runtime_health_report(
    database_url: str, *, freshness_seconds: int = 120
) -> dict[str, Any]:
    if freshness_seconds <= 0:
        raise ValueError("worker freshness must be positive")
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """
            SELECT worker_id, worker_kind, status, last_poll_at,
                   last_successful_poll_at, last_fatal_error,
                   restart_expectation, active_operation_id, lease_count,
                   runtime_group, active_attempts, completed_count, failed_count,
                   database_status, drain_status, active_attempt_id,
                   last_heartbeat_at, completed_batch_count,
                   completed_operation_count, failed_operation_count,
                   last_database_error, active_runtime_job_id, fencing_token,
                   completed_runtime_job_count, failed_runtime_job_count,
                   last_database_success_at, last_database_failure_at,
                   updated_at,
                   updated_at >= NOW()-(%s * INTERVAL '1 second')
            FROM authority_worker_health_projection
            ORDER BY worker_kind, worker_id
            """,
            [freshness_seconds],
        )
        keys = (
            "worker_id",
            "worker_kind",
            "status",
            "last_poll_at",
            "last_successful_poll_at",
            "last_fatal_error",
            "restart_expectation",
            "active_operation_id",
            "lease_count",
            "runtime_group",
            "active_attempts",
            "completed_count",
            "failed_count",
            "database_status",
            "drain_status",
            "active_attempt_id",
            "last_heartbeat_at",
            "completed_batch_count",
            "completed_operation_count",
            "failed_operation_count",
            "last_database_error",
            "active_runtime_job_id",
            "fencing_token",
            "completed_runtime_job_count",
            "failed_runtime_job_count",
            "last_database_success_at",
            "last_database_failure_at",
            "updated_at",
            "fresh",
        )
        workers = [dict(zip(keys, row, strict=True)) for row in uow.cursor.fetchall()]
        for worker in workers:
            worker["database_status"] = derive_worker_database_status(
                fresh=bool(worker["fresh"]),
                last_database_success_at=worker["last_database_success_at"],
                last_database_failure_at=worker["last_database_failure_at"],
            )
        uow.cursor.execute(
            """
            SELECT COALESCE(SUM(pool_size),0),
                   COALESCE(SUM(pool_in_use),0),
                   COALESCE(SUM(pool_waiting),0),
                   COALESCE(SUM(transaction_count),0),
                   COALESCE(SUM(rollback_count),0),
                   COALESCE(SUM(retry_count),0),
                   COALESCE(SUM(timeout_count),0),
                   COALESCE(SUM(deadlock_count),0),
                   COALESCE(SUM(serialization_failure_count),0),
                   COALESCE(SUM(long_transaction_count),0),
                   COALESCE(MAX(runtime_job_backlog),0),
                   COALESCE(MAX(outbox_backlog),0),
                   COALESCE(MAX(unknown_effect_backlog),0),
                   COALESCE(MAX(stale_worker_count),0)
            FROM authority_worker_operational_metrics_projection
            """
        )
        metric_values = tuple(int(value) for value in uow.cursor.fetchone())
        metric_keys = (
            "pool_size",
            "pool_in_use",
            "pool_waiting",
            "transaction_count",
            "rollback_count",
            "retry_count",
            "timeout_count",
            "deadlock_count",
            "serialization_failure_count",
            "long_transaction_count",
            "runtime_job_backlog",
            "outbox_backlog",
            "unknown_effect_backlog",
            "stale_worker_count",
        )
        fleet_metrics = dict(zip(metric_keys, metric_values, strict=True))
        uow.cursor.execute(
            "SELECT COUNT(*) FROM authority_operation WHERE status='DEAD_LETTER'"
        )
        dead_letters = int(uow.cursor.fetchone()[0])
    ready = bool(workers) and all(
        item["fresh"]
        and item["status"] not in {"FATAL", "STOPPED"}
        and item["database_status"] not in {"UNAVAILABLE", "UNKNOWN"}
        for item in workers
    )
    return {
        "type": "RuntimeHealthReport",
        "database_ready": True,
        "liveness": "ALIVE",
        "readiness": "READY" if ready else "DEGRADED",
        "workers": workers,
        "worker_freshness_seconds": freshness_seconds,
        "outbox_lag": fleet_metrics["outbox_backlog"],
        "dead_letter_count": dead_letters,
        "unknown_effect_count": fleet_metrics["unknown_effect_backlog"],
        "fleet_metrics": fleet_metrics,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "contract_version": "runtime-health-report-v2",
    }


__all__ = [
    "PostgresWorkerHealthObserver",
    "derive_worker_database_status",
    "runtime_health_report",
]
