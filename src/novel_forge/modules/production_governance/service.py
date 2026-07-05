from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.audit_log import record_audit_event
from novel_forge.modules.common import resolve_path
from novel_forge.modules.os_envelope import is_production_environment
from novel_forge.modules.production_context import filter_project_safe_references
from novel_forge.modules.runtime_ledger import record_gate_result
from novel_forge.schemas import FallbackDecision, ProductionGovernanceReport
from novel_forge.storage.local import LocalStorage


DEFAULT_PRODUCTION_GATE_ORDER = [
    "os_envelope",
    "context_bundle",
    "source_isolation",
    "mkaos_risk",
    "review_issue",
    "longform_stability",
    "evaluation_gate",
    "provider_runtime_gate",
    "platform_strategy_gate",
]


def build_production_governance_report(
    storage: LocalStorage,
    *,
    operation: str,
    environment: str,
    target_asset_id: str,
    target_asset_path: str | Path,
    project_id: str = "",
    workspace_path: str = "",
    gate_statuses: dict[str, Any] | None = None,
    required_gates: list[str] | None = None,
    source_policy: dict[str, Any] | None = None,
    evidence_refs: list[str] | None = None,
    rollback_plan: dict[str, Any] | None = None,
    trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist one normalized governance report for a production-sensitive path."""

    storage.ensure_layout()
    production = is_production_environment(environment)
    normalized_gates = {key: _normalize_gate(key, value) for key, value in (gate_statuses or {}).items()}
    gate_order = required_gates or DEFAULT_PRODUCTION_GATE_ORDER
    issues = _blocking_issues(normalized_gates, gate_order=gate_order, production=production)
    status = "blocked" if issues else "passed" if production else "skipped"
    trace_payload = trace if isinstance(trace, dict) else {}
    trace_id = str(trace_payload.get("trace_id") or make_id("trace", f"governance-{operation}-{utc_now()}"))
    target_display = _display_path(storage.root, resolve_path(storage.root, target_asset_path))
    content = {
        "report_id": make_id("production_governance", f"{operation}-{target_asset_id}-{utc_now()}"),
        "operation": operation,
        "environment": "production" if production else str(environment or "dev"),
        "target_asset_id": target_asset_id,
        "target_asset_path": target_display,
        "required_gates": gate_order,
        "gate_statuses": normalized_gates,
        "status": status,
        "blocking": bool(issues),
        "blocking_issues": issues,
        "source_policy": source_policy or {},
        "rollback_plan": rollback_plan or _default_rollback_plan(operation, target_display),
        "created_at": utc_now(),
    }
    gate = record_gate_result(
        storage,
        gate_kind="production_governance",
        status=status,
        target_paths=[target_display],
        result={key: value for key, value in content.items() if key != "gate_statuses"},
        trace=trace_payload,
        project_id=project_id,
        workspace_path=workspace_path,
        message="production governance passed" if status == "passed" else "production governance blocked" if status == "blocked" else "production governance skipped outside production",
        blocking=True,
    )
    content["gate_result_path"] = str(gate.get("path", ""))
    asset = ProductionGovernanceReport(
        title=f"Production governance: {operation}",
        source=target_asset_id or target_display,
        tags=["production-governance", operation, status],
        content=content,
        metadata={"project_id": project_id, "workspace_path": workspace_path, "operation": operation, "environment": content["environment"], "status": status, "blocking": bool(issues)},
        references=filter_project_safe_references(storage, project_id, _dedupe([target_display, str(gate.get("path", "")), *(evidence_refs or [])])),
    )
    path = storage.write_asset_auto(asset)
    audit_project_id = project_id or "local-system"
    audit = record_audit_event(
        storage,
        event_type="production_governance",
        action=operation,
        actor_type="system",
        target={"asset_id": target_asset_id, "path": target_display},
        project_id=audit_project_id,
        trace_id=trace_id,
        input_refs=[target_display],
        output_refs=[_display_path(storage.root, path)],
        evidence_refs=[str(gate.get("path", "")), *(evidence_refs or [])],
        status=status,
        blocking=bool(issues),
        rollback_ref=str(content["rollback_plan"].get("rollback_ref", "")),
        metadata={"required_gates": gate_order, "environment": content["environment"]},
    )
    return {
        "status": status,
        "blocking": bool(issues),
        "path": _display_path(storage.root, path),
        "gate_result_path": str(gate.get("path", "")),
        "audit_event_path": str(audit.get("path", "")),
        "asset": asset.to_dict(),
        "blocking_issues": issues,
    }


def record_fallback_decision(
    storage: LocalStorage,
    *,
    fallback_type: str,
    mode: str,
    allowed: bool,
    reason: str,
    project_id: str = "",
    workspace_path: str = "",
    environment: str = "",
    approval_required: bool = True,
    approval_ref: str = "",
    target_refs: list[str] | None = None,
    evidence_refs: list[str] | None = None,
    rollback_plan: dict[str, Any] | None = None,
    trace: dict[str, Any] | None = None,
    actor_type: str = "",
) -> dict[str, Any]:
    """Persist an explicit fallback decision with rollback evidence."""

    storage.ensure_layout()
    trace_payload = trace if isinstance(trace, dict) else {}
    trace_id = str(trace_payload.get("trace_id") or make_id("trace", f"fallback-{fallback_type}-{mode}-{utc_now()}"))
    decision_status = "approved" if allowed else "denied"
    content = {
        "decision_id": make_id("fallback_decision", f"{fallback_type}-{mode}-{utc_now()}"),
        "fallback_type": fallback_type,
        "mode": mode,
        "allowed": bool(allowed),
        "approval_required": bool(approval_required),
        "approval_ref": approval_ref,
        "silent_fallback_allowed": False,
        "reason": reason,
        "environment": "production" if is_production_environment(environment) else str(environment or "dev"),
        "trace_id": trace_id,
        "target_refs": target_refs or [],
        "evidence_refs": evidence_refs or [],
        "rollback_plan": rollback_plan or _fallback_rollback_plan(fallback_type, mode, approval_ref),
        "created_at": utc_now(),
    }
    asset = FallbackDecision(
        title=f"Fallback decision: {fallback_type}/{mode}",
        tags=["fallback-decision", fallback_type, mode, decision_status],
        content=content,
        metadata={"project_id": project_id, "workspace_path": workspace_path, "fallback_type": fallback_type, "mode": mode, "status": decision_status},
        references=filter_project_safe_references(storage, project_id, _dedupe([approval_ref, *(target_refs or []), *(evidence_refs or [])])),
    )
    path = storage.write_asset_auto(asset)
    audit_project_id = project_id or "local-system"
    audit = record_audit_event(
        storage,
        event_type="fallback_decision",
        action=f"{fallback_type}:{mode}",
        actor_type=actor_type or ("operator" if allowed else "system"),
        project_id=audit_project_id,
        trace_id=trace_id,
        input_refs=target_refs or [],
        output_refs=[_display_path(storage.root, path)],
        evidence_refs=[approval_ref, *(evidence_refs or [])],
        status=decision_status,
        blocking=not allowed,
        rollback_ref=str(content["rollback_plan"].get("rollback_ref", "")),
        metadata={"silent_fallback_allowed": False, "approval_required": bool(approval_required)},
    )
    return {
        "status": decision_status,
        "path": _display_path(storage.root, path),
        "audit_event_path": str(audit.get("path", "")),
        "asset": asset.to_dict(),
        "rollback_plan": content["rollback_plan"],
    }


def _normalize_gate(dimension: str, payload: Any) -> dict[str, Any]:
    if isinstance(payload, bool):
        return {"dimension": dimension, "status": "passed" if payload else "blocked", "blocking": not payload, "path": "", "summary": {}}
    data = payload if isinstance(payload, dict) else {}
    status = str(data.get("status") or data.get("decision") or "").strip().lower()
    if not status:
        status = "blocked" if data.get("blocking") else "passed"
    if status in {"ready", "accepted", "succeeded", "success", "ok"}:
        status = "passed"
    if status in {"failed", "fail", "error"}:
        status = "blocked"
    blocking = bool(data.get("blocking")) or status in {"blocked", "missing"}
    path = str(data.get("path") or data.get("gate_result_path") or data.get("context_bundle_path") or data.get("platform_strategy_pack_path") or "")
    return {"dimension": dimension, "status": status, "blocking": blocking, "path": path, "summary": data}


def _blocking_issues(normalized_gates: dict[str, dict[str, Any]], *, gate_order: list[str], production: bool) -> list[dict[str, Any]]:
    if not production:
        return []
    issues: list[dict[str, Any]] = []
    for dimension in gate_order:
        gate = normalized_gates.get(dimension)
        if not gate:
            issues.append({"dimension": dimension, "severity": "critical", "message": f"production path is missing required governance gate: {dimension}", "recommendation": f"run or attach {dimension} evidence before continuing"})
            continue
        if gate.get("blocking") or gate.get("status") not in {"passed", "skipped"}:
            issues.append({"dimension": dimension, "severity": "critical" if dimension in {"os_envelope", "provider_runtime_gate", "source_isolation"} else "high", "message": f"production governance gate failed: {dimension}", "current_status": gate.get("status", ""), "path": gate.get("path", ""), "recommendation": f"repair {dimension} and rerun the governed operation"})
    return issues


def _default_rollback_plan(operation: str, target_path: str) -> dict[str, Any]:
    return {
        "rollback_action": "stop_before_mutation" if operation.endswith("publish_gate") else "restore_previous_asset_version",
        "rollback_ref": target_path,
        "requires_operator_review": True,
    }


def _fallback_rollback_plan(fallback_type: str, mode: str, approval_ref: str) -> dict[str, Any]:
    return {
        "rollback_action": "return_to_primary_route",
        "fallback_type": fallback_type,
        "mode": mode,
        "approval_ref": approval_ref,
        "requires_operator_review": True,
    }


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
