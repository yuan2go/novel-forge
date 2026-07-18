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
from novel_forge.modules.command_kernel.worker_execution import AuthorityWorkerExecutionBoundary


@dataclass(slots=True)
class _Shutdown:
    requested: bool = False


def run_worker(*, poll_seconds: float = 1.0, batch_size: int = 10) -> None:
    if poll_seconds <= 0 or poll_seconds > 60 or batch_size <= 0:
        raise ValueError("worker poll and batch configuration is invalid")
    settings = IndustrialSettings.from_env()
    application = build_chapter_authority_application(settings)
    principal_resolver = build_trusted_principal_resolver()
    worker = principal_resolver.resolve_worker_principal(application.worker_id)
    scheduler = application.scheduler(principal=worker)
    shutdown = _Shutdown()
    boundary = AuthorityWorkerExecutionBoundary(worker_kind="chapter")

    def request_shutdown(_signum: int, _frame: object) -> None:
        shutdown.requested = True

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)
    while not shutdown.requested:
        roots = scheduler.pending_roots(limit=batch_size)
        if not roots:
            time.sleep(poll_seconds)
            continue
        batch = tuple(item for item in roots if not shutdown.requested)
        boundary.execute_batch(
            batch,
            identity=lambda item: (item[0], item[1]),
            execute=lambda item: scheduler.tick(
                project_id=item[0], root_operation_id=item[1]
            ),
        )


def main() -> None:
    run_worker()


if __name__ == "__main__":
    main()
