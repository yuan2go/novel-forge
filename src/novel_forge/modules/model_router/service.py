from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from novel_forge.model_adapters.runtime import estimate_provider_cost, evaluate_provider_runtime_guard, normalize_provider_usage, provider_runtime_guard_from_context
from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.audit_log import record_audit_event
from novel_forge.modules.evaluation_center import resolve_model_route as resolve_evaluation_route
from novel_forge.modules.operation_checkpoint import record_operation_stage_checkpoint
from novel_forge.modules.os_envelope import is_production_environment
from novel_forge.modules.production_context import filter_project_safe_references
from novel_forge.modules.prompt_registry import resolve_prompt
from novel_forge.modules.runtime_ledger import check_budget_policy, record_gate_result, record_model_call_log, record_trace_span
from novel_forge.modules.runtime_policy import runtime_policy_envelope
from novel_forge.schemas import ExternalProviderProofReport, ModelRoute, ModelRouteResolution, validate_common_fields
from novel_forge.storage.local import LocalStorage

MODEL_ROUTER_TYPES = {"model_route", "model_route_resolution"}
MOCK_PROVIDER_NAMES = {"mock", "mock-provider", "local-mock", "mock-openai", "fixture-mock"}
DEFAULT_PRODUCTION_PROVIDER_ALLOWLIST = {"claude-code"}


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
    environment: str = "",
    approval_status: str = "",
    approval_id: str = "",
    approved_by: str = "",
    approval_reason: str = "",
    production_provider_allowlist: list[str] | None = None,
    mock_provider_test_mode: bool = False,
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
        "environment": environment,
        "approval_status": approval_status,
        "approval_id": approval_id,
        "approved_by": approved_by,
        "approval_reason": approval_reason,
        "production_provider_allowlist": production_provider_allowlist or [],
        "mock_provider_test_mode": bool(mock_provider_test_mode),
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
    environment: str = "",
    allow_mock_fixture: bool = False,
) -> dict[str, Any]:
    route = _latest_model_route(storage, task_type=task_type, project_id=project_id)
    source = "model_route"
    if not route:
        route = resolve_evaluation_route(storage, task_type=task_type, project_id=project_id or None)
        source = str(route.get("source", "evaluation_center"))
    route_content = route.get("content", {}) if isinstance(route.get("content", {}), dict) else route
    resolved_environment = str(environment or route_content.get("environment") or "")
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
        "environment": resolved_environment,
        "created_at": utc_now(),
        "trace": trace_payload,
    }
    resolution["approval_evidence"] = _provider_route_approval_evidence(route_content)
    resolution["provider_policy"] = _production_provider_policy(
        provider=resolution["provider"],
        route_content=route_content,
        environment=resolved_environment,
        allow_mock_fixture=allow_mock_fixture,
        approval_evidence=resolution["approval_evidence"],
    )
    if resolution["provider_policy"]["blocking"]:
        resolution["status"] = "blocked"
        if persist:
            written = _write_model_route_resolution(
                storage,
                task_type=task_type,
                resolution=resolution,
                project_id=project_id,
                workspace_path=workspace_path,
                prompt=prompt,
            )
            raise ValueError(f"production provider policy blocked model route: {resolution['provider_policy']['message']} ({written['path']})")
        raise ValueError(f"production provider policy blocked model route: {resolution['provider_policy']['message']}")
    resolution["status"] = "resolved"
    if not persist:
        return {"status": "resolved", **resolution}
    written = _write_model_route_resolution(
        storage,
        task_type=task_type,
        resolution=resolution,
        project_id=project_id,
        workspace_path=workspace_path,
        prompt=prompt,
    )
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
    environment: str = "",
    allow_mock_fixture: bool = False,
) -> dict[str, Any]:
    route = resolve_model_route(
        storage,
        task_type=task_type,
        project_id=project_id,
        workspace_path=workspace_path,
        prompt_id=prompt_id,
        prompt_version=prompt_version,
        trace=trace,
        environment=environment,
        allow_mock_fixture=allow_mock_fixture,
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
        _record_model_gateway_audit(
            storage,
            action="provider_preflight_blocked",
            operation=operation,
            task_type=task_type,
            provider=provider,
            model=model,
            project_id=project_id,
            trace=trace_payload,
            status="failed",
            blocking=True,
            input_assets=input_assets or [],
            output_assets=output_assets or [],
            evidence_refs=[route.get("path", ""), preflight_gate.get("path", "") if isinstance(preflight_gate, dict) else "", failed_call.get("path", "")],
            metadata={"guard": preflight},
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
        _record_model_gateway_audit(
            storage,
            action="provider_postflight_blocked",
            operation=operation,
            task_type=task_type,
            provider=provider,
            model=model,
            project_id=project_id,
            trace=trace_payload,
            status="failed",
            blocking=True,
            input_assets=input_assets or [],
            output_assets=output_assets or [],
            evidence_refs=[route.get("path", ""), postflight_gate.get("path", "") if isinstance(postflight_gate, dict) else "", failed_call.get("path", "")],
            metadata={"guard": postflight, "usage": normalized_usage},
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
    _record_model_gateway_audit(
        storage,
        action="model_call_completed",
        operation=operation,
        task_type=task_type,
        provider=provider,
        model=model,
        project_id=project_id,
        trace=trace_payload,
        status="succeeded" if status in {"succeeded", "success", "ok"} else status,
        blocking=False,
        input_assets=input_assets or [],
        output_assets=output_assets or [],
        evidence_refs=[route.get("path", ""), model_call.get("path", ""), envelope.commit_result.get("path", "") if isinstance(envelope.commit_result, dict) else ""],
        metadata={"usage": normalized_usage, "cost": cost_payload},
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
    environment: str = "",
    allow_mock_fixture: bool = False,
    provider_runtime_guard: dict[str, Any] | None = None,
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
        environment=environment or str((context or {}).get("environment") or (context or {}).get("runtime_environment") or ""),
        allow_mock_fixture=allow_mock_fixture or bool((context or {}).get("allow_mock_fixture") or (context or {}).get("mock_provider_test_mode")),
    )
    resolution = route.get("resolution", {}) if isinstance(route.get("resolution", {}), dict) else route.get("asset", {}).get("content", {})
    provider = str(resolution.get("provider", "mock"))
    model = str(resolution.get("model_name", "mock-model"))
    context_payload = {
        **(context or {}),
        "model_route": _compact_route_for_context(route),
        "runtime_operation": operation,
        "runtime_environment": (
            environment
            or str(
                (context or {}).get("environment")
                or (context or {}).get("runtime_environment")
                or "development"
            )
        ),
    }
    started = utc_now()
    try:
        from novel_forge.modules.production_execution.legacy import (
            execute_legacy_model_operation,
        )

        result = execute_legacy_model_operation(
            adapter, operation, payload, context_payload
        )
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
            provider_runtime_guard=provider_runtime_guard,
            usage={},
            cost={"amount": 0.0, "currency": "USD", "source": "model_router_adapter_exception"},
            status="failed",
            trace=trace,
            environment=environment or str((context or {}).get("environment") or (context or {}).get("runtime_environment") or ""),
            allow_mock_fixture=allow_mock_fixture or bool((context or {}).get("allow_mock_fixture") or (context or {}).get("mock_provider_test_mode")),
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
        provider_runtime_guard=provider_runtime_guard,
        usage=usage,
        cost=cost,
        status="succeeded",
        trace=trace,
        environment=environment or str((context or {}).get("environment") or (context or {}).get("runtime_environment") or ""),
        allow_mock_fixture=allow_mock_fixture or bool((context or {}).get("allow_mock_fixture") or (context or {}).get("mock_provider_test_mode")),
    )
    if isinstance(result, dict):
        runtime_policy = gateway.get("runtime_policy", {}) if isinstance(gateway.get("runtime_policy", {}), dict) else {}
        runtime_policy_gate = runtime_policy.get("gate_result", {}) if isinstance(runtime_policy.get("gate_result", {}), dict) else {}
        runtime_policy_path = str(runtime_policy.get("path") or runtime_policy_gate.get("path", ""))
        result["model_route_resolution_path"] = str(route.get("path", ""))
        result["model_gateway_call"] = {
            "started_at": started,
            "status": gateway.get("status", ""),
            "model_call_log_path": gateway.get("model_call", {}).get("path", "") if isinstance(gateway.get("model_call", {}), dict) else "",
            "runtime_policy_path": runtime_policy_path,
            "cost_ledger_path": gateway.get("model_call", {}).get("cost_ledger", {}).get("path", "") if isinstance(gateway.get("model_call", {}).get("cost_ledger", {}), dict) else "",
            "provider_policy": resolution.get("provider_policy", {}) if isinstance(resolution.get("provider_policy", {}), dict) else {},
            "approval_evidence": resolution.get("approval_evidence", {}) if isinstance(resolution.get("approval_evidence", {}), dict) else {},
            "provider": provider,
            "model": model,
        }
    return result if isinstance(result, dict) else {"text": str(result), "model_route_resolution_path": str(route.get("path", "")), "model_gateway_call": gateway}


def record_external_provider_proof(
    storage: LocalStorage,
    *,
    proof_type: str,
    routed_result: dict[str, Any],
    adapter: Any | None = None,
    project_id: str = "",
    environment: str = "",
    target_refs: list[str] | None = None,
    strict: bool = False,
) -> dict[str, Any]:
    """Persist auditable evidence that a routed call was a real external provider call.

    This is intentionally stricter than provider route approval. A route can be
    approved while tests still use a fixture adapter; this proof requires the
    adapter/result to expose external-call evidence without secrets.
    """

    gateway = routed_result.get("model_gateway_call", {}) if isinstance(routed_result.get("model_gateway_call", {}), dict) else {}
    provider = str(gateway.get("provider") or "")
    provider_policy = gateway.get("provider_policy", {}) if isinstance(gateway.get("provider_policy", {}), dict) else {}
    approval_evidence = gateway.get("approval_evidence", {}) if isinstance(gateway.get("approval_evidence", {}), dict) else {}
    external_evidence = _external_provider_evidence(routed_result, adapter)
    credential_boundary = _credential_boundary(external_evidence)
    blocking_issues = _external_provider_proof_issues(
        provider=provider,
        provider_policy=provider_policy,
        approval_evidence=approval_evidence,
        external_evidence=external_evidence,
        credential_boundary=credential_boundary,
    )
    status = "passed" if not blocking_issues else "blocked"
    proof = ExternalProviderProofReport(
        title=f"External provider proof {proof_type}",
        tags=["model-router", "provider-proof", proof_type, status],
        content={
            "proof_id": make_id("external_provider_proof_report", f"{proof_type}-{utc_now()}"),
            "proof_type": proof_type,
            "status": status,
            "provider": provider,
            "model": str(gateway.get("model") or ""),
            "external_provider_evidence": external_evidence,
            "credential_boundary": credential_boundary,
            "provider_policy": provider_policy,
            "approval_evidence": approval_evidence,
            "blocking_issues": blocking_issues,
            "evidence_refs": _dedupe(
                [
                    str(routed_result.get("model_route_resolution_path") or ""),
                    str(gateway.get("model_call_log_path") or ""),
                    str(gateway.get("runtime_policy_path") or ""),
                    str(gateway.get("cost_ledger_path") or ""),
                    *(target_refs or []),
                ]
            ),
            "created_at": utc_now(),
        },
        metadata={"project_id": project_id, "environment": environment, "status": status},
        references=_dedupe(
            [
                str(routed_result.get("model_route_resolution_path") or ""),
                str(gateway.get("model_call_log_path") or ""),
                str(gateway.get("runtime_policy_path") or ""),
                str(gateway.get("cost_ledger_path") or ""),
                *(target_refs or []),
            ]
        ),
    )
    written = _write(storage, proof)
    result = {"status": status, "blocking": bool(blocking_issues), "path": written["path"], "asset": written["asset"], "blocking_issues": blocking_issues}
    if strict and blocking_issues:
        dimensions = ", ".join(str(issue.get("dimension") or "") for issue in blocking_issues)
        raise ValueError(f"external provider proof blocked: {dimensions}")
    return result


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


def provider_approval_evidence_report(
    storage: LocalStorage,
    *,
    project_id: str | None = None,
    task_type: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    assets = list_model_router_assets(storage, project_id=project_id, task_type=task_type, limit=max(limit, 1))
    rows: list[dict[str, Any]] = []
    route_rows: list[dict[str, Any]] = []
    for asset in assets:
        content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
        metadata = asset.get("metadata", {}) if isinstance(asset.get("metadata", {}), dict) else {}
        if asset.get("type") == "model_route":
            evidence = _provider_route_approval_evidence(content)
            environment = str(content.get("environment") or "")
            policy = _production_provider_policy(
                provider=str(content.get("provider", "")),
                route_content=content,
                environment=environment,
                allow_mock_fixture=bool(content.get("mock_provider_test_mode") or content.get("fixture_mode")),
                approval_evidence=evidence,
            )
            route_rows.append(
                {
                    "path": str(asset.get("path", "")),
                    "id": str(asset.get("id", "")),
                    "task_type": str(content.get("task_type") or metadata.get("task_type") or ""),
                    "provider": str(content.get("provider", "")),
                    "model_name": str(content.get("model_name", "")),
                    "environment": environment,
                    "production": is_production_environment(environment),
                    "approval_evidence": evidence,
                    "provider_policy": policy,
                    "status": _approval_report_row_status(status=str(content.get("status") or ""), production=is_production_environment(environment), approval_evidence=evidence, provider_policy=policy),
                    "updated_at": str(asset.get("updated_at", "")),
                }
            )
            continue
        if asset.get("type") != "model_route_resolution":
            continue
        evidence = content.get("approval_evidence", {}) if isinstance(content.get("approval_evidence", {}), dict) else {}
        policy = content.get("provider_policy", {}) if isinstance(content.get("provider_policy", {}), dict) else {}
        environment = str(content.get("environment") or policy.get("environment") or "")
        production = is_production_environment(environment)
        rows.append(
            {
                "path": str(asset.get("path", "")),
                "id": str(asset.get("id", "")),
                "task_type": str(content.get("task_type") or metadata.get("task_type") or ""),
                "provider": str(content.get("provider", "")),
                "model_name": str(content.get("model_name", "")),
                "environment": environment,
                "production": production,
                "resolution_status": str(content.get("status") or metadata.get("status") or ""),
                "approval_evidence": evidence,
                "provider_policy": policy,
                "status": _approval_report_row_status(status=str(content.get("status") or ""), production=production, approval_evidence=evidence, provider_policy=policy),
                "route_path": str(content.get("route_path") or ""),
                "created_at": str(content.get("created_at") or asset.get("created_at") or ""),
                "updated_at": str(asset.get("updated_at", "")),
            }
        )
    summary = _provider_approval_summary(rows, route_rows)
    return {
        "kind": "provider_approval_evidence_report",
        "status": _provider_approval_report_status(summary),
        "project_id": project_id or "",
        "task_type": task_type or "",
        "summary": summary,
        "rows": rows[:limit],
        "routes": route_rows[:limit],
        "generated_at": utc_now(),
    }


def _approval_report_row_status(
    *,
    status: str,
    production: bool,
    approval_evidence: dict[str, Any],
    provider_policy: dict[str, Any],
) -> str:
    if provider_policy.get("blocking") or str(provider_policy.get("status", "")) == "blocked" or status == "blocked":
        return "blocked"
    if not production:
        return "skipped"
    if not approval_evidence.get("approved"):
        return "missing_approval"
    if str(provider_policy.get("status", "")) == "passed":
        return "passed"
    return "warning"


def _provider_approval_summary(rows: list[dict[str, Any]], route_rows: list[dict[str, Any]]) -> dict[str, Any]:
    production_rows = [row for row in rows if row.get("production")]
    all_rows = rows + route_rows
    blocking_rows = [row for row in all_rows if row.get("status") == "blocked"]
    missing_rows = [row for row in all_rows if row.get("status") == "missing_approval"]
    return {
        "resolution_count": len(rows),
        "route_count": len(route_rows),
        "production_resolution_count": len(production_rows),
        "passed_resolution_count": sum(1 for row in rows if row.get("status") == "passed"),
        "blocked_resolution_count": sum(1 for row in rows if row.get("status") == "blocked"),
        "missing_approval_count": len(missing_rows),
        "blocked_count": len(blocking_rows),
        "mock_fixture_count": sum(1 for row in all_rows if (row.get("provider_policy", {}) if isinstance(row.get("provider_policy", {}), dict) else {}).get("mock_provider_fixture_mode")),
        "mock_denied_count": sum(
            1
            for row in all_rows
            for issue in ((row.get("provider_policy", {}) if isinstance(row.get("provider_policy", {}), dict) else {}).get("blocking_issues", []) or [])
            if isinstance(issue, dict) and issue.get("dimension") == "mock_provider_denied"
        ),
        "approval_present_count": sum(1 for row in all_rows if (row.get("approval_evidence", {}) if isinstance(row.get("approval_evidence", {}), dict) else {}).get("evidence_present")),
        "approved_count": sum(1 for row in all_rows if (row.get("approval_evidence", {}) if isinstance(row.get("approval_evidence", {}), dict) else {}).get("approved")),
    }


def _provider_approval_report_status(summary: dict[str, Any]) -> str:
    if int(summary.get("blocked_count", 0) or 0) > 0:
        return "blocked"
    if int(summary.get("missing_approval_count", 0) or 0) > 0:
        return "warning"
    if int(summary.get("production_resolution_count", 0) or 0) > 0:
        return "passed"
    if int(summary.get("route_count", 0) or 0) > 0:
        return "skipped"
    return "no_evidence"


def _write_model_route_resolution(
    storage: LocalStorage,
    *,
    task_type: str,
    resolution: dict[str, Any],
    project_id: str,
    workspace_path: str,
    prompt: dict[str, Any],
) -> dict[str, Any]:
    asset = ModelRouteResolution(
        title=f"Model route resolution {task_type}",
        tags=["model-route-resolution", task_type, str(resolution.get("provider", "")), str(resolution.get("model_name", "")), str(resolution.get("status", "resolved"))],
        content=resolution,
        metadata={"project_id": project_id, "workspace_path": workspace_path, "task_type": task_type, "status": str(resolution.get("status", "resolved"))},
        references=filter_project_safe_references(
            storage,
            project_id,
            [value for value in [resolution.get("route_path", ""), prompt.get("prompt_path", ""), prompt.get("release_path", "")] if value],
        ),
    )
    return _write(storage, asset)


def _provider_route_approval_evidence(route_content: dict[str, Any]) -> dict[str, Any]:
    nested = route_content.get("provider_route_approval", {}) if isinstance(route_content.get("provider_route_approval", {}), dict) else {}
    status = str(route_content.get("approval_status") or nested.get("status") or "").strip().lower()
    approval_id = str(route_content.get("approval_id") or nested.get("approval_id") or "")
    approved_by = str(route_content.get("approved_by") or nested.get("approved_by") or nested.get("operator") or "")
    reason = str(route_content.get("approval_reason") or nested.get("reason") or nested.get("approval_reason") or "")
    approved = status in {"approved", "operator_approved", "passed"} and bool(approval_id or approved_by or reason)
    return {
        "status": status or "missing",
        "approved": approved,
        "approval_id": approval_id,
        "approved_by": approved_by,
        "reason": reason,
        "evidence_present": bool(approval_id or approved_by or reason),
        "source": "model_route",
    }


def _production_provider_policy(
    *,
    provider: str,
    route_content: dict[str, Any],
    environment: str,
    allow_mock_fixture: bool,
    approval_evidence: dict[str, Any],
) -> dict[str, Any]:
    if not is_production_environment(environment):
        return {
            "status": "skipped",
            "blocking": False,
            "message": "non-production route",
            "environment": environment,
            "provider": provider,
            "allowlist": [],
            "mock_provider_fixture_mode": False,
            "approval_required": False,
        }
    provider_name = str(provider or "").strip().lower()
    route_allowlist = route_content.get("production_provider_allowlist", [])
    allowlist = {str(item).strip().lower() for item in route_allowlist if str(item).strip()} if isinstance(route_allowlist, list) else set()
    if not allowlist:
        allowlist = set(DEFAULT_PRODUCTION_PROVIDER_ALLOWLIST)
    fixture_mode = bool(allow_mock_fixture or route_content.get("mock_provider_test_mode") or route_content.get("fixture_mode"))
    issues: list[dict[str, Any]] = []
    if provider_name in MOCK_PROVIDER_NAMES:
        if not fixture_mode:
            issues.append(
                {
                    "dimension": "mock_provider_denied",
                    "severity": "critical",
                    "message": "mock provider is denied in production without explicit fixture/test mode",
                    "recommendation": "use an approved production provider or set explicit fixture mode only in tests",
                }
            )
    elif provider_name not in allowlist:
        issues.append(
            {
                "dimension": "production_provider_allowlist",
                "severity": "critical",
                "message": f"provider {provider} is not in the production provider allowlist",
                "recommendation": "add the provider to an approved production allowlist before routing production calls",
            }
        )
    if not approval_evidence.get("approved"):
        issues.append(
            {
                "dimension": "provider_route_approval",
                "severity": "high",
                "message": "production provider route requires approval evidence",
                "recommendation": "record approval_status plus approval_id, approved_by, or approval_reason on the route",
            }
        )
    return {
        "status": "blocked" if issues else "passed",
        "blocking": bool(issues),
        "message": "; ".join(str(issue.get("message", "")) for issue in issues) if issues else "production provider policy passed",
        "environment": environment,
        "provider": provider,
        "allowlist": sorted(allowlist),
        "mock_provider_denylist": sorted(MOCK_PROVIDER_NAMES),
        "mock_provider_fixture_mode": fixture_mode,
        "approval_required": True,
        "approval_evidence": approval_evidence,
        "blocking_issues": issues,
    }


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


def _record_model_gateway_audit(
    storage: LocalStorage,
    *,
    action: str,
    operation: str,
    task_type: str,
    provider: str,
    model: str,
    project_id: str,
    trace: dict[str, Any],
    status: str,
    blocking: bool,
    input_assets: list[str],
    output_assets: list[str],
    evidence_refs: list[str],
    metadata: dict[str, Any],
) -> None:
    try:
        record_audit_event(
            storage,
            event_type="model_gateway",
            action=action,
            actor_type="model_router",
            actor_id=provider,
            target={"operation": operation, "task_type": task_type, "provider": provider, "model": model},
            project_id=project_id,
            trace_id=str(trace.get("trace_id") or ""),
            input_refs=input_assets,
            output_refs=output_assets,
            evidence_refs=evidence_refs,
            status=status,
            blocking=blocking,
            metadata={key: value for key, value in metadata.items() if key not in {"prompt", "raw_text"}},
        )
    except Exception:
        pass


def _external_provider_evidence(routed_result: dict[str, Any], adapter: Any | None) -> dict[str, Any]:
    from_result = routed_result.get("external_provider_evidence", {}) if isinstance(routed_result.get("external_provider_evidence", {}), dict) else {}
    nested = routed_result.get("provider_evidence", {}) if isinstance(routed_result.get("provider_evidence", {}), dict) else {}
    from_nested = nested.get("external_provider_evidence", {}) if isinstance(nested.get("external_provider_evidence", {}), dict) else {}
    from_adapter = getattr(adapter, "external_provider_evidence", {})
    adapter_payload = from_adapter() if callable(from_adapter) else from_adapter
    if not isinstance(adapter_payload, dict):
        adapter_payload = {}
    return _redact({**adapter_payload, **from_nested, **from_result})


def _credential_boundary(evidence: dict[str, Any]) -> dict[str, Any]:
    credential_ref = str(evidence.get("credential_ref") or evidence.get("credential_env") or evidence.get("token_env") or "")
    return {
        "credential_ref": credential_ref,
        "secret_material_persisted": _contains_secret_material(evidence),
        "allowed_secret_forms": ["env-var-name", "secret-manager-reference"],
        "raw_secret_values_allowed": False,
    }


def _external_provider_proof_issues(
    *,
    provider: str,
    provider_policy: dict[str, Any],
    approval_evidence: dict[str, Any],
    external_evidence: dict[str, Any],
    credential_boundary: dict[str, Any],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    provider_name = provider.strip().lower()
    if provider_name in MOCK_PROVIDER_NAMES:
        issues.append({"dimension": "external_provider.mock_provider", "severity": "critical", "message": "mock provider cannot satisfy external provider proof"})
    if provider_policy.get("status") != "passed":
        issues.append({"dimension": "external_provider.provider_policy", "severity": "critical", "message": "production provider policy must pass"})
    if not approval_evidence.get("approved"):
        issues.append({"dimension": "external_provider.approval", "severity": "high", "message": "provider route approval evidence is required"})
    if not bool(external_evidence.get("external_call")):
        issues.append({"dimension": "external_provider.external_call", "severity": "critical", "message": "external_call=true evidence is required"})
    if bool(external_evidence.get("fixture") or external_evidence.get("mock") or external_evidence.get("simulated")):
        issues.append({"dimension": "external_provider.fixture_denied", "severity": "critical", "message": "fixture/mock/simulated responses cannot satisfy external provider proof"})
    for key in ["provider_response_id", "endpoint_host", "rate_limit_policy"]:
        if not external_evidence.get(key):
            issues.append({"dimension": f"external_provider.{key}", "severity": "high", "message": f"{key} is required for external provider proof"})
    if not credential_boundary.get("credential_ref"):
        issues.append({"dimension": "external_provider.credential_ref", "severity": "high", "message": "credential boundary must reference an env var or secret manager key"})
    if credential_boundary.get("secret_material_persisted"):
        issues.append({"dimension": "external_provider.secret_material", "severity": "critical", "message": "raw credential material must not be persisted"})
    return issues


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            lowered = str(key).lower()
            result[key] = "[redacted]" if any(token in lowered for token in ["secret", "token", "api_key", "password", "authorization"]) and lowered not in {"token_env"} else _redact(item)
        return result
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _contains_secret_material(value: Any) -> bool:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True).lower()
    return any(marker in text for marker in ["sk-", "bearer ", "api_key=", "authorization:"])


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _write(storage: LocalStorage, asset: Any) -> dict[str, Any]:
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
