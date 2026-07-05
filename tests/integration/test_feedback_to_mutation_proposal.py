from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.publishing_feedback_adapters import cluster_platform_comments, create_feedback_mutation_proposal
from novel_forge.storage.local import LocalStorage


class FeedbackMutationProposalIntegrationTests(unittest.TestCase):
    def test_feedback_clusters_create_human_gated_mutation_proposal_without_silent_plan_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            cluster = cluster_platform_comments(
                storage,
                platform_id="manual",
                comments=[
                    {"text": "第二章节奏太慢，看到这里想弃书", "characters": ["主角"]},
                    {"text": "反转好看，期待下一章", "characters": ["主角", "侦探"]},
                ],
            )
            proposal = create_feedback_mutation_proposal(
                storage,
                source_feedback_paths=[cluster["report_path"]],
                target_assets=[{"asset_type": "outline", "path": "data/outlines/outline.json"}],
                proposed_changes=[{"domain": "outline", "action": "tighten_chapter_2_hook"}],
            )

            self.assertTrue(cluster["asset"]["content"]["dropoff_reasons"])
            self.assertEqual(proposal["asset"]["type"], "feedback_plan_mutation_proposal")
            self.assertEqual(proposal["asset"]["content"]["human_gate"]["status"], "pending")
            self.assertFalse(proposal["asset"]["content"]["risk_assessment"]["silent_mutation_allowed"])


if __name__ == "__main__":
    unittest.main()
