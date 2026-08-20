from __future__ import annotations

import hashlib
import json
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

    def test_existing_0091_head_upgrades_through_0092_0093_and_0094(
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
            for migration in MIGRATIONS[:-3]:
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
            {migration.migration_id for migration in MIGRATIONS[:-3]},
        )
        self.assertEqual(
            MIGRATIONS[-4].migration_id,
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

    def test_0092_upgrade_repairs_only_proven_liveness_heads_and_adds_indexes(
        self,
    ) -> None:
        project_id = "project:migration-liveness"
        committed_book = "book-run:migration-committed"
        ambiguous_book = "book-run:migration-ambiguous"
        closure_book = "book-run:migration-closure"
        chapter_request_id = "chapter-request:migration-committed"
        delegation_id = "delegation:migration-committed"
        acceptance_operation_id = "operation:migration-acceptance"
        followup_operation_id = "operation:migration-followup"
        chapter_operation_id = "operation:migration-chapter"
        group_operation_id = "operation:migration-group"
        asset_versions = {
            "chapter_plan": "asset-version:migration-chapter-plan",
            "chapter_outcome": "asset-version:migration-outcome",
            "story_state": "asset-version:migration-story-state",
            "canon": "asset-version:migration-canon",
            "group_plan": "asset-version:migration-group-plan",
            "volume_plan": "asset-version:migration-volume-plan",
        }
        book_roots = {
            committed_book: "operation:migration-book-committed",
            ambiguous_book: "operation:migration-book-ambiguous",
            closure_book: "operation:migration-book-closure",
        }

        with psycopg.connect(self.test_url) as connection, connection.cursor() as cursor:
            for migration in MIGRATIONS[:-2]:
                for statement in migration.upgrade_statements:
                    cursor.execute(statement)
                cursor.execute(
                    "INSERT INTO nf_schema_migrations (migration_id) VALUES (%s)",
                    [migration.migration_id],
                )
            self.assertEqual(
                MIGRATIONS[-3].migration_id,
                "20260814_0092_longform_correctness_closure",
            )
            cursor.execute(
                """
                INSERT INTO authority_operation_definition(
                    name, definition_version, family, enabled,
                    command_schema, result_schema, policy, completion_contract
                ) VALUES (
                    'migration.liveness', '1.0.0', 'migration-test', TRUE,
                    '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb
                )
                """
            )
            operation_ids = (
                *book_roots.values(),
                chapter_operation_id,
                acceptance_operation_id,
                followup_operation_id,
                group_operation_id,
            )
            for operation_id in operation_ids:
                cursor.execute(
                    """
                    INSERT INTO authority_operation(
                        operation_id, definition_name, definition_version,
                        project_id, actor_id, status, root_operation_id,
                        idempotency_scope, idempotency_key, request_digest,
                        definition_snapshot, completion_contract_snapshot,
                        policy_snapshot
                    ) VALUES (
                        %s, 'migration.liveness', '1.0.0', %s,
                        'migration-worker', 'SUCCEEDED', %s,
                        %s, %s, %s, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb
                    )
                    """,
                    [
                        operation_id,
                        project_id,
                        operation_id,
                        f"project:{project_id}",
                        operation_id,
                        f"digest:{operation_id}",
                    ],
                )
            saga_operations = (*book_roots.values(), chapter_operation_id, group_operation_id)
            for operation_id in saga_operations:
                cursor.execute(
                    """
                    INSERT INTO authority_saga(
                        saga_id, root_operation_id, project_id, status,
                        trace_id, correlation_id
                    ) VALUES (%s,%s,%s,'SUCCEEDED',%s,%s)
                    """,
                    [
                        f"saga:{operation_id}",
                        operation_id,
                        project_id,
                        f"trace:{operation_id}",
                        f"correlation:{operation_id}",
                    ],
                )
            for asset_type, asset_version_id in asset_versions.items():
                asset_id = asset_version_id.replace("asset-version:", "asset:")
                cursor.execute(
                    "INSERT INTO authority_asset(asset_id, project_id, asset_type) VALUES (%s,%s,%s)",
                    [asset_id, project_id, asset_type],
                )
                cursor.execute(
                    """
                    INSERT INTO authority_asset_version(
                        asset_version_id, asset_id, version_number, lifecycle,
                        eligibility, governance, content, content_hash,
                        schema_version
                    ) VALUES (
                        %s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',
                        '{}'::jsonb,%s,'migration-liveness.v1'
                    )
                    """,
                    [asset_version_id, asset_id, "sha256:" + "a" * 64],
                )
            longform_context = psycopg.types.json.Jsonb(
                {
                    "volume_plan_version": asset_versions["volume_plan"],
                    "arc_plan_versions": ["asset-version:migration-arc"],
                    "character_state_version": "asset-version:migration-character",
                    "foreshadowing_state_version": "asset-version:migration-foreshadowing",
                    "quality_trend_version": "asset-version:migration-quality",
                    "reward_ledger_version": "asset-version:migration-reward",
                    "promise_ledger_version": "asset-version:migration-promise",
                }
            )
            book_rows = (
                (committed_book, "READER_OUTCOME_PENDING", 1, 1, 10),
                (ambiguous_book, "FOLLOWUP_PENDING", 0, 0, 10),
                (closure_book, "COMPLETED", 3, 3, 10),
            )
            for book_run_id, state, current, accepted, target in book_rows:
                root_operation_id = book_roots[book_run_id]
                cursor.execute(
                    """
                    INSERT INTO authority_book_production(
                        book_run_id, project_id, workspace_id, book_id,
                        book_design_version, book_plan_version,
                        production_profile_version, longform_context_versions,
                        root_operation_id, saga_id, stable_idempotency_key,
                        state, current_chapter, target_chapter_count,
                        light_recap_cadence, formal_recap_cadence,
                        last_reader_outcome_operation_id,
                        last_recap_operation_id, accepted_through_chapter,
                        active_story_state_version_id,
                        last_chapter_outcome_version_id,
                        active_canon_snapshot_version_id
                    ) VALUES (
                        %s,%s,%s,%s,'book-design:v1','book-plan:v1',
                        'production-profile:v1',%s,%s,%s,%s,%s,%s,%s,5,10,
                        %s,%s,%s,%s,%s,%s
                    )
                    """,
                    [
                        book_run_id,
                        project_id,
                        f"workspace:{book_run_id}",
                        f"book:{book_run_id}",
                        longform_context,
                        root_operation_id,
                        f"saga:{root_operation_id}",
                        f"stable:{book_run_id}",
                        state,
                        current,
                        target,
                        followup_operation_id if book_run_id == committed_book else None,
                        followup_operation_id if book_run_id == committed_book else None,
                        accepted,
                        asset_versions["story_state"] if accepted else None,
                        asset_versions["chapter_outcome"] if accepted else None,
                        asset_versions["canon"] if accepted else None,
                    ],
                )
            cursor.execute(
                """
                INSERT INTO authority_book_chapter_request(
                    chapter_request_id, book_run_id, project_id, chapter_number,
                    chapter_plan_version, chapter_plan_content_hash,
                    production_profile_version, stable_idempotency_key,
                    command_payload, chapter_root_operation_id, chapter_saga_id,
                    status_reference
                ) VALUES (
                    %s,%s,%s,1,%s,%s,'production-profile:v1',%s,
                    '{}'::jsonb,%s,%s,'SUCCEEDED'
                )
                """,
                [
                    chapter_request_id,
                    committed_book,
                    project_id,
                    asset_versions["chapter_plan"],
                    "sha256:" + "b" * 64,
                    "stable:migration-chapter",
                    chapter_operation_id,
                    f"saga:{chapter_operation_id}",
                ],
            )
            cursor.execute(
                """
                INSERT INTO authority_child_delegation(
                    delegation_id, project_id, owner_authority, owner_id,
                    child_authority, chapter_request_id, chapter_number,
                    plan_version_id, child_root_operation_id, child_saga_id,
                    stable_idempotency_key, status, accepted_at
                ) VALUES (
                    %s,%s,'BOOK',%s,'CHAPTER',%s,1,%s,%s,%s,%s,'ACCEPTED',NOW()
                )
                """,
                [
                    delegation_id,
                    project_id,
                    committed_book,
                    chapter_request_id,
                    asset_versions["chapter_plan"],
                    chapter_operation_id,
                    f"saga:{chapter_operation_id}",
                    "stable:migration-delegation",
                ],
            )
            cursor.execute(
                """
                INSERT INTO authority_book_chapter_acceptance(
                    acceptance_id, project_id, book_run_id, chapter_request_id,
                    delegation_id, acceptance_operation_id, chapter_number,
                    chapter_outcome_asset_version_id,
                    story_state_asset_version_id, evidence, status,
                    canon_snapshot_asset_version_id
                ) VALUES (
                    'acceptance:migration',%s,%s,%s,%s,%s,1,%s,%s,
                    '{}'::jsonb,'COMMITTED',%s
                )
                """,
                [
                    project_id,
                    committed_book,
                    chapter_request_id,
                    delegation_id,
                    acceptance_operation_id,
                    asset_versions["chapter_outcome"],
                    asset_versions["story_state"],
                    asset_versions["canon"],
                ],
            )
            cursor.execute(
                """
                INSERT INTO authority_book_followup_operation(
                    followup_id, book_run_id, chapter_request_id, project_id,
                    followup_type, operation_id, stable_idempotency_key
                ) VALUES (
                    'followup:migration',%s,%s,%s,'READER_OUTCOME',%s,
                    'stable:migration-followup'
                )
                """,
                [
                    committed_book,
                    chapter_request_id,
                    project_id,
                    followup_operation_id,
                ],
            )
            cursor.execute(
                """
                INSERT INTO authority_chapter_group_production(
                    group_run_id, project_id, book_id, book_run_id,
                    group_plan_version_id, volume_plan_version_id,
                    root_operation_id, saga_id, stable_idempotency_key,
                    chapter_start, chapter_end, accepted_through_chapter, state
                ) VALUES (
                    'chapter-group-run:migration',%s,%s,%s,%s,%s,%s,%s,
                    'stable:migration-group',1,3,3,'CLOSURE_PENDING'
                )
                """,
                [
                    project_id,
                    f"book:{closure_book}",
                    closure_book,
                    asset_versions["group_plan"],
                    asset_versions["volume_plan"],
                    group_operation_id,
                    f"saga:{group_operation_id}",
                ],
            )
            runtime_snapshot = {"book_run_id": committed_book}
            cursor.execute(
                """
                INSERT INTO authority_runtime_job(
                    runtime_job_id, job_kind, runtime_group, subject_kind,
                    subject_id, project_id, dedupe_key, input_snapshot,
                    input_hash, status
                ) VALUES (
                    'runtime-job:migration-followup','BOOK_FOLLOWUP_ADMISSION',
                    'book_followup','CHAPTER_ACCEPTANCE',%s,%s,
                    'migration-followup',%s,%s,'READY'
                )
                """,
                [
                    chapter_request_id,
                    project_id,
                    psycopg.types.json.Jsonb(runtime_snapshot),
                    canonical_payload_hash(runtime_snapshot),
                ],
            )

        status = run_migrations(self.test_url)
        self.assertTrue(status["ok"])
        self.assertEqual(status["current"], LATEST_MIGRATION_ID)
        with psycopg.connect(self.test_url) as connection:
            states = dict(
                connection.execute(
                    """
                    SELECT book_run_id, state
                    FROM authority_book_production
                    WHERE book_run_id = ANY(%s)
                    """,
                    [[committed_book, ambiguous_book, closure_book]],
                ).fetchall()
            )
            committed_row = connection.execute(
                """
                SELECT state, accepted_through_chapter,
                       active_chapter_request_id, active_child_delegation_id,
                       active_chapter_number, active_plan_version_id
                FROM authority_book_production WHERE book_run_id=%s
                """,
                [committed_book],
            ).fetchone()
            removed_pointer_columns = connection.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.columns
                WHERE table_schema='public'
                  AND table_name='authority_book_production'
                  AND column_name IN (
                      'last_reader_outcome_operation_id',
                      'last_recap_operation_id'
                  )
                """
            ).fetchone()[0]
            indexes = {
                row[0]
                for row in connection.execute(
                    """
                    SELECT indexname FROM pg_indexes
                    WHERE schemaname='public'
                      AND indexname IN (
                        'authority_book_acceptance_followup_admission_idx',
                        'authority_book_followup_backlog_idx',
                        'authority_book_followup_runtime_job_progress_idx'
                      )
                    """
                ).fetchall()
            }
            connection.execute("SET enable_seqscan=off")
            acceptance_plan = connection.execute(
                """
                EXPLAIN (FORMAT JSON)
                SELECT chapter_number, created_at, book_run_id, chapter_request_id
                FROM authority_book_chapter_acceptance
                WHERE status='COMMITTED'
                ORDER BY chapter_number, created_at, book_run_id, chapter_request_id
                LIMIT 10
                """
            ).fetchone()[0]
            backlog_plan = connection.execute(
                """
                EXPLAIN (FORMAT JSON)
                SELECT operation_id FROM authority_book_followup_operation
                WHERE book_run_id=%s AND chapter_request_id=%s
                  AND followup_type='READER_OUTCOME'
                """,
                [committed_book, chapter_request_id],
            ).fetchone()[0]
            runtime_plan = connection.execute(
                """
                EXPLAIN (FORMAT JSON)
                SELECT runtime_job_id FROM authority_runtime_job
                WHERE runtime_group='book_followup'
                  AND job_kind='BOOK_FOLLOWUP_ADMISSION'
                  AND project_id=%s
                  AND input_snapshot->>'book_run_id'=%s
                  AND status='READY'
                ORDER BY available_at
                LIMIT 10
                """,
                [project_id, committed_book],
            ).fetchone()[0]
        self.assertEqual(states[committed_book], "READY")
        self.assertEqual(states[ambiguous_book], "FOLLOWUP_PENDING")
        self.assertEqual(states[closure_book], "READY")
        self.assertEqual(committed_row, ("READY", 1, None, None, None, None))
        self.assertEqual(removed_pointer_columns, 0)
        self.assertEqual(
            indexes,
            {
                "authority_book_acceptance_followup_admission_idx",
                "authority_book_followup_backlog_idx",
                "authority_book_followup_runtime_job_progress_idx",
            },
        )
        self.assertIn(
            "authority_book_acceptance_followup_admission_idx",
            json.dumps(acceptance_plan),
        )
        self.assertIn("authority_book_followup_backlog_idx", json.dumps(backlog_plan))
        self.assertIn(
            "authority_book_followup_runtime_job_progress_idx",
            json.dumps(runtime_plan),
        )


if __name__ == "__main__":
    unittest.main()
