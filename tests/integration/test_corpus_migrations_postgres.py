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
from novel_forge.storage.migrations import (
    LATEST_MIGRATION_ID,
    MIGRATIONS,
    run_migrations,
)
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    insert_definition,
    insert_operation,
)
from tests.integration.migration_window_postgres_support import (
    disposable_database_at_migration,
)


@pytest.mark.parametrize(
    "baseline",
    [
        "20260625_0001_initial_industrial_schema",
        "20260907_0120_foundation_generation",
        "20260908_0123_source_analysis_dimensions",
        "20260909_0124_corpus_fk_indexes",
        "20260909_0125_corpus_ingestion_bridge",
        "20260909_0126_corpus_processing",
        "20260909_0127_corpus_curation",
    ],
)
def test_corpus_fresh_and_latest_main_upgrade_preserve_existing_data(baseline):
    with disposable_database_at_migration(
        DATABASE_URL, prefix="corpus_upgrade", target_migration_id=baseline
    ) as url:
        project, workspace = f"old-project-{uuid4()}", f"old-workspace-{uuid4()}"
        if baseline != "20260625_0001_initial_industrial_schema":
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
            assert connection.execute(
                "SELECT count(*) FROM nf_schema_migrations"
            ).fetchone()[0] == len(MIGRATIONS)
            tables = connection.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename LIKE 'authority_corpus_%'"
            ).fetchall()
            assert {row[0] for row in tables} == {
                "authority_corpus_" + name
                for name in (
                    "source",
                    "rights",
                    "snapshot",
                    "book_identity",
                    "edition",
                    "admission",
                    "membership",
                    "retirement",
                    "content",
                    "bridge",
                    "processing",
                    "review",
                    "equivalence",
                    "work_revision",
                    "work_member",
                    "curated_revision",
                    "curated_member",
                )
            }
            if baseline != "20260625_0001_initial_industrial_schema":
                after = _authority_facts(connection, project)
                for row in after["authority_source_document"]:
                    if "corpus_edition_id" not in historical_facts["authority_source_document"][0]:
                        assert row.pop("corpus_edition_id") is None
                assert {key: after[key] for key in historical_facts} == historical_facts
                assert all(
                    not value
                    for key, value in after.items()
                    if key not in historical_facts
                )
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
                assert job_after.get("corpus_snapshot_id") is None
                if "corpus_snapshot_id" not in job_before:
                    job_after.pop("corpus_snapshot_id")
                assert job_after == job_before
            index_names = {
                row[0]
                for row in connection.execute(
                    "SELECT indexname FROM pg_indexes WHERE tablename='authority_corpus_edition'"
                )
            }
            assert {
                "authority_corpus_edition_page_idx",
                "authority_corpus_edition_book_idx",
            } <= index_names
        assert run_migrations(url) == result
        evidence_dir = os.environ.get("CORPUS_EVIDENCE_DIR")
        if evidence_dir:
            Path(evidence_dir, "migration-" + baseline + ".json").write_text(
                json.dumps(
                    {
                        "baseline": baseline,
                        "result": result,
                        "existing_operation_preserved": baseline
                        != "20260625_0001_initial_industrial_schema",
                        "preserved_fact_counts": {
                            key: len(value) for key, value in historical_facts.items()
                        }
                        if baseline != "20260625_0001_initial_industrial_schema"
                        else {},
                    },
                    indent=2,
                )
            )


def _authority_facts(connection, project):
    return {
        table: sorted(
            [
                row[0]
                for row in connection.execute(
                    sql.SQL("SELECT to_jsonb(r) FROM {} r WHERE project_id=%s").format(
                        sql.Identifier(table)
                    ),
                    [project],
                )
            ],
            key=lambda row: json.dumps(row, sort_keys=True, default=str),
        )
        for table in (
            "authority_source_document",
            "authority_source_chunk",
            "authority_mkaos_knowledge_candidate",
            "authority_book",
            "authority_corpus_source",
            "authority_corpus_rights",
            "authority_corpus_snapshot",
            "authority_corpus_book_identity",
            "authority_corpus_edition",
            "authority_corpus_admission",
            "authority_corpus_membership",
        )
        if connection.execute("SELECT to_regclass(%s)", [table]).fetchone()[0]
        is not None
    }


def _seed_premerge_authority_facts(url, project, workspace):
    from novel_forge.modules.book_design_authority import (
        BookDesignAuthorityApplication,
        BookDesignAuthorityCommand,
    )
    from tests.integration import authority_postgres_support as support
    from tests.integration import test_mkaos_authority_postgres as fixtures

    BookDesignAuthorityApplication(
        url, application_build_id="upgrade-facts", commit_sha="e" * 40
    ).execute(
        BookDesignAuthorityCommand(
            definition_name="book.create",
            project_id=project,
            workspace_id=workspace,
            book_id="upgrade-book",
            actor_id="upgrade-operator",
            service_identity="book-design-authority",
            idempotency_key="upgrade-book",
            trace_id="upgrade-book",
            correlation_id=project,
            payload={
                "schema_version": "book-authority.v1",
                "title": "升级前作品",
                "production_profile": {"environment": "test"},
                "runtime_policy": {"execution_fallback": "FAIL_CLOSED"},
                "release_identity": "upgrade-facts@" + "e" * 40,
            },
        )
    )
    with (
        patch.object(support, "DATABASE_URL", url),
        patch.object(fixtures, "DATABASE_URL", url),
    ):
        fixture = fixtures.MkaosAuthorityPostgresTests()
        fixture.project_id, fixture.workspace_id = project, workspace
        # COMPATIBILITY: Seed the old schema contract directly; running today's
        # Source/MKAOS applications against an unmigrated schema is not supported.
        import hashlib

        raw, chunk_bytes = b"historical source bytes", b"historical normalized evidence"

        def digest(value):
            return "sha256:" + hashlib.sha256(value).hexdigest()

        raw_blob = fixture._insert_available_blob(project, raw)
        chunk_blob = fixture._insert_available_blob(project, chunk_bytes)
        versions = {
            kind: fixture._insert_asset_version(
                project, kind, {"historical_migration_fixture": True}
            )
            for kind in (
                "source_document",
                "source_transform",
                "source_chunk",
                "knowledge_candidate",
                "model_call_log",
            )
        }
        ids = {key: value.removesuffix(":v1") for key, value in versions.items()}
        with psycopg.connect(url) as connection:
            with connection.cursor() as cursor:
                definition, operation = "historical-facts-" + str(uuid4()), str(uuid4())
                insert_definition(cursor, definition)
                insert_operation(
                    cursor,
                    operation_id=operation,
                    definition_name=definition,
                    project_id=project,
                    workspace_id=workspace,
                )
                cursor.execute(
                    """INSERT INTO authority_source_document(
                    source_document_id,project_id,workspace_id,asset_version_id,blob_id,source_content_hash,source_size,media_type,title,
                    source_kind,source_uri,rights_authorization,license_name,copyright_boundary,governance_status,created_by_operation_id)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,'text/plain','历史来源','licensed_research','urn:historical-fixture','owned','owner-rights','abstract only','ELIGIBLE',%s)""",
                    [
                        ids["source_document"],
                        project,
                        workspace,
                        versions["source_document"],
                        raw_blob,
                        digest(raw),
                        len(raw),
                        operation,
                    ],
                )
                cursor.execute(
                    """INSERT INTO authority_source_transform(
                    source_transform_id,project_id,workspace_id,source_document_id,source_asset_version_id,asset_version_id,created_by_operation_id,
                    normalization_version,chunking_version,chunking_policy_hash,manifest_hash,chunk_count,total_chunk_bytes,status)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,'historical:v1','historical:v1',%s,%s,1,%s,'ACTIVE')""",
                    [
                        ids["source_transform"],
                        project,
                        workspace,
                        ids["source_document"],
                        versions["source_document"],
                        versions["source_transform"],
                        operation,
                        digest(b"policy"),
                        digest(b"manifest"),
                        len(chunk_bytes),
                    ],
                )
                cursor.execute(
                    """INSERT INTO authority_source_chunk(
                    source_chunk_id,project_id,workspace_id,source_transform_id,source_document_id,asset_version_id,blob_id,chunk_index,content_hash,
                    byte_size,character_count,token_count,source_byte_start,source_byte_end,created_by_operation_id)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,0,%s,%s,%s,5,0,%s,%s)""",
                    [
                        ids["source_chunk"],
                        project,
                        workspace,
                        ids["source_transform"],
                        ids["source_document"],
                        versions["source_chunk"],
                        chunk_blob,
                        digest(chunk_bytes),
                        len(chunk_bytes),
                        len(chunk_bytes),
                        len(raw),
                        operation,
                    ],
                )
                cursor.execute(
                    """INSERT INTO authority_mkaos_knowledge_candidate(
                    knowledge_candidate_id,project_id,workspace_id,asset_version_id,execution_asset_version_id,created_by_operation_id,candidate_hash,abstraction_policy_version,status)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,'historical:v1','NEEDS_REVIEW')""",
                    [
                        ids["knowledge_candidate"],
                        project,
                        workspace,
                        versions["knowledge_candidate"],
                        versions["model_call_log"],
                        operation,
                        digest(b"candidate"),
                    ],
                )

    with psycopg.connect(url) as connection:
        has_corpus = (
            connection.execute(
                "SELECT to_regclass('authority_corpus_source')"
            ).fetchone()[0]
            is not None
        )
    if has_corpus:
        from novel_forge.modules.source_authority import (
            SourceAuthorityApplication,
            SourceAuthorityScheduler,
        )
        from novel_forge.modules.source_authority.corpus import validate_corpus_action
        from novel_forge.modules.source_authority.corpus_application import (
            CorpusCommand,
        )

        authority = SourceAuthorityApplication(
            url, application_build_id="upgrade-facts", commit_sha="e" * 40
        )
        scheduler = SourceAuthorityScheduler(authority)

        def apply(action):
            key = str(uuid4())
            admitted = authority.admit_corpus(
                CorpusCommand(
                    project_id=project,
                    workspace_id=workspace,
                    actor_id="upgrade-operator",
                    idempotency_key=key,
                    trace_id=key,
                    correlation_id=key,
                    action=validate_corpus_action(action),
                )
            )
            return scheduler.run_or_recover(
                operation_id=admitted["operation_id"], project_id=project
            )

        source = apply(
            {
                "action": "register_source",
                "source_kind": "historical-metadata",
                "external_identity": "urn:historical:corpus",
                "purpose": "RESEARCH",
            }
        )["source_id"]
        rights = apply(
            {
                "action": "declare_rights",
                "source_id": source,
                "scope": "ALL_WORKS_IN_SNAPSHOT",
                "dataset_license": "MIT",
                "underlying_rights": "UNKNOWN",
                "allowed_purposes": ["RESEARCH"],
                "evidence_refs": ["historical:metadata-only"],
                "copyright_boundary": "no production grant",
            }
        )["rights_id"]
        snapshot = apply(
            {
                "action": "freeze_snapshot",
                "source_id": source,
                "rights_id": rights,
                "manifest": {
                    "origin_uri": "urn:historical:corpus",
                    "external_version": "historical:1",
                    "format": "manifest",
                    "checksum": digest(b"metadata"),
                    "adapter_profile": "metadata",
                    "adapter_contract_version": "v1",
                },
                "acquisition": {
                    "locator": "urn:historical:corpus",
                    "acquired_at": "2026-09-08T00:00:00Z",
                    "receipt_ref": "operator-declared-not-download",
                    "checksum": digest(b"metadata"),
                },
            }
        )["snapshot_id"]
        apply(
            {
                "action": "import_batch",
                "snapshot_id": snapshot,
                "batch_key": "historical:1",
                "entries": [
                    {
                        "external_work_id": "historical:book",
                        "external_edition_id": "1",
                        "title": "保留历史版本",
                        "checksum": digest(b"edition"),
                        "locator": "urn:historical:book",
                    }
                ],
            }
        )
    with psycopg.connect(url) as connection:
        facts = _authority_facts(connection, project)
    assert all(facts.values())
    return facts


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

        assert result["ok"] and result["current"] == LATEST_MIGRATION_ID
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


def _project_facts(connection, project, tables):
    return {
        table: sorted(
            [
                row[0]
                for row in connection.execute(
                    sql.SQL("SELECT to_jsonb(r) FROM {} r WHERE project_id=%s").format(
                        sql.Identifier(table)
                    ),
                    [project],
                )
            ],
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
