import json
import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from novel_forge.modules.project_authority import (
    ProjectAuthorityApplication,
    ProjectAuthorityCommand,
)
from novel_forge.storage.migrations import LATEST_MIGRATION_ID, MIGRATIONS, run_migrations
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
                "authority_corpus_source_workspace_idx",
                "authority_corpus_rights_previous_scope_idx",
                "authority_corpus_snapshot_rights_scope_idx",
                "authority_corpus_snapshot_previous_scope_idx",
                "authority_corpus_edition_snapshot_scope_idx",
                "authority_corpus_edition_book_scope_idx",
                "authority_corpus_membership_admission_idx",
                "authority_corpus_retirement_source_scope_idx",
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
                    },
                    indent=2,
                )
            )
