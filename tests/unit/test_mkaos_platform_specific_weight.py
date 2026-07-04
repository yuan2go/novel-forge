from tests.unit.mkaos_p1_helpers import MkaosP1TestCase
from novel_forge.modules import mkaos


class MkaosPlatformSpecificWeightTests(MkaosP1TestCase):
    def test_platform_weight_source_affects_pack_debugger(self):
        seeded = self.seed_knowledge_system()
        pack = mkaos.build_knowledge_pack(self.storage, {"project_id": self.project_id, "flow": "prose", "task_id": "fanqie", "platform": "fanqie"})
        debug = mkaos.pack_debug_report(self.storage, pack["asset"]["id"])
        self.assertEqual(debug["platform_match"][seeded["history"]["asset"]["id"]], "platform:fanqie")

    def test_platform_feedback_only_records_target_platform(self):
        seeded = self.seed_knowledge_system()
        result = mkaos.attribute_reader_feedback_to_knowledge(self.storage, {"project_id": self.project_id, "feedback_text": "节奏慢", "candidate_knowledge_ids": [seeded["history"]["asset"]["id"]], "platform": "fanqie"})
        self.assertEqual(result["asset"]["content"]["recommendation"], "reduce")
