from __future__ import annotations

import unittest

from novel_forge.modules.command_kernel.budget_runtime import (
    BudgetReservationRequest,
    reserve_provider_budget,
    resolve_provider_budget_failure,
    settle_provider_budget,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_runtime import (
    EffectCommandContext,
    dispatch_external_effect,
    plan_external_effect,
)
from novel_forge.modules.command_kernel.external_effect_adapters import FakeDeterministicProvider
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    insert_definition,
    insert_operation,
    transaction,
)


class ProviderBudgetRuntimePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_reserve_settle_and_cap_enforcement(self) -> None:
        context, effect_id = self._effect("success")
        reservation = reserve_provider_budget(
            DATABASE_URL,
            BudgetReservationRequest(
                operation_id=context.operation_id,
                external_effect_id=effect_id,
                project_id=context.project_id,
                stable_idempotency_key=f"budget:{effect_id}",
                provider="fake_deterministic_provider",
                currency="USD",
                estimated_amount="1.25",
                estimated_tokens=1200,
                chapter=1,
                caps={"project": "2.00", "operation": "1.50", "daily": "2.00"},
            ),
        )
        replay = reserve_provider_budget(
            DATABASE_URL,
            BudgetReservationRequest(
                operation_id=context.operation_id,
                external_effect_id=effect_id,
                project_id=context.project_id,
                stable_idempotency_key=f"budget:{effect_id}",
                provider="fake_deterministic_provider",
                currency="USD",
                estimated_amount="1.25",
                estimated_tokens=1200,
                chapter=1,
                caps={"project": "2.00", "operation": "1.50", "daily": "2.00"},
            ),
        )
        self.assertTrue(replay["replayed"])

        dispatch_external_effect(
            DATABASE_URL,
            context,
            effect_id=effect_id,
            worker_id="provider-budget-worker",
            lease_seconds=30,
            adapter=FakeDeterministicProvider("success"),
        )
        settled = settle_provider_budget(
            DATABASE_URL,
            reservation_id=reservation["reservation_id"],
            project_id=context.project_id,
            actual_amount="0.75",
            actual_tokens=800,
            evidence={"model_id": "fixture-model", "fixture": True},
        )
        self.assertEqual(settled["status"], "SETTLED")
        with self.assertRaises(KernelError) as overrun:
            settle_provider_budget(
                DATABASE_URL,
                reservation_id=reservation["reservation_id"],
                project_id=context.project_id,
                actual_amount="1.30",
                actual_tokens=1300,
                evidence={"model_id": "fixture-model"},
            )
        self.assertEqual(overrun.exception.code, "BUDGET_SETTLEMENT_CONFLICT")

    def test_unknown_effect_holds_reservation_for_reconciliation(self) -> None:
        context, effect_id = self._effect("timeout_after")
        reservation = reserve_provider_budget(
            DATABASE_URL,
            BudgetReservationRequest(
                operation_id=context.operation_id,
                external_effect_id=effect_id,
                project_id=context.project_id,
                stable_idempotency_key=f"budget:{effect_id}",
                provider="fake_deterministic_provider",
                currency="USD",
                estimated_amount="1.00",
                estimated_tokens=1000,
            ),
        )
        result = dispatch_external_effect(
            DATABASE_URL,
            context,
            effect_id=effect_id,
            worker_id="provider-unknown-worker",
            lease_seconds=30,
            adapter=FakeDeterministicProvider("timeout_after"),
        )
        self.assertEqual(result["outcome"], "unknown")
        held = resolve_provider_budget_failure(
            DATABASE_URL,
            reservation_id=reservation["reservation_id"],
            project_id=context.project_id,
        )
        self.assertEqual(held["status"], "HELD_UNKNOWN")

    def _effect(self, scenario: str) -> tuple[EffectCommandContext, str]:
        project_id = identifier("budget-project")
        operation_id = identifier("budget-operation")
        definition = identifier("budget-definition")
        with transaction() as connection, connection.cursor() as cursor:
            insert_definition(cursor, definition)
            insert_operation(
                cursor,
                operation_id=operation_id,
                definition_name=definition,
                project_id=project_id,
                status="EXECUTING",
            )
        context = EffectCommandContext(
            operation_id=operation_id,
            project_id=project_id,
            actor_id="provider-budget-test",
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        effect_id = plan_external_effect(
            DATABASE_URL,
            context,
            effect_type="model.invoke",
            provider="fake_deterministic_provider",
            capability="model.fixture",
            stable_idempotency_key=identifier("effect-key"),
            request_payload={"scenario": scenario},
            max_attempts=2,
            reversible=False,
            completion_policy="synchronous_final",
            model_id="fixture-model",
            request_timeout_seconds=60,
            reconciliation_mode="query",
        )["external_effect_id"]
        return context, str(effect_id)


if __name__ == "__main__":
    unittest.main()
