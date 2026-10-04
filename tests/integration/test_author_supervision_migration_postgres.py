import psycopg
import pytest

from novel_forge.storage.migrations import run_migrations
from tests.integration.authority_postgres_support import DATABASE_URL
from tests.integration.migration_window_postgres_support import disposable_database_at_migration


@pytest.mark.parametrize("baseline", ["20260625_0001_initial_industrial_schema", "20260927_0147_runtime_job_dispatch_pause"])
def test_supervised_snapshot_forward_migration_preserves_strict_contract(baseline):
    with disposable_database_at_migration(DATABASE_URL, prefix="author_supervision", target_migration_id=baseline) as url:
        result = run_migrations(url)
        assert result["ok"]
        assert run_migrations(url) == result
        with psycopg.connect(url) as connection:
            definition = connection.execute("""SELECT pg_get_constraintdef(oid) FROM pg_constraint
                WHERE conrelid='authority_book_production_input_snapshot'::regclass
                  AND conname='authority_book_production_design_admission_check'""").fetchone()[0]
            connection.execute("CREATE TEMP TABLE supervised_admission_probe (design_admission_status text, " + definition + ")")
            connection.execute("INSERT INTO supervised_admission_probe VALUES ('LEGACY_UNQUALIFIED'), ('LONGFORM_DESIGN_QUALIFIED'), ('AUTHOR_SUPERVISED_DESIGN')")
            with pytest.raises(psycopg.errors.CheckViolation):
                with connection.transaction():
                    connection.execute("INSERT INTO supervised_admission_probe VALUES ('QUALIFIED_BY_AUTHOR')")
            assert connection.execute("SELECT count(*) FROM supervised_admission_probe").fetchone()[0] == 3


@pytest.mark.parametrize("baseline", ["20260625_0001_initial_industrial_schema", "20260928_0148_author_supervised_design"])
def test_zero_increment_outcome_forward_views_preserve_accepted_history(baseline):
    with disposable_database_at_migration(DATABASE_URL, prefix="zero_outcome", target_migration_id=baseline) as url:
        result = run_migrations(url)
        assert result["ok"]
        assert run_migrations(url) == result
        with psycopg.connect(url) as connection:
            rebuild = connection.execute("SELECT pg_get_viewdef('authority_narrative_state_rebuild_source'::regclass, true)").fetchone()[0]
            events = connection.execute("SELECT pg_get_viewdef('authority_narrative_state_event_projection'::regclass, true)").fetchone()[0]
            assert all(version in rebuild for version in ("chapter-outcome-v1", "chapter-outcome-v2", "chapter-outcome-v3", "chapter-outcome-v4"))
            assert all(version in events for version in ("chapter-outcome-v2", "chapter-outcome-v3", "chapter-outcome-v4"))
            assert "WITH ORDINALITY" in events
            assert connection.execute("SELECT count(*) FROM authority_narrative_state_rebuild_source").fetchone()[0] == 0
