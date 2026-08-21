from __future__ import annotations

import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import psycopg

from novel_forge.modules.command_kernel.attempt_runtime import (
    WorkerLeaseCommand,
    acquire_attempt_lease,
    checkpoint_attempt_for_external_reconciliation,
    create_attempt,
    queue_attempt,
    start_attempt,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_adapters import (
    FakeDeterministicProvider,
    LocalFileObjectStoreAdapter,
)
from novel_forge.modules.command_kernel.external_effect_runtime import (
    EffectCommandContext,
    accept_external_effect_receipt,
    acquire_effect_dispatch,
    cancel_external_effect,
    compensate_external_effect,
    dispatch_external_effect,
    heartbeat_effect_dispatch,
    plan_external_effect,
    prepare_effect_dispatch,
    reconcile_external_effect,
    submit_effect_dispatch_result,
)
from novel_forge.modules.provider_control import ScriptedProviderAdapterV2
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    insert_definition,
    insert_operation,
    transaction,
)


class _SlowProvider(FakeDeterministicProvider):
    def execute(self, **kwargs):
        time.sleep(1.2)
        return super().execute(**kwargs)


class _CountingProvider(FakeDeterministicProvider):
    def __init__(self, database_url: str, scenario: str = "success") -> None:
        super().__init__(scenario)
        self.database_url = database_url
        self.execute_count = 0
        self.idle_in_transaction_during_execute = -1

    def execute(self, **kwargs):
        self.execute_count += 1
        with psycopg.connect(self.database_url) as connection:
            self.idle_in_transaction_during_execute = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM pg_stat_activity
                    WHERE pid <> pg_backend_pid()
                      AND state='idle in transaction'
                      AND application_name LIKE 'novel-forge-%'
                    """
                ).fetchone()[0]
            )
        return super().execute(**kwargs)


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

    def test_provider_v2_profile_and_request_id_are_frozen_and_persisted(self) -> None:
        context = self._context()
        adapter = ScriptedProviderAdapterV2("success")
        stable_key = identifier("provider-v2-effect")
        effect = plan_external_effect(
            DATABASE_URL,
            context,
            effect_type="model.invoke",
            provider=adapter.provider,
            capability="model.draft",
            stable_idempotency_key=stable_key,
            request_payload={
                "stage": "draft",
                "trace_id": context.trace_id,
                "correlation_id": context.correlation_id,
            },
            max_attempts=2,
            reversible=False,
            request_timeout_seconds=30,
            reconciliation_mode="query",
            provider_capability_profile=adapter.capability_profile.to_dict(),
        )["external_effect_id"]
        result = dispatch_external_effect(
            DATABASE_URL,
            context,
            effect_id=effect,
            worker_id="provider-v2-worker",
            lease_seconds=30,
            adapter=adapter,
        )
        self.assertEqual(result["outcome"], "success")
        self.assertTrue(result["provider_request_id"].startswith("scripted-request:"))
        self.assertEqual(
            adapter.last_request.stable_idempotency_key,
            stable_key,
        )
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT provider_request_id, provider_control_level,
                       provider_idempotency_mode, provider_query_mode,
                       provider_cancel_mode, provider_callback_mode,
                       provider_capability_profile->>'contract_version'
                FROM authority_external_effect
                WHERE external_effect_id = %s
                """,
                [effect],
            )
            self.assertEqual(
                cursor.fetchone(),
                (
                    result["provider_request_id"],
                    "FIXTURE_CONTROLLED",
                    "provider",
                    "query",
                    "cancel",
                    "callback",
                    "provider-capability-v2",
                ),
            )

    def test_provider_v2_capability_drift_fails_before_dispatch(self) -> None:
        context = self._context()
        adapter = ScriptedProviderAdapterV2("success")
        frozen = adapter.capability_profile.to_dict()
        frozen["supports_cancel"] = False
        effect = plan_external_effect(
            DATABASE_URL,
            context,
            effect_type="model.invoke",
            provider=adapter.provider,
            capability="model.draft",
            stable_idempotency_key=identifier("provider-v2-drift"),
            request_payload={"stage": "draft"},
            max_attempts=2,
            reversible=False,
            request_timeout_seconds=30,
            reconciliation_mode="query",
            provider_capability_profile=frozen,
        )["external_effect_id"]
        with self.assertRaisesRegex(KernelError, "runtime capabilities differ"):
            dispatch_external_effect(
                DATABASE_URL,
                context,
                effect_id=effect,
                worker_id="provider-v2-worker",
                lease_seconds=30,
                adapter=adapter,
            )

    def test_slow_provider_dispatch_renews_effect_lease(self) -> None:
        context = self._context()
        effect = self._plan(context, scenario="success")
        result = dispatch_external_effect(
            DATABASE_URL,
            context,
            effect_id=effect,
            worker_id="dispatcher-slow",
            lease_seconds=1,
            adapter=_SlowProvider("success"),
        )
        self.assertEqual(result["outcome"], "success")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT heartbeat_at > acquired_at FROM authority_effect_dispatch_lease WHERE dispatch_id = %s",
                [result["dispatch_id"]],
            )
            self.assertTrue(cursor.fetchone()[0])

    def test_expired_post_request_lease_requires_query_without_duplicate_execute(
        self,
    ) -> None:
        context = self._context()
        stable_key = identifier("db-result-loss")
        provider = _CountingProvider(DATABASE_URL)
        effect = plan_external_effect(
            DATABASE_URL,
            context,
            effect_type="provider.test",
            provider=provider.provider,
            capability="provider.test",
            stable_idempotency_key=stable_key,
            request_payload={"failure_injection": "database_result_commit_lost"},
            max_attempts=2,
            reversible=False,
            reconciliation_mode="query",
        )["external_effect_id"]
        dispatch = prepare_effect_dispatch(DATABASE_URL, context, effect_id=effect)
        acquire_effect_dispatch(
            DATABASE_URL,
            context,
            dispatch_id=dispatch["dispatch_id"],
            worker_id="crashed-after-provider-request",
            lease_seconds=1,
        )
        provider.execute(
            stable_idempotency_key=stable_key,
            capability="provider.test",
            request_payload={"failure_injection": "database_result_commit_lost"},
        )
        time.sleep(1.1)
        with self.assertRaises(KernelError) as retry:
            dispatch_external_effect(
                DATABASE_URL,
                context,
                effect_id=effect,
                worker_id="replacement-dispatcher",
                lease_seconds=30,
                adapter=provider,
            )
        self.assertEqual(retry.exception.code, "EFFECT_RECONCILIATION_REQUIRED")
        self.assertEqual(provider.execute_count, 1)
        reconciled = reconcile_external_effect(
            DATABASE_URL, context, effect_id=effect, adapter=provider
        )
        self.assertEqual(reconciled["outcome"], "success")
        self.assertEqual(provider.execute_count, 1)
        self.assertEqual(provider.idle_in_transaction_during_execute, 0)

    def test_two_dispatchers_compete_and_expired_lease_takeover_fences_old(
        self,
    ) -> None:
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
        self.assertEqual(
            sorted(value for value, _ in outcomes), ["acquired", "rejected"]
        )
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
                worker_id="dispatcher-a"
                if outcomes[0][0] == "acquired"
                else "dispatcher-b",
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
        self._assert_effect(effect, "DISPATCHED", "ACKNOWLEDGED")
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
            self.assertEqual(
                cursor.fetchall(), [("dispatch_result", 1), ("heartbeat", 1)]
            )

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
        self._assert_effect(effect, "DEAD_LETTER", "DEAD_LETTER")

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
        self.assertTrue(reconciled["receipt_id"])
        self._assert_effect(effect, "SUCCEEDED", "SUCCEEDED")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT receipt.status
                FROM authority_external_receipt AS receipt
                JOIN authority_external_effect_dispatch AS dispatch
                  ON dispatch.dispatch_id=receipt.dispatch_id
                WHERE dispatch.external_effect_id=%s
                """,
                [effect],
            )
            self.assertEqual(cursor.fetchone(), ("VERIFIED",))

    def test_reconciliation_not_found_allows_retry_and_ambiguous_stays_blocked(
        self,
    ) -> None:
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

    def test_reconciliation_not_found_terminalizes_checkpointed_attempt_for_retry(
        self,
    ) -> None:
        project_id = identifier("reconciled-retry-project")
        operation_id = identifier("reconciled-retry-operation")
        definition_name = identifier("reconciled-retry-definition")
        with transaction() as connection, connection.cursor() as cursor:
            insert_definition(cursor, definition_name)
            insert_operation(
                cursor,
                operation_id=operation_id,
                definition_name=definition_name,
                project_id=project_id,
                status="READY",
            )
        attempt = create_attempt(
            DATABASE_URL,
            operation_id=operation_id,
            project_id=project_id,
            max_attempts=2,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        queue_attempt(
            DATABASE_URL,
            attempt_id=attempt["attempt_id"],
            project_id=project_id,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        lease = acquire_attempt_lease(
            DATABASE_URL,
            attempt_id=attempt["attempt_id"],
            project_id=project_id,
            worker_id="reconciliation-worker-a",
            lease_seconds=30,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        worker = WorkerLeaseCommand(
            attempt_id=attempt["attempt_id"],
            project_id=project_id,
            worker_id="reconciliation-worker-a",
            fencing_token=lease["fencing_token"],
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
            causation_id=operation_id,
        )
        start_attempt(DATABASE_URL, worker)
        context = EffectCommandContext(
            operation_id=operation_id,
            project_id=project_id,
            actor_id=worker.worker_id,
            trace_id=worker.trace_id,
            correlation_id=worker.correlation_id,
        )
        effect = self._plan(context, scenario="unknown")
        dispatched = dispatch_external_effect(
            DATABASE_URL,
            context,
            effect_id=effect,
            worker_id=worker.worker_id,
            lease_seconds=30,
            adapter=FakeDeterministicProvider("unknown"),
        )
        self.assertEqual(dispatched["outcome"], "unknown")
        checkpoint_attempt_for_external_reconciliation(
            DATABASE_URL,
            worker,
            {"reason": "provider outcome unknown"},
        )
        recovery_lease = acquire_attempt_lease(
            DATABASE_URL,
            attempt_id=attempt["attempt_id"],
            project_id=project_id,
            worker_id="reconciliation-worker-b",
            lease_seconds=30,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        recovery_worker = WorkerLeaseCommand(
            attempt_id=attempt["attempt_id"],
            project_id=project_id,
            worker_id="reconciliation-worker-b",
            fencing_token=recovery_lease["fencing_token"],
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
            causation_id=operation_id,
        )

        reconciled = reconcile_external_effect(
            DATABASE_URL,
            context,
            effect_id=effect,
            adapter=FakeDeterministicProvider("not_found"),
            attempt_command=recovery_worker,
        )
        self.assertEqual(reconciled["outcome"], "not_found")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT status FROM authority_attempt WHERE attempt_id=%s",
                [attempt["attempt_id"]],
            )
            self.assertEqual(cursor.fetchone()[0], "FAILED_RETRYABLE")
        retry = create_attempt(
            DATABASE_URL,
            operation_id=operation_id,
            project_id=project_id,
            max_attempts=2,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        self.assertEqual(retry["attempt_number"], 2)

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

    def test_callback_policy_keeps_ack_distinct_from_business_success(self) -> None:
        context = self._context()
        effect = self._plan(
            context,
            scenario="success",
            completion_policy="callback_receipt",
        )
        dispatched = dispatch_external_effect(
            DATABASE_URL,
            context,
            effect_id=effect,
            worker_id="callback-dispatcher",
            lease_seconds=30,
            adapter=FakeDeterministicProvider("success"),
        )
        self.assertIsNone(dispatched["receipt"])
        self._assert_effect(effect, "DISPATCHED", "ACKNOWLEDGED")
        accept_external_effect_receipt(
            DATABASE_URL,
            context,
            dispatch_id=dispatched["dispatch_id"],
            provider="fake_deterministic_provider",
            receipt_id=identifier("callback-receipt"),
            message_id=identifier("callback-message"),
            payload_hash="sha256:callback-final",
            provider_correlation_id=identifier("callback-correlation"),
            generation=1,
            outcome="success",
            evidence={"business_final": True},
        )
        self._assert_effect(effect, "SUCCEEDED", "SUCCEEDED")

    def test_cancel_before_dispatch_and_after_dispatch_have_distinct_outcomes(
        self,
    ) -> None:
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
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT dispatch.status,
                       COUNT(lease.lease_id) FILTER (WHERE lease.status = 'HELD')
                FROM authority_external_effect_dispatch AS dispatch
                LEFT JOIN authority_effect_dispatch_lease AS lease
                  ON lease.dispatch_id = dispatch.dispatch_id
                WHERE dispatch.dispatch_id = %s
                GROUP BY dispatch.status
                """,
                [dispatch["dispatch_id"]],
            )
            self.assertEqual(cursor.fetchone(), ("CANCEL_REQUESTED", 0))

    def test_adapter_exception_is_recorded_and_releases_lease(self) -> None:
        for scenario, effect_status in (
            ("raise_before", "FAILED_RETRYABLE"),
            ("raise_after", "UNKNOWN"),
        ):
            with self.subTest(scenario=scenario):
                context = self._context()
                effect = self._plan(context, scenario=scenario)
                with self.assertRaises(KernelError) as caught:
                    dispatch_external_effect(
                        DATABASE_URL,
                        context,
                        effect_id=effect,
                        worker_id=identifier("exception-worker"),
                        lease_seconds=30,
                        adapter=FakeDeterministicProvider(scenario),
                    )
                self.assertEqual(
                    caught.exception.code,
                    (
                        "EFFECT_RETRYABLE_FAILURE_RECORDED"
                        if scenario == "raise_before"
                        else "EFFECT_EXTERNAL_STATE_UNKNOWN"
                    ),
                )
                with transaction() as connection, connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT effect.status,
                               COUNT(lease.lease_id) FILTER (WHERE lease.status = 'HELD')
                        FROM authority_external_effect AS effect
                        JOIN authority_external_effect_dispatch AS dispatch
                          ON dispatch.external_effect_id = effect.external_effect_id
                        LEFT JOIN authority_effect_dispatch_lease AS lease
                          ON lease.dispatch_id = dispatch.dispatch_id
                        WHERE effect.external_effect_id = %s
                        GROUP BY effect.status
                        """,
                        [effect],
                    )
                    self.assertEqual(cursor.fetchone(), (effect_status, 0))

    def test_stable_effect_key_is_scoped_by_project(self) -> None:
        first_context = self._context()
        second_context = self._context()
        key = identifier("shared-effect-key")
        effects = [
            plan_external_effect(
                DATABASE_URL,
                context,
                effect_type="provider.test",
                provider="fake_deterministic_provider",
                capability="provider.test",
                stable_idempotency_key=key,
                request_payload={"same": True},
                max_attempts=1,
                reversible=False,
            )["external_effect_id"]
            for context in (first_context, second_context)
        ]
        self.assertNotEqual(effects[0], effects[1])

    def test_local_file_adapter_executes_outside_transaction_and_is_idempotent(
        self,
    ) -> None:
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

    def test_compensation_is_a_linked_idempotent_external_effect(self) -> None:
        context = self._context()
        original = self._plan(context, scenario="success", reversible=True)
        dispatch_external_effect(
            DATABASE_URL,
            context,
            effect_id=original,
            worker_id="original-dispatcher",
            lease_seconds=30,
            adapter=FakeDeterministicProvider("success"),
        )
        first = compensate_external_effect(DATABASE_URL, context, effect_id=original)
        replay = compensate_external_effect(DATABASE_URL, context, effect_id=original)
        self.assertFalse(first["replayed"])
        self.assertTrue(replay["replayed"])
        self.assertEqual(first["external_effect_id"], replay["external_effect_id"])
        dispatch_external_effect(
            DATABASE_URL,
            context,
            effect_id=first["external_effect_id"],
            worker_id="compensation-dispatcher",
            lease_seconds=30,
            adapter=FakeDeterministicProvider("success"),
        )
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT compensation.effect_type, compensation.compensates_effect_id,
                       original.status, compensation.status
                FROM authority_external_effect AS compensation
                JOIN authority_external_effect AS original
                  ON original.external_effect_id = compensation.compensates_effect_id
                WHERE compensation.external_effect_id = %s
                """,
                [first["external_effect_id"]],
            )
            self.assertEqual(
                cursor.fetchone(),
                ("external_effect.compensate", original, "COMPENSATED", "SUCCEEDED"),
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
        completion_policy: str = "synchronous_final",
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
            completion_policy=completion_policy,
        )["external_effect_id"]

    def _assert_effect(
        self, effect_id: str, effect_status: str, dispatch_status: str
    ) -> None:
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
