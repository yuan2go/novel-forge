from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules import mkaos as mkaos_service
from novel_forge.modules.mkaos_converters import convert_creative_assets
from novel_forge.modules.mkaos_ingestion import create_creative_knowledge_card
from novel_forge.storage.local import LocalStorage


class MkaosGraphExplorerDeepeningTests(unittest.TestCase):
    def test_graph_explorer_includes_creative_assets_relations_and_v3_indexes(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            card = create_creative_knowledge_card(
                storage,
                {
                    "concept_name": "证据链压力",
                    "creative_principle": "证据解释权形成攻防",
                    "applicable_flows": ["outline", "review"],
                    "originality_boundary": "abstract only",
                },
            )["asset"]

            convert_creative_assets(storage, {"knowledge_ids": [card["id"]], "dry_run": False, "conversion_types": ["world_rule_card", "chapter_hook_card"]})
            explorer = mkaos_service.build_knowledge_graph_explorer(storage, {"project_id": "local-system", "max_nodes": 100})
            data = explorer["data"] if "data" in explorer else explorer
            node_types = {str(node.get("node_type") or "") for node in data["nodes"]}
            relations = {str(edge.get("relation") or "") for edge in data["edges"]}

            self.assertEqual(data["version"], "mkaos-graph-explorer-v3")
            self.assertIn("world_rule_card", node_types)
            self.assertIn("chapter_hook_card", node_types)
            self.assertIn("converted_to", relations)
            self.assertTrue(data["centrality"]["top_nodes"])
            self.assertTrue(any(item["relation"] == "converted_to" for item in data["relation_filters"]))
            self.assertFalse(data["source_isolation"]["raw_text_included"])


if __name__ == "__main__":
    unittest.main()
