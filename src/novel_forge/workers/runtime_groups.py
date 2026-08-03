"""Process-group entrypoints for the Authority-only deployment topology.

Groups follow execution characteristics. They do not create one deployment per
domain, and delivery queues never become the source of task state.
"""
from __future__ import annotations

import os
import signal
import time
from collections.abc import Callable

from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.command_kernel.deadline_runtime import (
    scan_expired_operation_deadlines,
)
from novel_forge.modules.command_kernel.worker_execution import WorkerSupervisor
from novel_forge.storage.migrations import get_migration_status
from novel_forge.storage.worker_health import PostgresWorkerHealthObserver


def _authority_maintenance_loop(worker_kind: str) -> int:
    settings = IndustrialSettings.from_env()
    if settings.storage_authority != "postgresql" or not settings.database_url:
        raise RuntimeError(f"{worker_kind} requires PostgreSQL authority")
    if settings.authority_runtime_profile == "track-b-minimal" and (
        settings.legacy_write_enabled or settings.silent_legacy_fallback_enabled
    ):
        raise RuntimeError("Authority-only worker forbids Legacy writes and fallback")
    migration = get_migration_status(settings.database_url)
    if not migration["ok"]:
        raise RuntimeError("Authority-only worker requires the current migration head")

    worker_id = str(
        os.environ.get("NOVEL_FORGE_RUNTIME_GROUP_WORKER_ID")
        or f"{worker_kind}-worker"
    ).strip()
    poll_seconds = max(
        0.1, float(os.environ.get("NOVEL_FORGE_AUTHORITY_POLL_SECONDS") or "1")
    )
    batch_size = max(
        1, int(os.environ.get("NOVEL_FORGE_AUTHORITY_BATCH_SIZE") or "100")
    )
    supervisor = WorkerSupervisor(
        worker_kind=worker_kind,
        worker_id=worker_id,
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
            actor_id=worker_id,
            limit=batch_size,
        )
        # This generic group only owns deadline scanning and health evidence.
        # Transaction Commands recover by rollback/replay; domain Durable Jobs
        # require their explicit scheduler/consumer and are not claimed here.
        supervisor.polled(idle=True)
        time.sleep(poll_seconds)
    supervisor.stopped()
    return 0


def authority_main() -> int:
    return _authority_maintenance_loop("authority")


def maintenance_main() -> int:
    return _authority_maintenance_loop("maintenance")


def execution_main() -> int:
    from novel_forge.workers.chapter_authority import run_worker

    return run_worker()


def integration_main() -> int:
    from novel_forge.workers.source_authority import main

    return main()


def _cli(target: Callable[[], int]) -> None:
    raise SystemExit(target())


def authority_cli() -> None:
    _cli(authority_main)


def execution_cli() -> None:
    _cli(execution_main)


def integration_cli() -> None:
    _cli(integration_main)


def maintenance_cli() -> None:
    _cli(maintenance_main)


__all__ = [
    "authority_cli",
    "authority_main",
    "execution_cli",
    "execution_main",
    "integration_cli",
    "integration_main",
    "maintenance_cli",
    "maintenance_main",
]
