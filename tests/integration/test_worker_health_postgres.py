from __future__ import annotations

import unittest

from novel_forge.modules.command_kernel.worker_execution import WorkerSupervisor
from novel_forge.modules.runtime_job import RuntimeJobAuthority, RuntimeJobSpec
from novel_forge.storage.worker_health import PostgresWorkerHealthObserver, runtime_health_report
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated, identifier


class WorkerHealthPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_supervisor_health_survives_process_local_observer_lifetime(self) -> None:
        worker_id = identifier("health-worker")
        supervisor = WorkerSupervisor(
            worker_kind="content", worker_id=worker_id,
            observer=PostgresWorkerHealthObserver(DATABASE_URL),
        )
        supervisor.polled(idle=True)
        supervisor.operation_started("health-operation")
        report = runtime_health_report(DATABASE_URL)
        worker = next(item for item in report["workers"] if item["worker_id"] == worker_id)
        self.assertEqual(worker["status"], "BUSY")
        self.assertEqual(worker["active_operation_id"], "health-operation")
        self.assertEqual(worker["completed_operation_count"], 0)
        supervisor.operation_finished("health-operation", succeeded=True)
        supervisor.batch_completed(())
        report = runtime_health_report(DATABASE_URL)
        worker = next(item for item in report["workers"] if item["worker_id"] == worker_id)
        self.assertIsNone(worker["active_operation_id"])
        self.assertEqual(worker["completed_operation_count"], 1)
        self.assertEqual(worker["completed_batch_count"], 1)
        self.assertTrue(worker["fresh"])
        self.assertIn("outbox_lag", report)
        self.assertIn("unknown_effect_count", report)

    def test_runtime_job_fence_database_status_and_fleet_metrics_are_projected(
        self,
    ) -> None:
        worker_id = identifier("runtime-health-worker")
        runtime_jobs = RuntimeJobAuthority(DATABASE_URL)
        scheduled = runtime_jobs.schedule(
            RuntimeJobSpec(
                job_kind="OPERATION_DEADLINE_SCAN",
                runtime_group="maintenance",
                subject_kind="AUTHORITY_MAINTENANCE_SCAN",
                subject_id=identifier("health-scan"),
                project_id="",
                dedupe_key=identifier("health-dedupe"),
                input_snapshot={"batch_limit": 1},
            )
        )
        claim = runtime_jobs.claim(
            runtime_group="maintenance",
            worker_id=worker_id,
            lease_seconds=30,
            job_kinds=("OPERATION_DEADLINE_SCAN",),
            subject_kind="AUTHORITY_MAINTENANCE_SCAN",
            subject_id=runtime_jobs.get(scheduled["runtime_job_id"])["subject_id"],
        )
        assert claim is not None
        supervisor = WorkerSupervisor(
            worker_kind="maintenance",
            worker_id=worker_id,
            observer=PostgresWorkerHealthObserver(DATABASE_URL),
        )
        supervisor.operation_started(claim.runtime_job_id)
        report = runtime_health_report(DATABASE_URL)
        worker = next(item for item in report["workers"] if item["worker_id"] == worker_id)
        self.assertEqual(worker["active_runtime_job_id"], claim.runtime_job_id)
        self.assertEqual(worker["active_attempt_id"], claim.attempt_id)
        self.assertEqual(worker["fencing_token"], claim.fencing_token)
        self.assertEqual(worker["database_status"], "READY")
        self.assertIsNotNone(worker["last_database_success_at"])
        self.assertIn("fleet_metrics", report)
        self.assertLessEqual(
            {
                "pool_size",
                "pool_in_use",
                "transaction_count",
                "runtime_job_backlog",
                "outbox_backlog",
                "unknown_effect_backlog",
                "stale_worker_count",
            },
            report["fleet_metrics"].keys(),
        )
        runtime_jobs.start(claim)
        runtime_jobs.complete(claim, {"status": "observed"})
        supervisor.operation_finished(claim.runtime_job_id, succeeded=True)


if __name__ == "__main__":
    unittest.main()
