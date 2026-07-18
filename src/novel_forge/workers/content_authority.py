"""Polling Content Authority worker backed by Command Kernel leases."""
from __future__ import annotations

import os
import signal
import time

from novel_forge.api.authority_dependencies import (
    build_content_authority_application,
    build_trusted_principal_resolver,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.command_kernel.worker_execution import AuthorityWorkerExecutionBoundary
from novel_forge.modules.content_authority.scheduler import ContentAuthorityScheduler


def main() -> int:
    settings = IndustrialSettings.from_env()
    application = build_content_authority_application(settings)
    worker_id = str(os.environ.get("NOVEL_FORGE_CONTENT_AUTHORITY_WORKER_ID") or "").strip()
    principal = build_trusted_principal_resolver().resolve_worker_principal(worker_id)
    poll_seconds = max(
        0.05, float(os.environ.get("NOVEL_FORGE_AUTHORITY_POLL_SECONDS") or "1")
    )
    batch_size = max(1, int(os.environ.get("NOVEL_FORGE_AUTHORITY_BATCH_SIZE") or "10"))
    lease_seconds = max(
        1, int(os.environ.get("NOVEL_FORGE_AUTHORITY_LEASE_SECONDS") or "120")
    )
    scheduler = ContentAuthorityScheduler(
        application.database_url,
        registry=application.registry,
        worker_id=principal.principal_id,
        lease_seconds=lease_seconds,
    )
    stopping = False
    boundary = AuthorityWorkerExecutionBoundary(worker_kind="content")

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    while not stopping:
        pending = scheduler.pending_operations(limit=batch_size)
        if not pending:
            time.sleep(poll_seconds)
            continue
        batch = tuple(item for item in pending if not stopping)

        def execute(item: tuple[str, str]) -> object:
            operation_id, project_id = item
            principal.require("content.authority.execute", project_id)
            return scheduler.run_or_recover(
                operation_id=operation_id,
                project_id=project_id,
            )

        boundary.execute_batch(
            batch,
            identity=lambda item: (item[1], item[0]),
            execute=execute,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
