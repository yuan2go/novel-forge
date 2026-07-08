from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.production_governance import build_production_governance_evidence_drift_report, run_production_governance_drift_gate
from novel_forge.modules.runtime_ledger import record_gate_result
from novel_forge.schemas import PublishGateReport
from novel_forge.storage.local import LocalStorage


class ProductionGovernanceEvidenceTests(unittest.TestCase):
    def test_drift_report_flags_blocking_issue_contract_gaps_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            gate_path = storage.write_asset_auto(
                PublishGateReport(
                    title="Bad publish gate",
                    content={
                        "target_asset_id": "draft-1",
                        "gates": {"provider_runtime_gate_passed": False},
                        "decision": "blocked",
                        "blocking_issues": [{"severity": "high", "message": "provider missing"}],
                        "required_reports": {},
                        "human_override": False,
                    },
                    metadata={"project_id": "gov-drift-p"},
                )
            )

            report = build_production_governance_evidence_drift_report(storage, project_id="gov-drift-p", persist=True)
            original = storage.read_json(gate_path)

            self.assertEqual(report["snapshot_kind"], "production_governance_evidence_drift")
            self.assertEqual(report["asset"]["type"], "project_metric_snapshot")
            self.assertGreaterEqual(report["summary"]["drift_count"], 2)
            self.assertEqual(original["content"]["blocking_issues"][0].get("dimension"), None)
            codes = {drift["code"] for row in report["content"]["drift_rows"] for drift in row["drifts"]}
            self.assertIn("missing_dimension", codes)
            self.assertIn("missing_recommendation", codes)

    def test_drift_report_accepts_normalized_gate_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            record_gate_result(
                storage,
                gate_kind="context_governance_runtime_coverage",
                status="passed",
                target_paths=[],
                result={"coverage_report_path": "data/runs/context-coverage.json", "summary": {"blocking_count": 0}},
                project_id="gov-clean-p",
                message="passed",
                blocking=False,
            )

            report = build_production_governance_evidence_drift_report(storage, project_id="gov-clean-p", persist=False)

            self.assertEqual(report["summary"]["scanned_artifact_count"], 1)
            self.assertEqual(report["summary"]["drift_count"], 0)
            self.assertEqual(report["content"]["recommendations"], ["Production governance evidence contracts are normalized for scanned assets"])

    def test_drift_gate_fails_production_and_warns_local_for_contract_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            _bad_publish_gate(storage, "gov-gate-p")

            production = run_production_governance_drift_gate(storage, project_id="gov-gate-p", environment="production")
            local = run_production_governance_drift_gate(storage, project_id="gov-gate-p", environment="local")

            self.assertEqual(production["status"], "failed")
            self.assertTrue(production["blocking"])
            self.assertEqual(storage.read_asset(production["gate_result"]["path"]).content["status"], "failed")
            self.assertEqual(local["status"], "warning")
            self.assertFalse(local["blocking"])
            self.assertEqual(storage.read_asset(local["gate_result"]["path"]).content["status"], "warning")

    def test_drift_gate_passes_when_contracts_are_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            record_gate_result(
                storage,
                gate_kind="context_governance_runtime_coverage",
                status="passed",
                target_paths=[],
                result={"coverage_report_path": "data/runs/context-coverage.json", "summary": {"blocking_count": 0}},
                project_id="gov-gate-clean-p",
                message="passed",
                blocking=False,
            )

            gate = run_production_governance_drift_gate(storage, project_id="gov-gate-clean-p", environment="production")

            self.assertEqual(gate["status"], "passed")
            self.assertFalse(gate["blocking"])
            self.assertEqual(storage.read_asset(gate["gate_result"]["path"]).content["status"], "passed")


def _bad_publish_gate(storage: LocalStorage, project_id: str) -> None:
    storage.write_asset_auto(
        PublishGateReport(
            title="Bad publish gate",
            content={
                "target_asset_id": "draft-1",
                "gates": {"provider_runtime_gate_passed": False},
                "decision": "blocked",
                "blocking_issues": [{"severity": "high", "message": "provider missing"}],
                "required_reports": {},
                "human_override": False,
            },
            metadata={"project_id": project_id},
        )
    )


if __name__ == "__main__":
    unittest.main()
