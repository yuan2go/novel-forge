from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.mkaos_production_gate import build_gate_coverage_report, run_mkaos_production_gate
from novel_forge.schemas import BaseAsset
from novel_forge.storage.local import LocalStorage


class MkaosProductionGateCoverageTests(unittest.TestCase):
    def test_coverage_report_marks_context_and_gate_covered_operations(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            storage.write_asset(
                "contexts",
                BaseAsset(
                    id="context-prose-1",
                    type="context_bundle",
                    title="Prose context",
                    content={"project_id": "coverage-p", "mkaos_flow": "prose", "context_bundle_id": "context-prose-1", "knowledge_pack_id": "pack-1"},
                    metadata={"project_id": "coverage-p", "mkaos_flow": "prose"},
                    references=["pack-1"],
                ),
            )
            run_mkaos_production_gate(
                storage,
                {
                    "project_id": "coverage-p",
                    "flow": "prose",
                    "environment": "compat",
                    "target_asset": {"id": "draft-1", "type": "draft_chapter", "content": {"text": "safe"}},
                    "knowledge_pack": {"id": "pack-1", "type": "knowledge_pack", "content": {"pack_items": [{"knowledge_id": "knowledge-1", "creative_principle": "abstract"}]}},
                },
            )

            report = build_gate_coverage_report(storage, project_id="coverage-p")

            operations = {row["operation"]: row for row in report["operations"]}
            self.assertEqual(operations["draft"]["status"], "covered")
            self.assertTrue(operations["draft"]["production_enforced"])
            self.assertIn("review", report["forbidden_bypass_operations"])
            self.assertFalse(report["source_isolation"]["raw_text_included"])
            self.assertGreater(report["compat_gap_count"], 0)
            self.assertIn("path", report)


if __name__ == "__main__":
    unittest.main()
