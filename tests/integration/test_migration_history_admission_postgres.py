from __future__ import annotations

import psycopg
import pytest

from novel_forge.storage.migrations import LATEST_MIGRATION_ID, MIGRATIONS, run_migrations
from tests.integration import authority_postgres_support as support
from tests.integration.migration_window_postgres_support import disposable_database_at_migration

MAIN_HEAD = "20261007_0159_planning_dead_letter_result_recovery"


def _snapshot(url):
    with psycopg.connect(url) as connection:
        return (
            connection.execute("SELECT migration_id,applied_at FROM nf_schema_migrations ORDER BY migration_id").fetchall(),
            connection.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").fetchall(),
            connection.execute("SELECT * FROM authority_external_effect ORDER BY external_effect_id").fetchall(),
            connection.execute("SELECT * FROM authority_budget_reservation ORDER BY reservation_id").fetchall(),
        )


def test_fixed_main_upgrade_preserves_unknown_receipt_and_frozen_ledger(monkeypatch):
    from novel_forge.modules.command_kernel.budget_runtime import BudgetReservationRequest, reserve_provider_budget, resolve_provider_budget_failure
    from novel_forge.modules.command_kernel.external_effect_runtime import EffectCommandContext, plan_external_effect

    with disposable_database_at_migration(support.DATABASE_URL, prefix="native_integrate", target_migration_id=MAIN_HEAD) as url:
        monkeypatch.setattr(support, "DATABASE_URL", url)
        support.seed_authority_project_book(project_id="upgrade-project", workspace_id="upgrade-workspace", book_id="upgrade-book")
        with support.transaction() as connection:
            support.insert_definition(connection.cursor(), "fixture.native.upgrade")
            support.insert_operation(connection.cursor(), operation_id="frozen-operation", definition_name="fixture.native.upgrade", project_id="upgrade-project", status="EXECUTING")
        effect = plan_external_effect(url, EffectCommandContext("frozen-operation", "upgrade-project", "integration-operator", "upgrade-trace", "upgrade-book"),
            effect_type="model.invoke", provider="deepseek", capability="model.fixture", stable_idempotency_key="frozen-effect",
            request_payload={"stage": "draft", "_production_execution": {"book_id": "upgrade-book"}}, max_attempts=2, reversible=False, model_id="deepseek-chat")["external_effect_id"]
        reservation = reserve_provider_budget(url, BudgetReservationRequest("frozen-operation", effect, "upgrade-project", "frozen-reservation", "deepseek", "USD", "0.5", 1000,
            work_id="upgrade-book", model_id="deepseek-chat", accounting_basis="PRICED"))
        resolve_provider_budget_failure(url, project_id="upgrade-project", reservation_id=reservation["reservation_id"], external_state_unknown=True)
        before = _snapshot(url)
        result = run_migrations(url)
        assert result["ok"] and result["current"] == LATEST_MIGRATION_ID
        after = _snapshot(url)
        assert before[0] == [row for row in after[0] if row[0] <= MAIN_HEAD]
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
