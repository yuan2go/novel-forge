from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.mkaos import create_knowledge_card
from novel_forge.modules.mkaos_ingestion import create_creative_knowledge_card, run_source_type_extractor
from novel_forge.storage.local import LocalStorage


class MkaosCreativeKnowledgeCardTests(unittest.TestCase):
    def test_creative_knowledge_card_extends_existing_knowledge_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()

            result = create_creative_knowledge_card(storage, {"concept_name": "礼法压力", "creative_principle": "礼法转成行动成本", "applicable_flows": ["outline", "review"], "originality_boundary": "abstract only"})
            card = result["asset"]

            self.assertEqual(card["type"], "knowledge_card")
            self.assertEqual(card["content"]["knowledge_subtype"], "creative_knowledge_card")
            self.assertIn("creative_usability_score", card["content"]["quality_dimensions"])

    def test_legacy_knowledge_card_remains_plain_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()

            result = create_knowledge_card(storage, {"concept_name": "普通知识", "core_explanation": "可复用原则"})

            self.assertNotEqual(result["asset"]["content"].get("knowledge_subtype"), "creative_knowledge_card")

    def test_run_source_type_extractor_persists_cards(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()

            result = run_source_type_extractor(storage, {"source_type": "professional_book", "text": "方法必须转成角色行动"})

            self.assertEqual(result["created_count"], 1)
            self.assertEqual(result["created"][0]["metadata"]["knowledge_subtype"], "creative_knowledge_card")


if __name__ == "__main__":
    unittest.main()
