from tests.unit.mkaos_p1_helpers import MkaosP1TestCase
from novel_forge.modules import mkaos


class MkaosSelectorV2Tests(MkaosP1TestCase):
    def test_task_goal_platform_genre_and_budget_drive_selection(self):
        seeded = self.seed_knowledge_system()
        pack = mkaos.build_knowledge_pack(
            self.storage,
            {
                "project_id": self.project_id,
                "flow": "prose",
                "task_id": "selector-v2",
                "task_goal": "悬疑 公平证据链",
                "genre": "悬疑",
                "platform": "zhihu_yanxuan",
                "source_policy": {"exclude_high_risk": True},
                "knowledge_budget": {"max_core_knowledge": 1, "max_optional_knowledge": 1, "max_estimated_tokens": 120},
            },
        )
        content = pack["asset"]["content"]
        selected_ids = {item["knowledge_id"] for item in content["pack_items"]}
        rejected_ids = {item["knowledge_id"] for item in content["selector_rejections"]}
        self.assertIn(seeded["mystery"]["asset"]["id"], selected_ids)
        self.assertIn(seeded["risky"]["asset"]["id"], rejected_ids)
        self.assertTrue(content["selector_decision_id"])
        self.assertEqual(content["selector_policy"]["selector_policy_version"], "selector-v2")

    def test_fallback_mode_is_recorded_when_task_goal_missing(self):
        self.seed_knowledge_system()
        pack = mkaos.build_knowledge_pack(self.storage, {"project_id": self.project_id, "flow": "outline", "task_id": "fallback"})
        self.assertEqual(pack["asset"]["content"]["selector_policy"]["selector_mode"], "fallback")
        self.assertEqual(pack["asset"]["content"]["selector_policy"]["fallback_reason"], "task_goal_missing")

    def test_quarantined_is_never_selected_in_production(self):
        seeded = self.seed_knowledge_system()
        mkaos.change_knowledge_status(self.storage, seeded["history"]["asset"]["id"], {"status": "quarantined"})
        pack = mkaos.build_knowledge_pack(
            self.storage,
            {
                "project_id": self.project_id,
                "flow": "outline",
                "task_id": "quarantine",
                "environment": "production",
                "source_policy": {"exclude_high_risk": True},
                "os_envelope": {"envelope_id": "env", "trace_id": "trace", "environment": "production", "project_id": self.project_id},
            },
        )
        self.assertNotIn(seeded["history"]["asset"]["id"], {item["knowledge_id"] for item in pack["asset"]["content"]["pack_items"]})
