from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.mkaos_ingestion import create_creative_knowledge_card
from novel_forge.modules.mkaos_quality import evaluate_extraction_quality, gate_knowledge_pack
from novel_forge.modules.review_issue import list_review_issues
from novel_forge.storage.local import LocalStorage


class MkaosExtractionQualityTests(unittest.TestCase):
    def test_extraction_report_blocks_weak_creative_card_in_production(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            result = create_creative_knowledge_card(storage, {"project_id": "quality", "concept_name": "弱卡", "creative_principle": "概念定义", "applicable_flows": [], "originality_boundary": "", "creative_usability_score": 0.2})
            path = storage.root / result["path"]
            card = storage.read_json(path)
            card["content"]["applicable_flows"] = []
            card["content"]["originality_boundary"] = ""
            card["content"]["quality_dimensions"]["creative_usability_score"] = 0.2
            card["content"]["quality_dimensions"]["abstraction_score"] = 0.2
            storage.write_json(path, card)

            with self.assertRaisesRegex(ValueError, "blocked production"):
                evaluate_extraction_quality(storage, {"project_id": "quality", "environment": "production"})

            self.assertTrue(list_review_issues(storage, project_id="quality", blocking=True))

    def test_pack_gate_blocks_forbidden_source_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()

            with self.assertRaisesRegex(ValueError, "KnowledgePack gate blocked"):
                gate_knowledge_pack(storage, {"project_id": "gate", "environment": "production", "flow": "prose", "knowledge_pack": {"content": {"pack_items": [{"source_text": "raw pair"}]}}})

    def test_valid_pack_gate_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            result = gate_knowledge_pack(storage, {"project_id": "gate", "flow": "prose", "knowledge_pack": {"content": {"pack_items": [{"knowledge_id": "k1", "principle": "abstract only"}]}}})
            self.assertTrue(result["passed"])


if __name__ == "__main__":
    unittest.main()
