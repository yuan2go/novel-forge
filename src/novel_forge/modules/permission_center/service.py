from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.audit_log import record_audit_event
from novel_forge.modules.common import resolve_path
from novel_forge.modules.os_envelope import is_production_environment
from novel_forge.modules.production_context import filter_project_safe_references
from novel_forge.schemas import ApprovalRequest, BaseAsset, validate_common_fields
from novel_forge.storage.local import LocalStorage

PERMISSION_SCOPES = {"agent", "tool", "source", "publish", "bypass"}
DECISION_STATUSES = {"allowed", "denied", "waiting_human"}
APPROVAL_STATUSES = {"pending", "approved", "rejected", "expired", "cancelled"}
APPROVAL_REQUEST_SCOPES = {"source", "context", "publish", "story_mutation", "provider", "fallback", "canon", "feedback", "agent", "budget"}
APPROVAL_REQUEST_RISK_LEVELS = {"low", "medium", "high", "critical"}


def create_approval_request(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    """Create a blueprint-level human approval request without applying side effects."""
    storage.ensure_layout()
    scope = _approval_scope(payload.get("scope") or payload.get("approval_scope") or payload.get("risk_scope") or "agent")
    action = str(payload.get("action") or payload.get("operation") or payload.get("approval_action") or "").strip() or "approve"
    environment = str(payload.get("environment") or payload.get("mode") or "local")
    risk_level = _risk_level(payload.get("risk_level") or payload.get("risk") or ("high" if scope in {"publish", "story_mutation", "source"} else "medium"))
    request_id = str(payload.get("request_id") or make_id("approval_request", f"{scope}:{action}:{payload.get('target_id', '')}:{utc_now()}"))
    evidence_refs = _strings(payload.get("evidence_refs")) or _strings(payload.get("evidence_paths")) or _strings(payload.get("references"))
    target_refs = _strings(payload.get("target_refs")) or _strings(payload.get("target_paths"))
    blocking = _approval_blocking(payload, environment=environment, risk_level=risk_level, scope=scope)
    expires_at = str(payload.get("expires_at") or payload.get("deadline_at") or "")
    content = {
        "request_id": request_id,
        "status": "pending",
        "scope": scope,
        "action": action,
        "subject": {
            "subject_type": str(payload.get("subject_type") or payload.get("actor_type") or "agent"),
            "subject_id": str(payload.get("subject_id") or payload.get("actor") or payload.get("actor_id") or ""),
        },
        "target": {
            "target_type": str(payload.get("target_type") or payload.get("resource_type") or scope),
            "target_id": str(payload.get("target_id") or payload.get("resource_id") or ""),
            "target_path": str(payload.get("target_path") or payload.get("resource_path") or ""),
        },
        "risk_level": risk_level,
        "environment": environment,
        "blocking": blocking,
        "reason": str(payload.get("reason") or payload.get("request_reason") or ""),
        "requested_by": str(payload.get("requested_by") or payload.get("actor") or payload.get("actor_id") or "system"),
        "required_before": _strings(payload.get("required_before")) or _approval_required_before(scope, action),
        "evidence_refs": evidence_refs,
        "target_refs": target_refs,
        "rollback_plan": _approval_rollback_plan(payload, scope=scope),
        "decision": {},
        "expires_at": expires_at,
        "trace_id": str(payload.get("trace_id") or ""),
        "source_policy": payload.get("source_policy", {}) if isinstance(payload.get("source_policy", {}), dict) else {},
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    asset = ApprovalRequest(
        id=request_id,
        title=str(payload.get("title") or f"Approval request {scope}:{action}"),
        tags=["permission-center", "approval-request", scope, "pending", risk_level],
        content=content,
        metadata={
            "project_id": str(payload.get("project_id") or ""),
            "workspace_path": str(payload.get("workspace_path") or ""),
            "asset_status": "pending",
            "risk_level": risk_level,
            "blocking": blocking,
            "use_in_generation_rag": False,
        },
        references=filter_project_safe_references(storage, str(payload.get("project_id") or ""), [*evidence_refs, *target_refs]),
    )
    data = asset.to_dict()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset)
    written = {"status": "pending", "path": _display_path(storage.root, path), "asset": storage.read_json(path)}
    audit = _audit(
        storage,
        "approval_request.created",
        payload,
        target={"asset_type": "approval_request", "request_id": request_id, "scope": scope, "action": action},
        input_refs=[*evidence_refs, *target_refs],
        output_refs=[written["path"]],
        status="waiting_human",
        blocking=blocking,
        metadata={"risk_level": risk_level, "environment": environment, "required_before": content["required_before"]},
    )
    return {**written, "audit_event_path": audit["path"], "blocking": blocking}


def list_approval_requests(storage: LocalStorage, *, project_id: str | None = None, status: str | None = None, scope: str | None = None, limit: int = 300) -> list[dict[str, Any]]:
    rows = _list_assets(storage, "approval_request", project_id=project_id or None, limit=max(1, int(limit or 300)))
    filtered: list[dict[str, Any]] = []
    for row in rows:
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        if status and str(content.get("status", "")) != status:
            continue
        if scope and str(content.get("scope", "")) != scope:
            continue
        filtered.append(row)
        if len(filtered) >= max(1, int(limit or 300)):
            break
    return filtered


def resolve_approval_request(storage: LocalStorage, request_ref: str | Path, payload: dict[str, Any]) -> dict[str, Any]:
    path = _resolve_asset(storage, request_ref, "approval_request")
    data = storage.read_json(path)
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    current = str(content.get("status") or "")
    if current in {"approved", "rejected", "expired", "cancelled"}:
        raise ValueError(f"approval request already resolved: {current}")
    decision = str(payload.get("decision") or payload.get("status") or "").strip().lower()
    if decision not in {"approved", "rejected", "cancelled", "expired"}:
        raise ValueError("approval request decision must be approved, rejected, cancelled, or expired")
    actor = str(payload.get("actor") or payload.get("actor_id") or "operator")
    reason = str(payload.get("reason") or payload.get("decision_note") or "")
    decided_at = utc_now()
    content["status"] = decision
    content["updated_at"] = decided_at
    content["decision"] = {
        "status": decision,
        "actor": actor,
        "reason": reason,
        "decided_at": decided_at,
        "trace_id": str(payload.get("trace_id") or content.get("trace_id") or ""),
        "evidence_refs": _strings(payload.get("evidence_refs")),
    }
    data["content"] = content
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    metadata.update({"asset_status": decision, "status": decision, "decided_by": actor})
    data["metadata"] = metadata
    data["tags"] = _dedupe([*[str(tag) for tag in data.get("tags", [])], decision])
    data["updated_at"] = decided_at
    storage.write_json(path, data)
    audit = _audit(
        storage,
        f"approval_request.{decision}",
        {**payload, "project_id": metadata.get("project_id", ""), "trace_id": content.get("trace_id", "")},
        target={"asset_type": "approval_request", "request_id": content.get("request_id", "")},
        input_refs=[_display_path(storage.root, path), *_strings(payload.get("evidence_refs"))],
        status="succeeded" if decision == "approved" else decision,
        blocking=False,
        metadata={"previous_status": current, "scope": content.get("scope", ""), "risk_level": content.get("risk_level", "")},
    )
    return {"status": decision, "path": _display_path(storage.root, path), "asset": data, "audit_event_path": audit["path"]}


def expire_approval_requests(storage: LocalStorage, *, project_id: str | None = None, now: str | None = None, limit: int = 300) -> dict[str, Any]:
    now_value = now or utc_now()
    expired: list[dict[str, Any]] = []
    for row in list_approval_requests(storage, project_id=project_id, status="pending", limit=limit):
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        expires_at = str(content.get("expires_at") or "")
        if not expires_at or expires_at > now_value:
            continue
        resolved = resolve_approval_request(storage, row.get("path", ""), {"decision": "expired", "actor": "permission-center", "reason": "approval request deadline expired", "project_id": project_id or ""})
        expired.append({"request_id": content.get("request_id", ""), "path": resolved["path"], "status": "expired"})
    return {"status": "completed", "expired_count": len(expired), "expired": expired, "checked_at": now_value}


def create_permission_policy(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    storage.ensure_layout()
    scope = _scope(payload.get("scope") or payload.get("scope_type") or payload.get("resource_scope") or "tool")
    policy_id = make_id("permission_policy", f"{scope}:{payload.get('subject_type', '*')}:{payload.get('action', '*')}:{utc_now()}")
    content = {
        "policy_id": policy_id,
        "scope": scope,
        "subject_type": str(payload.get("subject_type") or "*"),
        "subject_id": str(payload.get("subject_id") or "*"),
        "resource_type": str(payload.get("resource_type") or scope),
        "resource_id": str(payload.get("resource_id") or payload.get("tool_id") or "*"),
        "actions": _strings(payload.get("actions")) or _strings(payload.get("allowed_operations")) or [str(payload.get("action") or "*")],
        "effect": _effect(payload.get("effect") or "allow"),
        "environment": str(payload.get("environment") or "*"),
        "requires_human_approval": bool(payload.get("requires_human_approval", scope in {"publish", "bypass"})),
        "bypass_allowed": bool(payload.get("bypass_allowed", False)),
        "status": _status(payload.get("status") or "active"),
        "reason": str(payload.get("reason") or ""),
        "created_at": utc_now(),
    }
    written = _write_asset(
        storage,
        "permission_policy",
        f"Permission policy {scope}",
        ["permission-center", scope, content["status"], content["effect"]],
        content,
        project_id=str(payload.get("project_id") or ""),
        workspace_path=str(payload.get("workspace_path") or ""),
    )
    audit = _audit(
        storage,
        "permission_policy.created",
        payload,
        target={"asset_type": "permission_policy", "policy_id": policy_id, "scope": scope},
        output_refs=[written["path"]],
        status="succeeded",
    )
    return {**written, "status": "created", "audit_event_path": audit["path"]}


def list_permission_policies(storage: LocalStorage, *, project_id: str | None = None, scope: str | None = None, limit: int = 300) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in reversed(storage.list_json("runs")):
        data = _read_json_safe(storage, path)
        if data.get("type") != "permission_policy":
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if project_id and str(metadata.get("project_id", "")) != project_id:
            continue
        if scope and str(content.get("scope", "")) != scope:
            continue
        rows.append({**data, "path": _display_path(storage.root, path)})
        if len(rows) >= max(1, int(limit or 300)):
            break
    return rows


def evaluate_permission(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    storage.ensure_layout()
    scope = _scope(payload.get("scope") or payload.get("scope_type") or "tool")
    action = str(payload.get("action") or payload.get("operation") or "").strip() or "*"
    environment = str(payload.get("environment") or payload.get("mode") or "dev")
    policies = list_permission_policies(storage, project_id=str(payload.get("project_id") or "") or None, scope=scope, limit=1000)
    matches = [_policy_row(policy) for policy in policies if _policy_matches(policy, payload, scope=scope, action=action, environment=environment)]
    deny = next((policy for policy in matches if policy["effect"] == "deny"), None)
    allow = next((policy for policy in matches if policy["effect"] == "allow"), None)
    production = is_production_environment(environment)
    bypass = scope == "bypass" or bool(payload.get("bypass_requested"))
    if deny:
        decision = "denied"
        reason = f"denied by policy {deny['policy_id']}"
    elif allow and (not allow["requires_human_approval"] or _has_approved_gate(storage, payload, scope=scope, action=action)):
        decision = "allowed"
        reason = f"allowed by policy {allow['policy_id']}"
    elif allow and allow["requires_human_approval"]:
        decision = "waiting_human"
        reason = f"human approval required by policy {allow['policy_id']}"
    elif production or bypass:
        decision = "denied"
        reason = "fail-closed: no active permission policy matched production/bypass request"
    else:
        decision = "allowed"
        reason = "compat default allow; no active policy matched"
    gate = {}
    if decision == "waiting_human":
        gate = create_human_approval_gate(storage, {**payload, "scope": scope, "action": action, "reason": reason})
    decision_asset = _write_asset(
        storage,
        "permission_decision",
        f"Permission decision {scope}:{action}",
        ["permission-center", scope, decision],
        {
            "decision_id": make_id("permission_decision", f"{scope}:{action}:{utc_now()}"),
            "status": decision,
            "scope": scope,
            "action": action,
            "subject_type": str(payload.get("subject_type") or ""),
            "subject_id": str(payload.get("subject_id") or ""),
            "resource_type": str(payload.get("resource_type") or ""),
            "resource_id": str(payload.get("resource_id") or ""),
            "environment": environment,
            "matched_policies": matches,
            "reason": reason,
            "human_approval_gate_path": gate.get("path", ""),
            "created_at": utc_now(),
        },
        project_id=str(payload.get("project_id") or ""),
        workspace_path=str(payload.get("workspace_path") or ""),
        references=[gate.get("path", "")],
    )
    audit = _audit(
        storage,
        "permission.evaluate",
        payload,
        target={"asset_type": "permission_decision", "scope": scope, "action": action},
        output_refs=[decision_asset["path"], gate.get("path", "")],
        status=decision,
        blocking=decision != "allowed",
        metadata={"reason": reason, "matched_policy_count": len(matches)},
    )
    return {
        "status": decision,
        "allowed": decision == "allowed",
        "blocking": decision != "allowed",
        "reason": reason,
        "matched_policies": matches,
        "human_approval_gate": gate,
        "decision_path": decision_asset["path"],
        "audit_event_path": audit["path"],
    }


def create_human_approval_gate(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    gate_id = make_id("human_approval_gate", f"{payload.get('scope', 'approval')}:{payload.get('action', '')}:{utc_now()}")
    content = {
        "gate_id": gate_id,
        "status": "pending",
        "scope": _scope(payload.get("scope") or "agent"),
        "action": str(payload.get("action") or payload.get("operation") or ""),
        "subject_type": str(payload.get("subject_type") or ""),
        "subject_id": str(payload.get("subject_id") or ""),
        "resource_type": str(payload.get("resource_type") or ""),
        "resource_id": str(payload.get("resource_id") or ""),
        "reason": str(payload.get("reason") or "human approval required"),
        "trace_id": str(payload.get("trace_id") or ""),
        "created_at": utc_now(),
        "resolved_at": "",
        "resolution": {},
    }
    written = _write_asset(
        storage,
        "human_approval_gate",
        f"Human approval gate {content['scope']}:{content['action']}",
        ["permission-center", "human-approval", "pending"],
        content,
        project_id=str(payload.get("project_id") or ""),
        workspace_path=str(payload.get("workspace_path") or ""),
    )
    _audit(
        storage,
        "human_approval_gate.created",
        payload,
        target={"asset_type": "human_approval_gate", "gate_id": gate_id},
        output_refs=[written["path"]],
        status="waiting_human",
        blocking=True,
    )
    return {"status": "pending", **written}


def resolve_human_approval_gate(storage: LocalStorage, gate_ref: str | Path, payload: dict[str, Any]) -> dict[str, Any]:
    path = _resolve_asset(storage, gate_ref, "human_approval_gate")
    data = storage.read_json(path)
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    decision = str(payload.get("decision") or payload.get("status") or "").strip().lower()
    if decision not in {"approved", "rejected", "cancelled"}:
        raise ValueError("human approval gate decision must be approved, rejected, or cancelled")
    content["status"] = decision
    content["resolved_at"] = utc_now()
    content["resolution"] = {"decision": decision, "actor": str(payload.get("actor") or "operator"), "reason": str(payload.get("reason") or ""), "trace_id": str(payload.get("trace_id") or content.get("trace_id") or "")}
    data["content"] = content
    data["metadata"] = {**(data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}), "status": decision, "asset_status": decision}
    data["tags"] = _dedupe([*[str(tag) for tag in data.get("tags", [])], decision])
    data["updated_at"] = utc_now()
    storage.write_json(path, data)
    audit = _audit(
        storage,
        f"human_approval_gate.{decision}",
        {**payload, "project_id": data.get("metadata", {}).get("project_id", ""), "trace_id": content.get("trace_id", "")},
        target={"asset_type": "human_approval_gate", "gate_id": content.get("gate_id", "")},
        input_refs=[_display_path(storage.root, path)],
        status="succeeded" if decision == "approved" else "rejected",
        blocking=False,
    )
    return {"status": decision, "path": _display_path(storage.root, path), "asset": data, "audit_event_path": audit["path"]}


def permission_center_snapshot(storage: LocalStorage, *, project_id: str = "", limit: int = 300) -> dict[str, Any]:
    policies = list_permission_policies(storage, project_id=project_id or None, limit=limit)
    gates = _list_assets(storage, "human_approval_gate", project_id=project_id or None, limit=limit)
    approval_requests = list_approval_requests(storage, project_id=project_id or None, limit=limit)
    decisions = _list_assets(storage, "permission_decision", project_id=project_id or None, limit=limit)
    by_scope: dict[str, int] = {}
    for row in policies:
        scope = str(row.get("content", {}).get("scope") or "unknown")
        by_scope[scope] = by_scope.get(scope, 0) + 1
    pending = [row for row in gates if str(row.get("content", {}).get("status", "")) == "pending"]
    pending_requests = [row for row in approval_requests if str(row.get("content", {}).get("status", "")) == "pending"]
    blocking_requests = [row for row in pending_requests if bool(row.get("content", {}).get("blocking"))]
    denied = [row for row in decisions if str(row.get("content", {}).get("status", "")) == "denied"]
    return {
        "status": "blocked" if pending or blocking_requests or denied else "ready",
        "summary": {
            "policy_count": len(policies),
            "gate_count": len(gates),
            "pending_gate_count": len(pending),
            "approval_request_count": len(approval_requests),
            "pending_approval_request_count": len(pending_requests),
            "blocking_approval_request_count": len(blocking_requests),
            "decision_count": len(decisions),
            "denied_decision_count": len(denied),
            "by_scope": by_scope,
            "audit_required": True,
        },
        "policies": policies[:120],
        "human_approval_gates": gates[:120],
        "approval_requests": approval_requests[:120],
        "decisions": decisions[:120],
        "required_scopes": sorted(PERMISSION_SCOPES),
        "approval_request_scopes": sorted(APPROVAL_REQUEST_SCOPES),
        "created_at": utc_now(),
    }


def _approval_scope(value: Any) -> str:
    normalized = str(value or "agent").strip().lower().replace("-", "_")
    return normalized if normalized in APPROVAL_REQUEST_SCOPES else "agent"


def _risk_level(value: Any) -> str:
    normalized = str(value or "medium").strip().lower()
    return normalized if normalized in APPROVAL_REQUEST_RISK_LEVELS else "medium"


def _approval_blocking(payload: dict[str, Any], *, environment: str, risk_level: str, scope: str) -> bool:
    if "blocking" in payload:
        return bool(payload.get("blocking"))
    if "requires_blocking_approval" in payload:
        return bool(payload.get("requires_blocking_approval"))
    production = is_production_environment(environment)
    if production:
        return scope in {"source", "context", "publish", "story_mutation", "provider", "fallback", "canon", "feedback", "budget"} or risk_level in {"high", "critical"}
    return risk_level == "critical"


def _approval_required_before(scope: str, action: str) -> list[str]:
    if scope == "source":
        return ["source_context_injection", "mkaos_asset_activation"]
    if scope == "publish":
        return ["publish_gate", "external_platform_submission"]
    if scope == "story_mutation":
        return ["outline_patch", "chapter_plan_patch", "regeneration_task"]
    if scope == "context":
        return ["context_bundle_build"]
    if scope == "provider":
        return ["provider_route_resolution", "model_call"]
    if scope == "feedback":
        return ["mutation_application", "downstream_invalidation"]
    if scope == "budget":
        return ["cost_policy_change"]
    return [action or "operation"]


def _approval_rollback_plan(payload: dict[str, Any], *, scope: str) -> dict[str, Any]:
    explicit = payload.get("rollback_plan")
    if isinstance(explicit, dict):
        return explicit
    if scope == "publish":
        return {"strategy": "manual_release_hold", "steps": ["do_not_submit_platform_package", "rerun_publish_gate_after_resolution"]}
    if scope == "story_mutation":
        return {"strategy": "versioned_patch_rollback", "steps": ["preserve_previous_outline_or_plan_version", "invalidate_downstream_generated_assets"]}
    if scope == "source":
        return {"strategy": "source_quarantine", "steps": ["keep_source_evidence_only", "remove_from_context_selection"]}
    return {"strategy": "no_side_effect_before_approval", "steps": ["request_does_not_apply_changes_until_approved"]}


def _policy_matches(policy_asset: dict[str, Any], payload: dict[str, Any], *, scope: str, action: str, environment: str) -> bool:
    policy = _policy_row(policy_asset)
    if policy["scope"] != scope:
        return False
    if policy["status"] != "active":
        return False
    if policy["environment"] not in {"*", environment}:
        return False
    if "*" not in policy["actions"] and action not in policy["actions"]:
        return False
    for key in ["subject_type", "subject_id", "resource_type", "resource_id"]:
        expected = str(policy.get(key) or "*")
        actual = str(payload.get(key) or "")
        if expected not in {"*", actual}:
            return False
    return True


def _policy_row(policy_asset: dict[str, Any]) -> dict[str, Any]:
    content = policy_asset.get("content", {}) if isinstance(policy_asset.get("content", {}), dict) else {}
    return {
        "policy_id": str(content.get("policy_id") or policy_asset.get("id") or ""),
        "scope": str(content.get("scope") or ""),
        "subject_type": str(content.get("subject_type") or "*"),
        "subject_id": str(content.get("subject_id") or "*"),
        "resource_type": str(content.get("resource_type") or "*"),
        "resource_id": str(content.get("resource_id") or "*"),
        "actions": _strings(content.get("actions")) or ["*"],
        "effect": _effect(content.get("effect") or "allow"),
        "environment": str(content.get("environment") or "*"),
        "requires_human_approval": bool(content.get("requires_human_approval")),
        "status": _status(content.get("status") or "active"),
        "path": str(policy_asset.get("path") or ""),
    }


def _has_approved_gate(storage: LocalStorage, payload: dict[str, Any], *, scope: str, action: str) -> bool:
    subject_id = str(payload.get("subject_id") or "")
    resource_id = str(payload.get("resource_id") or "")
    for gate in _list_assets(storage, "human_approval_gate", project_id=str(payload.get("project_id") or "") or None, limit=500):
        content = gate.get("content", {}) if isinstance(gate.get("content", {}), dict) else {}
        if str(content.get("status", "")) != "approved":
            continue
        if str(content.get("scope", "")) != scope or str(content.get("action", "")) != action:
            continue
        if subject_id and str(content.get("subject_id", "")) not in {"", subject_id}:
            continue
        if resource_id and str(content.get("resource_id", "")) not in {"", resource_id}:
            continue
        return True
    return False


def _write_asset(
    storage: LocalStorage,
    asset_type: str,
    title: str,
    tags: list[str],
    content: dict[str, Any],
    *,
    project_id: str = "",
    workspace_path: str = "",
    references: list[str] | None = None,
) -> dict[str, Any]:
    asset = BaseAsset(
        type=asset_type,
        title=title,
        tags=tags,
        content=content,
        metadata={"project_id": project_id, "workspace_path": workspace_path, "asset_status": str(content.get("status") or ""), "use_in_generation_rag": False},
        references=filter_project_safe_references(storage, project_id, references or []),
    )
    data = asset.to_dict()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset("runs", asset)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path)}


def _audit(
    storage: LocalStorage,
    action: str,
    payload: dict[str, Any],
    *,
    target: dict[str, Any],
    input_refs: list[str] | None = None,
    output_refs: list[str] | None = None,
    status: str,
    blocking: bool = False,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    trace_id = str(payload.get("trace_id") or make_id("trace", f"permission:{action}:{utc_now()}"))
    return record_audit_event(
        storage,
        event_type="permission_center",
        action=action,
        actor_type=str(payload.get("actor_type") or "system"),
        actor_id=str(payload.get("actor") or payload.get("actor_id") or "permission-center"),
        target=target,
        project_id=str(payload.get("project_id") or ""),
        trace_id=trace_id,
        input_refs=input_refs or [],
        output_refs=output_refs or [],
        status=status,
        blocking=blocking,
        metadata=metadata or {},
    )


def _list_assets(storage: LocalStorage, asset_type: str, *, project_id: str | None, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in reversed(storage.list_json("runs")):
        data = _read_json_safe(storage, path)
        if data.get("type") != asset_type:
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if project_id and str(metadata.get("project_id", "")) != project_id:
            continue
        rows.append({**data, "path": _display_path(storage.root, path)})
        if len(rows) >= max(1, int(limit or 300)):
            break
    return rows


def _resolve_asset(storage: LocalStorage, value: str | Path, asset_type: str) -> Path:
    path = resolve_path(storage.root, value)
    if path.exists() and _read_json_safe(storage, path).get("type") == asset_type:
        return path
    for candidate in storage.list_json("runs"):
        data = _read_json_safe(storage, candidate)
        if data.get("type") != asset_type:
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if str(data.get("id", "")) == str(value) or str(content.get("gate_id", "")) == str(value) or str(content.get("request_id", "")) == str(value):
            return candidate
    raise FileNotFoundError(f"{asset_type} not found: {value}")


def _read_json_safe(storage: LocalStorage, path: Path) -> dict[str, Any]:
    try:
        data = storage.read_json(path)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _display_path(root: Path, path: str | Path) -> str:
    candidate = Path(path)
    try:
        return str(candidate.relative_to(root))
    except ValueError:
        return str(candidate)


def _scope(value: Any) -> str:
    scope = str(value or "tool").strip().lower().replace("_", "-")
    aliases = {"tools": "tool", "agents": "agent", "sources": "source", "publishing": "publish", "bypasses": "bypass"}
    normalized = aliases.get(scope, scope)
    if normalized not in PERMISSION_SCOPES:
        raise ValueError(f"permission scope must be one of: {', '.join(sorted(PERMISSION_SCOPES))}")
    return normalized


def _effect(value: Any) -> str:
    effect = str(value or "allow").strip().lower()
    if effect not in {"allow", "deny"}:
        raise ValueError("permission effect must be allow or deny")
    return effect


def _status(value: Any) -> str:
    status = str(value or "active").strip().lower()
    if status not in {"active", "disabled", "deprecated"}:
        raise ValueError("permission policy status must be active, disabled, or deprecated")
    return status


def _strings(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _dedupe(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result
