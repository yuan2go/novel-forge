from __future__ import annotations

import os
from contextlib import contextmanager
from collections.abc import Iterator
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

from novel_forge.storage.migrations import run_migrations


DATABASE_URL = os.environ.get(
    "NOVEL_FORGE_DATABASE_URL",
    "postgresql://novel_forge:novel_forge@127.0.0.1:55432/novel_forge_authority_test",
)


def connect() -> psycopg.Connection:
    return psycopg.connect(DATABASE_URL, connect_timeout=3)


@contextmanager
def transaction() -> Iterator[psycopg.Connection]:
    connection = connect()
    try:
        yield connection
        connection.commit()
    except Exception:
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
    workspace_id: str = "legacy-unknown",
    command_payload: dict[str, object] | None = None,
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
            workspace_id,
            status,
            parent_operation_id,
            root_operation_id,
            causation_operation_id,
            idempotency_scope,
            idempotency_key,
            request_digest,
            command_payload,
            definition_snapshot,
            completion_contract_snapshot,
            policy_snapshot
        )
        VALUES (
            %s, %s, '1.0.0', %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb
        )
        """,
        [
            operation_id,
            definition_name,
            project_id,
            workspace_id,
            status,
            parent_operation_id,
            root_operation_id or operation_id,
            causation_operation_id,
            f"project:{project_id}",
            operation_id,
            f"digest:{operation_id}",
            Jsonb(command_payload or {}),
        ],
    )


def seed_authority_project_book(
    *,
    project_id: str,
    book_id: str,
    workspace_id: str | None = None,
    production_profile: dict | None = None,
    seed_project: bool = True,
) -> None:
    """Create the minimum authoritative Project/Workspace/Book scope fixture."""
    workspace_id = workspace_id or f"workspace:{project_id}"
    definition_name = identifier("scope-fixture-definition")
    operation_id = identifier("scope-fixture-operation")
    project_asset_id = f"scope-fixture:project:{project_id}"
    workspace_asset_id = f"scope-fixture:workspace:{workspace_id}"
    book_asset_id = f"scope-fixture:book:{book_id}"
    with transaction() as connection, connection.cursor() as cursor:
        insert_definition(cursor, definition_name)
        insert_operation(
            cursor,
            operation_id=operation_id,
            definition_name=definition_name,
            project_id=project_id,
            status="SUCCEEDED",
        )
        for asset_id, asset_type in (
            (project_asset_id, "project"),
            (workspace_asset_id, "workspace"),
            (book_asset_id, "book"),
        ):
            if asset_type == "project" and not seed_project:
                continue
            cursor.execute(
                "INSERT INTO authority_asset(asset_id, project_id, asset_type) VALUES (%s, %s, %s)",
                [asset_id, project_id, asset_type],
            )
            cursor.execute(
                """
                INSERT INTO authority_asset_version(
                    asset_version_id, asset_id, version_number, lifecycle,
                    eligibility, governance, content, content_hash, schema_version
                ) VALUES (%s, %s, 1, 'ACTIVE', 'ELIGIBLE', 'CLEAR', %s, %s, %s)
                """,
                [
                    f"{asset_id}:v1",
                    asset_id,
                    Jsonb({"project_id": project_id, "book_id": book_id}),
                    f"sha256:{asset_id}",
                    f"{asset_type}-authority.v1",
                ],
            )
        if seed_project:
            cursor.execute(
                """
                INSERT INTO authority_project(
                    project_id, primary_workspace_id, title, status, stage, health,
                    current_asset_version_id, created_by_operation_id, last_operation_id
                ) VALUES (%s, %s, %s, 'ACTIVE', 'PLANNING', 'HEALTHY', %s, %s, %s)
                """,
                [
                    project_id,
                    workspace_id,
                    project_id,
                    f"{project_asset_id}:v1",
                    operation_id,
                    operation_id,
                ],
            )
        cursor.execute(
            """
            INSERT INTO authority_workspace(
                workspace_id, project_id, book_id, status, current_asset_version_id,
                created_by_operation_id, last_operation_id
            ) VALUES (%s, %s, %s, 'ACTIVE', %s, %s, %s)
            """,
            [
                workspace_id,
                project_id,
                book_id,
                f"{workspace_asset_id}:v1",
                operation_id,
                operation_id,
            ],
        )
        cursor.execute(
            """
            INSERT INTO authority_book(
                book_id, project_id, workspace_id, principal_id, service_identity,
                book_scope, production_profile, runtime_policy, release_identity,
                status, current_book_asset_version_id,
                created_by_operation_id, last_operation_id
            ) VALUES (%s, %s, %s, 'integration-operator', 'integration-service',
                      %s, %s, '{}'::jsonb, 'integration-release',
                      'DESIGN_PENDING', %s, %s, %s)
            """,
            [
                book_id,
                project_id,
                workspace_id,
                Jsonb({"book_id": book_id}),
                Jsonb(production_profile or {}),
                f"{book_asset_id}:v1",
                operation_id,
                operation_id,
            ],
        )
