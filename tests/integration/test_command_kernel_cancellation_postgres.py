from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from novel_forge.modules.command_kernel.cancellation import (
    CancelCommand,
    acknowledge_worker_cancellation,
    complete_compensation_from_child,
    create_compensation_child,
    request_cancellation,
    resolve_cancellation,
)
from novel_forge.modules.command_kernel.attempt_runtime import (
    WorkerLeaseCommand,
    WorkerResultCommand,
    acquire_attempt_lease,
    create_attempt,
    queue_attempt,
    start_attempt,
    submit_attempt_result,
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
from novel_forge.modules.command_kernel.runtime import (
    OperationTransitionCommand,
    transition_operation,
)
from novel_forge.modules.command_kernel.service import AdmissionContext
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    insert_definition,
    insert_operation,
    transaction,
)
from tests.integration.test_authority_attempt_lease_schema_postgres import (
    insert_attempt,
)
from tests.integration.test_command_kernel_definition_postgres import definition_payload


class CommandKernelCancellationPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_two_concurrent_cancel_commands_are_idempotent_and_signal_worker(
        self,
    ) -> None:
        project_id, operation_id = self._operation("EXECUTING")
        attempt_id = identifier("attempt")
        with transaction() as connection, connection.cursor() as cursor:
            insert_attempt(
                cursor,
                attempt_id=attempt_id,
                operation_id=operation_id,
                attempt_number=1,
                status="RUNNING",
            )
        command = self._cancel(operation_id, project_id, expected_version=0)
        barrier = Barrier(2)

        def cancel() -> dict:
            barrier.wait(timeout=5)
            return request_cancellation(DATABASE_URL, command)

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: cancel(), range(2)))

        self.assertEqual(
            sorted(result["replayed"] for result in results), [False, True]
        )
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT operation.status, operation.version,
                       (SELECT COUNT(*) FROM authority_cancellation_command WHERE operation_id = %s),
                       (SELECT COUNT(*) FROM authority_worker_cancel_signal WHERE operation_id = %s)
                FROM authority_operation AS operation
                WHERE operation.operation_id = %s AND operation.project_id = %s
                """,
                [operation_id, operation_id, operation_id, project_id],
            )
            self.assertEqual(cursor.fetchone(), ("CANCELLATION_REQUESTED", 1, 1, 1))

    def test_cancel_resolution_distinguishes_cancelled_and_reconciliation(self) -> None:
        for resolution, target in (
            ("no_external_effect", "CANCELLED"),
            ("external_state_unknown", "RECONCILIATION_REQUIRED"),
        ):
            with self.subTest(resolution=resolution):
                project_id, operation_id = self._operation("EXECUTING")
                request_cancellation(
                    DATABASE_URL,
                    self._cancel(operation_id, project_id, expected_version=0),
                )
                result = resolve_cancellation(
                    DATABASE_URL,
                    operation_id=operation_id,
                    project_id=project_id,
                    expected_version=1,
                    resolution=resolution,
                    actor_id="kernel.reconciler",
                    reason="external state classified",
                    trace_id=identifier("trace"),
                    correlation_id=identifier("correlation"),
                )
                self.assertEqual(result["status"], target)

    def test_control_cancel_settles_unreserved_ready_effect_and_replays(self) -> None:
        project_id, operation_id = self._operation("EXECUTING")
        context = EffectCommandContext(operation_id, project_id, "operator", "trace:unreserved", "correlation:unreserved")
        effect = plan_external_effect(
            DATABASE_URL, context, effect_type="model.invoke", provider="isolated-fixture",
            capability="model.planning", stable_idempotency_key=f"unreserved:{operation_id}",
            request_payload={"candidate": "immutable request"}, max_attempts=1, reversible=False,
        )
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT request_hash FROM authority_external_effect WHERE external_effect_id=%s", [effect["external_effect_id"]])
            original_request_hash = cursor.fetchone()[0]
        self._transition(operation_id, project_id, 0, "EXECUTING", "FAILED_RETRYABLE")
        command = self._cancel(operation_id, project_id, expected_version=1)
        result = request_cancellation(DATABASE_URL, command, settle_undispatched=True)
        self.assertEqual(result["status"], "CANCELLED")
        replay = request_cancellation(DATABASE_URL, command, settle_undispatched=True)
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["status"], "CANCELLED")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT status,request_payload,request_hash FROM authority_external_effect WHERE external_effect_id=%s", [effect["external_effect_id"]])
            status, payload, request_hash = cursor.fetchone()
            self.assertEqual(status, "CANCELLED")
            self.assertEqual(payload, {"candidate": "immutable request"})
            self.assertEqual(request_hash, original_request_hash)
            cursor.execute("SELECT count(*) FROM authority_external_effect_dispatch WHERE external_effect_id=%s", [effect["external_effect_id"]])
            self.assertEqual(cursor.fetchone()[0], 0)
            cursor.execute("SELECT count(*) FROM authority_budget_reservation WHERE operation_id=%s", [operation_id])
            self.assertEqual(cursor.fetchone()[0], 0)
            cursor.execute("SELECT payload FROM state_event WHERE aggregate_id=%s AND event_type='external_effect.cancelled'", [effect["external_effect_id"]])
            events = cursor.fetchall()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0][0]["budget_disposition"], "NONE")

    def test_control_cancel_without_effects_settles_but_active_attempt_waits(self) -> None:
        for active in (False, True):
            with self.subTest(active=active):
                project_id, operation_id = self._operation("FAILED_RETRYABLE" if not active else "EXECUTING")
                if active:
                    with transaction() as connection, connection.cursor() as cursor:
                        insert_attempt(cursor, attempt_id=identifier("active"), operation_id=operation_id, attempt_number=1, status="RUNNING")
                result = request_cancellation(DATABASE_URL, self._cancel(operation_id, project_id, 0), settle_undispatched=True)
                self.assertEqual(result["status"], "CANCELLATION_REQUESTED" if active else "CANCELLED")

    def test_no_effect_resolution_rejects_verified_external_effect(self) -> None:
        project_id, operation_id = self._operation("EXECUTING")
        trace_id = identifier("trace")
        correlation_id = identifier("correlation")
        context = EffectCommandContext(
            operation_id=operation_id,
            project_id=project_id,
            actor_id="kernel.reconciler",
            trace_id=trace_id,
            correlation_id=correlation_id,
        )
        adapter = FakeDeterministicProvider("success")
        effect = plan_external_effect(
            DATABASE_URL,
            context,
            effect_type="model.invoke",
            provider=adapter.provider,
            capability="model.narrative_semantic_evaluation",
            stable_idempotency_key=f"semantic-success:{operation_id}",
            request_payload={"candidate": "immutable"},
            max_attempts=1,
            reversible=False,
            reconciliation_mode=adapter.reconciliation_mode,
            provider_capability_profile=dict(adapter.capability_profile),
        )
        dispatch_external_effect(
            DATABASE_URL,
            context,
            effect_id=str(effect["external_effect_id"]),
            worker_id="synthetic-provider-worker",
            lease_seconds=30,
            adapter=adapter,
        )
        request_cancellation(
            DATABASE_URL,
            self._cancel(operation_id, project_id, expected_version=0),
        )

        with self.assertRaisesRegex(
            KernelError, "CANCELLATION_NO_EFFECT_EVIDENCE_CONFLICT"
        ):
            resolve_cancellation(
                DATABASE_URL,
                operation_id=operation_id,
                project_id=project_id,
                expected_version=1,
                resolution="no_external_effect",
                actor_id="kernel.reconciler",
                reason="false no-effect classification must fail closed",
                trace_id=trace_id,
                correlation_id=correlation_id,
            )

        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT operation.status,effect.status
                FROM authority_operation AS operation
                JOIN authority_external_effect AS effect
                  ON effect.operation_id=operation.operation_id
                WHERE operation.operation_id=%s AND operation.project_id=%s
                """,
                [operation_id, project_id],
            )
            self.assertEqual(cursor.fetchone(), ("CANCELLATION_REQUESTED", "SUCCEEDED"))

        reconciled = resolve_cancellation(
            DATABASE_URL,
            operation_id=operation_id,
            project_id=project_id,
            expected_version=1,
            resolution="external_state_unknown",
            actor_id="kernel.reconciler",
            reason="durable success requires governed reconciliation",
            trace_id=trace_id,
            correlation_id=correlation_id,
        )
        self.assertEqual(reconciled["status"], "RECONCILIATION_REQUIRED")

    def test_root_cancel_prevents_unstarted_children_and_signals_active_child(
        self,
    ) -> None:
        project_id, root_id = self._operation("WAITING_CHILDREN")
        ready_child = identifier("ready-child")
        running_child = identifier("running-child")
        running_attempt = identifier("running-child-attempt")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT definition_name FROM authority_operation WHERE operation_id = %s",
                [root_id],
            )
            definition_name = cursor.fetchone()[0]
            insert_operation(
                cursor,
                operation_id=ready_child,
                definition_name=definition_name,
                project_id=project_id,
                status="READY",
                root_operation_id=root_id,
                parent_operation_id=root_id,
            )
            insert_operation(
                cursor,
                operation_id=running_child,
                definition_name=definition_name,
                project_id=project_id,
                status="EXECUTING",
                root_operation_id=root_id,
                parent_operation_id=root_id,
            )
            insert_attempt(
                cursor,
                attempt_id=running_attempt,
                operation_id=running_child,
                attempt_number=1,
                status="RUNNING",
            )
        request_cancellation(
            DATABASE_URL, self._cancel(root_id, project_id, expected_version=0)
        )
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT operation_id, status FROM authority_operation WHERE operation_id = ANY(%s) ORDER BY operation_id",
                [[ready_child, running_child]],
            )
            statuses = dict(cursor.fetchall())
            self.assertEqual(statuses[ready_child], "CANCELLED")
            self.assertEqual(statuses[running_child], "CANCELLATION_REQUESTED")
            cursor.execute(
                "SELECT COUNT(*) FROM authority_worker_cancel_signal WHERE operation_id = %s AND attempt_id = %s",
                [running_child, running_attempt],
            )
            self.assertEqual(cursor.fetchone()[0], 1)

    def test_compensation_child_success_and_failure_have_distinct_parent_terminals(
        self,
    ) -> None:
        for child_target, parent_target in (
            ("SUCCEEDED", "COMPENSATED"),
            ("FAILED_FINAL", "COMPENSATION_FAILED"),
        ):
            with self.subTest(child_target=child_target):
                project_id, parent_id = self._operation("EXECUTING")
                definition = self._compensation_definition()
                request_cancellation(
                    DATABASE_URL,
                    self._cancel(parent_id, project_id, expected_version=0),
                )
                resolve_cancellation(
                    DATABASE_URL,
                    operation_id=parent_id,
                    project_id=project_id,
                    expected_version=1,
                    resolution="compensation_required",
                    actor_id="kernel.reconciler",
                    reason="successful external effect requires compensation",
                    trace_id=identifier("trace"),
                    correlation_id=identifier("correlation"),
                )
                admitted = create_compensation_child(
                    DATABASE_URL,
                    parent_operation_id=parent_id,
                    project_id=project_id,
                    expected_parent_version=2,
                    definition_name=definition["name"],
                    definition_version="1.0.0",
                    compensation_generation=1,
                    actor_id="kernel.compensator",
                    reason="reverse external effect",
                    trace_id=identifier("trace"),
                    correlation_id=identifier("correlation"),
                    context=self._compensation_context(definition),
                )
                child_id = admitted["operation_id"]
                self.assertFalse(admitted["replayed"])
                if child_target == "SUCCEEDED":
                    self._transition(child_id, project_id, 0, "ADMITTED", "READY")
                    self._transition(child_id, project_id, 1, "READY", "EXECUTING")
                    self._transition(child_id, project_id, 2, "EXECUTING", "SUCCEEDED")
                else:
                    self._transition(
                        child_id, project_id, 0, "ADMITTED", "FAILED_FINAL"
                    )

                result = complete_compensation_from_child(
                    DATABASE_URL,
                    child_operation_id=child_id,
                    project_id=project_id,
                    actor_id="kernel.compensator",
                    trace_id=identifier("trace"),
                    correlation_id=identifier("correlation"),
                )

                self.assertEqual(result["status"], parent_target)
                self.assertFalse(result["replayed"])

                replay = complete_compensation_from_child(
                    DATABASE_URL,
                    child_operation_id=child_id,
                    project_id=project_id,
                    actor_id="kernel.compensator",
                    trace_id=identifier("trace"),
                    correlation_id=identifier("correlation"),
                )
                self.assertEqual(replay["status"], parent_target)
                self.assertTrue(replay["replayed"])

    def test_compensation_child_uses_standard_admission_and_replays(self) -> None:
        project_id, parent_id = self._operation("COMPENSATION_REQUIRED")
        definition = self._compensation_definition()
        context = self._compensation_context(definition)
        command = self._create_compensation(
            parent_id,
            project_id,
            definition,
            context,
            reason="reverse provider charge",
        )

        first = create_compensation_child(DATABASE_URL, **command)
        second = create_compensation_child(DATABASE_URL, **command)

        self.assertFalse(first["replayed"])
        self.assertTrue(second["replayed"])
        self.assertEqual(first["operation_id"], second["operation_id"])
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT child.parent_operation_id, child.root_operation_id,
                       child.causation_operation_id, child.status,
                       parent.status, parent.version,
                       (SELECT COUNT(*) FROM authority_idempotency_record
                        WHERE operation_id = child.operation_id),
                       (SELECT COUNT(*) FROM state_event
                        WHERE aggregate_type = 'authority_operation'
                          AND aggregate_id = child.operation_id
                          AND event_type = 'authority.operation.admitted'),
                       (SELECT COUNT(*) FROM audit_log
                        WHERE operation_id = child.operation_id
                          AND action = 'authority.operation.admitted'),
                       (SELECT COUNT(*) FROM outbox_event AS outbox
                        JOIN state_event AS event ON event.event_id = outbox.event_id
                        WHERE event.aggregate_id = child.operation_id
                          AND outbox.topic = 'authority.operation.admitted')
                FROM authority_operation AS child
                JOIN authority_operation AS parent
                  ON parent.operation_id = child.parent_operation_id
                WHERE child.operation_id = %s AND child.project_id = %s
                """,
                [first["operation_id"], project_id],
            )
            self.assertEqual(
                cursor.fetchone(),
                (
                    parent_id,
                    parent_id,
                    parent_id,
                    "ADMITTED",
                    "COMPENSATING",
                    1,
                    1,
                    1,
                    1,
                    1,
                ),
            )

    def test_concurrent_compensation_creation_has_one_child(self) -> None:
        project_id, parent_id = self._operation("COMPENSATION_REQUIRED")
        definition = self._compensation_definition()
        context = self._compensation_context(definition)
        command = self._create_compensation(
            parent_id,
            project_id,
            definition,
            context,
            reason="concurrent reverse",
        )
        barrier = Barrier(2)

        def create() -> dict:
            barrier.wait(timeout=5)
            return create_compensation_child(DATABASE_URL, **command)

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: create(), range(2)))

        self.assertEqual(
            sorted(result["replayed"] for result in results), [False, True]
        )
        self.assertEqual(len({result["operation_id"] for result in results}), 1)
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM authority_operation WHERE parent_operation_id = %s",
                [parent_id],
            )
            self.assertEqual(cursor.fetchone()[0], 1)

    def test_compensation_definition_and_parent_cas_fail_closed(self) -> None:
        project_id, parent_id = self._operation("COMPENSATION_REQUIRED")
        missing = self._compensation_definition(register=False)
        with self.assertRaises(KernelError) as missing_error:
            create_compensation_child(
                DATABASE_URL,
                **self._create_compensation(
                    parent_id,
                    project_id,
                    missing,
                    self._compensation_context(missing),
                    reason="missing definition",
                ),
            )
        self.assertEqual(missing_error.exception.code, "OPERATION_DEFINITION_NOT_FOUND")

        disabled = self._compensation_definition(enabled=False)
        with self.assertRaises(KernelError) as disabled_error:
            create_compensation_child(
                DATABASE_URL,
                **self._create_compensation(
                    parent_id,
                    project_id,
                    disabled,
                    self._compensation_context(disabled),
                    reason="disabled definition",
                ),
            )
        self.assertEqual(disabled_error.exception.code, "OPERATION_DEFINITION_DISABLED")

        enabled = self._compensation_definition()
        for expected_version, expected_code in (
            (9, "OPERATION_VERSION_CONFLICT"),
            (0, "OPERATION_STATUS_CONFLICT"),
        ):
            if expected_code == "OPERATION_STATUS_CONFLICT":
                wrong_project, wrong_parent = self._operation("READY")
            else:
                wrong_project, wrong_parent = project_id, parent_id
            with self.subTest(expected_code=expected_code):
                command = self._create_compensation(
                    wrong_parent,
                    wrong_project,
                    enabled,
                    self._compensation_context(enabled),
                    reason=expected_code,
                )
                command["expected_parent_version"] = expected_version
                with self.assertRaises(KernelError) as caught:
                    create_compensation_child(DATABASE_URL, **command)
                self.assertEqual(caught.exception.code, expected_code)
                with transaction() as connection, connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT COUNT(*),
                               (SELECT COUNT(*)
                                FROM authority_idempotency_record AS record
                                JOIN authority_operation AS operation
                                  ON operation.operation_id = record.operation_id
                                WHERE operation.parent_operation_id = %s)
                        FROM authority_operation
                        WHERE parent_operation_id = %s
                        """,
                        [wrong_parent, wrong_parent],
                    )
                    self.assertEqual(cursor.fetchone(), (0, 0))

    def test_compensation_idempotency_key_rejects_different_content(self) -> None:
        project_id, parent_id = self._operation("COMPENSATION_REQUIRED")
        definition = self._compensation_definition()
        context = self._compensation_context(definition)
        command = self._create_compensation(
            parent_id,
            project_id,
            definition,
            context,
            reason="original reason",
        )
        create_compensation_child(DATABASE_URL, **command)
        command["reason"] = "different reason"

        with self.assertRaises(KernelError) as caught:
            create_compensation_child(DATABASE_URL, **command)

        self.assertEqual(caught.exception.code, "IDEMPOTENCY_CONFLICT")

    def test_worker_result_and_cancel_use_the_same_operation_cas(self) -> None:
        project_id, operation_id = self._operation("READY")
        created = create_attempt(
            DATABASE_URL,
            operation_id=operation_id,
            project_id=project_id,
            max_attempts=1,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        queue_attempt(
            DATABASE_URL,
            attempt_id=created["attempt_id"],
            project_id=project_id,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        lease = acquire_attempt_lease(
            DATABASE_URL,
            attempt_id=created["attempt_id"],
            project_id=project_id,
            worker_id="worker-result-cancel",
            lease_seconds=30,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        worker = WorkerLeaseCommand(
            attempt_id=created["attempt_id"],
            project_id=project_id,
            worker_id="worker-result-cancel",
            fencing_token=lease["fencing_token"],
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        start_attempt(DATABASE_URL, worker)
        result_command = WorkerResultCommand(
            **worker.__dict__,
            expected_operation_version=1,
            expected_operation_status="EXECUTING",
        )
        cancel_command = self._cancel(operation_id, project_id, expected_version=1)
        barrier = Barrier(2)

        def result_action() -> tuple[str, str]:
            barrier.wait(timeout=5)
            try:
                submit_attempt_result(
                    DATABASE_URL,
                    result_command,
                    outcome="success",
                    result={"value": "race"},
                )
                return "result", "ok"
            except KernelError as exc:
                return "result", exc.code

        def cancel_action() -> tuple[str, str]:
            barrier.wait(timeout=5)
            try:
                request_cancellation(DATABASE_URL, cancel_command)
                return "cancel", "ok"
            except KernelError as exc:
                return "cancel", exc.code

        with ThreadPoolExecutor(max_workers=2) as executor:
            result_future = executor.submit(result_action)
            cancel_future = executor.submit(cancel_action)
            outcomes = (result_future.result(), cancel_future.result())

        self.assertEqual(sum(outcome[1] == "ok" for outcome in outcomes), 1)
        self.assertIn(
            next(outcome[1] for outcome in outcomes if outcome[1] != "ok"),
            {"OPERATION_VERSION_CONFLICT", "OPERATION_STATUS_CONFLICT"},
        )
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT status, version FROM authority_operation WHERE operation_id = %s",
                [operation_id],
            )
            self.assertIn(
                cursor.fetchone(),
                {("SUCCEEDED", 2), ("CANCELLATION_REQUESTED", 2)},
            )

    def test_worker_cancel_acknowledgement_requires_current_fencing_token(self) -> None:
        project_id, operation_id = self._operation("READY")
        created = create_attempt(
            DATABASE_URL,
            operation_id=operation_id,
            project_id=project_id,
            max_attempts=1,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        queue_attempt(
            DATABASE_URL,
            attempt_id=created["attempt_id"],
            project_id=project_id,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        lease = acquire_attempt_lease(
            DATABASE_URL,
            attempt_id=created["attempt_id"],
            project_id=project_id,
            worker_id="worker-cancel-ack",
            lease_seconds=30,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        worker = WorkerLeaseCommand(
            attempt_id=created["attempt_id"],
            project_id=project_id,
            worker_id="worker-cancel-ack",
            fencing_token=lease["fencing_token"],
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        start_attempt(DATABASE_URL, worker)
        request_cancellation(
            DATABASE_URL,
            self._cancel(operation_id, project_id, expected_version=1),
        )

        result = acknowledge_worker_cancellation(
            DATABASE_URL,
            worker,
            expected_operation_version=2,
        )

        self.assertEqual(result["status"], "CANCELLED")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT attempt.status, signal.status, lease.status
                FROM authority_attempt AS attempt
                JOIN authority_worker_cancel_signal AS signal
                  ON signal.attempt_id = attempt.attempt_id
                JOIN authority_lease_acquisition AS lease
                  ON lease.attempt_id = attempt.attempt_id
                WHERE attempt.attempt_id = %s
                """,
                [created["attempt_id"]],
            )
            self.assertEqual(
                cursor.fetchone(),
                ("CANCELLED", "ACKNOWLEDGED", "RELEASED"),
            )

    def test_stale_cancel_acknowledgement_preserves_takeover_worker(self) -> None:
        project_id, operation_id = self._operation("READY")
        created = create_attempt(
            DATABASE_URL,
            operation_id=operation_id,
            project_id=project_id,
            max_attempts=1,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        attempt_id = created["attempt_id"]
        queue_attempt(
            DATABASE_URL,
            attempt_id=attempt_id,
            project_id=project_id,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        first = acquire_attempt_lease(
            DATABASE_URL,
            attempt_id=attempt_id,
            project_id=project_id,
            worker_id="worker-cancel-old",
            lease_seconds=30,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        old_worker = WorkerLeaseCommand(
            attempt_id=attempt_id,
            project_id=project_id,
            worker_id="worker-cancel-old",
            fencing_token=first["fencing_token"],
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        start_attempt(DATABASE_URL, old_worker)
        request_cancellation(
            DATABASE_URL,
            self._cancel(operation_id, project_id, expected_version=1),
        )
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE authority_lease_acquisition
                SET acquired_at = NOW() - INTERVAL '2 seconds',
                    heartbeat_at = NOW() - INTERVAL '2 seconds',
                    expires_at = NOW() - INTERVAL '1 second'
                WHERE attempt_id = %s AND status = 'HELD'
                """,
                [attempt_id],
            )
        second = acquire_attempt_lease(
            DATABASE_URL,
            attempt_id=attempt_id,
            project_id=project_id,
            worker_id="worker-cancel-current",
            lease_seconds=30,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        current_worker = WorkerLeaseCommand(
            attempt_id=attempt_id,
            project_id=project_id,
            worker_id="worker-cancel-current",
            fencing_token=second["fencing_token"],
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        start_attempt(DATABASE_URL, current_worker)

        with self.assertRaises(KernelError) as caught:
            acknowledge_worker_cancellation(
                DATABASE_URL,
                old_worker,
                expected_operation_version=2,
            )

        self.assertEqual(caught.exception.code, "ATTEMPT_FENCING_TOKEN_STALE")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT attempt.status, attempt.worker_id,
                       operation.status, operation.version,
                       signal.status,
                       (SELECT status FROM authority_lease_acquisition
                        WHERE attempt_id = %s AND fencing_token = 2),
                       (SELECT COUNT(*) FROM authority_late_result_evidence
                        WHERE attempt_id = %s AND command_type = 'cancel_acknowledgement')
                FROM authority_attempt AS attempt
                JOIN authority_operation AS operation
                  ON operation.operation_id = attempt.operation_id
                JOIN authority_worker_cancel_signal AS signal
                  ON signal.attempt_id = attempt.attempt_id
                WHERE attempt.attempt_id = %s
                """,
                [attempt_id, attempt_id, attempt_id],
            )
            self.assertEqual(
                cursor.fetchone(),
                (
                    "RUNNING",
                    "worker-cancel-current",
                    "CANCELLATION_REQUESTED",
                    2,
                    "REQUESTED",
                    "HELD",
                    1,
                ),
            )

        result = acknowledge_worker_cancellation(
            DATABASE_URL,
            current_worker,
            expected_operation_version=2,
        )
        self.assertEqual(result["status"], "CANCELLED")

    def _operation(self, status: str) -> tuple[str, str]:
        project_id = identifier("project")
        operation_id = identifier("operation")
        definition_name = identifier("definition")
        with transaction() as connection, connection.cursor() as cursor:
            insert_definition(cursor, definition_name)
            insert_operation(
                cursor,
                operation_id=operation_id,
                definition_name=definition_name,
                project_id=project_id,
                status=status,
            )
        return project_id, operation_id

    def test_cancelled_root_closes_terminal_reference_failure_without_rewriting_child(self):
        project, root = self._operation("CANCELLATION_REQUESTED")
        child = identifier("failed-intent")
        with transaction() as connection, connection.cursor() as cursor:
            definition = identifier("intent-definition")
            insert_definition(cursor, definition)
            insert_operation(cursor,operation_id=child,definition_name=definition,project_id=project,
                status="FAILED_FINAL",root_operation_id=root,parent_operation_id=root)
        result = resolve_cancellation(DATABASE_URL,operation_id=root,project_id=project,expected_version=0,
            resolution="no_external_effect",actor_id="operator-cancel",reason="Active PlanChange retires unproduced graph",
            trace_id=identifier("trace"),correlation_id=identifier("correlation"),
            require_no_active_attempt=True,require_terminal_children_without_effects=True)
        self.assertEqual(result["status"],"CANCELLED")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT status,version FROM authority_operation WHERE operation_id=%s",[child])
            self.assertEqual(cursor.fetchone(),("FAILED_FINAL",0))

    def test_cancelled_root_cannot_close_live_descendant(self):
        for status in ("READY","EXECUTING","RECONCILIATION_REQUIRED"):
            with self.subTest(status=status):
                project, root = self._operation("CANCELLATION_REQUESTED")
                with transaction() as connection, connection.cursor() as cursor:
                    definition = identifier("live-definition")
                    insert_definition(cursor,definition)
                    insert_operation(cursor,operation_id=identifier("child"),definition_name=definition,project_id=project,
                        status=status,root_operation_id=root,parent_operation_id=root)
                with self.assertRaises(KernelError) as raised:
                    resolve_cancellation(DATABASE_URL,operation_id=root,project_id=project,expected_version=0,
                        resolution="no_external_effect",actor_id="operator-cancel",reason="Do not bypass live work",
                        trace_id=identifier("trace"),correlation_id=identifier("correlation"),
                        require_terminal_children_without_effects=True)
                self.assertEqual(raised.exception.code,"CANCELLATION_CHILDREN_UNSETTLED")

    def _compensation_definition(
        self,
        *,
        enabled: bool = True,
        register: bool = True,
    ) -> dict:
        definition = {
            **definition_payload(identifier("compensation-definition")),
            "enabled": enabled,
            "family": "compensation",
            "handler_key": "novel_forge.command_handlers.compensation.reverse_effect",
            "permissions": ["operation.compensate"],
            "idempotency_scope": "operation:compensation",
            "concurrency_key_template": "operation:{parent_operation_id}:compensation",
            "command_schema": {
                "type": "object",
                "required": [
                    "parent_operation_id",
                    "compensation_generation",
                    "reason",
                ],
                "properties": {
                    "parent_operation_id": {"type": "string"},
                    "compensation_generation": {"type": "integer"},
                    "reason": {"type": "string"},
                },
                "additionalProperties": False,
            },
        }
        if register:
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.repositories.definitions.register(definition)
                uow.commit()
        return definition

    @staticmethod
    def _compensation_context(definition: dict) -> AdmissionContext:
        return AdmissionContext(
            actor_id="kernel.compensator",
            permissions=frozenset(definition["permissions"]),
            available_handlers=frozenset({definition["handler_key"]}),
            application_build_id="compensation-test-build",
            commit_sha="e" * 40,
        )

    @staticmethod
    def _create_compensation(
        parent_operation_id: str,
        project_id: str,
        definition: dict,
        context: AdmissionContext,
        *,
        reason: str,
    ) -> dict:
        return {
            "parent_operation_id": parent_operation_id,
            "project_id": project_id,
            "expected_parent_version": 0,
            "definition_name": definition["name"],
            "definition_version": definition["definition_version"],
            "compensation_generation": 1,
            "actor_id": "kernel.compensator",
            "reason": reason,
            "trace_id": identifier("trace"),
            "correlation_id": identifier("correlation"),
            "context": context,
        }

    @staticmethod
    def _cancel(
        operation_id: str, project_id: str, expected_version: int
    ) -> CancelCommand:
        return CancelCommand(
            operation_id=operation_id,
            project_id=project_id,
            actor_id="operator-cancel",
            reason="operator requested cancellation",
            expected_version=expected_version,
            idempotency_key=identifier("cancel"),
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )

    @staticmethod
    def _transition(
        operation_id: str,
        project_id: str,
        version: int,
        status: str,
        target: str,
    ) -> None:
        transition_operation(
            DATABASE_URL,
            OperationTransitionCommand(
                operation_id=operation_id,
                project_id=project_id,
                expected_version=version,
                expected_status=status,
                target_status=target,
                actor_id="compensation-worker",
                reason="compensation child progress",
                trace_id=identifier("trace"),
                correlation_id=identifier("correlation"),
                causation_id="",
            ),
        )


if __name__ == "__main__":
    unittest.main()
