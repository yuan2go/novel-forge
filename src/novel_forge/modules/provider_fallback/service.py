from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.model_adapters.runtime import estimate_provider_cost, normalize_provider_usage
from novel_forge.modules.common import resolve_path
from novel_forge.modules.model_router import resolve_model_route
from novel_forge.modules.production_governance import record_fallback_decision
from novel_forge.modules.runtime_ledger import record_gate_result
from novel_forge.storage.local import LocalStorage


def preview_provider_fallback(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    storage.ensure_layout()
    task_type = str(payload.get("task_type") or "generate")
    project_id = str(payload.get("project_id") or "")
    workspace_path = str(payload.get("workspace_path") or "")
    usage = _usage(payload)
    route = resolve_model_route(
        storage,
        task_type=task_type,
        project_id=project_id,
        workspace_path=workspace_path,
        prompt_id=str(payload.get("prompt_id") or ""),
        prompt_version=str(payload.get("prompt_version") or ""),
        workflow_node_id=str(payload.get("workflow_node_id") or ""),
        trace=payload.get("trace", {}) if isinstance(payload.get("trace", {}), dict) else {},
        persist=True,
        environment=str(payload.get("environment") or ""),
        allow_mock_fixture=bool(payload.get("allow_mock_fixture") or payload.get("mock_provider_test_mode")),
    )
    resolution = route.get("resolution", {}) if isinstance(route.get("resolution", {}), dict) else route.get("asset", {}).get("content", {})
    primary = _candidate_cost(
        {
            "provider": resolution.get("provider", "mock"),
            "model_name": resolution.get("model_name", "mock-model"),
            "cost_profile": payload.get("primary_cost_profile", payload.get("cost_profile", {})),
        },
        usage,
        role="primary",
    )
    fallbacks = []
    for index, candidate in enumerate(resolution.get("fallbacks", []) if isinstance(resolution.get("fallbacks", []), list) else []):
        if not isinstance(candidate, dict):
            continue
        row = _candidate_cost(candidate, usage, role="fallback")
        row["approval_key"] = _approval_key(task_type, row["provider"], row["model_name"], project_id)
        row["approval_required"] = True
        row["fallback_index"] = index
        fallbacks.append(row)
    result = {
        "status": "approval_required" if fallbacks else "no_fallbacks_configured",
        "task_type": task_type,
        "project_id": project_id,
        "workspace_path": workspace_path,
        "hard_stop_policy": "fail_closed",
        "silent_fallback_allowed": False,
        "usage_estimate": usage,
        "primary": primary,
        "fallback_candidates": fallbacks,
        "route_resolution_path": route.get("path", ""),
        "created_at": utc_now(),
    }
    if bool(payload.get("persist", True)):
        gate = record_gate_result(
            storage,
            gate_kind="provider_fallback_preview",
            status="warning" if fallbacks else "skipped",
            target_paths=[str(route.get("path", ""))],
            result=result,
            trace=payload.get("trace", {}) if isinstance(payload.get("trace", {}), dict) else {},
            project_id=project_id,
            workspace_path=workspace_path,
            message="provider fallback requires explicit approval before use" if fallbacks else "model route has no fallback candidates",
            blocking=False,
        )
        result["preview_gate_path"] = gate.get("path", "")
    return result


def approve_provider_fallback(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    preview = payload.get("preview") if isinstance(payload.get("preview"), dict) else preview_provider_fallback(storage, {**payload, "persist": False})
    task_type = str(payload.get("task_type") or preview.get("task_type") or "generate")
    project_id = str(payload.get("project_id") or preview.get("project_id") or "")
    workspace_path = str(payload.get("workspace_path") or preview.get("workspace_path") or "")
    provider = str(payload.get("provider") or payload.get("fallback_provider") or "")
    model_name = str(payload.get("model_name") or payload.get("fallback_model_name") or payload.get("model") or "")
    approved = bool(payload.get("approved", False))
    reason = str(payload.get("reason") or payload.get("approval_reason") or "").strip()
    candidate = _find_candidate(preview.get("fallback_candidates", []), provider=provider, model_name=model_name)
    if not candidate:
        raise ValueError("fallback provider/model must match a configured model route fallback candidate")
    if approved and not reason:
        raise ValueError("approval_reason is required for explicit provider fallback approval")
    approval = {
        "approval_id": make_id("provider_fallback_approval", f"{task_type}-{provider}-{model_name}-{utc_now()}"),
        "approved": approved,
        "task_type": task_type,
        "project_id": project_id,
        "workspace_path": workspace_path,
        "provider": provider,
        "model_name": model_name,
        "approval_key": candidate.get("approval_key") or _approval_key(task_type, provider, model_name, project_id),
        "reason": reason,
        "cost_prediction": candidate.get("cost_prediction", {}),
        "usage_estimate": preview.get("usage_estimate", {}),
        "hard_stop_policy": "fail_closed",
        "silent_fallback_allowed": False,
        "operator": str(payload.get("operator") or payload.get("actor_id") or "local-operator"),
        "expires_at": str(payload.get("expires_at") or ""),
        "preview": preview,
        "created_at": utc_now(),
    }
    gate = record_gate_result(
        storage,
        gate_kind="provider_fallback_approval",
        status="passed" if approved else "failed",
        target_paths=[str(preview.get("route_resolution_path", "")), str(preview.get("preview_gate_path", ""))],
        result=approval,
        trace=payload.get("trace", {}) if isinstance(payload.get("trace", {}), dict) else {},
        project_id=project_id,
        workspace_path=workspace_path,
        message=reason or "provider fallback approval denied",
        blocking=True,
    )
    decision = record_fallback_decision(
        storage,
        fallback_type="provider",
        mode="manual_operator_approval",
        allowed=approved,
        reason=reason or "provider fallback approval denied",
        project_id=project_id,
        workspace_path=workspace_path,
        environment=str(payload.get("environment") or preview.get("environment") or ""),
        approval_required=True,
        approval_ref=str(gate.get("path", "")),
        target_refs=[str(preview.get("route_resolution_path", "")), str(preview.get("preview_gate_path", ""))],
        evidence_refs=[str(gate.get("path", ""))],
        rollback_plan={
            "rollback_action": "return_to_primary_route",
            "approval_ref": str(gate.get("path", "")),
            "route_resolution_path": str(preview.get("route_resolution_path", "")),
            "requires_operator_review": True,
        },
        trace=payload.get("trace", {}) if isinstance(payload.get("trace", {}), dict) else {},
    )
    return {"status": "approved" if approved else "denied", "approval_gate_path": gate.get("path", ""), "fallback_decision_path": decision.get("path", ""), "approval": approval, "asset": gate.get("asset", {})}


def resolve_provider_fallback(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    approval_ref = str(payload.get("approval_ref") or payload.get("approval_gate_path") or "").strip()
    if not approval_ref:
        raise ValueError("explicit provider fallback approval required")
    approval_asset = _find_approval(storage, approval_ref)
    content = approval_asset.get("content", {}) if isinstance(approval_asset.get("content", {}), dict) else {}
    result = content.get("result", {}) if isinstance(content.get("result", {}), dict) else {}
    if content.get("gate_kind") != "provider_fallback_approval" or content.get("status") != "passed" or not result.get("approved"):
        raise ValueError("explicit provider fallback approval required")
    task_type = str(payload.get("task_type") or result.get("task_type") or "")
    provider = str(payload.get("provider") or payload.get("fallback_provider") or result.get("provider") or "")
    model_name = str(payload.get("model_name") or payload.get("fallback_model_name") or result.get("model_name") or "")
    if task_type and task_type != str(result.get("task_type") or ""):
        raise ValueError("provider fallback approval task_type mismatch")
    if provider and provider != str(result.get("provider") or ""):
        raise ValueError("provider fallback approval provider mismatch")
    if model_name and model_name != str(result.get("model_name") or ""):
        raise ValueError("provider fallback approval model mismatch")
    fallback_decision = _find_fallback_decision_for_approval(storage, approval_asset.get("path", ""), str(result.get("approval_id", "")))
    return {
        "status": "approved",
        "hard_stop_policy": "fail_closed",
        "silent_fallback_allowed": False,
        "provider": str(result.get("provider") or ""),
        "model_name": str(result.get("model_name") or ""),
        "task_type": str(result.get("task_type") or ""),
        "cost_prediction": result.get("cost_prediction", {}),
        "usage_estimate": result.get("usage_estimate", {}),
        "approval_gate_path": approval_asset.get("path", ""),
        "approval_id": result.get("approval_id", ""),
        "fallback_decision_path": fallback_decision.get("path", ""),
    }


def _usage(payload: dict[str, Any]) -> dict[str, Any]:
    usage = payload.get("usage", {}) if isinstance(payload.get("usage", {}), dict) else {}
    token_estimate = int(payload.get("token_estimate", 0) or 0)
    if token_estimate and not usage:
        usage = {"input_tokens": token_estimate, "output_tokens": 0, "total_tokens": token_estimate, "usage_source": "provider_fallback_preview"}
    return normalize_provider_usage(usage, usage_source="provider_fallback_preview")


def _candidate_cost(candidate: dict[str, Any], usage: dict[str, Any], *, role: str) -> dict[str, Any]:
    cost = estimate_provider_cost(usage, candidate.get("cost_profile", {}) if isinstance(candidate.get("cost_profile", {}), dict) else {})
    return {
        "role": role,
        "provider": str(candidate.get("provider") or candidate.get("provider_name") or "mock"),
        "model_name": str(candidate.get("model_name") or candidate.get("model") or "mock-model"),
        "reason": str(candidate.get("reason") or ""),
        "cost_prediction": cost,
        "max_cost_per_run": float(candidate.get("max_cost_per_run", 0.0) or 0.0),
        "risk": "requires_operator_approval" if role == "fallback" else "primary_route",
    }


def _find_candidate(candidates: Any, *, provider: str, model_name: str) -> dict[str, Any] | None:
    for candidate in candidates if isinstance(candidates, list) else []:
        if not isinstance(candidate, dict):
            continue
        if provider and provider != str(candidate.get("provider", "")):
            continue
        if model_name and model_name != str(candidate.get("model_name", "")):
            continue
        return candidate
    return None


def _find_approval(storage: LocalStorage, approval_ref: str) -> dict[str, Any]:
    direct = resolve_path(storage.root, approval_ref)
    if direct.exists():
        data = storage.read_json(direct)
        if isinstance(data, dict) and data.get("type") == "gate_result":
            return {**data, "path": _display_path(storage.root, direct)}
    for path in reversed(storage.list_json("runs")):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "gate_result":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        result = content.get("result", {}) if isinstance(content.get("result", {}), dict) else {}
        if approval_ref in {str(data.get("id", "")), str(content.get("gate_id", "")), str(result.get("approval_id", "")), _display_path(storage.root, path)}:
            return {**data, "path": _display_path(storage.root, path)}
    raise FileNotFoundError(f"provider fallback approval not found: {approval_ref}")


def _find_fallback_decision_for_approval(storage: LocalStorage, approval_path: str, approval_id: str) -> dict[str, Any]:
    for path in reversed(storage.list_json("runs")):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "fallback_decision":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if approval_path and str(content.get("approval_ref", "")) == approval_path:
            return {**data, "path": _display_path(storage.root, path)}
        if approval_id and approval_id in str(content):
            return {**data, "path": _display_path(storage.root, path)}
    return {}


def _approval_key(task_type: str, provider: str, model_name: str, project_id: str) -> str:
    digest = hashlib.sha256(f"{task_type}|{provider}|{model_name}|{project_id}".encode("utf-8")).hexdigest()[:16]
    return f"fallback:{digest}"


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
