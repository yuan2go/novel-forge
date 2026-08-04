from __future__ import annotations

import unittest

from novel_forge.modules.command_kernel.worker_execution import WorkerSupervisor
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


if __name__ == "__main__":
    unittest.main()
