from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.mkaos_lineage import analyze_asset_impact, build_lineage_index
from novel_forge.schemas import BaseAsset
from novel_forge.storage.local import LocalStorage


class MkaosAssetImpactAnalysisTests(unittest.TestCase):
    def test_impact_analysis_finds_review_issue_and_gate_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            _seed_impact_assets(storage)
            build_lineage_index(storage, project_id="impact-p")

            impact = analyze_asset_impact(storage, {"project_id": "impact-p", "asset_id": "knowledge-1", "persist": False})

            self.assertEqual(impact["risk_level"], "high")
            self.assertEqual(impact["recommended_action"], "quarantine")
            self.assertTrue(impact["review_issues"])
            self.assertTrue(impact["gate_blocks"])
            self.assertLess(impact["weight_delta_suggestion"], 0)


def _seed_impact_assets(storage: LocalStorage) -> None:
    knowledge = BaseAsset(id="knowledge-1", type="knowledge_card", title="Knowledge", content={"concept_name": "机制"}, metadata={"project_id": "impact-p"})
    issue = BaseAsset(id="issue-1", type="review_issue", title="Issue", source="draft-1", content={"target_asset_id": "draft-1", "related_knowledge_ids": ["knowledge-1"], "blocking": True, "status": "open", "severity": "critical"}, metadata={"project_id": "impact-p", "blocking": True}, references=["knowledge-1", "draft-1"])
    gate = BaseAsset(id="gate-1", type="mkaos_production_gate_report", title="Gate", source="draft-1", content={"passed": False, "target_asset_id": "draft-1", "knowledge_pack_id": "pack-1", "blocking_issue_count": 1, "review_issue_ids": ["issue-1"]}, metadata={"project_id": "impact-p"}, references=["knowledge-1", "issue-1"])
    storage.write_asset("knowledge", knowledge)
    storage.write_asset("reviews", issue)
    storage.write_asset("runs", gate)


if __name__ == "__main__":
    unittest.main()
