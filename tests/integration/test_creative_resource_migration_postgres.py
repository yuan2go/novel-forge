import psycopg

from novel_forge.modules.command_kernel.budget_runtime import BudgetReservationRequest, reserve_provider_budget, resolve_provider_budget_failure
from novel_forge.modules.command_kernel.external_effect_runtime import _hash
from psycopg.types.json import Jsonb
from novel_forge.storage.migrations import run_migrations, LATEST_MIGRATION_ID
from tests.integration import authority_postgres_support as support
from tests.integration.migration_window_postgres_support import disposable_database_at_migration


def test_previous_head_upgrade_retains_historical_unknown_reservation_and_frozen_intent(monkeypatch):
    with disposable_database_at_migration(support.DATABASE_URL, prefix="creative_resource", target_migration_id="20261005_0149_zero_increment_chapter_outcome") as url:
        monkeypatch.setattr(support, "DATABASE_URL", url)
        support.seed_authority_project_book(project_id="migration-project", workspace_id="migration-workspace", book_id="migration-book")
        with support.transaction() as connection, connection.cursor() as cursor:
            support.insert_definition(cursor, "fixture.creative.resource")
            support.insert_operation(cursor, operation_id="historical-operation", definition_name="fixture.creative.resource", project_id="migration-project", status="EXECUTING")
        effect = "historical-effect"
        payload = {"stage": "draft", "_production_execution": {"book_id": "migration-book"}}
        with psycopg.connect(url) as connection:
            connection.execute("INSERT INTO authority_external_effect(external_effect_id,operation_id,project_id,effect_type,stable_idempotency_key,status,request_hash,request_payload,provider,capability,max_attempts,reversible,model_id) VALUES (%s,'historical-operation','migration-project','model.invoke',%s,'READY',%s,%s,'deepseek','model.fixture',2,false,'deepseek-chat')", [effect,effect,_hash(payload),Jsonb(payload)])
        reservation = reserve_provider_budget(url, BudgetReservationRequest("historical-operation", effect, "migration-project", "historical-reservation", "deepseek", "USD", "0.5", 1000,
            work_id="migration-book", model_id="deepseek-chat", accounting_basis="PRICED"))
        resolve_provider_budget_failure(url, project_id="migration-project", reservation_id=reservation["reservation_id"], external_state_unknown=True)
        def snapshots():
            with psycopg.connect(url) as connection:
                return (connection.execute("SELECT * FROM authority_budget_reservation ORDER BY reservation_id").fetchall(),
                    connection.execute("SELECT * FROM authority_external_effect ORDER BY external_effect_id").fetchall(),
                    connection.execute("SELECT migration_id,applied_at FROM nf_schema_migrations ORDER BY applied_at,migration_id").fetchall())
        before = snapshots()
        status = run_migrations(url)
        assert status["ok"] and status["current"] == LATEST_MIGRATION_ID
        after = snapshots()
        assert before[0] == after[0] and before[1] == after[1]
        assert all(row in after[2] for row in before[2])
        assert run_migrations(url) == status
