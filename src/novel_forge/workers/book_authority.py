"""Bounded PostgreSQL Book Authority coordinator worker."""
from __future__ import annotations

import os
import signal
import time

from novel_forge.api.authority_dependencies import (
    build_book_authority_application,
    build_trusted_principal_resolver,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.book_authority import PostgresBookAuthorityScheduler
from novel_forge.modules.command_kernel.worker_execution import (
    AuthorityWorkerExecutionBoundary,
    WorkerProgrammingError,
    WorkerSupervisor,
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
)


def _pending(database_url: str, *, limit: int) -> tuple[tuple[str, str], ...]:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """
            SELECT book_run_id, project_id
            FROM authority_book_production
            WHERE state = ANY(%s)
            ORDER BY updated_at, book_run_id
            LIMIT %s
            """,
            [list(ACTIVE_STATES), limit],
        )
        return tuple((str(row[0]), str(row[1])) for row in uow.cursor.fetchall())


def main() -> int:
    settings = IndustrialSettings.from_env()
    if settings.storage_authority != "postgresql" or not settings.database_url:
        raise RuntimeError("Book Authority worker requires PostgreSQL authority")
    worker_id = str(
        os.environ.get("NOVEL_FORGE_BOOK_AUTHORITY_WORKER_ID")
        or "book-authority-worker"
    ).strip()
    principal = build_trusted_principal_resolver().resolve_worker_principal(worker_id)
    authority = build_book_authority_application(settings)
    scheduler = PostgresBookAuthorityScheduler(authority, principal=principal)
    poll_seconds = max(
        0.05, float(os.environ.get("NOVEL_FORGE_AUTHORITY_POLL_SECONDS") or "1")
    )
    batch_size = max(
        1, int(os.environ.get("NOVEL_FORGE_AUTHORITY_BATCH_SIZE") or "10")
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
            pending = _pending(settings.database_url, limit=batch_size)
            if not pending:
                supervisor.polled(idle=True)
                time.sleep(poll_seconds)
                continue
            supervisor.polled(idle=False)
            batch = tuple(item for item in pending if not stopping)
            try:
                failures = boundary.execute_batch(
                    batch,
                    identity=lambda item: (item[1], item[0]),
                    execute=lambda item: scheduler.tick(item[0]),
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
