from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.canon_graph import run_canon_graph_plugin
from novel_forge.schemas import DraftChapter, PowerScaleRule
from novel_forge.storage.local import LocalStorage


class CanonGraphPluginTests(unittest.TestCase):
    def test_fantasy_power_scale_plugin_writes_report_and_review_issue(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            rule = PowerScaleRule(
                title="power scale",
                content={"scale_id": "scale-1", "levels": ["一阶", "二阶"], "constraints": ["突破必须有代价"], "violation_checks": ["无代价突破"]},
                metadata={"project_id": "p1"},
            )
            storage.write_asset_auto(rule)
            draft = DraftChapter(
                title="chapter",
                content={"chapter": 3, "text": "主角无代价突破，随后一击秒杀所有敌人。", "copyright_boundary": "original draft"},
                metadata={"project_id": "p1"},
            )
            draft_path = storage.write_asset_auto(draft)

            result = run_canon_graph_plugin(storage, {"plugin": "fantasy_power_scale_engine", "target_path": str(draft_path)})

            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["asset"]["type"], "fantasy_power_scale_report")
            self.assertGreaterEqual(result["asset"]["content"]["blocking_issue_count"], 1)
            self.assertTrue(result["review_issues"])

    def test_all_plugins_have_schema_backed_pass_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            for plugin, expected_type in {
                "mystery_evidence_chain_engine": "mystery_evidence_chain_report",
                "romance_relationship_state_engine": "romance_relationship_state_report",
                "historical_faction_network_engine": "historical_faction_network_report",
                "sci_fi_rule_consistency_engine": "sci_fi_rule_consistency_report",
                "horror_rule_contamination_engine": "horror_rule_contamination_report",
            }.items():
                result = run_canon_graph_plugin(storage, {"plugin": plugin, "artifact_text": "稳定规则下的原创章节。", "persist_issues": False})
                self.assertEqual(result["asset"]["type"], expected_type)
                self.assertEqual(result["asset"]["content"]["blocking_issue_count"], 0)


if __name__ == "__main__":
    unittest.main()
