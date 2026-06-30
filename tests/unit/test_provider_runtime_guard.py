from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.model_adapters.runtime import (
    ProviderRuntimeGuard,
    ProviderRuntimeGuardViolation,
    estimate_provider_cost,
    estimate_usage_from_text,
    evaluate_provider_runtime_guard,
    normalize_provider_usage,
    provider_runtime_controller,
    provider_runtime_guard_from_context,
)
from novel_forge.model_adapters.guarded import GuardedModelAdapter, ProviderRuntimeGuardError
from novel_forge.model_adapters.providers import ChatGPTAdapter, _read_openai_compatible_stream, _streaming_enabled
from novel_forge.modules.agent_runs import AgentExecutionContext
from novel_forge.storage.local import LocalStorage


class UsageReportingAdapter:
    name = "usage-adapter"

    def generate(self, prompt, context=None):
        return {
            "text": f"generated: {prompt}",
            "provider": "usage-provider",
            "model": "usage-model",
            "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30, "usage_source": "unit_provider"},
        }


class OverBudgetUsageAdapter:
    name = "over-budget-adapter"

    def generate(self, prompt, context=None):
        return {
            "text": f"generated: {prompt}",
            "provider": "usage-provider",
            "model": "usage-model",
            "usage": {"input_tokens": 10, "output_tokens": 200, "total_tokens": 210, "usage_source": "unit_provider"},
        }


class ProviderRuntimeGuardTests(unittest.TestCase):
    def test_normalizes_openai_compatible_usage_shape(self):
        usage = normalize_provider_usage(
            {
                "prompt_tokens": 120,
                "completion_tokens": 80,
                "total_tokens": 200,
                "prompt_tokens_details": {"cached_tokens": 20},
                "completion_tokens_details": {"reasoning_tokens": 5},
            },
            elapsed_ms=30,
            usage_source="provider",
        )

        self.assertEqual(usage["input_tokens"], 120)
        self.assertEqual(usage["output_tokens"], 80)
        self.assertEqual(usage["total_tokens"], 200)
        self.assertEqual(usage["cached_tokens"], 20)
        self.assertEqual(usage["reasoning_tokens"], 5)
        self.assertEqual(usage["elapsed_ms"], 30)
        self.assertEqual(usage["usage_source"], "provider")

    def test_estimates_cost_from_profile(self):
        usage = {"input_tokens": 1000, "output_tokens": 500, "total_tokens": 1500}
        cost = estimate_provider_cost(usage, {"input_per_1k": 0.01, "output_per_1k": 0.02, "currency": "USD"})

        self.assertEqual(cost["amount"], 0.02)
        self.assertEqual(cost["currency"], "USD")
        self.assertEqual(cost["source"], "provider_usage")

    def test_guard_blocks_token_timeout_and_cancel_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            cancel_file = Path(tmp) / "cancel.flag"
            cancel_file.write_text("cancel\n", encoding="utf-8")
            guard = ProviderRuntimeGuard(max_total_tokens=100, timeout_ms=50, cancel_file=str(cancel_file))

            result = evaluate_provider_runtime_guard(
                operation="draft",
                provider="mock",
                usage={"input_tokens": 80, "output_tokens": 60, "elapsed_ms": 90},
                guard=guard,
            )

            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["error_type"], "ProviderTimeoutExceeded")
            self.assertIn("provider execution cancellation requested", result["message"])
            self.assertIn("provider token cutoff exceeded", result["message"])
            self.assertIn("provider timeout exceeded", result["message"])
            event_types = {event["event_type"] for event in result["events"]}
            self.assertIn("provider_cancel_requested", event_types)
            self.assertIn("provider_token_cutoff", event_types)
            self.assertIn("provider_timeout", event_types)

    def test_context_guard_and_usage_estimation(self):
        guard = provider_runtime_guard_from_context({"provider_runtime_guard": {"max_tokens": 1000, "cost_profile": {"per_1k": 0.01}}})
        usage = estimate_usage_from_text("abcd" * 100, "efgh" * 50, usage_source="estimated")
        result = evaluate_provider_runtime_guard(operation="review", provider="mock", usage=usage, guard=guard)

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["usage"]["usage_source"], "estimated")
        self.assertEqual(result["guard"]["max_total_tokens"], 1000)
        self.assertIn("provider_call_finished", {event["event_type"] for event in result["events"]})

    def test_runtime_controller_streaming_delta_cuts_off_live_usage(self):
        controller = provider_runtime_controller(
            operation="draft",
            provider="mock",
            guard=ProviderRuntimeGuard(max_total_tokens=100),
        )
        controller.start()
        controller.observe_usage_delta({"input_tokens": 30, "output_tokens": 20, "usage_source": "provider_stream"})

        with self.assertRaises(ProviderRuntimeGuardViolation):
            controller.observe_usage_delta({"output_tokens": 60, "usage_source": "provider_stream"})

        payload = controller.to_dict()
        self.assertEqual(payload["status"], "failed")
        self.assertGreaterEqual(payload["usage"]["total_tokens"], 110)
        self.assertIn("provider_token_cutoff", {event["event_type"] for event in payload["events"]})

    def test_openai_compatible_stream_reader_observes_usage_and_content(self):
        controller = provider_runtime_controller(
            operation="draft",
            provider="chatgpt",
            guard=ProviderRuntimeGuard(max_total_tokens=1000),
        )
        controller.start()
        response = [
            b'data: {"choices":[{"delta":{"content":"{\\"text\\":\\"hello"},"finish_reason":null}]}\n\n',
            b'data: {"choices":[{"delta":{"content":" world\\"}"},"finish_reason":"stop"}],"usage":{"prompt_tokens":12,"completion_tokens":8,"total_tokens":20}}\n\n',
            b"data: [DONE]\n\n",
        ]

        result = _read_openai_compatible_stream(response, controller=controller, operation="draft", provider="chatgpt")

        self.assertEqual(result["choices"][0]["message"]["content"], '{"text":"hello world"}')
        self.assertEqual(result["usage"]["total_tokens"], 20)
        self.assertTrue(result["stream"]["enabled"])
        self.assertIn("provider_stream_guard_ok", {event["event_type"] for event in controller.to_dict()["events"]})

    def test_openai_compatible_streaming_auto_enables_for_live_guard_and_can_be_overridden(self):
        with patch.dict("os.environ", {"NOVEL_FORGE_PROVIDER_STREAMING": ""}):
            self.assertTrue(_streaming_enabled({"provider_runtime_guard": {"max_output_tokens": 32}}))
            self.assertTrue(_streaming_enabled({"provider_runtime_guard": {"cancel_file": "/tmp/novel-forge-cancel.flag"}}))
            self.assertFalse(_streaming_enabled({"stream": False, "provider_runtime_guard": {"max_total_tokens": 32}}))

            health = ChatGPTAdapter().health_check()
        capabilities = health["runtime_capabilities"]
        self.assertTrue(capabilities["live_streaming"]["supported"])
        self.assertEqual(capabilities["live_streaming"]["transport"], "json_postflight")
        self.assertEqual(capabilities["live_cancel"]["mechanism"], "postflight_guard_only")

    def test_guarded_adapter_persists_provider_gate_checkpoint_model_call_and_cost(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()

            with AgentExecutionContext(
                storage,
                agent_key="draft",
                operation="draft",
                output_types=["draft_chapter"],
                model_provider="usage-provider",
                model_name="usage-model",
            ) as run:
                adapter = GuardedModelAdapter(UsageReportingAdapter(), storage, run.path)
                result = adapter.generate(
                    "chapter prompt",
                    {
                        "runtime_operation": "draft",
                        "provider_runtime_guard": {
                            "max_total_tokens": 1000,
                            "cost_profile": {"input_per_1k": 0.01, "output_per_1k": 0.02, "currency": "USD"},
                        },
                    },
                )

            self.assertIn("/runs/", result["model_call_log_path"])
            self.assertIn("/runs/", result["cost_ledger_path"])
            rows = [storage.read_json(path) for path in storage.list_json("runs")]
            checkpoints = [row for row in rows if row.get("type") == "agent_checkpoint"]
            stages = {row["content"]["stage"] for row in checkpoints if row.get("content", {}).get("operation") == "draft"}
            self.assertTrue({"prompt_built", "provider_started", "provider_completed", "output_validated"}.issubset(stages))
            provider_gates = [row for row in rows if row.get("type") == "gate_result" and row.get("content", {}).get("gate_kind") == "provider_runtime_guard"]
            self.assertTrue(provider_gates)
            route_resolutions = [row for row in rows if row.get("type") == "model_route_resolution" and row.get("content", {}).get("task_type") == "draft"]
            self.assertTrue(route_resolutions)
            model_calls = [row for row in rows if row.get("type") == "model_call_log" and row.get("content", {}).get("operation") == "draft"]
            self.assertEqual(model_calls[-1]["content"]["status"], "succeeded")
            self.assertEqual(model_calls[-1]["content"]["source_id"], result["model_route_resolution_path"])

    def test_guarded_adapter_records_failed_model_call_when_postflight_guard_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()

            with AgentExecutionContext(
                storage,
                agent_key="draft",
                operation="draft",
                output_types=["draft_chapter"],
                model_provider="usage-provider",
                model_name="usage-model",
            ) as run:
                adapter = GuardedModelAdapter(OverBudgetUsageAdapter(), storage, run.path)
                with self.assertRaises(ProviderRuntimeGuardError):
                    adapter.generate(
                        "chapter prompt",
                        {
                            "runtime_operation": "draft",
                            "provider_runtime_guard": {"max_total_tokens": 100},
                        },
                    )

            rows = [storage.read_json(path) for path in storage.list_json("runs")]
            failed_gates = [
                row
                for row in rows
                if row.get("type") == "gate_result"
                and row.get("content", {}).get("gate_kind") == "provider_runtime_guard"
                and row.get("content", {}).get("status") == "failed"
            ]
            failed_calls = [row for row in rows if row.get("type") == "model_call_log" and row.get("content", {}).get("status") == "failed"]
            self.assertTrue(failed_gates)
            self.assertTrue(failed_calls)


if __name__ == "__main__":
    unittest.main()
