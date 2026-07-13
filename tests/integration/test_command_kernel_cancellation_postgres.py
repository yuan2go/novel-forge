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
from novel_forge.modules.command_kernel.runtime import (
    OperationTransitionCommand,
    transition_operation,
)
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    insert_definition,
    insert_operation,
    transaction,
)
from tests.integration.test_authority_attempt_lease_schema_postgres import insert_attempt


class CommandKernelCancellationPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_two_concurrent_cancel_commands_are_idempotent_and_signal_worker(self) -> None:
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

        self.assertEqual(sorted(result["replayed"] for result in results), [False, True])
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

    def test_compensation_child_success_and_failure_have_distinct_parent_terminals(self) -> None:
        for child_target, parent_target in (
            ("SUCCEEDED", "COMPENSATED"),
            ("FAILED_FINAL", "COMPENSATION_FAILED"),
        ):
            with self.subTest(child_target=child_target):
                project_id, parent_id = self._operation("EXECUTING")
                compensation_definition = identifier("compensation-definition")
                with transaction() as connection, connection.cursor() as cursor:
                    insert_definition(cursor, compensation_definition)
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
                child_id = create_compensation_child(
                    DATABASE_URL,
                    parent_operation_id=parent_id,
                    project_id=project_id,
                    expected_parent_version=2,
                    definition_name=compensation_definition,
                    definition_version="1.0.0",
                    actor_id="kernel.compensator",
                    reason="reverse external effect",
                    trace_id=identifier("trace"),
                    correlation_id=identifier("correlation"),
                )
                if child_target == "SUCCEEDED":
                    self._transition(child_id, project_id, 0, "ADMITTED", "READY")
                    self._transition(child_id, project_id, 1, "READY", "EXECUTING")
                    self._transition(child_id, project_id, 2, "EXECUTING", "SUCCEEDED")
                else:
                    self._transition(child_id, project_id, 0, "ADMITTED", "FAILED_FINAL")

                result = complete_compensation_from_child(
                    DATABASE_URL,
                    child_operation_id=child_id,
                    project_id=project_id,
                    actor_id="kernel.compensator",
                    trace_id=identifier("trace"),
                    correlation_id=identifier("correlation"),
                )

                self.assertEqual(result["status"], parent_target)

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

    @staticmethod
    def _cancel(operation_id: str, project_id: str, expected_version: int) -> CancelCommand:
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
