from tests.unit.mkaos_p1_helpers import MkaosP1TestCase
from novel_forge.modules import mkaos


class MkaosVersioningTests(MkaosP1TestCase):
    def test_update_diff_and_rollback_are_tracked(self):
        seeded = self.seed_knowledge_system()
        kid = seeded["history"]["asset"]["id"]
        mkaos.update_knowledge_card(self.storage, kid, {"weight": 1.8, "reason": "unit"})
        versions = mkaos.list_knowledge_versions(self.storage, kid)
        self.assertGreaterEqual(len(versions), 2)
        diff = mkaos.diff_knowledge_versions(self.storage, versions[0]["id"], versions[-1]["id"])
        self.assertTrue(diff["changed_fields"])
        create_version = next(row for row in versions if row["content"]["reason"] == "create")
        rolled = mkaos.rollback_knowledge_version(self.storage, create_version["id"])
        self.assertEqual(rolled["asset"]["content"]["weight"], seeded["history"]["asset"]["content"]["weight"])
        self.assertTrue(mkaos.list_mkaos_mutations(self.storage, asset_id=kid))
