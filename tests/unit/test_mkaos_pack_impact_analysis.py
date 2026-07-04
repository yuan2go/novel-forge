from tests.unit.mkaos_p1_helpers import MkaosP1TestCase
from novel_forge.modules import mkaos


class MkaosPackImpactAnalysisTests(MkaosP1TestCase):
    def test_quarantine_generates_impact_report(self):
        seeded = self.seed_knowledge_system()
        kid = seeded["history"]["asset"]["id"]
        pack = mkaos.build_knowledge_pack(self.storage, {"project_id": self.project_id, "flow": "prose", "task_id": "impact"})
        report = mkaos.analyze_knowledge_impact(self.storage, kid, change_type="quarantine", dry_run=True)
        self.assertIn(pack["asset"]["id"], report["affected_packs"])
        self.assertIn("review", report["recommended_rechecks"])
        self.assertFalse(report["source_isolation"]["raw_text_included"])
