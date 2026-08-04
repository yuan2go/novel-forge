"""Container health probe for PostgreSQL-backed Authority worker heartbeats."""
from __future__ import annotations

import argparse
import json
import os
from typing import Any

from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.storage.database_runtime import (
    close_all_database_runtimes,
    get_database_runtime,
)
from novel_forge.storage.migrations import get_migration_status


def worker_health(
    database_url: str,
    *,
    worker_kind: str,
    worker_id: str,
    freshness_seconds: int = 60,
) -> dict[str, Any]:
    migration = get_migration_status(database_url)
    runtime = get_database_runtime(database_url)
    with runtime.connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT status, last_poll_at, active_attempts,
                   completed_operation_count, failed_operation_count,
                   database_status, drain_status,
                   last_heartbeat_at, active_operation_id, active_attempt_id,
                   lease_count, completed_batch_count,
                   updated_at >= NOW() - (%s * INTERVAL '1 second')
            FROM authority_worker_health_projection
            WHERE worker_kind=%s AND worker_id=%s
            """,
            [freshness_seconds, worker_kind, worker_id],
        )
        row = cursor.fetchone()
    ready = bool(
        migration["ok"]
        and row is not None
        and bool(row[12])
        and str(row[0]) in {"READY", "BUSY", "DEGRADED"}
        and str(row[5]) == "READY"
        and str(row[6]) == "ACCEPTING"
    )
    return {
        "status": "ready" if ready else "not_ready",
        "worker_id": worker_id,
        "runtime_group": worker_kind,
        "last_heartbeat": str(row[7]) if row else "",
        "last_poll": str(row[1]) if row else "",
        "active_attempts": int(row[2]) if row else 0,
        "completed_count": int(row[3]) if row else 0,
        "failed_count": int(row[4]) if row else 0,
        "database_status": str(row[5]) if row else "UNAVAILABLE",
        "drain_status": str(row[6]) if row else "UNKNOWN",
        "active_operation_id": str(row[8]) if row and row[8] else "",
        "active_attempt_id": str(row[9]) if row and row[9] else "",
        "lease_count": int(row[10]) if row else 0,
        "completed_batch_count": int(row[11]) if row else 0,
        "migration_head": migration["current"],
        "migration_chain_current": migration["ok"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker-kind", required=True)
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--freshness-seconds", type=int, default=60)
    args = parser.parse_args(argv)
    settings = IndustrialSettings.from_env()
    if settings.storage_authority != "postgresql" or not settings.database_url:
        return 1
    try:
        result = worker_health(
            settings.database_url,
            worker_kind=args.worker_kind,
            worker_id=args.worker_id,
            freshness_seconds=args.freshness_seconds,
        )
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "ready" else 1
    finally:
        close_all_database_runtimes()


if __name__ == "__main__":
    raise SystemExit(main())
