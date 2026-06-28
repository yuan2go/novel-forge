from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.api.product import create_project_with_defaults
from novel_forge.modules.analysis import convert_analysis_report, create_analysis_handoff, list_analysis_reports, run_analysis
from novel_forge.schemas import SourceDocument, validate_common_fields
from novel_forge.storage.local import LocalStorage


class AnalysisServiceTests(unittest.TestCase):
    def test_analysis_reports_are_schema_backed_and_not_direct_rag_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = create_project_with_defaults(tmp, "Analysis Project")
            storage = LocalStorage(tmp)
            source_path = self._write_source(storage, project)

            results = [
                run_analysis(storage, source_path, "common", workspace_path=project["path"]),
                run_analysis(storage, source_path, "web_fiction_business", workspace_path=project["path"]),
                run_analysis(storage, source_path, "published_fiction", workspace_path=project["path"]),
                run_analysis(storage, source_path, "classic_literary", workspace_path=project["path"]),
            ]

            report_types = {result["report_type"] for result in results}
            self.assertEqual(
                report_types,
                {
                    "common_novel_analysis_report",
                    "web_fiction_business_analysis_report",
                    "published_fiction_analysis_report",
                    "classic_literary_analysis_report",
                },
            )
            for result in results:
                data = storage.read_json(result["path"])
                self.assertEqual(validate_common_fields(data), [])
                self.assertEqual(data["metadata"]["project_id"], project["project_id"])
                self.assertFalse(data["metadata"]["use_in_generation_rag"])
                self.assertIn("abstract", data["metadata"]["copyright_boundary"])
                self.assertIn("semantic_depth", data["content"])
                self.assertGreaterEqual(data["content"]["semantic_depth"]["overall_score"], 0)
                self.assertIn("provider_review", data["content"])
                self.assertTrue(data["content"]["mode_specific_panels"])

            rows = list_analysis_reports(storage, project_id=project["project_id"])
            self.assertEqual(len(rows), 4)
            self.assertIn("semantic_depth", rows[0])
            self.assertIn("visualization", rows[0])

    def test_analysis_conversion_creates_safe_abstract_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = create_project_with_defaults(tmp, "Analysis Conversion Project")
            storage = LocalStorage(tmp)
            source_path = self._write_source(storage, project)
            report = run_analysis(storage, source_path, "web_fiction_business", workspace_path=project["path"])

            converted = convert_analysis_report(
                storage,
                report["path"],
                targets=["writing_template", "material_card", "review_rule_pack"],
                workspace_path=project["path"],
            )

            self.assertEqual(validate_common_fields(converted["asset"]), [])
            self.assertEqual(len(converted["created_assets"]), 3)
            for created in converted["created_assets"]:
                data = storage.read_json(created["path"])
                self.assertEqual(data["metadata"]["project_id"], project["project_id"])
                self.assertIn("abstract", data["metadata"]["copyright_boundary"])
                self.assertNotEqual(data["type"], "web_fiction_business_analysis_report")
                self.assertEqual(data["metadata"]["asset_status"], "needs_human_gate")
                self.assertFalse(data["metadata"]["use_in_generation_rag"])

            approved = convert_analysis_report(
                storage,
                report["path"],
                targets=["knowledge_card"],
                workspace_path=project["path"],
                human_approved=True,
                approval_note="unit test approved abstraction",
            )
            approved_data = storage.read_json(approved["created_assets"][0]["path"])
            self.assertEqual(approved_data["metadata"]["asset_status"], "active")
            self.assertTrue(approved_data["metadata"]["use_in_generation_rag"])

    def test_analysis_handoff_uses_analysis_agent_and_expected_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = create_project_with_defaults(tmp, "Analysis Handoff Project")
            storage = LocalStorage(tmp)
            source_path = self._write_source(storage, project)

            handoff = create_analysis_handoff(
                storage,
                source_path,
                "classic_literary",
                workspace_path=project["path"],
            )

            data = handoff["asset"]
            self.assertEqual(validate_common_fields(data), [])
            self.assertEqual(data["type"], "claude_code_handoff")
            self.assertEqual(data["content"]["skill"], "classic-literary-depth-analysis")
            self.assertEqual(data["content"]["expected_output_type"], "classic_literary_analysis_report")
            self.assertEqual(data["content"]["agent_runtime"]["agent"], "Analysis Agent")
            self.assertIn("write_analysis_report", data["content"]["agent_runtime"]["allowed_tools"])

    def _write_source(self, storage: LocalStorage, project: dict[str, str]) -> str:
        path = storage.write_asset(
            "raw",
            SourceDocument(
                title="Fixture Reference",
                source="fixture.txt",
                content={
                    "text": "第一章 雨夜里秘密出现。主角必须选择，代价是真相延后。第二章 危机升级，新的钩子出现。"
                },
                metadata={
                    "project_id": project["project_id"],
                    "workspace_path": project["path"],
                    "rights": {
                        "authorization": "test_fixture",
                        "copyright_boundary": "self-authored unit test fixture",
                        "allow_downstream_generation": True,
                    },
                },
            ),
        )
        return str(path.relative_to(storage.root))


if __name__ == "__main__":
    unittest.main()
