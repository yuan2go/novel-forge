from tests.unit.mkaos_p1_helpers import MkaosP1TestCase
from novel_forge.modules import mkaos


class MkaosMutationAuditTests(MkaosP1TestCase):
    def test_create_update_weight_quarantine_have_audit_events(self):
        seeded = self.seed_knowledge_system()
        kid = seeded["history"]["asset"]["id"]
        mkaos.apply_weight_update(self.storage, {"project_id": self.project_id, "knowledge_id": kid, "delta": -0.2, "reason": "unit"})
        mkaos.change_knowledge_status(self.storage, kid, {"status": "quarantined", "reason": "unit"})
        mutations = mkaos.list_mkaos_mutations(self.storage, asset_id=kid)
        types = {row["content"]["mutation_type"] for row in mutations}
        self.assertIn("create", types)
        self.assertIn("quarantined", types)
        self.assertNotIn("历史制度会改变资源分配", str(mutations))
