from __future__ import annotations

from novel_forge.workers.dispatch_pause import pause_worker_dispatch

import signal
import time
from dataclasses import dataclass

from novel_forge.api.authority_dependencies import (
    build_chapter_authority_application,
    build_production_execution_composition,
    build_trusted_principal_resolver,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.command_kernel.worker_execution import (
    AuthorityWorkerExecutionBoundary,
    WorkerProgrammingError,
    WorkerSupervisor,
)
from novel_forge.modules.command_kernel.deadline_runtime import (
    scan_expired_operation_deadlines,
)
from novel_forge.storage.worker_health import PostgresWorkerHealthObserver
from novel_forge.storage.database_runtime import close_all_database_runtimes


@dataclass(slots=True)
class _Shutdown:
    requested: bool = False


def execute_chapter_with_creation_scope(settings, scheduler, worker, *, project_id, root_operation_id):
    from novel_forge.modules.book_authority.queries import PostgresBookProductionQuery
    from novel_forge.modules.book_authority.creation_runtime import creation_runtime_environment

    query = PostgresBookProductionQuery(settings.database_url)
    if not query.uses_creation_scope(project_id=project_id, subject_id=root_operation_id):
        return scheduler.tick(project_id=project_id, root_operation_id=root_operation_id)
    values = creation_runtime_environment(project_id)
    execution = build_production_execution_composition(settings, env=values)
    try:
        scoped = build_chapter_authority_application(settings, execution=execution, env=values)
        return scoped.scheduler(principal=worker).tick(project_id=project_id, root_operation_id=root_operation_id)
    finally:
        execution.close()


def run_worker(*, poll_seconds: float = 1.0, batch_size: int = 10) -> int:
    if poll_seconds <= 0 or poll_seconds > 60 or batch_size <= 0:
        raise ValueError("worker poll and batch configuration is invalid")
    settings = IndustrialSettings.from_env()
    production_execution = build_production_execution_composition(settings)
    application = build_chapter_authority_application(
        settings, execution=production_execution
    )
    principal_resolver = build_trusted_principal_resolver()
    worker = principal_resolver.resolve_worker_principal(application.worker_id)
    scheduler = application.scheduler(principal=worker)
    shutdown = _Shutdown()
    boundary = AuthorityWorkerExecutionBoundary(worker_kind="chapter")
    supervisor = WorkerSupervisor(
        worker_kind="chapter",
        worker_id=worker.principal_id,
        observer=PostgresWorkerHealthObserver(settings.database_url),
    )

    def request_shutdown(_signum: int, _frame: object) -> None:
        shutdown.requested = True

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)
    while not shutdown.requested:
        if pause_worker_dispatch(supervisor, poll_seconds):
            continue
        scan_expired_operation_deadlines(
            settings.database_url, actor_id=worker.principal_id, limit=batch_size
        )
        embedding_runtime = application.embedding_projection_runtime
        if embedding_runtime is not None:
            embedding_runtime.schedule_pending(limit=batch_size)
            embedding_operations = embedding_runtime.pending_operations(
                limit=batch_size
            )
            if embedding_operations:
                supervisor.polled(idle=False)
                failures = boundary.execute_batch(
                    embedding_operations,
                    identity=lambda item: (item[0], item[1]),
                    execute=lambda item: embedding_runtime.tick(
                        project_id=item[0], operation_id=item[1]
                    ),
                    on_task_start=supervisor.operation_started,
                    on_task_finish=lambda operation_id, succeeded: (
                        supervisor.operation_finished(operation_id, succeeded=succeeded)
                    ),
                )
                supervisor.batch_completed(failures)
                continue
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
                execute=lambda item: execute_chapter_with_creation_scope(
                    settings, scheduler, worker, project_id=item[0], root_operation_id=item[1]
                ),
                on_task_start=supervisor.operation_started,
                on_task_finish=lambda operation_id, succeeded: (
                    supervisor.operation_finished(operation_id, succeeded=succeeded)
                ),
            )
            supervisor.batch_completed(failures)
        except WorkerProgrammingError as error:
            supervisor.fatal(error)
            production_execution.close()
            close_all_database_runtimes()
            return WorkerSupervisor.FATAL_EXIT_CODE
    supervisor.draining()
    supervisor.stopped()
    production_execution.close()
    close_all_database_runtimes()
    return 0


def main() -> None:
    raise SystemExit(run_worker())


if __name__ == "__main__":
    main()
