from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.mobile_reading import create_mobile_reading_report
from novel_forge.schemas import DraftChapter, validate_common_fields
from novel_forge.storage.local import LocalStorage


class MobileReadingTests(unittest.TestCase):
    def test_mobile_friendly_paragraphs_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            text = "\n".join(
                [
                    "阿照停在官署门前，听见门内有人压低声音。",
                    "她没有退，反而把旧印塞进袖中，逼自己先确认账册。",
                    "“若账册被换，今晚就没有第二次机会。”她说。",
                    "黑手的马车停在巷口，灯影一晃，新的威胁逼近。",
                ]
                * 6
            )
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Chapter 6",
                    content={"chapter": 6, "text": text, "copyright_boundary": "test fixture original draft"},
                    metadata={"project_id": "mobile-p1", "workspace_path": "workspaces/mobile-p1"},
                ),
            )

            result = create_mobile_reading_report(storage, draft_path, workspace_path="workspaces/mobile-p1")
            report = result["asset"]

            self.assertEqual(validate_common_fields(report), [])
            self.assertEqual(report["type"], "mobile_reading_report")
            self.assertEqual(report["content"]["recommendation"], "passed")
            self.assertGreaterEqual(report["content"]["mobile_score"], 80)
            self.assertFalse(result["review_issues"])

    def test_dense_single_paragraph_blocks_and_creates_reflow_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            sentence = "阿照决定查明旧印，官署封存账册，黑手的威胁逼近，她承担问责代价并继续追问证人。"
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Chapter 7",
                    content={"chapter": 7, "text": sentence * 28, "copyright_boundary": "test fixture original draft"},
                    metadata={"project_id": "mobile-p1", "workspace_path": "workspaces/mobile-p1"},
                ),
            )

            result = create_mobile_reading_report(storage, draft_path, workspace_path="workspaces/mobile-p1")
            report = result["asset"]
            issue = storage.read_json(storage.root / result["review_issues"][0])
            task = storage.read_json(storage.root / result["revision_task_path"])

            self.assertEqual(result["status"], "blocked")
            self.assertEqual(report["content"]["recommendation"], "blocked")
            self.assertTrue(report["content"]["blocking"])
            self.assertEqual(issue["content"]["issue_type"], "mobile_reading_friction")
            self.assertTrue(issue["content"]["blocking"])
            self.assertEqual(task["content"]["revision_strategy_plan"]["strategy_ids"], ["mobile_paragraph_reflow"])


if __name__ == "__main__":
    unittest.main()
