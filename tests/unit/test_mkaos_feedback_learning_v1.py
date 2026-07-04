from tests.unit.mkaos_p1_helpers import MkaosP1TestCase
from novel_forge.modules import mkaos


class MkaosFeedbackLearningV1Tests(MkaosP1TestCase):
    def test_learning_generates_recommendations_without_auto_update(self):
        seeded = self.seed_knowledge_system()
        kid = seeded["history"]["asset"]["id"]
        mkaos.record_usage_event(self.storage, {"project_id": self.project_id, "knowledge_id": kid, "knowledge_pack_id": "pack", "flow": "prose", "agent_name": "DraftAgent", "used_as": "constraint", "effect_score": 0.9})
        before = seeded["history"]["asset"]["content"]["weight"]
        snapshot = mkaos.learn_from_knowledge_effects(self.storage, {"project_id": self.project_id, "flow": "prose", "apply_updates": False})
        after = next(row for row in mkaos.list_knowledge_cards(self.storage, project_id=self.project_id) if row["id"] == kid)["content"]["weight"]
        self.assertTrue(snapshot["data"]["recommendations"])
        self.assertEqual(before, after)
        self.assertFalse(snapshot["data"]["source_isolation"]["raw_source_text_included"])

    def test_apply_updates_changes_weight_and_leaves_trace(self):
        seeded = self.seed_knowledge_system()
        kid = seeded["history"]["asset"]["id"]
        mkaos.record_review_feedback(self.storage, {"project_id": self.project_id, "knowledge_id": kid, "flow": "prose", "conflict_effective": True})
        snapshot = mkaos.learn_from_knowledge_effects(self.storage, {"project_id": self.project_id, "flow": "prose", "apply_updates": True, "min_apply_delta": 0.01})
        self.assertTrue(snapshot["data"]["applied_updates"])
        self.assertTrue(mkaos.knowledge_quality_history(self.storage, kid)["items"])
