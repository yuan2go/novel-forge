from tests.unit.mkaos_p1_helpers import MkaosP1TestCase
from novel_forge.modules import mkaos


class MkaosLineageAuditTests(MkaosP1TestCase):
    def test_lineage_tracks_source_to_pack_issue_feedback_and_no_raw_text(self):
        seeded = self.seed_knowledge_system()
        kid = seeded["history"]["asset"]["id"]
        pack = mkaos.build_knowledge_pack(self.storage, {"project_id": self.project_id, "flow": "prose", "task_id": "lineage"})
        mkaos.record_usage_event(self.storage, {"project_id": self.project_id, "knowledge_id": kid, "knowledge_pack_id": pack["asset"]["id"], "flow": "prose", "agent_name": "DraftAgent", "used_as": "constraint"})
        mkaos.persist_mkaos_review_issues(self.storage, {"project_id": self.project_id, "target_asset_id": "draft-1", "related_knowledge_ids": [kid], "issues": [{"issue_type": "mkaos_conflict", "severity": "high", "message": "bad use"}]})
        mkaos.attribute_reader_feedback_to_knowledge(self.storage, {"project_id": self.project_id, "feedback_text": "节奏慢", "candidate_knowledge_ids": [kid]})
        report = mkaos.query_lineage_audit(self.storage, {"project_id": self.project_id, "knowledge_id": kid})
        self.assertTrue(report["knowledge_packs"])
        self.assertTrue(report["review_issues"])
        self.assertTrue(report["feedback_attributions"])
        self.assertFalse(report["source_isolation"]["raw_text_included"])
        self.assertNotIn("历史制度会改变资源分配", str(report))
