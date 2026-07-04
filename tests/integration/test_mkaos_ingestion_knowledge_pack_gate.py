from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.mkaos_quality import gate_knowledge_pack
from novel_forge.modules.review_issue import list_review_issues
from novel_forge.storage.local import LocalStorage


class MkaosIngestionKnowledgePackGateTests(unittest.TestCase):
    def test_pack_gate_blocks_parallel_pair_text_in_production(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()

            with self.assertRaisesRegex(ValueError, "blocked production"):
                gate_knowledge_pack(
                    storage,
                    {
                        "project_id": "pack-gate",
                        "environment": "production",
                        "flow": "publish",
                        "knowledge_pack": {"content": {"pack_items": [{"knowledge_id": "k", "target_text": "译文原文"}]}},
                    },
                )

            issues = list_review_issues(storage, project_id="pack-gate", blocking=True)
            self.assertTrue(issues)
            self.assertEqual(issues[0]["content"]["issue_type"], "source_leakage")

    def test_pack_gate_allows_abstract_pack(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()

            result = gate_knowledge_pack(storage, {"project_id": "pack-gate", "flow": "publish", "knowledge_pack": {"content": {"pack_items": [{"knowledge_id": "k", "creative_principle": "abstract only"}]}}})

            self.assertTrue(result["passed"])


if __name__ == "__main__":
    unittest.main()
