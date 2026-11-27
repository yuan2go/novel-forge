from uuid import uuid4

import psycopg

from novel_forge.storage.migrations import run_migrations, LATEST_MIGRATION_ID
from novel_forge.modules.project_authority import (
    ProjectAuthorityApplication,
    ProjectAuthorityCommand,
)
from tests.integration.authority_postgres_support import DATABASE_URL
from tests.integration.migration_window_postgres_support import (
    disposable_database_at_migration,
)


def test_expired_retry_after_does_not_silently_resume_stopped_site():
    import pytest
    from novel_forge.modules.command_kernel.errors import KernelError
    from novel_forge.modules.source_import.market_runtime import site_slot, stop_site

    with disposable_database_at_migration(
        DATABASE_URL, prefix="market_site", target_migration_id=LATEST_MIGRATION_ID
    ) as url:
        site_slot(url, 1)
        stop_site(url, "RATE_LIMITED", 120)
        with pytest.raises(KernelError, match="MARKET_SITE_STOPPED"):
            site_slot(url, 1)
        with psycopg.connect(url) as connection:
            connection.execute(
                "UPDATE authority_source_market_site SET blocked_until=NOW()-interval '1 second'"
            )
        with pytest.raises(KernelError, match="MARKET_SITE_STOPPED"):
            site_slot(url, 1)


def test_market_forward_upgrade_preserves_existing_project_and_installs_scope_guards():
    with disposable_database_at_migration(
        DATABASE_URL,
        prefix="market_upgrade",
        target_migration_id="20261008_0181_author_manuscript_delivery",
    ) as url:
        project, workspace = "market-upgrade:" + uuid4().hex, "workspace:" + uuid4().hex
        ProjectAuthorityApplication(
            url, application_build_id="market-upgrade", commit_sha="a" * 40
        ).execute(
            ProjectAuthorityCommand(
                definition_name="project_lifecycle.create",
                project_id=project,
                workspace_id=workspace,
                actor_id="fixture",
                idempotency_key=project,
                trace_id=project,
                correlation_id=project,
                payload={"title": "Preserved project"},
            )
        )
        with psycopg.connect(url) as connection:
            before = connection.execute(
                "SELECT to_jsonb(p) FROM authority_project p WHERE project_id=%s",
                [project],
            ).fetchone()
        result = run_migrations(url)
        assert result["ok"] and result["current"] == LATEST_MIGRATION_ID
        assert run_migrations(url) == result
        with psycopg.connect(url) as connection:
            assert (
                connection.execute(
                    "SELECT to_jsonb(p) FROM authority_project p WHERE project_id=%s",
                    [project],
                ).fetchone()
                == before
            )
            triggers = connection.execute(
                "SELECT tgname FROM pg_trigger WHERE tgname LIKE 'source_market_%%' AND NOT tgisinternal"
            ).fetchall()
            assert len(triggers) == 9
            assert (
                connection.execute(
                    "SELECT count(*) FROM authority_source_market_attempt"
                ).fetchone()[0]
                == 0
            )
