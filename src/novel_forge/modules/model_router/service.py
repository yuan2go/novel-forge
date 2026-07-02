from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from novel_forge.model_adapters.runtime import estimate_provider_cost, evaluate_provider_runtime_guard, normalize_provider_usage, provider_runtime_guard_from_context
from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.evaluation_center import resolve_model_route as resolve_evaluation_route
from novel_forge.modules.operation_checkpoint import record_operation_stage_checkpoint
from novel_forge.modules.production_context import filter_project_safe_references
from novel_forge.modules.prompt_registry import resolve_prompt
from novel_forge.modules.runtime_ledger import check_budget_policy, record_gate_result, record_model_call_log, record_trace_span
from novel_forge.modules.runtime_policy import runtime_policy_envelope
from novel_forge.schemas import ModelRoute, ModelRouteResolution, validate_common_fields
from novel_forge.storage.local import LocalStorage

MODEL_ROUTER_TYPES = {"model_route", "model_route_resolution"}


def create_model_route(
    storage: LocalStorage,
    *,
    task_type: str,
    provider: str,
    model_name: str,
    fallbacks: list[dict[str, Any]] | None = None,
    selection_rule: str = "balanced",
    max_cost_per_run: float = 0.0,
    max_latency_ms: int = 0,
    status: str = "active",
    project_id: str = "",
    workspace_path: str = "",
) -> dict[str, Any]:
    content = {
        "model_route_id": make_id("model_route", f"{task_type}-{provider}-{model_name}"),
        "task_type": task_type,
        "provider": provider,
        "model_name": model_name,
        "fallbacks": fallbacks or [],
        "selection_rule": _selection_rule(selection_rule),
        "max_cost_per_run": float(max_cost_per_run or 0.0),
        "max_latency_ms": int(max_latency_ms or 0),
        "status": _status(status),
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    asset = ModelRoute(
        title=f"Model route {task_type}: {provider}/{model_name}",
        tags=["model-route", task_type, content["selection_rule"], content["status"]],
        content=content,
        metadata={"project_id": project_id, "workspace_path": workspace_path, "task_type": task_type, "status": content["status"]},
    )
    return _write(storage, asset)


def resolve_model_route(
    storage: LocalStorage,
    *,
    task_type: str,
    project_id: str = "",
    workspace_path: str = "",
    prompt_id: str = "",
    prompt_version: str = "",
    workflow_node_id: str = "",
    trace: dict[str, Any] | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    route = _latest_model_route(storage, task_type=task_type, project_id=project_id)
    source = "model_route"
    if not route:
        route = resolve_evaluation_route(storage, task_type=task_type, project_id=project_id or None)
        source = str(route.get("source", "evaluation_center"))
    route_content = route.get("content", {}) if isinstance(route.get("content", {}), dict) else route
    prompt = resolve_prompt(
        storage,
        prompt_id=prompt_id,
        task_type=task_type,
        version=prompt_version,
        workflow_node_id=workflow_node_id,
        project_id=project_id,
        trace=trace,
    )
    trace_payload = _trace_payload(trace, task_type=task_type)
    budget = check_budget_policy(
        storage,
        scope=project_id or "global",
        amount=float(route_content.get("max_cost_per_run", 0.0) or 0.0),
        token_used=0,
        project_id=project_id,
        workspace_path=workspace_path,
        trace=trace_payload,
    )
    resolution = {
        "resolution_id": make_id("model_route_resolution", f"{task_type}-{utc_now()}"),
        "task_type": task_type,
        "provider": str(route_content.get("provider", "mock") or "mock"),
        "model_name": str(route_content.get("model_name", "mock-model") or route_content.get("model", "mock-model") or "mock-model"),
        "fallbacks": route_content.get("fallbacks", []) if isinstance(route_content.get("fallbacks", []), list) else [],
        "selection_rule": str(route_content.get("selection_rule", "balanced")),
        "max_cost_per_run": float(route_content.get("max_cost_per_run", 0.0) or 0.0),
        "max_latency_ms": int(route_content.get("max_latency_ms", 0) or 0),
        "route_source": source,
        "route_path": str(route.get("path", "")) if isinstance(route, dict) else "",
        "prompt": prompt,
        "budget": budget,
        "created_at": utc_now(),
        "trace": trace_payload,
    }
    if not persist:
        return {"status": "resolved", **resolution}
    asset = ModelRouteResolution(
        title=f"Model route resolution {task_type}",
        tags=["model-route-resolution", task_type, resolution["provider"], resolution["model_name"]],
        content=resolution,
        metadata={"project_id": project_id, "workspace_path": workspace_path, "task_type": task_type},
        references=filter_project_safe_references(
            storage,
            project_id,
            [value for value in [resolution.get("route_path", ""), prompt.get("prompt_path", ""), prompt.get("release_path", "")] if value],
        ),
    )
    written = _write(storage, asset)
    if trace_payload.get("trace_id"):
        record_trace_span(
            storage,
            trace_id=str(trace_payload["trace_id"]),
            span_type="model_router",
            name=f"resolve:{task_type}",
            status="succeeded",
            parent_span_id=str(trace_payload.get("span_id") or trace_payload["trace_id"]),
            attributes={key: value for key, value in resolution.items() if key not in {"prompt", "budget"}},
            references=[written["path"]],
            project_id=project_id,
            workspace_path=workspace_path,
        )
    return {"status": "resolved", "path": written["path"], "id": written["id"], "asset": written["asset"], "resolution": resolution, "validation": written["validation"]}


def execute_model_gateway_call(
    storage: LocalStorage,
    *,
    task_type: str,
    operation: str,
    prompt_id: str = "",
    prompt_version: str = "",
    project_id: str = "",
    workspace_path: str = "",
    input_assets: list[str] | None = None,
    output_assets: list[str] | None = None,
    context_bundle_path: str = "",
    provider_runtime_guard: dict[str, Any] | None = None,
    usage: dict[str, Any] | None = None,
    cost: dict[str, Any] | None = None,
    status: str = "succeeded",
    trace: dict[str, Any] | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    route = resolve_model_route(
        storage,
        task_type=task_type,
        project_id=project_id,
        workspace_path=workspace_path,
        prompt_id=prompt_id,
        prompt_version=prompt_version,
        trace=trace,
    )
    resolution = route.get("resolution", {}) if isinstance(route.get("resolution", {}), dict) else route.get("asset", {}).get("content", {})
    trace_payload = _trace_payload(trace, task_type=task_type)
    provider = str(resolution.get("provider", "mock"))
    model = str(resolution.get("model_name", "mock-model"))
    project_scoped = bool((project_id and project_id != "local-system") or (workspace_path and workspace_path != "local-system"))
    model_call_source_id = str((trace_payload.get("trace_id") or context_bundle_path or next(iter(input_assets or []), "")) if project_scoped else route.get("path", ""))
    checkpoint_common = _gateway_checkpoint_common(
        operation=operation,
        input_assets=input_assets or [],
        output_assets=output_assets or [],
        context_bundle_path=context_bundle_path,
        prompt_version=prompt_version or str(resolution.get("prompt", {}).get("version", "")),
        model=model,
        prompt_payload=resolution.get("prompt", {}),
        project_id=project_id,
        workspace_path=workspace_path,
    )
    _record_gateway_checkpoint(storage, "prompt_built", checkpoint_common, stage_payload={"route_path": route.get("path", ""), "resolution": _compact_resolution(resolution)})
    guard_payload = provider_runtime_guard if isinstance(provider_runtime_guard, dict) else {}
    guard_context = {"provider_runtime_guard": guard_payload}
    preflight = evaluate_provider_runtime_guard(operation=operation, provider=provider, usage={}, guard=provider_runtime_guard_from_context(guard_context), phase="preflight")
    preflight_gate = _record_provider_guard_gate(storage, operation=operation, provider=provider, result=preflight, trace=trace_payload, project_id=project_id, workspace_path=workspace_path, target_paths=[*(input_assets or []), *(output_assets or [])])
    if preflight.get("status") == "failed":
        _record_gateway_checkpoint(storage, "provider_started", checkpoint_common, error=str(preflight.get("message", "")), stage_payload={"guard": preflight})
        failed_call = record_model_call_log(
            storage,
            provider=provider,
            model=model,
            operation=operation,
            status="failed",
            usage=preflight.get("usage", {}),
            cost={"amount": 0.0, "currency": "USD", "source": "model_gateway_guard"},
            trace=trace_payload,
            project_id=project_id,
            workspace_path=workspace_path,
            source_id=model_call_source_id,
            prompt_version=prompt_version or str(resolution.get("prompt", {}).get("version", "")),
        )
        raise RuntimeError(f"provider runtime guard blocked model gateway call: {preflight.get('message')} ({failed_call.get('path', '')})")
    _record_gateway_checkpoint(storage, "provider_started", checkpoint_common, stage_payload={"guard": preflight})
    normalized_usage = normalize_provider_usage(usage or {}, usage_source=str((usage or {}).get("usage_source", "model_gateway") if isinstance(usage, dict) else "model_gateway"))
    cost_payload = cost if isinstance(cost, dict) and cost else _gateway_cost_from_usage(normalized_usage, guard_payload)
    postflight = evaluate_provider_runtime_guard(operation=operation, provider=provider, usage=normalized_usage, guard=provider_runtime_guard_from_context(guard_context), phase="postflight")
    postflight_gate = _record_provider_guard_gate(storage, operation=operation, provider=provider, result=postflight, trace=trace_payload, project_id=project_id, workspace_path=workspace_path, target_paths=[*(input_assets or []), *(output_assets or [])])
    if postflight.get("status") == "failed":
        _record_gateway_checkpoint(storage, "provider_completed", checkpoint_common, error=str(postflight.get("message", "")), stage_payload={"guard": postflight, "usage": normalized_usage})
        failed_call = record_model_call_log(
            storage,
            provider=provider,
            model=model,
            operation=operation,
            status="failed",
            usage=normalized_usage,
            cost=cost_payload,
            trace=trace_payload,
            project_id=project_id,
            workspace_path=workspace_path,
            source_id=model_call_source_id,
            prompt_version=prompt_version or str(resolution.get("prompt", {}).get("version", "")),
        )
        raise RuntimeError(f"provider runtime guard blocked model gateway call: {postflight.get('message')} ({failed_call.get('path', '')})")
    _record_gateway_checkpoint(storage, "provider_completed", checkpoint_common, stage_payload={"guard": postflight, "usage": normalized_usage, "cost": cost_payload})
    with runtime_policy_envelope(
        storage,
        operation=operation,
        project_id=project_id,
        workspace_path=workspace_path,
        input_assets=input_assets or [],
        output_assets=output_assets or [],
        context_bundle_path=context_bundle_path,
        trace=trace_payload,
        mode=mode,
    ) as envelope:
        if preflight_gate:
            envelope.add_gate_result(preflight_gate)
        if postflight_gate:
            envelope.add_gate_result(postflight_gate)
        model_call = envelope.record_model_result(
            provider=provider,
            model=model,
            usage=normalized_usage,
            cost=cost_payload,
            status=status,
            source_id=model_call_source_id,
            prompt_version=prompt_version or str(resolution.get("prompt", {}).get("version", "")),
        )
    _record_gateway_checkpoint(
        storage,
        "output_validated",
        checkpoint_common,
        stage_payload={"model_call_log_path": model_call.get("path", ""), "runtime_policy_status": envelope.commit_result.get("status", "")},
    )
    return {
        "status": "succeeded" if status in {"succeeded", "success", "ok"} else status,
        "route": route,
        "model_call": model_call,
        "runtime_policy": envelope.commit_result,
    }


def call_model_via_router(
    storage: LocalStorage,
    *,
    adapter: Any,
    operation: str,
    payload: Any,
    context: dict[str, Any] | None = None,
    task_type: str = "",
    project_id: str = "",
    workspace_path: str = "",
    input_assets: list[str] | None = None,
    output_assets: list[str] | None = None,
    context_bundle_path: str = "",
    prompt_id: str = "",
    prompt_version: str = "",
    trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve ModelRouter before executing an adapter operation.

    This is for legacy API/CLI/service paths that do not have an AgentRun and
    therefore cannot use GuardedModelAdapter. Agent paths should keep using
    GuardedModelAdapter, which now resolves ModelRouter internally.
    """

    routed_task = task_type or _task_type_for_operation(operation)
    route = resolve_model_route(
        storage,
        task_type=routed_task,
        project_id=project_id,
        workspace_path=workspace_path,
        prompt_id=prompt_id,
        prompt_version=prompt_version,
        trace=trace,
    )
    context_payload = {**(context or {}), "model_route": _compact_route_for_context(route), "runtime_operation": operation}
    started = utc_now()
    try:
        if operation == "generate":
            result = adapter.generate(str(payload), context_payload)
        elif operation == "analyze":
            result = adapter.analyze(str(payload), context_payload)
        elif operation in {"review", "handoff_review"}:
            result = adapter.review(str(payload), context_payload)
        elif operation == "revise":
            review_payload = context_payload.get("review", {}) if isinstance(context_payload.get("review", {}), dict) else {}
            result = adapter.revise(str(payload), review_payload, context_payload)
        else:
            raise ValueError(f"unsupported routed model operation: {operation}")
    except Exception:
        execute_model_gateway_call(
            storage,
            task_type=routed_task,
            operation=operation,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            project_id=project_id,
            workspace_path=workspace_path,
            input_assets=input_assets or [],
            output_assets=output_assets or [],
            context_bundle_path=context_bundle_path,
            usage={},
            cost={"amount": 0.0, "currency": "USD", "source": "model_router_adapter_exception"},
            status="failed",
            trace=trace,
        )
        raise
    usage = normalize_provider_usage(
        result.get("usage", result.get("provider_usage", {})) if isinstance(result, dict) else {},
        usage_source="model_router_adapter",
    )
    cost = result.get("cost") if isinstance(result, dict) and isinstance(result.get("cost"), dict) else {"amount": 0.0, "currency": "USD", "source": "model_router_adapter"}
    gateway = execute_model_gateway_call(
        storage,
        task_type=routed_task,
        operation=operation,
        prompt_id=prompt_id,
        prompt_version=prompt_version,
        project_id=project_id,
        workspace_path=workspace_path,
        input_assets=input_assets or [],
        output_assets=output_assets or [],
        context_bundle_path=context_bundle_path,
        usage=usage,
        cost=cost,
        status="succeeded",
        trace=trace,
    )
    if isinstance(result, dict):
        result["model_route_resolution_path"] = str(route.get("path", ""))
        result["model_gateway_call"] = {
            "started_at": started,
            "status": gateway.get("status", ""),
            "model_call_log_path": gateway.get("model_call", {}).get("path", "") if isinstance(gateway.get("model_call", {}), dict) else "",
        }
    return result if isinstance(result, dict) else {"text": str(result), "model_route_resolution_path": str(route.get("path", "")), "model_gateway_call": gateway}


def list_model_router_assets(storage: LocalStorage, *, project_id: str | None = None, task_type: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in storage.list_json("runs"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") not in MODEL_ROUTER_TYPES:
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if project_id and str(metadata.get("project_id", "")) != project_id:
            continue
        if task_type and str(content.get("task_type", metadata.get("task_type", ""))) != task_type:
            continue
        rows.append({**data, "path": _display_path(storage.root, path)})
    return sorted(rows, key=lambda row: str(row.get("updated_at", "")), reverse=True)[:limit]


def _latest_model_route(storage: LocalStorage, *, task_type: str, project_id: str) -> dict[str, Any] | None:
    candidates = []
    for row in list_model_router_assets(storage, project_id=project_id or None, task_type=task_type or None, limit=1000):
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        if row.get("type") == "model_route" and content.get("status") == "active":
            candidates.append(row)
    return sorted(candidates, key=lambda row: str(row.get("updated_at", "")), reverse=True)[0] if candidates else None


def _trace_payload(trace: dict[str, Any] | None, *, task_type: str) -> dict[str, Any]:
    data = dict(trace or {})
    if data.get("trace_id") and not data.get("span_id"):
        data["span_id"] = make_id("span", f"model-router-{task_type}-{utc_now()}")
    if data.get("trace_id") and not data.get("parent_span_id"):
        data["parent_span_id"] = data["trace_id"]
    return data


def _gateway_checkpoint_common(
    *,
    operation: str,
    input_assets: list[str],
    output_assets: list[str],
    context_bundle_path: str,
    prompt_version: str,
    model: str,
    prompt_payload: Any,
    project_id: str,
    workspace_path: str,
) -> dict[str, Any]:
    prompt_hash = hashlib.sha256(json.dumps(prompt_payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()
    return {
        "operation": operation,
        "input_assets": input_assets,
        "output_assets": output_assets,
        "context_bundle_path": context_bundle_path,
        "prompt_version": prompt_version,
        "prompt_hash": prompt_hash,
        "model": model,
        "project_id": project_id,
        "workspace_path": workspace_path,
    }


def _record_gateway_checkpoint(storage: LocalStorage, stage: str, common: dict[str, Any], *, error: str = "", stage_payload: dict[str, Any] | None = None) -> None:
    try:
        record_operation_stage_checkpoint(storage, stage=stage, error=error, stage_payload=stage_payload or {}, **common)
    except Exception:
        return


def _record_provider_guard_gate(
    storage: LocalStorage,
    *,
    operation: str,
    provider: str,
    result: dict[str, Any],
    trace: dict[str, Any],
    project_id: str,
    workspace_path: str,
    target_paths: list[str],
) -> dict[str, Any] | None:
    try:
        return record_gate_result(
            storage,
            gate_kind="provider_runtime_guard",
            status="passed" if result.get("status") != "failed" else "failed",
            target_paths=target_paths,
            result={"operation": operation, "provider": provider, **result},
            trace=trace,
            project_id=project_id,
            workspace_path=workspace_path,
            message=str(result.get("message", "")),
            blocking=True,
        )
    except Exception:
        return None


def _gateway_cost_from_usage(usage: dict[str, Any], guard_payload: dict[str, Any]) -> dict[str, Any]:
    cost_profile = guard_payload.get("cost_profile", {}) if isinstance(guard_payload.get("cost_profile", {}), dict) else {}
    if cost_profile:
        return estimate_provider_cost(usage, cost_profile)
    return {"amount": 0.0, "currency": "USD", "source": "model_gateway"}


def _compact_resolution(resolution: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in resolution.items() if key not in {"prompt", "budget"}}


def _compact_route_for_context(route: dict[str, Any]) -> dict[str, Any]:
    resolution = route.get("resolution", {}) if isinstance(route.get("resolution", {}), dict) else {}
    return {
        "path": route.get("path", ""),
        "provider": resolution.get("provider", ""),
        "model_name": resolution.get("model_name", ""),
        "task_type": resolution.get("task_type", ""),
        "route_source": resolution.get("route_source", ""),
    }


def _task_type_for_operation(operation: str) -> str:
    value = str(operation or "").strip().lower().replace("-", "_")
    return {
        "generate": "generate",
        "analyze": "analyze",
        "review": "review",
        "revise": "revise",
        "handoff_review": "review",
    }.get(value, value or "generate")


def _selection_rule(value: str) -> str:
    normalized = str(value or "balanced").strip().lower().replace("-", "_")
    return normalized if normalized in {"quality_first", "cost_first", "latency_first", "balanced"} else "balanced"


def _status(value: str) -> str:
    normalized = str(value or "active").strip().lower().replace(" ", "_")
    return normalized if normalized in {"active", "draft", "disabled", "archived"} else "active"


def _write(storage: LocalStorage, asset: ModelRoute | ModelRouteResolution) -> dict[str, Any]:
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "id": asset.id, "asset": asset.to_dict(), "validation": {"ok": True, "errors": []}}


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
