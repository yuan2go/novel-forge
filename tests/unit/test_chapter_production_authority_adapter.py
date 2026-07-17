from __future__ import annotations

import unittest

from novel_forge.modules.chapter_production_bus.authority_adapter import (
    ChapterProductionAuthorityAdapter,
)


class ChapterProductionAuthorityAdapterTests(unittest.TestCase):
    def test_projection_is_explicitly_non_authoritative_and_rebuildable(self) -> None:
        projection = ChapterProductionAuthorityAdapter.project(
            {
                "project_id": "project-a",
                "root_operation_id": "root-1",
                "status": "SUCCEEDED",
                "saga": {"status": "SUCCEEDED"},
                "operations": [
                    {"operation_id": "root-1", "definition_name": "chapter.slice.run", "status": "SUCCEEDED"},
                    {"operation_id": "op-1", "definition_name": "chapter.plan.materialize", "status": "SUCCEEDED"},
                ],
                "primary_outputs": [
                    {"operation_id": "op-1", "asset_version_id": "plan-v1"}
                ],
                "model_effects": [],
            }
        )
        self.assertFalse(projection["authoritative"])
        self.assertTrue(projection["rebuildable"])
        self.assertEqual(projection["steps"][0]["output"]["asset_version_id"], "plan-v1")


if __name__ == "__main__":
    unittest.main()
