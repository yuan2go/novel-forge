from tests.unit.mkaos_p1_helpers import MkaosP1TestCase
from novel_forge.modules import mkaos


class MkaosKnowledgeEvolutionTests(MkaosP1TestCase):
    def test_evolution_cycle_generates_graph_learning_rules_templates_and_elimination(self):
        seeded = self.seed_knowledge_system()
        history_id = seeded["history"]["asset"]["id"]
        risky_id = seeded["risky"]["asset"]["id"]
        mkaos.record_usage_event(
            self.storage,
            {
                "project_id": self.project_id,
                "knowledge_id": history_id,
                "knowledge_pack_id": "pack-hot",
                "flow": "prose",
                "agent_name": "DraftAgent",
                "used_as": "constraint",
                "effect_score": 0.95,
                "reader_feedback": {"sentiment": "positive", "rating": 5},
            },
        )
        for index in range(3):
            mkaos.record_usage_event(
                self.storage,
                {
                    "project_id": self.project_id,
                    "knowledge_id": risky_id,
                    "knowledge_pack_id": "pack-risk",
                    "flow": "prose",
                    "agent_name": "DraftAgent",
                    "used_as": "constraint",
                    "effect_score": 0.05,
                    "reader_feedback": {"sentiment": "negative", "rating": 1},
                    "target_artifact_id": f"draft-{index}",
                },
            )
        mkaos.attribute_reader_feedback_to_knowledge(
            self.storage,
            {
                "project_id": self.project_id,
                "feedback_text": "设定太多，节奏慢，像 AI",
                "candidate_knowledge_ids": [risky_id],
                "knowledge_pack_id": "pack-risk",
            },
        )

        report = mkaos.run_knowledge_evolution_cycle(
            self.storage,
            {
                "project_id": self.project_id,
                "flow": "prose",
                "hot_deconstruction_templates": [
                    {
                        "pattern_name": "强钩子拆解",
                        "flow": "chapter_outline",
                        "platform": "fanqie",
                        "genre": "历史",
                        "template_structure": {"beats": ["hook", "pressure", "reversal", "payoff"]},
                    }
                ],
            },
        )
        data = report["data"]
        self.assertTrue(data["graph_snapshot"]["summary"]["node_count"])
        self.assertGreaterEqual(data["learning_snapshot"]["recommendation_count"], 1)
        self.assertTrue(data["review_rule_evolution"]["candidates"])
        self.assertTrue(data["hot_template_backflow"]["candidates"])
        self.assertTrue(data["reader_feedback_backflow"]["top_tags"])
        self.assertTrue(data["low_effect_elimination"]["recommendations"])
        self.assertFalse(data["source_isolation"]["raw_text_included"])
        self.assertEqual(data["governance_policy"]["default_mode"], "advisory")

    def test_evolution_cycle_can_apply_low_effect_status_update_explicitly(self):
        seeded = self.seed_knowledge_system()
        risky_id = seeded["risky"]["asset"]["id"]
        for index in range(3):
            mkaos.record_usage_event(
                self.storage,
                {
                    "project_id": self.project_id,
                    "knowledge_id": risky_id,
                    "knowledge_pack_id": "pack-risk",
                    "flow": "prose",
                    "agent_name": "DraftAgent",
                    "used_as": "constraint",
                    "effect_score": 0.05,
                    "target_artifact_id": f"draft-{index}",
                },
            )

        report = mkaos.run_knowledge_evolution_cycle(
            self.storage,
            {"project_id": self.project_id, "flow": "prose", "apply_elimination": True},
        )

        self.assertTrue(report["data"]["low_effect_elimination"]["applied"])
        updated = next(row for row in mkaos.list_knowledge_cards(self.storage, project_id=self.project_id, include_deprecated=True) if row["id"] == risky_id)
        self.assertIn(updated["content"]["status"], {"needs_review", "quarantined"})

    def test_guarded_auto_policy_promotes_safe_assets_and_quarantines_repeated_failures(self):
        seeded = self.seed_knowledge_system()
        history_id = seeded["history"]["asset"]["id"]
        risky_id = seeded["risky"]["asset"]["id"]
        for index in range(2):
            mkaos.record_usage_event(
                self.storage,
                {
                    "project_id": self.project_id,
                    "knowledge_id": history_id,
                    "knowledge_pack_id": "pack-hot",
                    "flow": "prose",
                    "agent_name": "DraftAgent",
                    "used_as": "constraint",
                    "effect_score": 0.9,
                    "target_artifact_id": f"good-{index}",
                },
            )
        for index in range(3):
            mkaos.record_usage_event(
                self.storage,
                {
                    "project_id": self.project_id,
                    "knowledge_id": risky_id,
                    "knowledge_pack_id": "pack-risk",
                    "flow": "prose",
                    "agent_name": "DraftAgent",
                    "used_as": "constraint",
                    "effect_score": 0.05,
                    "reader_feedback": {"sentiment": "negative", "rating": 1},
                    "target_artifact_id": f"bad-{index}",
                },
            )
        mkaos.attribute_reader_feedback_to_knowledge(
            self.storage,
            {"project_id": self.project_id, "feedback_text": "设定太多，节奏慢", "candidate_knowledge_ids": [risky_id]},
        )

        report = mkaos.run_knowledge_evolution_cycle(
            self.storage,
            {"project_id": self.project_id, "flow": "prose", "evolution_mode": "guarded_auto"},
        )["data"]

        self.assertEqual(report["governance_policy"]["evolution_mode"], "guarded_auto")
        self.assertTrue(report["review_rule_evolution"]["applied"])
        self.assertTrue(report["hot_template_backflow"]["applied"])
        self.assertTrue(report["low_effect_elimination"]["applied"])
        updated = next(row for row in mkaos.list_knowledge_cards(self.storage, project_id=self.project_id, include_deprecated=True) if row["id"] == risky_id)
        self.assertEqual(updated["content"]["status"], "quarantined")
