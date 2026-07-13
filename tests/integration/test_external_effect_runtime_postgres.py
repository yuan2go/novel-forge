from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_adapters import (
    FakeDeterministicProvider,
    LocalFileObjectStoreAdapter,
)
from novel_forge.modules.command_kernel.external_effect_runtime import (
    EffectCommandContext,
    acquire_effect_dispatch,
    accept_external_effect_receipt,
    cancel_external_effect,
    dispatch_external_effect,
    heartbeat_effect_dispatch,
    plan_external_effect,
    prepare_effect_dispatch,
    reconcile_external_effect,
    submit_effect_dispatch_result,
)
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    insert_definition,
    insert_operation,
    transaction,
)


class ExternalEffectRuntimePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_dispatch_success_and_prepared_dispatch_replay(self) -> None:
        context = self._context()
        effect = self._plan(context, scenario="success")
        first = prepare_effect_dispatch(DATABASE_URL, context, effect_id=effect)
        replay = prepare_effect_dispatch(DATABASE_URL, context, effect_id=effect)
        self.assertFalse(first["replayed"])
        self.assertTrue(replay["replayed"])
        self.assertEqual(first["dispatch_id"], replay["dispatch_id"])

        result = dispatch_external_effect(
            DATABASE_URL,
            context,
            effect_id=effect,
            worker_id="dispatcher-a",
            lease_seconds=30,
            adapter=FakeDeterministicProvider("success"),
        )
        self.assertEqual(result["outcome"], "success")
        self._assert_effect(effect, "SUCCEEDED", "SUCCEEDED")

    def test_two_dispatchers_compete_and_expired_lease_takeover_fences_old(self) -> None:
        context = self._context()
        effect = self._plan(context, scenario="success")
        dispatch = prepare_effect_dispatch(DATABASE_URL, context, effect_id=effect)
        barrier = Barrier(2)

        def acquire(worker: str) -> tuple[str, int | str]:
            barrier.wait(timeout=5)
            try:
                lease = acquire_effect_dispatch(
                    DATABASE_URL,
                    context,
                    dispatch_id=dispatch["dispatch_id"],
                    worker_id=worker,
                    lease_seconds=30,
                )
                return "acquired", lease["fencing_token"]
            except KernelError as exc:
                return "rejected", exc.code

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(acquire, ("dispatcher-a", "dispatcher-b")))
        self.assertEqual(sorted(value for value, _ in outcomes), ["acquired", "rejected"])
        winner = next(token for status, token in outcomes if status == "acquired")
        self.assertEqual(winner, 1)

        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE authority_effect_dispatch_lease
                SET acquired_at = NOW() - INTERVAL '2 seconds',
                    heartbeat_at = NOW() - INTERVAL '2 seconds',
                    expires_at = NOW() - INTERVAL '1 second'
                WHERE dispatch_id = %s AND status = 'HELD'
                """,
                [dispatch["dispatch_id"]],
            )
        takeover = acquire_effect_dispatch(
            DATABASE_URL,
            context,
            dispatch_id=dispatch["dispatch_id"],
            worker_id="dispatcher-current",
            lease_seconds=30,
        )
        heartbeat = heartbeat_effect_dispatch(
            DATABASE_URL,
            context,
            dispatch_id=dispatch["dispatch_id"],
            worker_id="dispatcher-current",
            fencing_token=takeover["fencing_token"],
            lease_seconds=60,
        )
        self.assertGreater(heartbeat["expires_at"], takeover["expires_at"])
        with self.assertRaises(KernelError) as stale_heartbeat:
            heartbeat_effect_dispatch(
                DATABASE_URL,
                context,
                dispatch_id=dispatch["dispatch_id"],
                worker_id="dispatcher-stale",
                fencing_token=1,
                lease_seconds=60,
            )
        self.assertEqual(stale_heartbeat.exception.code, "EFFECT_FENCING_TOKEN_STALE")
        with self.assertRaises(KernelError) as stale:
            submit_effect_dispatch_result(
                DATABASE_URL,
                context,
                dispatch_id=dispatch["dispatch_id"],
                worker_id="dispatcher-a" if outcomes[0][0] == "acquired" else "dispatcher-b",
                fencing_token=1,
                outcome="success",
                evidence={"stale": True},
            )
        self.assertEqual(stale.exception.code, "EFFECT_FENCING_TOKEN_STALE")
        submit_effect_dispatch_result(
            DATABASE_URL,
            context,
            dispatch_id=dispatch["dispatch_id"],
            worker_id="dispatcher-current",
            fencing_token=takeover["fencing_token"],
            outcome="success",
            evidence={"current": True},
        )
        self._assert_effect(effect, "SUCCEEDED", "SUCCEEDED")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT command_type, COUNT(*)
                FROM authority_effect_command_rejection
                WHERE dispatch_id = %s
                GROUP BY command_type
                ORDER BY command_type
                """,
                [dispatch["dispatch_id"]],
            )
            self.assertEqual(cursor.fetchall(), [("dispatch_result", 1), ("heartbeat", 1)])

    def test_timeout_before_effect_retries_and_exhaustion_dead_letters(self) -> None:
        context = self._context()
        effect = self._plan(context, scenario="timeout_before", max_attempts=2)
        first = dispatch_external_effect(
            DATABASE_URL,
            context,
            effect_id=effect,
            worker_id="dispatcher-timeout-1",
            lease_seconds=30,
            adapter=FakeDeterministicProvider("timeout_before"),
        )
        self.assertEqual(first["outcome"], "retryable_failure")
        second = dispatch_external_effect(
            DATABASE_URL,
            context,
            effect_id=effect,
            worker_id="dispatcher-timeout-2",
            lease_seconds=30,
            adapter=FakeDeterministicProvider("timeout_before"),
        )
        self.assertEqual(second["outcome"], "final_failure")
        self._assert_effect(effect, "FAILED_FINAL", "DEAD_LETTER")

    def test_timeout_after_effect_requires_provider_reconciliation(self) -> None:
        context = self._context()
        provider = FakeDeterministicProvider("timeout_after")
        effect = self._plan(context, scenario="timeout_after")
        result = dispatch_external_effect(
            DATABASE_URL,
            context,
            effect_id=effect,
            worker_id="dispatcher-unknown",
            lease_seconds=30,
            adapter=provider,
        )
        self.assertEqual(result["outcome"], "unknown")
        with self.assertRaises(KernelError) as blind_retry:
            prepare_effect_dispatch(DATABASE_URL, context, effect_id=effect)
        self.assertEqual(blind_retry.exception.code, "EFFECT_RECONCILIATION_REQUIRED")
        reconciled = reconcile_external_effect(
            DATABASE_URL,
            context,
            effect_id=effect,
            adapter=provider,
        )
        self.assertEqual(reconciled["outcome"], "success")
        self._assert_effect(effect, "SUCCEEDED", "UNKNOWN")

    def test_reconciliation_not_found_allows_retry_and_ambiguous_stays_blocked(self) -> None:
        for query_outcome, effect_status in (
            ("not_found", "FAILED_RETRYABLE"),
            ("ambiguous", "RECONCILIATION_REQUIRED"),
        ):
            with self.subTest(query_outcome=query_outcome):
                context = self._context()
                effect = self._plan(context, scenario="unknown")
                dispatch_external_effect(
                    DATABASE_URL,
                    context,
                    effect_id=effect,
                    worker_id=identifier("dispatcher"),
                    lease_seconds=30,
                    adapter=FakeDeterministicProvider("unknown"),
                )
                outcome = reconcile_external_effect(
                    DATABASE_URL,
                    context,
                    effect_id=effect,
                    adapter=FakeDeterministicProvider(query_outcome),
                )
                self.assertEqual(outcome["outcome"], query_outcome)
                with transaction() as connection, connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT status FROM authority_external_effect WHERE external_effect_id = %s",
                        [effect],
                    )
                    self.assertEqual(cursor.fetchone()[0], effect_status)

    def test_receipt_inbox_replay_conflict_and_generation_binding(self) -> None:
        context = self._context()
        effect = self._plan(context, scenario="callback")
        dispatch = prepare_effect_dispatch(DATABASE_URL, context, effect_id=effect)
        receipt = {
            "dispatch_id": dispatch["dispatch_id"],
            "provider": "fake_deterministic_provider",
            "receipt_id": identifier("receipt"),
            "message_id": identifier("message"),
            "payload_hash": "sha256:callback",
            "provider_correlation_id": identifier("provider-correlation"),
            "generation": 1,
            "outcome": "success",
            "evidence": {"signature": "test-signature"},
        }
        first = accept_external_effect_receipt(DATABASE_URL, context, **receipt)
        replay = accept_external_effect_receipt(DATABASE_URL, context, **receipt)
        self.assertFalse(first["replayed"])
        self.assertTrue(replay["replayed"])
        receipt["payload_hash"] = "sha256:conflict"
        with self.assertRaises(KernelError) as conflict:
            accept_external_effect_receipt(DATABASE_URL, context, **receipt)
        self.assertEqual(conflict.exception.code, "RECEIPT_PAYLOAD_CONFLICT")

    def test_cancel_before_dispatch_and_after_dispatch_have_distinct_outcomes(self) -> None:
        context = self._context()
        before = self._plan(context, scenario="success")
        self.assertEqual(
            cancel_external_effect(DATABASE_URL, context, effect_id=before)["status"],
            "CANCELLED",
        )
        after = self._plan(context, scenario="success", reversible=True)
        dispatch = prepare_effect_dispatch(DATABASE_URL, context, effect_id=after)
        acquire_effect_dispatch(
            DATABASE_URL,
            context,
            dispatch_id=dispatch["dispatch_id"],
            worker_id="dispatcher-cancel",
            lease_seconds=30,
        )
        self.assertEqual(
            cancel_external_effect(DATABASE_URL, context, effect_id=after)["status"],
            "COMPENSATION_REQUIRED",
        )

    def test_local_file_adapter_executes_outside_transaction_and_is_idempotent(self) -> None:
        context = self._context()
        with tempfile.TemporaryDirectory() as directory:
            adapter = LocalFileObjectStoreAdapter(Path(directory))
            payload = {
                "object_key": "project/output.txt",
                "content": "durable external bytes",
            }
            effect = plan_external_effect(
                DATABASE_URL,
                context,
                effect_type="object_store.put",
                provider="local_file_object_store",
                capability="object_store.put",
                stable_idempotency_key=identifier("file-effect"),
                request_payload=payload,
                max_attempts=2,
                reversible=True,
            )["external_effect_id"]
            result = dispatch_external_effect(
                DATABASE_URL,
                context,
                effect_id=effect,
                worker_id="file-dispatcher",
                lease_seconds=30,
                adapter=adapter,
            )
            self.assertEqual(result["outcome"], "success")
            self.assertEqual(
                (Path(directory) / "project" / "output.txt").read_text(),
                "durable external bytes",
            )

    def _context(self) -> EffectCommandContext:
        project_id = identifier("project")
        operation_id = identifier("operation")
        definition_name = identifier("effect-definition")
        with transaction() as connection, connection.cursor() as cursor:
            insert_definition(cursor, definition_name)
            insert_operation(
                cursor,
                operation_id=operation_id,
                definition_name=definition_name,
                project_id=project_id,
                status="EXECUTING",
            )
        return EffectCommandContext(
            operation_id=operation_id,
            project_id=project_id,
            actor_id="effect-runtime",
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )

    def _plan(
        self,
        context: EffectCommandContext,
        *,
        scenario: str,
        max_attempts: int = 3,
        reversible: bool = False,
    ) -> str:
        return plan_external_effect(
            DATABASE_URL,
            context,
            effect_type="provider.test",
            provider="fake_deterministic_provider",
            capability="provider.test",
            stable_idempotency_key=identifier("effect-key"),
            request_payload={"scenario": scenario},
            max_attempts=max_attempts,
            reversible=reversible,
        )["external_effect_id"]

    def _assert_effect(self, effect_id: str, effect_status: str, dispatch_status: str) -> None:
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT effect.status, dispatch.status
                FROM authority_external_effect AS effect
                JOIN authority_external_effect_dispatch AS dispatch
                  ON dispatch.external_effect_id = effect.external_effect_id
                WHERE effect.external_effect_id = %s
                ORDER BY dispatch.generation DESC
                LIMIT 1
                """,
                [effect_id],
            )
            self.assertEqual(cursor.fetchone(), (effect_status, dispatch_status))


if __name__ == "__main__":
    unittest.main()
