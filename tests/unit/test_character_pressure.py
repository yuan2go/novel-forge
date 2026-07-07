from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.character_pressure import create_character_pressure_reports
from novel_forge.schemas import DraftChapter, validate_common_fields
from novel_forge.storage.local import LocalStorage


class CharacterPressureTests(unittest.TestCase):
    def test_visible_agency_and_pressure_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Chapter 4",
                    content={
                        "chapter": 4,
                        "text": "阿照决定当众查明旧印，逼官署交出封存账册。她保住证据，承担问责代价。黑手的威胁逼近，她仍选择把线索交到灯下。",
                        "chapter_plan_blueprint": {"core_conflict": "institutional pressure exposes the protagonist choice"},
                        "copyright_boundary": "test fixture original draft",
                    },
                    metadata={"project_id": "pressure-p1", "workspace_path": "workspaces/pressure-p1"},
                ),
            )

            result = create_character_pressure_reports(storage, draft_path, workspace_path="workspaces/pressure-p1")
            protagonist = result["protagonist_charm_report"]
            antagonist = result["antagonist_pressure_report"]

            self.assertEqual(validate_common_fields(protagonist), [])
            self.assertEqual(validate_common_fields(antagonist), [])
            self.assertEqual(protagonist["type"], "protagonist_charm_report")
            self.assertEqual(antagonist["type"], "antagonist_pressure_report")
            self.assertEqual(protagonist["content"]["recommendation"], "passed")
            self.assertEqual(antagonist["content"]["recommendation"], "passed")
            self.assertGreaterEqual(protagonist["content"]["agency_score"], 60)
            self.assertGreaterEqual(antagonist["content"]["pressure_score"], 58)
            self.assertFalse(result["review_issues"])

    def test_weak_agency_and_pressure_creates_review_issues_and_revision_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Chapter 5",
                    content={
                        "chapter": 5,
                        "text": "他想了很久，大家都觉得情况复杂。事情很多，但没人作出选择，也没有新的阻碍。屋里很安静，结尾仍在解释局势。" * 3,
                        "chapter_plan_blueprint": {"core_conflict": "fixture intentionally lacks action pressure"},
                        "copyright_boundary": "test fixture original draft",
                    },
                    metadata={"project_id": "pressure-p1", "workspace_path": "workspaces/pressure-p1"},
                ),
            )

            result = create_character_pressure_reports(storage, draft_path, workspace_path="workspaces/pressure-p1")
            issue_types = {
                storage.read_json(storage.root / issue_path)["content"]["issue_type"]
                for issue_path in result["review_issues"]
            }
            task = storage.read_json(storage.root / result["revision_task_path"])

            self.assertEqual(result["status"], "blocked")
            self.assertIn("protagonist_charm_drop", issue_types)
            self.assertIn("antagonist_pressure_drop", issue_types)
            self.assertEqual(task["content"]["revision_strategy_plan"]["strategy_ids"], ["restore_character_charm_pressure"])


if __name__ == "__main__":
    unittest.main()
