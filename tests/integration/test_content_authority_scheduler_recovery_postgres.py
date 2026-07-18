from __future__ import annotations

import unittest
import time
from unittest.mock import patch

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
from novel_forge.modules.command_kernel.worker_execution import AuthorityWorkerExecutionBoundary
from novel_forge.modules.content_authority import CONTENT_CODECS
from novel_forge.modules.content_authority.application import (
    ContentAuthorityApplication,
    ContentOperationRequest,
)
from novel_forge.modules.content_authority.definitions import CONTENT_DEFINITION_VERSION
from novel_forge.modules.content_authority.runtime import execute_content_handler
from novel_forge.modules.content_authority.scheduler import ContentAuthorityScheduler
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    transaction,
)


class ContentAuthoritySchedulerRecoveryPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def setUp(self) -> None:
        self.project_id = identifier("content-recovery-project")
        self.app = ContentAuthorityApplication(
            DATABASE_URL,
            application_build_id="content-recovery-integration",
            commit_sha="e" * 40,
            integration_proven=CONTENT_CODECS,
        )

    def request(self, suffix: str) -> ContentOperationRequest:
        return ContentOperationRequest(
            definition_name="theme.question.create",
            project_id=self.project_id,
            workspace_id=f"workspace:{self.project_id}",
            actor_id="content-recovery-operator",
            trace_id=f"trace:{self.project_id}:{suffix}",
            correlation_id=f"correlation:{self.project_id}:{suffix}",
            idempotency_key=f"{self.project_id}:theme:{suffix}",
            payload={
                "question": "When safety demands betrayal, is loyalty worth its visible cost?"
            },
        )

    def start_worker(
        self,
        operation_id: str,
        *,
        worker_id: str,
        trace_id: str,
        correlation_id: str,
    ) -> WorkerLeaseCommand:
        attempt = create_attempt(
            DATABASE_URL,
            operation_id=operation_id,
            project_id=self.project_id,
            max_attempts=2,
            trace_id=trace_id,
            correlation_id=correlation_id,
        )
        attempt_id = str(attempt["attempt_id"])
        queue_attempt(
            DATABASE_URL,
            attempt_id=attempt_id,
            project_id=self.project_id,
            trace_id=trace_id,
            correlation_id=correlation_id,
        )
        lease = acquire_attempt_lease(
            DATABASE_URL,
            attempt_id=attempt_id,
            project_id=self.project_id,
            worker_id=worker_id,
            lease_seconds=30,
            trace_id=trace_id,
            correlation_id=correlation_id,
        )
        worker = WorkerLeaseCommand(
            attempt_id=attempt_id,
            project_id=self.project_id,
            worker_id=worker_id,
            fencing_token=int(lease["fencing_token"]),
            trace_id=trace_id,
            correlation_id=correlation_id,
            causation_id=operation_id,
        )
        start_attempt(DATABASE_URL, worker)
        return worker

    def test_crash_before_output_recovers_with_new_attempt(self) -> None:
        request = self.request("before-output")
        admission = self.app.admit(request)
        worker = self.start_worker(
            admission.operation_id,
            worker_id="content-crash-before-output",
            trace_id=request.trace_id,
            correlation_id=request.correlation_id,
        )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            state = uow.repositories.attempt_runtime.operation_state(
                admission.operation_id, self.project_id
            )
        submit_attempt_result(
            DATABASE_URL,
            WorkerResultCommand(
                **worker.__dict__,
                expected_operation_status=state["status"],
                expected_operation_version=state["version"],
            ),
            outcome="retryable_failure",
            result={"error_code": "INJECTED_CRASH_BEFORE_OUTPUT"},
        )

        recovered = ContentAuthorityScheduler(
            DATABASE_URL,
            registry=self.app.registry,
            worker_id="content-recovery-worker",
        ).run_or_recover(
            operation_id=admission.operation_id,
            project_id=self.project_id,
        )

        self.assertEqual(recovered.recovery_mode, "retry_attempt")
        self.assertEqual(recovered.attempt_number, 2)
        self.assertFalse(recovered.output.replayed)
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT status FROM authority_operation WHERE operation_id = %s",
                [admission.operation_id],
            )
            self.assertEqual(cursor.fetchone()[0], "SUCCEEDED")
            cursor.execute(
                "SELECT ARRAY_AGG(status ORDER BY attempt_number) FROM authority_attempt WHERE operation_id = %s",
                [admission.operation_id],
            )
            self.assertEqual(cursor.fetchone()[0], ["FAILED_RETRYABLE", "SUCCEEDED"])

    def test_crash_after_output_takes_over_replays_and_fences_stale_worker(self) -> None:
        request = self.request("after-output")
        admission = self.app.admit(request)
        stale_worker = self.start_worker(
            admission.operation_id,
            worker_id="content-crash-after-output",
            trace_id=request.trace_id,
            correlation_id=request.correlation_id,
        )
        first_output = execute_content_handler(
            DATABASE_URL,
            command=stale_worker,
            definition_name=request.definition_name,
            definition_version=CONTENT_DEFINITION_VERSION,
            registry=self.app.registry,
        )
        scheduler = ContentAuthorityScheduler(
            DATABASE_URL,
            registry=self.app.registry,
            worker_id="content-takeover-worker",
        )
        with self.assertRaises(KernelError) as active:
            scheduler.run_or_recover(
                operation_id=admission.operation_id,
                project_id=self.project_id,
            )
        self.assertEqual(active.exception.code, "CONTENT_RECOVERY_LEASE_ACTIVE")

        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE authority_lease_acquisition
                SET acquired_at = NOW() - INTERVAL '2 seconds',
                    heartbeat_at = NOW() - INTERVAL '2 seconds',
                    expires_at = NOW() - INTERVAL '1 second'
                WHERE attempt_id = %s AND status = 'HELD'
                """,
                [stale_worker.attempt_id],
            )
        recovered = scheduler.run_or_recover(
            operation_id=admission.operation_id,
            project_id=self.project_id,
        )

        self.assertEqual(recovered.recovery_mode, "output_replay_takeover")
        self.assertTrue(recovered.output.replayed)
        self.assertEqual(recovered.output.asset_version_id, first_output.asset_version_id)
        with self.assertRaises(KernelError) as stale:
            execute_content_handler(
                DATABASE_URL,
                command=stale_worker,
                definition_name=request.definition_name,
                definition_version=CONTENT_DEFINITION_VERSION,
                registry=self.app.registry,
            )
        self.assertEqual(stale.exception.code, "ATTEMPT_FENCING_TOKEN_STALE")

        replay = self.app.execute(request)
        self.assertTrue(replay.replayed)
        self.assertEqual(replay.asset_version_id, first_output.asset_version_id)
        topic = f"content.{request.definition_name}.materialized"
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM authority_operation_output_asset WHERE operation_id = %s",
                [admission.operation_id],
            )
            self.assertEqual(cursor.fetchone()[0], 1)
            cursor.execute(
                "SELECT COUNT(*) FROM audit_log WHERE operation_id = %s AND action = %s",
                [admission.operation_id, topic],
            )
            self.assertEqual(cursor.fetchone()[0], 1)
            cursor.execute(
                "SELECT COUNT(*) FROM outbox_event WHERE project_id = %s AND topic = %s AND payload->>'operation_id' = %s",
                [self.project_id, topic, admission.operation_id],
            )
            self.assertEqual(cursor.fetchone()[0], 1)
            cursor.execute(
                "SELECT COUNT(*) FROM authority_lease_acquisition WHERE attempt_id = %s",
                [stale_worker.attempt_id],
            )
            self.assertEqual(cursor.fetchone()[0], 2)

    def test_slow_handler_renews_attempt_lease_until_completion(self) -> None:
        request = self.request("slow-heartbeat")
        admission = self.app.admit(request)
        scheduler = ContentAuthorityScheduler(
            DATABASE_URL,
            registry=self.app.registry,
            worker_id="content-slow-worker",
            lease_seconds=1,
        )

        def slow_handler(*args, **kwargs):
            time.sleep(1.2)
            return execute_content_handler(*args, **kwargs)

        with patch(
            "novel_forge.modules.content_authority.scheduler.execute_content_handler",
            side_effect=slow_handler,
        ):
            result = scheduler.run_or_recover(
                operation_id=admission.operation_id,
                project_id=self.project_id,
            )

        self.assertEqual(result.output.operation_id, admission.operation_id)
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT heartbeat_at > acquired_at FROM authority_lease_acquisition WHERE attempt_id = %s",
                [result.attempt_id],
            )
            self.assertTrue(cursor.fetchone()[0])

    def test_batch_failure_is_persisted_and_next_operation_succeeds(self) -> None:
        first_request = self.request("batch-first")
        second_request = self.request("batch-second")
        first = self.app.admit(first_request)
        second = self.app.admit(second_request)
        scheduler = ContentAuthorityScheduler(
            DATABASE_URL, registry=self.app.registry, worker_id="content-batch-worker",
        )
        original = execute_content_handler

        def fail_first(*args, **kwargs):
            command = kwargs["command"]
            if command.causation_id == first.operation_id:
                raise KernelError("INPUT_INVALID", "isolated PostgreSQL task failure")
            return original(*args, **kwargs)

        with patch(
            "novel_forge.modules.content_authority.scheduler.execute_content_handler",
            side_effect=fail_first,
        ):
            failures = AuthorityWorkerExecutionBoundary(worker_kind="content-integration").execute_batch(
                ((first.operation_id, self.project_id), (second.operation_id, self.project_id)),
                identity=lambda item: (item[1], item[0]),
                execute=lambda item: scheduler.run_or_recover(operation_id=item[0], project_id=item[1]),
            )
        self.assertEqual(len(failures), 1)
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT operation_id, status FROM authority_operation WHERE operation_id = ANY(%s) ORDER BY operation_id", [[first.operation_id, second.operation_id]])
            statuses = dict(cursor.fetchall())
            self.assertEqual(statuses[first.operation_id], "FAILED_FINAL")
            self.assertEqual(statuses[second.operation_id], "SUCCEEDED")
            cursor.execute("SELECT COUNT(*) FROM state_event WHERE aggregate_id = %s AND event_type = 'authority.operation.status_changed'", [first.operation_id])
            self.assertGreaterEqual(cursor.fetchone()[0], 1)
            cursor.execute("SELECT COUNT(*) FROM audit_log WHERE operation_id = %s", [first.operation_id])
            self.assertGreaterEqual(cursor.fetchone()[0], 1)
            cursor.execute("SELECT COUNT(*) FROM outbox_event WHERE payload->>'operation_id' = %s", [first.operation_id])
            self.assertGreaterEqual(cursor.fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
