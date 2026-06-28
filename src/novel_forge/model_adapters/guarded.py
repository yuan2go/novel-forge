from __future__ import annotations

import time
from typing import Any

from novel_forge.model_adapters.base import ModelAdapter
from novel_forge.modules.agent_runs import create_agent_failure_report, guard_agent_action, record_agent_gate
from novel_forge.storage.local import LocalStorage


class ProviderRuntimeGuardError(RuntimeError):
    """Raised when provider usage violates a runtime guard contract."""


class GuardedModelAdapter:
    """Model adapter boundary that records Agent allowlist gates before every call."""

    def __init__(self, adapter: ModelAdapter, storage: LocalStorage, agent_run_path: str) -> None:
        self.adapter = adapter
        self.storage = storage
        self.agent_run_path = agent_run_path
        self.name = getattr(adapter, "name", adapter.__class__.__name__)

    def generate(self, prompt: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._call("generate", context, lambda: self.adapter.generate(prompt, context))

    def analyze(self, text: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._call("analyze", context, lambda: self.adapter.analyze(text, context))

    def review(self, content: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._call("review", context, lambda: self.adapter.review(content, context))

    def revise(self, content: str, review: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._call("revise", context, lambda: self.adapter.revise(content, review, context))

    def batch(self, prompts: list[str], context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return self._call("batch", context, lambda: self.adapter.batch(prompts, context))

    def health_check(self) -> dict[str, Any]:
        if hasattr(self.adapter, "health_check"):
            return self.adapter.health_check()
        return {"ok": True, "provider": self.name, "model": self.name}

    def _guard(self) -> None:
        guard_agent_action(self.storage, self.agent_run_path, tool_name="call_model_adapter")

    def _call(self, operation: str, context: dict[str, Any] | None, thunk: Any) -> Any:
        self._guard()
        context_payload = context or {}
        preflight = self._evaluate_provider_runtime_guard(operation, context_payload, usage={}, elapsed_ms=0)
        if preflight.get("status") == "failed":
            self._fail_provider_runtime_guard(operation, preflight)
        started = time.monotonic()
        result = thunk()
        elapsed_ms = int((time.monotonic() - started) * 1000)
        usage = _provider_usage_from_result(result)
        postflight = self._evaluate_provider_runtime_guard(operation, context_payload, usage=usage, elapsed_ms=elapsed_ms)
        if postflight.get("status") == "failed":
            self._fail_provider_runtime_guard(operation, postflight)
        return result

    def _evaluate_provider_runtime_guard(
        self,
        operation: str,
        context: dict[str, Any],
        *,
        usage: dict[str, Any],
        elapsed_ms: int,
    ) -> dict[str, Any]:
        guard = context.get("provider_runtime_guard", context.get("runtime_guard", {})) if isinstance(context, dict) else {}
        if not isinstance(guard, dict):
            guard = {}
        context_usage = context.get("provider_usage", {}) if isinstance(context.get("provider_usage", {}), dict) else {}
        merged_usage = {**context_usage, **usage}
        if elapsed_ms:
            merged_usage["elapsed_ms"] = max(int(merged_usage.get("elapsed_ms", 0) or 0), elapsed_ms)
        failures: list[str] = []
        error_type = "ProviderRuntimeGuardFailed"
        if bool(guard.get("cancel_requested", False) or merged_usage.get("cancel_requested", False)):
            failures.append("provider execution cancellation requested")
            error_type = "ProviderExecutionCancelled"
        max_tokens = int(guard.get("max_tokens", guard.get("token_cutoff", 0)) or 0)
        total_tokens = int(merged_usage.get("total_tokens", 0) or 0)
        if total_tokens <= 0:
            total_tokens = int(merged_usage.get("input_tokens", 0) or 0) + int(merged_usage.get("output_tokens", 0) or 0)
        if max_tokens > 0 and total_tokens > max_tokens:
            failures.append(f"provider token cutoff exceeded: used {total_tokens}, limit {max_tokens}")
            error_type = "ProviderTokenCutoffExceeded"
        timeout_ms = int(guard.get("timeout_ms", guard.get("max_elapsed_ms", 0)) or 0)
        actual_elapsed_ms = int(merged_usage.get("elapsed_ms", elapsed_ms) or 0)
        if timeout_ms > 0 and actual_elapsed_ms > timeout_ms:
            failures.append(f"provider timeout exceeded: elapsed {actual_elapsed_ms}ms, limit {timeout_ms}ms")
            error_type = "ProviderTimeoutExceeded"
        if not failures:
            return {"status": "passed", "operation": operation, "usage": merged_usage, "guard": guard}
        return {
            "status": "failed",
            "operation": operation,
            "message": "; ".join(failures),
            "usage": merged_usage,
            "guard": guard,
            "error_type": error_type,
            "provider": self.name,
        }

    def _fail_provider_runtime_guard(self, operation: str, result: dict[str, Any]) -> None:
        record_agent_gate(
            self.storage,
            agent_run_path=self.agent_run_path,
            gate_type="provider_runtime_guard",
            status="failed",
            result=result,
        )
        create_agent_failure_report(
            self.storage,
            agent_run_path=self.agent_run_path,
            error_type=str(result.get("error_type") or "ProviderRuntimeGuardFailed"),
            error_message=str(result.get("message") or "provider runtime guard failed"),
            recovery_instruction=f"Reduce provider usage or route {operation} through a smaller context before retrying.",
        )
        raise ProviderRuntimeGuardError(str(result.get("message") or "provider runtime guard failed"))


def _provider_usage_from_result(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        for key in ["provider_usage", "usage"]:
            value = result.get(key)
            if isinstance(value, dict):
                return value
    return {}
