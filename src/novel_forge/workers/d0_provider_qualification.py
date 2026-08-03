"""Integration worker for PostgreSQL-authoritative D0 qualification jobs."""
from __future__ import annotations

import os
import signal
import time

from novel_forge.api.authority_dependencies import authority_release_identity
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.provider_qualification import (
    D0QualificationAuthority,
    D0QualificationScheduler,
)
from novel_forge.storage.object_store import MinioObjectStore


def main() -> int:
    settings = IndustrialSettings.from_env()
    if settings.storage_authority != "postgresql" or not settings.database_url:
        raise RuntimeError("D0 worker requires PostgreSQL authority")
    build_id, commit_sha = authority_release_identity()
    worker_id = str(os.environ.get("NOVEL_FORGE_D0_WORKER_ID") or "integration-worker:d0")
    scheduler = D0QualificationScheduler(
        D0QualificationAuthority(
            settings.database_url,
            evidence_store=MinioObjectStore(settings),
            application_build_id=build_id,
            commit_sha=commit_sha,
            worker_id=worker_id,
        )
    )
    stopping = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    poll_seconds = max(0.1, float(os.environ.get("NOVEL_FORGE_AUTHORITY_POLL_SECONDS") or "1"))
    while not stopping:
        pending = scheduler.pending_operations()
        if not pending:
            time.sleep(poll_seconds)
            continue
        for operation_id, project_id in pending:
            scheduler.run_or_recover(operation_id=operation_id, project_id=project_id)
    return 0


def cli() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    cli()
