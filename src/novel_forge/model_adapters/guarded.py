from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from novel_forge.model_adapters.base import ModelAdapter
from novel_forge.model_adapters.runtime import (
    estimate_provider_cost,
    evaluate_provider_runtime_guard,
    normalize_provider_usage,
    provider_runtime_guard_from_context,
)
from novel_forge.modules.agent_runs import create_agent_failure_report, guard_agent_action, record_agent_gate
from novel_forge.modules.common import resolve_path
from novel_forge.modules.operation_checkpoint import checkpoint_idempotency_key, record_operation_stage_checkpoint, record_raw_output_segment
from novel_forge.modules.runtime_ledger import record_gate_result, record_model_call_log
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
        return self._call("generate", context, lambda: self.adapter.generate(prompt, context), prompt_payload=prompt)

    def analyze(self, text: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._call("analyze", context, lambda: self.adapter.analyze(text, context), prompt_payload=text)

    def review(self, content: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._call("review", context, lambda: self.adapter.review(content, context), prompt_payload=content)

    def revise(self, content: str, review: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._call("revise", context, lambda: self.adapter.revise(content, review, context), prompt_payload={"content": content, "review": review})

    def batch(self, prompts: list[str], context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return self._call("batch", context, lambda: self.adapter.batch(prompts, context), prompt_payload=prompts)

    def health_check(self) -> dict[str, Any]:
        if hasattr(self.adapter, "health_check"):
            return self.adapter.health_check()
        return {"ok": True, "provider": self.name, "model": self.name}

    def _guard(self) -> None:
        guard_agent_action(self.storage, self.agent_run_path, tool_name="call_model_adapter")

    def _call(self, operation: str, context: dict[str, Any] | None, thunk: Any, *, prompt_payload: Any = "") -> Any:
        self._guard()
        context_payload = context or {}
        run_info = self._agent_run_info()
        runtime_operation = _runtime_operation(operation, context_payload, run_info)
        model_route = self._resolve_model_route(runtime_operation, context_payload, run_info)
        checkpoint_common = self._checkpoint_common(runtime_operation, context_payload, run_info, prompt_payload, model_route=model_route)
        self._record_stage_checkpoint("prompt_built", checkpoint_common, stage_payload={"model_route": model_route})
        preflight = self._evaluate_provider_runtime_guard(runtime_operation, context_payload, usage={}, elapsed_ms=0, phase="preflight")
        if preflight.get("status") == "failed":
            self._record_stage_checkpoint("provider_started", checkpoint_common, error=str(preflight.get("message", "")), stage_payload={"guard": preflight})
            self._record_provider_guard_gate(runtime_operation, preflight, run_info, status="failed")
            self._record_failed_model_call(runtime_operation, run_info, preflight, usage={}, model_route=model_route)
            self._fail_provider_runtime_guard(runtime_operation, preflight)
        self._record_provider_guard_gate(runtime_operation, preflight, run_info, status="passed")
        self._record_stage_checkpoint("provider_started", checkpoint_common, stage_payload={"guard": preflight})
        started = time.monotonic()
        try:
            result = thunk()
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            usage = normalize_provider_usage({}, elapsed_ms=elapsed_ms, usage_source="guarded_adapter_exception")
            failure = {"status": "failed", "message": str(exc), "usage": usage, "error_type": type(exc).__name__}
            self._record_stage_checkpoint("provider_started", checkpoint_common, error=str(exc), stage_payload={"error_type": type(exc).__name__})
            self._record_provider_guard_gate(runtime_operation, failure, run_info, status="failed")
            self._record_failed_model_call(runtime_operation, run_info, failure, usage=usage, model_route=model_route)
            raise
        elapsed_ms = int((time.monotonic() - started) * 1000)
        usage = _provider_usage_from_result(result)
        raw_output_segments = self._record_raw_output_segments(runtime_operation, result, checkpoint_common, run_info)
        checkpoint_with_output = {**checkpoint_common, "raw_output_segments": raw_output_segments}
        postflight = self._evaluate_provider_runtime_guard(runtime_operation, context_payload, usage=usage, elapsed_ms=elapsed_ms, phase="postflight")
        if postflight.get("status") == "failed":
            self._record_stage_checkpoint("provider_completed", checkpoint_with_output, error=str(postflight.get("message", "")), stage_payload={"guard": postflight, "usage": postflight.get("usage", {})})
            self._record_provider_guard_gate(runtime_operation, postflight, run_info, status="failed")
            self._record_failed_model_call(runtime_operation, run_info, postflight, usage=postflight.get("usage", usage), model_route=model_route)
            self._fail_provider_runtime_guard(runtime_operation, postflight)
        self._record_provider_guard_gate(runtime_operation, postflight, run_info, status="passed")
        self._record_stage_checkpoint("provider_completed", checkpoint_with_output, stage_payload={"guard": postflight, "usage": postflight.get("usage", usage)})
        self._record_model_call(runtime_operation, result, usage, context_payload=context_payload, run_info=run_info, model_route=model_route)
        self._record_stage_checkpoint(
            "output_validated",
            checkpoint_with_output,
            stage_payload={
                "model_call_log_path": result.get("model_call_log_path", "") if isinstance(result, dict) else "",
                "usage": postflight.get("usage", usage),
                "raw_output_segments": raw_output_segments,
            },
        )
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

    def _record_model_call(self, operation: str, result: Any, usage: dict[str, Any], *, context_payload: dict[str, Any], run_info: dict[str, Any], model_route: dict[str, Any]) -> None:
        if not isinstance(result, dict):
            return
        provider = str(result.get("provider") or run_info.get("model_provider") or self.name)
        model = str(result.get("model") or run_info.get("model_name") or self.name)
        normalized_usage = normalize_provider_usage(usage, usage_source="guarded_adapter")
        cost = _cost_from_result(result, normalized_usage, context_payload)
        trace = run_info.get("trace", {}) if isinstance(run_info.get("trace", {}), dict) else {}
        project_scoped = _is_project_scoped_run(run_info)
        source_id = str((run_info.get("run_id") or trace.get("trace_id") or self.agent_run_path) if project_scoped else (model_route.get("path") or run_info.get("run_id", "")))
        try:
            call = record_model_call_log(
                self.storage,
                provider=provider,
                model=model,
                operation=operation,
                status="succeeded",
                usage=normalized_usage,
                cost=cost,
                trace=trace,
                project_id=str(run_info.get("project_id", "")),
                workspace_path=str(run_info.get("workspace_path", "")),
                source_id=source_id,
                prompt_version=str(run_info.get("prompt_version", "")),
            )
        except Exception:
            return
        result["model_call_log_path"] = call.get("path", "")
        result["model_route_resolution_path"] = str(model_route.get("path", ""))
        result["model_route_provider"] = str(model_route.get("provider", ""))
        result["model_route_model"] = str(model_route.get("model_name", ""))
        if isinstance(call.get("cost_ledger"), dict):
            result["cost_ledger_path"] = call["cost_ledger"].get("path", "")

    def _record_failed_model_call(self, operation: str, run_info: dict[str, Any], failure: dict[str, Any], *, usage: dict[str, Any], model_route: dict[str, Any] | None = None) -> None:
        provider = str(run_info.get("model_provider") or self.name)
        model = str(run_info.get("model_name") or self.name)
        route = model_route or {}
        try:
            trace = run_info.get("trace", {}) if isinstance(run_info.get("trace", {}), dict) else {}
            record_model_call_log(
                self.storage,
                provider=provider,
                model=model,
                operation=operation,
                status="failed",
                usage=normalize_provider_usage(usage or failure.get("usage", {}), usage_source="guarded_adapter_failed"),
                cost={"amount": 0.0, "currency": "USD", "source": "guarded_adapter_failed"},
                trace=trace,
                project_id=str(run_info.get("project_id", "")),
                workspace_path=str(run_info.get("workspace_path", "")),
                source_id=str((run_info.get("run_id") or trace.get("trace_id") or self.agent_run_path) if _is_project_scoped_run(run_info) else (route.get("path") or run_info.get("run_id", ""))),
                prompt_version=str(run_info.get("prompt_version", "")),
            )
        except Exception:
            return

    def _record_provider_guard_gate(self, operation: str, result: dict[str, Any], run_info: dict[str, Any], *, status: str) -> None:
        gate_status = "passed" if status == "passed" and result.get("status") != "failed" else "failed"
        try:
            record_gate_result(
                self.storage,
                gate_kind="provider_runtime_guard",
                status=gate_status,
                target_paths=[self.agent_run_path],
                result={"operation": operation, **result},
                trace=run_info.get("trace", {}) if isinstance(run_info.get("trace", {}), dict) else {},
                project_id=str(run_info.get("project_id", "")),
                workspace_path=str(run_info.get("workspace_path", "")),
                message=str(result.get("message", "")),
                blocking=True,
            )
        except Exception:
            return

    def _checkpoint_common(self, operation: str, context: dict[str, Any], run_info: dict[str, Any], prompt_payload: Any, *, model_route: dict[str, Any]) -> dict[str, Any]:
        prompt_hash = hashlib.sha256(json.dumps(prompt_payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()
        input_assets = [str(item.get("path", "")) for item in run_info.get("input_assets", []) if isinstance(item, dict) and str(item.get("path", "")).strip()]
        context_bundle_path = _context_bundle_path(context)
        prompt_version = str(run_info.get("prompt_version", ""))
        model = str(run_info.get("model_name") or self.name)
        idempotency_key = checkpoint_idempotency_key(
            self.storage,
            operation=operation,
            input_assets=input_assets,
            context_bundle_path=context_bundle_path,
            prompt_version=prompt_version,
            model=model,
        )
        return {
            "operation": operation,
            "agent_run_path": self.agent_run_path,
            "agent_run_id": str(run_info.get("run_id", "")),
            "input_assets": input_assets,
            "context_bundle_path": context_bundle_path,
            "prompt_version": prompt_version,
            "prompt_hash": prompt_hash,
            "model": model,
            "idempotency_key": idempotency_key,
            "project_id": str(run_info.get("project_id", "")),
            "workspace_path": str(run_info.get("workspace_path", "")),
        }

    def _resolve_model_route(self, operation: str, context: dict[str, Any], run_info: dict[str, Any]) -> dict[str, Any]:
        from novel_forge.modules.model_router import resolve_model_route

        route = resolve_model_route(
            self.storage,
            task_type=_router_task_type(operation),
            project_id=str(run_info.get("project_id", "")),
            workspace_path=str(run_info.get("workspace_path", "")),
            prompt_id=str(context.get("prompt_id", "")),
            prompt_version=str(context.get("prompt_version") or run_info.get("prompt_version", "")),
            workflow_node_id=str(context.get("workflow_node_id", "")),
            trace=run_info.get("trace", {}) if isinstance(run_info.get("trace", {}), dict) else {},
            persist=True,
            environment=str(context.get("environment") or context.get("runtime_environment") or run_info.get("environment") or ""),
            allow_mock_fixture=bool(context.get("allow_mock_fixture") or context.get("mock_provider_test_mode") or run_info.get("allow_mock_fixture")),
        )
        resolution = route.get("resolution", {}) if isinstance(route.get("resolution", {}), dict) else route.get("asset", {}).get("content", {})
        return {
            "status": route.get("status", "resolved"),
            "path": route.get("path", ""),
            "id": route.get("id", ""),
            "provider": str(resolution.get("provider", "")),
            "model_name": str(resolution.get("model_name", "")),
            "route_source": str(resolution.get("route_source", "")),
            "selection_rule": str(resolution.get("selection_rule", "")),
        }

    def _record_stage_checkpoint(self, stage: str, common: dict[str, Any], *, error: str = "", stage_payload: dict[str, Any] | None = None) -> None:
        try:
            record_operation_stage_checkpoint(self.storage, stage=stage, error=error, stage_payload=stage_payload or {}, **common)
        except Exception:
            return

    def _record_raw_output_segments(self, operation: str, result: Any, common: dict[str, Any], run_info: dict[str, Any]) -> list[str]:
        text = _raw_output_text(result)
        if not text:
            return []
        paths: list[str] = []
        chunk_size = 8000
        for index, start in enumerate(range(0, len(text), chunk_size), start=1):
            try:
                segment = record_raw_output_segment(
                    self.storage,
                    operation=operation,
                    idempotency_key=str(common.get("idempotency_key", "")),
                    segment_index=index,
                    text=text[start : start + chunk_size],
                    raw_payload=_raw_output_payload(result, index=index),
                    provider=str(run_info.get("model_provider") or self.name),
                    model=str(run_info.get("model_name") or self.name),
                    provider_request_id=str(_result_value(result, "provider_request_id") or _result_value(result, "request_id") or ""),
                    project_id=str(common.get("project_id", "")),
                    workspace_path=str(common.get("workspace_path", "")),
                )
            except Exception:
                continue
            paths.append(str(segment.get("path", "")))
        if isinstance(result, dict):
            result["raw_output_segment_paths"] = paths
        return [path for path in paths if path]

    def _agent_run_info(self) -> dict[str, Any]:
        try:
            data = self.storage.read_json(resolve_path(self.storage.root, self.agent_run_path))
        except Exception:
            return {}
        content = data.get("content", {}) if isinstance(data, dict) and isinstance(data.get("content", {}), dict) else {}
        metadata = data.get("metadata", {}) if isinstance(data, dict) and isinstance(data.get("metadata", {}), dict) else {}
        return {
            "run_id": content.get("run_id", ""),
            "operation": content.get("operation", ""),
            "input_assets": content.get("input_assets", []) if isinstance(content.get("input_assets", []), list) else [],
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


def _raw_output_text(result: Any) -> str:
    if isinstance(result, dict):
        for key in ["raw_output", "text", "summary", "content"]:
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)
    if isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)


def _raw_output_payload(result: Any, *, index: int) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {"segment_index": index, "raw_type": type(result).__name__}
    return {
        "segment_index": index,
        "provider": result.get("provider", ""),
        "model": result.get("model", ""),
        "usage": result.get("usage", result.get("provider_usage", {})),
        "cost": result.get("cost", {}),
        "status": result.get("status", "succeeded"),
        "keys": sorted(str(key) for key in result.keys()),
    }


def _result_value(result: Any, key: str) -> Any:
    return result.get(key) if isinstance(result, dict) else None


def _runtime_operation(adapter_operation: str, context: dict[str, Any], run_info: dict[str, Any]) -> str:
    for key in ["runtime_operation", "operation", "task_type"]:
        value = str(context.get(key, "") or "").strip()
        if value:
            return value
    run_operation = str(run_info.get("operation", "") or "").strip()
    return run_operation or adapter_operation


def _router_task_type(operation: str) -> str:
    normalized = str(operation or "").strip().lower().replace("-", "_")
    aliases = {
        "draft": "draft",
        "generate": "generate",
        "develop_topic": "topic",
        "topic": "topic",
        "decompose": "analyze",
        "analysis": "analyze",
        "analyze": "analyze",
        "review": "review",
        "handoff_review": "review",
        "revise": "revise",
        "revision": "revise",
        "revision_executor": "revise",
        "final_draft": "revise",
        "chapter_plan": "chapter_plan",
        "outline": "outline",
    }
    return aliases.get(normalized, normalized or "generate")


def _context_bundle_path(context: dict[str, Any]) -> str:
    for key in ["context_bundle_path", "context_path"]:
        value = str(context.get(key, "") or "").strip()
        if value:
            return value
    bundle = context.get("context_bundle", {})
    if isinstance(bundle, dict):
        for key in ["path", "context_bundle_path"]:
            value = str(bundle.get(key, "") or "").strip()
            if value:
                return value
    return ""


def _cost_from_result(result: dict[str, Any], usage: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    if isinstance(result.get("cost"), dict):
        return result["cost"]
    guard = provider_runtime_guard_from_context(context)
    if guard.cost_profile:
        return estimate_provider_cost(usage, guard.cost_profile)
    return {"amount": 0.0, "currency": "USD", "source": "guarded_adapter"}


def _is_project_scoped_run(run_info: dict[str, Any]) -> bool:
    project_id = str(run_info.get("project_id", "") or "").strip()
    workspace_path = str(run_info.get("workspace_path", "") or "").strip()
    return bool((project_id and project_id != "local-system") or (workspace_path and workspace_path != "local-system"))
