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

    def test_started_cli_failure_keeps_shared_allowance_and_legacy_receipts_count(self) -> None:
        from novel_forge.modules.command_kernel.budget_runtime import provider_project_usage
        from novel_forge.modules.command_kernel.external_effect_adapters import ProviderResult

        for started, legacy in ((True, False), (True, True), (False, False)):
            with self.subTest(started=started, legacy=legacy):
                class RejectedCli(FakeDeterministicProvider):
                    def execute(self, **kwargs):
                        return ProviderResult("retryable_failure", "fixture-cli-400", {
                            "production_execution": {
                                "execution_handle": {"transport": "LOCAL_CLI_REMOTE_INFERENCE"},
                                "execution_result": {"started_at": "2026-09-11T00:00:00Z" if started else None},
                            },
                        })

                context, effect = self._effect("retryable_failure")
                reservation = reserve_provider_budget(DATABASE_URL, BudgetReservationRequest(
                    operation_id=context.operation_id, external_effect_id=effect,
                    project_id=context.project_id, stable_idempotency_key=f"budget:{effect}",
                    provider="fake_deterministic_provider", currency="UNKNOWN", estimated_amount=None,
                    estimated_tokens=1200, accounting_basis="ACCOUNT_ENTITLEMENT",
                    cost_authorization_ref="fixture-user-grant", call_caps={"project_total": 1},
                    token_caps={"project_total": 2000},
                ))
                dispatch_external_effect(DATABASE_URL, context, effect_id=effect,
                    worker_id="fixture-worker", lease_seconds=30, adapter=RejectedCli("retryable_failure"))
                if legacy:
                    with patch("novel_forge.modules.command_kernel.budget_runtime._STARTED_CODEX_DISPATCH_SQL", "FALSE"):
                        failed = resolve_provider_budget_failure(DATABASE_URL,
                            reservation_id=reservation["reservation_id"], project_id=context.project_id)
                else:
                    failed = resolve_provider_budget_failure(DATABASE_URL,
                        reservation_id=reservation["reservation_id"], project_id=context.project_id)
                self.assertEqual(failed["status"], "HELD_UNKNOWN" if started and not legacy else "RELEASED")
                with transaction() as connection, connection.cursor() as cursor:
                    usage = provider_project_usage(cursor, context.project_id)
                self.assertEqual(usage["calls_used_or_reserved"], int(started))
                self.assertEqual(usage["conservative_tokens"], 1200 if started else 0)
                self.assertEqual(usage["recorded_actual_tokens"], 0)
                if not started:
                    continue
                second, second_effect = self._effect_for_project(context.project_id)
                for call_cap, token_cap, expected in [(1, 3000, "BUDGET_CALL_CAP_EXCEEDED"), (3, 2000, "BUDGET_TOKEN_CAP_EXCEEDED")]:
                    with self.subTest(cap=expected), self.assertRaises(KernelError) as raised:
                        reserve_provider_budget(DATABASE_URL, BudgetReservationRequest(
                            operation_id=second.operation_id, external_effect_id=second_effect,
                            project_id=context.project_id, stable_idempotency_key=f"budget:{second_effect}:{expected}",
                            provider="fake_deterministic_provider", currency="UNKNOWN", estimated_amount=None,
                            estimated_tokens=1000, accounting_basis="ACCOUNT_ENTITLEMENT",
                            cost_authorization_ref="fixture-user-grant", call_caps={"project_total": call_cap},
                            token_caps={"project_total": token_cap},
                        ))
                    self.assertEqual(raised.exception.code, expected)

    def test_legacy_cli_timeout_blocks_source_until_reconciled(self) -> None:
        from novel_forge.modules.command_kernel.budget_runtime import unresolved_cli_outcomes
        from novel_forge.modules.command_kernel.external_effect_adapters import ProviderResult
        from novel_forge.modules.source_import.corpus_ingestion.curated_analysis import require_known_cli_outcomes

        for process_outcome, started, blocked_expected in [
            ("UNKNOWN", True, True), ("TIMED_OUT", True, True), ("CANCELLED", False, False), ("ORPHANED", False, True)
        ]:
            with self.subTest(outcome=process_outcome, started=started):
                class TimedOutCli(FakeDeterministicProvider):
                    def execute(self, **kwargs):
                        return ProviderResult("unknown" if process_outcome == "UNKNOWN" else "retryable_failure", "fixture-timeout", {
                            "production_execution": {
                                "execution_handle": {"transport": "LOCAL_CLI_REMOTE_INFERENCE"},
                                "execution_result": {"started_at": "2026-09-11T00:00:00Z" if started else None,
                                    "outcome": process_outcome, "usage_receipt_ref": None,
                                    "process_receipt_ref": "fixture-local-only-receipt"},
                            },
                        })

                context, effect = self._effect("retryable_failure")
                reservation = reserve_provider_budget(DATABASE_URL, BudgetReservationRequest(
                    operation_id=context.operation_id, external_effect_id=effect,
                    project_id=context.project_id, stable_idempotency_key=f"budget:{effect}",
                    provider="fake_deterministic_provider", currency="UNKNOWN", estimated_amount=None,
                    estimated_tokens=1200, accounting_basis="ACCOUNT_ENTITLEMENT",
                    cost_authorization_ref="fixture-user-grant", call_caps={"project_total": 2},
                    token_caps={"project_total": 3000},
                ))
                dispatch_external_effect(DATABASE_URL, context, effect_id=effect,
                    worker_id="fixture-worker", lease_seconds=30, adapter=TimedOutCli("retryable_failure"))
                if process_outcome == "UNKNOWN":
                    resolve_provider_budget_failure(DATABASE_URL, reservation_id=reservation["reservation_id"], project_id=context.project_id)
                with transaction() as connection, connection.cursor() as cursor:
                    if process_outcome == "UNKNOWN":
                        cursor.execute("SELECT status,estimated_tokens FROM authority_budget_reservation WHERE external_effect_id=%s", [effect])
                        self.assertEqual(cursor.fetchone(), ("HELD_UNKNOWN", 1200))
                    rows = unresolved_cli_outcomes(cursor, context.project_id)
                    if not blocked_expected:
                        self.assertEqual(rows, [])
                        require_known_cli_outcomes(cursor, context.project_id)
                        continue
                    self.assertEqual(rows[0]["external_effect_id"], effect)
                    self.assertEqual(rows[0]["state"], "RECONCILIATION_REQUIRED")
                    with self.assertRaises(KernelError) as blocked:
                        require_known_cli_outcomes(cursor, context.project_id)
                    self.assertEqual(blocked.exception.code, "SOURCE_CLI_OUTCOME_RECONCILIATION_REQUIRED")
                    require_known_cli_outcomes(cursor, identifier("another-project"))

    def test_unknown_cli_generation_cannot_be_hidden_by_a_later_unsent_generation(self) -> None:
        from psycopg.types.json import Jsonb
        from novel_forge.modules.command_kernel.budget_runtime import require_known_cli_lineage, unresolved_cli_outcomes

        context, effect = self._effect("retryable_failure")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute("INSERT INTO authority_external_effect_dispatch (dispatch_id,external_effect_id,generation,status,payload_hash,evidence) VALUES (%s,%s,1,'FAILED_RETRYABLE','fixture',%s)",
                [identifier("original-dispatch"), effect, Jsonb({"production_execution": {
                    "execution_handle": {"transport": "LOCAL_CLI_REMOTE_INFERENCE"},
                    "execution_result": {"outcome": "RETRYABLE_FAILURE", "started_at": "2026-10-07T00:00:00Z",
                        "usage_receipt_ref": None, "process_receipt_ref": "original-local-receipt"},
                    "process_evidence": {"failure_code": "PROCESS_EXIT_FAILURE"}}})])
            cursor.execute("INSERT INTO authority_external_effect_dispatch (dispatch_id,external_effect_id,generation,status,payload_hash,evidence) VALUES (%s,%s,2,'CREATED','fixture','{}'::jsonb)",
                [identifier("unsent-dispatch"), effect])
            self.assertEqual(unresolved_cli_outcomes(cursor, context.project_id)[0]["process_receipt_ref"], "original-local-receipt")
            with self.assertRaises(KernelError) as blocked:
                require_known_cli_lineage(cursor, project_id=context.project_id, operation_id=context.operation_id)
            self.assertEqual(blocked.exception.code, "EFFECT_CLI_OUTCOME_RECONCILIATION_REQUIRED")

    def test_same_book_successor_send_rechecks_original_receipt_scope(self) -> None:
        from psycopg.types.json import Jsonb
        from novel_forge.modules.command_kernel.budget_runtime import require_known_cli_lineage, unresolved_cli_outcomes
        from novel_forge.modules.command_kernel.external_effect_runtime import prepare_effect_dispatch

        original, effect = self._effect("retryable_failure")
        replacement, replacement_effect = self._effect_for_project(original.project_id)
        unrelated, _ = self._effect_for_project(original.project_id)
        with transaction() as connection, connection.cursor() as cursor:
            for context, book in ((original, "original-book"), (replacement, "original-book"), (unrelated, "unrelated-book")):
                cursor.execute("UPDATE authority_operation SET command_payload=%s WHERE operation_id=%s", [Jsonb({"book_id": book}), context.operation_id])
            cursor.execute("INSERT INTO authority_external_effect_dispatch (dispatch_id,external_effect_id,generation,status,payload_hash,evidence) VALUES (%s,%s,1,'FAILED_RETRYABLE','fixture',%s)",
                [identifier("missing-start-dispatch"), effect, Jsonb({"production_execution": {
                    "execution_handle": {"transport": "LOCAL_CLI_REMOTE_INFERENCE"},
                    "execution_result": {"outcome": "TIMED_OUT", "usage_receipt_ref": "",
                        "process_receipt_ref": "missing-start-proof"}}})])
            self.assertEqual(len(unresolved_cli_outcomes(cursor, original.project_id, book_id="original-book")), 1)
            self.assertEqual(unresolved_cli_outcomes(cursor, original.project_id, book_id="unrelated-book"), [])
            require_known_cli_lineage(cursor, project_id=unrelated.project_id, operation_id=unrelated.operation_id)
        with self.assertRaises(KernelError) as blocked:
            prepare_effect_dispatch(DATABASE_URL, replacement, effect_id=replacement_effect)
        self.assertEqual(blocked.exception.code, "EFFECT_CLI_OUTCOME_RECONCILIATION_REQUIRED")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM authority_external_effect_dispatch WHERE external_effect_id=%s", [replacement_effect])
            self.assertEqual(cursor.fetchone()[0], 0)

    def _effect(self, scenario: str) -> tuple[EffectCommandContext, str]:
        project_id = identifier("budget-project")
        return self._effect_for_project(project_id, scenario=scenario)

    def test_canonical_book_request_blocks_a_new_root_without_book_payload(self) -> None:
        from psycopg.types.json import Jsonb
        from tests.integration.authority_postgres_support import seed_authority_project_book
        from novel_forge.modules.command_kernel.budget_runtime import require_known_cli_lineage
        from novel_forge.modules.command_kernel.external_effect_runtime import prepare_effect_dispatch

        project, workspace = identifier("canonical-project"), identifier("canonical-workspace")
        unrelated_workspace = identifier("unrelated-workspace")
        book_a, book_b = identifier("book-a"), identifier("book-b")
        seed_authority_project_book(project_id=project, workspace_id=workspace, book_id=book_a)
        seed_authority_project_book(project_id=project, workspace_id=unrelated_workspace, book_id=book_b, seed_project=False)
        original, effect = self._effect_for_project(project, workspace_id=workspace, metadata_book_id="synthetic-wrong-book")
        replacement, replacement_effect = self._effect_for_project(project, workspace_id=workspace)
        unrelated, _ = self._effect_for_project(project, workspace_id=unrelated_workspace)
        contexts = {key: "source:fixture" for key in (
            "volume_plan_version", "character_state_version", "foreshadowing_state_version",
            "quality_trend_version", "reward_ledger_version", "promise_ledger_version")}
        contexts["arc_plan_versions"] = ["source:fixture"]
        with transaction() as connection, connection.cursor() as cursor:
            for book, book_workspace, roots in ((book_a, workspace, (original, replacement)),
                    (book_b, unrelated_workspace, (unrelated,))):
                owner, _ = self._effect_for_project(project, workspace_id=book_workspace)
                run, saga = identifier("canonical-run"), identifier("canonical-saga")
                cursor.execute("INSERT INTO authority_saga(saga_id,root_operation_id,project_id,status,trace_id,correlation_id) VALUES (%s,%s,%s,'RUNNING',%s,%s)",
                    [saga, owner.operation_id, project, owner.trace_id, owner.correlation_id])
                cursor.execute("""INSERT INTO authority_book_production(book_run_id,project_id,workspace_id,book_id,
                    book_design_version,book_plan_version,production_profile_version,longform_context_versions,
                    root_operation_id,saga_id,stable_idempotency_key,state,target_chapter_count,light_recap_cadence,
                    formal_recap_cadence,input_mode) VALUES (%s,%s,%s,%s,'design:fixture','plan:fixture','profile:fixture',
                    %s,%s,%s,%s,'READY',3,1,1,'LEGACY_FIXTURE_INPUT_MODE')""",
                    [run, project, book_workspace, book, Jsonb(contexts), owner.operation_id, saga, run])
                for chapter, root in enumerate(roots, 1):
                    request = identifier("canonical-request")
                    cursor.execute("""INSERT INTO authority_book_chapter_request(chapter_request_id,book_run_id,
                        project_id,chapter_number,chapter_plan_version,chapter_plan_content_hash,production_profile_version,
                        stable_idempotency_key,command_payload,chapter_root_operation_id,status_reference)
                        VALUES (%s,%s,%s,%s,'plan:fixture','hash:fixture','profile:fixture',%s,'{}'::jsonb,%s,'ADMITTED')""",
                        [request, run, project, chapter, request, root.operation_id])
            cursor.execute("INSERT INTO authority_external_effect_dispatch(dispatch_id,external_effect_id,generation,status,payload_hash,evidence) VALUES (%s,%s,1,'FAILED_RETRYABLE','fixture',%s)",
                [identifier("canonical-unknown"), effect, Jsonb({"production_execution": {
                    "execution_handle": {"transport": "LOCAL_CLI_REMOTE_INFERENCE"},
                    "execution_result": {"outcome": "TIMED_OUT", "started_at": "2026-10-07T00:00:00Z",
                        "usage_receipt_ref": None, "process_receipt_ref": "canonical-original"}}})])
            require_known_cli_lineage(cursor, project_id=project, operation_id=unrelated.operation_id)
        with self.assertRaises(KernelError) as blocked:
            prepare_effect_dispatch(DATABASE_URL, replacement, effect_id=replacement_effect)
        self.assertEqual(blocked.exception.code, "EFFECT_CLI_OUTCOME_RECONCILIATION_REQUIRED")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM authority_external_effect_dispatch WHERE external_effect_id=%s", [replacement_effect])
            self.assertEqual(cursor.fetchone()[0], 0)

    def _effect_for_project(
        self, project_id: str, *, scenario: str = "success", workspace_id: str = "legacy-unknown", metadata_book_id: str | None = None
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
                workspace_id=workspace_id,
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
            request_payload={"scenario": scenario, **(
                {"_production_execution": {"book_id": metadata_book_id}} if metadata_book_id else {})},
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
