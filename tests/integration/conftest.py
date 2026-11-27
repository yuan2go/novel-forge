from __future__ import annotations

import os
from collections.abc import Iterator

import psycopg
from psycopg import sql
import pytest

from novel_forge.storage.migrations import run_migrations
from novel_forge.tools.backend_qualification_resources import (
    require_disposable_database_name,
)


_READ_ONLY_PREFLIGHT_OPTIONS = "-c default_transaction_read_only=on"


def require_disposable_test_database(database_name: object) -> str:
    """Validate the server-reported database identity without touching PostgreSQL."""
    try:
        return require_disposable_database_name(database_name)
    except ValueError as exc:
        raise AssertionError(str(exc)) from exc


def preflight_integration_database(database_url: str) -> str:
    """Resolve and validate the target through a read-only PostgreSQL session."""
    with psycopg.connect(
        database_url,
        autocommit=True,
        application_name="novel-forge-pytest-safety-preflight",
        connect_timeout=5,
        options=_READ_ONLY_PREFLIGHT_OPTIONS,
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT current_database(), current_setting('transaction_read_only')
                """
            )
            row = cursor.fetchone()
    if row is None or len(row) != 2 or str(row[1]).lower() != "on":
        raise AssertionError(
            "integration database safety preflight did not run read-only; "
            "refusing migrations and cleanup"
        )
    return require_disposable_test_database(row[0])


@pytest.fixture(scope="module", autouse=True)
def isolate_postgresql_integration_module() -> Iterator[None]:
    """Keep global Authority registries from leaking across test modules."""
    database_url = os.environ.get("NOVEL_FORGE_DATABASE_URL", "")
    if not database_url:
        yield
        return

    preflight_database_name = preflight_integration_database(database_url)
    status = run_migrations(database_url)
    if not status["ok"]:
        raise AssertionError(f"PostgreSQL migrations are incomplete: {status}")
    with psycopg.connect(database_url, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            row = cursor.fetchone()
            database_name = require_disposable_test_database(
                None if row is None else row[0]
            )
            if database_name != preflight_database_name:
                raise AssertionError(
                    "integration database identity changed after safety preflight; "
                    f"refusing cleanup for {database_name!r}"
                )
            cursor.execute(
                """
                SELECT tablename
                FROM pg_tables
                WHERE schemaname='public'
                  AND tablename <> 'nf_schema_migrations'
                ORDER BY tablename
                """
            )
            tables = [str(row[0]) for row in cursor.fetchall()]
            if tables:
                cursor.execute(
                    sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY CASCADE").format(
                        sql.SQL(", ").join(
                            sql.Identifier("public", table) for table in tables
                        )
                    )
                )
    yield
