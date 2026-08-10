from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.tools.worker_fleet_evidence import (
    WORKER_SCENARIOS,
    build_worker_fleet_summary,
    validate_worker_evidence,
)


SHA = "a" * 40


def _evidence(worker: str) -> dict[str, object]:
    return {
        "worker": worker,
        "scenario": f"{worker} authority execution and recovery",
        "commit_sha": SHA,
        "runtime_group": f"{worker}-authority",
        "worker_id": f"{worker}-worker-1",
        "work_id": f"work:{worker}",
        "attempt_or_job_id": f"attempt:{worker}",
        "lease_id": f"lease:{worker}",
        "fencing_token": 2,
        "checkpoint": "RECOVERED",
        "restart": True,
        "recovery": True,
        "stale_rejection": True,
        "graceful_drain": True,
        "zero_leaked_connections": True,
        "fixture": True,
        "real_provider_proven": False,
        "production_verified": False,
        "result": "PASS",
    }


class WorkerFleetEvidenceTests(unittest.TestCase):
    def test_fixture_mkaos_activation_is_explicit_and_forbidden_in_production(self) -> None:
        with TemporaryDirectory() as root:
            settings = IndustrialSettings.from_env(
                {
                    "NOVEL_FORGE_ENVIRONMENT": "test",
                    "NOVEL_FORGE_MKAOS_ALLOW_FIXTURE_ACTIVATION": "true",
                },
                root=Path(root),
            )
            self.assertTrue(settings.mkaos_fixture_activation_enabled)
            with self.assertRaisesRegex(ValueError, "controlled runtime forbids"):
                IndustrialSettings(
                    root=Path(root),
                    environment="production",
                    mkaos_fixture_activation_enabled=True,
                )

    def test_summary_requires_all_seven_sha_bound_scenarios(self) -> None:
        summary = build_worker_fleet_summary(
            (_evidence(worker) for worker in WORKER_SCENARIOS), commit_sha=SHA
        )
        self.assertTrue(summary["worker_fleet_e2e_proven"])
        self.assertEqual(summary["worker_count"], 7)
        self.assertFalse(summary["real_provider_proven"])

    def test_health_only_or_single_fence_evidence_is_rejected(self) -> None:
        health_only = _evidence("chapter")
        health_only["work_id"] = ""
        with self.assertRaisesRegex(ValueError, "work_id"):
            validate_worker_evidence(health_only)
        unfenced = _evidence("chapter")
        unfenced["fencing_token"] = 1
        with self.assertRaisesRegex(ValueError, "higher fencing token"):
            validate_worker_evidence(unfenced)

    def test_missing_duplicate_and_wrong_sha_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing"):
            build_worker_fleet_summary(
                (_evidence(worker) for worker in WORKER_SCENARIOS[:-1]),
                commit_sha=SHA,
            )
        duplicated = [_evidence(worker) for worker in WORKER_SCENARIOS]
        duplicated[-1] = _evidence("chapter")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            build_worker_fleet_summary(duplicated, commit_sha=SHA)
        wrong_sha = _evidence("chapter")
        wrong_sha["commit_sha"] = "b" * 40
        with self.assertRaisesRegex(ValueError, "another Git SHA"):
            validate_worker_evidence(wrong_sha, expected_sha=SHA)


if __name__ == "__main__":
    unittest.main()
