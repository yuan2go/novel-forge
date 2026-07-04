from tests.unit.mkaos_p1_helpers import MkaosP1TestCase
from novel_forge.modules import mkaos


class MkaosStatusLifecycleTests(MkaosP1TestCase):
    def test_deprecated_quarantined_and_do_not_select_do_not_enter_pack(self):
        seeded = self.seed_knowledge_system()
        for status in ["deprecated", "quarantined", "do_not_select"]:
            with self.subTest(status=status):
                mkaos.change_knowledge_status(self.storage, seeded["history"]["asset"]["id"], {"status": status, "reason": "unit"})
                pack = mkaos.build_knowledge_pack(self.storage, {"project_id": self.project_id, "flow": "outline", "task_id": status})
                self.assertNotIn(seeded["history"]["asset"]["id"], {item["knowledge_id"] for item in pack["asset"]["content"]["pack_items"]})
        mutations = mkaos.list_mkaos_mutations(self.storage, asset_id=seeded["history"]["asset"]["id"])
        self.assertTrue(any(row["content"]["mutation_type"] in {"status_change", "quarantined", "do_not_select"} for row in mutations))

    def test_needs_review_blocks_production_selection(self):
        seeded = self.seed_knowledge_system()
        mkaos.change_knowledge_status(self.storage, seeded["history"]["asset"]["id"], {"status": "needs_review"})
        pack = mkaos.build_knowledge_pack(self.storage, {"project_id": self.project_id, "flow": "outline", "task_id": "needs-review", "environment": "production", "source_policy": {"exclude_high_risk": True}, "os_envelope": {"envelope_id": "env", "trace_id": "t", "environment": "production", "project_id": self.project_id}})
        self.assertNotIn(seeded["history"]["asset"]["id"], {item["knowledge_id"] for item in pack["asset"]["content"]["pack_items"]})
