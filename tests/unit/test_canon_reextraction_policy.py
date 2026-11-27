from __future__ import annotations

from decimal import Decimal
import unittest

from novel_forge.modules.canon_graph.reextraction_policy import CanonReextractionPolicy
from novel_forge.modules.command_kernel.errors import KernelError


class CanonReextractionPolicyTests(unittest.TestCase):
    def test_policy_snapshot_is_versioned_and_bounded(self) -> None:
        policy = CanonReextractionPolicy(maximum_total_cost=Decimal("2.50"))
        snapshot = policy.snapshot()
        self.assertEqual(snapshot["policy_version"], "canon-reextraction-policy-v2")
        self.assertEqual(snapshot["maximum_total_cost"], "2.50")
        policy.require_generation(3)
        self.assertIsNone(snapshot["maximum_generations"])
        self.assertIsNone(snapshot["generation_timeout_seconds"])

    def test_historical_generation_cap_does_not_block_new_authorized_work(self) -> None:
        policy = CanonReextractionPolicy(maximum_generations=2)
        policy.require_generation(100)
        self.assertEqual(policy.snapshot()["maximum_generations"], 2)
        with self.assertRaisesRegex(KernelError, "append-only generation identity"):
            policy.require_generation(1)

    def test_invalid_policy_is_rejected(self) -> None:
        with self.assertRaisesRegex(KernelError, "invalid bound"):
            CanonReextractionPolicy(no_progress_limit=0).validate()


if __name__ == "__main__":
    unittest.main()
