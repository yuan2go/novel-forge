from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

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
from novel_forge.modules.command_kernel.external_effect_adapters import (
    FakeDeterministicProvider,
)
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
                caps={
                    "project_total": "2.00",
                    "operation_total": "1.50",
                    "project_daily": "2.00",
                },
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
                caps={
                    "project_total": "2.00",
                    "operation_total": "1.50",
                    "project_daily": "2.00",
                },
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

    def test_account_entitlement_settles_tokens_with_unknown_monetary_cost(
        self,
    ) -> None:
        context, effect_id = self._effect("success")
        authorization_ref = "task-authorization:classical-corpus-20260908"
        reservation = reserve_provider_budget(
            DATABASE_URL,
            BudgetReservationRequest(
                operation_id=context.operation_id,
                external_effect_id=effect_id,
                project_id=context.project_id,
                stable_idempotency_key=f"budget:{effect_id}",
                provider="production_execution_gateway",
                currency="UNKNOWN",
                estimated_amount=None,
                estimated_tokens=1_200,
                accounting_basis="ACCOUNT_ENTITLEMENT",
                cost_authorization_ref=authorization_ref,
                call_caps={"project_total": 1},
                token_caps={"project_total": 2_000},
            ),
        )

        settled = settle_provider_budget(
            DATABASE_URL,
            reservation_id=str(reservation["reservation_id"]),
            project_id=context.project_id,
            actual_amount=None,
            actual_tokens=800,
            evidence={
                "model_id": "gpt-5.6-sol",
                "real_model_call": True,
                "accounting_basis": "ACCOUNT_ENTITLEMENT",
                "cost_status": "UNKNOWN",
            },
        )

        self.assertEqual(settled["status"], "SETTLED")
        self.assertEqual(settled["accounting_basis"], "ACCOUNT_ENTITLEMENT")
        self.assertEqual(settled["cost_status"], "UNKNOWN")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT estimated_amount,reserved_amount,settled_amount,
                       accounting_basis,estimated_cost_status,settled_cost_status,
                       evidence->>'cost_authorization_ref'
                FROM authority_budget_reservation
                WHERE reservation_id=%s
                """,
                [reservation["reservation_id"]],
            )
            self.assertEqual(
                cursor.fetchone(),
                (
                    None,
                    None,
                    None,
                    "ACCOUNT_ENTITLEMENT",
                    "UNKNOWN",
                    "UNKNOWN",
                    authorization_ref,
                ),
            )
            cursor.execute(
                """
                SELECT amount,currency,accounting_basis,cost_status,
                       evidence->>'cost_authorization_ref'
                FROM authority_operation_cost_evidence
                WHERE cost_evidence_id=%s
                """,
                [f"budget-cost:{reservation['reservation_id']}"],
            )
            self.assertEqual(
                cursor.fetchone(),
                (
                    None,
                    "UNKNOWN",
                    "ACCOUNT_ENTITLEMENT",
                    "UNKNOWN",
                    authorization_ref,
                ),
            )

        with self.assertRaises(KernelError) as fake_cost:
            settle_provider_budget(
                DATABASE_URL,
                reservation_id=str(reservation["reservation_id"]),
                project_id=context.project_id,
                actual_amount="0",
                actual_tokens=800,
                evidence={"model_id": "gpt-5.6-sol"},
            )
        self.assertEqual(fake_cost.exception.code, "BUDGET_SETTLEMENT_INVALID")

        second_context, second_effect_id = self._effect_for_project(context.project_id)
        with self.assertRaises(KernelError) as exhausted:
            reserve_provider_budget(
                DATABASE_URL,
                BudgetReservationRequest(
                    operation_id=second_context.operation_id,
                    external_effect_id=second_effect_id,
                    project_id=context.project_id,
                    stable_idempotency_key=f"budget:{second_effect_id}",
                    provider="production_execution_gateway",
                    currency="UNKNOWN",
                    estimated_amount=None,
                    estimated_tokens=1_000,
                    accounting_basis="ACCOUNT_ENTITLEMENT",
                    cost_authorization_ref=authorization_ref,
                    call_caps={"project_total": 1},
                    token_caps={"project_total": 2_000},
                ),
            )
        self.assertEqual(exhausted.exception.code, "BUDGET_CALL_CAP_EXCEEDED")

    def test_account_entitlement_reconciles_cli_visible_estimate_within_token_cap(
        self,
    ) -> None:
        context, effect_id = self._effect("success")
        reservation = reserve_provider_budget(
            DATABASE_URL,
            BudgetReservationRequest(
                operation_id=context.operation_id,
                external_effect_id=effect_id,
                project_id=context.project_id,
                stable_idempotency_key=f"budget:{effect_id}",
                provider="production_execution_gateway",
                currency="UNKNOWN",
                estimated_amount=None,
                estimated_tokens=1_200,
                accounting_basis="ACCOUNT_ENTITLEMENT",
                cost_authorization_ref="task-authorization:cli-entitlement",
                call_caps={"project_total": 1},
                token_caps={"project_total": 2_000},
            ),
        )

        with self.assertRaises(KernelError) as initial:
            settle_provider_budget(
                DATABASE_URL,
                reservation_id=str(reservation["reservation_id"]),
                project_id=context.project_id,
                actual_amount=None,
                actual_tokens=1_800,
                evidence={"model_id": "gpt-5.6-sol", "real_model_call": True},
            )
        self.assertEqual(
            initial.exception.code, "BUDGET_ACTUAL_EXCEEDS_RESERVATION"
        )

        settled = settle_provider_budget(
            DATABASE_URL,
            reservation_id=str(reservation["reservation_id"]),
            project_id=context.project_id,
            actual_amount=None,
            actual_tokens=1_800,
            evidence={
                "model_id": "gpt-5.6-sol",
                "real_model_call": True,
                "token_accounting_precision": "APPLICATION_VISIBLE_UPPER_BOUND",
                "actual_token_source": "PROVIDER_USAGE_RECEIPT",
            },
        )

        self.assertEqual(settled["status"], "SETTLED")
        self.assertTrue(settled["entitlement_usage_reconciled"])
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT estimated_tokens,actual_tokens,status,budget_breach,
                       evidence->>'pre_call_token_control',
                       evidence->>'actual_usage_cap_revalidated'
                FROM authority_budget_reservation
                WHERE reservation_id=%s
                """,
                [reservation["reservation_id"]],
            )
            self.assertEqual(
                cursor.fetchone(),
                (
                    1_200,
                    1_800,
                    "SETTLED",
                    False,
                    "APPLICATION_VISIBLE_ONLY",
                    "true",
                ),
            )

    def test_account_entitlement_cli_estimate_overrun_still_honors_token_cap(
        self,
    ) -> None:
        context, effect_id = self._effect("success")
        reservation = reserve_provider_budget(
            DATABASE_URL,
            BudgetReservationRequest(
                operation_id=context.operation_id,
                external_effect_id=effect_id,
                project_id=context.project_id,
                stable_idempotency_key=f"budget:{effect_id}",
                provider="production_execution_gateway",
                currency="UNKNOWN",
                estimated_amount=None,
                estimated_tokens=1_200,
                accounting_basis="ACCOUNT_ENTITLEMENT",
                cost_authorization_ref="task-authorization:cli-entitlement",
                call_caps={"project_total": 1},
                token_caps={"project_total": 1_500},
            ),
        )

        with self.assertRaises(KernelError) as error:
            settle_provider_budget(
                DATABASE_URL,
                reservation_id=str(reservation["reservation_id"]),
                project_id=context.project_id,
                actual_amount=None,
                actual_tokens=1_800,
                evidence={
                    "model_id": "gpt-5.6-sol",
                    "real_model_call": True,
                    "token_accounting_precision": (
                        "APPLICATION_VISIBLE_UPPER_BOUND"
                    ),
                    "actual_token_source": "PROVIDER_USAGE_RECEIPT",
                },
            )

        self.assertEqual(error.exception.code, "BUDGET_ACTUAL_EXCEEDS_RESERVATION")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT status,budget_breach,evidence->>'token_cap_error_code'
                FROM authority_budget_reservation
                WHERE reservation_id=%s
                """,
                [reservation["reservation_id"]],
            )
            self.assertEqual(
                cursor.fetchone(),
                ("HELD_UNKNOWN", True, "BUDGET_TOKEN_CAP_EXCEEDED"),
            )

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

    def test_success_dispatch_receipt_gap_never_releases_reservation(self) -> None:
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
                estimated_amount="1.00",
                estimated_tokens=1000,
            ),
        )
        with patch(
            "novel_forge.modules.command_kernel.external_effect_runtime."
            "accept_external_effect_receipt",
            side_effect=RuntimeError("receipt transaction unavailable"),
        ):
            with self.assertRaises(RuntimeError):
                dispatch_external_effect(
                    DATABASE_URL,
                    context,
                    effect_id=effect_id,
                    worker_id="provider-receipt-gap-worker",
                    lease_seconds=30,
                    adapter=FakeDeterministicProvider("success"),
                )

        held = resolve_provider_budget_failure(
            DATABASE_URL,
            reservation_id=reservation["reservation_id"],
            project_id=context.project_id,
        )
        self.assertEqual(held["status"], "HELD_UNKNOWN")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT effect.status,reservation.status
                FROM authority_external_effect AS effect
                JOIN authority_budget_reservation AS reservation
                  ON reservation.external_effect_id=effect.external_effect_id
                WHERE effect.external_effect_id=%s
                  AND reservation.reservation_id=%s
                """,
                [effect_id, reservation["reservation_id"]],
            )
            self.assertEqual(cursor.fetchone(), ("DISPATCHED", "HELD_UNKNOWN"))

    def test_invalid_dimension_chapter_scope_and_timezone_fail_closed(self) -> None:
        for caps, timezone, code in (
            ({"daily": "1"}, "UTC", "BUDGET_CAP_INVALID"),
            ({"chapter_total": "1"}, "UTC", "BUDGET_CAP_INVALID"),
            ({"project_daily": "1"}, "Not/A_Real_Zone", "BUDGET_TIMEZONE_INVALID"),
        ):
            with self.subTest(code=code, caps=caps):
                context, effect_id = self._effect("success")
                with self.assertRaises(KernelError) as error:
                    reserve_provider_budget(
                        DATABASE_URL,
                        BudgetReservationRequest(
                            operation_id=context.operation_id,
                            external_effect_id=effect_id,
                            project_id=context.project_id,
                            stable_idempotency_key=identifier("invalid-budget"),
                            provider="fake_deterministic_provider",
                            currency="USD",
                            estimated_amount="0.5",
                            estimated_tokens=10,
                            caps=caps,
                            budget_timezone=timezone,
                        ),
                    )
                self.assertEqual(error.exception.code, code)

    def test_actual_cost_breach_is_held_for_manual_resolution(self) -> None:
        context, effect_id = self._effect("success")
        reservation = reserve_provider_budget(
            DATABASE_URL,
            BudgetReservationRequest(
                operation_id=context.operation_id,
                external_effect_id=effect_id,
                project_id=context.project_id,
                stable_idempotency_key=identifier("breach"),
                provider="fake_deterministic_provider",
                currency="USD",
                estimated_amount="0.5",
                estimated_tokens=10,
            ),
        )
        with self.assertRaises(KernelError) as error:
            settle_provider_budget(
                DATABASE_URL,
                reservation_id=reservation["reservation_id"],
                project_id=context.project_id,
                actual_amount="0.75",
                actual_tokens=11,
                evidence={"fixture": True},
            )
        self.assertEqual(error.exception.code, "BUDGET_ACTUAL_EXCEEDS_RESERVATION")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT status, budget_breach FROM authority_budget_reservation WHERE reservation_id = %s",
                [reservation["reservation_id"]],
            )
            self.assertEqual(cursor.fetchone(), ("HELD_UNKNOWN", True))

    def test_concurrent_project_cap_serializes_reservations(self) -> None:
        project_id = identifier("concurrent-budget-project")
        effects = [self._effect_for_project(project_id) for _ in range(2)]

        def reserve(item):
            context, effect_id = item
            try:
                return reserve_provider_budget(
                    DATABASE_URL,
                    BudgetReservationRequest(
                        operation_id=context.operation_id,
                        external_effect_id=effect_id,
                        project_id=project_id,
                        stable_idempotency_key=identifier("concurrent"),
                        provider="fake_deterministic_provider",
                        currency="USD",
                        estimated_amount="0.75",
                        estimated_tokens=10,
                        caps={"project_total": "1.00"},
                    ),
                )["status"]
            except KernelError as error:
                return error.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(reserve, effects))
        self.assertEqual(sorted(outcomes), ["BUDGET_CAP_EXCEEDED", "RESERVED"])

    def test_currency_scopes_do_not_cross_contaminate_global_cap(self) -> None:
        project_id = identifier("currency-budget-project")
        first_context, first_effect = self._effect_for_project(project_id)
        second_context, second_effect = self._effect_for_project(project_id)
        currency_prefix = project_id[-8:].upper()
        for context, effect, currency in (
            (first_context, first_effect, f"X{currency_prefix}A"),
            (second_context, second_effect, f"X{currency_prefix}B"),
        ):
            reserved = reserve_provider_budget(
                DATABASE_URL,
                BudgetReservationRequest(
                    operation_id=context.operation_id,
                    external_effect_id=effect,
                    project_id=project_id,
                    stable_idempotency_key=identifier(currency),
                    provider="fake_deterministic_provider",
                    currency=currency,
                    estimated_amount="0.75",
                    estimated_tokens=10,
                    caps={"global_daily": "1.00"},
                ),
            )
            self.assertEqual(reserved["status"], "RESERVED")

    def _effect(self, scenario: str) -> tuple[EffectCommandContext, str]:
        project_id = identifier("budget-project")
        return self._effect_for_project(project_id, scenario=scenario)

    def _effect_for_project(
        self, project_id: str, *, scenario: str = "success"
    ) -> tuple[EffectCommandContext, str]:
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
