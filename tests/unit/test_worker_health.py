from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from novel_forge.storage.worker_health import derive_worker_database_status


class WorkerDatabaseHealthDerivationTests(unittest.TestCase):
    def test_status_is_derived_from_probe_success_failure_and_freshness(self) -> None:
        now = datetime.now(timezone.utc)
        self.assertEqual(
            derive_worker_database_status(
                fresh=False,
                last_database_success_at=now,
                last_database_failure_at=None,
                now=now,
            ),
            "UNAVAILABLE",
        )
        self.assertEqual(
            derive_worker_database_status(
                fresh=True,
                last_database_success_at=None,
                last_database_failure_at=None,
                now=now,
            ),
            "UNKNOWN",
        )
        failure = now - timedelta(seconds=10)
        self.assertEqual(
            derive_worker_database_status(
                fresh=True,
                last_database_success_at=now,
                last_database_failure_at=failure,
                now=now,
            ),
            "DEGRADED",
        )
        self.assertEqual(
            derive_worker_database_status(
                fresh=True,
                last_database_success_at=failure - timedelta(seconds=1),
                last_database_failure_at=failure,
                now=now,
            ),
            "UNAVAILABLE",
        )
        self.assertEqual(
            derive_worker_database_status(
                fresh=True,
                last_database_success_at=now,
                last_database_failure_at=now - timedelta(minutes=10),
                now=now,
            ),
            "READY",
        )


if __name__ == "__main__":
    unittest.main()
