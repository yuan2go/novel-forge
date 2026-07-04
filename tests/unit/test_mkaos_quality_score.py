from tests.unit.mkaos_p1_helpers import MkaosP1TestCase
from novel_forge.modules import mkaos


class MkaosQualityScoreTests(MkaosP1TestCase):
    def test_quality_dimensions_recalculate_and_audit(self):
        seeded = self.seed_knowledge_system()
        kid = seeded["history"]["asset"]["id"]
        mkaos.record_review_feedback(self.storage, {"project_id": self.project_id, "knowledge_id": kid, "flow": "prose", "conflict_effective": True})
        recalculated = mkaos.recalculate_knowledge_quality(self.storage, kid, {"reason": "unit_test"})
        self.assertIn("abstraction_score", recalculated["quality_dimensions"])
        self.assertGreater(recalculated["overall_quality_score"], 0.5)
        mutations = mkaos.list_mkaos_mutations(self.storage, asset_id=kid)
        self.assertTrue(any(row["content"]["mutation_type"] == "quality_recalculate" for row in mutations))

    def test_low_abstraction_and_high_copyright_risk_are_visible(self):
        seeded = self.seed_knowledge_system()
        lows = mkaos.list_low_quality_knowledge(self.storage, threshold=0.8)
        high_risk = mkaos.list_high_copyright_risk_knowledge(self.storage)
        self.assertIn(seeded["risky"]["asset"]["id"], {row["id"] for row in lows})
        self.assertIn(seeded["risky"]["asset"]["id"], {row["id"] for row in high_risk})

    def test_reader_feedback_updates_reader_dimension_via_recalculate(self):
        seeded = self.seed_knowledge_system()
        result = mkaos.recalculate_knowledge_quality(self.storage, seeded["history"]["asset"]["id"], {"reader_feedback_delta": -0.2})
        self.assertLess(result["quality_dimensions"]["reader_feedback_score"], 0.5)
