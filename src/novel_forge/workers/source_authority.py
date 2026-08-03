"""Standalone PostgreSQL Source Authority worker with lease takeover recovery."""
from __future__ import annotations

import os
import signal
import time

from novel_forge.api.authority_dependencies import (
    authority_release_identity,
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
from novel_forge.modules.source_authority import (
    SourceAuthorityApplication,
    SourceAuthorityScheduler,
)
from novel_forge.storage.worker_health import PostgresWorkerHealthObserver


def main() -> int:
    settings = IndustrialSettings.from_env()
    if settings.storage_authority != "postgresql" or not settings.database_url:
        raise RuntimeError("Source Authority worker requires PostgreSQL authority")
    build_id, commit_sha = authority_release_identity()
    worker_id = str(
        os.environ.get("NOVEL_FORGE_SOURCE_AUTHORITY_WORKER_ID")
        or "source-authority-worker"
    ).strip()
    principal = build_trusted_principal_resolver().resolve_worker_principal(worker_id)
    poll_seconds = max(
        0.05, float(os.environ.get("NOVEL_FORGE_AUTHORITY_POLL_SECONDS") or "1")
    )
    batch_size = max(
        1, int(os.environ.get("NOVEL_FORGE_AUTHORITY_BATCH_SIZE") or "10")
    )
    lease_seconds = max(
        1, int(os.environ.get("NOVEL_FORGE_AUTHORITY_LEASE_SECONDS") or "30")
    )
    application = SourceAuthorityApplication(
        settings.database_url,
        application_build_id=build_id,
        commit_sha=commit_sha,
        worker_id=worker_id,
    )
    scheduler = SourceAuthorityScheduler(
        application,
        worker_id=principal.principal_id,
        lease_seconds=lease_seconds,
    )
    boundary = AuthorityWorkerExecutionBoundary(worker_kind="source")
    supervisor = WorkerSupervisor(
        worker_kind="source",
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
        scan_expired_operation_deadlines(
            settings.database_url,
            actor_id=principal.principal_id,
            limit=batch_size,
        )
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
            )
            supervisor.batch_completed(failures)
        except WorkerProgrammingError as error:
            supervisor.fatal(error)
            return WorkerSupervisor.FATAL_EXIT_CODE
    supervisor.stopped()
    return 0


def cli() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    cli()
