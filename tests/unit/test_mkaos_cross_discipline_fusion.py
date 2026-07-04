from tests.unit.mkaos_p1_helpers import MkaosP1TestCase
from novel_forge.modules import mkaos


class MkaosCrossDisciplineFusionTests(MkaosP1TestCase):
    def test_fusion_outputs_abstract_application_without_raw_text(self):
        seeded = self.seed_knowledge_system()
        result = mkaos.create_cross_discipline_fusion_path(
            self.storage,
            {
                "project_id": self.project_id,
                "flow": "prose",
                "task_goal": "历史制度 + 叙事冲突 + 心理压力",
                "genre": "历史",
                "selected_knowledge_ids": [seeded["history"]["asset"]["id"], seeded["mystery"]["asset"]["id"]],
                "persist": True,
            },
        )
        self.assertTrue(result["source_knowledge_ids"])
        self.assertIn("行动", result["scene_application"])
        self.assertFalse(result["source_isolation"]["raw_text_included"])

    def test_logic_and_mystery_path_is_explained(self):
        seeded = self.seed_knowledge_system()
        result = mkaos.create_cross_discipline_fusion_path(
            self.storage,
            {"project_id": self.project_id, "genre": "悬疑", "selected_knowledge_ids": [seeded["mystery"]["asset"]["id"]]},
        )
        self.assertIn("证据链", result["narrative_application"])
