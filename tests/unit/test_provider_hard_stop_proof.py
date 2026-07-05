from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.model_adapters.runtime import ProviderRuntimeGuard, evaluate_provider_runtime_guard
from novel_forge.modules.model_router import create_model_route, execute_model_gateway_call, provider_approval_evidence_report, resolve_model_route
from novel_forge.modules.runtime_ledger import record_gate_result, record_model_call_log
from novel_forge.modules.runtime_policy import provider_hard_stop_evidence_report
from novel_forge.storage.local import LocalStorage


class ProviderHardStopProofTests(unittest.TestCase):
    def test_provider_hard_stop_evidence_covers_token_cost_timeout_and_cancel(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            project_id = "provider-proof-p"
            cancel_file = Path(tmp) / "cancel.flag"
            cancel_file.write_text("cancel\n", encoding="utf-8")
            cases = [
                ("token", {"input_tokens": 80, "output_tokens": 40, "total_tokens": 120}, ProviderRuntimeGuard(max_total_tokens=100)),
                ("cost", {"input_tokens": 1000, "output_tokens": 1000, "total_tokens": 2000}, ProviderRuntimeGuard(max_cost=0.001, cost_profile={"per_1k": 0.01})),
                ("timeout", {"input_tokens": 10, "output_tokens": 10, "total_tokens": 20, "elapsed_ms": 100}, ProviderRuntimeGuard(timeout_ms=20)),
                ("cancel", {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}, ProviderRuntimeGuard(cancel_file=str(cancel_file))),
            ]

            for label, usage, guard in cases:
                result = evaluate_provider_runtime_guard(operation=f"proof_{label}", provider="mock", usage=usage, guard=guard)
                self.assertEqual(result["status"], "failed", label)
                record_gate_result(
                    storage,
                    gate_kind="provider_runtime_guard",
                    status="failed",
                    target_paths=[],
                    result=result,
                    trace={"trace_id": f"trace-{label}", "span_id": f"span-{label}"},
                    project_id=project_id,
                    message=result["message"],
                )
                record_model_call_log(
                    storage,
                    provider="mock",
                    model="mock-proof",
                    operation=f"proof_{label}",
                    status="failed",
                    usage=result.get("usage", {}),
                    cost={"amount": 0.0, "currency": "USD", "source": "hard_stop_proof"},
                    trace={"trace_id": f"trace-{label}", "span_id": f"span-{label}"},
                    project_id=project_id,
                )

            success = evaluate_provider_runtime_guard(
                operation="proof_success",
                provider="mock",
                usage={"input_tokens": 20, "output_tokens": 30, "total_tokens": 50, "elapsed_ms": 10},
                guard=ProviderRuntimeGuard(max_total_tokens=1000, timeout_ms=1000, max_cost=1.0, cost_profile={"per_1k": 0.01}),
            )
            self.assertEqual(success["status"], "passed")
            record_gate_result(
                storage,
                gate_kind="provider_runtime_guard",
                status="passed",
                target_paths=[],
                result=success,
                trace={"trace_id": "trace-success", "span_id": "span-success"},
                project_id=project_id,
                message=success["message"],
            )
            record_model_call_log(
                storage,
                provider="mock",
                model="mock-proof",
                operation="proof_success",
                status="succeeded",
                usage=success.get("usage", {}),
                cost={"amount": 0.0005, "currency": "USD", "source": "hard_stop_proof_success"},
                trace={"trace_id": "trace-success", "span_id": "span-success"},
                project_id=project_id,
            )

            report = provider_hard_stop_evidence_report(storage, project_id=project_id)

            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["summary"]["covered_hard_stop_dimension_count"], 4)
            self.assertEqual(report["summary"]["missing_dimensions"], [])
            self.assertEqual(report["summary"]["missing_success_evidence"], [])
            self.assertEqual(report["summary"]["successful_provider_guard_count"], 1)
            self.assertEqual(report["summary"]["successful_model_call_count"], 1)
            for dimension in ["token", "cost", "timeout", "cancel"]:
                self.assertGreaterEqual(report["summary"]["dimension_counts"][dimension], 1)
            self.assertEqual(report["summary"]["failed_model_call_count"], 4)

    def test_gateway_hard_stop_does_not_retry_or_fallback_silently(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            project_id = "provider-boundary-p"
            create_model_route(
                storage,
                task_type="draft",
                provider="primary-provider",
                model_name="primary-model",
                fallbacks=[{"provider": "fallback-provider", "model_name": "fallback-model", "reason": "manual operator fallback only"}],
                project_id=project_id,
            )

            with self.assertRaisesRegex(RuntimeError, "provider runtime guard blocked"):
                execute_model_gateway_call(
                    storage,
                    task_type="draft",
                    operation="draft",
                    project_id=project_id,
                    usage={"input_tokens": 90, "output_tokens": 40, "total_tokens": 130, "usage_source": "unit_provider"},
                    provider_runtime_guard={"max_total_tokens": 100},
                    trace={"trace_id": "trace-no-silent-fallback"},
                )

            rows = [storage.read_json(path) for path in storage.list_json("runs")]
            resolutions = [row for row in rows if row.get("type") == "model_route_resolution"]
            failed_calls = [row for row in rows if row.get("type") == "model_call_log" and row.get("content", {}).get("status") == "failed"]
            fallback_calls = [row for row in rows if row.get("type") == "model_call_log" and row.get("content", {}).get("provider") == "fallback-provider"]

            self.assertTrue(resolutions)
            self.assertEqual(resolutions[-1]["content"]["fallbacks"][0]["provider"], "fallback-provider")
            self.assertEqual(len(failed_calls), 1)
            self.assertEqual(failed_calls[0]["content"]["provider"], "primary-provider")
            self.assertEqual(fallback_calls, [])

    def test_production_model_route_requires_provider_approval_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            create_model_route(
                storage,
                task_type="draft",
                provider="openai",
                model_name="gpt-production",
                production_provider_allowlist=["openai"],
                project_id="provider-policy-p",
            )

            with self.assertRaisesRegex(ValueError, "approval evidence"):
                resolve_model_route(storage, task_type="draft", project_id="provider-policy-p", environment="production")

            resolutions = [storage.read_json(path) for path in storage.list_json("runs") if storage.read_json(path).get("type") == "model_route_resolution"]
            self.assertEqual(resolutions[-1]["content"]["status"], "blocked")
            self.assertEqual(resolutions[-1]["content"]["provider_policy"]["status"], "blocked")
            self.assertEqual(resolutions[-1]["content"]["provider_policy"]["blocking_issues"][0]["dimension"], "provider_route_approval")

    def test_production_model_route_blocks_provider_outside_allowlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            create_model_route(
                storage,
                task_type="draft",
                provider="unapproved-provider",
                model_name="model",
                production_provider_allowlist=["openai"],
                approval_status="approved",
                approval_id="approval-1",
                project_id="provider-allowlist-p",
            )

            with self.assertRaisesRegex(ValueError, "allowlist"):
                resolve_model_route(storage, task_type="draft", project_id="provider-allowlist-p", environment="production")

    def test_production_model_route_blocks_mock_without_explicit_fixture_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            create_model_route(
                storage,
                task_type="draft",
                provider="mock",
                model_name="mock-model",
                approval_status="approved",
                approval_id="approval-1",
                project_id="provider-mock-p",
            )

            with self.assertRaisesRegex(ValueError, "mock provider"):
                resolve_model_route(storage, task_type="draft", project_id="provider-mock-p", environment="production")

    def test_production_model_route_records_approval_evidence_when_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            create_model_route(
                storage,
                task_type="draft",
                provider="openai",
                model_name="gpt-production",
                production_provider_allowlist=["openai"],
                approval_status="approved",
                approval_id="approval-prod-route",
                approved_by="operator",
                approval_reason="production release candidate",
                project_id="provider-approved-p",
            )

            route = resolve_model_route(storage, task_type="draft", project_id="provider-approved-p", environment="production")
            resolution = route["resolution"]

            self.assertEqual(resolution["provider_policy"]["status"], "passed")
            self.assertFalse(resolution["provider_policy"]["blocking"])
            self.assertTrue(resolution["approval_evidence"]["approved"])
            self.assertEqual(resolution["approval_evidence"]["approval_id"], "approval-prod-route")
            self.assertEqual(resolution["environment"], "production")

    def test_production_mock_provider_requires_explicit_fixture_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            create_model_route(
                storage,
                task_type="draft",
                provider="mock",
                model_name="mock-model",
                approval_status="approved",
                approval_id="approval-fixture-route",
                mock_provider_test_mode=True,
                project_id="provider-mock-fixture-p",
            )

            route = resolve_model_route(storage, task_type="draft", project_id="provider-mock-fixture-p", environment="production")
            policy = route["resolution"]["provider_policy"]

            self.assertEqual(policy["status"], "passed")
            self.assertTrue(policy["mock_provider_fixture_mode"])
            self.assertIn("mock", policy["mock_provider_denylist"])

    def test_provider_approval_evidence_report_exposes_resolution_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            project_id = "provider-ops-report-p"
            create_model_route(
                storage,
                task_type="draft",
                provider="openai",
                model_name="gpt-production",
                production_provider_allowlist=["openai"],
                approval_status="approved",
                approval_id="approval-report-pass",
                approved_by="release-operator",
                approval_reason="ops report success fixture",
                project_id=project_id,
            )
            resolve_model_route(storage, task_type="draft", project_id=project_id, environment="production")

            create_model_route(
                storage,
                task_type="review",
                provider="mock",
                model_name="mock-model",
                approval_status="approved",
                approval_id="approval-report-block",
                project_id=project_id,
            )
            with self.assertRaisesRegex(ValueError, "mock provider"):
                resolve_model_route(storage, task_type="review", project_id=project_id, environment="production")

            report = provider_approval_evidence_report(storage, project_id=project_id)

            self.assertEqual(report["status"], "blocked")
            self.assertEqual(report["summary"]["production_resolution_count"], 2)
            self.assertEqual(report["summary"]["passed_resolution_count"], 1)
            self.assertEqual(report["summary"]["blocked_resolution_count"], 1)
            self.assertEqual(report["summary"]["mock_denied_count"], 1)
            rows_by_task = {row["task_type"]: row for row in report["rows"]}
            self.assertEqual(rows_by_task["draft"]["approval_evidence"]["approval_id"], "approval-report-pass")
            self.assertEqual(rows_by_task["draft"]["provider_policy"]["status"], "passed")
            self.assertEqual(rows_by_task["review"]["provider_policy"]["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
