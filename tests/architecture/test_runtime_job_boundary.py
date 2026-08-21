from __future__ import annotations

from pathlib import Path
import unittest

from novel_forge.modules.runtime_job import OPERATIONAL_RUNTIME_JOB_CONTRACTS


ROOT = Path(__file__).resolve().parents[2]


class RuntimeJobBoundaryTests(unittest.TestCase):
    def test_runtime_job_is_closed_to_operational_ticks_and_scans(self) -> None:
        self.assertEqual(
            set(OPERATIONAL_RUNTIME_JOB_CONTRACTS),
            {
                "BOOK_COORDINATION_TICK",
                "BOOK_FOLLOWUP_ADMISSION",
                "BOOK_PROJECTION_REPAIR",
                "OPERATION_DEADLINE_SCAN",
                "ATTEMPT_LEASE_EXPIRY_SCAN",
                "OUTBOX_RECOVERY_SCAN",
                "EXTERNAL_EFFECT_RECONCILIATION_SCAN",
            },
        )
        self.assertEqual(
            OPERATIONAL_RUNTIME_JOB_CONTRACTS["BOOK_FOLLOWUP_ADMISSION"],
            ("book_followup", "CHAPTER_ACCEPTANCE"),
        )

    def test_runtime_job_does_not_own_business_attempts_or_effects(self) -> None:
        source = (
            ROOT / "src/novel_forge/modules/runtime_job/application.py"
        ).read_text(encoding="utf-8")
        for forbidden in (
            "command_kernel.attempt_runtime",
            "command_kernel.external_effect_runtime",
            "provider_control",
            "AuthorityAssetWriter",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
