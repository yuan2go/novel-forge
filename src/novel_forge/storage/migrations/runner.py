from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .versions import VERSION_MODULES


@dataclass(frozen=True)
class Migration:
    migration_id: str
    down_revision: str | None
    upgrade_statements: tuple[str, ...]


MIGRATIONS = tuple(
    Migration(
        migration_id=str(module.MIGRATION_ID),
        down_revision=module.DOWN_REVISION,
        upgrade_statements=tuple(module.UPGRADE_STATEMENTS),
    )
    for module in VERSION_MODULES
)
LATEST_MIGRATION_ID = MIGRATIONS[-1].migration_id
MIGRATION_STATEMENTS = [statement for migration in MIGRATIONS for statement in migration.upgrade_statements]


def validate_migration_chain(migrations: tuple[Migration, ...] = MIGRATIONS) -> None:
    seen: set[str] = set()
    previous: str | None = None
    for migration in migrations:
        if migration.migration_id in seen:
            raise ValueError(f"duplicate migration id: {migration.migration_id}")
        if migration.down_revision != previous:
            raise ValueError(
                f"migration chain break at {migration.migration_id}: "
                f"expected down_revision {previous!r}, got {migration.down_revision!r}"
            )
        seen.add(migration.migration_id)
        previous = migration.migration_id


def pending_migrations(applied_ids: set[str], migrations: tuple[Migration, ...] = MIGRATIONS) -> list[Migration]:
    validate_migration_chain(migrations)
    return [migration for migration in migrations if migration.migration_id not in applied_ids]


def run_migrations(database_url: str) -> dict[str, Any]:
    validate_migration_chain()
    with _connect(database_url) as connection:
        with connection.cursor() as cursor:
            _ensure_migration_table(cursor)
            applied = _applied_migration_rows(cursor)
            applied_ids = {str(row["migration_id"]) for row in applied}
            for migration in pending_migrations(applied_ids):
                for statement in migration.upgrade_statements:
                    cursor.execute(statement)
                cursor.execute(
                    "INSERT INTO nf_schema_migrations (migration_id) VALUES (%s) ON CONFLICT (migration_id) DO NOTHING",
                    [migration.migration_id],
                )
            cursor.execute("SELECT migration_id, applied_at FROM nf_schema_migrations ORDER BY applied_at ASC")
            rows = cursor.fetchall()
    applied_after = [{"migration_id": row[0], "applied_at": str(row[1])} for row in rows]
    return _status_from_rows(applied_after)


def get_migration_status(database_url: str) -> dict[str, Any]:
    validate_migration_chain()
    with _connect(database_url) as connection:
        with connection.cursor() as cursor:
            _ensure_migration_table(cursor)
            applied = _applied_migration_rows(cursor)
    return _status_from_rows(applied)


def _status_from_rows(applied: list[dict[str, str]]) -> dict[str, Any]:
    applied_ids = {row["migration_id"] for row in applied}
    missing = [migration.migration_id for migration in MIGRATIONS if migration.migration_id not in applied_ids]
    extra = sorted(applied_ids - {migration.migration_id for migration in MIGRATIONS})
    return {
        "current": LATEST_MIGRATION_ID,
        "applied": applied,
        "available": [migration.migration_id for migration in MIGRATIONS],
        "missing": missing,
        "extra": extra,
        "ok": not missing and not extra,
    }


def _ensure_migration_table(cursor: Any) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS nf_schema_migrations (
            migration_id TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )


def _applied_migration_rows(cursor: Any) -> list[dict[str, str]]:
    cursor.execute("SELECT migration_id, applied_at FROM nf_schema_migrations ORDER BY applied_at ASC")
    rows = cursor.fetchall()
    return [{"migration_id": row[0], "applied_at": str(row[1])} for row in rows]


def _connect(database_url: str):
    try:
        import psycopg
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency-gated path
        raise RuntimeError("PostgreSQL support requires the optional dependency: psycopg[binary]") from exc
    return psycopg.connect(database_url, connect_timeout=1)
