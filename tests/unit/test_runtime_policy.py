from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.runtime_ledger import create_budget_policy, record_gate_result
from novel_forge.modules.runtime_policy import (
    check_runtime_policy,
    provider_hard_stop_evidence_report,
    record_runtime_model_result,
    runtime_policy_enforcement_report,
    runtime_policy_envelope,
    runtime_policy_legacy_entrypoint_audit,
    runtime_policy_surface_coverage_report,
    runtime_policy_status,
)
from novel_forge.model_adapters.runtime import ProviderRuntimeGuard, evaluate_provider_runtime_guard
from novel_forge.schemas import ChapterPlan, ContextBundle, DraftChapter
from novel_forge.storage.local import LocalStorage


class RuntimePolicyTests(unittest.TestCase):
    def test_strict_mode_blocks_missing_budget_context_and_trace(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()

            result = check_runtime_policy(
                storage,
                operation="draft",
                project_id="policy-project",
                phase="preflight",
                mode="operating_system",
                persist_gate_result=False,
            )

            self.assertEqual(result["status"], "blocked")
            self.assertTrue(result["strict"])
            self.assertIn("missing context bundle", "; ".join(result["failures"]))
            self.assertIn("missing active budget policy", "; ".join(result["failures"]))
            self.assertIn("missing trace_id", "; ".join(result["failures"]))

    def test_compat_mode_reports_warning_instead_of_blocking(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()

            result = check_runtime_policy(
                storage,
                operation="draft",
                project_id="policy-project",
                phase="preflight",
                mode="compat",
            )

            self.assertEqual(result["status"], "warning")
            self.assertFalse(result["strict"])
            self.assertEqual(result["failures"], [])
            self.assertTrue(result["warnings"])
            self.assertEqual(result["gate_result"]["asset"]["type"], "gate_result")
            self.assertEqual(result["gate_result"]["asset"]["content"]["status"], "warning")

    def test_commit_passes_with_context_budget_model_cost_and_gate_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            project_id = "policy-project"
            trace = {"trace_id": "trace-policy", "span_id": "span-policy", "parent_span_id": "trace-policy"}

            create_budget_policy(storage, scope=project_id, project_id=project_id, limits={"max_cost": 10.0, "max_tokens_per_run": 5000})
            chapter_plan = storage.write_asset_auto(
                ChapterPlan(
                    title="Chapter 1 plan",
                    content={"chapter": 1, "objective": "prove the runtime policy", "beats": ["setup", "turn"], "hook": "evidence is missing"},
                    metadata={"project_id": project_id},
                )
            )
            context_bundle = storage.write_asset_auto(
                ContextBundle(
                    title="Chapter 1 context",
                    content={
                        "build_plan_id": "plan-1",
                        "target_asset_id": "chapter-1",
                        "selected_assets": [],
                        "kg_context": {"items": [{"name": "Clock City", "ranker": "novel_kg_context"}]},
                        "compressed_context": "project-safe continuity context",
                        "token_budget": 4000,
                        "token_estimate": 200,
                        "actual_context": "project-safe continuity context",
                        "source_asset_ids": [],
                    },
                    metadata={"project_id": project_id},
                )
            )
            draft = storage.write_asset_auto(
                DraftChapter(
                    title="Chapter 1 draft",
                    content={"chapter": 1, "text": "A local deterministic draft.", "copyright_boundary": "original"},
                    metadata={"project_id": project_id},
                )
            )
            kg_gate = record_gate_result(
                storage,
                gate_kind="kg",
                status="passed",
                target_paths=[str(draft.relative_to(storage.root))],
                result={"conflicts": []},
                trace=trace,
                project_id=project_id,
            )
            review_gate = record_gate_result(
                storage,
                gate_kind="review",
                status="passed",
                target_paths=[str(draft.relative_to(storage.root))],
                result={"issues": []},
                trace=trace,
                project_id=project_id,
            )
            model_call = record_runtime_model_result(
                storage,
                operation="draft",
                provider="mock",
                model="mock-policy",
                usage={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
                cost={"amount": 0.25, "currency": "USD", "source": "unit_test"},
                trace=trace,
                project_id=project_id,
                source_id="policy-test",
            )

            result = check_runtime_policy(
                storage,
                operation="draft",
                project_id=project_id,
                input_assets=[str(chapter_plan.relative_to(storage.root))],
                output_assets=[str(draft.relative_to(storage.root))],
                context_bundle_path=str(context_bundle.relative_to(storage.root)),
                token_used=150,
                cost_estimate=0.25,
                trace=trace,
                phase="commit",
                mode="operating_system",
                model_call_log_path=model_call["path"],
                cost_ledger_paths=[model_call["cost_ledger"]["path"]],
                gate_result_paths=[kg_gate["path"], review_gate["path"]],
            )

            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["failures"], [])
            self.assertEqual(result["evidence"]["budget_policy"]["status"], "passed")
            self.assertEqual(result["evidence"]["model_call_log"]["status"], "present")
            self.assertEqual(result["evidence"]["cost_ledgers"][0]["status"], "present")
            self.assertTrue(all(item["status"] == "present" for item in result["evidence"]["gate_results"]))

            status = runtime_policy_status(storage, project_id=project_id, mode="operating_system")
            self.assertGreaterEqual(status["operation_count"], 10)
            self.assertGreaterEqual(status["evidence_counts"]["active_budget_policy"], 1)
            self.assertGreaterEqual(status["evidence_counts"]["model_call_log"], 1)
            self.assertGreaterEqual(status["evidence_counts"]["cost_ledger"], 1)

    def test_envelope_commits_runtime_evidence_and_enforcement_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            project_id = "policy-envelope-project"
            trace = {"trace_id": "trace-envelope", "span_id": "span-envelope", "parent_span_id": "trace-envelope"}
            create_budget_policy(storage, scope=project_id, project_id=project_id, limits={"max_cost": 10.0, "max_tokens_per_run": 5000})
            chapter_plan = storage.write_asset_auto(
                ChapterPlan(
                    title="Chapter plan",
                    content={"chapter": 1, "objective": "run envelope", "beats": ["setup"], "hook": "trace"},
                    metadata={"project_id": project_id},
                )
            )
            context_bundle = storage.write_asset_auto(
                ContextBundle(
                    title="Envelope context",
                    content={
                        "actual_context": "Clock City KG context",
                        "kg_context": {"items": [{"name": "Clock City", "confidence": 0.9}]},
                        "selected_assets": [],
                    },
                    metadata={"project_id": project_id},
                )
            )
            draft = storage.write_asset_auto(
                DraftChapter(
                    title="Envelope draft",
                    content={"chapter": 1, "text": "Original envelope draft.", "copyright_boundary": "original"},
                    metadata={"project_id": project_id},
                )
            )
            kg_gate = record_gate_result(storage, gate_kind="kg", status="passed", target_paths=[str(draft.relative_to(storage.root))], result={}, trace=trace, project_id=project_id)
            review_gate = record_gate_result(storage, gate_kind="review", status="passed", target_paths=[str(draft.relative_to(storage.root))], result={}, trace=trace, project_id=project_id)

            with runtime_policy_envelope(
                storage,
                operation="draft",
                project_id=project_id,
                input_assets=[str(chapter_plan.relative_to(storage.root))],
                output_assets=[str(draft.relative_to(storage.root))],
                context_bundle_path=str(context_bundle.relative_to(storage.root)),
                trace=trace,
                mode="operating_system",
            ) as envelope:
                envelope.add_gate_result(kg_gate)
                envelope.add_gate_result(review_gate)
                envelope.record_model_result(
                    provider="mock",
                    model="mock-envelope",
                    usage={"input_tokens": 100, "output_tokens": 75, "total_tokens": 175},
                    cost={"amount": 0.11, "currency": "USD", "source": "unit_test"},
                    source_id="envelope-test",
                )

            self.assertEqual(envelope.commit_result["status"], "passed")
            report = runtime_policy_enforcement_report(storage, project_id=project_id, mode="operating_system")
            draft_row = [row for row in report["operations"] if row["operation"] == "draft"][0]
            self.assertEqual(draft_row["status"], "covered")
            self.assertGreaterEqual(draft_row["model_call_count"], 1)
            self.assertGreaterEqual(report["summary"]["trace_span_count"], 1)

    def test_legacy_entrypoint_audit_flags_direct_model_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "src" / "novel_forge" / "modules"
            src.mkdir(parents=True)
            direct = src / "legacy_service.py"
            direct.write_text("def run(adapter):\n    return adapter.generate('x')\n", encoding="utf-8")
            covered = src / "covered_service.py"
            covered.write_text("from novel_forge.modules.runtime_policy import runtime_policy_envelope\n\ndef run(adapter):\n    with runtime_policy_envelope:\n        return adapter.generate('x')\n", encoding="utf-8")

            audit = runtime_policy_legacy_entrypoint_audit(repo_root=root)

            rows = {row["path"]: row for row in audit["entrypoints"]}
            self.assertEqual(rows["src/novel_forge/modules/legacy_service.py"]["status"], "review_required")
            self.assertEqual(rows["src/novel_forge/modules/covered_service.py"]["status"], "covered")
            self.assertEqual(audit["summary"]["review_required_count"], 1)

    def test_provider_hard_stop_report_counts_only_triggered_dimensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            trace = {"trace_id": "trace-hard-stop", "span_id": "span-hard-stop"}
            result = evaluate_provider_runtime_guard(
                operation="draft",
                provider="local-provider",
                usage={"input_tokens": 1000, "output_tokens": 1000, "total_tokens": 2000},
                guard=ProviderRuntimeGuard(max_cost=0.001, cost_profile={"per_1k": 0.01}),
            )
            record_gate_result(
                storage,
                gate_kind="provider_runtime_guard",
                status="failed",
                target_paths=[],
                result=result,
                trace=trace,
                project_id="policy-project",
                message=result["message"],
            )

            report = provider_hard_stop_evidence_report(storage, project_id="policy-project")

            self.assertEqual(report["summary"]["dimension_counts"]["cost"], 1)
            self.assertEqual(report["summary"]["dimension_counts"]["token"], 0)
            self.assertIn("token", report["summary"]["missing_dimensions"])
            self.assertEqual(report["provider_gates"][0]["observed_dimensions"], ["cost"])

    def test_surface_coverage_report_exposes_operator_matrix(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            report = runtime_policy_surface_coverage_report(storage, mode="compat", repo_root=Path(tmp))

            self.assertIn("surface_matrix", report)
            self.assertTrue(any(row["operation"] == "draft" for row in report["surface_matrix"]))
            self.assertIn(report["status"], {"passed", "warning"})
            self.assertIn("provider_hard_stop_evidence", report)


if __name__ == "__main__":
    unittest.main()
