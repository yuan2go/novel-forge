from tests.unit.mkaos_p1_helpers import MkaosP1TestCase
from novel_forge.modules import mkaos


class MkaosLongitudinalLearningTests(MkaosP1TestCase):
    def test_longitudinal_learning_aggregates_quality_reader_and_platform_metrics(self):
        seeded = self.seed_knowledge_system()
        good_id = seeded["history"]["asset"]["id"]
        risky_id = seeded["risky"]["asset"]["id"]
        before = {
            row["id"]: row["content"]["weight"]
            for row in mkaos.list_knowledge_cards(self.storage, project_id=self.project_id, include_deprecated=True)
            if row["id"] in {good_id, risky_id}
        }

        report = mkaos.run_longitudinal_knowledge_effect_learning(
            self.storage,
            {
                "project_id": self.project_id,
                "flow": "prose",
                "apply_updates": True,
                "observations": [
                    {"chapter_id": "1", "knowledge_ids": [good_id], "quality_score": 86, "review_score": 90, "completion_rate": 0.82, "retention_rate": 0.76, "platform": "qidian", "genre": "历史", "reader_rating": 5},
                    {"chapter_id": "2", "knowledge_ids": [good_id], "quality_score": 88, "review_score": 86, "completion_rate": 0.8, "retention_rate": 0.74, "platform": "qidian", "genre": "历史", "reader_rating": 4.5},
                    {"chapter_id": "3", "knowledge_ids": [risky_id], "quality_score": 42, "review_score": 40, "completion_rate": 0.3, "retention_rate": 0.22, "platform": "fanqie", "genre": "历史", "reader_rating": 1, "issue_tags": ["source_leakage"]},
                    {"chapter_id": "4", "knowledge_ids": [risky_id], "quality_score": 45, "review_score": 35, "completion_rate": 0.28, "retention_rate": 0.2, "platform": "fanqie", "genre": "历史", "reader_rating": 1.5, "issue_tags": ["anti_encyclopedia"]},
                ],
            },
        )["data"]

        actions = {item["knowledge_id"]: item["recommended_action"] for item in report["learning_items"]}
        self.assertEqual(actions[good_id], "boost")
        self.assertEqual(actions[risky_id], "quarantine")
        self.assertEqual(report["source_metrics"]["chapter_count"], 4)
        self.assertEqual(len(report["generated_usage_event_ids"]), 4)
        self.assertFalse(report["source_isolation"]["raw_text_included"])

        after = {
            row["id"]: row["content"]["weight"]
            for row in mkaos.list_knowledge_cards(self.storage, project_id=self.project_id, include_deprecated=True)
            if row["id"] in {good_id, risky_id}
        }
        self.assertGreater(after[good_id], before[good_id])
        self.assertLess(after[risky_id], before[risky_id])
