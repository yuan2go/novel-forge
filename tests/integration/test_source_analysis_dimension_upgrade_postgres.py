from __future__ import annotations

import psycopg

from novel_forge.modules.source_authority.deconstruction import (
    SUPPORTED_DECONSTRUCTION_DIMENSIONS,
)
from novel_forge.storage.migrations import LATEST_MIGRATION_ID, run_migrations
from tests.integration.authority_postgres_support import DATABASE_URL
from tests.integration.migration_window_postgres_support import (
    disposable_database_at_migration,
)


BASELINE = "20260908_0122_source_work_manifest"


def test_source_analysis_dimension_upgrade_preserves_and_expands_constraint() -> None:
    with disposable_database_at_migration(
        DATABASE_URL,
        prefix="source_dimension_upgrade",
        target_migration_id=BASELINE,
    ) as url:
        with psycopg.connect(url) as connection:
            before = connection.execute(
                """
                SELECT pg_get_constraintdef(oid), convalidated
                FROM pg_constraint
                WHERE conname=
                    'authority_source_deconstruction_observation_dimension_check'
                """
            ).fetchone()
        assert before is not None
        assert "character_choice_cost" not in str(before[0])
        assert before[1] is True

        status = run_migrations(url)
        assert status["ok"] is True
        assert status["current"] == LATEST_MIGRATION_ID

        with psycopg.connect(url) as connection:
            after = connection.execute(
                """
                SELECT pg_get_constraintdef(oid), convalidated
                FROM pg_constraint
                WHERE conname=
                    'authority_source_deconstruction_observation_dimension_check'
                """
            ).fetchone()
        assert after is not None
        definition = str(after[0])
        assert after[1] is True
        for dimension in SUPPORTED_DECONSTRUCTION_DIMENSIONS:
            assert dimension in definition
