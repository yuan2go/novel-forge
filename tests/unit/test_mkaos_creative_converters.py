from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.mkaos_converters import convert_creative_assets
from novel_forge.modules.mkaos_ingestion import create_creative_knowledge_card
from novel_forge.storage.local import LocalStorage


class MkaosCreativeConverterTests(unittest.TestCase):
    def test_dry_run_converts_creative_knowledge_to_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            card = create_creative_knowledge_card(storage, {"concept_name": "证据链压力", "creative_principle": "证据解释权形成攻防", "applicable_flows": ["outline", "review"], "originality_boundary": "abstract only"})["asset"]

            result = convert_creative_assets(storage, {"knowledge_ids": [card["id"]], "dry_run": True, "conversion_types": ["conflict_pattern_card", "chapter_hook_card"]})

            self.assertEqual(result["converted_count"], 2)
            self.assertEqual(result["converted"][0]["references"][0], card["id"])
            self.assertFalse(result["source_isolation"]["raw_text_included"])

    def test_persisted_conversion_creates_rule_and_template_cards(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            card = create_creative_knowledge_card(storage, {"concept_name": "制度冲突", "creative_principle": "制度差异制造利益冲突", "applicable_flows": ["outline", "review"], "originality_boundary": "abstract only"})["asset"]

            result = convert_creative_assets(storage, {"knowledge_ids": [card["id"]], "dry_run": False, "conversion_types": ["review_rule_card", "plot_template_card"]})

            self.assertEqual(result["converted_count"], 2)
            self.assertEqual(len(result["rule_cards"]), 1)
            self.assertEqual(len(result["template_cards"]), 1)
            self.assertEqual(result["relations"][0]["content"]["relation_type"], "converted_to")


if __name__ == "__main__":
    unittest.main()
