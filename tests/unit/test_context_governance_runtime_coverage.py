from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.context_builder import build_context_governance_runtime_coverage_report, run_context_governance_coverage_gate
from novel_forge.schemas import (
    AgentRun,
    ChapterProductionRun,
    ContextBundle,
    MKAOSSelectorGovernanceBindingApplicationReport,
    MKAOSSelectorGovernanceReport,
    NodeRun,
)
from novel_forge.storage.local import LocalStorage


NOW = "2026-07-08T00:00:00+00:00"


class ContextGovernanceRuntimeCoverageTests(unittest.TestCase):
    def _binding_refs(self, storage: LocalStorage, *, project_id: str = "coverage-p") -> dict[str, str]:
        report_path = storage.write_asset(
            "runs",
            MKAOSSelectorGovernanceReport(
                title="Coverage selector governance report",
                content={
                    "selector_governance_report_id": "selector-governance-report-coverage",
                    "selector_policy_patch": {"weights": {"coverage": 1.0}},
                    "refresh_contract": {"selector_refresh_only": True, "raw_source_text_included": False},
                    "generated_at": NOW,
                },
                metadata={"project_id": project_id},
            ),
        )
        report_ref = str(report_path.relative_to(storage.root))
        application_path = storage.write_asset(
            "runs",
            MKAOSSelectorGovernanceBindingApplicationReport(
                title="Coverage selector governance binding application",
                content={
                    "binding_application_id": "selector-governance-binding-application-coverage",
                    "binding_proposal_path": "data/runs/selector-governance-binding-proposal-coverage.json",
                    "selector_governance_report_path": report_ref,
                    "context_builder_payload_patch": {
                        "selector_governance_report_path": report_ref,
                        "selector_governance_binding_application_report_id": "selector-governance-binding-application-coverage",
                    },
                    "status": "applied",
                    "application_contract": {
                        "approval_verified": True,
                        "context_build_executed": False,
                        "context_bundle_mutated": False,
                        "payload_patch_only": True,
                    },
                    "created_at": NOW,
                },
                metadata={"project_id": project_id, "asset_status": "applied"},
                references=[report_ref],
            ),
        )
        return {"report_path": report_ref, "application_path": str(application_path.relative_to(storage.root))}

    def test_runtime_coverage_classifies_governed_gaps_and_legacy_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            refs = self._binding_refs(storage)
            binding = {
                "application_report_path": refs["application_path"],
                "selector_governance_report_path": refs["report_path"],
            }
            governed_context = storage.write_asset(
                "contexts",
                ContextBundle(
                    title="Governed context",
                    content={
                        "build_plan_id": "plan-governed",
                        "target_asset_id": "chapter-1",
                        "selected_assets": [],
                        "compressed_context": {},
                        "token_budget": {"max_tokens": 1000},
                        "token_estimate": 10,
                        "actual_context": "governed context",
                        "source_asset_ids": [],
                        "knowledge_context_contract": {
                            "selector_governance": {"report_path": refs["report_path"]},
                            "selector_governance_binding_application": binding,
                        },
                        "selector_governance_binding_application": binding,
                    },
                    metadata={
                        "project_id": "coverage-p",
                        "selector_governance_report_path": refs["report_path"],
                        "selector_governance_binding_application_path": refs["application_path"],
                    },
                    references=[refs["report_path"], refs["application_path"]],
                ),
            )
            storage.write_asset(
                "contexts",
                ContextBundle(
                    title="Missing binding context",
                    content={
                        "build_plan_id": "plan-missing",
                        "target_asset_id": "chapter-2",
                        "selected_assets": [],
                        "compressed_context": {},
                        "token_budget": {"max_tokens": 1000},
                        "token_estimate": 10,
                        "actual_context": "selector report without binding",
                        "source_asset_ids": [],
                        "knowledge_context_contract": {"selector_governance": {"report_path": refs["report_path"]}},
                    },
                    metadata={"project_id": "coverage-p", "selector_governance_report_path": refs["report_path"]},
                ),
            )
            storage.write_asset(
                "contexts",
                ContextBundle(
                    title="Legacy context",
                    content={
                        "build_plan_id": "plan-legacy",
                        "target_asset_id": "chapter-3",
                        "selected_assets": [],
                        "compressed_context": {},
                        "token_budget": {"max_tokens": 1000},
                        "token_estimate": 10,
                        "actual_context": "legacy local context",
                        "source_asset_ids": [],
                    },
                    metadata={"project_id": "coverage-p"},
                ),
            )
            storage.write_asset(
                "runs",
                ChapterProductionRun(
                    title="Governed chapter production run",
                    content={
                        "run_id": "chapter-run-governed",
                        "status": "succeeded",
                        "current_step": "context_bundle",
                        "chapter": 1,
                        "step_order": ["context_bundle"],
                        "steps": {},
                        "timeline": [],
                        "outputs": {
                            "context_bundle_path": str(governed_context.relative_to(storage.root)),
                            "selector_governance_report_path": refs["report_path"],
                            "selector_governance_binding_application_report_path": refs["application_path"],
                        },
                        "created_at": NOW,
                        "updated_at": NOW,
                    },
                    metadata={"project_id": "coverage-p"},
                    references=[refs["report_path"], refs["application_path"]],
                ),
            )
            storage.write_asset(
                "runs",
                NodeRun(
                    title="Governed workflow node",
                    content={
                        "run_id": "workflow-run-governed",
                        "node_id": "draft",
                        "node_type": "generation",
                        "operation": "draft",
                        "status": "succeeded",
                        "input_assets": [str(governed_context.relative_to(storage.root))],
                        "output_assets": [],
                        "processor": {
                            "runtime_policy": {"mode": "operating_system"},
                            "runtime_policy_evidence": {
                                "selector_governance_report_path": refs["report_path"],
                                "selector_governance_binding_application_report_path": refs["application_path"],
                            },
                        },
                        "started_at": NOW,
                        "finished_at": NOW,
                    },
                    metadata={"project_id": "coverage-p"},
                    references=[refs["report_path"], refs["application_path"]],
                ),
            )
            storage.write_asset(
                "runs",
                AgentRun(
                    title="Governed agent run",
                    content={
                        "run_id": "agent-run-governed",
                        "agent_type": "context",
                        "operation": "build-context-bundle",
                        "status": "succeeded",
                        "input_assets": [],
                        "output_assets": [str(governed_context.relative_to(storage.root))],
                        "contract_id": "context-contract",
                        "permissions": {},
                        "started_at": NOW,
                        "runtime_policy": {"mode": "operating_system"},
                        "evidence": {
                            "selector_governance_report_path": refs["report_path"],
                            "selector_governance_binding_application_report_path": refs["application_path"],
                        },
                    },
                    metadata={"project_id": "coverage-p"},
                    references=[refs["report_path"], refs["application_path"]],
                ),
            )

            report = build_context_governance_runtime_coverage_report(storage, project_id="coverage-p", persist=True)

            self.assertEqual(report["snapshot_kind"], "context_governance_runtime_coverage")
            self.assertTrue(report["path"])
            self.assertEqual(storage.read_asset(report["path"]).type, "project_metric_snapshot")
            self.assertGreaterEqual(report["summary"]["governed_count"], 4)
            self.assertEqual(report["summary"]["gap_count"], 1)
            self.assertEqual(report["summary"]["blocking_count"], 1)
            self.assertGreaterEqual(report["summary"]["local_legacy_count"], 1)
            statuses = {row["coverage_status"] for row in report["rows"]}
            self.assertIn("governed", statuses)
            self.assertIn("missing_binding", statuses)
            self.assertIn("local_legacy", statuses)
            self.assertFalse(report["source_isolation"]["raw_source_text_included"])

    def test_coverage_gate_fails_production_and_warns_local_for_blockers(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            refs = self._binding_refs(storage)
            storage.write_asset(
                "contexts",
                ContextBundle(
                    title="Missing binding context",
                    content={
                        "build_plan_id": "plan-missing",
                        "target_asset_id": "chapter-2",
                        "selected_assets": [],
                        "compressed_context": {},
                        "token_budget": {"max_tokens": 1000},
                        "token_estimate": 10,
                        "actual_context": "selector report without binding",
                        "source_asset_ids": [],
                        "knowledge_context_contract": {"selector_governance": {"report_path": refs["report_path"]}},
                    },
                    metadata={"project_id": "coverage-p", "selector_governance_report_path": refs["report_path"]},
                ),
            )

            production = run_context_governance_coverage_gate(storage, project_id="coverage-p", environment="production")
            local = run_context_governance_coverage_gate(storage, project_id="coverage-p", environment="local")

            self.assertEqual(production["status"], "failed")
            self.assertTrue(production["blocking"])
            self.assertEqual(storage.read_asset(production["gate_result"]["path"]).content["status"], "failed")
            self.assertEqual(local["status"], "warning")
            self.assertFalse(local["blocking"])
            self.assertEqual(storage.read_asset(local["gate_result"]["path"]).content["status"], "warning")

    def test_coverage_gate_passes_when_production_rows_are_governed(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            refs = self._binding_refs(storage)
            binding = {
                "application_report_path": refs["application_path"],
                "selector_governance_report_path": refs["report_path"],
            }
            storage.write_asset(
                "contexts",
                ContextBundle(
                    title="Governed context",
                    content={
                        "build_plan_id": "plan-governed",
                        "target_asset_id": "chapter-1",
                        "selected_assets": [],
                        "compressed_context": {},
                        "token_budget": {"max_tokens": 1000},
                        "token_estimate": 10,
                        "actual_context": "governed context",
                        "source_asset_ids": [],
                        "knowledge_context_contract": {
                            "selector_governance": {"report_path": refs["report_path"]},
                            "selector_governance_binding_application": binding,
                        },
                        "selector_governance_binding_application": binding,
                    },
                    metadata={
                        "project_id": "coverage-p",
                        "selector_governance_report_path": refs["report_path"],
                        "selector_governance_binding_application_path": refs["application_path"],
                    },
                    references=[refs["report_path"], refs["application_path"]],
                ),
            )

            gate = run_context_governance_coverage_gate(storage, project_id="coverage-p", environment="production")

            self.assertEqual(gate["status"], "passed")
            self.assertFalse(gate["blocking"])
            self.assertEqual(storage.read_asset(gate["gate_result"]["path"]).content["status"], "passed")


if __name__ == "__main__":
    unittest.main()
