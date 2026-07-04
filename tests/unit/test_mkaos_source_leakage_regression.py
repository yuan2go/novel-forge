from tests.unit.mkaos_p1_helpers import MkaosP1TestCase
from novel_forge.modules import mkaos


class MkaosSourceLeakageRegressionTests(MkaosP1TestCase):
    def test_runtime_assets_and_source_text_do_not_enter_pack_or_graph(self):
        seeded = self.seed_knowledge_system()
        pack = mkaos.build_knowledge_pack(self.storage, {"project_id": self.project_id, "flow": "prose", "task_id": "leak"})
        preview = mkaos.pack_prompt_preview(self.storage, pack["asset"]["id"])
        graph = mkaos.build_knowledge_graph(self.storage, {"project_id": self.project_id})
        self.assertFalse(pack["asset"]["content"]["source_isolation"]["prose_raw_source_text_included"])
        self.assertNotIn("历史制度会改变资源分配", str(pack["asset"]["content"]))
        self.assertNotIn("历史制度会改变资源分配", preview["preview"])
        self.assertFalse(graph["data"]["source_isolation"]["raw_source_text_included"])
        issues = mkaos.persist_mkaos_review_issues(self.storage, {"project_id": self.project_id, "target_asset_id": "draft", "related_knowledge_ids": [seeded["history"]["asset"]["id"]], "issues": [{"issue_type": "source_leakage", "severity": "critical", "message": "leak"}]})
        self.assertEqual(issues["blocking_count"], 1)
