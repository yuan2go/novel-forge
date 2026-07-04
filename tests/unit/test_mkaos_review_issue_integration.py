from tests.unit.mkaos_p1_helpers import MkaosP1TestCase
from novel_forge.modules import mkaos
from novel_forge.modules.review_issue.service import blocking_review_issues, update_review_issue_status


class MkaosReviewIssueIntegrationTests(MkaosP1TestCase):
    def test_mkaos_issues_persist_as_blocking_review_issues_and_resolve(self):
        seeded = self.seed_knowledge_system()
        summary = mkaos.persist_mkaos_review_issues(
            self.storage,
            {
                "project_id": self.project_id,
                "target_asset_id": "draft-1",
                "knowledge_pack_id": "pack-1",
                "context_bundle_id": "ctx-1",
                "related_knowledge_ids": [seeded["history"]["asset"]["id"]],
                "issues": [{"issue_type": "source_leakage", "severity": "high", "message": "raw source expression risk"}],
            },
        )
        self.assertEqual(summary["blocking_count"], 1)
        blocking = blocking_review_issues(self.storage, target_asset_id="draft-1", project_id=self.project_id)
        self.assertEqual(len(blocking), 1)
        update_review_issue_status(self.storage, blocking[0]["id"], status="resolved")
        self.assertEqual(blocking_review_issues(self.storage, target_asset_id="draft-1", project_id=self.project_id), [])

    def test_issue_can_become_revision_task(self):
        task = mkaos.create_revision_task_from_mkaos_issue(
            self.storage,
            {"project_id": self.project_id, "issue": {"issue_type": "source_leakage", "message": "leak", "blocking": True}, "related_knowledge_ids": ["k1"], "artifact_id": "draft-1"},
        )
        content = task["asset"]["content"]
        self.assertTrue(content["blocking"])
        self.assertIn("re-review", " ".join(content["required_checks"]).replace("_", "-"))
