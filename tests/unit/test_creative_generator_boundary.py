from __future__ import annotations

import unittest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.creative.generator_boundary import build_candidate_pool


def candidate(index: int) -> dict:
    return {
        "candidate_id": f"candidate-{index}",
        "fingerprint": {
            "protagonist_advantage_mechanism": f"advantage-{index}",
            "conflict_loop": f"conflict-{index}", "growth_loop": f"growth-{index}",
            "reward_loop": f"reward-{index}", "information_asymmetry": f"info-{index}",
            "world_constraint": f"constraint-{index}", "relationship_engine": f"relation-{index}",
            "antagonist_response_pattern": f"response-{index}",
            "chapter_payoff_pattern": f"payoff-{index}",
        },
    }


class CreativeGeneratorBoundaryTests(unittest.TestCase):
    def test_structured_mechanism_distinct_pool_is_accepted(self) -> None:
        result = build_candidate_pool(
            project_id="project-1", creative_brief_asset_version_id="brief-v1",
            provider_receipt_asset_version_id="receipt-v1",
            receipt={"candidates": [candidate(1), candidate(2), candidate(3)], "fixture_protocol_only": True, "real_model_call": False},
        )
        self.assertEqual(result["mechanism_distinct_count"], 3)
        self.assertFalse(result["production_verified"])

    def test_surface_only_duplicates_are_rejected(self) -> None:
        duplicate = candidate(1)
        with self.assertRaisesRegex(KernelError, "superficially"):
            build_candidate_pool(
                project_id="project-1", creative_brief_asset_version_id="brief-v1",
                provider_receipt_asset_version_id="receipt-v1",
                receipt={"candidates": [{**duplicate, "candidate_id": value} for value in ("a", "b", "c")]},
            )


if __name__ == "__main__":
    unittest.main()
