from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.api.services import product as product_service
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules import mkaos
from novel_forge.modules.workflow_nodes.control import build_cancel_control_update, build_pause_control_update, normalize_workflow_control_action
from novel_forge.storage.local import LocalStorage


class UseCaseServiceSeamTests(unittest.TestCase):
    def test_product_task_control_facade_preserves_config_and_dead_letter_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = IndustrialSettings(root=Path(tmp).resolve())
            config = product_service.update_task_control(tmp, {"max_concurrent_batches": 4, "max_concurrent_steps": 2})
            status = product_service.task_control_status(settings)
            dead_letters = product_service.task_dead_letter_rows(tmp, limit=5)

            self.assertEqual(config["max_concurrent_batches"], 4)
            self.assertEqual(status["config"]["max_concurrent_steps"], 2)
            self.assertIn("celery", status)
            self.assertIn("scheduler", status)
            self.assertIn("dead_letters", status)
            self.assertIsInstance(dead_letters, list)

    def test_workflow_control_use_case_builds_pause_and_cancel_updates(self):
        content = {"status": "running", "blocked": {"node_id": "draft", "status": "waiting_human", "reason": "gate"}}

        paused = build_pause_control_update(content, reason="operator hold", operator="unit", next_node_id="review", terminal_statuses={"completed"})
        cancelled = build_cancel_control_update(content, reason="operator cancel", operator="unit")

        self.assertEqual(normalize_workflow_control_action(" Pause ", {"pause"}), "pause")
        self.assertEqual(paused["status"], "paused")
        self.assertEqual(paused["blocked"]["node_id"], "draft")
        self.assertEqual(paused["blocked"]["status"], "paused")
        self.assertEqual(paused["control"]["operator"], "unit")
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertTrue(cancelled["finish"])
        self.assertEqual(cancelled["blocked"]["reason"], "operator cancel")

    def test_mkaos_quality_query_use_case_preserves_low_and_risk_filters(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            low = mkaos.create_knowledge_card(
                storage,
                {
                    "title": "Low quality rule",
                    "discipline": "craft",
                    "summary": "Needs work",
                    "quality_score": 0.2,
                    "overall_quality_score": 0.2,
                    "project_id": "quality-p",
                },
            )
            risky = mkaos.create_knowledge_card(
                storage,
                {
                    "title": "High risk rule",
                    "discipline": "craft",
                    "summary": "Risky",
                    "risk_level": "high",
                    "quality_dimensions": {"copyright_risk_score": 0.9},
                    "project_id": "quality-p",
                },
            )

            lows = mkaos.list_low_quality_knowledge(storage, threshold=0.5, project_id="quality-p")
            high_risk = mkaos.list_high_copyright_risk_knowledge(storage, threshold=0.7, project_id="quality-p")

            self.assertIn(low["asset"]["id"], {row["id"] for row in lows})
            self.assertIn(risky["asset"]["id"], {row["id"] for row in high_risk})


if __name__ == "__main__":
    unittest.main()
