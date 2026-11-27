from __future__ import annotations

import psycopg
import pytest

from novel_forge.storage.migrations import LATEST_MIGRATION_ID, MIGRATIONS, get_migration_status, run_migrations
from psycopg.conninfo import make_conninfo
from tests.integration import authority_postgres_support as support
from tests.integration.migration_window_postgres_support import disposable_database_at_migration

MAIN_HEAD = "20261007_0159_planning_dead_letter_result_recovery"


def test_restored_migration_status_is_read_only_and_preserves_partial_history():
    with disposable_database_at_migration(support.DATABASE_URL, prefix="status_restore", target_migration_id=MAIN_HEAD) as url:
        before = _snapshot(url)
        readonly = make_conninfo(url, options="-c default_transaction_read_only=on")
        result = get_migration_status(readonly)
        assert not result["ok"] and not result["extra"]
        assert result["applied"][-1]["migration_id"] == MAIN_HEAD
        assert result["missing"][-1] == LATEST_MIGRATION_ID
        assert _snapshot(url) == before
        assert get_migration_status(readonly) == result


def test_missing_migration_ledger_is_reported_without_bootstrapping():
    with disposable_database_at_migration(support.DATABASE_URL, prefix="status_empty", target_migration_id=MIGRATIONS[0].migration_id) as url:
        with psycopg.connect(url) as connection:
            connection.execute("DROP TABLE nf_schema_migrations")
        result = get_migration_status(make_conninfo(url, options="-c default_transaction_read_only=on"))
        assert not result["ok"] and result["applied"] == []
        assert result["missing"] == result["available"]
        with psycopg.connect(url) as connection:
            assert connection.execute("SELECT to_regclass('nf_schema_migrations')").fetchone() == (None,)


def _snapshot(url):
    with psycopg.connect(url) as connection:
        return (
            connection.execute("SELECT migration_id,applied_at FROM nf_schema_migrations ORDER BY migration_id").fetchall(),
            connection.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").fetchall(),
            connection.execute("SELECT * FROM authority_external_effect ORDER BY external_effect_id").fetchall(),
            connection.execute("SELECT * FROM authority_budget_reservation ORDER BY reservation_id").fetchall(),
        )


@pytest.mark.parametrize("baseline", [MAIN_HEAD,
    "20260928_0148_author_supervised_design", "20261009_0184_cli_original_reconciliation"])
def test_fixed_main_upgrade_preserves_unknown_receipt_and_frozen_ledger(monkeypatch, baseline):
    from novel_forge.modules.command_kernel.budget_runtime import BudgetReservationRequest, reserve_provider_budget, resolve_provider_budget_failure
    from novel_forge.modules.command_kernel.external_effect_runtime import _hash
    from psycopg.types.json import Jsonb

    with disposable_database_at_migration(support.DATABASE_URL, prefix="native_integrate", target_migration_id=baseline) as url:
        monkeypatch.setattr(support, "DATABASE_URL", url)
        support.seed_authority_project_book(project_id="upgrade-project", workspace_id="upgrade-workspace", book_id="upgrade-book")
        with support.transaction() as connection:
            support.insert_definition(connection.cursor(), "fixture.native.upgrade")
            support.insert_operation(connection.cursor(), operation_id="frozen-operation", definition_name="fixture.native.upgrade", project_id="upgrade-project", status="EXECUTING")
        payload = {"stage":"draft", "_production_execution":{"book_id":"upgrade-book"}}
        effect = "frozen-effect"
        with psycopg.connect(url) as connection:
            # WHY: Historical rows predate the current Kernel isolation guard and its table.
            connection.execute("""INSERT INTO authority_external_effect
                (external_effect_id,operation_id,project_id,effect_type,stable_idempotency_key,
                 status,request_hash,request_payload,provider,capability,max_attempts,reversible,model_id)
                VALUES(%s,'frozen-operation','upgrade-project','model.invoke','frozen-effect',
                    'UNKNOWN',%s,%s,'deepseek','model.fixture',2,false,'deepseek-chat')""",
                [effect,_hash(payload),Jsonb(payload)])
        reservation = reserve_provider_budget(url, BudgetReservationRequest("frozen-operation", effect, "upgrade-project", "frozen-reservation", "deepseek", "USD", "0.5", 1000,
            work_id="upgrade-book", model_id="deepseek-chat", accounting_basis="PRICED"))
        resolve_provider_budget_failure(url, project_id="upgrade-project", reservation_id=reservation["reservation_id"], external_state_unknown=True)
        before = _snapshot(url)
        from novel_forge.storage.migrations import runner
        audit_boundary = "20261009_0194_multi_model_generation_isolation"
        prefix = MIGRATIONS[:next(i for i, migration in enumerate(MIGRATIONS) if migration.migration_id == audit_boundary) + 1]
        with monkeypatch.context() as window:
            pending = runner.pending_migrations
            window.setattr(runner, "pending_migrations", lambda applied: pending(applied, prefix))
            run_migrations(url)
        with psycopg.connect(url) as connection:
            applied = {row[0] for row in connection.execute("SELECT migration_id FROM nf_schema_migrations")}
        assert applied == {migration.migration_id for migration in prefix}
        result = run_migrations(url)
        assert result["ok"] and result["current"] == LATEST_MIGRATION_ID
        after = _snapshot(url)
        assert before[0] == [row for row in after[0] if row[0] in {old[0] for old in before[0]}]
        assert before[2:] == after[2:]
        assert run_migrations(url) == result


@pytest.mark.parametrize("history", ("foreign", "hole"))
def test_invalid_ledger_blocks_all_pending_business_ddl_and_preserves_history(history):
    with disposable_database_at_migration(support.DATABASE_URL, prefix="native_history", target_migration_id=MAIN_HEAD) as url:
        with psycopg.connect(url) as connection:
            if history == "foreign":
                connection.execute("INSERT INTO nf_schema_migrations(migration_id) VALUES ('20261006_0157_planning_result_admission')")
            else:
                connection.execute("DELETE FROM nf_schema_migrations WHERE migration_id=%s", [MIGRATIONS[1].migration_id])
        before = _snapshot(url)
        with pytest.raises(ValueError, match="MIGRATION_HISTORY"):
            run_migrations(url)
        assert _snapshot(url) == before
