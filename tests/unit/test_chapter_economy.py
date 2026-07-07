from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.chapter_economy import create_chapter_economy_report
from novel_forge.modules.longform_stability import create_reward_ledger
from novel_forge.schemas import DraftChapter, validate_common_fields
from novel_forge.storage.local import LocalStorage


class ChapterEconomyTests(unittest.TestCase):
    def test_high_value_chapter_economy_passes_and_writes_pleasure_points(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Chapter 2",
                    content={
                        "chapter": 2,
                        "text": "阿照决定当众查明旧印。官署封存账册，她却逼证人开口，证明纸页线索。她保住证据，也承责付出代价，结尾发现真正威胁逼近。",
                        "chapter_plan_blueprint": {
                            "pleasure_beats": ["查明旧印", "保住证据", "承责付出代价"],
                            "payoff_target": {"local_payoff": "proof becomes visible"},
                        },
                        "copyright_boundary": "test fixture original draft",
                    },
                    metadata={"project_id": "economy-p1", "workspace_path": "workspaces/economy-p1"},
                ),
            )
            reward = create_reward_ledger(storage, draft_path, workspace_path="workspaces/economy-p1")

            result = create_chapter_economy_report(
                storage,
                draft_path,
                reward_ledger_path=reward["path"],
                workspace_path="workspaces/economy-p1",
            )
            report = result["asset"]

            self.assertEqual(validate_common_fields(report), [])
            self.assertEqual(report["type"], "chapter_economy_report")
            self.assertEqual(report["content"]["recommendation"], "passed")
            self.assertGreaterEqual(report["content"]["scene_value_score"], 70)
            self.assertTrue(result["pleasure_point_paths"])
            point = storage.read_json(storage.root / result["pleasure_point_paths"][0])
            self.assertEqual(validate_common_fields(point), [])
            self.assertEqual(point["type"], "pleasure_point")

    def test_low_value_chapter_economy_creates_review_issue_and_revision_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Chapter 3",
                    content={
                        "chapter": 3,
                        "text": "其实这件事可以说非常复杂。总之大家都知道局势很复杂。换句话说，事情并不简单。也就是说，所有人都需要思考。显然，这是一段没有行动、没有代价、没有线索推进的解释。" * 4,
                        "chapter_plan_blueprint": {"pleasure_beats": ["public choice with visible cost", "new clue changes direction"]},
                        "copyright_boundary": "test fixture original draft",
                    },
                    metadata={"project_id": "economy-p1", "workspace_path": "workspaces/economy-p1"},
                ),
            )

            result = create_chapter_economy_report(storage, draft_path, workspace_path="workspaces/economy-p1")
            report = result["asset"]

            self.assertEqual(report["content"]["recommendation"], "blocked")
            self.assertTrue(report["content"]["blocking"])
            self.assertTrue(result["review_issues"])
            self.assertTrue(result["revision_task_path"])
            issue = storage.read_json(storage.root / result["review_issues"][0])
            task = storage.read_json(storage.root / result["revision_task_path"])
            self.assertEqual(issue["content"]["issue_type"], "chapter_economy_gap")
            self.assertTrue(issue["content"]["blocking"])
            self.assertEqual(task["content"]["revision_strategy_plan"]["strategy_ids"], ["raise_chapter_economy"])


if __name__ == "__main__":
    unittest.main()
