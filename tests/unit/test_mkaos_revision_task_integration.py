from tests.unit.mkaos_p1_helpers import MkaosP1TestCase
from novel_forge.modules import mkaos


class MkaosRevisionTaskIntegrationTests(MkaosP1TestCase):
    def test_source_leakage_issue_becomes_blocking_revision_task(self):
        seeded = self.seed_knowledge_system()
        task = mkaos.create_revision_task_from_mkaos_issue(
            self.storage,
            {
                "project_id": self.project_id,
                "issue": {"issue_type": "source_leakage", "message": "raw expression", "blocking": True},
                "related_knowledge_ids": [seeded["history"]["asset"]["id"]],
                "artifact_id": "draft-1",
                "knowledge_pack_id": "pack-1",
                "context_bundle_id": "ctx-1",
            },
        )
        content = task["asset"]["content"]
        self.assertTrue(content["blocking"])
        self.assertIn(seeded["history"]["asset"]["id"], content["related_knowledge"])
        self.assertTrue(content["re_review_criteria"])
