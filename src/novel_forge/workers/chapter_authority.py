"""Standalone bounded PostgreSQL Chapter Authority worker."""
from __future__ import annotations

import signal
import time
from dataclasses import dataclass

from novel_forge.api.authority_dependencies import (
    build_chapter_authority_application,
    build_trusted_principal_resolver,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.command_kernel.worker_execution import (
    AuthorityWorkerExecutionBoundary,
    WorkerProgrammingError,
    WorkerSupervisor,
)
from novel_forge.modules.command_kernel.deadline_runtime import scan_expired_operation_deadlines
from novel_forge.storage.worker_health import PostgresWorkerHealthObserver


@dataclass(slots=True)
class _Shutdown:
    requested: bool = False


def run_worker(*, poll_seconds: float = 1.0, batch_size: int = 10) -> int:
    if poll_seconds <= 0 or poll_seconds > 60 or batch_size <= 0:
        raise ValueError("worker poll and batch configuration is invalid")
    settings = IndustrialSettings.from_env()
    application = build_chapter_authority_application(settings)
    principal_resolver = build_trusted_principal_resolver()
    worker = principal_resolver.resolve_worker_principal(application.worker_id)
    scheduler = application.scheduler(principal=worker)
    shutdown = _Shutdown()
    boundary = AuthorityWorkerExecutionBoundary(worker_kind="chapter")
    supervisor = WorkerSupervisor(
        worker_kind="chapter", worker_id=worker.principal_id,
        observer=PostgresWorkerHealthObserver(settings.database_url),
    )

    def request_shutdown(_signum: int, _frame: object) -> None:
        shutdown.requested = True

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)
    while not shutdown.requested:
        scan_expired_operation_deadlines(
            settings.database_url, actor_id=worker.principal_id, limit=batch_size
        )
        roots = scheduler.pending_roots(limit=batch_size)
        if not roots:
            supervisor.polled(idle=True)
            time.sleep(poll_seconds)
            continue
        supervisor.polled(idle=False)
        batch = tuple(item for item in roots if not shutdown.requested)
        try:
            failures = boundary.execute_batch(
                batch,
                identity=lambda item: (item[0], item[1]),
                execute=lambda item: scheduler.tick(
                    project_id=item[0], root_operation_id=item[1]
                ),
            )
            supervisor.batch_completed(failures)
        except WorkerProgrammingError as error:
            supervisor.fatal(error)
            return WorkerSupervisor.FATAL_EXIT_CODE
    supervisor.stopped()
    return 0


def main() -> None:
    raise SystemExit(run_worker())


if __name__ == "__main__":
    main()
