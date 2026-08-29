from __future__ import annotations

import hashlib

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb

from novel_forge.storage.migrations import MIGRATIONS, run_migrations
from tests.integration.authority_postgres_support import DATABASE_URL, identifier


def _database_url(database_name: str) -> str:
    parameters = conninfo_to_dict(DATABASE_URL)
    parameters["dbname"] = database_name
    return make_conninfo(**parameters)


@pytest.fixture()
def previous_head_database() -> str:
    database_name = identifier("nf_branch_reconciliation_upgrade").replace(
        "-", "_"
    )[:63]
    admin_url = _database_url("postgres")
    with psycopg.connect(admin_url, autocommit=True) as connection:
        connection.execute(
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
        )
    test_url = _database_url(database_name)
    try:
        yield test_url
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


def test_0102_upgrade_preserves_legacy_membership_and_requires_sidecar(
    previous_head_database: str,
) -> None:
    project_id = "project:branch-upgrade"
    workspace_id = "workspace:branch-upgrade"
    book_id = "book:branch-upgrade"
    seed_operation_id = "operation:branch-upgrade-seed"
    generation_operation_id = "operation:branch-upgrade-generation"
    generation_attempt_id = "attempt:branch-upgrade-generation"
    search_id = "narrative-search:branch-upgrade"
    candidate_version_id = "asset-version:branch-upgrade-candidate"
    membership_id = "narrative-search-candidate:branch-upgrade:future-1"
    with psycopg.connect(previous_head_database) as connection:
        cursor = connection.cursor()
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
                == "20260829_0103_book_opening_semantic_runtime_hardening"
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
            INSERT INTO authority_operation_definition(
                name,definition_version,family,enabled,command_schema,
                result_schema,policy,completion_contract
            ) VALUES (
                'fixture.branch_upgrade','1.0.0','migration-fixture',TRUE,
                '{}'::jsonb,'{}'::jsonb,'{}'::jsonb,'{}'::jsonb
            )
            """
        )
        for operation_id, status in (
            (seed_operation_id, "SUCCEEDED"),
            (generation_operation_id, "SUCCEEDED"),
        ):
            cursor.execute(
                """
                INSERT INTO authority_operation(
                    operation_id,definition_name,definition_version,project_id,
                    workspace_id,actor_id,status,root_operation_id,
                    idempotency_scope,idempotency_key,request_digest,
                    definition_snapshot,completion_contract_snapshot,
                    policy_snapshot,concurrency_key,command_payload
                ) VALUES (
                    %s,'fixture.branch_upgrade','1.0.0',%s,%s,
                    'migration-fixture',%s,%s,%s,%s,%s,
                    '{}'::jsonb,'{}'::jsonb,'{}'::jsonb,%s,%s
                )
                """,
                [
                    operation_id,
                    project_id,
                    workspace_id,
                    status,
                    operation_id,
                    f"project:{project_id}",
                    operation_id,
                    "sha256:" + hashlib.sha256(operation_id.encode()).hexdigest(),
                    f"fixture:{operation_id}",
                    Jsonb({"payload": {"book_id": book_id}}),
                ],
            )
        assets = (
            ("asset:branch-upgrade-project", "project_record", "1"),
            ("asset:branch-upgrade-workspace", "workspace_record", "2"),
            ("asset:branch-upgrade-book", "book_record", "3"),
            ("asset:branch-upgrade-candidate", "book_plan", "4"),
        )
        for asset_id, asset_type, digest in assets:
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
                ) VALUES (%s,%s,1,%s,'ELIGIBLE','CLEAR',%s,%s,%s)
                """,
                [
                    (
                        candidate_version_id
                        if asset_type == "book_plan"
                        else f"{asset_id}:v1"
                    ),
                    asset_id,
                    "CANDIDATE" if asset_type == "book_plan" else "ACTIVE",
                    Jsonb({"fixture": asset_type}),
                    "sha256:" + digest * 64,
                    "branch-upgrade.v1",
                ],
            )
        cursor.execute(
            """
            INSERT INTO authority_project(
                project_id,primary_workspace_id,title,status,stage,health,
                current_asset_version_id,created_by_operation_id,last_operation_id
            ) VALUES (
                %s,%s,'Branch Upgrade','ACTIVE','PLANNING','HEALTHY',
                'asset:branch-upgrade-project:v1',%s,%s
            )
            """,
            [project_id, workspace_id, seed_operation_id, seed_operation_id],
        )
        cursor.execute(
            """
            INSERT INTO authority_workspace(
                workspace_id,project_id,book_id,status,current_asset_version_id,
                created_by_operation_id,last_operation_id
            ) VALUES (
                %s,%s,%s,'ACTIVE','asset:branch-upgrade-workspace:v1',%s,%s
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
                book_id,project_id,workspace_id,principal_id,service_identity,
                book_scope,production_profile,runtime_policy,release_identity,
                status,current_book_asset_version_id,created_by_operation_id,
                last_operation_id
            ) VALUES (
                %s,%s,%s,'migration-fixture','migration-fixture','{}'::jsonb,
                '{}'::jsonb,'{}'::jsonb,'migration@0102','DESIGN_PENDING',
                'asset:branch-upgrade-book:v1',%s,%s
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
            """
            INSERT INTO authority_story_narrative_search(
                search_id,project_id,workspace_id,book_id,
                generator_operation_name,planning_scope,logical_key,
                accepted_through_chapter,planning_horizon,
                desired_transformation,hard_constraints,input_snapshot_hash,
                strategy_directives,candidate_target,status,
                stable_idempotency_key
            ) VALUES (
                %s,%s,%s,%s,'book_plan.generate','BOOK','book:main',0,
                '{}'::jsonb,'{}'::jsonb,'[]'::jsonb,%s,
                '["legacy future","future two"]'::jsonb,2,'GENERATING',%s
            )
            """,
            [
                search_id,
                project_id,
                workspace_id,
                book_id,
                "sha256:" + "5" * 64,
                "branch-upgrade-search",
            ],
        )
        cursor.execute(
            """
            INSERT INTO authority_attempt(
                attempt_id,operation_id,attempt_number,status,worker_id,max_attempts
            ) VALUES (%s,%s,1,'SUCCEEDED','branch-upgrade-fixture',1)
            """,
            [generation_attempt_id, generation_operation_id],
        )
        cursor.execute(
            """
            INSERT INTO authority_story_planning_generation(
                generation_id,operation_id,project_id,workspace_id,book_id,
                generator_operation_name,planning_scope,logical_key,
                input_snapshot,input_snapshot_hash,status,narrative_search_id,
                narrative_search_branch_key
            ) VALUES (
                'generation:branch-upgrade',%s,%s,%s,%s,
                'book_plan.generate','BOOK','book:main','[]'::jsonb,%s,
                'ADMITTED',%s,'future-1'
            )
            """,
            [
                generation_operation_id,
                project_id,
                workspace_id,
                book_id,
                "sha256:" + "6" * 64,
                search_id,
            ],
        )
        cursor.execute(
            """
            INSERT INTO authority_story_planning_candidate(
                candidate_id,generation_id,project_id,book_id,
                candidate_asset_version_id,content_hash,attempt_id
            ) VALUES (
                'planning-candidate:branch-upgrade',
                'generation:branch-upgrade',%s,%s,%s,%s,%s
            )
            """,
            [
                project_id,
                book_id,
                candidate_version_id,
                "sha256:" + "4" * 64,
                generation_attempt_id,
            ],
        )
        cursor.execute(
            """
            UPDATE authority_story_planning_generation
            SET candidate_asset_version_id=%s,status='APPROVAL_PENDING',version=version+1
            WHERE generation_id='generation:branch-upgrade'
            """,
            [candidate_version_id],
        )
        cursor.execute(
            """
            INSERT INTO authority_story_narrative_search_candidate(
                membership_id,search_id,branch_key,candidate_asset_version_id,
                generation_operation_id,projection,projection_hash,
                strategy_fingerprint,comparison_score,qualification_hash,status
            ) VALUES (
                %s,%s,'future-1',%s,%s,'{}'::jsonb,%s,'legacy-future',
                0.75,%s,'ELIGIBLE'
            )
            """,
            [
                membership_id,
                search_id,
                candidate_version_id,
                generation_operation_id,
                "sha256:" + "7" * 64,
                "sha256:" + "8" * 64,
            ],
        )
        connection.commit()

    status = run_migrations(previous_head_database)
    assert status["ok"] is True
    with psycopg.connect(previous_head_database) as connection:
        membership = connection.execute(
            """
            SELECT branch_evidence_contract_version,branch_evidence_hash,
                   projection_hash,qualification_hash
            FROM authority_story_narrative_search_candidate
            WHERE membership_id=%s
            """,
            [membership_id],
        ).fetchone()
        sidecar_count = connection.execute(
            "SELECT COUNT(*) FROM "
            "authority_story_narrative_branch_reconciliation_evidence"
        ).fetchone()[0]
        assert membership == (
            "legacy-unbound",
            "",
            "sha256:" + "7" * 64,
            "sha256:" + "8" * 64,
        )
        assert sidecar_count == 0
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                """
                UPDATE authority_story_narrative_search_candidate
                SET branch_evidence_hash=%s WHERE membership_id=%s
                """,
                ["sha256:" + "9" * 64, membership_id],
            )
        connection.rollback()
