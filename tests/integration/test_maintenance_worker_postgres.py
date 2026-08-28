from __future__ import annotations

import unittest
import time

from novel_forge.modules.runtime_job import RuntimeJobAuthority
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.workers.runtime_groups import (
    MAINTENANCE_RUNTIME_JOB_KINDS,
    execute_maintenance_runtime_claim,
    schedule_maintenance_runtime_jobs,
)
from tests.integration.authority_postgres_support import (
    ensure_migrated,
    identifier,
    insert_definition,
    insert_operation,
    transaction,
    DATABASE_URL,
)


class MaintenanceWorkerPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_cycle_expires_attempt_and_outbox_leases_and_marks_timeout(self) -> None:
        project_id = identifier("maintenance-project")
        operation_id = identifier("maintenance-operation")
        attempt_id = identifier("maintenance-attempt")
        lease_id = identifier("maintenance-lease")
        event_id = identifier("maintenance-event")
        outbox_id = identifier("maintenance-outbox")
        definition = identifier("maintenance-definition")
        with transaction() as connection, connection.cursor() as cursor:
            insert_definition(cursor, definition)
            insert_operation(
                cursor,
                operation_id=operation_id,
                definition_name=definition,
                project_id=project_id,
                status="READY",
            )
            cursor.execute(
                "UPDATE authority_operation SET business_deadline_at=NOW()-INTERVAL '1 second' "
                "WHERE operation_id=%s",
                [operation_id],
            )
            cursor.execute(
                """
                INSERT INTO authority_attempt(
                    attempt_id,operation_id,attempt_number,status,worker_id,started_at
                ) VALUES (%s,%s,1,'RUNNING','crashed-maintenance-worker',
                          NOW()-INTERVAL '2 minutes')
                """,
                [attempt_id, operation_id],
            )
            cursor.execute(
                """
                INSERT INTO authority_lease_acquisition(
                    lease_id,attempt_id,owner,fencing_token,acquired_at,expires_at,status
                ) VALUES (%s,%s,'crashed-maintenance-worker',1,
                          NOW()-INTERVAL '2 minutes',NOW()-INTERVAL '1 minute','HELD')
                """,
                [lease_id, attempt_id],
            )
            cursor.execute(
                """
                INSERT INTO state_event(
                    event_id,aggregate_type,aggregate_id,project_id,event_type,
                    event_version,sequence_number,payload
                ) VALUES (%s,'maintenance',%s,%s,'maintenance.probe',1,1,'{}'::jsonb)
                """,
                [event_id, outbox_id, project_id],
            )
            cursor.execute(
                """
                INSERT INTO outbox_event(
                    outbox_id,event_id,project_id,topic,status,claimed_by,claimed_at,
                    lease_expires_at,payload,attempt_count,lease_id,fencing_token,
                    runtime_group
                ) VALUES (%s,%s,%s,'maintenance.probe','claimed','crashed-outbox',
                          NOW()-INTERVAL '2 minutes',NOW()-INTERVAL '1 minute',
                          '{}'::jsonb,1,%s,1,'outbox')
                """,
                [outbox_id, event_id, project_id, f"{outbox_id}:1"],
            )

        runtime_jobs = RuntimeJobAuthority(DATABASE_URL)
        scheduled = schedule_maintenance_runtime_jobs(
            runtime_jobs,
            batch_limit=10_000,
            schedule_bucket=time.time_ns(),
        )
        self.assertEqual(len(scheduled), len(MAINTENANCE_RUNTIME_JOB_KINDS))
        self.assertEqual(
            len({str(item["runtime_job_id"]) for item in scheduled}),
            len(MAINTENANCE_RUNTIME_JOB_KINDS),
        )
        results: dict[str, dict[str, object]] = {}
        claims = []
        for _ in MAINTENANCE_RUNTIME_JOB_KINDS:
            claim = runtime_jobs.claim(
                runtime_group="maintenance",
                worker_id="maintenance-integration-worker",
                lease_seconds=30,
                job_kinds=MAINTENANCE_RUNTIME_JOB_KINDS,
            )
            self.assertIsNotNone(claim)
            assert claim is not None
            claims.append(claim)
            results[claim.job_kind] = execute_maintenance_runtime_claim(
                DATABASE_URL,
                runtime_jobs,
                claim,
                actor_id="maintenance-integration-worker",
            )
        self.assertEqual(set(results), set(MAINTENANCE_RUNTIME_JOB_KINDS))
        self.assertEqual(
            len({claim.runtime_job_id for claim in claims}),
            len(MAINTENANCE_RUNTIME_JOB_KINDS),
        )
        self.assertIn(
            lease_id,
            [
                item["lease_id"]
                for item in results["ATTEMPT_LEASE_EXPIRY_SCAN"][
                    "expired_attempt_leases"
                ]
            ],
        )
        recovered = next(
            item
            for item in results["OUTBOX_RECOVERY_SCAN"]["recovered_outbox"]
            if item["outbox_id"] == outbox_id
        )
        self.assertEqual(recovered["status"], "failed")
        self.assertEqual(recovered["fencing_token"], 1)
        self.assertIn(
            operation_id,
            results["OPERATION_DEADLINE_SCAN"]["cancellation_issued"],
        )
        self.assertEqual(
            results["EXTERNAL_EFFECT_RECONCILIATION_SCAN"]["external_effects_replayed"],
            0,
        )
        self.assertFalse(
            results["EXTERNAL_EFFECT_RECONCILIATION_SCAN"]["provider_query_proven"]
        )
        self.assertEqual(
            results["BOOK_OPENING_EXECUTION_LOSS_SCAN"][
                "book_opening_execution_losses"
            ],
            [],
        )
        self.assertEqual(
            results["BOOK_OPENING_EXECUTION_LOSS_SCAN"]["provider_invocations"],
            0,
        )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT COUNT(*), COUNT(*) FILTER (WHERE job.status='SUCCEEDED'),
                       COUNT(*) FILTER (
                           WHERE attempt.fencing_token > 0
                             AND lease.status='RELEASED'
                             AND EXISTS (
                                 SELECT 1 FROM authority_runtime_job_checkpoint AS checkpoint
                                 WHERE checkpoint.attempt_id=attempt.attempt_id
                             )
                       )
                FROM authority_runtime_job AS job
                JOIN authority_runtime_job_attempt AS attempt
                  ON attempt.attempt_id=job.current_attempt_id
                JOIN authority_runtime_job_lease AS lease
                  ON lease.attempt_id=attempt.attempt_id
                WHERE job.runtime_job_id=ANY(%s)
                """,
                [[item["runtime_job_id"] for item in scheduled]],
            )
            runtime_evidence = uow.cursor.fetchone()
        expected_runtime_job_count = len(MAINTENANCE_RUNTIME_JOB_KINDS)
        self.assertEqual(
            tuple(int(value) for value in runtime_evidence),
            (expected_runtime_job_count,) * 3,
        )


if __name__ == "__main__":
    unittest.main()
