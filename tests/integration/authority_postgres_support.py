from __future__ import annotations

import os
from contextlib import contextmanager
from collections.abc import Iterator
from uuid import uuid4

import psycopg

from novel_forge.storage.migrations import run_migrations


DATABASE_URL = os.environ.get(
    "NOVEL_FORGE_DATABASE_URL",
    "postgresql://novel_forge@127.0.0.1:55432/novel_forge_authority_test",
)


def connect() -> psycopg.Connection:
    return psycopg.connect(DATABASE_URL, connect_timeout=3)


@contextmanager
def transaction() -> Iterator[psycopg.Connection]:
    connection = connect()
    try:
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def ensure_migrated() -> None:
    status = run_migrations(DATABASE_URL)
    if not status["ok"]:
        raise AssertionError(f"PostgreSQL migrations are incomplete: {status}")


def identifier(prefix: str) -> str:
    return f"{prefix}-{uuid4()}"


def insert_definition(cursor: psycopg.Cursor, name: str) -> None:
    cursor.execute(
        """
        INSERT INTO authority_operation_definition (
            name,
            definition_version,
            family,
            enabled,
            command_schema,
            result_schema,
            policy,
            completion_contract
        )
        VALUES (%s, '1.0.0', 'ops', TRUE, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb)
        """,
        [name],
    )


def insert_operation(
    cursor: psycopg.Cursor,
    *,
    operation_id: str,
    definition_name: str,
    project_id: str,
    status: str = "ADMITTED",
    root_operation_id: str | None = None,
    parent_operation_id: str | None = None,
    causation_operation_id: str | None = None,
) -> None:
    cursor.execute(
        """
        INSERT INTO authority_operation (
            operation_id,
            definition_name,
            definition_version,
            project_id,
            status,
            parent_operation_id,
            root_operation_id,
            causation_operation_id,
            idempotency_scope,
            idempotency_key,
            request_digest,
            definition_snapshot,
            completion_contract_snapshot,
            policy_snapshot
        )
        VALUES (
            %s, %s, '1.0.0', %s, %s, %s, %s, %s,
            %s, %s, %s, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb
        )
        """,
        [
            operation_id,
            definition_name,
            project_id,
            status,
            parent_operation_id,
            root_operation_id or operation_id,
            causation_operation_id,
            f"project:{project_id}",
            operation_id,
            f"digest:{operation_id}",
        ],
    )
