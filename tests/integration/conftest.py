from __future__ import annotations

import os
from collections.abc import Iterator

import psycopg
from psycopg import sql
import pytest

from novel_forge.storage.migrations import run_migrations


@pytest.fixture(scope="module", autouse=True)
def isolate_postgresql_integration_module() -> Iterator[None]:
    """Keep global Authority registries from leaking across test modules."""
    database_url = os.environ.get("NOVEL_FORGE_DATABASE_URL", "")
    if not database_url:
        yield
        return

    status = run_migrations(database_url)
    if not status["ok"]:
        raise AssertionError(f"PostgreSQL migrations are incomplete: {status}")
    with psycopg.connect(database_url, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            database_name = str(cursor.fetchone()[0])
            if not database_name.endswith("_test"):
                raise AssertionError(
                    "integration module isolation requires a database ending in _test; "
                    f"refusing to truncate {database_name!r}"
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
