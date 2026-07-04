from tests.unit.mkaos_p1_helpers import MkaosP1TestCase
from novel_forge.modules import mkaos


class MkaosGenreSpecificWeightTests(MkaosP1TestCase):
    def test_suspense_prefers_evidence_chain_and_history_prefers_institution(self):
        seeded = self.seed_knowledge_system()
        suspense = mkaos.build_knowledge_pack(self.storage, {"project_id": self.project_id, "flow": "outline", "task_id": "suspense", "genre": "悬疑", "task_goal": "公平证据链"})
        history = mkaos.build_knowledge_pack(self.storage, {"project_id": self.project_id, "flow": "outline", "task_id": "history", "genre": "历史", "task_goal": "土地制度冲突"})
        self.assertIn(seeded["mystery"]["asset"]["id"], {item["knowledge_id"] for item in suspense["asset"]["content"]["pack_items"]})
        self.assertIn(seeded["history"]["asset"]["id"], {item["knowledge_id"] for item in history["asset"]["content"]["pack_items"]})
