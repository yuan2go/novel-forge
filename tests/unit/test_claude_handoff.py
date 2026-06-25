from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.schemas import validate_common_fields
from novel_forge.workflows import pipeline


class ClaudeHandoffTests(unittest.TestCase):
    def test_claude_deconstruct_handoff_references_source_without_copying_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.txt"
            protected_fixture_text = "Hidden source sentence for handoff boundary"
            source.write_text(protected_fixture_text, encoding="utf-8")
            raw_path = pipeline.ingest(
                tmp,
                str(source),
                rights_authorization="test_fixture",
                copyright_note="self-authored test fixture",
                allow_downstream_generation=True,
            )
            cleaned_path = pipeline.clean(tmp, str(raw_path))

            handoff_path = pipeline.claude_deconstruct(
                tmp,
                str(cleaned_path),
                genre="urban suspense",
                target_reader="serialized web readers",
            )

            data = json.loads(handoff_path.read_text(encoding="utf-8"))
            content = data["content"]
            self.assertEqual(validate_common_fields(data), [])
            self.assertEqual(data["type"], "claude_code_handoff")
            self.assertEqual(content["operation"], "hot_novel_deconstruction")
            self.assertEqual(content["skill"], "hot-novel-deconstruction")
            self.assertEqual(content["runtime"], "claude-code")
            self.assertEqual(content["runtime_model"], "codex")
            self.assertEqual(content["expected_output_type"], "decomposition_report")
            self.assertEqual(content["agent_runtime"]["agent"], "Knowledge Agent")
            self.assertIn("write_decomposition_report", content["agent_runtime"]["allowed_tools"])
            self.assertEqual(data["metadata"]["permission_profile"], "reference_to_abstract_knowledge_only")
            self.assertIn("agent_runtime", content["handoff_packet"]["context"])
            self.assertIn("skills/hot-novel-deconstruction/SKILL.md", data["references"])
            self.assertNotIn(protected_fixture_text, json.dumps(content, ensure_ascii=False))

    def test_claude_knowledge_handoff_targets_knowledge_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.txt"
            source.write_text("A concise domain note about credible constraints.", encoding="utf-8")
            raw_path = pipeline.ingest(
                tmp,
                str(source),
                rights_authorization="test_fixture",
                copyright_note="self-authored test fixture",
                allow_downstream_generation=True,
            )

            handoff_path = pipeline.claude_knowledge(
                tmp,
                str(raw_path),
                discipline="forensic accounting",
                credibility="introductory public knowledge",
                project_context="modern suspense serial",
            )

            data = json.loads(handoff_path.read_text(encoding="utf-8"))
            content = data["content"]
            self.assertEqual(validate_common_fields(data), [])
            self.assertEqual(content["operation"], "multidisciplinary_knowledge_parse")
            self.assertEqual(content["skill"], "multidisciplinary-knowledge")
            self.assertEqual(content["expected_output_type"], "knowledge_card")
            self.assertEqual(content["expected_output_dir"], "data/knowledge")
            self.assertEqual(content["handoff_packet"]["provider"], "claude-code")
            self.assertFalse(content["handoff_packet"]["automated_model_call"])
            self.assertEqual(content["agent_runtime"]["agent"], "Knowledge Agent")
            self.assertIn("write_knowledge_card", content["agent_runtime"]["allowed_tools"])


if __name__ == "__main__":
    unittest.main()
