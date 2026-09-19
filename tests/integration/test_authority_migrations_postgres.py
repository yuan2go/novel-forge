from __future__ import annotations

import hashlib
import unittest

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from novel_forge.storage.migrations import (
    LATEST_MIGRATION_ID,
    MIGRATIONS,
    get_migration_status,
    run_migrations,
)
from novel_forge.modules.runtime_job import RuntimeJobAuthority, RuntimeJobSpec
from novel_forge.modules.runtime_job.application import canonical_payload_hash
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import DATABASE_URL, identifier
from tests.integration.migration_window_postgres_support import (
    disposable_database_at_migration,
)


@pytest.mark.parametrize(
    "baseline",
    ["20260625_0001_initial_industrial_schema", "20260916_0136_provider_routing_policy"],
)
def test_opening_delete_fence_fresh_and_upgrade(baseline):
    with disposable_database_at_migration(
        DATABASE_URL, prefix="opening_delete", target_migration_id=baseline
    ) as url:
        status = run_migrations(url)
        assert status["ok"]
        assert run_migrations(url) == status
        with psycopg.connect(url) as connection:
            connection.execute(
                """CREATE TEMP TABLE opening_delete_probe (
                    opening_run_id TEXT, lifecycle TEXT,
                    capacity_successor_opening_run_id TEXT)"""
            )
            for name, function in (
                ("authority_bo_capacity_predecessor_fence", "authority_bo_capacity_predecessor_fence"),
                ("authority_book_opening_run_terminal_immutable", "authority_bo_run_terminal_immutable_guard"),
            ):
                connection.execute(sql.SQL(
                    "CREATE TRIGGER {} BEFORE UPDATE OR DELETE ON opening_delete_probe "
                    "FOR EACH ROW EXECUTE FUNCTION {}()"
                ).format(sql.Identifier(name), sql.Identifier(function)))
            connection.execute(
                """INSERT INTO opening_delete_probe VALUES
                    ('unfenced','FAILED',NULL), ('fenced','FAILED','successor'),
                    ('complete','COMPLETE',NULL), ('aborted','ABORTED',NULL)"""
            )
            assert connection.execute(
                "DELETE FROM opening_delete_probe WHERE opening_run_id='unfenced'"
            ).rowcount == 1
            for opening_id, error in (
                ("fenced", "BOOK_OPENING_CAPACITY_PREDECESSOR_FENCED"),
                ("complete", "BOOK_OPENING_RUN_TERMINAL_IMMUTABLE"),
                ("aborted", "BOOK_OPENING_RUN_TERMINAL_IMMUTABLE"),
            ):
                with pytest.raises(psycopg.errors.CheckViolation, match=error):
                    with connection.transaction():
                        connection.execute(
                            "DELETE FROM opening_delete_probe WHERE opening_run_id=%s",
                            [opening_id],
                        )
            assert connection.execute(
                "SELECT opening_run_id FROM opening_delete_probe ORDER BY opening_run_id"
            ).fetchall() == [("aborted",), ("complete",), ("fenced",)]


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

    def _seed_v2_scheduled_opening(self) -> tuple[str, str, str, str]:
        status = run_migrations(self.test_url)
        self.assertTrue(status["ok"])
        project_id = "project:migration-relational-closure"
        workspace_id = "workspace:migration-relational-closure"
        book_id = "book:migration-relational-closure"
        operation_id = "operation:migration-relational-closure"
        opening_run_id = "book-opening:migration-relational-closure"
        runtime_job_id = "runtime-job:migration-relational-closure"
        execution_id = "book-opening-execution:migration-relational-closure:1"
        request_hash = "sha256:" + "1" * 64
        input_hash = "sha256:" + "2" * 64
        with (
            psycopg.connect(self.test_url) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                """
                INSERT INTO authority_operation_definition(
                    name,definition_version,family,enabled,command_schema,
                    result_schema,policy,completion_contract
                ) VALUES (
                    'fixture.migration.relational_closure','1.0.0',
                    'migration-fixture',TRUE,'{}'::jsonb,'{}'::jsonb,
                    '{}'::jsonb,'{}'::jsonb
                )
                """
            )
            cursor.execute(
                """
                INSERT INTO authority_operation(
                    operation_id,definition_name,definition_version,project_id,
                    workspace_id,actor_id,status,root_operation_id,
                    idempotency_scope,idempotency_key,request_digest,
                    definition_snapshot,completion_contract_snapshot,
                    policy_snapshot,concurrency_key,command_payload
                ) VALUES (
                    %s,'fixture.migration.relational_closure','1.0.0',%s,%s,
                    'migration-fixture','ADMITTED',%s,%s,%s,%s,
                    '{}'::jsonb,'{}'::jsonb,'{}'::jsonb,%s,'{}'::jsonb
                )
                """,
                [
                    operation_id,
                    project_id,
                    workspace_id,
                    operation_id,
                    f"project:{project_id}",
                    operation_id,
                    request_hash,
                    f"fixture:{operation_id}",
                ],
            )
            for asset_id, asset_type, digest in (
                ("asset:migration-relational-project", "project_record", "3"),
                ("asset:migration-relational-workspace", "workspace_record", "4"),
                ("asset:migration-relational-book", "book_record", "5"),
            ):
                cursor.execute(
                    "INSERT INTO authority_asset(asset_id,project_id,asset_type) "
                    "VALUES (%s,%s,%s)",
                    [asset_id, project_id, asset_type],
                )
                cursor.execute(
                    """
                    INSERT INTO authority_asset_version(
                        asset_version_id,asset_id,version_number,lifecycle,
                        eligibility,governance,content,content_hash,schema_version
                    ) VALUES (
                        %s,%s,1,'ACTIVE','ELIGIBLE','CLEAR','{}'::jsonb,%s,
                        'migration-relational-closure.v1'
                    )
                    """,
                    [f"{asset_id}:v1", asset_id, "sha256:" + digest * 64],
                )
            cursor.execute(
                """
                INSERT INTO authority_project(
                    project_id,primary_workspace_id,title,status,stage,health,
                    current_asset_version_id,created_by_operation_id,
                    last_operation_id
                ) VALUES (
                    %s,%s,'Migration Relational Closure','ACTIVE','PLANNING',
                    'HEALTHY','asset:migration-relational-project:v1',%s,%s
                )
                """,
                [project_id, workspace_id, operation_id, operation_id],
            )
            cursor.execute(
                """
                INSERT INTO authority_workspace(
                    workspace_id,project_id,book_id,status,
                    current_asset_version_id,created_by_operation_id,
                    last_operation_id
                ) VALUES (
                    %s,%s,%s,'ACTIVE',
                    'asset:migration-relational-workspace:v1',%s,%s
                )
                """,
                [workspace_id, project_id, book_id, operation_id, operation_id],
            )
            cursor.execute(
                """
                INSERT INTO authority_book(
                    book_id,project_id,workspace_id,principal_id,
                    service_identity,book_scope,production_profile,
                    runtime_policy,release_identity,status,
                    current_book_asset_version_id,created_by_operation_id,
                    last_operation_id
                ) VALUES (
                    %s,%s,%s,'migration-fixture','migration-fixture',
                    '{}'::jsonb,'{}'::jsonb,'{}'::jsonb,'migration@0102',
                    'DESIGN_PENDING','asset:migration-relational-book:v1',%s,%s
                )
                """,
                [book_id, project_id, workspace_id, operation_id, operation_id],
            )
            cursor.execute(
                """
                INSERT INTO authority_book_opening_run(
                    opening_run_id,project_id,workspace_id,book_id,
                    root_operation_id,stable_idempotency_key,lifecycle,
                    frozen_request,frozen_request_digest,
                    execution_contract_version,recovery_state,
                    workflow_contract_version,current_workflow_node_id,
                    workflow_graph_revision,workflow_graph_hash
                ) VALUES (
                    %s,%s,%s,%s,%s,%s,'ADMITTED',
                    jsonb_build_object(
                        'project_id',%s::text,'workspace_id',%s::text,
                        'book_id',%s::text,'idempotency_key',%s::text
                    ),%s,
                    'book-opening-execution-v2','READY',
                    'legacy-monolithic-v2',NULL,0,''
                )
                """,
                [
                    opening_run_id,
                    project_id,
                    workspace_id,
                    book_id,
                    operation_id,
                    "migration-relational-closure",
                    project_id,
                    workspace_id,
                    book_id,
                    "migration-relational-closure",
                    request_hash,
                ],
            )
            cursor.execute(
                """
                INSERT INTO authority_runtime_job(
                    runtime_job_id,job_kind,runtime_group,subject_kind,
                    subject_id,project_id,dedupe_key,input_snapshot,input_hash,
                    max_attempts,lease_loss_policy
                ) VALUES (
                    %s,'BOOK_OPENING_EXECUTE','book_opening',
                    'BOOK_OPENING_RUN',%s,%s,%s,'{}'::jsonb,%s,1,
                    'AUTHORITY_CONVERGENCE_REQUIRED'
                )
                """,
                [
                    runtime_job_id,
                    opening_run_id,
                    project_id,
                    "migration-relational-closure:generation:1",
                    input_hash,
                ],
            )
            cursor.execute(
                """
                INSERT INTO authority_book_opening_execution(
                    opening_execution_id,opening_run_id,generation,
                    runtime_job_id,lifecycle,frozen_request_digest,
                    input_snapshot_hash,policy_snapshot_hash,
                    authority_contract_hash
                ) VALUES (%s,%s,1,%s,'SCHEDULED',%s,%s,%s,%s)
                """,
                [
                    execution_id,
                    opening_run_id,
                    runtime_job_id,
                    request_hash,
                    input_hash,
                    "sha256:" + "6" * 64,
                    "sha256:" + "7" * 64,
                ],
            )
            cursor.execute(
                """
                UPDATE authority_book_opening_run
                SET current_execution_id=%s,current_execution_generation=1
                WHERE opening_run_id=%s
                """,
                [execution_id, opening_run_id],
            )
        return project_id, opening_run_id, runtime_job_id, execution_id

    @staticmethod
    def _insert_recovery_assessment(
        cursor: psycopg.Cursor,
        *,
        opening_run_id: str,
        execution_id: str,
        assessment_id: str,
        kind: str,
        disposition: str | None = None,
        snapshot: dict[str, object] | None = None,
    ) -> None:
        disposition = disposition or {
            "EXECUTION_LOSS": "EXECUTION_LOST",
            "CHECKPOINT_RECONCILIATION": "RECONCILIATION_REQUIRED",
            "LEGACY_EXECUTION_RECONCILIATION": "RECONCILIATION_REQUIRED",
        }.get(kind, "PROVEN_NO_EFFECT")
        cursor.execute(
            """
            INSERT INTO authority_book_opening_recovery_assessment(
                recovery_assessment_id,assessment_kind,opening_run_id,
                opening_version,opening_execution_id,execution_generation,
                evaluation_head_digest,external_effect_digest,
                policy_config_digest,authority_version_digest,
                snapshot,snapshot_hash,disposition,idempotency_key
            ) VALUES (
                %s,%s,%s,0,%s,1,%s,%s,%s,%s,
                %s,%s,%s,%s
            )
            """,
            [
                assessment_id,
                kind,
                opening_run_id,
                execution_id,
                "sha256:" + "1" * 64,
                "sha256:" + "2" * 64,
                "sha256:" + "3" * 64,
                "sha256:" + "4" * 64,
                psycopg.types.json.Jsonb(snapshot or {}),
                "sha256:" + "5" * 64,
                disposition,
                f"assessment:{assessment_id}",
            ],
        )

    @staticmethod
    def _insert_recovery_intent(
        cursor: psycopg.Cursor,
        *,
        opening_run_id: str,
        execution_id: str,
        assessment_id: str,
        intent_id: str,
    ) -> None:
        cursor.execute(
            """
            INSERT INTO authority_book_opening_recovery_intent(
                recovery_intent_id,opening_run_id,recovery_assessment_id,
                predecessor_execution_id,predecessor_generation,
                successor_generation,idempotency_key,intent_hash,
                authorized_by,authorization_reason
            ) VALUES (%s,%s,%s,%s,1,2,%s,%s,'migration-operator','test')
            """,
            [
                intent_id,
                opening_run_id,
                assessment_id,
                execution_id,
                f"intent:{intent_id}",
                "sha256:" + "6" * 64,
            ],
        )

    @staticmethod
    def _insert_recovery_receipt(
        cursor: psycopg.Cursor,
        *,
        opening_run_id: str,
        execution_id: str,
        assessment_id: str,
        receipt_id: str,
        kind: str,
        intent_id: str = "",
        successor_execution_id: str = "",
    ) -> None:
        cursor.execute(
            """
            INSERT INTO authority_book_opening_recovery_receipt(
                recovery_receipt_id,receipt_kind,opening_run_id,
                recovery_assessment_id,recovery_intent_id,
                predecessor_execution_id,predecessor_generation,
                successor_execution_id,successor_generation,
                result,result_hash,idempotency_key
            ) VALUES (
                %s,%s,%s,%s,NULLIF(%s,''),%s,1,NULLIF(%s,''),
                CASE WHEN %s='' THEN NULL ELSE 2 END,
                '{}'::jsonb,%s,%s
            )
            """,
            [
                receipt_id,
                kind,
                opening_run_id,
                assessment_id,
                intent_id,
                execution_id,
                successor_execution_id,
                successor_execution_id,
                "sha256:" + "7" * 64,
                f"receipt:{receipt_id}",
            ],
        )

    @staticmethod
    def _insert_recovery_successor_execution(
        cursor: psycopg.Cursor,
        *,
        project_id: str,
        opening_run_id: str,
        predecessor_execution_id: str,
        successor_execution_id: str,
        recovery_intent_id: str,
        frozen_request_digest: str | None = None,
    ) -> str:
        runtime_job_id = f"runtime-job:{successor_execution_id}"
        input_hash = "sha256:" + "8" * 64
        cursor.execute(
            """
            INSERT INTO authority_runtime_job(
                runtime_job_id,job_kind,runtime_group,subject_kind,
                subject_id,project_id,dedupe_key,input_snapshot,input_hash
            ) VALUES (
                %s,'BOOK_OPENING_EXECUTE','book_opening',
                'BOOK_OPENING_RUN',%s,%s,%s,'{}'::jsonb,%s
            )
            """,
            [
                runtime_job_id,
                opening_run_id,
                project_id,
                f"migration-recovery-successor:{successor_execution_id}",
                input_hash,
            ],
        )
        cursor.execute(
            """
            INSERT INTO authority_book_opening_execution(
                opening_execution_id,opening_run_id,generation,
                predecessor_execution_id,predecessor_generation,
                recovery_intent_id,runtime_job_id,lifecycle,frozen_request_digest,
                input_snapshot_hash,policy_snapshot_hash,
                authority_contract_hash
            ) VALUES (
                %s,%s,2,%s,1,%s,%s,'SCHEDULED',%s,%s,%s,%s
            )
            """,
            [
                successor_execution_id,
                opening_run_id,
                predecessor_execution_id,
                recovery_intent_id,
                runtime_job_id,
                frozen_request_digest or "sha256:" + "1" * 64,
                input_hash,
                "sha256:" + "9" * 64,
                "sha256:" + "a" * 64,
            ],
        )
        return runtime_job_id

    def _write_recovery_admission(
        self,
        cursor: psycopg.Cursor,
        *,
        project_id: str,
        opening_run_id: str,
        predecessor_execution_id: str,
        suffix: str,
        disposition: str = "PROVEN_NO_EFFECT",
        snapshot: dict[str, object] | None = None,
        frozen_request_digest: str | None = None,
        update_opening_head: bool = True,
    ) -> tuple[str, str, str, str]:
        assessment_id = f"assessment:{suffix}"
        intent_id = f"intent:{suffix}"
        receipt_id = f"receipt:{suffix}"
        successor_execution_id = f"book-opening-execution:{suffix}:2"
        self._insert_recovery_successor_execution(
            cursor,
            project_id=project_id,
            opening_run_id=opening_run_id,
            predecessor_execution_id=predecessor_execution_id,
            successor_execution_id=successor_execution_id,
            recovery_intent_id=intent_id,
            frozen_request_digest=frozen_request_digest,
        )
        self._insert_recovery_assessment(
            cursor,
            opening_run_id=opening_run_id,
            execution_id=predecessor_execution_id,
            assessment_id=assessment_id,
            kind="RECOVERY",
            disposition=disposition,
            snapshot=snapshot,
        )
        self._insert_recovery_intent(
            cursor,
            opening_run_id=opening_run_id,
            execution_id=predecessor_execution_id,
            assessment_id=assessment_id,
            intent_id=intent_id,
        )
        self._insert_recovery_receipt(
            cursor,
            opening_run_id=opening_run_id,
            execution_id=predecessor_execution_id,
            assessment_id=assessment_id,
            receipt_id=receipt_id,
            kind="RECOVERY_ADMISSION",
            intent_id=intent_id,
            successor_execution_id=successor_execution_id,
        )
        if update_opening_head:
            cursor.execute(
                """
                UPDATE authority_book_opening_run
                SET current_execution_id=%s,current_execution_generation=2,
                    lifecycle='ADMITTED',recovery_state='RECOVERY_ADMITTED',
                    version=version+1,updated_at=transaction_timestamp()
                WHERE opening_run_id=%s AND lifecycle='FAILED'
                """,
                [successor_execution_id, opening_run_id],
            )
        return assessment_id, intent_id, receipt_id, successor_execution_id

    def _claim_and_bind_opening_execution(
        self,
        *,
        runtime_job_id: str,
        execution_id: str,
        worker_id: str,
    ):
        runtime_jobs = RuntimeJobAuthority(self.test_url)
        with AuthorityUnitOfWork(self.test_url) as uow:
            claim = runtime_jobs.claim_ready_in_uow(
                uow,
                runtime_job_id=runtime_job_id,
                worker_id=worker_id,
                lease_seconds=60,
            )
            uow.cursor.execute(
                """
                UPDATE authority_book_opening_execution
                SET current_attempt_id=%s,current_lease_id=%s,
                    current_worker_id=%s,current_fencing_token=%s,
                    lifecycle='BOUND',version=version+1,
                    updated_at=transaction_timestamp()
                WHERE opening_execution_id=%s AND lifecycle='SCHEDULED'
                """,
                [
                    claim.attempt_id,
                    claim.lease_id,
                    claim.worker_id,
                    claim.fencing_token,
                    execution_id,
                ],
            )
            self.assertEqual(uow.cursor.rowcount, 1)
            uow.commit()
        return claim

    def _abort_unclaimed_opening_execution(
        self,
        *,
        opening_run_id: str,
        runtime_job_id: str,
        execution_id: str,
        opening_lifecycle: str = "FAILED",
    ) -> None:
        if opening_lifecycle not in {"FAILED", "ABORTED"}:
            raise ValueError("opening_lifecycle must be terminal")
        with psycopg.connect(self.test_url) as connection:
            connection.execute(
                """
                UPDATE authority_runtime_job
                SET status='CANCELLED',completed_at=transaction_timestamp(),
                    last_error='{"code":"TEST_PREDECESSOR_ABORTED"}'::jsonb,
                    updated_at=transaction_timestamp()
                WHERE runtime_job_id=%s AND status='READY'
                """,
                [runtime_job_id],
            )
            connection.execute(
                """
                UPDATE authority_book_opening_execution
                SET lifecycle='ABORTED',terminal_at=transaction_timestamp(),
                    terminal_reason=
                        '{"code":"TEST_PREDECESSOR_ABORTED"}'::jsonb,
                    version=version+1,updated_at=transaction_timestamp()
                WHERE opening_execution_id=%s AND lifecycle='SCHEDULED'
                """,
                [execution_id],
            )
            connection.execute(
                """
                UPDATE authority_book_opening_run
                SET lifecycle=%s,recovery_state='RECOVERY_REQUIRED',
                    version=version+1,updated_at=transaction_timestamp()
                WHERE opening_run_id=%s AND lifecycle='ADMITTED'
                """,
                [opening_lifecycle, opening_run_id],
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

    def test_policy_completion_index_upgrade_rolls_back_and_replays(self) -> None:
        from tests.integration.test_book_projection_repair_upgrade_postgres import (
            _apply_through,
        )

        _apply_through(self.test_url, "20260905_0112_realization_execution_policy")
        with psycopg.connect(self.test_url) as connection:
            before = connection.execute(
                "SELECT migration_id, applied_at FROM nf_schema_migrations ORDER BY migration_id"
            ).fetchall()
            indexes_before = connection.execute(
                "SELECT indexrelid FROM pg_index ORDER BY indexrelid"
            ).fetchall()
            pending = [
                migration for migration in MIGRATIONS
                if migration.migration_id not in {row[0] for row in before}
            ]
            self.assertTrue(pending, "the merged policy/completion schema needs a forward index repair")
            with self.assertRaisesRegex(RuntimeError, "rollback index repair"):
                with connection.transaction():
                    for migration in pending:
                        for statement in migration.upgrade_statements:
                            connection.execute(statement)
                    raise RuntimeError("rollback index repair")
            self.assertEqual(
                connection.execute("SELECT indexrelid FROM pg_index ORDER BY indexrelid").fetchall(),
                indexes_before,
            )
        first = run_migrations(self.test_url)
        self.assertTrue(first["ok"])
        self.assertEqual(run_migrations(self.test_url), first)
        with psycopg.connect(self.test_url) as connection:
            after = dict(connection.execute(
                "SELECT migration_id, applied_at FROM nf_schema_migrations"
            ).fetchall())
            self.assertTrue(all(after[revision] == applied_at for revision, applied_at in before))
            missing = connection.execute(
                """
                SELECT constraint_row.conname FROM pg_constraint AS constraint_row
                JOIN pg_class AS table_row ON table_row.oid=constraint_row.conrelid
                WHERE constraint_row.contype='f' AND table_row.relname LIKE 'authority_%'
                  AND NOT EXISTS (
                      SELECT 1 FROM pg_index AS index_row
                      WHERE index_row.indrelid=constraint_row.conrelid
                        AND index_row.indisvalid
                        AND constraint_row.conkey::smallint[] <@ index_row.indkey::smallint[]
                  )
                """
            ).fetchall()
            self.assertEqual(missing, [])

    def test_0128_corpus_member_index_repair_is_atomic_and_preserves_history(self) -> None:
        from tests.integration.test_book_projection_repair_upgrade_postgres import _apply_through

        _apply_through(self.test_url, "20260910_0128_corpus_operations")
        repair = next(migration for migration in MIGRATIONS
                      if migration.migration_id == "20260912_0129_corpus_member_fk_indexes")
        coverage_sql = """
            SELECT constraint_row.conrelid::regclass::text,
                   ARRAY(SELECT attribute.attname::text
                         FROM unnest(constraint_row.conkey) WITH ORDINALITY key(attnum,position)
                         JOIN pg_attribute attribute ON attribute.attrelid=constraint_row.conrelid
                           AND attribute.attnum=key.attnum ORDER BY key.position),
                   EXISTS(SELECT 1 FROM pg_index index_row
                          WHERE index_row.indrelid=constraint_row.conrelid
                            AND index_row.indisvalid AND index_row.indpred IS NULL
                            AND ARRAY(SELECT key.attnum FROM unnest(index_row.indkey) WITH ORDINALITY key(attnum,position)
                                      WHERE key.position <= cardinality(constraint_row.conkey)
                                      ORDER BY key.position)=constraint_row.conkey)
            FROM pg_constraint constraint_row
            WHERE constraint_row.contype='f' AND constraint_row.conrelid IN (
                'authority_corpus_work_member'::regclass,'authority_corpus_curated_member'::regclass)
            ORDER BY 1,2
        """
        expected_keys = {(table, columns) for table in (
            "authority_corpus_work_member", "authority_corpus_curated_member") for columns in (
                ("revision_id", "project_id"), ("processing_id", "project_id", "edition_id"))}
        with psycopg.connect(self.test_url) as connection:
            before = connection.execute("SELECT migration_id,applied_at FROM nf_schema_migrations ORDER BY migration_id").fetchall()
            rows = connection.execute(coverage_sql).fetchall()
            self.assertEqual({(table, tuple(columns)) for table, columns, covered in rows if not covered}, expected_keys)
            with self.assertRaisesRegex(RuntimeError, "rollback corpus member indexes"):
                with connection.transaction():
                    for statement in repair.upgrade_statements:
                        connection.execute(statement)
                    self.assertTrue(all(covered for _, _, covered in connection.execute(coverage_sql)))
                    raise RuntimeError("rollback corpus member indexes")
            self.assertEqual(connection.execute(coverage_sql).fetchall(), rows)
            self.assertEqual(connection.execute("SELECT migration_id,applied_at FROM nf_schema_migrations ORDER BY migration_id").fetchall(), before)
        upgraded = run_migrations(self.test_url)
        self.assertTrue(upgraded["ok"])
        self.assertEqual(run_migrations(self.test_url), upgraded)
        with psycopg.connect(self.test_url) as connection:
            repaired = connection.execute(coverage_sql).fetchall()
            self.assertEqual({(table, tuple(columns)) for table, columns, _ in repaired}, expected_keys)
            self.assertTrue(all(covered for _, _, covered in repaired))
            after = dict(connection.execute("SELECT migration_id,applied_at FROM nf_schema_migrations"))
            self.assertTrue(all(after[revision] == applied_at for revision, applied_at in before))

    def test_0102_recovery_intent_requires_recovery_assessment_at_commit(
        self,
    ) -> None:
        _project_id, opening_run_id, _runtime_job_id, execution_id = (
            self._seed_v2_scheduled_opening()
        )
        with self.assertRaises(psycopg.errors.CheckViolation) as invalid:
            with psycopg.connect(self.test_url) as connection:
                with connection.cursor() as cursor:
                    self._insert_recovery_assessment(
                        cursor,
                        opening_run_id=opening_run_id,
                        execution_id=execution_id,
                        assessment_id="assessment:loss-cannot-authorize",
                        kind="EXECUTION_LOSS",
                    )
                    self._insert_recovery_intent(
                        cursor,
                        opening_run_id=opening_run_id,
                        execution_id=execution_id,
                        assessment_id="assessment:loss-cannot-authorize",
                        intent_id="intent:loss-cannot-authorize",
                    )
        self.assertIn(
            "BOOK_OPENING_RECOVERY_INTENT_ASSESSMENT_BINDING_INVALID",
            str(invalid.exception),
        )

    def test_0102_recovery_receipt_kind_and_intent_are_assessment_bound(
        self,
    ) -> None:
        project_id, opening_run_id, runtime_job_id, execution_id = (
            self._seed_v2_scheduled_opening()
        )
        self._abort_unclaimed_opening_execution(
            opening_run_id=opening_run_id,
            runtime_job_id=runtime_job_id,
            execution_id=execution_id,
        )
        for assessment_kind, receipt_kind in (
            ("RECOVERY", "EXECUTION_LOSS_CONVERGENCE"),
            ("EXECUTION_LOSS", "CHECKPOINT_RECONCILIATION"),
        ):
            suffix = receipt_kind.lower()
            with self.subTest(receipt_kind=receipt_kind):
                with self.assertRaises(psycopg.errors.CheckViolation) as invalid:
                    with psycopg.connect(self.test_url) as connection:
                        with connection.cursor() as cursor:
                            self._insert_recovery_assessment(
                                cursor,
                                opening_run_id=opening_run_id,
                                execution_id=execution_id,
                                assessment_id=f"assessment:{suffix}",
                                kind=assessment_kind,
                            )
                            self._insert_recovery_receipt(
                                cursor,
                                opening_run_id=opening_run_id,
                                execution_id=execution_id,
                                assessment_id=f"assessment:{suffix}",
                                receipt_id=f"receipt:{suffix}",
                                kind=receipt_kind,
                            )
                self.assertIn(
                    "BOOK_OPENING_RECOVERY_RECEIPT_ASSESSMENT_KIND_INVALID",
                    str(invalid.exception),
                )

        successor_execution_id = "book-opening-execution:receipt-mismatch:2"
        with self.assertRaises(psycopg.errors.CheckViolation) as mismatch:
            with psycopg.connect(self.test_url) as connection:
                with connection.cursor() as cursor:
                    self._insert_recovery_successor_execution(
                        cursor,
                        project_id=project_id,
                        opening_run_id=opening_run_id,
                        predecessor_execution_id=execution_id,
                        successor_execution_id=successor_execution_id,
                        recovery_intent_id="intent:receipt-mismatch",
                    )
                    self._insert_recovery_assessment(
                        cursor,
                        opening_run_id=opening_run_id,
                        execution_id=execution_id,
                        assessment_id="assessment:intent-owner",
                        kind="RECOVERY",
                    )
                    self._insert_recovery_intent(
                        cursor,
                        opening_run_id=opening_run_id,
                        execution_id=execution_id,
                        assessment_id="assessment:intent-owner",
                        intent_id="intent:receipt-mismatch",
                    )
                    self._insert_recovery_assessment(
                        cursor,
                        opening_run_id=opening_run_id,
                        execution_id=execution_id,
                        assessment_id="assessment:receipt-mismatch",
                        kind="RECOVERY",
                    )
                    self._insert_recovery_receipt(
                        cursor,
                        opening_run_id=opening_run_id,
                        execution_id=execution_id,
                        assessment_id="assessment:receipt-mismatch",
                        receipt_id="receipt:intent-mismatch",
                        kind="RECOVERY_ADMISSION",
                        intent_id="intent:receipt-mismatch",
                        successor_execution_id=successor_execution_id,
                    )
                    cursor.execute(
                        """
                        UPDATE authority_book_opening_run
                        SET lifecycle='ADMITTED',
                            recovery_state='RECOVERY_ADMITTED',
                            current_execution_id=%s,
                            current_execution_generation=2,
                            version=version+1,
                            updated_at=transaction_timestamp()
                        WHERE opening_run_id=%s
                        """,
                        [successor_execution_id, opening_run_id],
                    )
        self.assertIn(
            "BOOK_OPENING_RECOVERY_INTENT_RECEIPT_REQUIRED",
            str(mismatch.exception),
        )

    def test_0102_valid_recovery_fact_relationships_commit(self) -> None:
        project_id, opening_run_id, runtime_job_id, execution_id = (
            self._seed_v2_scheduled_opening()
        )
        self._abort_unclaimed_opening_execution(
            opening_run_id=opening_run_id,
            runtime_job_id=runtime_job_id,
            execution_id=execution_id,
        )
        successor_execution_id = "book-opening-execution:valid-recovery:2"
        with psycopg.connect(self.test_url) as connection:
            with connection.cursor() as cursor:
                self._insert_recovery_successor_execution(
                    cursor,
                    project_id=project_id,
                    opening_run_id=opening_run_id,
                    predecessor_execution_id=execution_id,
                    successor_execution_id=successor_execution_id,
                    recovery_intent_id="intent:valid-recovery",
                )
                self._insert_recovery_assessment(
                    cursor,
                    opening_run_id=opening_run_id,
                    execution_id=execution_id,
                    assessment_id="assessment:valid-recovery",
                    kind="RECOVERY",
                )
                self._insert_recovery_intent(
                    cursor,
                    opening_run_id=opening_run_id,
                    execution_id=execution_id,
                    assessment_id="assessment:valid-recovery",
                    intent_id="intent:valid-recovery",
                )
                self._insert_recovery_receipt(
                    cursor,
                    opening_run_id=opening_run_id,
                    execution_id=execution_id,
                    assessment_id="assessment:valid-recovery",
                    receipt_id="receipt:valid-recovery",
                    kind="RECOVERY_ADMISSION",
                    intent_id="intent:valid-recovery",
                    successor_execution_id=successor_execution_id,
                )
                cursor.execute(
                    """
                    UPDATE authority_book_opening_run
                    SET current_execution_id=%s,current_execution_generation=2,
                        lifecycle='ADMITTED',recovery_state='RECOVERY_ADMITTED',
                        version=version+1,updated_at=transaction_timestamp()
                    WHERE opening_run_id=%s AND lifecycle='FAILED'
                    """,
                    [successor_execution_id, opening_run_id],
                )
        with psycopg.connect(self.test_url) as connection:
            counts = connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM authority_book_opening_recovery_assessment),
                    (SELECT COUNT(*) FROM authority_book_opening_recovery_intent),
                    (SELECT COUNT(*) FROM authority_book_opening_recovery_receipt)
                """
            ).fetchone()
        self.assertEqual(counts, (1, 1, 1))

    def test_0102_unknown_recovery_assessment_cannot_authorize_admission(
        self,
    ) -> None:
        project_id, opening_run_id, runtime_job_id, execution_id = (
            self._seed_v2_scheduled_opening()
        )
        self._abort_unclaimed_opening_execution(
            opening_run_id=opening_run_id,
            runtime_job_id=runtime_job_id,
            execution_id=execution_id,
        )
        with self.assertRaises(psycopg.errors.CheckViolation) as unsafe:
            with psycopg.connect(self.test_url) as connection:
                with connection.cursor() as cursor:
                    self._write_recovery_admission(
                        cursor,
                        project_id=project_id,
                        opening_run_id=opening_run_id,
                        predecessor_execution_id=execution_id,
                        suffix="unknown-ambiguous",
                        disposition="UNKNOWN_AMBIGUOUS",
                    )
        self.assertIn(
            "BOOK_OPENING_RECOVERY_INTENT_ASSESSMENT_BINDING_INVALID",
            str(unsafe.exception),
        )
        with psycopg.connect(self.test_url) as connection:
            facts = connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM authority_book_opening_recovery_intent),
                    (SELECT COUNT(*) FROM authority_book_opening_recovery_receipt),
                    (SELECT COUNT(*) FROM authority_book_opening_execution
                     WHERE generation>1)
                """
            ).fetchone()
        self.assertEqual(facts, (0, 0, 0))

    def test_0102_recovery_intent_cannot_commit_without_admission_receipt(
        self,
    ) -> None:
        _project_id, opening_run_id, runtime_job_id, execution_id = (
            self._seed_v2_scheduled_opening()
        )
        self._abort_unclaimed_opening_execution(
            opening_run_id=opening_run_id,
            runtime_job_id=runtime_job_id,
            execution_id=execution_id,
        )
        with self.assertRaises(psycopg.errors.CheckViolation) as standalone:
            with psycopg.connect(self.test_url) as connection:
                with connection.cursor() as cursor:
                    self._insert_recovery_assessment(
                        cursor,
                        opening_run_id=opening_run_id,
                        execution_id=execution_id,
                        assessment_id="assessment:standalone-intent",
                        kind="RECOVERY",
                    )
                    self._insert_recovery_intent(
                        cursor,
                        opening_run_id=opening_run_id,
                        execution_id=execution_id,
                        assessment_id="assessment:standalone-intent",
                        intent_id="intent:standalone",
                    )
        self.assertIn(
            "BOOK_OPENING_RECOVERY_INTENT_RECEIPT_REQUIRED",
            str(standalone.exception),
        )

    def test_0102_recovery_intent_cannot_have_duplicate_admission_receipts(
        self,
    ) -> None:
        project_id, opening_run_id, runtime_job_id, execution_id = (
            self._seed_v2_scheduled_opening()
        )
        self._abort_unclaimed_opening_execution(
            opening_run_id=opening_run_id,
            runtime_job_id=runtime_job_id,
            execution_id=execution_id,
        )
        with self.assertRaises(psycopg.errors.UniqueViolation):
            with psycopg.connect(self.test_url) as connection:
                with connection.cursor() as cursor:
                    assessment_id, intent_id, _receipt_id, successor_id = (
                        self._write_recovery_admission(
                            cursor,
                            project_id=project_id,
                            opening_run_id=opening_run_id,
                            predecessor_execution_id=execution_id,
                            suffix="duplicate-receipt",
                        )
                    )
                    self._insert_recovery_receipt(
                        cursor,
                        opening_run_id=opening_run_id,
                        execution_id=execution_id,
                        assessment_id=assessment_id,
                        receipt_id="receipt:duplicate-receipt:second",
                        kind="RECOVERY_ADMISSION",
                        intent_id=intent_id,
                        successor_execution_id=successor_id,
                    )

    def test_0102_execution_head_rejects_generation_skip_and_rollback(
        self,
    ) -> None:
        project_id, opening_run_id, runtime_job_id, execution_id = (
            self._seed_v2_scheduled_opening()
        )
        with self.assertRaises(psycopg.errors.CheckViolation) as skipped:
            with psycopg.connect(self.test_url) as connection:
                connection.execute(
                    """
                    UPDATE authority_book_opening_run
                    SET current_execution_generation=3
                    WHERE opening_run_id=%s
                    """,
                    [opening_run_id],
                )
        self.assertIn(
            "BOOK_OPENING_EXECUTION_HEAD_NON_MONOTONIC",
            str(skipped.exception),
        )

        self._abort_unclaimed_opening_execution(
            opening_run_id=opening_run_id,
            runtime_job_id=runtime_job_id,
            execution_id=execution_id,
        )
        with psycopg.connect(self.test_url) as connection:
            with connection.cursor() as cursor:
                _assessment, _intent, _receipt, successor_id = (
                    self._write_recovery_admission(
                        cursor,
                        project_id=project_id,
                        opening_run_id=opening_run_id,
                        predecessor_execution_id=execution_id,
                        suffix="head-monotonic",
                    )
                )
        with self.assertRaises(psycopg.errors.CheckViolation) as rolled_back:
            with psycopg.connect(self.test_url) as connection:
                connection.execute(
                    """
                    UPDATE authority_book_opening_run
                    SET current_execution_id=%s,current_execution_generation=1
                    WHERE opening_run_id=%s
                      AND current_execution_id=%s
                    """,
                    [execution_id, opening_run_id, successor_id],
                )
        self.assertIn(
            "BOOK_OPENING_EXECUTION_HEAD_NON_MONOTONIC",
            str(rolled_back.exception),
        )

    def test_0102_checkpoint_head_rejects_cursor_rollback(self) -> None:
        _project_id, opening_run_id, _runtime_job_id, execution_id = (
            self._seed_v2_scheduled_opening()
        )
        request_digest = "sha256:" + "1" * 64
        checkpoint_1_hash = "sha256:" + "b" * 64
        checkpoint_2_hash = "sha256:" + "c" * 64
        with psycopg.connect(self.test_url) as connection:
            connection.execute(
                """
                INSERT INTO authority_book_opening_semantic_checkpoint(
                    checkpoint_id,opening_run_id,opening_execution_id,
                    execution_generation,checkpoint_sequence,semantic_work_key,
                    owning_authority,evidence_type,evidence_id,evidence_version,
                    evidence_hash,frozen_request_digest,checkpoint_hash
                ) VALUES (
                    'checkpoint:head:1',%s,%s,1,1,'semantic:head:1',
                    'STORY_DESIGN_AUTHORITY','ASSET_VERSION','evidence:head:1',1,
                    %s,%s,%s
                )
                """,
                [
                    opening_run_id,
                    execution_id,
                    "sha256:" + "d" * 64,
                    request_digest,
                    checkpoint_1_hash,
                ],
            )
            connection.execute(
                """
                UPDATE authority_book_opening_run
                SET current_checkpoint_id='checkpoint:head:1',
                    current_checkpoint_sequence=1,current_checkpoint_hash=%s
                WHERE opening_run_id=%s
                """,
                [checkpoint_1_hash, opening_run_id],
            )
            connection.execute(
                """
                INSERT INTO authority_book_opening_semantic_checkpoint(
                    checkpoint_id,opening_run_id,opening_execution_id,
                    execution_generation,checkpoint_sequence,semantic_work_key,
                    owning_authority,evidence_type,evidence_id,evidence_version,
                    evidence_hash,frozen_request_digest,
                    predecessor_checkpoint_id,predecessor_checkpoint_sequence,
                    predecessor_checkpoint_hash,checkpoint_hash
                ) VALUES (
                    'checkpoint:head:2',%s,%s,1,2,'semantic:head:2',
                    'STORY_DESIGN_AUTHORITY','ASSET_VERSION','evidence:head:2',1,
                    %s,%s,'checkpoint:head:1',1,%s,%s
                )
                """,
                [
                    opening_run_id,
                    execution_id,
                    "sha256:" + "e" * 64,
                    request_digest,
                    checkpoint_1_hash,
                    checkpoint_2_hash,
                ],
            )
            connection.execute(
                """
                UPDATE authority_book_opening_run
                SET current_checkpoint_id='checkpoint:head:2',
                    current_checkpoint_sequence=2,current_checkpoint_hash=%s
                WHERE opening_run_id=%s
                """,
                [checkpoint_2_hash, opening_run_id],
            )
        with self.assertRaises(psycopg.errors.CheckViolation) as rolled_back:
            with psycopg.connect(self.test_url) as connection:
                connection.execute(
                    """
                    UPDATE authority_book_opening_run
                    SET current_checkpoint_id='checkpoint:head:1',
                        current_checkpoint_sequence=1,current_checkpoint_hash=%s
                    WHERE opening_run_id=%s
                    """,
                    [checkpoint_1_hash, opening_run_id],
                )
        self.assertIn(
            "BOOK_OPENING_CHECKPOINT_HEAD_NON_MONOTONIC",
            str(rolled_back.exception),
        )

    def test_0102_execution_and_checkpoint_digest_mismatch_are_rejected(
        self,
    ) -> None:
        project_id, opening_run_id, runtime_job_id, execution_id = (
            self._seed_v2_scheduled_opening()
        )
        with self.assertRaises(psycopg.errors.CheckViolation) as checkpoint_drift:
            with psycopg.connect(self.test_url) as connection:
                connection.execute(
                    """
                    INSERT INTO authority_book_opening_semantic_checkpoint(
                        checkpoint_id,opening_run_id,opening_execution_id,
                        execution_generation,checkpoint_sequence,
                        semantic_work_key,owning_authority,evidence_type,
                        evidence_id,evidence_version,evidence_hash,
                        frozen_request_digest,checkpoint_hash
                    ) VALUES (
                        'checkpoint:digest-drift',%s,%s,1,1,'semantic:digest',
                        'STORY_DESIGN_AUTHORITY','ASSET_VERSION',
                        'evidence:digest',1,%s,%s,%s
                    )
                    """,
                    [
                        opening_run_id,
                        execution_id,
                        "sha256:" + "b" * 64,
                        "sha256:" + "9" * 64,
                        "sha256:" + "c" * 64,
                    ],
                )
        self.assertIn(
            "BOOK_OPENING_CHECKPOINT_BINDING_INVALID",
            str(checkpoint_drift.exception),
        )

        self._abort_unclaimed_opening_execution(
            opening_run_id=opening_run_id,
            runtime_job_id=runtime_job_id,
            execution_id=execution_id,
        )
        with self.assertRaises(psycopg.errors.CheckViolation) as execution_drift:
            with psycopg.connect(self.test_url) as connection:
                with connection.cursor() as cursor:
                    self._write_recovery_admission(
                        cursor,
                        project_id=project_id,
                        opening_run_id=opening_run_id,
                        predecessor_execution_id=execution_id,
                        suffix="execution-digest-drift",
                        frozen_request_digest="sha256:" + "9" * 64,
                    )
        self.assertIn(
            "BOOK_OPENING_RELATIONAL_CLOSURE_INVALID",
            str(execution_drift.exception),
        )

    def test_0102_non_current_active_recovery_execution_cannot_commit(
        self,
    ) -> None:
        project_id, opening_run_id, runtime_job_id, execution_id = (
            self._seed_v2_scheduled_opening()
        )
        self._abort_unclaimed_opening_execution(
            opening_run_id=opening_run_id,
            runtime_job_id=runtime_job_id,
            execution_id=execution_id,
        )
        with self.assertRaises(psycopg.errors.CheckViolation) as orphan:
            with psycopg.connect(self.test_url) as connection:
                with connection.cursor() as cursor:
                    self._write_recovery_admission(
                        cursor,
                        project_id=project_id,
                        opening_run_id=opening_run_id,
                        predecessor_execution_id=execution_id,
                        suffix="non-current-active",
                        update_opening_head=False,
                    )
        self.assertTrue(
            "BOOK_OPENING_RELATIONAL_CLOSURE_INVALID" in str(orphan.exception)
            or "BOOK_OPENING_RECOVERY_RECEIPT_OPENING_BINDING_INVALID"
            in str(orphan.exception)
        )

    def test_0102_semantic_replacement_rejects_wrong_intent_scope_and_predecessor(
        self,
    ) -> None:
        project_id, opening_run_id, runtime_job_id, execution_id = (
            self._seed_v2_scheduled_opening()
        )
        book_id = "book:migration-relational-closure"
        other_book_id = "book:migration-relational-closure:other"
        candidate_asset_id = "asset:migration-semantic-candidate"
        candidate_version_id = "asset-version:migration-semantic-candidate"
        candidate_hash = "sha256:" + "d" * 64
        evaluation_1_id = "narrative-evaluation:migration-guard:1"
        operation_1_id = "operation:migration-semantic-guard:1"
        intent_id = "intent:semantic-lineage-guard"
        with psycopg.connect(self.test_url) as connection:
            connection.execute(
                """
                INSERT INTO authority_operation_definition(
                    name,definition_version,family,enabled,command_schema,
                    result_schema,policy,completion_contract
                ) VALUES (
                    'story_design.semantic_evaluate','1.0.0',
                    'migration-fixture',TRUE,'{}'::jsonb,'{}'::jsonb,
                    '{}'::jsonb,'{}'::jsonb
                )
                """
            )
            connection.execute(
                """
                INSERT INTO authority_asset(asset_id,project_id,asset_type)
                VALUES ('asset:migration-relational-book:other',%s,'book_record')
                """,
                [project_id],
            )
            connection.execute(
                """
                INSERT INTO authority_asset_version(
                    asset_version_id,asset_id,version_number,lifecycle,
                    eligibility,governance,content,content_hash,schema_version
                ) VALUES (
                    'asset:migration-relational-book:other:v1',
                    'asset:migration-relational-book:other',1,'ACTIVE',
                    'ELIGIBLE','CLEAR','{}'::jsonb,%s,
                    'migration-relational-closure.v1'
                )
                """,
                ["sha256:" + "8" * 64],
            )
            connection.execute(
                """
                INSERT INTO authority_book(
                    book_id,project_id,workspace_id,principal_id,
                    service_identity,book_scope,production_profile,
                    runtime_policy,release_identity,status,
                    current_book_asset_version_id,created_by_operation_id,
                    last_operation_id
                )
                SELECT %s,project_id,workspace_id,principal_id,
                       service_identity,book_scope,production_profile,
                       runtime_policy,release_identity,status,
                       'asset:migration-relational-book:other:v1',
                       created_by_operation_id,
                       last_operation_id
                FROM authority_book WHERE book_id=%s
                """,
                [other_book_id, book_id],
            )
            connection.execute(
                """
                INSERT INTO authority_asset(asset_id,project_id,asset_type)
                VALUES (%s,%s,'book_design')
                """,
                [candidate_asset_id, project_id],
            )
            connection.execute(
                """
                INSERT INTO authority_asset_version(
                    asset_version_id,asset_id,version_number,lifecycle,
                    eligibility,governance,content,content_hash,schema_version
                ) VALUES (
                    %s,%s,1,'CANDIDATE','ELIGIBLE','CLEAR','{}'::jsonb,%s,
                    'story-design-authority.v1'
                )
                """,
                [candidate_version_id, candidate_asset_id, candidate_hash],
            )
            connection.execute(
                """
                INSERT INTO authority_operation(
                    operation_id,definition_name,definition_version,project_id,
                    workspace_id,actor_id,status,root_operation_id,
                    idempotency_scope,idempotency_key,request_digest,
                    definition_snapshot,completion_contract_snapshot,
                    policy_snapshot,concurrency_key,command_payload
                ) VALUES (
                    %s,'story_design.semantic_evaluate','1.0.0',%s,
                    'workspace:migration-relational-closure','migration-fixture',
                    'CANCELLED',%s,'book:narrative-semantic-evaluation',%s,%s,
                    '{}'::jsonb,'{}'::jsonb,'{}'::jsonb,%s,'{}'::jsonb
                )
                """,
                [
                    operation_1_id,
                    project_id,
                    operation_1_id,
                    f"{candidate_version_id}:semantic-evaluation:generation:1",
                    "sha256:" + "e" * 64,
                    f"book:{book_id}:evaluation:{candidate_version_id}:generation:1",
                ],
            )
            connection.execute(
                """
                INSERT INTO authority_narrative_evaluation_execution(
                    evaluation_execution_id,project_id,book_id,
                    candidate_asset_version_id,candidate_content_hash,
                    generation,operation_id,idempotency_scope,idempotency_key,
                    concurrency_key,lifecycle,terminal_reason,terminal_at
                ) VALUES (
                    %s,%s,%s,%s,%s,1,%s,
                    'book:narrative-semantic-evaluation',%s,%s,'CANCELLED',
                    '{"code":"MIGRATION_GUARD_FIXTURE"}'::jsonb,
                    transaction_timestamp()
                )
                """,
                [
                    evaluation_1_id,
                    project_id,
                    book_id,
                    candidate_version_id,
                    candidate_hash,
                    operation_1_id,
                    f"{candidate_version_id}:semantic-evaluation:generation:1",
                    f"book:{book_id}:evaluation:{candidate_version_id}:generation:1",
                ],
            )
            connection.execute(
                """
                INSERT INTO authority_narrative_evaluation_execution_head(
                    project_id,candidate_asset_version_id,current_execution_id,
                    current_generation
                ) VALUES (%s,%s,%s,1)
                """,
                [project_id, candidate_version_id, evaluation_1_id],
            )

        self._abort_unclaimed_opening_execution(
            opening_run_id=opening_run_id,
            runtime_job_id=runtime_job_id,
            execution_id=execution_id,
        )
        semantic_snapshot = {
            "semantic_evaluation": {
                "evaluation_execution_id": evaluation_1_id,
                "generation": "1",
                "operation_id": operation_1_id,
                "candidate_asset_version_id": candidate_version_id,
            }
        }
        with psycopg.connect(self.test_url) as connection:
            with connection.cursor() as cursor:
                _assessment, actual_intent_id, _receipt, _successor = (
                    self._write_recovery_admission(
                        cursor,
                        project_id=project_id,
                        opening_run_id=opening_run_id,
                        predecessor_execution_id=execution_id,
                        suffix="semantic-lineage-guard",
                        snapshot=semantic_snapshot,
                    )
                )
        self.assertEqual(actual_intent_id, intent_id)

        for replacement_book_id, predecessor_id, suffix in (
            (
                book_id,
                "narrative-evaluation:migration-guard:wrong",
                "wrong-predecessor",
            ),
            (other_book_id, evaluation_1_id, "wrong-book"),
        ):
            with self.subTest(case=suffix):
                operation_2_id = f"operation:migration-semantic-guard:2:{suffix}"
                evaluation_2_id = f"narrative-evaluation:migration-guard:2:{suffix}"
                idempotency_key = (
                    f"{candidate_version_id}:semantic-evaluation:generation:2:{suffix}"
                )
                concurrency_key = (
                    f"book:{replacement_book_id}:evaluation:{candidate_version_id}:"
                    f"generation:2:{suffix}"
                )
                with self.assertRaises(psycopg.errors.CheckViolation) as invalid:
                    with psycopg.connect(self.test_url) as connection:
                        connection.execute(
                            """
                            INSERT INTO authority_operation(
                                operation_id,definition_name,definition_version,
                                project_id,workspace_id,actor_id,status,
                                root_operation_id,idempotency_scope,idempotency_key,
                                request_digest,definition_snapshot,
                                completion_contract_snapshot,policy_snapshot,
                                concurrency_key,command_payload
                            ) VALUES (
                                %s,'story_design.semantic_evaluate','1.0.0',%s,
                                'workspace:migration-relational-closure',
                                'migration-fixture','ADMITTED',%s,
                                'book:narrative-semantic-evaluation',%s,%s,
                                '{}'::jsonb,'{}'::jsonb,'{}'::jsonb,%s,
                                '{}'::jsonb
                            )
                            """,
                            [
                                operation_2_id,
                                project_id,
                                operation_2_id,
                                idempotency_key,
                                "sha256:" + "f" * 64,
                                concurrency_key,
                            ],
                        )
                        connection.execute(
                            """
                            INSERT INTO authority_narrative_evaluation_execution(
                                evaluation_execution_id,project_id,book_id,
                                candidate_asset_version_id,candidate_content_hash,
                                generation,predecessor_execution_id,
                                predecessor_generation,predecessor_operation_id,
                                recovery_intent_id,operation_id,idempotency_scope,
                                idempotency_key,concurrency_key,lifecycle
                            ) VALUES (
                                %s,%s,%s,%s,%s,2,%s,1,%s,%s,%s,
                                'book:narrative-semantic-evaluation',%s,%s,
                                'ADMITTED'
                            )
                            """,
                            [
                                evaluation_2_id,
                                project_id,
                                replacement_book_id,
                                candidate_version_id,
                                candidate_hash,
                                predecessor_id,
                                operation_1_id,
                                intent_id,
                                operation_2_id,
                                idempotency_key,
                                concurrency_key,
                            ],
                        )
                self.assertIn(
                    "NARRATIVE_EVALUATION_RECOVERY_INTENT_BINDING_INVALID",
                    str(invalid.exception),
                )

    def test_0102_semantic_work_key_cannot_rebind_to_different_evidence(
        self,
    ) -> None:
        _project_id, opening_run_id, _runtime_job_id, execution_id = (
            self._seed_v2_scheduled_opening()
        )
        with self.assertRaises(psycopg.errors.UniqueViolation):
            with psycopg.connect(self.test_url) as connection:
                connection.execute(
                    """
                    INSERT INTO authority_book_opening_semantic_checkpoint(
                        checkpoint_id,opening_run_id,opening_execution_id,
                        execution_generation,checkpoint_sequence,
                        semantic_work_key,owning_authority,evidence_type,
                        evidence_id,evidence_version,evidence_hash,
                        frozen_request_digest,checkpoint_hash
                    ) VALUES (
                        'checkpoint:work-key:1',%s,%s,1,1,'semantic:once',
                        'STORY_DESIGN_AUTHORITY','ASSET_VERSION','evidence:1',1,
                        %s,%s,%s
                    )
                    """,
                    [
                        opening_run_id,
                        execution_id,
                        "sha256:" + "b" * 64,
                        "sha256:" + "1" * 64,
                        "sha256:" + "c" * 64,
                    ],
                )
                connection.execute(
                    """
                    INSERT INTO authority_book_opening_semantic_checkpoint(
                        checkpoint_id,opening_run_id,opening_execution_id,
                        execution_generation,checkpoint_sequence,
                        semantic_work_key,owning_authority,evidence_type,
                        evidence_id,evidence_version,evidence_hash,
                        frozen_request_digest,predecessor_checkpoint_id,
                        predecessor_checkpoint_sequence,
                        predecessor_checkpoint_hash,checkpoint_hash
                    ) VALUES (
                        'checkpoint:work-key:2',%s,%s,1,2,'semantic:once',
                        'STORY_DESIGN_AUTHORITY','ASSET_VERSION','evidence:2',1,
                        %s,%s,'checkpoint:work-key:1',1,%s,%s
                    )
                    """,
                    [
                        opening_run_id,
                        execution_id,
                        "sha256:" + "d" * 64,
                        "sha256:" + "1" * 64,
                        "sha256:" + "c" * 64,
                        "sha256:" + "e" * 64,
                    ],
                )

    def test_0102_legacy_terminal_execution_can_preserve_missing_runtime_job(
        self,
    ) -> None:
        _project_id, source_opening_id, runtime_job_id, source_execution_id = (
            self._seed_v2_scheduled_opening()
        )
        self._abort_unclaimed_opening_execution(
            opening_run_id=source_opening_id,
            runtime_job_id=runtime_job_id,
            execution_id=source_execution_id,
            opening_lifecycle="ABORTED",
        )
        for lifecycle in ("FAILED", "ABORTED"):
            suffix = lifecycle.lower()
            opening_run_id = f"book-opening:legacy-unbound:{suffix}"
            execution_id = f"book-opening-execution:legacy-unbound:{suffix}:1"
            operation_id = f"operation:legacy-unbound:{suffix}"
            with self.subTest(lifecycle=lifecycle):
                with psycopg.connect(self.test_url) as connection:
                    connection.execute(
                        """
                        INSERT INTO authority_operation(
                            operation_id,definition_name,definition_version,
                            project_id,workspace_id,actor_id,status,
                            root_operation_id,idempotency_scope,idempotency_key,
                            request_digest,definition_snapshot,
                            completion_contract_snapshot,policy_snapshot,
                            concurrency_key,command_payload
                        )
                        SELECT %s,definition_name,definition_version,project_id,
                               workspace_id,actor_id,'ADMITTED',%s,
                               idempotency_scope,%s,%s,definition_snapshot,
                               completion_contract_snapshot,policy_snapshot,%s,
                               command_payload
                        FROM authority_operation
                        WHERE operation_id=(
                            SELECT root_operation_id
                            FROM authority_book_opening_run
                            WHERE opening_run_id=%s
                        )
                        """,
                        [
                            operation_id,
                            operation_id,
                            operation_id,
                            "sha256:" + "5" * 64,
                            f"fixture:{operation_id}",
                            source_opening_id,
                        ],
                    )
                    connection.execute(
                        """
                        INSERT INTO authority_book_opening_run(
                            opening_run_id,project_id,workspace_id,book_id,
                            root_operation_id,stable_idempotency_key,lifecycle,
                            frozen_request,frozen_request_digest,
                            execution_contract_version,recovery_state,
                            workflow_contract_version,
                            workflow_graph_revision,workflow_graph_hash,
                            current_execution_id,current_execution_generation
                        )
                        SELECT %s,project_id,workspace_id,book_id,
                               %s,%s,%s,
                               jsonb_build_object(
                                   'project_id',project_id,
                                   'workspace_id',workspace_id,
                                   'book_id',book_id,
                                   'idempotency_key',%s::text
                               ),%s,'book-opening-execution-v2',
                               'RECOVERY_REQUIRED','legacy-monolithic-v2',0,'',
                               %s,1
                        FROM authority_book_opening_run
                        WHERE opening_run_id=%s
                        """,
                        [
                            opening_run_id,
                            operation_id,
                            opening_run_id,
                            lifecycle,
                            opening_run_id,
                            "sha256:" + "1" * 64,
                            execution_id,
                            source_opening_id,
                        ],
                    )
                    connection.execute(
                        """
                        INSERT INTO authority_book_opening_execution(
                            opening_execution_id,opening_run_id,generation,
                            runtime_job_id,lifecycle,frozen_request_digest,
                            input_snapshot_hash,policy_snapshot_hash,
                            authority_contract_hash,terminal_reason,terminal_at
                        ) VALUES (
                            %s,%s,1,NULL,%s,%s,%s,%s,%s,
                            '{"code":"LEGACY_RUNTIME_JOB_MISSING"}'::jsonb,
                            transaction_timestamp()
                        )
                        """,
                        [
                            execution_id,
                            opening_run_id,
                            lifecycle,
                            "sha256:" + "1" * 64,
                            "sha256:" + "2" * 64,
                            "sha256:" + "3" * 64,
                            "sha256:" + "4" * 64,
                        ],
                    )
        with psycopg.connect(self.test_url) as connection:
            preserved = connection.execute(
                """
                SELECT opening.lifecycle,execution.lifecycle,
                       execution.runtime_job_id,
                       execution.current_attempt_id
                FROM authority_book_opening_run AS opening
                JOIN authority_book_opening_execution AS execution
                  ON execution.opening_execution_id=opening.current_execution_id
                WHERE opening.opening_run_id LIKE
                      'book-opening:legacy-unbound:%'
                ORDER BY execution.lifecycle
                """
            ).fetchall()
        self.assertEqual(
            preserved,
            [
                ("ABORTED", "ABORTED", None, None),
                ("FAILED", "FAILED", None, None),
            ],
        )

        with self.assertRaises(psycopg.errors.CheckViolation):
            with psycopg.connect(self.test_url) as connection:
                connection.execute(
                    """
                    INSERT INTO authority_book_opening_execution(
                        opening_execution_id,opening_run_id,generation,
                        runtime_job_id,lifecycle,frozen_request_digest,
                        input_snapshot_hash,policy_snapshot_hash,
                        authority_contract_hash
                    ) VALUES (
                        'book-opening-execution:invalid-unbound:2',%s,2,NULL,
                        'RUNNING',%s,%s,%s,%s
                    )
                    """,
                    [
                        source_opening_id,
                        "sha256:" + "1" * 64,
                        "sha256:" + "2" * 64,
                        "sha256:" + "3" * 64,
                        "sha256:" + "4" * 64,
                    ],
                )

    def test_0102_failed_execution_accepts_dead_letter_runtime_terminal_truth(
        self,
    ) -> None:
        _project_id, opening_run_id, runtime_job_id, execution_id = (
            self._seed_v2_scheduled_opening()
        )
        claim = self._claim_and_bind_opening_execution(
            runtime_job_id=runtime_job_id,
            execution_id=execution_id,
            worker_id="dead-letter-worker",
        )
        with psycopg.connect(self.test_url) as connection:
            connection.execute(
                """
                UPDATE authority_runtime_job_lease
                SET status='RELEASED',released_at=transaction_timestamp(),
                    release_reason='dead_letter'
                WHERE lease_id=%s
                """,
                [claim.lease_id],
            )
            connection.execute(
                """
                UPDATE authority_runtime_job_attempt
                SET status='FAILED',completed_at=transaction_timestamp(),
                    error='{"code":"DEAD_LETTER"}'::jsonb
                WHERE attempt_id=%s
                """,
                [claim.attempt_id],
            )
            connection.execute(
                """
                UPDATE authority_runtime_job
                SET status='DEAD_LETTER',claimed_by='',
                    last_error='{"code":"DEAD_LETTER"}'::jsonb,
                    completed_at=transaction_timestamp(),
                    updated_at=transaction_timestamp()
                WHERE runtime_job_id=%s
                """,
                [runtime_job_id],
            )
            connection.execute(
                """
                UPDATE authority_book_opening_execution
                SET lifecycle='FAILED',terminal_at=transaction_timestamp(),
                    terminal_reason='{"code":"DEAD_LETTER"}'::jsonb,
                    version=version+1,updated_at=transaction_timestamp()
                WHERE opening_execution_id=%s
                """,
                [execution_id],
            )
            connection.execute(
                """
                UPDATE authority_book_opening_run
                SET lifecycle='FAILED',recovery_state='RECOVERY_REQUIRED',
                    version=version+1,updated_at=transaction_timestamp()
                WHERE opening_run_id=%s
                """,
                [opening_run_id],
            )

    def test_0102_failed_opening_accepts_aborted_execution_and_cancelled_job(
        self,
    ) -> None:
        _project_id, opening_run_id, runtime_job_id, execution_id = (
            self._seed_v2_scheduled_opening()
        )
        claim = self._claim_and_bind_opening_execution(
            runtime_job_id=runtime_job_id,
            execution_id=execution_id,
            worker_id="aborted-worker",
        )
        with psycopg.connect(self.test_url) as connection:
            connection.execute(
                """
                UPDATE authority_runtime_job_lease
                SET status='RELEASED',released_at=transaction_timestamp(),
                    release_reason='aborted'
                WHERE lease_id=%s
                """,
                [claim.lease_id],
            )
            connection.execute(
                """
                UPDATE authority_runtime_job_attempt
                SET status='ABANDONED',completed_at=transaction_timestamp(),
                    error='{"code":"ABORTED"}'::jsonb
                WHERE attempt_id=%s
                """,
                [claim.attempt_id],
            )
            connection.execute(
                """
                UPDATE authority_runtime_job
                SET status='CANCELLED',claimed_by='',
                    last_error='{"code":"ABORTED"}'::jsonb,
                    completed_at=transaction_timestamp(),
                    updated_at=transaction_timestamp()
                WHERE runtime_job_id=%s
                """,
                [runtime_job_id],
            )
            connection.execute(
                """
                UPDATE authority_book_opening_execution
                SET lifecycle='ABORTED',terminal_at=transaction_timestamp(),
                    terminal_reason='{"code":"ABORTED"}'::jsonb,
                    version=version+1,updated_at=transaction_timestamp()
                WHERE opening_execution_id=%s
                """,
                [execution_id],
            )
            connection.execute(
                """
                UPDATE authority_book_opening_run
                SET lifecycle='FAILED',recovery_state='RECOVERY_REQUIRED',
                    version=version+1,updated_at=transaction_timestamp()
                WHERE opening_run_id=%s
                """,
                [opening_run_id],
            )

    def test_0102_deferred_guards_close_relational_identity_without_clock_truth(
        self,
    ) -> None:
        project_id, opening_run_id, runtime_job_id, execution_id = (
            self._seed_v2_scheduled_opening()
        )
        runtime_jobs = RuntimeJobAuthority(self.test_url)
        with AuthorityUnitOfWork(self.test_url) as uow:
            claim = runtime_jobs.claim_ready_in_uow(
                uow,
                runtime_job_id=runtime_job_id,
                worker_id="migration-relational-worker",
                lease_seconds=60,
            )
            uow.cursor.execute(
                """
                UPDATE authority_book_opening_execution
                SET current_attempt_id=%s,current_lease_id=%s,
                    current_worker_id=%s,current_fencing_token=%s,
                    lifecycle='BOUND',version=version+1,
                    updated_at=transaction_timestamp()
                WHERE opening_execution_id=%s AND lifecycle='SCHEDULED'
                """,
                [
                    claim.attempt_id,
                    claim.lease_id,
                    claim.worker_id,
                    claim.fencing_token,
                    execution_id,
                ],
            )
            self.assertEqual(uow.cursor.rowcount, 1)
            uow.commit()

        # Temporal validity remains a runtime-path responsibility.  A held but
        # expired Lease is still relationally exact, so the deferred guard must
        # accept the binding and leave the loss sweeper to converge it.
        with psycopg.connect(self.test_url) as connection:
            connection.execute(
                """
                UPDATE authority_runtime_job_lease
                SET lease_expires_at=transaction_timestamp()-INTERVAL '1 second'
                WHERE lease_id=%s
                """,
                [claim.lease_id],
            )
            connection.execute(
                """
                UPDATE authority_runtime_job_attempt
                SET lease_expires_at=transaction_timestamp()-INTERVAL '1 second'
                WHERE attempt_id=%s
                """,
                [claim.attempt_id],
            )
            connection.execute(
                """
                UPDATE authority_book_opening_execution
                SET current_attempt_id=%s,current_lease_id=%s,
                    current_worker_id=%s,current_fencing_token=%s,
                    lifecycle='RUNNING',version=version+1,
                    started_at=transaction_timestamp(),
                    updated_at=transaction_timestamp()
                WHERE opening_execution_id=%s AND lifecycle='BOUND'
                """,
                [
                    claim.attempt_id,
                    claim.lease_id,
                    claim.worker_id,
                    claim.fencing_token,
                    execution_id,
                ],
            )
            connection.execute(
                """
                UPDATE authority_book_opening_run
                SET lifecycle='RUNNING',updated_at=transaction_timestamp()
                WHERE opening_run_id=%s AND lifecycle='ADMITTED'
                """,
                [opening_run_id],
            )

        with psycopg.connect(self.test_url) as connection:
            exact = connection.execute(
                """
                SELECT opening.lifecycle,execution.lifecycle,job.status,
                       attempt.status,lease.status,
                       lease.lease_expires_at < transaction_timestamp(),
                       execution.current_attempt_id=job.current_attempt_id,
                       execution.current_fencing_token=job.current_fencing_token,
                       execution.current_worker_id=job.claimed_by
                FROM authority_book_opening_run AS opening
                JOIN authority_book_opening_execution AS execution
                  ON execution.opening_execution_id=opening.current_execution_id
                JOIN authority_runtime_job AS job
                  ON job.runtime_job_id=execution.runtime_job_id
                JOIN authority_runtime_job_attempt AS attempt
                  ON attempt.attempt_id=execution.current_attempt_id
                JOIN authority_runtime_job_lease AS lease
                  ON lease.lease_id=execution.current_lease_id
                WHERE opening.opening_run_id=%s
                """,
                [opening_run_id],
            ).fetchone()
        self.assertEqual(
            exact,
            (
                "RUNNING",
                "RUNNING",
                "CLAIMED",
                "CLAIMED",
                "HELD",
                True,
                True,
                True,
                True,
            ),
        )

        with self.assertRaises(psycopg.errors.CheckViolation) as claim_drift:
            with psycopg.connect(self.test_url) as connection:
                connection.execute(
                    """
                    UPDATE authority_runtime_job
                    SET claimed_by='migration-intruder'
                    WHERE runtime_job_id=%s
                    """,
                    [runtime_job_id],
                )
        self.assertIn(
            "RUNTIME_JOB_CURRENT_CLAIM_IDENTITY_INVALID",
            str(claim_drift.exception),
        )

        with self.assertRaises(psycopg.errors.CheckViolation) as lifecycle_drift:
            with psycopg.connect(self.test_url) as connection:
                connection.execute(
                    """
                    UPDATE authority_book_opening_run SET lifecycle='COMPLETE'
                    WHERE opening_run_id=%s
                    """,
                    [opening_run_id],
                )
        self.assertIn(
            "BOOK_OPENING_RELATIONAL_CLOSURE_INVALID",
            str(lifecycle_drift.exception),
        )

        with psycopg.connect(self.test_url) as connection:
            connection.execute(
                """
                UPDATE authority_runtime_job_lease
                SET status='EXPIRED',released_at=transaction_timestamp(),
                    release_reason='migration-relational-loss'
                WHERE lease_id=%s AND status='HELD'
                """,
                [claim.lease_id],
            )
            connection.execute(
                """
                UPDATE authority_runtime_job_attempt
                SET status='ABANDONED',completed_at=transaction_timestamp(),
                    error='{"code":"MIGRATION_RELATIONAL_LOSS"}'::jsonb
                WHERE attempt_id=%s AND status='CLAIMED'
                """,
                [claim.attempt_id],
            )
            connection.execute(
                """
                UPDATE authority_runtime_job
                SET status='FAILED',claimed_by='',
                    last_error='{"code":"MIGRATION_RELATIONAL_LOSS"}'::jsonb,
                    completed_at=transaction_timestamp(),
                    updated_at=transaction_timestamp()
                WHERE runtime_job_id=%s AND status='CLAIMED'
                """,
                [runtime_job_id],
            )
            connection.execute(
                """
                UPDATE authority_book_opening_execution
                SET lifecycle='LOST',
                    terminal_reason='{"code":"MIGRATION_RELATIONAL_LOSS"}'::jsonb,
                    terminal_at=transaction_timestamp(),version=version+1,
                    updated_at=transaction_timestamp()
                WHERE opening_execution_id=%s AND lifecycle='RUNNING'
                """,
                [execution_id],
            )
            connection.execute(
                """
                UPDATE authority_book_opening_run
                SET lifecycle='FAILED',recovery_state='RECOVERY_REQUIRED',
                    version=version+1,updated_at=transaction_timestamp()
                WHERE opening_run_id=%s AND lifecycle='RUNNING'
                """,
                [opening_run_id],
            )

        for table, identity_column, identity, mutation in (
            (
                "authority_runtime_job",
                "runtime_job_id",
                runtime_job_id,
                "last_error='{}'::jsonb",
            ),
            (
                "authority_runtime_job_attempt",
                "attempt_id",
                claim.attempt_id,
                "error='{}'::jsonb",
            ),
            (
                "authority_runtime_job_lease",
                "lease_id",
                claim.lease_id,
                "release_reason='rewritten'",
            ),
        ):
            with self.assertRaises(psycopg.errors.CheckViolation):
                with psycopg.connect(self.test_url) as connection:
                    connection.execute(
                        sql.SQL("UPDATE {} SET {} WHERE {}=%s").format(
                            sql.Identifier(table),
                            sql.SQL(mutation),
                            sql.Identifier(identity_column),
                        ),
                        [identity],
                    )

    def test_0102_book_opening_frozen_input_is_database_immutable(self) -> None:
        _, opening_run_id, _, _ = self._seed_v2_scheduled_opening()
        with self.assertRaises(psycopg.errors.CheckViolation) as frozen_drift:
            with psycopg.connect(self.test_url) as connection:
                connection.execute(
                    """
                    UPDATE authority_book_opening_run
                    SET frozen_request=jsonb_set(
                        frozen_request,'{idempotency_key}',
                        '"migration-drift"'::jsonb
                    )
                    WHERE opening_run_id=%s
                    """,
                    [opening_run_id],
                )
        self.assertIn(
            "BOOK_OPENING_FROZEN_INPUT_IMMUTABLE",
            str(frozen_drift.exception),
        )

    def test_0102_old_writer_book_opening_insert_is_normalized_in_database(
        self,
    ) -> None:
        status = run_migrations(self.test_url)
        self.assertTrue(status["ok"])
        runtime_job_id = "runtime-job:old-writer-book-opening"
        with psycopg.connect(self.test_url) as connection:
            connection.execute(
                """
                INSERT INTO authority_runtime_job(
                    runtime_job_id,job_kind,runtime_group,subject_kind,
                    subject_id,project_id,dedupe_key,input_snapshot,input_hash
                ) VALUES (
                    %s,'BOOK_OPENING_EXECUTE','book_opening',
                    'BOOK_OPENING_RUN','book-opening:old-writer',
                    'project:old-writer','old-writer-generation-1',
                    '{}'::jsonb,%s
                )
                """,
                [runtime_job_id, "sha256:" + "a" * 64],
            )
        with psycopg.connect(self.test_url) as connection:
            policy = connection.execute(
                """
                SELECT lease_loss_policy,max_attempts,status,attempt_count,
                       current_attempt_id,current_fencing_token
                FROM authority_runtime_job WHERE runtime_job_id=%s
                """,
                [runtime_job_id],
            ).fetchone()
        self.assertEqual(
            policy,
            ("AUTHORITY_CONVERGENCE_REQUIRED", 1, "READY", 0, None, 0),
        )

    def test_0102_old_writer_prebind_claim_rolls_back_and_second_attempt_is_blocked(
        self,
    ) -> None:
        _project_id, _opening_run_id, runtime_job_id, execution_id = (
            self._seed_v2_scheduled_opening()
        )
        old_attempt_id = "runtime-attempt:old-writer-prebind"
        old_lease_id = "runtime-lease:old-writer-prebind"
        with self.assertRaises(psycopg.errors.CheckViolation) as prebind:
            with psycopg.connect(self.test_url) as connection:
                connection.execute(
                    """
                    INSERT INTO authority_runtime_job_attempt(
                        attempt_id,runtime_job_id,attempt_number,worker_id,
                        status,lease_id,fencing_token,lease_expires_at,
                        heartbeat_at
                    ) VALUES (
                        %s,%s,1,'old-writer','CLAIMED',%s,1,
                        transaction_timestamp()+INTERVAL '60 seconds',
                        transaction_timestamp()
                    )
                    """,
                    [old_attempt_id, runtime_job_id, old_lease_id],
                )
                connection.execute(
                    """
                    INSERT INTO authority_runtime_job_lease(
                        lease_id,runtime_job_id,attempt_id,worker_id,
                        fencing_token,lease_expires_at,heartbeat_at,status
                    ) VALUES (
                        %s,%s,%s,'old-writer',1,
                        transaction_timestamp()+INTERVAL '60 seconds',
                        transaction_timestamp(),'HELD'
                    )
                    """,
                    [old_lease_id, runtime_job_id, old_attempt_id],
                )
                connection.execute(
                    """
                    UPDATE authority_runtime_job
                    SET status='CLAIMED',claimed_by='old-writer',
                        current_attempt_id=%s,current_fencing_token=1,
                        attempt_count=1,updated_at=transaction_timestamp()
                    WHERE runtime_job_id=%s AND status='READY'
                    """,
                    [old_attempt_id, runtime_job_id],
                )
        self.assertIn("BOOK_OPENING_RELATIONAL_CLOSURE_INVALID", str(prebind.exception))
        with psycopg.connect(self.test_url) as connection:
            rolled_back = connection.execute(
                """
                SELECT job.status,job.attempt_count,job.current_attempt_id,
                       (SELECT COUNT(*) FROM authority_runtime_job_attempt
                        WHERE runtime_job_id=job.runtime_job_id),
                       (SELECT COUNT(*) FROM authority_runtime_job_lease
                        WHERE runtime_job_id=job.runtime_job_id)
                FROM authority_runtime_job AS job
                WHERE job.runtime_job_id=%s
                """,
                [runtime_job_id],
            ).fetchone()
        self.assertEqual(rolled_back, ("READY", 0, None, 0, 0))

        runtime_jobs = RuntimeJobAuthority(self.test_url)
        with AuthorityUnitOfWork(self.test_url) as uow:
            claim = runtime_jobs.claim_ready_in_uow(
                uow,
                runtime_job_id=runtime_job_id,
                worker_id="coordinator-worker",
                lease_seconds=60,
            )
            uow.cursor.execute(
                """
                UPDATE authority_book_opening_execution
                SET current_attempt_id=%s,current_lease_id=%s,
                    current_worker_id=%s,current_fencing_token=%s,
                    lifecycle='BOUND',version=version+1,
                    updated_at=transaction_timestamp()
                WHERE opening_execution_id=%s AND lifecycle='SCHEDULED'
                """,
                [
                    claim.attempt_id,
                    claim.lease_id,
                    claim.worker_id,
                    claim.fencing_token,
                    execution_id,
                ],
            )
            self.assertEqual(uow.cursor.rowcount, 1)
            uow.commit()

        with self.assertRaises(psycopg.errors.CheckViolation) as replacement:
            with psycopg.connect(self.test_url) as connection:
                connection.execute(
                    """
                    INSERT INTO authority_runtime_job_attempt(
                        attempt_id,runtime_job_id,attempt_number,worker_id,
                        status,lease_id,fencing_token,lease_expires_at,
                        heartbeat_at
                    ) VALUES (
                        'runtime-attempt:forbidden-second',%s,2,
                        'old-takeover-worker','CLAIMED',
                        'runtime-lease:forbidden-second',2,
                        transaction_timestamp()+INTERVAL '60 seconds',
                        transaction_timestamp()
                    )
                    """,
                    [runtime_job_id],
                )
                connection.execute(
                    """
                    INSERT INTO authority_runtime_job_lease(
                        lease_id,runtime_job_id,attempt_id,worker_id,
                        fencing_token,lease_expires_at,heartbeat_at,status
                    ) VALUES (
                        'runtime-lease:forbidden-second',%s,
                        'runtime-attempt:forbidden-second',
                        'old-takeover-worker',2,
                        transaction_timestamp()+INTERVAL '60 seconds',
                        transaction_timestamp(),'HELD'
                    )
                    """,
                    [runtime_job_id],
                )
        self.assertIn(
            "RUNTIME_JOB_AUTHORITY_ATTEMPT_REPLACEMENT_FORBIDDEN",
            str(replacement.exception),
        )
        with psycopg.connect(self.test_url) as connection:
            attempt_count = connection.execute(
                "SELECT COUNT(*) FROM authority_runtime_job_attempt "
                "WHERE runtime_job_id=%s",
                [runtime_job_id],
            ).fetchone()[0]
        self.assertEqual(attempt_count, 1)

    def test_0102_upgrade_preserves_terminal_runtime_execution_history(self) -> None:
        runtime_job_id = "runtime-job:legacy-terminal-opening"
        attempt_id = "runtime-attempt:legacy-terminal-opening"
        lease_id = "runtime-lease:legacy-terminal-opening"
        result_hash = "sha256:" + "d" * 64
        with (
            psycopg.connect(self.test_url) as connection,
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
            for migration in MIGRATIONS:
                if (
                    migration.migration_id
                    == "20260828_0102_book_opening_recovery_closure"
                ):
                    break
                for statement in migration.upgrade_statements:
                    cursor.execute(statement)
                cursor.execute(
                    "INSERT INTO nf_schema_migrations(migration_id) VALUES (%s)",
                    [migration.migration_id],
                )
            cursor.execute(
                """
                INSERT INTO authority_runtime_job(
                    runtime_job_id,job_kind,runtime_group,subject_kind,
                    subject_id,project_id,dedupe_key,input_snapshot,input_hash,
                    status,attempt_count,max_attempts,claimed_by,
                    current_attempt_id,current_fencing_token,result_hash,
                    last_error,created_at,updated_at,completed_at
                ) VALUES (
                    %s,'BOOK_OPENING_EXECUTE','book_opening',
                    'BOOK_OPENING_RUN','book-opening:legacy-terminal',
                    'project:legacy-terminal','legacy-terminal-generation-1',
                    '{}'::jsonb,%s,'FAILED',1,5,'',%s,1,%s,
                    '{"code":"LEGACY_TERMINAL"}'::jsonb,
                    '2026-08-01T00:00:00Z','2026-08-01T00:01:00Z',
                    '2026-08-01T00:01:00Z'
                )
                """,
                [
                    runtime_job_id,
                    "sha256:" + "c" * 64,
                    attempt_id,
                    result_hash,
                ],
            )
            cursor.execute(
                """
                INSERT INTO authority_runtime_job_attempt(
                    attempt_id,runtime_job_id,attempt_number,worker_id,status,
                    lease_id,fencing_token,lease_expires_at,heartbeat_at,
                    result_hash,error,started_at,completed_at
                ) VALUES (
                    %s,%s,1,'legacy-worker','FAILED',%s,1,
                    '2026-08-01T00:00:30Z','2026-08-01T00:00:20Z',%s,
                    '{"code":"LEGACY_TERMINAL"}'::jsonb,
                    '2026-08-01T00:00:00Z','2026-08-01T00:01:00Z'
                )
                """,
                [attempt_id, runtime_job_id, lease_id, result_hash],
            )
            cursor.execute(
                """
                INSERT INTO authority_runtime_job_lease(
                    lease_id,runtime_job_id,attempt_id,worker_id,
                    fencing_token,lease_expires_at,heartbeat_at,status,
                    released_at,release_reason,created_at
                ) VALUES (
                    %s,%s,%s,'legacy-worker',1,
                    '2026-08-01T00:00:30Z','2026-08-01T00:00:20Z',
                    'RELEASED','2026-08-01T00:01:00Z','legacy_failed',
                    '2026-08-01T00:00:00Z'
                )
                """,
                [lease_id, runtime_job_id, attempt_id],
            )
            cursor.execute(
                """
                INSERT INTO authority_runtime_job_result(
                    result_id,runtime_job_id,attempt_id,fencing_token,
                    status,result,result_hash,created_at
                ) VALUES (
                    'runtime-result:legacy-terminal',%s,%s,1,'FAILED',
                    '{"code":"LEGACY_TERMINAL"}'::jsonb,%s,
                    '2026-08-01T00:01:00Z'
                )
                """,
                [runtime_job_id, attempt_id, result_hash],
            )

        status = run_migrations(self.test_url)
        self.assertTrue(status["ok"])
        with psycopg.connect(self.test_url) as connection:
            preserved = connection.execute(
                """
                SELECT job.status,job.attempt_count,job.max_attempts,
                       job.current_attempt_id,job.current_fencing_token,
                       job.result_hash,job.last_error,
                       job.lease_loss_policy,
                       attempt.status,attempt.result_hash,attempt.error,
                       lease.status,lease.release_reason,
                       result.status,result.result_hash,result.result
                FROM authority_runtime_job AS job
                JOIN authority_runtime_job_attempt AS attempt
                  ON attempt.attempt_id=job.current_attempt_id
                JOIN authority_runtime_job_lease AS lease
                  ON lease.lease_id=attempt.lease_id
                JOIN authority_runtime_job_result AS result
                  ON result.attempt_id=attempt.attempt_id
                WHERE job.runtime_job_id=%s
                """,
                [runtime_job_id],
            ).fetchone()
        self.assertEqual(
            preserved,
            (
                "FAILED",
                1,
                5,
                attempt_id,
                1,
                result_hash,
                {"code": "LEGACY_TERMINAL"},
                "AUTHORITY_CONVERGENCE_REQUIRED",
                "FAILED",
                result_hash,
                {"code": "LEGACY_TERMINAL"},
                "RELEASED",
                "legacy_failed",
                "FAILED",
                result_hash,
                {"code": "LEGACY_TERMINAL"},
            ),
        )

    def test_existing_0007_database_upgrades_without_losing_authority_rows(
        self,
    ) -> None:
        operation_id = identifier("existing-operation")
        with (
            psycopg.connect(self.test_url) as connection,
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

    def test_previous_head_disables_legacy_agent_admission_and_upgrades_context_views(
        self,
    ) -> None:
        with (
            psycopg.connect(self.test_url) as connection,
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
            for migration in MIGRATIONS:
                if migration.migration_id == "20260826_0101_quality_qualification":
                    break
                for statement in migration.upgrade_statements:
                    cursor.execute(statement)
                cursor.execute(
                    "INSERT INTO nf_schema_migrations (migration_id) VALUES (%s)",
                    [migration.migration_id],
                )
            for name in (
                "agent.chapter_binding.register",
                "agent.chapter_binding.activate",
                "agent.candidate.execute",
                "agent.session.execute",
            ):
                cursor.execute(
                    """
                    INSERT INTO authority_operation_definition(
                        name, definition_version, family, enabled,
                        command_schema, result_schema, policy,
                        completion_contract
                    ) VALUES (
                        %s, '2.0.0', 'legacy-agent-runtime', TRUE,
                        '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb
                    )
                    """,
                    [name],
                )

        status = run_migrations(self.test_url)

        self.assertTrue(status["ok"])
        with psycopg.connect(self.test_url) as connection:
            legacy = connection.execute(
                """
                SELECT name, enabled
                FROM authority_operation_definition
                WHERE name IN (
                    'agent.chapter_binding.register',
                    'agent.chapter_binding.activate',
                    'agent.candidate.execute',
                    'agent.session.execute'
                )
                ORDER BY name
                """
            ).fetchall()
            transcript_constraint = connection.execute(
                """
                SELECT pg_get_constraintdef(oid)
                FROM pg_constraint
                WHERE conname=
                    'authority_agent_transcript_event_event_type_check'
                """
            ).fetchone()
            context_view = connection.execute(
                "SELECT pg_get_viewdef('authority_context_runtime_usage_projection')"
            ).fetchone()
            mkaos_view = connection.execute(
                "SELECT pg_get_viewdef('authority_mkaos_runtime_selection_projection')"
            ).fetchone()
        self.assertEqual(
            legacy,
            [
                ("agent.candidate.execute", False),
                ("agent.chapter_binding.activate", False),
                ("agent.chapter_binding.register", False),
                ("agent.session.execute", False),
            ],
        )
        self.assertIn("SKILL_ACTIVATED", str(transcript_constraint[0]))
        self.assertIn("authority-context-bundle-v7", str(context_view[0]))
        self.assertIn("narrative-context-manifest-v3", str(context_view[0]))
        self.assertIn("authority-context-bundle-v8", str(context_view[0]))
        self.assertIn("narrative-context-manifest-v4", str(context_view[0]))
        self.assertIn("authority-context-bundle-v7", str(mkaos_view[0]))
        self.assertIn("authority-context-bundle-v8", str(mkaos_view[0]))

    def test_0101_upgrade_bootstraps_semantic_generation_without_rewriting_history(
        self,
    ) -> None:
        project_id = "project:recovery-migration"
        workspace_id = "workspace:recovery-migration"
        book_id = "book:recovery-migration"
        seed_operation_id = "operation:recovery-migration-seed"
        opening_operation_id = "operation:recovery-migration-opening"
        evaluation_operation_id = "operation:recovery-migration-evaluation"
        opening_run_id = "book-opening:recovery-migration"
        runtime_job_id = "runtime-job:recovery-migration-opening"
        candidate_asset_id = "asset:recovery-migration-candidate"
        candidate_version_id = "asset-version:recovery-migration-candidate"
        candidate_hash = "sha256:" + "c" * 64
        frozen_request_digest = "sha256:" + "f" * 64
        with (
            psycopg.connect(self.test_url) as connection,
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
            for migration in MIGRATIONS:
                if (
                    migration.migration_id
                    == "20260828_0102_book_opening_recovery_closure"
                ):
                    break
                for statement in migration.upgrade_statements:
                    cursor.execute(statement)
                cursor.execute(
                    "INSERT INTO nf_schema_migrations (migration_id) VALUES (%s)",
                    [migration.migration_id],
                )
            for definition_name in (
                "fixture.recovery_migration.seed",
                "fixture.recovery_migration.opening",
                "story_design.semantic_evaluate",
            ):
                cursor.execute(
                    """
                    INSERT INTO authority_operation_definition(
                        name, definition_version, family, enabled,
                        command_schema, result_schema, policy,
                        completion_contract
                    ) VALUES (
                        %s, '1.0.0', 'migration-fixture', TRUE,
                        '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb
                    )
                    """,
                    [definition_name],
                )
            for operation_id, definition_name, status in (
                (
                    seed_operation_id,
                    "fixture.recovery_migration.seed",
                    "SUCCEEDED",
                ),
                (
                    opening_operation_id,
                    "fixture.recovery_migration.opening",
                    "EXECUTING",
                ),
            ):
                cursor.execute(
                    """
                    INSERT INTO authority_operation(
                        operation_id, definition_name, definition_version,
                        project_id, workspace_id, actor_id, status,
                        root_operation_id, idempotency_scope, idempotency_key,
                        request_digest, definition_snapshot,
                        completion_contract_snapshot, policy_snapshot,
                        concurrency_key, command_payload
                    ) VALUES (
                        %s,%s,'1.0.0',%s,%s,'migration-fixture',%s,
                        %s,'project:recovery-migration',%s,%s,
                        '{}'::jsonb,'{}'::jsonb,'{}'::jsonb,%s,'{}'::jsonb
                    )
                    """,
                    [
                        operation_id,
                        definition_name,
                        project_id,
                        workspace_id,
                        status,
                        operation_id,
                        operation_id,
                        "sha256:" + hashlib.sha256(operation_id.encode()).hexdigest(),
                        f"fixture:{operation_id}",
                    ],
                )
            for asset_id, asset_type, digest in (
                ("asset:recovery-migration-project", "project_record", "1"),
                ("asset:recovery-migration-workspace", "workspace_record", "2"),
                ("asset:recovery-migration-book", "book_record", "3"),
            ):
                cursor.execute(
                    "INSERT INTO authority_asset(asset_id,project_id,asset_type) "
                    "VALUES (%s,%s,%s)",
                    [asset_id, project_id, asset_type],
                )
                cursor.execute(
                    """
                    INSERT INTO authority_asset_version(
                        asset_version_id,asset_id,version_number,lifecycle,
                        eligibility,governance,content,content_hash,
                        schema_version
                    ) VALUES (
                        %s,%s,1,'ACTIVE','ELIGIBLE','CLEAR','{}'::jsonb,%s,
                        'migration-fixture.v1'
                    )
                    """,
                    [f"{asset_id}:v1", asset_id, "sha256:" + digest * 64],
                )
            cursor.execute(
                """
                INSERT INTO authority_project(
                    project_id,primary_workspace_id,title,status,stage,health,
                    current_asset_version_id,created_by_operation_id,
                    last_operation_id
                ) VALUES (
                    %s,%s,'Recovery Migration','ACTIVE','PLANNING','HEALTHY',
                    'asset:recovery-migration-project:v1',%s,%s
                )
                """,
                [project_id, workspace_id, seed_operation_id, seed_operation_id],
            )
            cursor.execute(
                """
                INSERT INTO authority_workspace(
                    workspace_id,project_id,book_id,status,
                    current_asset_version_id,created_by_operation_id,
                    last_operation_id
                ) VALUES (
                    %s,%s,%s,'ACTIVE',
                    'asset:recovery-migration-workspace:v1',%s,%s
                )
                """,
                [
                    workspace_id,
                    project_id,
                    book_id,
                    seed_operation_id,
                    seed_operation_id,
                ],
            )
            cursor.execute(
                """
                INSERT INTO authority_book(
                    book_id,project_id,workspace_id,principal_id,
                    service_identity,book_scope,production_profile,
                    runtime_policy,release_identity,status,
                    current_book_asset_version_id,created_by_operation_id,
                    last_operation_id
                ) VALUES (
                    %s,%s,%s,'migration-fixture','migration-fixture',
                    '{}'::jsonb,'{}'::jsonb,'{}'::jsonb,'migration@0101',
                    'DESIGN_PENDING','asset:recovery-migration-book:v1',%s,%s
                )
                """,
                [
                    book_id,
                    project_id,
                    workspace_id,
                    seed_operation_id,
                    seed_operation_id,
                ],
            )
            cursor.execute(
                "INSERT INTO authority_asset(asset_id,project_id,asset_type) "
                "VALUES (%s,%s,'book_design')",
                [candidate_asset_id, project_id],
            )
            cursor.execute(
                """
                INSERT INTO authority_asset_version(
                    asset_version_id,asset_id,version_number,lifecycle,
                    eligibility,governance,content,content_hash,schema_version
                ) VALUES (
                    %s,%s,1,'CANDIDATE','ELIGIBLE','CLEAR','{}'::jsonb,%s,
                    'story-design-authority.v1'
                )
                """,
                [candidate_version_id, candidate_asset_id, candidate_hash],
            )
            evaluation_command_payload = {
                "project_id": project_id,
                "input_asset_version_ids": [candidate_version_id],
                "payload": {
                    "book_id": book_id,
                    "candidate_asset_version_id": candidate_version_id,
                    "candidate_content_hash": candidate_hash,
                },
            }
            evaluation_concurrency_key = (
                f"book:{book_id}:evaluation:{candidate_version_id}"
            )
            cursor.execute(
                """
                INSERT INTO authority_operation(
                    operation_id,definition_name,definition_version,project_id,
                    workspace_id,actor_id,status,root_operation_id,
                    idempotency_scope,idempotency_key,request_digest,
                    definition_snapshot,completion_contract_snapshot,
                    policy_snapshot,concurrency_key,command_payload
                ) VALUES (
                    %s,'story_design.semantic_evaluate','1.0.0',%s,%s,
                    'migration-evaluator','CANCELLED',%s,
                    'book:narrative-semantic-evaluation',%s,%s,
                    '{}'::jsonb,'{}'::jsonb,'{}'::jsonb,%s,%s
                )
                """,
                [
                    evaluation_operation_id,
                    project_id,
                    workspace_id,
                    evaluation_operation_id,
                    f"{candidate_version_id}:semantic-evaluation",
                    "sha256:" + "e" * 64,
                    evaluation_concurrency_key,
                    psycopg.types.json.Jsonb(evaluation_command_payload),
                ],
            )
            cursor.execute(
                """
                INSERT INTO authority_book_opening_run(
                    opening_run_id,project_id,workspace_id,book_id,
                    root_operation_id,stable_idempotency_key,lifecycle,
                    frozen_request,frozen_request_digest
                ) VALUES (%s,%s,%s,%s,%s,%s,'RUNNING','{}'::jsonb,%s)
                """,
                [
                    opening_run_id,
                    project_id,
                    workspace_id,
                    book_id,
                    opening_operation_id,
                    "recovery-migration-opening",
                    frozen_request_digest,
                ],
            )
            cursor.execute(
                """
                INSERT INTO authority_runtime_job(
                    runtime_job_id,job_kind,runtime_group,subject_kind,
                    subject_id,project_id,dedupe_key,input_snapshot,input_hash
                ) VALUES (
                    %s,'BOOK_OPENING_EXECUTE','book_opening',
                    'BOOK_OPENING_RUN',%s,%s,'legacy-opening-generation',
                    '{}'::jsonb,%s
                )
                """,
                [runtime_job_id, opening_run_id, project_id, "sha256:" + "9" * 64],
            )
        status = run_migrations(self.test_url)

        self.assertTrue(status["ok"])
        with psycopg.connect(self.test_url) as connection:
            opening = connection.execute(
                """
                SELECT execution_contract_version,current_execution_id,
                       current_execution_generation,current_checkpoint_id,
                       current_checkpoint_sequence,current_checkpoint_hash,
                       recovery_state,lifecycle
                FROM authority_book_opening_run WHERE opening_run_id=%s
                """,
                [opening_run_id],
            ).fetchone()
            runtime_policy = connection.execute(
                "SELECT lease_loss_policy,status FROM authority_runtime_job "
                "WHERE runtime_job_id=%s",
                [runtime_job_id],
            ).fetchone()
            evaluation = connection.execute(
                """
                SELECT evaluation_execution_id,generation,operation_id,
                       lifecycle,predecessor_execution_id,recovery_intent_id,
                       idempotency_key,concurrency_key
                FROM authority_narrative_evaluation_execution
                WHERE operation_id=%s
                """,
                [evaluation_operation_id],
            ).fetchone()
            head = connection.execute(
                """
                SELECT current_execution_id,current_generation,version
                FROM authority_narrative_evaluation_execution_head
                WHERE project_id=%s AND candidate_asset_version_id=%s
                """,
                [project_id, candidate_version_id],
            ).fetchone()
            operation = connection.execute(
                "SELECT status,version FROM authority_operation WHERE operation_id=%s",
                [evaluation_operation_id],
            ).fetchone()
            candidate_once_index = connection.execute(
                "SELECT to_regclass('authority_narrative_evaluation_candidate_once_idx')"
            ).fetchone()[0]
        self.assertEqual(
            opening,
            (
                "legacy-unbound",
                None,
                None,
                None,
                0,
                "",
                "LEGACY_RECONCILIATION_REQUIRED",
                "RUNNING",
            ),
        )
        self.assertEqual(
            runtime_policy,
            ("AUTHORITY_CONVERGENCE_REQUIRED", "READY"),
        )
        expected_execution_id = (
            "narrative-evaluation-execution:legacy:" + evaluation_operation_id
        )
        self.assertEqual(
            evaluation,
            (
                expected_execution_id,
                1,
                evaluation_operation_id,
                "CANCELLED",
                None,
                None,
                f"{candidate_version_id}:semantic-evaluation",
                evaluation_concurrency_key,
            ),
        )
        self.assertEqual(head, (expected_execution_id, 1, 0))
        self.assertEqual(operation, ("CANCELLED", 0))
        self.assertEqual(
            candidate_once_index,
            "authority_narrative_evaluation_candidate_once_idx",
        )

        with self.assertRaises(psycopg.errors.CheckViolation):
            with psycopg.connect(self.test_url) as connection:
                connection.execute(
                    "UPDATE authority_operation SET status='READY' "
                    "WHERE operation_id=%s",
                    [evaluation_operation_id],
                )

    def test_existing_previous_head_upgrades_with_runtime_identity_and_0092_schema(
        self,
    ) -> None:
        dedupe_key = "book:shared:version:3"
        input_snapshot = {"observed_version": 3, "state": "CHAPTER_COMPLETED"}
        old_identity = "\x1f".join(("book", "BOOK_COORDINATION_TICK", dedupe_key))
        old_runtime_job_id = (
            "runtime-job:" + hashlib.sha256(old_identity.encode("utf-8")).hexdigest()
        )
        legacy_project_id = "project:legacy-provider"
        legacy_workspace_id = "workspace:legacy-provider"
        legacy_book_id = "book:legacy-provider"
        legacy_candidate_id = "asset-version:legacy-provider-candidate"
        legacy_evaluation_id = "asset-version:legacy-provider-evaluation"
        legacy_book_plan_id = "asset-version:legacy-book-plan"
        legacy_volume_plan_id = "asset-version:legacy-volume-plan"
        replacement_volume_plan_id = "asset-version:replacement-volume-plan"
        legacy_arc_plan_id = "asset-version:legacy-arc-plan"
        legacy_generation_operation_id = "operation:legacy-provider-generation"
        legacy_evaluation_operation_id = "operation:legacy-provider-evaluation"
        legacy_attempt_id = "attempt:legacy-provider-evaluation"
        with (
            psycopg.connect(self.test_url) as connection,
            connection.cursor() as cursor,
        ):
            migrations_before_correctness = tuple(
                migration
                for migration in MIGRATIONS
                if migration.migration_id
                <= "20260814_0091_canonical_longform_runtime_completion"
            )
            for migration in migrations_before_correctness:
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
            cursor.execute(
                """
                INSERT INTO authority_operation_definition(
                    name, definition_version, family, enabled,
                    command_schema, result_schema, policy, completion_contract
                ) VALUES (
                    'legacy.provider.proof', '1.0.0', 'migration-test', TRUE,
                    '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb
                )
                """
            )
            for operation_id, actor_id in (
                (legacy_generation_operation_id, "legacy-generator"),
                (legacy_evaluation_operation_id, "legacy-evaluator"),
            ):
                cursor.execute(
                    """
                    INSERT INTO authority_operation(
                        operation_id, definition_name, definition_version,
                        project_id, workspace_id, actor_id, status,
                        root_operation_id, idempotency_scope, idempotency_key,
                        request_digest, definition_snapshot,
                        completion_contract_snapshot, policy_snapshot
                    ) VALUES (
                        %s, 'legacy.provider.proof', '1.0.0', %s, %s, %s,
                        'SUCCEEDED', %s, %s, %s, %s,
                        '{}'::jsonb, '{}'::jsonb, '{}'::jsonb
                    )
                    """,
                    [
                        operation_id,
                        legacy_project_id,
                        legacy_workspace_id,
                        actor_id,
                        operation_id,
                        f"project:{legacy_project_id}",
                        operation_id,
                        f"digest:{operation_id}",
                    ],
                )
            for authority_asset_id, authority_asset_type in (
                ("asset:legacy-project", "project_record"),
                ("asset:legacy-workspace", "workspace_record"),
                ("asset:legacy-book", "book_record"),
            ):
                cursor.execute(
                    """
                    INSERT INTO authority_asset(asset_id, project_id, asset_type)
                    VALUES (%s,%s,%s)
                    """,
                    [authority_asset_id, legacy_project_id, authority_asset_type],
                )
                cursor.execute(
                    """
                    INSERT INTO authority_asset_version(
                        asset_version_id, asset_id, version_number,
                        lifecycle, eligibility, governance,
                        content, content_hash, schema_version
                    ) VALUES (
                        %s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',
                        '{}'::jsonb,%s,'migration-test.v1'
                    )
                    """,
                    [
                        f"{authority_asset_id}:v1",
                        authority_asset_id,
                        "sha256:" + "f" * 64,
                    ],
                )
            cursor.execute(
                """
                INSERT INTO authority_project(
                    project_id, primary_workspace_id, title, status, stage, health,
                    current_asset_version_id,
                    created_by_operation_id, last_operation_id
                ) VALUES (
                    %s,%s,'Legacy Provider Qualification',
                    'ACTIVE','PLANNING','HEALTHY','asset:legacy-project:v1',%s,%s
                )
                """,
                [
                    legacy_project_id,
                    legacy_workspace_id,
                    legacy_generation_operation_id,
                    legacy_generation_operation_id,
                ],
            )
            cursor.execute(
                """
                INSERT INTO authority_workspace(
                    workspace_id, project_id, book_id, status,
                    current_asset_version_id,
                    created_by_operation_id, last_operation_id
                ) VALUES (
                    %s,%s,%s,'ACTIVE','asset:legacy-workspace:v1',%s,%s
                )
                """,
                [
                    legacy_workspace_id,
                    legacy_project_id,
                    legacy_book_id,
                    legacy_generation_operation_id,
                    legacy_generation_operation_id,
                ],
            )
            cursor.execute(
                """
                INSERT INTO authority_book(
                    book_id, project_id, workspace_id, principal_id,
                    service_identity, book_scope, production_profile,
                    runtime_policy, release_identity, status,
                    current_book_asset_version_id,
                    created_by_operation_id, last_operation_id
                ) VALUES (
                    %s,%s,%s,'legacy-operator','migration-test',
                    '{}'::jsonb,'{}'::jsonb,'{}'::jsonb,'legacy@0091',
                    'DESIGN_PENDING','asset:legacy-book:v1',%s,%s
                )
                """,
                [
                    legacy_book_id,
                    legacy_project_id,
                    legacy_workspace_id,
                    legacy_generation_operation_id,
                    legacy_generation_operation_id,
                ],
            )
            cursor.execute(
                """
                INSERT INTO authority_attempt(
                    attempt_id, operation_id, attempt_number, status,
                    worker_id, max_attempts
                ) VALUES (%s,%s,1,'SUCCEEDED','legacy-worker',1)
                """,
                [legacy_attempt_id, legacy_evaluation_operation_id],
            )
            for asset_id, asset_version_id, asset_type in (
                (
                    "asset:legacy-provider-candidate",
                    legacy_candidate_id,
                    "book_design",
                ),
                (
                    "asset:legacy-provider-evaluation",
                    legacy_evaluation_id,
                    "narrative_design_evaluation",
                ),
            ):
                cursor.execute(
                    """
                    INSERT INTO authority_asset(asset_id, project_id, asset_type)
                    VALUES (%s,%s,%s)
                    """,
                    [asset_id, legacy_project_id, asset_type],
                )
                cursor.execute(
                    """
                    INSERT INTO authority_asset_version(
                        asset_version_id, asset_id, version_number,
                        lifecycle, eligibility, governance,
                        content, content_hash, schema_version
                    ) VALUES (
                        %s,%s,1,'CANDIDATE','INELIGIBLE','CLEAR',
                        '{}'::jsonb,%s,'migration-test.v1'
                    )
                    """,
                    [asset_version_id, asset_id, "sha256:" + "a" * 64],
                )
            for asset_id, asset_version_id, asset_type, content in (
                ("asset:legacy-book-plan", legacy_book_plan_id, "book_plan", {}),
                (
                    "asset:legacy-volume-plan",
                    legacy_volume_plan_id,
                    "volume_plan",
                    {"chapter_range": [1, 3]},
                ),
                (
                    "asset:replacement-volume-plan",
                    replacement_volume_plan_id,
                    "volume_plan",
                    {"chapter_range": [1, 3]},
                ),
                (
                    "asset:legacy-arc-plan",
                    legacy_arc_plan_id,
                    "arc_plan",
                    {"cross_volume_scope": [legacy_volume_plan_id]},
                ),
            ):
                cursor.execute(
                    "INSERT INTO authority_asset(asset_id, project_id, asset_type) VALUES (%s,%s,%s)",
                    [asset_id, legacy_project_id, asset_type],
                )
                cursor.execute(
                    """
                    INSERT INTO authority_asset_version(
                        asset_version_id, asset_id, version_number,
                        lifecycle, eligibility, governance,
                        content, content_hash, schema_version
                    ) VALUES (
                        %s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',
                        %s,%s,'migration-test.v1'
                    )
                    """,
                    [
                        asset_version_id,
                        asset_id,
                        psycopg.types.json.Jsonb(content),
                        "sha256:" + "8" * 64,
                    ],
                )
            for (
                binding_id,
                contract_type,
                logical_key,
                version_id,
                parent_id,
                freshness,
            ) in (
                (
                    "binding:legacy-book-plan",
                    "BOOK",
                    "book:main",
                    legacy_book_plan_id,
                    None,
                    "CURRENT",
                ),
                (
                    "binding:legacy-volume-plan",
                    "VOLUME",
                    "volume:1",
                    legacy_volume_plan_id,
                    legacy_book_plan_id,
                    "CURRENT",
                ),
                (
                    "binding:legacy-arc-plan",
                    "ARC",
                    "arc:main",
                    legacy_arc_plan_id,
                    None,
                    "CURRENT",
                ),
            ):
                cursor.execute(
                    """
                    INSERT INTO story_plan_binding(
                        binding_id, project_id, book_id, contract_type,
                        logical_key, asset_version_id, parent_version_id,
                        execution_scope, freshness, created_by_operation_id
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,'PLANNED',%s,%s)
                    """,
                    [
                        binding_id,
                        legacy_project_id,
                        legacy_book_id,
                        contract_type,
                        logical_key,
                        version_id,
                        parent_id,
                        freshness,
                        legacy_generation_operation_id,
                    ],
                )
            cursor.execute(
                """
                INSERT INTO active_story_plan_version(
                    project_id, book_id, logical_key, binding_id,
                    asset_version_id, activated_by_operation_id
                ) VALUES (%s,%s,'volume:1',
                          'binding:legacy-volume-plan',%s,%s)
                """,
                [
                    legacy_project_id,
                    legacy_book_id,
                    legacy_volume_plan_id,
                    legacy_generation_operation_id,
                ],
            )
            cursor.execute(
                """
                INSERT INTO authority_narrative_design_qualification(
                    qualification_id, project_id, book_id, asset_version_id,
                    source_operation_id, candidate_content_hash, design_layer,
                    profile_id, profile_version, profile_hash, capability_id,
                    skill_ref, evaluator_execution_class,
                    qualification_status, evaluation, evaluation_hash,
                    qualification_hash, generation_operation_id,
                    evaluation_operation_id, evaluation_attempt_id,
                    evaluation_asset_version_id, evaluation_evidence_hash,
                    trust_boundary
                ) VALUES (
                    'qualification:legacy-provider',%s,%s,%s,%s,%s,
                    'STORY_INTENT','legacy-profile','1.0.0',%s,
                    'legacy-capability','legacy-skill','MODEL_PROVIDER','PASS',
                    '{}'::jsonb,%s,%s,%s,%s,%s,%s,%s,'INDEPENDENT'
                )
                """,
                [
                    legacy_project_id,
                    legacy_book_id,
                    legacy_candidate_id,
                    legacy_evaluation_operation_id,
                    "sha256:" + "a" * 64,
                    "sha256:" + "b" * 64,
                    "sha256:" + "c" * 64,
                    "sha256:" + "d" * 64,
                    legacy_generation_operation_id,
                    legacy_evaluation_operation_id,
                    legacy_attempt_id,
                    legacy_evaluation_id,
                    "sha256:" + "e" * 64,
                ],
            )
            cursor.execute(
                """
                INSERT INTO authority_book_production_input_snapshot(
                    snapshot_id,project_id,workspace_id,book_id,
                    expected_book_version,narrative_chapter_cursor,
                    book_record_version,book_design_version,book_plan_version,
                    current_volume_plan_version,volume_portfolio_plan_versions,
                    active_arc_plan_versions,current_chapter_group_plan_version,
                    production_profile_version,reader_segment_version,
                    reader_contract_version,platform_profile_version,
                    character_state_version,foreshadowing_state_version,
                    quality_trend_version,reward_ledger_version,
                    promise_ledger_version,capability_pack_deployment_refs,
                    release_sha,snapshot_hash,resolved_by_operation_id
                ) VALUES (
                    'snapshot:legacy-0091',%s,%s,%s,1,1,
                    'asset:legacy-book:v1',%s,%s,%s,'[]'::jsonb,
                    %s::jsonb,NULL,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    '[]'::jsonb,%s,%s,%s
                )
                """,
                [
                    legacy_project_id,
                    legacy_workspace_id,
                    legacy_book_id,
                    legacy_candidate_id,
                    legacy_book_plan_id,
                    legacy_volume_plan_id,
                    psycopg.types.json.Jsonb([legacy_arc_plan_id]),
                    *([legacy_candidate_id] * 9),
                    "f" * 40,
                    "sha256:" + "9" * 64,
                    legacy_generation_operation_id,
                ],
            )
            cursor.execute(
                """
                INSERT INTO story_plan_binding(
                    binding_id, project_id, book_id, contract_type,
                    logical_key, asset_version_id, parent_version_id,
                    execution_scope, freshness, created_by_operation_id
                ) VALUES (
                    'binding:replacement-volume-plan',%s,%s,'VOLUME',
                    'volume:1:replacement',%s,%s,'PLANNED','CURRENT',%s
                )
                """,
                [
                    legacy_project_id,
                    legacy_book_id,
                    replacement_volume_plan_id,
                    legacy_book_plan_id,
                    legacy_generation_operation_id,
                ],
            )
            cursor.execute(
                """
                UPDATE story_plan_binding
                SET freshness='STALE'
                WHERE binding_id='binding:legacy-volume-plan'
                """
            )
            cursor.execute(
                """
                DELETE FROM active_story_plan_version
                WHERE binding_id='binding:legacy-volume-plan'
                """
            )
            cursor.execute(
                """
                INSERT INTO active_story_plan_version(
                    project_id,book_id,logical_key,binding_id,
                    asset_version_id,activated_by_operation_id
                ) VALUES (%s,%s,'volume:1:replacement',
                          'binding:replacement-volume-plan',%s,%s)
                """,
                [
                    legacy_project_id,
                    legacy_book_id,
                    replacement_volume_plan_id,
                    legacy_generation_operation_id,
                ],
            )
            applied_before = {
                row[0]
                for row in cursor.execute(
                    "SELECT migration_id FROM nf_schema_migrations"
                ).fetchall()
            }

        self.assertEqual(
            applied_before,
            {migration.migration_id for migration in migrations_before_correctness},
        )
        self.assertEqual(
            migrations_before_correctness[-1].migration_id,
            "20260814_0091_canonical_longform_runtime_completion",
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
            correctness_columns = {
                row[0]
                for row in connection.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema='public'
                      AND table_name='authority_narrative_design_qualification'
                      AND column_name LIKE 'provider_%'
                    """
                ).fetchall()
            }
            correctness_objects = connection.execute(
                """
                SELECT
                  to_regclass('authority_book_production_arc_portfolio_gin_idx'),
                  to_regclass('authority_book_production_current_relevant_arc_gin_idx'),
                  to_regclass('authority_narrative_design_provider_receipt_idx'),
                  to_regclass('authority_current_narrative_design_qualification'),
                  to_regclass('authority_canonical_planning_projection'),
                  to_regprocedure('authority_validate_narrative_provider_lineage()')
                """
            ).fetchone()
            provider_guard = connection.execute(
                """
                SELECT COUNT(*)
                FROM pg_trigger
                WHERE tgname='authority_narrative_design_provider_lineage_guard'
                  AND NOT tgisinternal
                """
            ).fetchone()[0]
            legacy_qualification = connection.execute(
                """
                SELECT trust_boundary,
                       provider_model_call_asset_version_id,
                       EXISTS (
                           SELECT 1
                           FROM authority_current_narrative_design_qualification
                           WHERE qualification_id='qualification:legacy-provider'
                       )
                FROM authority_narrative_design_qualification
                WHERE qualification_id='qualification:legacy-provider'
                """
            ).fetchone()
            legacy_snapshot = connection.execute(
                """
                SELECT volume_portfolio_plan_versions,
                       arc_portfolio_plan_versions,
                       current_relevant_arc_plan_versions
                FROM authority_book_production_input_snapshot
                WHERE snapshot_id='snapshot:legacy-0091'
                """
            ).fetchone()
        self.assertIn("project_id", definitions["authority_runtime_job_dedupe_idx"])
        self.assertEqual(
            correctness_columns,
            {
                "provider_model_call_asset_version_id",
                "provider_model_call_content_hash",
                "provider_evidence_hash",
                "provider_result_hash",
                "provider_route_snapshot_id",
            },
        )
        self.assertTrue(all(correctness_objects))
        self.assertEqual(provider_guard, 1)
        self.assertEqual(legacy_qualification, ("LEGACY_COUPLED", None, False))
        self.assertEqual(
            legacy_snapshot,
            (
                [legacy_volume_plan_id],
                [legacy_arc_plan_id],
                [legacy_arc_plan_id],
            ),
        )
        restarted_status = get_migration_status(self.test_url)
        self.assertTrue(restarted_status["ok"])
        self.assertEqual(restarted_status["current"], LATEST_MIGRATION_ID)
        self.assertIn(
            "project_id", definitions["authority_runtime_job_active_subject_idx"]
        )


if __name__ == "__main__":
    unittest.main()
