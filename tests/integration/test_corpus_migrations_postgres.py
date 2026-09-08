import json
import os
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest
from unittest.mock import patch

from novel_forge.modules.project_authority import (
    ProjectAuthorityApplication,
    ProjectAuthorityCommand,
)
from novel_forge.modules.source_authority import (
    SourceAuthorityApplication,
    SourceAuthorityScheduler,
)
from novel_forge.modules.source_authority.corpus import validate_corpus_action
from novel_forge.modules.source_authority.corpus_application import CorpusCommand
from novel_forge.storage.migrations import LATEST_MIGRATION_ID, MIGRATIONS, run_migrations
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    insert_definition,
    insert_operation,
)
from tests.integration.migration_window_postgres_support import (
    disposable_database_at_migration,
)


CORPUS_TABLES = (
    "authority_corpus_source",
    "authority_corpus_rights",
    "authority_corpus_snapshot",
    "authority_corpus_book_identity",
    "authority_corpus_edition",
    "authority_corpus_admission",
    "authority_corpus_membership",
    "authority_corpus_retirement",
)
CORPUS_INDEX_REPAIR = {
    "authority_corpus_source_workspace_idx",
    "authority_corpus_rights_previous_scope_idx",
    "authority_corpus_snapshot_rights_scope_idx",
    "authority_corpus_snapshot_previous_scope_idx",
    "authority_corpus_edition_snapshot_scope_idx",
    "authority_corpus_edition_book_scope_idx",
    "authority_corpus_membership_admission_idx",
    "authority_corpus_retirement_source_scope_idx",
}


@pytest.mark.parametrize(
    "baseline",
    ["20260625_0001_initial_industrial_schema", "20260907_0120_foundation_generation"],
)
def test_corpus_fresh_and_latest_main_upgrade_preserve_existing_data(baseline):
    with disposable_database_at_migration(
        DATABASE_URL, prefix="corpus_upgrade", target_migration_id=baseline
    ) as url:
        project, workspace = f"old-project-{uuid4()}", f"old-workspace-{uuid4()}"
        if baseline == "20260907_0120_foundation_generation":
            created = ProjectAuthorityApplication(
                url, application_build_id="upgrade-test", commit_sha="e" * 40
            ).execute(
                ProjectAuthorityCommand(
                    definition_name="project_lifecycle.create",
                    project_id=project,
                    workspace_id=workspace,
                    actor_id="upgrade-operator",
                    idempotency_key=project,
                    trace_id=project,
                    correlation_id=project,
                    payload={"title": "Existing project: 不可改写"},
                )
            )
            historical_facts = _seed_premerge_authority_facts(url, project, workspace)
            with psycopg.connect(url) as connection:
                history_before = connection.execute(
                    "SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s",
                    [created["operation_id"]],
                ).fetchone()[0]
                definition, operation = f"frozen-source-import-{uuid4()}", str(uuid4())
                with connection.cursor() as cursor:
                    insert_definition(cursor, definition)
                    insert_operation(
                        cursor,
                        operation_id=operation,
                        definition_name=definition,
                        project_id=project,
                        workspace_id=workspace,
                    )
                    cursor.execute(
                        """
                        INSERT INTO authority_source_import_job (
                            import_job_id,project_id,workspace_id,source_type,source_locator,requested_ref,
                            import_policy,import_policy_hash,intelligence_policy,intelligence_policy_hash,
                            mode,status,discovery_operation_id
                        ) VALUES (%s,%s,%s,'github_repository','{"repository_url":"https://example.invalid/historical"}',
                            'frozen-commit','{}',%s,'{}',%s,'PREVIEW','ADMITTED',%s)
                    """,
                        [
                            operation,
                            project,
                            workspace,
                            "sha256:" + "a" * 64,
                            "sha256:" + "b" * 64,
                            operation,
                        ],
                    )
                job_before = connection.execute(
                    "SELECT to_jsonb(j) FROM authority_source_import_job j WHERE import_job_id=%s",
                    [operation],
                ).fetchone()[0]
        result = run_migrations(url)
        assert result["ok"] and result["current"] == LATEST_MIGRATION_ID
        with psycopg.connect(url) as connection:
            assert (
                connection.execute(
                    "SELECT count(*) FROM nf_schema_migrations"
                ).fetchone()[0]
                == len(MIGRATIONS)
            )
            tables = connection.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename LIKE 'authority_corpus_%'"
            ).fetchall()
            assert len(tables) == 8
            if baseline == "20260907_0120_foundation_generation":
                assert _authority_facts(connection, project) == historical_facts
                assert (
                    history_before
                    == connection.execute(
                        "SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s",
                        [created["operation_id"]],
                    ).fetchone()[0]
                )
                assert (
                    connection.execute(
                        "SELECT workspace_id FROM authority_workspace WHERE project_id=%s",
                        [project],
                    ).fetchone()[0]
                    == workspace
                )
                job_after = connection.execute(
                    "SELECT to_jsonb(j) FROM authority_source_import_job j WHERE import_job_id=%s",
                    [operation],
                ).fetchone()[0]
                assert job_after.pop("corpus_snapshot_id") is None
                assert job_after == job_before
            index_names = {
                row[0]
                for row in connection.execute(
                    "SELECT indexname FROM pg_indexes WHERE indexname LIKE 'authority_corpus_%'"
                )
            }
            assert {
                "authority_corpus_edition_page_idx",
                "authority_corpus_edition_book_idx",
                *CORPUS_INDEX_REPAIR,
            } <= index_names
        assert run_migrations(url) == result
        evidence_dir = os.environ.get("CORPUS_EVIDENCE_DIR")
        if evidence_dir:
            Path(evidence_dir, "migration-" + baseline + ".json").write_text(
                json.dumps(
                    {
                        "baseline": baseline,
                        "result": result,
                        "existing_operation_preserved": baseline.endswith(
                            "0120_foundation_generation"
                        ),
                        "preserved_fact_counts": {key: len(value) for key, value in historical_facts.items()}
                        if baseline.endswith("0120_foundation_generation") else {},
                    },
                    indent=2,
                )
            )


def test_corpus_index_repair_preserves_existing_complete_lineage():
    with disposable_database_at_migration(
        DATABASE_URL,
        prefix="corpus_index_repair",
        target_migration_id="20260908_0123_source_analysis_dimensions",
    ) as url:
        project, workspace = f"index-project-{uuid4()}", f"index-workspace-{uuid4()}"
        ProjectAuthorityApplication(
            url, application_build_id="index-repair", commit_sha="e" * 40
        ).execute(
            ProjectAuthorityCommand(
                definition_name="project_lifecycle.create",
                project_id=project,
                workspace_id=workspace,
                actor_id="index-operator",
                idempotency_key=project,
                trace_id=project,
                correlation_id=project,
                payload={"title": "Existing Corpus lineage"},
            )
        )
        application = SourceAuthorityApplication(
            url, application_build_id="index-repair", commit_sha="e" * 40
        )
        scheduler = SourceAuthorityScheduler(
            application, worker_id=f"index-worker-{uuid4()}"
        )
        source = _execute_corpus_action(
            application,
            scheduler,
            project,
            workspace,
            {
                "action": "register_source",
                "source_kind": "repository_manifest",
                "external_identity": "repository:existing-corpus",
                "purpose": "RESEARCH",
            },
        )["source_id"]
        rights = _execute_corpus_action(
            application,
            scheduler,
            project,
            workspace,
            {
                "action": "declare_rights",
                "source_id": source,
                "dataset_license": "test-fixture-license",
                "underlying_rights": "UNKNOWN",
                "allowed_purposes": ["RESEARCH"],
                "evidence_refs": ["fixture:index-repair"],
                "copyright_boundary": "migration preservation fixture only",
                "scope": "ALL_WORKS_IN_SNAPSHOT",
            },
        )["rights_id"]
        digest = "sha256:" + "a" * 64
        snapshot = _execute_corpus_action(
            application,
            scheduler,
            project,
            workspace,
            {
                "action": "freeze_snapshot",
                "source_id": source,
                "rights_id": rights,
                "manifest": {
                    "origin_uri": "https://example.invalid/existing-corpus",
                    "external_version": "frozen-revision",
                    "format": "json",
                    "checksum": digest,
                    "adapter_profile": "migration-fixture",
                    "adapter_contract_version": "1",
                },
                "acquisition": {
                    "locator": "fixture:manifest.json",
                    "acquired_at": "2026-09-09T00:00:00Z",
                    "receipt_ref": "fixture:index-repair",
                    "checksum": digest,
                },
            },
        )["snapshot_id"]
        _execute_corpus_action(
            application,
            scheduler,
            project,
            workspace,
            {
                "action": "import_batch",
                "snapshot_id": snapshot,
                "batch_key": "existing-page",
                "entries": [
                    {
                        "external_work_id": "existing-work",
                        "external_edition_id": "existing-edition",
                        "title": "既有语料",
                        "checksum": digest,
                        "locator": "fixture:existing-work",
                    }
                ],
            },
        )
        _execute_corpus_action(
            application,
            scheduler,
            project,
            workspace,
            {
                "action": "retire_source",
                "source_id": source,
                "reason": "exercise immutable history during index repair",
            },
        )
        with psycopg.connect(url) as connection:
            before = _project_facts(connection, project, CORPUS_TABLES)
        assert all(len(rows) == 1 for rows in before.values())

        result = run_migrations(url)

        assert result["ok"] and result["current"] == "20260909_0124_corpus_fk_indexes"
        with psycopg.connect(url) as connection:
            assert _project_facts(connection, project, CORPUS_TABLES) == before
            index_names = {
                row[0]
                for row in connection.execute(
                    "SELECT indexname FROM pg_indexes WHERE indexname LIKE 'authority_corpus_%'"
                )
            }
        assert CORPUS_INDEX_REPAIR <= index_names
        assert run_migrations(url) == result


def _authority_facts(connection, project):
    return _project_facts(
        connection,
        project,
        (
            "authority_source_document",
            "authority_source_chunk",
            "authority_mkaos_knowledge_candidate",
            "authority_book",
        ),
    )


def _project_facts(connection, project, tables):
    return {
        table: sorted(
            [row[0] for row in connection.execute(sql.SQL("SELECT to_jsonb(r) FROM {} r WHERE project_id=%s").format(sql.Identifier(table)), [project])],
            key=lambda row: json.dumps(row, sort_keys=True, default=str),
        )
        for table in tables
    }


def _execute_corpus_action(application, scheduler, project, workspace, action):
    operation = application.admit_corpus(
        CorpusCommand(
            project_id=project,
            workspace_id=workspace,
            actor_id="index-operator",
            idempotency_key=str(uuid4()),
            trace_id=str(uuid4()),
            correlation_id=project,
            action=validate_corpus_action(action),
        )
    )
    return scheduler.run_or_recover(
        operation_id=operation["operation_id"], project_id=project
    )


def _seed_premerge_authority_facts(url, project, workspace):
    from novel_forge.modules.book_design_authority import BookDesignAuthorityApplication, BookDesignAuthorityCommand
    from novel_forge.modules.mkaos_authority import MkaosAuthorityApplication
    from tests.integration import authority_postgres_support as support
    from tests.integration import test_mkaos_authority_postgres as fixtures

    BookDesignAuthorityApplication(url, application_build_id="upgrade-facts", commit_sha="e" * 40).execute(
        BookDesignAuthorityCommand(definition_name="book.create", project_id=project,
            workspace_id=workspace, book_id="upgrade-book", actor_id="upgrade-operator",
            service_identity="book-design-authority", idempotency_key="upgrade-book",
            trace_id="upgrade-book", correlation_id=project,
            payload={"schema_version": "book-authority.v1", "title": "升级前作品",
                "production_profile": {"environment": "test"},
                "runtime_policy": {"execution_fallback": "FAIL_CLOSED"}, "release_identity": "upgrade-facts@" + "e" * 40}))
    with patch.object(support, "DATABASE_URL", url), patch.object(fixtures, "DATABASE_URL", url):
        fixture = fixtures.MkaosAuthorityPostgresTests()
        fixture.project_id, fixture.workspace_id = project, workspace
        chunk = fixture._source_chunk_version()
        execution = fixture._insert_asset_version(project, "model_call_log", {
            "gateway": "ProductionExecutionGateway", "fixture_protocol_only": True,
            "real_provider_proven": False, "production_verified": False})
        MkaosAuthorityApplication(url, application_build_id="upgrade-facts", commit_sha="f" * 40).execute_candidate(
            fixture._candidate_command(chunk_version_id=chunk, execution_version_id=execution))
    with psycopg.connect(url) as connection:
        facts = _authority_facts(connection, project)
    assert all(facts.values())
    return facts
