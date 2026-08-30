from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from novel_forge.storage.migrations import (
    LATEST_MIGRATION_ID,
    MIGRATIONS,
    run_migrations,
)
from tests.integration.authority_postgres_support import DATABASE_URL
from tests.integration.test_book_opening_legacy_reconciliation_postgres import (
    _seed_opening,
)


RECOVERY_MIGRATION_ID = "20260828_0102_book_opening_recovery_closure"
WORKFLOW_MIGRATION_ID = "20260829_0104_book_opening_workflow_nodes"


def _database_url(database_name: str) -> str:
    parameters = conninfo_to_dict(DATABASE_URL)
    parameters["dbname"] = database_name
    return make_conninfo(**parameters)


def _bind_v2_execution_history(cursor: psycopg.Cursor, legacy: dict[str, str]) -> None:
    """Seed the already-qualified 0103 history that 0104 must not rewrite."""

    execution_id = f"book-opening-execution:legacy:{legacy['opening_run_id']}"
    cursor.execute(
        """
        SELECT opening.frozen_request_digest,job.input_hash
        FROM authority_book_opening_run AS opening
        JOIN authority_runtime_job AS job ON job.runtime_job_id=%s
        WHERE opening.opening_run_id=%s
        """,
        [legacy["runtime_job_id"], legacy["opening_run_id"]],
    )
    frozen_request_digest, input_hash = cursor.fetchone()
    cursor.execute(
        """
        INSERT INTO authority_book_opening_execution(
            opening_execution_id,opening_run_id,generation,runtime_job_id,
            current_attempt_id,current_lease_id,current_worker_id,
            current_fencing_token,lifecycle,frozen_request_digest,
            input_snapshot_hash,policy_snapshot_hash,authority_contract_hash,
            version,started_at
        ) VALUES (%s,%s,1,%s,%s,%s,'legacy-worker',1,'RUNNING',%s,%s,%s,%s,
                  0,'2026-08-01T00:00:00Z')
        """,
        [
            execution_id,
            legacy["opening_run_id"],
            legacy["runtime_job_id"],
            legacy["attempt_id"],
            legacy["lease_id"],
            frozen_request_digest,
            input_hash,
            "sha256:" + "7" * 64,
            "sha256:" + "8" * 64,
        ],
    )
    cursor.execute(
        """
        UPDATE authority_book_opening_run
        SET execution_contract_version='book-opening-execution-v2',
            recovery_state='READY',current_execution_id=%s,
            current_execution_generation=1
        WHERE opening_run_id=%s
        """,
        [execution_id, legacy["opening_run_id"]],
    )


@pytest.fixture()
def v2_legacy_database() -> Iterator[tuple[str, dict[str, str]]]:
    database_name = f"nf_opening_workflow_v2_{uuid4().hex}_test"[:63]
    admin_url = _database_url("postgres")
    test_url = _database_url(database_name)
    with psycopg.connect(admin_url, autocommit=True) as connection:
        connection.execute(
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
        )
    try:
        with psycopg.connect(test_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE nf_schema_migrations (
                    migration_id TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            for migration in MIGRATIONS:
                if migration.migration_id == RECOVERY_MIGRATION_ID:
                    break
                for statement in migration.upgrade_statements:
                    cursor.execute(statement)
                cursor.execute(
                    "INSERT INTO nf_schema_migrations(migration_id) VALUES (%s)",
                    [migration.migration_id],
                )
            legacy = _seed_opening(
                cursor,
                suffix="workflow-v2-preservation",
                with_runtime="active",
            )
            # Flush 0101 deferred relationship checks before any later
            # migration performs ALTER TABLE. PostgreSQL intentionally rejects
            # DDL while this transaction still owns pending trigger events.
            connection.commit()
            reached_workflow_migration = False
            for migration in MIGRATIONS:
                if migration.migration_id == WORKFLOW_MIGRATION_ID:
                    reached_workflow_migration = True
                    break
                cursor.execute(
                    "SELECT EXISTS(SELECT 1 FROM nf_schema_migrations "
                    "WHERE migration_id=%s)",
                    [migration.migration_id],
                )
                if bool(cursor.fetchone()[0]):
                    continue
                for statement in migration.preflight_statements:
                    cursor.execute(statement)
                for statement in migration.upgrade_statements:
                    cursor.execute(statement)
                cursor.execute(
                    "INSERT INTO nf_schema_migrations(migration_id) VALUES (%s)",
                    [migration.migration_id],
                )
            assert reached_workflow_migration is True
            _bind_v2_execution_history(cursor, legacy)
        yield test_url, legacy
    finally:
        with psycopg.connect(admin_url, autocommit=True) as connection:
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


def _legacy_history(database_url: str, opening_run_id: str) -> tuple[object, ...]:
    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            """
            SELECT
                opening.lifecycle,
                opening.version,
                opening.execution_contract_version,
                opening.current_execution_id,
                opening.current_execution_generation,
                opening.current_checkpoint_id,
                opening.current_checkpoint_sequence,
                opening.current_checkpoint_hash,
                opening.recovery_state,
                opening.result,
                opening.failure,
                execution.opening_execution_id,
                execution.generation,
                execution.predecessor_execution_id,
                execution.predecessor_generation,
                execution.recovery_intent_id,
                execution.runtime_job_id,
                execution.lifecycle,
                execution.current_attempt_id,
                execution.current_lease_id,
                execution.current_worker_id,
                execution.current_fencing_token,
                execution.version,
                job.status,
                job.attempt_count,
                job.current_attempt_id,
                job.current_fencing_token,
                job.result_hash,
                job.last_error,
                attempt.status,
                attempt.fencing_token,
                lease.status,
                lease.fencing_token
            FROM authority_book_opening_run AS opening
            JOIN authority_book_opening_execution AS execution
              ON execution.opening_execution_id=opening.current_execution_id
            JOIN authority_runtime_job AS job
              ON job.runtime_job_id=execution.runtime_job_id
            JOIN authority_runtime_job_attempt AS attempt
              ON attempt.attempt_id=job.current_attempt_id
            JOIN authority_runtime_job_lease AS lease
              ON lease.lease_id=attempt.lease_id
            WHERE opening.opening_run_id=%s
            """,
            [opening_run_id],
        ).fetchone()
    assert row is not None
    return tuple(row)


def test_0104_upgrade_does_not_rewrite_v2_opening_execution_history(
    v2_legacy_database: tuple[str, dict[str, str]],
) -> None:
    database_url, legacy = v2_legacy_database
    before = _legacy_history(database_url, legacy["opening_run_id"])

    status = run_migrations(database_url)
    assert status["ok"] is True
    assert status["current"] == LATEST_MIGRATION_ID
    assert WORKFLOW_MIGRATION_ID in {
        item["migration_id"] for item in status["applied"]
    }
    assert _legacy_history(database_url, legacy["opening_run_id"]) == before

    with psycopg.connect(database_url) as connection:
        defaults = connection.execute(
            """
            SELECT column_name,column_default
            FROM information_schema.columns
            WHERE table_schema='public'
              AND table_name='authority_book_opening_run'
              AND column_name IN (
                  'workflow_contract_version',
                  'workflow_graph_revision',
                  'workflow_graph_hash'
              )
            ORDER BY column_name
            """
        ).fetchall()
        compatibility = connection.execute(
            """
            SELECT opening.workflow_contract_version,
                   opening.current_workflow_node_id,
                   opening.workflow_graph_revision,
                   opening.workflow_graph_hash,
                   execution.workflow_node_id,
                   execution.workflow_transition_kind,
                   execution.source_checkpoint_id,
                   execution.source_checkpoint_sequence,
                   execution.source_checkpoint_hash,
                   (SELECT COUNT(*)
                    FROM authority_book_opening_workflow_node AS node
                    WHERE node.opening_run_id=opening.opening_run_id),
                   (SELECT COUNT(*)
                    FROM authority_book_opening_node_receipt AS receipt
                    WHERE receipt.opening_run_id=opening.opening_run_id),
                   (SELECT COUNT(*)
                    FROM authority_book_opening_workflow_transition_receipt AS receipt
                    WHERE receipt.opening_run_id=opening.opening_run_id)
            FROM authority_book_opening_run AS opening
            JOIN authority_book_opening_execution AS execution
              ON execution.opening_execution_id=opening.current_execution_id
            WHERE opening.opening_run_id=%s
            """,
            [legacy["opening_run_id"]],
        ).fetchone()
    assert defaults == [
        ("workflow_contract_version", None),
        ("workflow_graph_hash", None),
        ("workflow_graph_revision", None),
    ]
    assert compatibility == (
        "legacy-monolithic-v2",
        None,
        0,
        "",
        None,
        "LEGACY_MONOLITHIC",
        None,
        0,
        "",
        0,
        0,
        0,
    )
