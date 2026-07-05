from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.mkaos_production_gate import latest_gate_report, list_gate_reports, run_mkaos_production_gate
from novel_forge.modules.review_issue import list_review_issues
from novel_forge.storage.local import LocalStorage


class MkaosProductionGateRunnerTests(unittest.TestCase):
    def test_production_gate_blocks_forbidden_source_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()

            with self.assertRaisesRegex(ValueError, "MKAOS production gate blocked"):
                run_mkaos_production_gate(
                    storage,
                    {
                        "project_id": "gate-p",
                        "flow": "prose",
                        "environment": "production",
                        "target_asset": {"id": "draft-1", "type": "draft_chapter", "content": {"raw_text": "forbidden"}},
                        "knowledge_pack": {"id": "pack-1", "type": "knowledge_pack", "content": {"pack_items": [{"knowledge_id": "k1", "principle": "abstract"}]}},
                    },
                )

            self.assertTrue(list_review_issues(storage, project_id="gate-p", blocking=True))
            self.assertEqual(latest_gate_report(storage, project_id="gate-p")["content"]["recommendation"], "block")

    def test_compat_gate_records_warning_report_without_blocking(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()

            report = run_mkaos_production_gate(
                storage,
                {
                    "project_id": "gate-p",
                    "flow": "recap",
                    "environment": "compat",
                    "target_asset": {"id": "recap-1", "type": "longform_recap_report", "content": {"summary": "safe"}},
                    "knowledge_pack": {"id": "pack-1", "type": "knowledge_pack", "content": {"pack_items": [{"knowledge_id": "k1", "principle": "abstract"}]}},
                },
            )

            self.assertTrue(report["passed"])
            self.assertTrue(report["warnings"])
            self.assertEqual(len(list_gate_reports(storage, project_id="gate-p")), 1)

    def test_publish_gate_reads_blocking_review_issue(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            from novel_forge.modules.review_issue import create_review_issue

            create_review_issue(storage, {"project_id": "gate-p", "target_asset_id": "release-1", "issue_type": "source_leakage", "severity": "critical", "blocking": True, "message": "leak"})

            with self.assertRaisesRegex(ValueError, "blocked publish"):
                run_mkaos_production_gate(
                    storage,
                    {
                        "project_id": "gate-p",
                        "flow": "publish",
                        "environment": "production",
                        "target_asset": {"id": "release-1", "type": "release_package", "content": {"summary": "safe"}},
                        "knowledge_pack": {"id": "pack-1", "type": "knowledge_pack", "content": {"pack_items": [{"knowledge_id": "k1", "principle": "abstract"}]}},
                    },
                )


if __name__ == "__main__":
    unittest.main()
