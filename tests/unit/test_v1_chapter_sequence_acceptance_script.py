from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


def _load_acceptance_script():
    script_path = ROOT / "scripts" / "run_v1_chapter_sequence_acceptance.py"
    spec = importlib.util.spec_from_file_location("run_v1_chapter_sequence_acceptance", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class V1ChapterSequenceAcceptanceScriptTests(unittest.TestCase):
    def test_runtime_growth_preflight_failure_demotes_success_without_running_acceptance(self):
        module = _load_acceptance_script()

        result = module._with_runtime_growth_acceptance_preflight(
            {
                "status": "succeeded",
                "completed_chapters": 10,
                "chapter_count": 10,
                "failures": [],
                "acceptance_report": {"asset": {"content": {"recommendation": "pass"}}},
            },
            {
                "status": "failed",
                "blocking": True,
                "gate_result_path": "data/runs/runtime-growth-gate.json",
                "message": "chapter runtime growth threshold gate has blockers",
                "summary": {"blocking_count": 1},
                "blocking_rows": [{"code": "chapter_runtime_full_mode"}],
            },
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["runtime_growth_preflight"]["status"], "failed")
        self.assertEqual(result["unified_acceptance_preflight_manifest"]["status"], "failed")
        self.assertEqual(result["unified_acceptance_preflight_manifest"]["enforced_failure_count"], 1)
        self.assertEqual(result["failures"][0]["failure_type"], "runtime_growth_threshold_gate")
        self.assertEqual(result["acceptance_report"]["asset"]["content"]["recommendation"], "repair_runtime_growth_before_acceptance")

    def test_unified_preflight_manifest_marks_deferred_final_evidence_without_demoting_runtime_pass(self):
        module = _load_acceptance_script()

        result = module._with_runtime_growth_acceptance_preflight(
            {
                "status": "succeeded",
                "completed_chapters": 10,
                "chapter_count": 10,
                "failures": [],
                "acceptance_report": {"asset": {"content": {"recommendation": "pass"}}},
            },
            {
                "status": "passed",
                "blocking": False,
                "gate_result_path": "data/runs/runtime-growth-gate.json",
                "message": "passed",
                "summary": {"blocking_count": 0},
                "blocking_rows": [],
            },
        )

        manifest = result["unified_acceptance_preflight_manifest"]
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(manifest["status"], "review_required")
        self.assertEqual(manifest["enforced_failure_count"], 0)
        self.assertEqual(manifest["missing_or_deferred_final_evidence_count"], 3)
        self.assertIn("source_governance_runtime", {row["key"] for row in manifest["required_evidence"]})
        self.assertFalse(manifest["chapter_acceptance_executed_by_manifest"])

    def test_runtime_growth_preflight_persists_report_demotion(self):
        module = _load_acceptance_script()
        from novel_forge.storage.local import LocalStorage

        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            report_path = "data/runs/v1-acceptance-report.json"
            storage.write_json(
                report_path,
                {
                    "id": "v1-acceptance-report",
                    "type": "long_chain_acceptance_report",
                    "title": "V1 acceptance",
                    "tags": ["acceptance", "pass"],
                    "content": {"recommendation": "pass"},
                    "metadata": {"project_id": "book-a", "risk_level": "low"},
                },
            )
            result = {
                "acceptance_report_path": report_path,
                "runtime_growth_preflight": {
                    "status": "failed",
                    "blocking": True,
                    "gate_result_path": "data/runs/runtime-growth-gate.json",
                    "message": "blocked",
                    "summary": {"blocking_count": 1},
                    "blocking_rows": [{"code": "chapter_runtime_high_fanout"}],
                },
                "acceptance_report": {"asset": {"content": {"recommendation": "pass"}}},
            }

            module._persist_runtime_growth_acceptance_preflight(storage, result)

            persisted = storage.read_json(report_path)
            self.assertEqual(persisted["content"]["recommendation"], "repair_runtime_growth_before_acceptance")
            self.assertEqual(persisted["content"]["runtime_growth_preflight"]["status"], "failed")
            self.assertEqual(persisted["content"]["unified_acceptance_preflight_manifest"]["status"], "failed")
            self.assertEqual(persisted["metadata"]["risk_level"], "high")
            self.assertIn("runtime-growth-blocked", persisted["tags"])
            self.assertNotIn("pass", persisted["tags"])


if __name__ == "__main__":
    unittest.main()
