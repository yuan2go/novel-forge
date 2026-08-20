"""Bounded PostgreSQL Book Authority coordinator worker."""

from __future__ import annotations

import os
import signal
import time
from dataclasses import asdict

from novel_forge.api.authority_dependencies import (
    build_book_production_composition,
    build_chapter_authority_application,
    build_production_execution_composition,
    build_trusted_principal_resolver,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.book_authority import (
    BookProductionComposition,
    PostgresBookAuthorityScheduler,
)
from novel_forge.modules.book_authority.queries import PostgresBookProductionQuery
from novel_forge.modules.command_kernel.worker_execution import (
    AuthorityWorkerExecutionBoundary,
    WorkerProgrammingError,
    WorkerSupervisor,
)
from novel_forge.modules.command_kernel.lease_heartbeat import LeaseHeartbeatGuard
from novel_forge.modules.runtime_job import (
    RuntimeJobAuthority,
    RuntimeJobClaim,
    RuntimeJobSpec,
)
from novel_forge.storage.database_runtime import close_all_database_runtimes
from novel_forge.storage.worker_health import PostgresWorkerHealthObserver


def schedule_book_coordination_jobs(
    query: PostgresBookProductionQuery,
    runtime_jobs: RuntimeJobAuthority,
    *,
    limit: int,
    book_run_id: str = "",
) -> tuple[dict[str, object], ...]:
    pending = query.coordination_candidates(
        book_run_id=book_run_id,
        limit=limit,
    )
    scheduled: list[dict[str, object]] = []
    for candidate in pending:
        scheduled.append(
            runtime_jobs.schedule(
                RuntimeJobSpec(
                    job_kind="BOOK_COORDINATION_TICK",
                    runtime_group="book",
                    subject_kind="BOOK_RUN",
                    subject_id=candidate.book_run_id,
                    project_id=candidate.project_id,
                    dedupe_key=(
                        f"{candidate.book_run_id}:tick:{candidate.next_tick_sequence}"
                    ),
                    input_snapshot={
                        "book_run_id": candidate.book_run_id,
                        "project_id": candidate.project_id,
                        "observed_state": candidate.state,
                        "observed_version": candidate.version,
                        "observed_updated_at": candidate.updated_at.isoformat(),
                        "tick_sequence": candidate.next_tick_sequence,
                    },
                    max_attempts=5,
                )
            )
        )
    return tuple(scheduled)


def execute_book_coordination_claim(
    runtime_jobs: RuntimeJobAuthority,
    ticker: BookProductionComposition | PostgresBookAuthorityScheduler,
    claim: RuntimeJobClaim,
    *,
    lease_seconds: int = 30,
) -> dict[str, object]:
    if claim.job_kind != "BOOK_COORDINATION_TICK" or claim.subject_kind != "BOOK_RUN":
        raise RuntimeError("Book worker received a non-Book Runtime Job")
    runtime_jobs.start(claim)
    runtime_jobs.checkpoint(
        claim,
        {
            "stage": "BOOK_TICK_STARTED",
            "book_run_id": claim.subject_id,
            "observed_state": claim.input_snapshot.get("observed_state", ""),
            "observed_version": claim.input_snapshot.get("observed_version", -1),
        },
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
            tick = ticker.tick(claim.subject_id)
        tick_result = asdict(tick)
        runtime_jobs.checkpoint(
            claim,
            {
                "stage": "BOOK_TICK_APPLIED",
                "book_run_id": claim.subject_id,
                "action": tick.action,
                "state": tick.state,
                "operation_id": tick.operation_id,
            },
        )
        runtime_jobs.complete(claim, tick_result)
        return tick_result
    except Exception as exc:
        runtime_jobs.fail(
            claim,
            {
                "code": type(exc).__name__,
                "message": str(exc),
                "book_run_id": claim.subject_id,
            },
        )
        raise


def main() -> int:
    settings = IndustrialSettings.from_env()
    if settings.storage_authority != "postgresql" or not settings.database_url:
        raise RuntimeError("Book Authority worker requires PostgreSQL authority")
    worker_id = str(
        os.environ.get("NOVEL_FORGE_BOOK_AUTHORITY_WORKER_ID")
        or "book-authority-worker"
    ).strip()
    principal = build_trusted_principal_resolver().resolve_worker_principal(worker_id)
    production_execution = build_production_execution_composition(settings)
    chapter = build_chapter_authority_application(
        settings, execution=production_execution
    )
    composition = build_book_production_composition(
        settings,
        principal=principal,
        execution=production_execution,
        chapter_application=chapter,
    )
    runtime_jobs = RuntimeJobAuthority(settings.database_url)
    poll_seconds = max(
        0.05, float(os.environ.get("NOVEL_FORGE_AUTHORITY_POLL_SECONDS") or "1")
    )
    batch_size = max(1, int(os.environ.get("NOVEL_FORGE_AUTHORITY_BATCH_SIZE") or "10"))
    lease_seconds = max(
        5, int(os.environ.get("NOVEL_FORGE_AUTHORITY_LEASE_SECONDS") or "30")
    )
    stopping = False
    boundary = AuthorityWorkerExecutionBoundary(worker_kind="book")
    supervisor = WorkerSupervisor(
        worker_kind="book",
        worker_id=worker_id,
        observer=PostgresWorkerHealthObserver(settings.database_url),
    )

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        while not stopping:
            schedule_book_coordination_jobs(
                composition.query,
                runtime_jobs,
                limit=batch_size,
            )
            claim = runtime_jobs.claim(
                runtime_group="book",
                worker_id=worker_id,
                lease_seconds=lease_seconds,
                job_kinds=("BOOK_COORDINATION_TICK",),
            )
            if claim is None:
                supervisor.polled(idle=True)
                time.sleep(poll_seconds)
                continue
            supervisor.polled(idle=False)
            # Claim only work that is about to execute. Pre-claiming a serial
            # batch allows later leases to expire before their heartbeat starts.
            batch = (claim,)
            try:
                failures = boundary.execute_batch(
                    batch,
                    identity=lambda item: (item.project_id, item.runtime_job_id),
                    execute=lambda item: execute_book_coordination_claim(
                        runtime_jobs,
                        composition,
                        item,
                        lease_seconds=lease_seconds,
                    ),
                    on_task_start=supervisor.operation_started,
                    on_task_finish=lambda operation_id, succeeded: (
                        supervisor.operation_finished(operation_id, succeeded=succeeded)
                    ),
                )
                supervisor.batch_completed(failures)
            except WorkerProgrammingError as error:
                supervisor.fatal(error)
                return WorkerSupervisor.FATAL_EXIT_CODE
        supervisor.draining()
        supervisor.stopped()
        return 0
    finally:
        production_execution.close()
        close_all_database_runtimes()


def cli() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    cli()


__all__ = [
    "cli",
    "execute_book_coordination_claim",
    "main",
    "schedule_book_coordination_jobs",
]
