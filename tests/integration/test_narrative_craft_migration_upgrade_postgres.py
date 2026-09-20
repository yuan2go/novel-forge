from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb
import pytest

from novel_forge.modules.mkaos_authority.craft import craft_hash
from novel_forge.modules.project_authority import ProjectAuthorityApplication, ProjectAuthorityCommand
from novel_forge.storage.migrations import LATEST_MIGRATION_ID, run_migrations
from tests.integration.authority_postgres_support import DATABASE_URL, insert_definition, insert_operation
from tests.integration.migration_window_postgres_support import disposable_database_at_migration


BASELINE = "20260920_0137_opening_delete_fence"
MIGRATION = "20260920_0138_narrative_craft_origin"


def _project(url):
    project_id, workspace_id = "craft-upgrade:" + uuid4().hex, "workspace:" + uuid4().hex
    ProjectAuthorityApplication(url, application_build_id="craft-upgrade-test", commit_sha="c" * 40).execute(ProjectAuthorityCommand(definition_name="project_lifecycle.create", project_id=project_id, workspace_id=workspace_id, actor_id="migration-fixture", idempotency_key="project:create", trace_id="trace:upgrade", correlation_id="correlation:upgrade", payload={"title": "Craft migration compatibility fixture"}))
    return project_id, workspace_id


def _asset(cursor, project_id, identity, asset_type, content):
    version_id = identity + ":v1"
    cursor.execute("INSERT INTO authority_asset(asset_id,project_id,asset_type) VALUES (%s,%s,%s)", [identity, project_id, asset_type])
    cursor.execute("INSERT INTO authority_asset_version(asset_version_id,asset_id,version_number,lifecycle,eligibility,governance,content,content_hash,schema_version) VALUES (%s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',%s,%s,'migration-fixture.v1')", [version_id, identity, Jsonb(content), craft_hash(content)])
    return version_id


def _candidate_identity(cursor, project_id, workspace_id, definition, name):
    identity = "candidate:" + name + ":" + uuid4().hex
    content = {"candidate": {"abstract_principle": "A deliberately original migration fixture mechanism."}, "lineage": {"preserve": "legacy-evidence-identity"}}
    asset_version = _asset(cursor, project_id, identity, "knowledge_card_candidate", content)
    operation = "operation:" + identity
    insert_operation(cursor, operation_id=operation, definition_name=definition, project_id=project_id, workspace_id=workspace_id, status="SUCCEEDED")
    return [identity, project_id, workspace_id, asset_version, operation, craft_hash({"candidate": identity}), "legacy-abstraction:v1", "NEEDS_REVIEW"]


def test_craft_origin_upgrade_preserves_legacy_source_candidates_and_enforces_new_origin():
    with disposable_database_at_migration(DATABASE_URL, prefix="craft_origin_upgrade", target_migration_id=BASELINE) as url:
        project_id, workspace_id = _project(url)
        definition = "fixture.craft-upgrade"
        with psycopg.connect(url) as connection, connection.cursor() as cursor:
            insert_definition(cursor, definition)
            execution = _asset(cursor, project_id, "source-execution:" + uuid4().hex, "model_call_log", {"fixture_protocol_only": True, "real_provider_proven": False, "preserved_source_execution": True})
            legacy = _candidate_identity(cursor, project_id, workspace_id, definition, "legacy")
            cursor.execute("INSERT INTO authority_mkaos_knowledge_candidate(knowledge_candidate_id,project_id,workspace_id,asset_version_id,created_by_operation_id,candidate_hash,abstraction_policy_version,status,execution_asset_version_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", [*legacy, execution])
            cursor.execute("SELECT candidate.asset_version_id,candidate.execution_asset_version_id,candidate.candidate_hash,candidate.abstraction_policy_version,candidate.status,version.content,version.content_hash,candidate.created_at FROM authority_mkaos_knowledge_candidate candidate JOIN authority_asset_version version ON version.asset_version_id=candidate.asset_version_id WHERE candidate.knowledge_candidate_id=%s", [legacy[0]])
            before = cursor.fetchone()
        status = run_migrations(url)
        assert status["ok"] is True and status["current"] == LATEST_MIGRATION_ID
        assert MIGRATION in {item["migration_id"] for item in status["applied"]}
        assert run_migrations(url) == status
        with psycopg.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT candidate.asset_version_id,candidate.execution_asset_version_id,candidate.candidate_hash,candidate.abstraction_policy_version,candidate.status,version.content,version.content_hash,candidate.created_at FROM authority_mkaos_knowledge_candidate candidate JOIN authority_asset_version version ON version.asset_version_id=candidate.asset_version_id WHERE candidate.knowledge_candidate_id=%s", [legacy[0]])
            assert cursor.fetchone() == before
            cursor.execute("SELECT origin_kind,craft_mechanism_id,craft_mechanism_version,craft_mechanism_hash FROM authority_mkaos_knowledge_candidate WHERE knowledge_candidate_id=%s", [legacy[0]])
            assert cursor.fetchone() == ("SOURCE_ABSTRACTION", None, None, None)
            insert = "INSERT INTO authority_mkaos_knowledge_candidate(knowledge_candidate_id,project_id,workspace_id,asset_version_id,created_by_operation_id,candidate_hash,abstraction_policy_version,status,execution_asset_version_id,origin_kind,craft_mechanism_id,craft_mechanism_version,craft_mechanism_hash) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            for label, fields, constraint in (
                ("source-without-execution", [None, "SOURCE_ABSTRACTION", None, None, None], "authority_mkaos_candidate_origin_ck"),
                ("original-with-execution", [execution, "REPOSITORY_ORIGINAL", "spatial-anchor", 1, "sha256:" + "a" * 64], "authority_mkaos_candidate_origin_ck"),
                ("original-without-identity", [None, "REPOSITORY_ORIGINAL", None, None, None], "authority_mkaos_candidate_origin_ck"),
                ("original-empty-identity", [None, "REPOSITORY_ORIGINAL", "", 1, "sha256:" + "a" * 64], "authority_mkaos_candidate_craft_identity_ck"),
                ("original-invalid-identity", [None, "REPOSITORY_ORIGINAL", "Copied Source Text", 1, "sha256:" + "a" * 64], "authority_mkaos_candidate_craft_identity_ck"),
                ("original-without-version", [None, "REPOSITORY_ORIGINAL", "spatial-anchor", None, "sha256:" + "a" * 64], "authority_mkaos_candidate_craft_identity_ck"),
                ("original-without-hash", [None, "REPOSITORY_ORIGINAL", "spatial-anchor", 1, None], "authority_mkaos_candidate_craft_identity_ck"),
                ("original-invalid-version", [None, "REPOSITORY_ORIGINAL", "spatial-anchor", 0, "sha256:" + "a" * 64], "authority_mkaos_candidate_craft_identity_ck"),
                ("original-invalid-hash", [None, "REPOSITORY_ORIGINAL", "spatial-anchor", 1, "unversioned"], "authority_mkaos_candidate_craft_identity_ck"),
            ):
                row = _candidate_identity(cursor, project_id, workspace_id, definition, label)
                with pytest.raises(psycopg.errors.CheckViolation, match=constraint):
                    with connection.transaction():
                        cursor.execute(insert, [*row, *fields])
            original = _candidate_identity(cursor, project_id, workspace_id, definition, "original")
            fields = [None, "REPOSITORY_ORIGINAL", "spatial-anchor", 1, "sha256:" + "a" * 64]
            cursor.execute(insert, [*original, *fields])
            duplicate = _candidate_identity(cursor, project_id, workspace_id, definition, "duplicate")
            with pytest.raises(psycopg.errors.UniqueViolation, match="authority_mkaos_candidate_craft_version_idx"):
                with connection.transaction():
                    cursor.execute(insert, [*duplicate, *fields])
            cursor.execute("SELECT origin_kind,execution_asset_version_id,craft_mechanism_id,craft_mechanism_version,craft_mechanism_hash FROM authority_mkaos_knowledge_candidate WHERE knowledge_candidate_id=%s", [original[0]])
            assert cursor.fetchone() == ("REPOSITORY_ORIGINAL", None, "spatial-anchor", 1, "sha256:" + "a" * 64)


def test_craft_origin_fresh_migration_and_rerun_install_validated_constraints():
    with disposable_database_at_migration(DATABASE_URL, prefix="craft_origin_fresh", target_migration_id="20260625_0001_initial_industrial_schema") as url:
        status = run_migrations(url)
        assert status["ok"] is True and status["current"] == LATEST_MIGRATION_ID
        assert MIGRATION in {item["migration_id"] for item in status["applied"]}
        assert run_migrations(url) == status
        with psycopg.connect(url) as connection:
            rows = connection.execute("SELECT conname,convalidated FROM pg_constraint WHERE conname IN ('authority_mkaos_candidate_origin_ck','authority_mkaos_candidate_craft_identity_ck') ORDER BY conname").fetchall()
        assert rows == [("authority_mkaos_candidate_craft_identity_ck", True), ("authority_mkaos_candidate_origin_ck", True)]
