"""Process-group entrypoints for the Authority-only deployment topology.

Groups follow execution characteristics. They do not create one deployment per
domain, and delivery queues never become the source of task state.
"""
from __future__ import annotations

import os
import signal
import time
from collections.abc import Callable

from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.command_kernel.deadline_runtime import (
    scan_expired_operation_deadlines,
)
from novel_forge.modules.command_kernel.lease_heartbeat import LeaseHeartbeatGuard
from novel_forge.modules.command_kernel.maintenance import (
    scan_expired_attempt_leases,
    scan_expired_outbox_leases,
    scan_external_effect_reconciliation,
)
from novel_forge.modules.command_kernel.worker_execution import (
    AuthorityWorkerExecutionBoundary,
    WorkerProgrammingError,
    WorkerSupervisor,
)
from novel_forge.modules.runtime_job import (
    RuntimeJobAuthority,
    RuntimeJobClaim,
    RuntimeJobSpec,
)
from novel_forge.storage.migrations import get_migration_status
from novel_forge.storage.worker_health import PostgresWorkerHealthObserver
from novel_forge.storage.database_runtime import close_all_database_runtimes


MAINTENANCE_RUNTIME_JOB_KINDS = (
    "OPERATION_DEADLINE_SCAN",
    "ATTEMPT_LEASE_EXPIRY_SCAN",
    "OUTBOX_RECOVERY_SCAN",
    "EXTERNAL_EFFECT_RECONCILIATION_SCAN",
)


def schedule_maintenance_runtime_jobs(
    runtime_jobs: RuntimeJobAuthority,
    *,
    batch_limit: int,
    schedule_bucket: int,
) -> tuple[dict[str, object], ...]:
    if batch_limit <= 0 or schedule_bucket < 0:
        raise ValueError("maintenance scheduling bounds are invalid")
    return tuple(
        runtime_jobs.schedule(
            RuntimeJobSpec(
                job_kind=job_kind,
                runtime_group="maintenance",
                subject_kind="AUTHORITY_MAINTENANCE_SCAN",
                subject_id=job_kind,
                project_id="",
                dedupe_key=f"{job_kind}:bucket:{schedule_bucket}",
                input_snapshot={
                    "job_kind": job_kind,
                    "batch_limit": batch_limit,
                    "schedule_bucket": schedule_bucket,
                },
                priority=10,
                max_attempts=5,
            )
        )
        for job_kind in MAINTENANCE_RUNTIME_JOB_KINDS
    )


def execute_maintenance_runtime_claim(
    database_url: str,
    runtime_jobs: RuntimeJobAuthority,
    claim: RuntimeJobClaim,
    *,
    actor_id: str,
    lease_seconds: int = 30,
) -> dict[str, object]:
    if claim.job_kind not in MAINTENANCE_RUNTIME_JOB_KINDS:
        raise RuntimeError("Maintenance worker received an unsupported Runtime Job")
    limit = int(claim.input_snapshot.get("batch_limit") or 100)
    runtime_jobs.start(claim)
    runtime_jobs.checkpoint(
        claim,
        {"stage": "SCAN_STARTED", "job_kind": claim.job_kind, "limit": limit},
    )
    try:
        with LeaseHeartbeatGuard(
            lambda: runtime_jobs.heartbeat(
                claim,
                lease_seconds=lease_seconds,
            ),
            lease_seconds=lease_seconds,
            label=f"runtime-job:{claim.attempt_id}",
        ):
            if claim.job_kind == "OPERATION_DEADLINE_SCAN":
                result: dict[str, object] = scan_expired_operation_deadlines(
                    database_url, actor_id=actor_id, limit=limit
                )
            elif claim.job_kind == "ATTEMPT_LEASE_EXPIRY_SCAN":
                result = {
                    "expired_attempt_leases": scan_expired_attempt_leases(
                        database_url, actor_id=actor_id, limit=limit
                    )
                }
            elif claim.job_kind == "OUTBOX_RECOVERY_SCAN":
                result = {
                    "recovered_outbox": scan_expired_outbox_leases(
                        database_url, actor_id=actor_id, limit=limit
                    )
                }
            else:
                result = {
                    "reconciliation_required": scan_external_effect_reconciliation(
                        database_url, actor_id=actor_id, limit=limit
                    ),
                    "external_effects_replayed": 0,
                    "provider_query_proven": False,
                }
        runtime_jobs.checkpoint(
            claim,
            {
                "stage": "SCAN_COMPLETED",
                "job_kind": claim.job_kind,
                "result_hash_pending": True,
            },
        )
        runtime_jobs.complete(claim, result)
        return result
    except Exception as exc:
        runtime_jobs.fail(
            claim,
            {"code": type(exc).__name__, "message": str(exc)},
        )
        raise


def _maintenance_loop() -> int:
    settings = IndustrialSettings.from_env()
    if settings.storage_authority != "postgresql" or not settings.database_url:
        raise RuntimeError("maintenance worker requires PostgreSQL authority")
    if settings.authority_runtime_profile == "track-b-minimal" and (
        settings.legacy_write_enabled or settings.silent_legacy_fallback_enabled
    ):
        raise RuntimeError("Authority-only worker forbids Legacy writes and fallback")
    migration = get_migration_status(settings.database_url)
    if not migration["ok"]:
        raise RuntimeError("Authority-only worker requires the current migration head")

    worker_id = str(
        os.environ.get("NOVEL_FORGE_RUNTIME_GROUP_WORKER_ID")
        or "maintenance-worker"
    ).strip()
    poll_seconds = max(
        0.1, float(os.environ.get("NOVEL_FORGE_AUTHORITY_POLL_SECONDS") or "1")
    )
    batch_size = max(
        1, int(os.environ.get("NOVEL_FORGE_AUTHORITY_BATCH_SIZE") or "100")
    )
    supervisor = WorkerSupervisor(
        worker_kind="maintenance",
        worker_id=worker_id,
        observer=PostgresWorkerHealthObserver(settings.database_url),
    )
    runtime_jobs = RuntimeJobAuthority(settings.database_url)
    boundary = AuthorityWorkerExecutionBoundary(worker_kind="maintenance")
    lease_seconds = max(
        5, int(os.environ.get("NOVEL_FORGE_AUTHORITY_LEASE_SECONDS") or "30")
    )
    stopping = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    while not stopping:
        schedule_bucket = int(time.time() // max(1.0, poll_seconds))
        schedule_maintenance_runtime_jobs(
            runtime_jobs,
            batch_limit=batch_size,
            schedule_bucket=schedule_bucket,
        )
        claims: list[RuntimeJobClaim] = []
        while len(claims) < len(MAINTENANCE_RUNTIME_JOB_KINDS) and not stopping:
            claim = runtime_jobs.claim(
                runtime_group="maintenance",
                worker_id=worker_id,
                lease_seconds=lease_seconds,
                job_kinds=MAINTENANCE_RUNTIME_JOB_KINDS,
            )
            if claim is None:
                break
            claims.append(claim)
        if not claims:
            supervisor.polled(idle=True)
            time.sleep(poll_seconds)
            continue
        try:
            failures = boundary.execute_batch(
                claims,
                identity=lambda claim: ("", claim.runtime_job_id),
                execute=lambda claim: execute_maintenance_runtime_claim(
                    settings.database_url,
                    runtime_jobs,
                    claim,
                    actor_id=worker_id,
                    lease_seconds=lease_seconds,
                ),
                on_task_start=supervisor.operation_started,
                on_task_finish=lambda job_id, succeeded: supervisor.operation_finished(
                    job_id, succeeded=succeeded
                ),
            )
            supervisor.batch_completed(failures)
            supervisor.polled(idle=False)
        except WorkerProgrammingError as error:
            supervisor.fatal(error)
            return WorkerSupervisor.FATAL_EXIT_CODE
        time.sleep(poll_seconds)
    supervisor.draining()
    supervisor.stopped()
    close_all_database_runtimes()
    return 0


def maintenance_main() -> int:
    return _maintenance_loop()


def _cli(target: Callable[[], int]) -> None:
    raise SystemExit(target())


def maintenance_cli() -> None:
    _cli(maintenance_main)


__all__ = [
    "maintenance_cli",
    "maintenance_main",
    "execute_maintenance_runtime_claim",
    "schedule_maintenance_runtime_jobs",
]
