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
