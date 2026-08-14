from __future__ import annotations

import hashlib
import unittest

import psycopg
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
            {migration.migration_id for migration in MIGRATIONS[:-1]},
        )
        self.assertEqual(
            MIGRATIONS[-2].migration_id,
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
