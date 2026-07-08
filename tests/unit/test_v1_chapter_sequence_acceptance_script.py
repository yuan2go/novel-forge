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
        self.assertEqual(manifest["unready_final_evidence_count"], 4)
        self.assertEqual(manifest["missing_or_deferred_final_evidence_count"], 4)
        self.assertIn("legacy_count_compatibility", manifest)
        self.assertEqual(len(manifest["unready_final_evidence"]), 4)
        self.assertIn("source_governance_runtime", {row["key"] for row in manifest["required_evidence"]})
        self.assertIn("quality_calibration_readiness_gate", {row["key"] for row in manifest["required_evidence"]})
        self.assertFalse(manifest["chapter_acceptance_executed_by_manifest"])

    def test_unified_preflight_manifest_resolves_existing_source_workflow_and_approval_evidence(self):
        module = _load_acceptance_script()
        from novel_forge.storage.local import LocalStorage

        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            storage.write_json(
                "data/runs/source-gate.json",
                {
                    "id": "source-gate",
                    "type": "gate_result",
                    "title": "source gate",
                    "content": {"gate_kind": "source_governance_runtime", "status": "passed", "message": "source passed"},
                    "metadata": {"project_id": "book-a"},
                },
            )
            storage.write_json(
                "data/runs/workflow-gate.json",
                {
                    "id": "workflow-gate",
                    "type": "gate_result",
                    "title": "workflow gate",
                    "content": {"gate_kind": "workflow_governance_drift", "status": "passed", "message": "workflow passed"},
                    "metadata": {"project_id": "book-a"},
                },
            )
            storage.write_json(
                "data/runs/approval-readiness.json",
                {
                    "id": "approval-readiness",
                    "type": "project_metric_snapshot",
                    "title": "approval readiness",
                    "content": {"snapshot_kind": "approval_request_caller_readiness", "status": "passed", "operator_action": "approval ready"},
                    "metadata": {"project_id": "book-a", "snapshot_kind": "approval_request_caller_readiness"},
                },
            )
            storage.write_json(
                "data/runs/quality-calibration-readiness.json",
                {
                    "id": "quality-calibration-readiness",
                    "type": "project_metric_snapshot",
                    "title": "quality calibration readiness",
                    "content": {
                        "snapshot_kind": "quality_calibration_readiness",
                        "status": "passed",
                        "operator_action": "quality calibration ready",
                    },
                    "metadata": {"project_id": "book-a", "snapshot_kind": "quality_calibration_readiness"},
                },
            )
            storage.write_json(
                "data/runs/quality-calibration-gate.json",
                {
                    "id": "quality-calibration-gate",
                    "type": "gate_result",
                    "title": "quality calibration gate",
                    "content": {
                        "gate_kind": "quality_calibration_readiness_gate",
                        "status": "passed",
                        "message": "quality calibration passed",
                        "blocking": False,
                        "result": {
                            "operator_action": "quality calibration gate ready",
                            "readiness_report_path": "data/runs/quality-calibration-readiness.json",
                        },
                    },
                    "metadata": {"project_id": "book-a"},
                },
            )

            resolved = module._resolve_unified_acceptance_preflight_evidence(storage, project_id="book-a")
            result = module._with_runtime_growth_acceptance_preflight(
                {"status": "succeeded", "failures": [], "acceptance_report": {"asset": {"content": {"recommendation": "pass"}}}},
                {
                    "status": "passed",
                    "blocking": False,
                    "gate_result_path": "data/runs/runtime-growth-gate.json",
                    "message": "passed",
                    "summary": {"blocking_count": 0},
                    "blocking_rows": [],
                },
                resolved_evidence=resolved,
            )

            manifest = result["unified_acceptance_preflight_manifest"]
            status_by_key = {row["key"]: row["status"] for row in manifest["required_evidence"]}
            self.assertEqual(manifest["status"], "passed")
            self.assertEqual(manifest["unready_final_evidence_count"], 0)
            self.assertEqual(manifest["missing_or_deferred_final_evidence_count"], 0)
            self.assertEqual(manifest["unready_final_evidence"], [])
            self.assertEqual(status_by_key["source_governance_runtime"], "passed")
            self.assertEqual(status_by_key["workflow_governance_drift"], "passed")
            self.assertEqual(status_by_key["approval_request_caller_readiness"], "passed")
            self.assertEqual(status_by_key["quality_calibration_readiness_gate"], "passed")
            quality_row = [row for row in manifest["required_evidence"] if row["key"] == "quality_calibration_readiness_gate"][0]
            self.assertEqual(quality_row["linked_evidence_paths"], ["data/runs/quality-calibration-readiness.json"])

    def test_unified_preflight_requires_passed_quality_calibration_gate_not_only_snapshot(self):
        module = _load_acceptance_script()
        from novel_forge.storage.local import LocalStorage

        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            storage.write_json(
                "data/runs/source-gate.json",
                {
                    "id": "source-gate",
                    "type": "gate_result",
                    "title": "source gate",
                    "content": {"gate_kind": "source_governance_runtime", "status": "passed", "message": "source passed"},
                    "metadata": {"project_id": "book-a"},
                },
            )
            storage.write_json(
                "data/runs/workflow-gate.json",
                {
                    "id": "workflow-gate",
                    "type": "gate_result",
                    "title": "workflow gate",
                    "content": {"gate_kind": "workflow_governance_drift", "status": "passed", "message": "workflow passed"},
                    "metadata": {"project_id": "book-a"},
                },
            )
            storage.write_json(
                "data/runs/approval-readiness.json",
                {
                    "id": "approval-readiness",
                    "type": "project_metric_snapshot",
                    "title": "approval readiness",
                    "content": {"snapshot_kind": "approval_request_caller_readiness", "status": "passed", "operator_action": "approval ready"},
                    "metadata": {"project_id": "book-a", "snapshot_kind": "approval_request_caller_readiness"},
                },
            )
            storage.write_json(
                "data/runs/quality-calibration-readiness.json",
                {
                    "id": "quality-calibration-readiness",
                    "type": "project_metric_snapshot",
                    "title": "quality calibration readiness",
                    "content": {"snapshot_kind": "quality_calibration_readiness", "status": "passed"},
                    "metadata": {"project_id": "book-a", "snapshot_kind": "quality_calibration_readiness"},
                },
            )
            storage.write_json(
                "data/runs/quality-calibration-gate.json",
                {
                    "id": "quality-calibration-gate",
                    "type": "gate_result",
                    "title": "quality calibration gate",
                    "content": {
                        "gate_kind": "quality_calibration_readiness_gate",
                        "status": "failed",
                        "message": "quality calibration failed",
                        "blocking": True,
                        "result": {
                            "operator_action": "repair quality calibration",
                            "readiness_report_path": "data/runs/quality-calibration-readiness.json",
                        },
                    },
                    "metadata": {"project_id": "book-a"},
                },
            )

            resolved = module._resolve_unified_acceptance_preflight_evidence(storage, project_id="book-a")
            result = module._with_runtime_growth_acceptance_preflight(
                {"status": "succeeded", "failures": [], "acceptance_report": {"asset": {"content": {"recommendation": "pass"}}}},
                {
                    "status": "passed",
                    "blocking": False,
                    "gate_result_path": "data/runs/runtime-growth-gate.json",
                    "message": "passed",
                    "summary": {"blocking_count": 0},
                    "blocking_rows": [],
                },
                resolved_evidence=resolved,
            )

            manifest = result["unified_acceptance_preflight_manifest"]
            status_by_key = {row["key"]: row["status"] for row in manifest["required_evidence"]}
            self.assertEqual(result["status"], "succeeded")
            self.assertEqual(manifest["status"], "review_required")
            self.assertEqual(manifest["enforced_failure_count"], 0)
            self.assertEqual(manifest["unready_final_evidence_count"], 1)
            self.assertEqual(manifest["missing_or_deferred_final_evidence_count"], 1)
            self.assertEqual(manifest["unready_final_evidence"][0]["key"], "quality_calibration_readiness_gate")
            self.assertEqual(manifest["unready_final_evidence"][0]["status"], "failed")
            self.assertEqual(status_by_key["quality_calibration_readiness_gate"], "failed")

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
