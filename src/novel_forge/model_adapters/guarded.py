from __future__ import annotations

import time
from typing import Any

from novel_forge.model_adapters.base import ModelAdapter
from novel_forge.model_adapters.runtime import (
    evaluate_provider_runtime_guard,
    normalize_provider_usage,
    provider_runtime_guard_from_context,
)
from novel_forge.modules.agent_runs import create_agent_failure_report, guard_agent_action, record_agent_gate
from novel_forge.modules.common import resolve_path
from novel_forge.modules.runtime_ledger import record_model_call_log
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
        preflight = self._evaluate_provider_runtime_guard(operation, context_payload, usage={}, elapsed_ms=0, phase="preflight")
        if preflight.get("status") == "failed":
            self._fail_provider_runtime_guard(operation, preflight)
        started = time.monotonic()
        result = thunk()
        elapsed_ms = int((time.monotonic() - started) * 1000)
        usage = _provider_usage_from_result(result)
        postflight = self._evaluate_provider_runtime_guard(operation, context_payload, usage=usage, elapsed_ms=elapsed_ms, phase="postflight")
        if postflight.get("status") == "failed":
            self._fail_provider_runtime_guard(operation, postflight)
        self._record_model_call(operation, result, usage)
        return result

    def _evaluate_provider_runtime_guard(
        self,
        operation: str,
        context: dict[str, Any],
        *,
        usage: dict[str, Any],
        elapsed_ms: int,
        phase: str = "postflight",
    ) -> dict[str, Any]:
        context_usage = context.get("provider_usage", {}) if isinstance(context.get("provider_usage", {}), dict) else {}
        merged_usage = normalize_provider_usage({**context_usage, **usage}, elapsed_ms=elapsed_ms, usage_source="guarded_adapter")
        if elapsed_ms:
            merged_usage["elapsed_ms"] = max(int(merged_usage.get("elapsed_ms", 0) or 0), elapsed_ms)
        return evaluate_provider_runtime_guard(
            operation=operation,
            provider=self.name,
            usage=merged_usage,
            guard=provider_runtime_guard_from_context(context),
            phase=phase,
        )

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

    def _record_model_call(self, operation: str, result: Any, usage: dict[str, Any]) -> None:
        if not isinstance(result, dict):
            return
        run_info = self._agent_run_info()
        provider = str(result.get("provider") or run_info.get("model_provider") or self.name)
        model = str(result.get("model") or run_info.get("model_name") or self.name)
        normalized_usage = normalize_provider_usage(usage, usage_source="guarded_adapter")
        cost = result.get("cost") if isinstance(result.get("cost"), dict) else {"amount": 0.0, "currency": "USD", "source": "guarded_adapter"}
        try:
            call = record_model_call_log(
                self.storage,
                provider=provider,
                model=model,
                operation=operation,
                status="succeeded",
                usage=normalized_usage,
                cost=cost,
                trace=run_info.get("trace", {}) if isinstance(run_info.get("trace", {}), dict) else {},
                project_id=str(run_info.get("project_id", "")),
                workspace_path=str(run_info.get("workspace_path", "")),
                source_id=str(run_info.get("run_id", "")),
                prompt_version=str(run_info.get("prompt_version", "")),
            )
        except Exception:
            return
        result["model_call_log_path"] = call.get("path", "")
        if isinstance(call.get("cost_ledger"), dict):
            result["cost_ledger_path"] = call["cost_ledger"].get("path", "")

    def _agent_run_info(self) -> dict[str, Any]:
        try:
            data = self.storage.read_json(resolve_path(self.storage.root, self.agent_run_path))
        except Exception:
            return {}
        content = data.get("content", {}) if isinstance(data, dict) and isinstance(data.get("content", {}), dict) else {}
        metadata = data.get("metadata", {}) if isinstance(data, dict) and isinstance(data.get("metadata", {}), dict) else {}
        return {
            "run_id": content.get("run_id", ""),
            "trace": content.get("trace", {}) if isinstance(content.get("trace", {}), dict) else {},
            "model_provider": content.get("model_provider") or metadata.get("model_provider", ""),
            "model_name": content.get("model_name") or metadata.get("model_name", ""),
            "prompt_version": content.get("prompt_version") or metadata.get("prompt_version", ""),
            "project_id": metadata.get("project_id", ""),
            "workspace_path": metadata.get("workspace_path", ""),
        }


def _provider_usage_from_result(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        for key in ["provider_usage", "usage"]:
            value = result.get(key)
            if isinstance(value, dict):
                return value
    return {}
