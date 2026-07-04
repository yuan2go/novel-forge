from tests.unit.mkaos_p1_helpers import MkaosP1TestCase
from novel_forge.modules import mkaos


class MkaosPackDebuggerTests(MkaosP1TestCase):
    def test_debug_report_explains_selection_rejection_budget_and_risk(self):
        self.seed_knowledge_system()
        pack = mkaos.build_knowledge_pack(
            self.storage,
            {"project_id": self.project_id, "flow": "prose", "task_id": "debug", "source_policy": {"exclude_high_risk": True}},
        )
        debug = mkaos.pack_debug_report(self.storage, pack["asset"]["id"])
        self.assertTrue(debug["score_breakdown"])
        self.assertTrue(debug["rejected_items"])
        self.assertIn("budget_usage", debug)
        self.assertFalse(debug["source_isolation"]["raw_text_included"])
