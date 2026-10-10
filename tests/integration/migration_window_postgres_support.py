from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import uuid4
from pathlib import Path
import hashlib
import json
import shutil
import subprocess

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb

from novel_forge.storage.migrations import MIGRATIONS
from novel_forge.storage.migrations.runner import Migration, validate_migration_chain
from tests.integration.conftest import (
    preflight_integration_database,
    require_disposable_test_database,
)


PRE_WORKFLOW_MIGRATION_ID = "20260829_0103_book_opening_semantic_runtime_hardening"
WORKFLOW_MIGRATION_ID = "20260829_0104_book_opening_workflow_nodes"
_OWNED_MIGRATION_DATABASES: set[str] = set()


def _database_fingerprint(database_url):
    with psycopg.connect(database_url) as connection:
        identity = connection.execute("SELECT current_database(),oid FROM pg_database WHERE datname=current_database()").fetchone()
        cluster = connection.execute("SELECT system_identifier::text FROM pg_control_system()").fetchone()[0]
        tables = connection.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").fetchall()
        fingerprints = {}
        for (name,) in tables:
            rows = connection.execute(sql.SQL("SELECT to_jsonb(t)::text FROM {} t ORDER BY to_jsonb(t)::text").format(sql.Identifier(name))).fetchall()
            payload = json.dumps([row[0] for row in rows], separators=(",", ":")).encode()
            fingerprints[name] = {"rows": len(rows), "sha256": hashlib.sha256(payload).hexdigest()}
        return {"database": identity[0], "oid": identity[1], "cluster": cluster}, fingerprints


@contextmanager
def restored_generation_backup(database_url: str, *, backup_root: Path, execution_root: Path | None = None):
    preflight_integration_database(database_url)
    backup_root.mkdir(parents=True)
    original_identity, before = _database_fingerprint(database_url)
    dump = backup_root / "database.dump"
    commands = []
    def run(arguments):
        result = subprocess.run(arguments, capture_output=True, timeout=120, check=False)
        commands.append({"command": [argument.replace(database_url, "<owned-source-database>").replace(restored_url, "<owned-restored-database>") for argument in arguments], "exit_code": result.returncode})
        (backup_root / f"command-{len(commands)}.log").write_bytes(result.stdout + result.stderr)
        assert result.returncode == 0, result.stderr.decode(errors="replace")
    name = _temporary_database_name("generation_restore")
    restored_url = _database_url(database_url, name)
    admin_url = _database_url(database_url, "postgres")
    execution_files = {}
    if execution_root is not None:
        for path in sorted(execution_root.rglob("*")):
            if path.is_file():
                execution_files[str(path.relative_to(execution_root))] = hashlib.sha256(path.read_bytes()).hexdigest()
        assert execution_files
        shutil.copytree(execution_root, backup_root / "execution-directory")
    run(["pg_dump", "--format=custom", "--file=" + str(dump), database_url])
    with psycopg.connect(admin_url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        run(["pg_restore", "--exit-on-error", "--dbname=" + restored_url, str(dump)])
        restored_identity, after = _database_fingerprint(restored_url)
        assert original_identity != restored_identity and before == after
        if execution_root is not None:
            # WHY: Frozen receipts use original absolute paths; restore at that owned path.
            execution_root.rename(backup_root / "original-execution-directory")
            shutil.copytree(backup_root / "execution-directory", execution_root)
            assert execution_files == {str(path.relative_to(execution_root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in execution_root.rglob("*") if path.is_file()}
        report = {"contract_version": "generation-joint-restore-evidence.v1", "status": "PASS",
            "source": original_identity, "restored": restored_identity, "commands": commands,
            "dump_sha256": hashlib.sha256(dump.read_bytes()).hexdigest(), "tables": before,
            "execution_root": str(execution_root) if execution_root else None,
            "execution_files": execution_files, "artifact_store": "POSTGRES_AUTHORITY_ASSET_VERSIONS",
            "migration_identities": [{"migration_id":migration.migration_id,"down_revision":migration.down_revision} for migration in MIGRATIONS]}
        (backup_root / "restore-evidence.json").write_text(json.dumps(report, indent=2) + "\n")
        yield restored_url
    finally:
        with psycopg.connect(admin_url, autocommit=True) as connection:
            connection.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()", [name])
            connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


def _database_url(base_database_url: str, database_name: str) -> str:
    parameters = conninfo_to_dict(base_database_url)
    parameters["dbname"] = database_name
    return make_conninfo(**parameters)


def _temporary_database_name(prefix: str) -> str:
    normalized = "".join(
        character if character.isalnum() else "_" for character in prefix.lower()
    ).strip("_")
    if not normalized:
        raise AssertionError("temporary migration database prefix cannot be empty")
    database_name = f"{normalized[:20]}_{uuid4().hex}_test"
    return require_disposable_test_database(database_name)


def _migration_prefix(target_migration_id: str) -> tuple[Migration, ...]:
    validate_migration_chain()
    target_index = next(
        (
            index
            for index, migration in enumerate(MIGRATIONS)
            if migration.migration_id == target_migration_id
        ),
        None,
    )
    if target_index is None:
        raise AssertionError(f"unknown migration window target: {target_migration_id}")
    return MIGRATIONS[: target_index + 1]


def _apply_migrations_through(
    database_url: str,
    *,
    target_migration_id: str,
) -> None:
    migrations = _migration_prefix(target_migration_id)
    with (
        psycopg.connect(
            database_url,
            connect_timeout=5,
        ) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
            CREATE TABLE nf_schema_migrations (
                migration_id TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        for migration in migrations:
            blockers: list[str] = []
            for statement in migration.preflight_statements:
                cursor.execute(statement)
                for row in cursor.fetchall():
                    if int(row[1]):
                        blockers.append(f"{row[0]}={row[1]}")
            if blockers:
                raise AssertionError(
                    f"migration preflight blocked {migration.migration_id}: "
                    + ", ".join(blockers)
                )
            for statement in migration.upgrade_statements:
                cursor.execute(statement)
            cursor.execute(
                "INSERT INTO nf_schema_migrations(migration_id) VALUES (%s)",
                [migration.migration_id],
            )


def assert_database_at_migration(
    database_url: str,
    *,
    target_migration_id: str,
) -> None:
    expected = {
        migration.migration_id for migration in _migration_prefix(target_migration_id)
    }
    with (
        psycopg.connect(
            database_url,
            connect_timeout=5,
        ) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT migration_id FROM nf_schema_migrations")
        actual = {str(row[0]) for row in cursor.fetchall()}
    if actual != expected:
        raise AssertionError(
            "migration-window database drifted from its required head: "
            f"target={target_migration_id}, missing={sorted(expected - actual)}, "
            f"unexpected={sorted(actual - expected)}"
        )


@contextmanager
def disposable_database_at_migration(
    base_database_url: str,
    *,
    prefix: str,
    target_migration_id: str,
) -> Iterator[str]:
    """Create an exact, disposable migration-window database for one test."""

    preflight_integration_database(base_database_url)
    database_name = _temporary_database_name(prefix)
    admin_url = _database_url(base_database_url, "postgres")
    test_url = _database_url(base_database_url, database_name)
    created = False
    try:
        with psycopg.connect(
            admin_url,
            autocommit=True,
            connect_timeout=5,
        ) as connection:
            connection.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
            )
        created = True
        _OWNED_MIGRATION_DATABASES.add(test_url)
        _apply_migrations_through(
            test_url,
            target_migration_id=target_migration_id,
        )
        assert_database_at_migration(
            test_url,
            target_migration_id=target_migration_id,
        )
        yield test_url
    finally:
        _OWNED_MIGRATION_DATABASES.discard(test_url)
        if created:
            with psycopg.connect(
                admin_url,
                autocommit=True,
                connect_timeout=5,
            ) as connection:
                connection.execute(
                    """
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname=%s AND pid<>pg_backend_pid()
                    """,
                    [database_name],
                )
                connection.execute(
                    sql.SQL("DROP DATABASE {}").format(sql.Identifier(database_name))
                )


def _fixture_table_rows(
    connection: psycopg.Connection,
) -> dict[str, tuple[tuple[str, ...], tuple[str, ...], list[tuple[Any, ...]]]]:
    tables = connection.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' AND table_type='BASE TABLE' "
        "AND table_name<>'nf_schema_migrations' ORDER BY table_name"
    ).fetchall()
    captured = {}
    for (table_name,) in tables:
        metadata = connection.execute(
            "SELECT column_name,data_type FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
            [table_name],
        ).fetchall()
        columns = tuple(str(row[0]) for row in metadata)
        json_columns = tuple(
            str(row[0]) for row in metadata if row[1] in {"json", "jsonb"}
        )
        ordering = (
            sql.SQL(" ORDER BY fencing_token")
            if table_name == "authority_lease_acquisition"
            else sql.SQL("")
        )
        rows = connection.execute(
            sql.SQL("SELECT {} FROM {}{}").format(
                sql.SQL(",").join(map(sql.Identifier, columns)),
                sql.Identifier(table_name),
                ordering,
            )
        ).fetchall()
        if rows:
            captured[str(table_name)] = (columns, json_columns, rows)
    return captured


def _insert_historical_fixture_rows(
    connection: psycopg.Connection,
    tables: dict[str, tuple[tuple[str, ...], tuple[str, ...], list[tuple[Any, ...]]]],
) -> None:
    # WHY: SQL fixture construction obeys historical guards; dependencies can include
    # trigger lookups beyond declared FKs, so each unsuccessful insert is rolled back.
    pending = [
        (name, columns, json_columns, row)
        for name, (columns, json_columns, rows) in tables.items()
        for row in rows
    ]
    deferred_generation_links = []
    while pending:
        remaining = []
        errors = {}
        for name, columns, json_columns, row in pending:
            connection.execute("SAVEPOINT historical_fixture_row")
            try:
                inserted_row = list(row)
                generation_link = None
                lease_release = None
                if (
                    name == "authority_story_planning_generation"
                    and row[columns.index("candidate_asset_version_id")] is not None
                ):
                    # WHY: The generation must exist before its candidate can refer
                    # back to it; link that candidate after both SQL rows exist.
                    generation_link = (
                        row[columns.index("generation_id")],
                        row[columns.index("candidate_asset_version_id")],
                    )
                    inserted_row[columns.index("candidate_asset_version_id")] = None
                if (
                    name == "authority_lease_acquisition"
                    and row[columns.index("status")] != "HELD"
                ):
                    # WHY: Historical lease construction follows the original
                    # HELD -> terminal guard rather than inserting a terminal lease.
                    lease_release = {
                        column: row[columns.index(column)]
                        for column in ("status", "released_at", "release_reason")
                    }
                    inserted_row[columns.index("status")] = "HELD"
                    inserted_row[columns.index("released_at")] = None
                    inserted_row[columns.index("release_reason")] = ""
                values = [
                    Jsonb(value)
                    if column in json_columns and value is not None
                    else value
                    for column, value in zip(columns, inserted_row, strict=True)
                ]
                connection.execute(
                    sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                        sql.Identifier(name),
                        sql.SQL(",").join(map(sql.Identifier, columns)),
                        sql.SQL(",").join(sql.Placeholder() for _ in columns),
                    ),
                    values,
                )
                if lease_release is not None:
                    connection.execute(
                        "UPDATE authority_lease_acquisition SET status=%s,released_at=%s,release_reason=%s WHERE lease_id=%s",
                        [
                            lease_release["status"],
                            lease_release["released_at"],
                            lease_release["release_reason"],
                            row[columns.index("lease_id")],
                        ],
                    )
                if generation_link is not None:
                    deferred_generation_links.append(generation_link)
            except psycopg.Error as error:
                connection.execute("ROLLBACK TO SAVEPOINT historical_fixture_row")
                remaining.append((name, columns, json_columns, row))
                errors[name] = str(error).splitlines()[0]
            finally:
                connection.execute("RELEASE SAVEPOINT historical_fixture_row")
        if len(remaining) == len(pending):
            raise AssertionError(
                f"historical fixture dependencies cannot be satisfied: {errors}"
            )
        pending = remaining
    for generation_id, candidate_version_id in deferred_generation_links:
        connection.execute(
            "UPDATE authority_story_planning_generation SET candidate_asset_version_id=%s WHERE generation_id=%s",
            [candidate_version_id, generation_id],
        )


def _advance_fixture_sequences(connection: psycopg.Connection) -> None:
    columns = connection.execute(
        "SELECT table_name,column_name,pg_get_serial_sequence(table_name,column_name) "
        "FROM information_schema.columns WHERE table_schema='public' "
        "AND (column_default LIKE 'nextval(%' OR is_identity='YES')"
    ).fetchall()
    for table_name, column_name, sequence in columns:
        if sequence is None:
            continue
        maximum = connection.execute(
            sql.SQL("SELECT MAX({}) FROM {}").format(
                sql.Identifier(column_name), sql.Identifier(table_name)
            )
        ).fetchone()[0]
        if maximum is not None:
            connection.execute("SELECT setval(%s,%s,true)", [sequence, maximum])


def materialize_historical_fixture_at_migration(
    database_url: str,
    *,
    target_migration_id: str,
) -> dict[str, tuple[tuple[str, ...], tuple[str, ...], list[tuple[Any, ...]]]]:
    """Construct historical SQL data; this does not execute current Runtime on old DDL.

    Current-schema Runtime only produces controlled fixture data before this boundary.
    Its compatible columns become historical SQL rows under all original constraints.
    Later-only tables remain separate until the migration upgrade completes.
    """
    from novel_forge.storage.migrations import LATEST_MIGRATION_ID

    assert_database_at_migration(database_url, target_migration_id=LATEST_MIGRATION_ID)
    parameters = conninfo_to_dict(database_url)
    database_name = require_disposable_test_database(parameters["dbname"])
    assert database_url in _OWNED_MIGRATION_DATABASES, (
        "historical fixture database is not owned by this test"
    )
    with psycopg.connect(database_url) as connection:
        current = _fixture_table_rows(connection)
    # WHY: Recreating this exact owned disposable database avoids holding hundreds
    # of DDL locks while projecting current fixture rows into the old schema.
    with psycopg.connect(
        _database_url(database_url, "postgres"), autocommit=True
    ) as connection:
        connection.execute(
            sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                sql.Identifier(database_name)
            )
        )
        connection.execute(
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
        )
    _apply_migrations_through(database_url, target_migration_id=target_migration_id)
    assert_database_at_migration(database_url, target_migration_id=target_migration_id)
    with psycopg.connect(database_url) as connection:
        if target_migration_id == PRE_WORKFLOW_MIGRATION_ID:
            assert connection.execute(
                "SELECT to_regclass('authority_runtime_dispatch_control'), "
                "to_regclass('authority_book_opening_legacy_snapshot_entitlement')"
            ).fetchone() == (None, None)
        historical_columns = connection.execute(
            "SELECT table_name,column_name FROM information_schema.columns "
            "WHERE table_schema='public' ORDER BY table_name,ordinal_position"
        ).fetchall()
        allowed: dict[str, list[str]] = {}
        for table_name, column_name in historical_columns:
            allowed.setdefault(str(table_name), []).append(str(column_name))
        historical = {}
        later_tables = {}
        for name, (columns, json_columns, rows) in current.items():
            if name not in allowed:
                later_tables[name] = (columns, json_columns, rows)
                continue
            compatible = tuple(column for column in allowed[name] if column in columns)
            indexes = tuple(columns.index(column) for column in compatible)
            historical[name] = (
                compatible,
                tuple(column for column in json_columns if column in compatible),
                [tuple(row[index] for index in indexes) for row in rows],
            )
        _insert_historical_fixture_rows(connection, historical)
        _advance_fixture_sequences(connection)
        actual = _fixture_table_rows(connection)
        for name, (columns, _, rows) in historical.items():
            actual_columns, _, actual_rows = actual[name]
            indexes = tuple(actual_columns.index(column) for column in columns)
            projected_rows = [
                tuple(row[index] for index in indexes) for row in actual_rows
            ]
            assert sorted(map(repr, projected_rows)) == sorted(map(repr, rows)), name
    return later_tables


def restore_post_window_fixture_tables(
    database_url: str,
    tables: dict[str, tuple[tuple[str, ...], tuple[str, ...], list[tuple[Any, ...]]]],
) -> None:
    """Restore only later-schema fixture inputs after the historical window is upgraded."""
    from novel_forge.storage.migrations import LATEST_MIGRATION_ID

    assert_database_at_migration(database_url, target_migration_id=LATEST_MIGRATION_ID)
    with psycopg.connect(database_url) as connection:
        for name in tables:
            count = connection.execute(
                sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(name))
            ).fetchone()[0]
            assert count == 0, f"upgrade already populated later fixture table: {name}"
        _insert_historical_fixture_rows(connection, tables)
        _advance_fixture_sequences(connection)
