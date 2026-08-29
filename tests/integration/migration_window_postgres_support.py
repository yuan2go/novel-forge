from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from novel_forge.storage.migrations import MIGRATIONS
from novel_forge.storage.migrations.runner import Migration, validate_migration_chain
from tests.integration.conftest import (
    preflight_integration_database,
    require_disposable_test_database,
)


PRE_WORKFLOW_MIGRATION_ID = "20260829_0103_book_opening_semantic_runtime_hardening"
WORKFLOW_MIGRATION_ID = "20260829_0104_book_opening_workflow_nodes"


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
