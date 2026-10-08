from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .versions import VERSION_MODULES


@dataclass(frozen=True)
class Migration:
    migration_id: str
    down_revision: str | None
    upgrade_statements: tuple[str, ...]
    downgrade_statements: tuple[str, ...]
    strategy: str = "REVERSIBLE_WHEN_DECLARED"
    preflight_statements: tuple[str, ...] = ()
    forward_fix: str = ""
    backup_required: bool = False


MIGRATIONS = tuple(
    Migration(
        migration_id=str(module.MIGRATION_ID),
        down_revision=module.DOWN_REVISION,
        upgrade_statements=tuple(module.UPGRADE_STATEMENTS),
        downgrade_statements=tuple(getattr(module, "DOWNGRADE_STATEMENTS", ())),
        strategy=(
            "FORWARD_ONLY"
            if bool(getattr(module, "FORWARD_ONLY", False))
            else "REVERSIBLE_WHEN_DECLARED"
        ),
        preflight_statements=tuple(getattr(module, "PREFLIGHT_STATEMENTS", ())),
        forward_fix=str(getattr(module, "FORWARD_FIX", "")),
        backup_required=bool(getattr(module, "BACKUP_REQUIRED", False)),
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
    known = [migration.migration_id for migration in migrations]
    extra = sorted(applied_ids - set(known))
    if extra:
        raise ValueError(f"MIGRATION_HISTORY_FOREIGN: {', '.join(extra)}")
    prefix_length = len(applied_ids)
    if applied_ids != set(known[:prefix_length]):
        raise ValueError("MIGRATION_HISTORY_DISCONTINUOUS: applied identities must form the registered prefix")
    return list(migrations[prefix_length:])


def downgrade_plan(target_revision: str | None, applied_ids: set[str], migrations: tuple[Migration, ...] = MIGRATIONS) -> list[Migration]:
    validate_migration_chain(migrations)
    known_ids = [migration.migration_id for migration in migrations]
    if target_revision is not None and target_revision not in known_ids:
        raise ValueError(f"unknown target_revision: {target_revision}")
    target_index = -1 if target_revision is None else known_ids.index(target_revision)
    candidates = [migration for migration in migrations[target_index + 1 :] if migration.migration_id in applied_ids]
    return list(reversed(candidates))


def run_migrations(database_url: str) -> dict[str, Any]:
    validate_migration_chain()
    with _connect(database_url) as connection:
        with connection.cursor() as cursor:
            _ensure_migration_table(cursor)
            applied = _applied_migration_rows(cursor)
            applied_ids = {str(row["migration_id"]) for row in applied}
            for migration in pending_migrations(applied_ids):
                _run_preflight(cursor, migration)
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


def downgrade_migrations(database_url: str, *, target_revision: str | None, execute: bool = False) -> dict[str, Any]:
    validate_migration_chain()
    with _connect(database_url) as connection:
        with connection.cursor() as cursor:
            _ensure_migration_table(cursor)
            applied = _applied_migration_rows(cursor)
            applied_ids = {str(row["migration_id"]) for row in applied}
            plan = downgrade_plan(target_revision, applied_ids)
            statements = [statement for migration in plan for statement in migration.downgrade_statements]
            missing_downgrade = [migration.migration_id for migration in plan if not migration.downgrade_statements]
            if execute and missing_downgrade:
                raise ValueError(f"missing downgrade statements for: {', '.join(missing_downgrade)}")
            if execute:
                for migration in plan:
                    for statement in migration.downgrade_statements:
                        cursor.execute(statement)
                    if migration.migration_id != MIGRATIONS[0].migration_id:
                        cursor.execute("DELETE FROM nf_schema_migrations WHERE migration_id = %s", [migration.migration_id])
                if target_revision is None:
                    applied_after: list[dict[str, str]] = []
                else:
                    _ensure_migration_table(cursor)
                    applied_after = _applied_migration_rows(cursor)
            else:
                applied_after = applied
    status = _status_from_rows(applied_after)
    status.update(
        {
            "target_revision": target_revision,
            "execute": execute,
            "downgrade_plan": [migration.migration_id for migration in plan],
            "downgrade_statement_count": len(statements),
            "destructive": any("DROP TABLE" in statement.upper() for statement in statements),
        }
    )
    return status


def get_migration_status(database_url: str) -> dict[str, Any]:
    validate_migration_chain()
    with _connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute("SELECT to_regclass('nf_schema_migrations')")
            applied = _applied_migration_rows(cursor) if cursor.fetchone()[0] is not None else []
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


def _run_preflight(cursor: Any, migration: Migration) -> None:
    blockers: list[str] = []
    for statement in migration.preflight_statements:
        cursor.execute(statement)
        for row in cursor.fetchall():
            code = str(row[0])
            count = int(row[1])
            if count:
                blockers.append(f"{code}={count}")
    if blockers:
        raise RuntimeError(
            f"migration preflight blocked {migration.migration_id}: "
            + ", ".join(blockers)
            + (f"; forward fix: {migration.forward_fix}" if migration.forward_fix else "")
        )
