from __future__ import annotations

from novel_forge.workers.dispatch_pause import pause_worker_dispatch

import os
import signal
import time

from novel_forge.api.authority_dependencies import (
    build_production_execution_composition,
    build_source_import_application,
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
from novel_forge.modules.source_import import SourceImportScheduler
from novel_forge.storage.database_runtime import close_all_database_runtimes
from novel_forge.storage.worker_health import PostgresWorkerHealthObserver


def main() -> int:
    settings = IndustrialSettings.from_env()
    if settings.storage_authority != "postgresql" or not settings.database_url:
        raise RuntimeError("Source Import worker requires PostgreSQL authority")
    worker_id = str(
        os.environ.get("NOVEL_FORGE_SOURCE_IMPORT_WORKER_ID")
        or "source-import-worker"
    ).strip()
    principal = build_trusted_principal_resolver().resolve_worker_principal(
        worker_id,
        permission_subset=frozenset(
            {
                "source.authority.execute",
                "mkaos.authority.execute",
                "external_effect.execute",
            }
        ),
    )
    poll_seconds = max(
        0.05, float(os.environ.get("NOVEL_FORGE_AUTHORITY_POLL_SECONDS") or "1")
    )
    batch_size = max(
        1, int(os.environ.get("NOVEL_FORGE_AUTHORITY_BATCH_SIZE") or "10")
    )
    lease_seconds = max(
        1, int(os.environ.get("NOVEL_FORGE_AUTHORITY_LEASE_SECONDS") or "30")
    )
    production_execution = build_production_execution_composition(settings)
    application = build_source_import_application(
        settings, execution=production_execution
    )
    scheduler = SourceImportScheduler(
        application,
        worker_id=principal.principal_id,
        lease_seconds=lease_seconds,
    )
    boundary = AuthorityWorkerExecutionBoundary(worker_kind="source_import")
    supervisor = WorkerSupervisor(
        worker_kind="source_import",
        worker_id=principal.principal_id,
        observer=PostgresWorkerHealthObserver(settings.database_url),
    )
    stopping = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    while not stopping:
        if pause_worker_dispatch(supervisor, poll_seconds):
            continue
        scan_expired_operation_deadlines(
            settings.database_url,
            actor_id=principal.principal_id,
            limit=batch_size,
        )
        from novel_forge.modules.source_import.market_runtime import enqueue_market_updates
        enqueue_market_updates(application, limit=batch_size)
        pending = scheduler.pending_operations(limit=batch_size)
        if not pending:
            supervisor.polled(idle=True)
            time.sleep(poll_seconds)
            continue
        supervisor.polled(idle=False)
        batch = tuple(item for item in pending if not stopping)

        def execute(item: tuple[str, str]) -> object:
            operation_id, project_id = item
            principal.require("source.authority.execute", project_id)
            return scheduler.run_or_recover(
                operation_id=operation_id,
                project_id=project_id,
            )

        try:
            failures = boundary.execute_batch(
                batch,
                identity=lambda item: (item[1], item[0]),
                execute=execute,
                on_task_start=supervisor.operation_started,
                on_task_finish=lambda operation_id, succeeded: supervisor.operation_finished(
                    operation_id, succeeded=succeeded
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


if __name__ == "__main__":
    raise SystemExit(main())
