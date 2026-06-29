from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.feedback_backflow import apply_feedback_backflow_plan, create_feedback_backflow_plan
from novel_forge.schemas import ReaderFeedback, validate_common_fields
from novel_forge.storage.local import LocalStorage


class FeedbackBackflowTests(unittest.TestCase):
    def test_feedback_creates_human_gated_plan_rule_and_kg_proposals(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            project_id = "feedback-project"
            feedback_path = storage.write_asset_auto(
                ReaderFeedback(
                    title="Reader feedback",
                    content={
                        "rows": [
                            {"chapter": 1, "comment": "The ending hook is weak and not exciting enough."},
                            {"chapter": 2, "comment": "The cultivation rule is confusing and hard to understand."},
                        ]
                    },
                    metadata={"project_id": project_id},
                )
            )

            result = create_feedback_backflow_plan(storage, feedback_paths=[str(feedback_path.relative_to(storage.root))], project_id=project_id)

            self.assertEqual(validate_common_fields(result["asset"]), [])
            proposal_types = {item["asset"]["type"] for item in result["proposals"]}
            self.assertIn("plan_adjustment_proposal", proposal_types)
            self.assertIn("review_rule_update_proposal", proposal_types)
            self.assertIn("feedback_kg_patch", proposal_types)
            self.assertEqual(result["asset"]["content"]["status"], "waiting_human")
            for proposal in result["proposals"]:
                self.assertTrue(proposal["asset"]["content"]["human_gate"]["required"])

            waiting = apply_feedback_backflow_plan(storage, plan_path=result["path"], confirmed=False)
            self.assertEqual(waiting["status"], "waiting_human")

            approved = apply_feedback_backflow_plan(storage, plan_path=result["path"], confirmed=True, note="approved for workflow apply nodes")
            self.assertEqual(approved["status"], "approved")
            updated = storage.read_json(result["path"])
            self.assertEqual(updated["content"]["human_gate"]["status"], "approved")


if __name__ == "__main__":
    unittest.main()

