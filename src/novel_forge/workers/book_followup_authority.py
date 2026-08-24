"""Isolated executor for non-blocking Book acceptance follow-up work."""

from __future__ import annotations

import os
import signal
import time
from dataclasses import asdict

from novel_forge.api.authority_dependencies import (
    build_book_authority_application,
    build_chapter_authority_application,
    build_production_execution_composition,
    build_trusted_principal_resolver,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.book_authority.queries import (
    BookFollowupAdmissionCandidate,
    PostgresBookProductionQuery,
)
from novel_forge.modules.book_followup_authority.coordinator import (
    PostgresBookFollowupCoordinator,
)
from novel_forge.modules.command_kernel.deadline_runtime import (
    scan_expired_operation_deadlines,
)
from novel_forge.modules.command_kernel.worker_execution import (
    AuthorityWorkerExecutionBoundary,
    WorkerProgrammingError,
    WorkerSupervisor,
)
from novel_forge.modules.content_authority.scheduler import ContentAuthorityScheduler
from novel_forge.modules.command_kernel.lease_heartbeat import LeaseHeartbeatGuard
from novel_forge.modules.runtime_job import (
    RuntimeJobAuthority,
    RuntimeJobClaim,
    RuntimeJobSpec,
)
from novel_forge.storage.database_runtime import close_all_database_runtimes
from novel_forge.storage.worker_health import PostgresWorkerHealthObserver


def schedule_book_followup_admission_jobs(
    coordinator: PostgresBookFollowupCoordinator,
    runtime_jobs: RuntimeJobAuthority,
    *,
    limit: int,
) -> tuple[dict[str, object], ...]:
    scheduled: list[dict[str, object]] = []
    for candidate in coordinator.admission_candidates(limit=limit):
        scheduled.append(
            runtime_jobs.schedule(
                RuntimeJobSpec(
                    job_kind="BOOK_FOLLOWUP_ADMISSION",
                    runtime_group="book_followup",
                    subject_kind="CHAPTER_ACCEPTANCE",
                    subject_id=candidate.chapter_request_id,
                    project_id=candidate.project_id,
                    dedupe_key=(
                        f"{candidate.chapter_request_id}:"
                        f"{'reader' if not candidate.reader_operation_id else 'recap'}"
                    ),
                    input_snapshot=asdict(candidate),
                    max_attempts=5,
                )
            )
        )
    return tuple(scheduled)


def execute_book_followup_admission_claim(
    coordinator: PostgresBookFollowupCoordinator,
    runtime_jobs: RuntimeJobAuthority,
    claim: RuntimeJobClaim,
    *,
    lease_seconds: int,
) -> dict[str, object]:
    if (
        claim.job_kind != "BOOK_FOLLOWUP_ADMISSION"
        or claim.subject_kind != "CHAPTER_ACCEPTANCE"
    ):
        raise RuntimeError("Book Followup worker received an invalid RuntimeJob")
    candidate = BookFollowupAdmissionCandidate(**claim.input_snapshot)
    if (
        candidate.chapter_request_id != claim.subject_id
        or candidate.project_id != claim.project_id
    ):
        raise RuntimeError("Book Followup RuntimeJob input identity drifted")
    runtime_jobs.start(claim)
    runtime_jobs.checkpoint(
        claim,
        {
            "stage": "BOOK_FOLLOWUP_ADMISSION_STARTED",
            "book_run_id": candidate.book_run_id,
            "chapter_request_id": candidate.chapter_request_id,
            "chapter_number": candidate.chapter_number,
        },
    )
    try:
        with LeaseHeartbeatGuard(
            lambda: runtime_jobs.heartbeat(claim, lease_seconds=lease_seconds),
            lease_seconds=lease_seconds,
            label=f"runtime-job:{claim.attempt_id}",
        ):
            result = coordinator.admit(candidate)
        payload = asdict(result)
        runtime_jobs.checkpoint(
            claim,
            {
                "stage": "BOOK_FOLLOWUP_OPERATION_ADMITTED",
                "operation_id": result.operation_id,
                "action": result.action,
            },
        )
        runtime_jobs.complete(claim, payload)
        return payload
    except Exception as exc:
        runtime_jobs.fail(
            claim,
            {
                "code": type(exc).__name__,
                "message": str(exc),
                "book_run_id": candidate.book_run_id,
                "chapter_request_id": candidate.chapter_request_id,
            },
            retry_delay_seconds=5,
        )
        raise


def main() -> int:
    settings = IndustrialSettings.from_env()
    if settings.storage_authority != "postgresql" or not settings.database_url:
        raise RuntimeError("Book Followup worker requires PostgreSQL authority")
    worker_id = str(
        os.environ.get("NOVEL_FORGE_BOOK_FOLLOWUP_WORKER_ID")
        or "book-followup-authority-worker"
    ).strip()
    principal = build_trusted_principal_resolver().resolve_worker_principal(worker_id)
    production_execution = build_production_execution_composition(settings)
    chapter = build_chapter_authority_application(
        settings, execution=production_execution
    )
    book = build_book_authority_application(
        settings,
        execution=production_execution,
        chapter_application=chapter,
    )
    query = PostgresBookProductionQuery(settings.database_url)
    coordinator = PostgresBookFollowupCoordinator(
        book,
        query=query,
        principal=principal,
    )
    runtime_jobs = RuntimeJobAuthority(settings.database_url)
    lease_seconds = max(
        5, int(os.environ.get("NOVEL_FORGE_AUTHORITY_LEASE_SECONDS") or "120")
    )
    scheduler = ContentAuthorityScheduler(
        settings.database_url,
        registry=book.followup.registry,
        worker_id=principal.principal_id,
        lease_seconds=lease_seconds,
    )
    poll_seconds = max(
        0.05, float(os.environ.get("NOVEL_FORGE_AUTHORITY_POLL_SECONDS") or "1")
    )
    batch_size = max(
        1, int(os.environ.get("NOVEL_FORGE_AUTHORITY_BATCH_SIZE") or "10")
    )
    stopping = False
    project_ids = (
        () if "*" in principal.project_scope else tuple(sorted(principal.project_scope))
    )
    boundary = AuthorityWorkerExecutionBoundary(worker_kind="book_followup")
    supervisor = WorkerSupervisor(
        worker_kind="book_followup",
        worker_id=principal.principal_id,
        observer=PostgresWorkerHealthObserver(settings.database_url),
    )

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        while not stopping:
            scan_expired_operation_deadlines(
                settings.database_url,
                actor_id=principal.principal_id,
                limit=batch_size,
            )
            coordinator.reconcile_completed_arc_checkpoint_followups(
                limit=batch_size
            )
            schedule_book_followup_admission_jobs(
                coordinator,
                runtime_jobs,
                limit=batch_size,
            )
            admission_claim = runtime_jobs.claim(
                runtime_group="book_followup",
                worker_id=principal.principal_id,
                lease_seconds=lease_seconds,
                job_kinds=("BOOK_FOLLOWUP_ADMISSION",),
                project_ids=project_ids,
            )
            if admission_claim is not None:
                supervisor.polled(idle=False)
                try:
                    failures = boundary.execute_batch(
                        (admission_claim,),
                        identity=lambda item: (item.project_id, item.runtime_job_id),
                        execute=lambda item: execute_book_followup_admission_claim(
                            coordinator,
                            runtime_jobs,
                            item,
                            lease_seconds=lease_seconds,
                        ),
                        on_task_start=supervisor.operation_started,
                        on_task_finish=lambda operation_id, succeeded: (
                            supervisor.operation_finished(
                                operation_id, succeeded=succeeded
                            )
                        ),
                    )
                    supervisor.batch_completed(failures)
                except WorkerProgrammingError as error:
                    supervisor.fatal(error)
                    return WorkerSupervisor.FATAL_EXIT_CODE
            pending = scheduler.pending_operations(
                limit=batch_size,
                project_ids=project_ids,
            )
            if pending:
                supervisor.polled(idle=False)

                def execute(item: tuple[str, str]) -> object:
                    operation_id, project_id = item
                    principal.require("book.authority.execute", project_id)
                    result = scheduler.run_or_recover(
                        operation_id=operation_id,
                        project_id=project_id,
                    )
                    coordinator.reconcile_arc_checkpoint_followup(operation_id)
                    return result

                try:
                    failures = boundary.execute_batch(
                        pending,
                        identity=lambda item: (item[1], item[0]),
                        execute=execute,
                        on_task_start=supervisor.operation_started,
                        on_task_finish=lambda operation_id, succeeded: (
                            supervisor.operation_finished(
                                operation_id, succeeded=succeeded
                            )
                        ),
                    )
                    supervisor.batch_completed(failures)
                except WorkerProgrammingError as error:
                    supervisor.fatal(error)
                    return WorkerSupervisor.FATAL_EXIT_CODE
            if admission_claim is None and not pending:
                supervisor.polled(idle=True)
                time.sleep(poll_seconds)
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
    "execute_book_followup_admission_claim",
    "main",
    "schedule_book_followup_admission_jobs",
]
