from __future__ import annotations

import hashlib
import unittest

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from novel_forge.storage.migrations import LATEST_MIGRATION_ID, MIGRATIONS, run_migrations
from novel_forge.modules.runtime_job import RuntimeJobAuthority, RuntimeJobSpec
from novel_forge.modules.runtime_job.application import canonical_payload_hash
from tests.integration.authority_postgres_support import DATABASE_URL, identifier


def database_url(database_name: str) -> str:
    parameters = conninfo_to_dict(DATABASE_URL)
    parameters["dbname"] = database_name
    return make_conninfo(**parameters)


class AuthorityMigrationsPostgresTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_name = identifier("nf_authority_migration").replace("-", "_")[:63]
        self.admin_url = database_url("postgres")
        with psycopg.connect(self.admin_url, autocommit=True) as connection:
            connection.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.database_name))
            )
        self.test_url = database_url(self.database_name)

    def tearDown(self) -> None:
        with psycopg.connect(self.admin_url, autocommit=True) as connection:
            connection.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = %s AND pid <> pg_backend_pid()
                """,
                [self.database_name],
            )
            connection.execute(
                sql.SQL("DROP DATABASE {}").format(sql.Identifier(self.database_name))
            )

    def test_clean_database_applies_complete_migration_chain(self) -> None:
        status = run_migrations(self.test_url)

        self.assertTrue(status["ok"])
        self.assertEqual(status["current"], LATEST_MIGRATION_ID)
        self.assertEqual(
            [row["migration_id"] for row in status["applied"]],
            [migration.migration_id for migration in MIGRATIONS],
        )
        with psycopg.connect(self.test_url) as connection:
            row = connection.execute(
                """
                SELECT
                    to_regclass('authority_operation'),
                    to_regclass('authority_external_receipt'),
                    to_regprocedure('authority_acquire_attempt_lease(text,text,text,integer)'),
                    to_regprocedure('authority_record_inbox_message(text,text,text,jsonb)')
                """
            ).fetchone()
            missing_foreign_key_indexes = connection.execute(
                """
                SELECT constraint_row.conrelid::regclass::text, constraint_row.conname
                FROM pg_constraint AS constraint_row
                JOIN pg_class AS table_row ON table_row.oid = constraint_row.conrelid
                WHERE constraint_row.contype = 'f'
                  AND table_row.relname LIKE 'authority_%'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM pg_index AS index_row
                      WHERE index_row.indrelid = constraint_row.conrelid
                        AND index_row.indisvalid
                        AND constraint_row.conkey::smallint[]
                            <@ index_row.indkey::smallint[]
                  )
                ORDER BY constraint_row.conrelid::regclass::text, constraint_row.conname
                """
            ).fetchall()
        self.assertEqual(
            tuple(str(value) for value in row),
            (
                "authority_operation",
                "authority_external_receipt",
                "authority_acquire_attempt_lease(text,text,text,integer)",
                "authority_record_inbox_message(text,text,text,jsonb)",
            ),
        )
        self.assertEqual(missing_foreign_key_indexes, [])

    def test_existing_0007_database_upgrades_without_losing_authority_rows(self) -> None:
        operation_id = identifier("existing-operation")
        with psycopg.connect(self.test_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE nf_schema_migrations (
                    migration_id TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            for migration in MIGRATIONS:
                if migration.migration_id == "20260713_0008_authority_schema_recovery":
                    break
                for statement in migration.upgrade_statements:
                    cursor.execute(statement)
                cursor.execute(
                    "INSERT INTO nf_schema_migrations (migration_id) VALUES (%s)",
                    [migration.migration_id],
                )
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
                VALUES (
                    'ops.existing', '1.0.0', 'ops', TRUE,
                    '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb
                )
                """
            )
            cursor.execute(
                """
                INSERT INTO authority_operation (
                    operation_id,
                    definition_name,
                    definition_version,
                    project_id,
                    status,
                    root_operation_id,
                    idempotency_scope,
                    idempotency_key,
                    request_digest,
                    definition_snapshot,
                    completion_contract_snapshot,
                    policy_snapshot
                )
                VALUES (
                    %s, 'ops.existing', '1.0.0', 'existing-project', 'ADMITTED', %s,
                    'project:existing-project', %s, 'digest:existing',
                    '{}'::jsonb, '{}'::jsonb, '{}'::jsonb
                )
                """,
                [operation_id, operation_id, operation_id],
            )

        status = run_migrations(self.test_url)

        self.assertTrue(status["ok"])
        with psycopg.connect(self.test_url) as connection:
            operation = connection.execute(
                "SELECT operation_id, status FROM authority_operation WHERE operation_id = %s",
                [operation_id],
            ).fetchone()
            blob_project_column = connection.execute(
                """
                SELECT is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'authority_blob'
                  AND column_name = 'project_id'
                """
            ).fetchone()
        self.assertEqual(operation, (operation_id, "ADMITTED"))
        self.assertEqual(blob_project_column, ("NO",))

    def test_existing_0085_upgrades_without_losing_runtime_job_identity(self) -> None:
        dedupe_key = "book:shared:version:3"
        input_snapshot = {"observed_version": 3, "state": "CHAPTER_COMPLETED"}
        old_identity = "\x1f".join(
            ("book", "BOOK_COORDINATION_TICK", dedupe_key)
        )
        old_runtime_job_id = (
            "runtime-job:"
            + hashlib.sha256(old_identity.encode("utf-8")).hexdigest()
        )
        with psycopg.connect(self.test_url) as connection, connection.cursor() as cursor:
            for migration in MIGRATIONS[:-1]:
                for statement in migration.upgrade_statements:
                    cursor.execute(statement)
                cursor.execute(
                    "INSERT INTO nf_schema_migrations (migration_id) VALUES (%s)",
                    [migration.migration_id],
                )
            cursor.execute(
                """
                INSERT INTO authority_runtime_job(
                  runtime_job_id, job_kind, runtime_group, subject_kind,
                  subject_id, project_id, dedupe_key, input_snapshot, input_hash
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                [
                    old_runtime_job_id,
                    "BOOK_COORDINATION_TICK",
                    "book",
                    "BOOK_RUN",
                    "book-run:shared",
                    "project:a",
                    dedupe_key,
                    psycopg.types.json.Jsonb(input_snapshot),
                    canonical_payload_hash(input_snapshot),
                ],
            )

        status = run_migrations(self.test_url)
        self.assertTrue(status["ok"])
        authority = RuntimeJobAuthority(self.test_url)

        def spec(project_id: str) -> RuntimeJobSpec:
            return RuntimeJobSpec(
                job_kind="BOOK_COORDINATION_TICK",
                runtime_group="book",
                subject_kind="BOOK_RUN",
                subject_id="book-run:shared",
                project_id=project_id,
                dedupe_key=dedupe_key,
                input_snapshot=input_snapshot,
            )

        replay = authority.schedule(spec("project:a"))
        isolated = authority.schedule(spec("project:b"))
        self.assertEqual(replay["runtime_job_id"], old_runtime_job_id)
        self.assertTrue(replay["deduplicated"])
        self.assertTrue(isolated["created"])
        self.assertNotEqual(isolated["runtime_job_id"], old_runtime_job_id)
        with psycopg.connect(self.test_url) as connection:
            definitions = dict(
                connection.execute(
                    """
                    SELECT indexname, indexdef
                    FROM pg_indexes
                    WHERE schemaname='public'
                      AND indexname IN (
                        'authority_runtime_job_dedupe_idx',
                        'authority_runtime_job_active_subject_idx'
                      )
                    """
                ).fetchall()
            )
        self.assertIn("project_id", definitions["authority_runtime_job_dedupe_idx"])
        self.assertIn(
            "project_id", definitions["authority_runtime_job_active_subject_idx"]
        )


if __name__ == "__main__":
    unittest.main()
