from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.api.product import create_github_knowledge_handoff
from novel_forge.modules.source_intake import list_github_knowledge_sources, list_source_policies
from novel_forge.schemas import validate_common_fields


class SourceIntakeTests(unittest.TestCase):
    def test_source_policies_keep_crawler_boundaries(self):
        policies = {item["id"]: item for item in list_source_policies()}

        self.assertFalse(policies["chinese_text_project"]["crawler_allowed"])
        self.assertEqual(policies["chinese_text_project"]["method"], "manual_reference_only")
        self.assertIn("official_robot_harvest_or_mirror", policies["project_gutenberg"]["method"])
        self.assertTrue(policies["project_gutenberg"]["crawler_allowed"])

    def test_github_knowledge_sources_filter_for_knowledge_cards(self):
        ancient = list_github_knowledge_sources(category="ancient_chinese", allowed_pipeline="knowledge_card_extraction")
        repos = {item["repo"] for item in ancient}

        self.assertIn("NiuTrans/Classical-Modern", repos)
        self.assertIn("QSJDAMTX/Ancient-Chinese-Allusion-Resource-Database", repos)
        self.assertTrue(all("knowledge_card_extraction" in item["allowed_pipeline"] for item in ancient))

    def test_github_knowledge_handoff_uses_metadata_note_and_license_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = create_github_knowledge_handoff(
                tmp,
                {
                    "repo_refs": ["NiuTrans/Classical-Modern", "ydli-ai/CSL"],
                    "discipline": "classical Chinese and research methods",
                    "project_context": "eastern fantasy worldbuilding",
                },
            )
            source_note = result["source_note"]["asset"]
            handoff = result["handoff"]["asset"]
            content = handoff["content"]
            serialized = json.dumps(handoff, ensure_ascii=False)

            self.assertEqual(validate_common_fields(source_note), [])
            self.assertEqual(validate_common_fields(handoff), [])
            self.assertEqual(source_note["type"], "source_document")
            self.assertTrue(source_note["metadata"]["license_review_required"])
            self.assertFalse(source_note["metadata"]["rights"]["allow_downstream_generation"])
            self.assertEqual(content["operation"], "multidisciplinary_knowledge_parse")
            self.assertEqual(content["expected_output_type"], "knowledge_card")
            self.assertEqual(len(content["external_source_refs"]), 2)
            self.assertTrue(content["source_acquisition_policy"]["license_review_required"])
            self.assertIn("raw_text_used=false", " ".join(content["acceptance_checks"]))
            self.assertNotIn("Hidden source sentence", serialized)


if __name__ == "__main__":
    unittest.main()
