from __future__ import annotations

import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from novel_forge.modules.command_kernel.attempt_runtime import (
    WorkerLeaseCommand,
    WorkerResultCommand,
    acquire_attempt_lease,
    checkpoint_attempt,
    cancel_attempt,
    create_attempt,
    expire_attempt_lease,
    queue_attempt,
    start_attempt,
    submit_attempt_result,
    supersede_attempt,
    timeout_attempt,
)
from novel_forge.modules.command_kernel.errors import KernelError
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    insert_definition,
    insert_operation,
    transaction,
)
from tests.integration.test_authority_attempt_lease_schema_postgres import insert_attempt


class CommandKernelAttemptRuntimePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_attempt_runs_through_fenced_checkpoint_and_success(self) -> None:
        project_id, operation_id = self._operation("READY")
        attempt = self._create_and_queue(project_id, operation_id)
        lease = acquire_attempt_lease(
            DATABASE_URL,
            attempt_id=attempt,
            project_id=project_id,
            worker_id="worker-a",
            lease_seconds=30,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        worker = self._worker(attempt, project_id, "worker-a", lease["fencing_token"])
        start_attempt(DATABASE_URL, worker)
        checkpoint_attempt(DATABASE_URL, worker, {"cursor": 7})
        result_command = WorkerResultCommand(
            **worker.__dict__,
            expected_operation_version=1,
            expected_operation_status="EXECUTING",
        )

        submit_attempt_result(
            DATABASE_URL,
            result_command,
            outcome="success",
            result={"value": "accepted"},
        )

        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT attempt.status, attempt.checkpoint, attempt.result,
                       operation.status, operation.version,
                       lease.status
                FROM authority_attempt AS attempt
                JOIN authority_operation AS operation
                  ON operation.operation_id = attempt.operation_id
                JOIN authority_lease_acquisition AS lease
                  ON lease.attempt_id = attempt.attempt_id
                WHERE attempt.attempt_id = %s AND operation.project_id = %s
                """,
                [attempt, project_id],
            )
            self.assertEqual(
                cursor.fetchone(),
                (
                    "SUCCEEDED",
                    {"cursor": 7},
                    {"value": "accepted"},
                    "SUCCEEDED",
                    2,
                    "RELEASED",
                ),
            )

    def test_two_workers_compete_for_one_lease(self) -> None:
        project_id, operation_id = self._operation("READY")
        attempt = self._create_and_queue(project_id, operation_id)
        barrier = Barrier(2)

        def acquire(worker_id: str) -> tuple[str, int | str]:
            barrier.wait(timeout=5)
            try:
                lease = acquire_attempt_lease(
                    DATABASE_URL,
                    attempt_id=attempt,
                    project_id=project_id,
                    worker_id=worker_id,
                    lease_seconds=30,
                    trace_id=identifier("trace"),
                    correlation_id=identifier("correlation"),
                )
                return "acquired", lease["fencing_token"]
            except KernelError as exc:
                return "rejected", exc.code

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(acquire, ("worker-a", "worker-b")))

        self.assertEqual(
            sorted(result[0] for result in results),
            ["acquired", "rejected"],
        )
        self.assertIn(("acquired", 1), results)
        self.assertIn(("rejected", "LEASE_NOT_AVAILABLE"), results)

    def test_stale_checkpoint_does_not_stop_takeover_worker(self) -> None:
        project_id, operation_id = self._operation("READY")
        attempt = self._create_and_queue(project_id, operation_id)
        first = acquire_attempt_lease(
            DATABASE_URL,
            attempt_id=attempt,
            project_id=project_id,
            worker_id="worker-old",
            lease_seconds=1,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        old_worker = self._worker(
            attempt,
            project_id,
            "worker-old",
            first["fencing_token"],
        )
        start_attempt(DATABASE_URL, old_worker)
        self._expire_lease(attempt)
        second = acquire_attempt_lease(
            DATABASE_URL,
            attempt_id=attempt,
            project_id=project_id,
            worker_id="worker-new",
            lease_seconds=30,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        new_worker = self._worker(
            attempt,
            project_id,
            "worker-new",
            second["fencing_token"],
        )
        start_attempt(DATABASE_URL, new_worker)

        with self.assertRaises(KernelError) as caught:
            checkpoint_attempt(DATABASE_URL, old_worker, {"cursor": "late"})

        self.assertEqual(caught.exception.code, "ATTEMPT_FENCING_TOKEN_STALE")
        self.assertEqual(second["fencing_token"], 2)
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT attempt.status, attempt.worker_id,
                       operation.status, operation.version,
                       (SELECT COUNT(*) FROM authority_late_result_evidence WHERE attempt_id = %s),
                       (SELECT status FROM authority_lease_acquisition
                        WHERE attempt_id = %s AND fencing_token = 2)
                FROM authority_attempt AS attempt
                JOIN authority_operation AS operation
                  ON operation.operation_id = attempt.operation_id
                WHERE attempt.attempt_id = %s AND operation.project_id = %s
                """,
                [attempt, attempt, attempt, project_id],
            )
            self.assertEqual(
                cursor.fetchone(),
                ("RUNNING", "worker-new", "EXECUTING", 1, 1, "HELD"),
            )

        checkpoint_attempt(DATABASE_URL, new_worker, {"cursor": "current"})
        submit_attempt_result(
            DATABASE_URL,
            WorkerResultCommand(
                **new_worker.__dict__,
                expected_operation_version=1,
                expected_operation_status="EXECUTING",
            ),
            outcome="success",
            result={"value": "accepted-after-takeover"},
        )
        self._assert_succeeded_after_takeover(attempt, operation_id, project_id)

    def test_heartbeat_loss_marks_attempt_lease_lost(self) -> None:
        project_id, operation_id = self._operation("READY")
        attempt = self._create_and_queue(project_id, operation_id)
        lease = acquire_attempt_lease(
            DATABASE_URL,
            attempt_id=attempt,
            project_id=project_id,
            worker_id="worker-crash",
            lease_seconds=1,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        worker = self._worker(
            attempt,
            project_id,
            "worker-crash",
            lease["fencing_token"],
        )
        start_attempt(DATABASE_URL, worker)
        time.sleep(1.05)

        expire_attempt_lease(DATABASE_URL, worker)

        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT status FROM authority_attempt WHERE attempt_id = %s",
                [attempt],
            )
            self.assertEqual(cursor.fetchone()[0], "LEASE_LOST")

    def test_stale_result_does_not_stop_takeover_worker(self) -> None:
        project_id, operation_id = self._operation("READY")
        attempt = self._create_and_queue(project_id, operation_id)
        first = acquire_attempt_lease(
            DATABASE_URL,
            attempt_id=attempt,
            project_id=project_id,
            worker_id="worker-old-result",
            lease_seconds=1,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        old_worker = self._worker(
            attempt,
            project_id,
            "worker-old-result",
            first["fencing_token"],
        )
        start_attempt(DATABASE_URL, old_worker)
        self._expire_lease(attempt)
        second = acquire_attempt_lease(
            DATABASE_URL,
            attempt_id=attempt,
            project_id=project_id,
            worker_id="worker-new-result",
            lease_seconds=30,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        new_worker = self._worker(
            attempt,
            project_id,
            "worker-new-result",
            second["fencing_token"],
        )
        start_attempt(DATABASE_URL, new_worker)
        old_result = WorkerResultCommand(
            **old_worker.__dict__,
            expected_operation_version=1,
            expected_operation_status="EXECUTING",
        )

        with self.assertRaises(KernelError) as caught:
            submit_attempt_result(
                DATABASE_URL,
                old_result,
                outcome="success",
                result={"value": "must-not-commit"},
            )

        self.assertEqual(caught.exception.code, "ATTEMPT_FENCING_TOKEN_STALE")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT status, version
                FROM authority_operation
                WHERE operation_id = %s AND project_id = %s
                """,
                [operation_id, project_id],
            )
            self.assertEqual(cursor.fetchone(), ("EXECUTING", 1))

        submit_attempt_result(
            DATABASE_URL,
            WorkerResultCommand(
                **new_worker.__dict__,
                expected_operation_version=1,
                expected_operation_status="EXECUTING",
            ),
            outcome="success",
            result={"value": "current-worker-wins"},
        )
        self._assert_succeeded_after_takeover(attempt, operation_id, project_id)

    def test_concurrent_stale_and_current_results_accept_only_current_fence(self) -> None:
        project_id, operation_id = self._operation("READY")
        attempt = self._create_and_queue(project_id, operation_id)
        first = acquire_attempt_lease(
            DATABASE_URL,
            attempt_id=attempt,
            project_id=project_id,
            worker_id="worker-race-old",
            lease_seconds=30,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        old_worker = self._worker(
            attempt,
            project_id,
            "worker-race-old",
            first["fencing_token"],
        )
        start_attempt(DATABASE_URL, old_worker)
        self._expire_lease(attempt)
        second = acquire_attempt_lease(
            DATABASE_URL,
            attempt_id=attempt,
            project_id=project_id,
            worker_id="worker-race-current",
            lease_seconds=30,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        current_worker = self._worker(
            attempt,
            project_id,
            "worker-race-current",
            second["fencing_token"],
        )
        start_attempt(DATABASE_URL, current_worker)
        barrier = Barrier(2)

        def submit(worker: WorkerLeaseCommand, value: str) -> tuple[str, str]:
            barrier.wait(timeout=5)
            try:
                submit_attempt_result(
                    DATABASE_URL,
                    WorkerResultCommand(
                        **worker.__dict__,
                        expected_operation_version=1,
                        expected_operation_status="EXECUTING",
                    ),
                    outcome="success",
                    result={"value": value},
                )
                return value, "accepted"
            except KernelError as exc:
                return value, exc.code

        with ThreadPoolExecutor(max_workers=2) as executor:
            old_future = executor.submit(submit, old_worker, "stale")
            current_future = executor.submit(submit, current_worker, "current")
            outcomes = {old_future.result(), current_future.result()}

        self.assertEqual(
            outcomes,
            {
                ("stale", "ATTEMPT_FENCING_TOKEN_STALE"),
                ("current", "accepted"),
            },
        )
        self._assert_succeeded_after_takeover(attempt, operation_id, project_id)
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM authority_late_result_evidence WHERE attempt_id = %s",
                [attempt],
            )
            self.assertEqual(cursor.fetchone()[0], 1)

    def test_retry_exhaustion_dead_letters_operation_without_new_attempt(self) -> None:
        project_id, operation_id = self._operation("FAILED_RETRYABLE")
        with transaction() as connection, connection.cursor() as cursor:
            insert_attempt(
                cursor,
                attempt_id=identifier("attempt-old"),
                operation_id=operation_id,
                attempt_number=1,
                status="FAILED_RETRYABLE",
            )

        result = create_attempt(
            DATABASE_URL,
            operation_id=operation_id,
            project_id=project_id,
            max_attempts=1,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )

        self.assertTrue(result["dead_letter"])
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT status, version FROM authority_operation WHERE operation_id = %s",
                [operation_id],
            )
            self.assertEqual(cursor.fetchone(), ("DEAD_LETTER", 1))

    def test_retry_creates_a_new_attempt_and_moves_operation_back_to_ready(self) -> None:
        project_id, operation_id = self._operation("READY")
        first_attempt = self._create_and_queue(project_id, operation_id)
        lease = acquire_attempt_lease(
            DATABASE_URL,
            attempt_id=first_attempt,
            project_id=project_id,
            worker_id="worker-retry",
            lease_seconds=30,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        worker = self._worker(
            first_attempt,
            project_id,
            "worker-retry",
            lease["fencing_token"],
        )
        start_attempt(DATABASE_URL, worker)
        submit_attempt_result(
            DATABASE_URL,
            WorkerResultCommand(
                **worker.__dict__,
                expected_operation_version=1,
                expected_operation_status="EXECUTING",
            ),
            outcome="retryable_failure",
            result={"code": "TRANSIENT"},
        )

        retry = create_attempt(
            DATABASE_URL,
            operation_id=operation_id,
            project_id=project_id,
            max_attempts=3,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )

        self.assertEqual(retry["attempt_number"], 2)
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT operation.status, operation.version,
                       ARRAY_AGG(attempt.status ORDER BY attempt.attempt_number)
                FROM authority_operation AS operation
                JOIN authority_attempt AS attempt
                  ON attempt.operation_id = operation.operation_id
                WHERE operation.operation_id = %s AND operation.project_id = %s
                GROUP BY operation.status, operation.version
                """,
                [operation_id, project_id],
            )
            self.assertEqual(
                cursor.fetchone(),
                ("READY", 3, ["FAILED_RETRYABLE", "CREATED"]),
            )

    def test_kernel_can_timeout_cancel_and_supersede_attempts(self) -> None:
        transitions = (
            ("QUEUED", timeout_attempt, "TIMED_OUT"),
            ("CREATED", cancel_attempt, "CANCELLED"),
            ("CREATED", supersede_attempt, "SUPERSEDED"),
        )
        for initial_status, action, target_status in transitions:
            with self.subTest(target_status=target_status):
                project_id, operation_id = self._operation("READY")
                created = create_attempt(
                    DATABASE_URL,
                    operation_id=operation_id,
                    project_id=project_id,
                    max_attempts=1,
                    trace_id=identifier("trace"),
                    correlation_id=identifier("correlation"),
                )
                if initial_status == "QUEUED":
                    queue_attempt(
                        DATABASE_URL,
                        attempt_id=created["attempt_id"],
                        project_id=project_id,
                        trace_id=identifier("trace"),
                        correlation_id=identifier("correlation"),
                    )
                action(
                    DATABASE_URL,
                    attempt_id=created["attempt_id"],
                    project_id=project_id,
                    trace_id=identifier("trace"),
                    correlation_id=identifier("correlation"),
                )
                with transaction() as connection, connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT status FROM authority_attempt WHERE attempt_id = %s",
                        [created["attempt_id"]],
                    )
                    self.assertEqual(cursor.fetchone()[0], target_status)

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

    def _create_and_queue(self, project_id: str, operation_id: str) -> str:
        created = create_attempt(
            DATABASE_URL,
            operation_id=operation_id,
            project_id=project_id,
            max_attempts=3,
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
        return created["attempt_id"]

    @staticmethod
    def _expire_lease(attempt_id: str) -> None:
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

    def _assert_succeeded_after_takeover(
        self,
        attempt_id: str,
        operation_id: str,
        project_id: str,
    ) -> None:
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT attempt.status, operation.status, operation.version,
                       (SELECT COUNT(*) FROM authority_lease_acquisition
                        WHERE attempt_id = %s AND status = 'HELD')
                FROM authority_attempt AS attempt
                JOIN authority_operation AS operation
                  ON operation.operation_id = attempt.operation_id
                WHERE attempt.attempt_id = %s
                  AND operation.operation_id = %s
                  AND operation.project_id = %s
                """,
                [attempt_id, attempt_id, operation_id, project_id],
            )
            self.assertEqual(cursor.fetchone(), ("SUCCEEDED", "SUCCEEDED", 2, 0))

    @staticmethod
    def _worker(
        attempt_id: str,
        project_id: str,
        worker_id: str,
        fencing_token: int,
    ) -> WorkerLeaseCommand:
        return WorkerLeaseCommand(
            attempt_id=attempt_id,
            project_id=project_id,
            worker_id=worker_id,
            fencing_token=fencing_token,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )


if __name__ == "__main__":
    unittest.main()
