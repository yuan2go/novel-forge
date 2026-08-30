from __future__ import annotations

import signal
import time
import os
from dataclasses import dataclass

from novel_forge.api.authority_dependencies import (
    build_agent_authority_scheduler,
    build_production_execution_composition,
    build_trusted_principal_resolver,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.command_kernel.deadline_runtime import (
    scan_expired_operation_deadlines,
)
from novel_forge.modules.command_kernel.worker_execution import (
    AuthorityWorkerExecutionBoundary,
    WorkerProgrammingError,
    WorkerSupervisor,
)
from novel_forge.storage.database_runtime import close_all_database_runtimes
from novel_forge.storage.worker_health import PostgresWorkerHealthObserver


@dataclass(slots=True)
class _Shutdown:
    requested: bool = False


def run_worker(*, poll_seconds: float = 1.0, batch_size: int = 10) -> int:
    if poll_seconds <= 0 or poll_seconds > 60 or batch_size <= 0:
        raise ValueError("worker poll and batch configuration is invalid")
    settings = IndustrialSettings.from_env()
    production_execution = build_production_execution_composition(settings)
    resolver = build_trusted_principal_resolver()
    worker_id = str(
        os.environ.get("NOVEL_FORGE_AUTHORITY_WORKER_ID")
        or "agent-authority-worker"
    ).strip()
    principal = resolver.resolve_worker_principal(worker_id)
    scheduler = build_agent_authority_scheduler(
        settings,
        execution=production_execution,
        worker_id=principal.principal_id,
    )
    shutdown = _Shutdown()
    boundary = AuthorityWorkerExecutionBoundary(worker_kind="agent")
    supervisor = WorkerSupervisor(
        worker_kind="agent",
        worker_id=principal.principal_id,
        observer=PostgresWorkerHealthObserver(settings.database_url),
    )

    def request_shutdown(_signum: int, _frame: object) -> None:
        shutdown.requested = True

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)
    while not shutdown.requested:
        scan_expired_operation_deadlines(
            settings.database_url,
            actor_id=principal.principal_id,
            limit=batch_size,
        )
        runs = scheduler.pending_runs(limit=batch_size)
        if not runs:
            supervisor.polled(idle=True)
            time.sleep(poll_seconds)
            continue
        supervisor.polled(idle=False)
        batch = tuple(item for item in runs if not shutdown.requested)
        try:
            failures = boundary.execute_batch(
                batch,
                identity=lambda item: (item[0], item[1]),
                execute=lambda item: scheduler.tick(
                    project_id=item[0], agent_run_id=item[1]
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
