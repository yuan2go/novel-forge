from __future__ import annotations

import hashlib
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from psycopg.errors import CheckViolation
from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.budget_runtime import (
    BudgetAssessmentOutcome,
    BudgetReservationRequest,
    BudgetScopeRequest,
    assess_budget_scope_in_uow,
    create_or_get_budget_scope,
    reserve_provider_budget,
    reserve_provider_budget_in_uow,
    resolve_provider_token_reservation_contract,
    resolve_provider_budget_failure,
    settle_provider_budget,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_adapters import (
    FakeDeterministicProvider,
)
from novel_forge.modules.command_kernel.external_effect_runtime import (
    EffectCommandContext,
    dispatch_external_effect,
    plan_external_effect,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    insert_definition,
    insert_operation,
    seed_authority_project_book,
    transaction,
)


def _hash(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class ProviderBudgetScopePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_scope_creation_is_semantically_idempotent_and_policy_drift_fails(
        self,
    ) -> None:
        fixture = self._opening_scope()
        request = self._request(fixture)

        created = create_or_get_budget_scope(DATABASE_URL, request)
        replayed = create_or_get_budget_scope(DATABASE_URL, request)

        self.assertEqual(created["budget_scope_id"], request.budget_scope_id)
        self.assertFalse(created["replayed"])
        self.assertEqual(replayed, {**created, "replayed": True})
        with self.assertRaises(KernelError) as conflict:
            create_or_get_budget_scope(
                DATABASE_URL,
                BudgetScopeRequest(
                    **{
                        **self._request_values(fixture),
                        "policy_snapshot": {
                            "execution_mode": "PROVIDER_ALLOWED",
                            "provider_call_limit": 2,
                            "token_limit": 20_000,
                            "cost_limit_usd": "2",
                        },
                    }
                ),
            )
        self.assertEqual(conflict.exception.code, "BUDGET_SCOPE_IDEMPOTENCY_CONFLICT")

    def test_assessment_counts_scope_reservations_and_fails_closed_at_limit(
        self,
    ) -> None:
        fixture = self._opening_scope()
        scope = self._live_scope(fixture)
        before = self._assessment(scope)
        context = EffectCommandContext(
            operation_id=fixture["operation_id"],
            project_id=fixture["project_id"],
            actor_id="budget-scope-test",
            trace_id=identifier("budget-scope-trace"),
            correlation_id=identifier("budget-scope-correlation"),
        )
        effect_id = str(
            plan_external_effect(
                DATABASE_URL,
                context,
                effect_type="model.invoke",
                provider="fake_deterministic_provider",
                capability="model.fixture",
                stable_idempotency_key=identifier("budget-scope-effect"),
                request_payload={"fixture": True},
                max_attempts=1,
                reversible=False,
            )["external_effect_id"]
        )

        reservation = reserve_provider_budget(
            DATABASE_URL,
            BudgetReservationRequest(
                operation_id=fixture["operation_id"],
                external_effect_id=effect_id,
                project_id=fixture["project_id"],
                stable_idempotency_key=f"budget:{effect_id}",
                provider="fake_deterministic_provider",
                currency="USD",
                estimated_amount="0.50",
                estimated_tokens=1_000,
                budget_scope_id=scope["budget_scope_id"],
                expected_budget_scope_revision=scope["revision"],
            ),
        )
        after = self._assessment(scope)

        self.assertEqual(reservation["budget_scope_id"], scope["budget_scope_id"])
        self.assertEqual(before["outcome"], BudgetAssessmentOutcome.ELIGIBLE)
        self.assertEqual(after["outcome"], BudgetAssessmentOutcome.EXHAUSTED)
        self.assertEqual(after["usage"]["provider_call_count"], 1)
        self.assertEqual(after["usage"]["committed_tokens"], 1_000)
        self.assertEqual(after["usage"]["committed_amount"], "0.5")
        self.assertNotEqual(before["snapshot_hash"], after["snapshot_hash"])
        self.assertEqual(after["scope"]["revision"], scope["revision"])

    def test_account_entitlement_scope_enforces_calls_and_tokens_without_cost(
        self,
    ) -> None:
        fixture = self._opening_scope()
        authorization_ref = "task-authorization:classical-corpus-20260908"
        request_values = self._request_values(fixture)
        request_values.update(
            {
                "currency": "UNKNOWN",
                "policy_snapshot": {
                    "execution_mode": "PROVIDER_ALLOWED",
                    "accounting_basis": "ACCOUNT_ENTITLEMENT",
                    "authorization_ref": authorization_ref,
                    "cost_observability": "UNKNOWN",
                    "provider_call_limit": 1,
                    "token_limit": 1_000,
                    "per_call_token_limit": 1_000,
                },
            }
        )
        scope = self._live_scope(
            fixture,
            request=BudgetScopeRequest(**request_values),
        )
        from novel_forge.modules.book_authority.recovery import (
            PostgresBookOpeningRecoveryApplication,
        )

        recovery = object.__new__(PostgresBookOpeningRecoveryApplication)
        run = {
            "project_id": fixture["project_id"],
            "budget_scope_id": scope["budget_scope_id"],
            "budget_scope_revision": scope["revision"],
            "budget_contract_state": "BOUND",
        }
        for provider_required in (False, True):
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                recovery_budget = recovery._budget_authority_snapshot(
                    uow, run, provider_call_required=provider_required
                )
            self.assertEqual(
                recovery_budget["outcome"],
                BudgetAssessmentOutcome.ELIGIBLE if provider_required
                else BudgetAssessmentOutcome.NOT_REQUIRED,
            )
            self.assertEqual(recovery_budget["scope"]["revision"], scope["revision"])
        context = EffectCommandContext(
            operation_id=fixture["operation_id"],
            project_id=fixture["project_id"],
            actor_id="budget-scope-test",
            trace_id=identifier("budget-scope-trace"),
            correlation_id=identifier("budget-scope-correlation"),
        )
        effect_id = str(
            plan_external_effect(
                DATABASE_URL,
                context,
                effect_type="model.invoke",
                provider="production_execution_gateway",
                capability="model.fixture",
                stable_idempotency_key=identifier("entitlement-scope-effect"),
                request_payload={"fixture": True},
                max_attempts=1,
                reversible=False,
            )["external_effect_id"]
        )
        reserve_provider_budget(
            DATABASE_URL,
            BudgetReservationRequest(
                operation_id=fixture["operation_id"],
                external_effect_id=effect_id,
                project_id=fixture["project_id"],
                stable_idempotency_key=f"budget:{effect_id}",
                provider="production_execution_gateway",
                currency="UNKNOWN",
                estimated_amount=None,
                estimated_tokens=1_000,
                budget_scope_id=str(scope["budget_scope_id"]),
                expected_budget_scope_revision=int(scope["revision"]),
                accounting_basis="ACCOUNT_ENTITLEMENT",
                cost_authorization_ref=authorization_ref,
            ),
        )

        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            assessment = assess_budget_scope_in_uow(
                uow,
                budget_scope_id=str(scope["budget_scope_id"]),
                project_id=fixture["project_id"],
                requested_amount=None,
                requested_tokens=1,
                requested_calls=1,
                expected_revision=int(scope["revision"]),
            )

        self.assertEqual(assessment["outcome"], BudgetAssessmentOutcome.EXHAUSTED)
        self.assertIsNone(assessment["usage"]["committed_amount"])
        self.assertEqual(assessment["usage"]["cost_status"], "UNKNOWN")
        self.assertIsNone(assessment["headroom"]["cost_amount"])
        self.assertIsNone(assessment["request"]["requested_amount"])

    def test_durable_result_replay_validates_evidence_without_new_call_headroom(
        self,
    ) -> None:
        fixture = self._opening_scope()
        scope = self._live_scope(fixture)
        reservation = self._reserve(fixture, scope)
        settle_provider_budget(
            DATABASE_URL,
            reservation_id=str(reservation["reservation_id"]),
            project_id=fixture["project_id"],
            actual_amount="0.40",
            actual_tokens=800,
            evidence={"model_id": "fixture-model", "fixture": True},
        )

        provider_assessment = self._assessment(scope)
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            replay_assessment = assess_budget_scope_in_uow(
                uow,
                budget_scope_id=str(scope["budget_scope_id"]),
                project_id=fixture["project_id"],
                requested_amount="0",
                requested_tokens=0,
                requested_calls=0,
                execution_mode="DURABLE_RESULT_REPLAY",
                expected_revision=int(scope["revision"]),
            )

        self.assertEqual(
            provider_assessment["outcome"], BudgetAssessmentOutcome.EXHAUSTED
        )
        self.assertEqual(
            replay_assessment["outcome"], BudgetAssessmentOutcome.NOT_REQUIRED
        )
        self.assertEqual(
            replay_assessment["request"]["execution_mode"],
            "DURABLE_RESULT_REPLAY",
        )
        self.assertEqual(replay_assessment["usage"]["provider_call_count"], 1)

    def test_proven_no_send_release_restores_provider_call_headroom(self) -> None:
        fixture = self._opening_scope()
        scope = self._live_scope(fixture)
        context = EffectCommandContext(
            operation_id=fixture["operation_id"],
            project_id=fixture["project_id"],
            actor_id="budget-scope-test",
            trace_id=identifier("budget-scope-trace"),
            correlation_id=identifier("budget-scope-correlation"),
        )
        effect_id = str(
            plan_external_effect(
                DATABASE_URL,
                context,
                effect_type="model.invoke",
                provider="fake_deterministic_provider",
                capability="model.fixture",
                stable_idempotency_key=identifier("budget-scope-effect"),
                request_payload={"fixture": True, "max_output_tokens": 500},
                max_attempts=1,
                reversible=False,
            )["external_effect_id"]
        )
        reservation = reserve_provider_budget(
            DATABASE_URL,
            BudgetReservationRequest(
                operation_id=fixture["operation_id"],
                external_effect_id=effect_id,
                project_id=fixture["project_id"],
                stable_idempotency_key=f"budget:{effect_id}",
                provider="fake_deterministic_provider",
                currency="USD",
                estimated_amount="0.50",
                estimated_tokens=1_000,
                budget_scope_id=str(scope["budget_scope_id"]),
                expected_budget_scope_revision=int(scope["revision"]),
            ),
        )

        with self.assertRaises(KernelError):
            dispatch_external_effect(
                DATABASE_URL,
                context,
                effect_id=effect_id,
                worker_id="budget-scope-dispatcher",
                lease_seconds=30,
                adapter=FakeDeterministicProvider("raise_before"),
                budget_reservation_id=str(reservation["reservation_id"]),
            )
        released = resolve_provider_budget_failure(
            DATABASE_URL,
            reservation_id=str(reservation["reservation_id"]),
            project_id=fixture["project_id"],
        )
        assessment = self._assessment(scope)

        self.assertEqual(released["status"], "RELEASED")
        self.assertEqual(assessment["usage"]["provider_call_count"], 0)
        self.assertEqual(assessment["usage"]["committed_tokens"], 0)
        self.assertEqual(assessment["usage"]["committed_amount"], "0")
        self.assertEqual(assessment["outcome"], BudgetAssessmentOutcome.ELIGIBLE)

    def test_in_uow_reservation_rolls_back_with_its_caller(self) -> None:
        fixture = self._opening_scope()
        scope = self._live_scope(fixture)
        context = EffectCommandContext(
            operation_id=fixture["operation_id"],
            project_id=fixture["project_id"],
            actor_id="budget-scope-test",
            trace_id=identifier("budget-scope-trace"),
            correlation_id=identifier("budget-scope-correlation"),
        )
        effect_id = str(
            plan_external_effect(
                DATABASE_URL,
                context,
                effect_type="model.invoke",
                provider="fake_deterministic_provider",
                capability="model.fixture",
                stable_idempotency_key=identifier("budget-scope-effect"),
                request_payload={"fixture": True},
                max_attempts=1,
                reversible=False,
            )["external_effect_id"]
        )
        request = BudgetReservationRequest(
            operation_id=fixture["operation_id"],
            external_effect_id=effect_id,
            project_id=fixture["project_id"],
            stable_idempotency_key=f"budget:{effect_id}",
            provider="fake_deterministic_provider",
            currency="USD",
            estimated_amount="0.50",
            estimated_tokens=1_000,
            budget_scope_id=str(scope["budget_scope_id"]),
            expected_budget_scope_revision=int(scope["revision"]),
        )

        with self.assertRaisesRegex(RuntimeError, "rollback boundary"):
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                reserve_provider_budget_in_uow(uow, request)
                raise RuntimeError("rollback boundary")

        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*) FROM authority_budget_reservation
                WHERE budget_scope_id=%s
                """,
                [scope["budget_scope_id"]],
            )
            self.assertEqual(cursor.fetchone()[0], 0)

    def test_settlement_appends_cost_evidence_without_mutating_policy_revision(
        self,
    ) -> None:
        fixture = self._opening_scope()
        scope = self._live_scope(fixture)
        context = EffectCommandContext(
            operation_id=fixture["operation_id"],
            project_id=fixture["project_id"],
            actor_id="budget-scope-test",
            trace_id=identifier("budget-scope-trace"),
            correlation_id=identifier("budget-scope-correlation"),
        )
        effect_id = str(
            plan_external_effect(
                DATABASE_URL,
                context,
                effect_type="model.invoke",
                provider="fake_deterministic_provider",
                capability="model.fixture",
                stable_idempotency_key=identifier("budget-scope-effect"),
                request_payload={"fixture": True},
                max_attempts=1,
                reversible=False,
            )["external_effect_id"]
        )
        reservation = reserve_provider_budget(
            DATABASE_URL,
            BudgetReservationRequest(
                operation_id=fixture["operation_id"],
                external_effect_id=effect_id,
                project_id=fixture["project_id"],
                stable_idempotency_key=f"budget:{effect_id}",
                provider="fake_deterministic_provider",
                currency="USD",
                estimated_amount="0.50",
                estimated_tokens=1_000,
                budget_scope_id=str(scope["budget_scope_id"]),
                expected_budget_scope_revision=int(scope["revision"]),
            ),
        )

        settled = settle_provider_budget(
            DATABASE_URL,
            reservation_id=reservation["reservation_id"],
            project_id=fixture["project_id"],
            actual_amount="0.40",
            actual_tokens=800,
            evidence={"model_id": "fixture-model", "fixture": True},
        )
        replayed = settle_provider_budget(
            DATABASE_URL,
            reservation_id=reservation["reservation_id"],
            project_id=fixture["project_id"],
            actual_amount="0.40",
            actual_tokens=800,
            evidence={"model_id": "fixture-model", "fixture": True},
        )

        self.assertEqual(settled["status"], "SETTLED")
        self.assertTrue(replayed["replayed"])
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT reservation.version,scope.revision,COUNT(link.*)
                FROM authority_budget_reservation AS reservation
                JOIN authority_provider_budget_scope AS scope
                  ON scope.budget_scope_id=reservation.budget_scope_id
                LEFT JOIN authority_budget_evidence_link AS link
                  ON link.reservation_id=reservation.reservation_id
                 AND link.evidence_kind='OPERATION_COST'
                WHERE reservation.reservation_id=%s
                GROUP BY reservation.version,scope.revision
                """,
                [reservation["reservation_id"]],
            )
            self.assertEqual(cursor.fetchone(), (1, scope["revision"], 1))

    def test_scope_lock_prevents_concurrent_reservation_phantoms(self) -> None:
        fixture = self._opening_scope()
        scope = self._live_scope(fixture)
        context = EffectCommandContext(
            operation_id=fixture["operation_id"],
            project_id=fixture["project_id"],
            actor_id="budget-scope-test",
            trace_id=identifier("budget-scope-trace"),
            correlation_id=identifier("budget-scope-correlation"),
        )
        effect_ids = [
            str(
                plan_external_effect(
                    DATABASE_URL,
                    context,
                    effect_type="model.invoke",
                    provider="fake_deterministic_provider",
                    capability="model.fixture",
                    stable_idempotency_key=identifier("budget-scope-effect"),
                    request_payload={"fixture": True},
                    max_attempts=1,
                    reversible=False,
                )["external_effect_id"]
            )
            for _ in range(2)
        ]

        def reserve(effect_id: str) -> str:
            try:
                return str(
                    reserve_provider_budget(
                        DATABASE_URL,
                        BudgetReservationRequest(
                            operation_id=fixture["operation_id"],
                            external_effect_id=effect_id,
                            project_id=fixture["project_id"],
                            stable_idempotency_key=f"budget:{effect_id}",
                            provider="fake_deterministic_provider",
                            currency="USD",
                            estimated_amount="0.50",
                            estimated_tokens=1_000,
                            budget_scope_id=str(scope["budget_scope_id"]),
                            expected_budget_scope_revision=int(scope["revision"]),
                        ),
                    )["status"]
                )
            except KernelError as exc:
                return exc.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = sorted(pool.map(reserve, effect_ids))

        self.assertEqual(outcomes, ["BUDGET_SCOPE_EXHAUSTED", "RESERVED"])

    def test_exact_opening_budget_binding_authorizes_provider_pre_send(self) -> None:
        fixture = self._opening_scope()
        scope = self._live_scope(fixture)
        token_contract = resolve_provider_token_reservation_contract(
            DATABASE_URL,
            operation_id=fixture["operation_id"],
            project_id=fixture["project_id"],
            currency="USD",
            frozen_request_token_ceiling=8_000,
        )
        self.assertEqual(token_contract["estimated_total_tokens"], 20_000)
        self.assertEqual(token_contract["input_token_ceiling"], 8_000)
        self.assertEqual(token_contract["max_output_tokens"], 8_000)
        self.assertEqual(token_contract["estimated_cost_amount"], "2")
        self.assertLessEqual(
            token_contract["input_token_ceiling"] + token_contract["max_output_tokens"],
            token_contract["estimated_total_tokens"],
        )
        with self.assertRaises(KernelError) as insufficient:
            resolve_provider_token_reservation_contract(
                DATABASE_URL,
                operation_id=fixture["operation_id"],
                project_id=fixture["project_id"],
                currency="USD",
                frozen_request_token_ceiling=20_000,
            )
        self.assertEqual(
            insufficient.exception.code,
            "PROVIDER_TOKEN_RESERVATION_INSUFFICIENT",
        )
        context = EffectCommandContext(
            operation_id=fixture["operation_id"],
            project_id=fixture["project_id"],
            actor_id="budget-scope-test",
            trace_id=identifier("budget-scope-trace"),
            correlation_id=identifier("budget-scope-correlation"),
        )
        effect_id = str(
            plan_external_effect(
                DATABASE_URL,
                context,
                effect_type="model.invoke",
                provider="fake_deterministic_provider",
                capability="model.fixture",
                stable_idempotency_key=identifier("budget-scope-effect"),
                request_payload={"fixture": True, "max_output_tokens": 500},
                max_attempts=1,
                reversible=False,
            )["external_effect_id"]
        )
        reservation = reserve_provider_budget(
            DATABASE_URL,
            BudgetReservationRequest(
                operation_id=fixture["operation_id"],
                external_effect_id=effect_id,
                project_id=fixture["project_id"],
                stable_idempotency_key=f"budget:{effect_id}",
                provider="fake_deterministic_provider",
                currency="USD",
                estimated_amount="0.50",
                estimated_tokens=1_000,
                budget_scope_id=str(scope["budget_scope_id"]),
                expected_budget_scope_revision=int(scope["revision"]),
            ),
        )

        result = dispatch_external_effect(
            DATABASE_URL,
            context,
            effect_id=effect_id,
            worker_id="budget-scope-dispatcher",
            lease_seconds=30,
            adapter=FakeDeterministicProvider("success"),
            budget_reservation_id=str(reservation["reservation_id"]),
        )

        self.assertEqual(result["outcome"], "success")

    def test_opening_reservation_uses_frozen_per_call_cost_not_runtime_cap(
        self,
    ) -> None:
        fixture = self._opening_scope()
        request_values = self._request_values(fixture)
        request_values["policy_snapshot"] = {
            "execution_mode": "PROVIDER_ALLOWED",
            "provider_call_limit": 10,
            "token_limit": 100_000,
            "cost_limit_usd": "10",
            "per_call_token_limit": 10_000,
            "per_call_cost_limit_usd": "2",
        }
        scope = self._live_scope(
            fixture,
            request=BudgetScopeRequest(**request_values),
        )
        context = EffectCommandContext(
            operation_id=fixture["operation_id"],
            project_id=fixture["project_id"],
            actor_id="budget-scope-test",
            trace_id=identifier("budget-scope-trace"),
            correlation_id=identifier("budget-scope-correlation"),
        )

        def reserve(amount: str) -> None:
            effect_id = str(
                plan_external_effect(
                    DATABASE_URL,
                    context,
                    effect_type="model.invoke",
                    provider="fake_deterministic_provider",
                    capability="model.fixture",
                    stable_idempotency_key=identifier("budget-scope-effect"),
                    request_payload={"fixture": True, "max_output_tokens": 500},
                    max_attempts=1,
                    reversible=False,
                )["external_effect_id"]
            )
            reserve_provider_budget(
                DATABASE_URL,
                BudgetReservationRequest(
                    operation_id=fixture["operation_id"],
                    external_effect_id=effect_id,
                    project_id=fixture["project_id"],
                    stable_idempotency_key=f"budget:{effect_id}",
                    provider="fake_deterministic_provider",
                    currency="USD",
                    estimated_amount=amount,
                    estimated_tokens=1_000,
                    budget_scope_id=str(scope["budget_scope_id"]),
                    expected_budget_scope_revision=int(scope["revision"]),
                ),
            )

        for amount in ("2", "2", "2", "1"):
            reserve(amount)

        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            assessment = assess_budget_scope_in_uow(
                uow,
                budget_scope_id=str(scope["budget_scope_id"]),
                project_id=fixture["project_id"],
                requested_amount="2",
                requested_tokens=10_000,
                requested_calls=1,
                expected_revision=int(scope["revision"]),
            )
            uow.commit()
        self.assertEqual(assessment["headroom"]["cost_amount"], "3")
        self.assertEqual(assessment["outcome"], BudgetAssessmentOutcome.ELIGIBLE)

        with self.assertRaises(KernelError) as over_per_call:
            reserve("4")
        self.assertEqual(over_per_call.exception.code, "BUDGET_SCOPE_EXHAUSTED")

    def test_reservation_trigger_guards_identity_version_and_terminal_history(
        self,
    ) -> None:
        fixture = self._opening_scope()
        scope = self._live_scope(fixture)
        reservation = self._reserve(fixture, scope)

        with self.assertRaisesRegex(
            CheckViolation, "BUDGET_RESERVATION_IDENTITY_IMMUTABLE"
        ):
            with transaction() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE authority_budget_reservation
                    SET budget_scope_revision=budget_scope_revision+1,
                        version=version+1
                    WHERE reservation_id=%s
                    """,
                    [reservation["reservation_id"]],
                )

        with self.assertRaisesRegex(
            CheckViolation, "BUDGET_RESERVATION_VERSION_NON_MONOTONIC"
        ):
            with transaction() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE authority_budget_reservation
                    SET evidence=evidence || '{"unversioned":true}'::jsonb
                    WHERE reservation_id=%s
                    """,
                    [reservation["reservation_id"]],
                )

        with self.assertRaisesRegex(
            CheckViolation, "BUDGET_RESERVATION_VERSION_WITHOUT_CHANGE"
        ):
            with transaction() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE authority_budget_reservation
                    SET version=version+1
                    WHERE reservation_id=%s
                    """,
                    [reservation["reservation_id"]],
                )

        settled = settle_provider_budget(
            DATABASE_URL,
            reservation_id=str(reservation["reservation_id"]),
            project_id=fixture["project_id"],
            actual_amount="0.40",
            actual_tokens=800,
            evidence={"model_id": "fixture-model", "fixture": True},
        )
        self.assertEqual(settled["status"], "SETTLED")

        with self.assertRaisesRegex(
            CheckViolation, "BUDGET_RESERVATION_TERMINAL_IMMUTABLE"
        ):
            with transaction() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE authority_budget_reservation
                    SET evidence=evidence || '{"rewrite":true}'::jsonb,
                        version=version+1,updated_at=NOW()
                    WHERE reservation_id=%s
                    """,
                    [reservation["reservation_id"]],
                )

    def test_reservation_trigger_rejects_unknown_to_released_transition(self) -> None:
        fixture = self._opening_scope()
        scope = self._live_scope(fixture)
        reservation = self._reserve(fixture, scope)

        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE authority_budget_reservation
                SET status='HELD_UNKNOWN',evidence=evidence || %s,
                    version=version+1,updated_at=NOW()
                WHERE reservation_id=%s
                """,
                [
                    Jsonb({"manual_resolution_required": True}),
                    reservation["reservation_id"],
                ],
            )

        with self.assertRaisesRegex(
            CheckViolation, "BUDGET_RESERVATION_TRANSITION_INVALID"
        ):
            with transaction() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE authority_budget_reservation
                    SET status='RELEASED',version=version+1,updated_at=NOW()
                    WHERE reservation_id=%s
                    """,
                    [reservation["reservation_id"]],
                )

    def _assessment(self, scope: dict[str, object]) -> dict[str, object]:
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            return assess_budget_scope_in_uow(
                uow,
                budget_scope_id=str(scope["budget_scope_id"]),
                project_id=str(scope["project_id"]),
                requested_amount="0.01",
                requested_tokens=1,
                requested_calls=1,
                expected_revision=int(scope["revision"]),
            )

    def _reserve(
        self, fixture: dict[str, str], scope: dict[str, object]
    ) -> dict[str, object]:
        context = EffectCommandContext(
            operation_id=fixture["operation_id"],
            project_id=fixture["project_id"],
            actor_id="budget-scope-test",
            trace_id=identifier("budget-scope-trace"),
            correlation_id=identifier("budget-scope-correlation"),
        )
        effect_id = str(
            plan_external_effect(
                DATABASE_URL,
                context,
                effect_type="model.invoke",
                provider="fake_deterministic_provider",
                capability="model.fixture",
                stable_idempotency_key=identifier("budget-scope-effect"),
                request_payload={"fixture": True},
                max_attempts=1,
                reversible=False,
            )["external_effect_id"]
        )
        return reserve_provider_budget(
            DATABASE_URL,
            BudgetReservationRequest(
                operation_id=fixture["operation_id"],
                external_effect_id=effect_id,
                project_id=fixture["project_id"],
                stable_idempotency_key=f"budget:{effect_id}",
                provider="fake_deterministic_provider",
                currency="USD",
                estimated_amount="0.50",
                estimated_tokens=1_000,
                budget_scope_id=str(scope["budget_scope_id"]),
                expected_budget_scope_revision=int(scope["revision"]),
            ),
        )

    def _request(self, fixture: dict[str, str]) -> BudgetScopeRequest:
        return BudgetScopeRequest(**self._request_values(fixture))

    def _request_values(self, fixture: dict[str, str]) -> dict[str, object]:
        started_at = datetime(2026, 8, 29, tzinfo=timezone.utc)
        return {
            "project_id": fixture["project_id"],
            "owner_kind": "BOOK_OPENING",
            "owner_id": fixture["opening_run_id"],
            "stable_idempotency_key": f"budget:{fixture['opening_run_id']}",
            "currency": "USD",
            "policy_contract_version": "book-opening-budget.v1",
            "policy_snapshot": {
                "execution_mode": "PROVIDER_ALLOWED",
                "provider_call_limit": 1,
                "token_limit": 20_000,
                "cost_limit_usd": "2",
            },
            "started_at": started_at,
            "deadline_at": started_at + timedelta(days=3650),
            "created_by_operation_id": fixture["root_operation_id"],
        }

    def _live_scope(
        self,
        fixture: dict[str, str],
        *,
        request: BudgetScopeRequest | None = None,
    ) -> dict[str, object]:
        scope = create_or_get_budget_scope(
            DATABASE_URL,
            request or self._request(fixture),
        )
        worker_id = "budget-scope-worker"
        binding = {
            "opening_run_id": fixture["opening_run_id"],
            "opening_execution_id": fixture["opening_execution_id"],
            "opening_execution_generation": 1,
            "runtime_job_id": fixture["runtime_job_id"],
            "runtime_attempt_id": fixture["runtime_attempt_id"],
            "runtime_lease_id": fixture["runtime_lease_id"],
            "runtime_worker_id": worker_id,
            "runtime_fencing_token": 1,
        }
        with transaction() as connection, connection.cursor() as cursor:
            insert_operation(
                cursor,
                operation_id=fixture["operation_id"],
                definition_name=fixture["definition_name"],
                project_id=fixture["project_id"],
                workspace_id=fixture["workspace_id"],
                status="EXECUTING",
                root_operation_id=fixture["root_operation_id"],
                parent_operation_id=fixture["root_operation_id"],
                causation_operation_id=fixture["root_operation_id"],
                command_payload={
                    "book_id": fixture["book_id"],
                    "opening_execution_binding": binding,
                },
            )
            cursor.execute(
                """
                INSERT INTO authority_runtime_job_attempt(
                    attempt_id,runtime_job_id,attempt_number,worker_id,status,
                    lease_id,fencing_token,lease_expires_at,heartbeat_at
                ) VALUES (%s,%s,1,%s,'RUNNING',%s,1,
                          clock_timestamp()+INTERVAL '10 minutes',clock_timestamp())
                """,
                [
                    fixture["runtime_attempt_id"],
                    fixture["runtime_job_id"],
                    worker_id,
                    fixture["runtime_lease_id"],
                ],
            )
            cursor.execute(
                """
                INSERT INTO authority_runtime_job_lease(
                    lease_id,runtime_job_id,attempt_id,worker_id,fencing_token,
                    lease_expires_at,heartbeat_at,status
                ) VALUES (%s,%s,%s,%s,1,
                          clock_timestamp()+INTERVAL '10 minutes',
                          clock_timestamp(),'HELD')
                """,
                [
                    fixture["runtime_lease_id"],
                    fixture["runtime_job_id"],
                    fixture["runtime_attempt_id"],
                    worker_id,
                ],
            )
            cursor.execute(
                """
                UPDATE authority_runtime_job
                SET status='RUNNING',attempt_count=1,claimed_by=%s,
                    current_attempt_id=%s,current_fencing_token=1,
                    updated_at=clock_timestamp()
                WHERE runtime_job_id=%s AND status='READY'
                """,
                [worker_id, fixture["runtime_attempt_id"], fixture["runtime_job_id"]],
            )
            cursor.execute(
                """
                UPDATE authority_book_opening_execution
                SET lifecycle='RUNNING',current_attempt_id=%s,current_lease_id=%s,
                    current_worker_id=%s,current_fencing_token=1,version=version+1,
                    started_at=clock_timestamp(),updated_at=clock_timestamp()
                WHERE opening_execution_id=%s AND lifecycle='SCHEDULED'
                """,
                [
                    fixture["runtime_attempt_id"],
                    fixture["runtime_lease_id"],
                    worker_id,
                    fixture["opening_execution_id"],
                ],
            )
            cursor.execute(
                """
                UPDATE authority_book_opening_run
                SET lifecycle='RUNNING',budget_scope_id=%s,
                    budget_scope_revision=%s,budget_contract_state='BOUND',
                    updated_at=clock_timestamp()
                WHERE opening_run_id=%s AND lifecycle='ADMITTED'
                """,
                [
                    scope["budget_scope_id"],
                    scope["revision"],
                    fixture["opening_run_id"],
                ],
            )
        return scope

    def _opening_scope(self) -> dict[str, str]:
        project_id = identifier("budget-scope-project")
        workspace_id = identifier("budget-scope-workspace")
        book_id = identifier("budget-scope-book")
        root_operation_id = identifier("budget-scope-root-operation")
        operation_id = identifier("budget-scope-provider-operation")
        definition_name = identifier("budget-scope-definition")
        opening_run_id = identifier("budget-scope-opening")
        opening_execution_id = identifier("budget-scope-opening-execution")
        runtime_job_id = identifier("budget-scope-runtime-job")
        runtime_attempt_id = identifier("budget-scope-runtime-attempt")
        runtime_lease_id = identifier("budget-scope-runtime-lease")
        seed_authority_project_book(
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
        )
        opening_idempotency_key = f"opening:{opening_run_id}"
        frozen_request = {
            "fixture": True,
            "opening_run_id": opening_run_id,
            "project_id": project_id,
            "workspace_id": workspace_id,
            "book_id": book_id,
            "idempotency_key": opening_idempotency_key,
        }
        with transaction() as connection, connection.cursor() as cursor:
            insert_definition(cursor, definition_name)
            insert_operation(
                cursor,
                operation_id=root_operation_id,
                definition_name=definition_name,
                project_id=project_id,
                workspace_id=workspace_id,
                status="ADMITTED",
            )
            cursor.execute(
                """
                INSERT INTO authority_book_opening_run(
                    opening_run_id,project_id,workspace_id,book_id,
                    root_operation_id,stable_idempotency_key,lifecycle,
                    frozen_request,frozen_request_digest,
                    execution_contract_version,recovery_state,
                    workflow_contract_version,current_workflow_node_id,
                    workflow_graph_revision,workflow_graph_hash
                ) VALUES (%s,%s,%s,%s,%s,%s,'ADMITTED',%s,%s,
                          'book-opening-execution-v2','READY',
                          'legacy-monolithic-v2',NULL,0,'')
                """,
                [
                    opening_run_id,
                    project_id,
                    workspace_id,
                    book_id,
                    root_operation_id,
                    opening_idempotency_key,
                    Jsonb(frozen_request),
                    _hash(frozen_request),
                ],
            )
            runtime_input = {
                "opening_run_id": opening_run_id,
                "opening_execution_id": opening_execution_id,
                "execution_generation": 1,
                "recovery_intent_id": "",
                "replacement_evaluation_operation_id": "",
                "semantic_evaluation_operation_id": "",
                "semantic_evaluation_execution_id": "",
                "semantic_evaluation_generation": 0,
                "semantic_execution_mode": "NONE",
            }
            cursor.execute(
                """
                INSERT INTO authority_runtime_job(
                    runtime_job_id,job_kind,runtime_group,subject_kind,
                    subject_id,project_id,dedupe_key,input_snapshot,input_hash,
                    max_attempts,lease_loss_policy
                ) VALUES (%s,'BOOK_OPENING_EXECUTE','book_opening',
                          'BOOK_OPENING_RUN',%s,%s,%s,%s,%s,1,
                          'AUTHORITY_CONVERGENCE_REQUIRED')
                """,
                [
                    runtime_job_id,
                    opening_run_id,
                    project_id,
                    f"{opening_run_id}:generation:1",
                    Jsonb(runtime_input),
                    _hash(runtime_input),
                ],
            )
            cursor.execute(
                """
                INSERT INTO authority_book_opening_execution(
                    opening_execution_id,opening_run_id,generation,
                    runtime_job_id,lifecycle,frozen_request_digest,
                    input_snapshot_hash,policy_snapshot_hash,
                    authority_contract_hash
                ) VALUES (%s,%s,1,%s,'SCHEDULED',%s,%s,%s,%s)
                """,
                [
                    opening_execution_id,
                    opening_run_id,
                    runtime_job_id,
                    _hash(frozen_request),
                    _hash(runtime_input),
                    "sha256:" + "6" * 64,
                    "sha256:" + "7" * 64,
                ],
            )
            cursor.execute(
                """
                UPDATE authority_book_opening_run
                SET current_execution_id=%s,current_execution_generation=1
                WHERE opening_run_id=%s
                """,
                [opening_execution_id, opening_run_id],
            )
        return {
            "project_id": project_id,
            "workspace_id": workspace_id,
            "book_id": book_id,
            "operation_id": operation_id,
            "root_operation_id": root_operation_id,
            "opening_run_id": opening_run_id,
            "opening_execution_id": opening_execution_id,
            "runtime_job_id": runtime_job_id,
            "runtime_attempt_id": runtime_attempt_id,
            "runtime_lease_id": runtime_lease_id,
            "definition_name": definition_name,
        }


if __name__ == "__main__":
    unittest.main()
