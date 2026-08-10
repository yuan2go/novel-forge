"""Bounded PostgreSQL Book Authority coordinator worker."""
from __future__ import annotations

import os
import signal
import time
from dataclasses import asdict

from novel_forge.api.authority_dependencies import (
    build_book_production_composition,
    build_chapter_authority_application,
    build_trusted_principal_resolver,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.book_authority import (
    BookProductionComposition,
    PostgresBookAuthorityScheduler,
)
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
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.database_runtime import close_all_database_runtimes
from novel_forge.storage.worker_health import PostgresWorkerHealthObserver


ACTIVE_STATES = (
    "CHAPTER_SUBMITTED",
    "CHAPTER_RUNNING",
    "CHAPTER_WAITING_RETRY",
    "CHAPTER_COMPLETED",
    "READER_OUTCOME_PENDING",
    "CHECKPOINT_PENDING",
    "REPLAN_REQUIRED",
    "REPLAN_GENERATING",
    "READY",
    "COMPLETED",
)


def schedule_book_coordination_jobs(
    database_url: str,
    runtime_jobs: RuntimeJobAuthority,
    *,
    limit: int,
    book_run_id: str = "",
) -> tuple[dict[str, object], ...]:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """
            SELECT book.book_run_id, book.project_id, book.state, book.version,
                   book.updated_at,
                   COALESCE((
                       SELECT COUNT(*)
                       FROM authority_runtime_job AS job
                       WHERE job.runtime_group='book'
                         AND job.job_kind='BOOK_COORDINATION_TICK'
                         AND job.subject_kind='BOOK_RUN'
                         AND job.subject_id=book.book_run_id
                   ), 0) AS previous_tick_count
            FROM authority_book_production AS book
            WHERE book.state = ANY(%s)
              AND (%s='' OR book.book_run_id=%s)
              AND (
                  book.state NOT IN ('READY','COMPLETED')
                  OR (
                      book.state='READY'
                      AND book.input_mode='RESOLVED_AUTHORITY_INPUT'
                  )
                  OR EXISTS (
                      SELECT 1
                      FROM authority_book_chapter_acceptance AS acceptance
                      JOIN authority_book_chapter_request AS request
                        ON request.chapter_request_id=acceptance.chapter_request_id
                      WHERE acceptance.book_run_id=book.book_run_id
                        AND acceptance.chapter_number=(
                            SELECT MAX(latest.chapter_number)
                            FROM authority_book_chapter_acceptance AS latest
                            WHERE latest.book_run_id=book.book_run_id
                        )
                        AND (
                            NOT EXISTS (
                                SELECT 1
                                FROM authority_book_followup_operation AS followup
                                JOIN authority_operation AS operation
                                  ON operation.operation_id=followup.operation_id
                                WHERE followup.chapter_request_id=request.chapter_request_id
                                  AND followup.followup_type='READER_OUTCOME'
                                  AND operation.status='SUCCEEDED'
                            )
                            OR (
                                (
                                    MOD(request.chapter_number, book.light_recap_cadence)=0
                                    OR MOD(request.chapter_number, book.formal_recap_cadence)=0
                                )
                                AND EXISTS (
                                    SELECT 1
                                    FROM authority_book_followup_operation AS reader_followup
                                    JOIN authority_operation AS reader_operation
                                      ON reader_operation.operation_id=reader_followup.operation_id
                                    WHERE reader_followup.chapter_request_id=request.chapter_request_id
                                      AND reader_followup.followup_type='READER_OUTCOME'
                                      AND reader_operation.status='SUCCEEDED'
                                )
                                AND NOT EXISTS (
                                    SELECT 1
                                    FROM authority_book_followup_operation AS recap_followup
                                    JOIN authority_operation AS recap_operation
                                      ON recap_operation.operation_id=recap_followup.operation_id
                                    WHERE recap_followup.chapter_request_id=request.chapter_request_id
                                      AND recap_followup.followup_type='LONGFORM_RECAP'
                                      AND recap_operation.status='SUCCEEDED'
                                )
                            )
                        )
                  )
              )
            ORDER BY book.updated_at, book.book_run_id
            LIMIT %s
            """,
            [list(ACTIVE_STATES), book_run_id, book_run_id, limit],
        )
        pending = tuple(uow.cursor.fetchall())
    scheduled: list[dict[str, object]] = []
    for (
        book_run_id,
        project_id,
        state,
        version,
        updated_at,
        previous_tick_count,
    ) in pending:
        scheduled.append(
            runtime_jobs.schedule(
                RuntimeJobSpec(
                    job_kind="BOOK_COORDINATION_TICK",
                    runtime_group="book",
                    subject_kind="BOOK_RUN",
                    subject_id=str(book_run_id),
                    project_id=str(project_id),
                    dedupe_key=f"{book_run_id}:tick:{int(previous_tick_count) + 1}",
                    input_snapshot={
                        "book_run_id": str(book_run_id),
                        "project_id": str(project_id),
                        "observed_state": str(state),
                        "observed_version": int(version),
                        "observed_updated_at": updated_at.isoformat(),
                        "tick_sequence": int(previous_tick_count) + 1,
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
    chapter = build_chapter_authority_application(settings)
    composition = build_book_production_composition(
        settings,
        principal=principal,
        chapter_application=chapter,
    )
    runtime_jobs = RuntimeJobAuthority(settings.database_url)
    poll_seconds = max(
        0.05, float(os.environ.get("NOVEL_FORGE_AUTHORITY_POLL_SECONDS") or "1")
    )
    batch_size = max(
        1, int(os.environ.get("NOVEL_FORGE_AUTHORITY_BATCH_SIZE") or "10")
    )
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
                settings.database_url,
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
                    on_task_finish=lambda operation_id, succeeded: supervisor.operation_finished(
                        operation_id, succeeded=succeeded
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
