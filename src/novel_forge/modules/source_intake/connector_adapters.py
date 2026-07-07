from __future__ import annotations

from urllib.parse import urlsplit
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.os_envelope import is_production_environment
from novel_forge.modules.runtime_ledger import record_cost_ledger, record_trace_span
from novel_forge.modules.source_intake.service import (
    SOURCE_CONNECTOR_ALLOWLIST,
    _approval_status,
    _asset_ref,
    _dedupe,
    _display_path,
    _latest_related_asset,
    _resolve_governance_asset,
    _short_ref_key,
    _source_ref,
    _strings,
    create_source_sync_job,
)
from novel_forge.storage.local import LocalStorage


def list_source_connector_adapters(include_network: bool = True) -> list[dict[str, Any]]:
    adapters: list[dict[str, Any]] = []
    for connector_id, policy in sorted(SOURCE_CONNECTOR_ALLOWLIST.items()):
        if bool(policy.get("network_access")) and not include_network:
            continue
        adapters.append(_public_adapter_policy(connector_id, policy))
    return adapters


def plan_source_connector_adapter_lifecycle(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    storage.ensure_layout()
    source_ref = _source_ref(payload)
    connector_id = str(payload.get("connector_id") or "manual_metadata_connector").strip()
    connector_policy = SOURCE_CONNECTOR_ALLOWLIST.get(connector_id)
    environment = str(payload.get("environment") or "local")
    execute_requested = bool(payload.get("execute") or payload.get("execute_requested"))
    project_id = str(payload.get("project_id") or "")
    workspace_path = str(payload.get("workspace_path") or "")
    approval_status = _approval_status(storage, payload.get("approval_request_path") or payload.get("approval_request_ref"))
    policy_asset = _resolve_governance_asset(storage, payload.get("source_policy_path") or payload.get("policy_ref"), "source_policy") or _latest_related_asset(storage, "source_policy", source_ref)
    refresh = _resolve_governance_asset(storage, payload.get("source_refresh_report_path") or payload.get("refresh_report_ref"), "source_refresh_report") or _latest_related_asset(storage, "source_refresh_report", source_ref)

    if not connector_policy:
        receipt = _adapter_lifecycle_receipt(
            connector_id=connector_id,
            source_ref=source_ref,
            status="blocked_connector_not_allowed",
            reason="connector is not registered in SOURCE_CONNECTOR_ALLOWLIST",
            approval_status=approval_status,
            execute_requested=execute_requested,
            connector_policy={},
            payload=payload,
        )
        trace, cost = _record_adapter_lifecycle_ledgers(storage, receipt, project_id=project_id, workspace_path=workspace_path)
        receipt["trace_span_path"] = trace.get("path", "")
        receipt["cost_ledger_path"] = cost.get("path", "")
        sync_job = _write_adapter_sync_job(storage, payload, source_ref, policy_asset, refresh, receipt, status="blocked")
        return {"status": "blocked", "allowed": False, "adapter": {}, "sync_job": sync_job, "approval_request": {}, "execution_receipt": receipt}

    requires_approval = bool(
        execute_requested
        or is_production_environment(environment)
        or connector_policy.get("network_access")
        or connector_policy.get("file_access")
        or connector_policy.get("adapter_lifecycle_required")
    )
    approval_request: dict[str, Any] = {}
    if requires_approval and approval_status != "approved":
        from novel_forge.modules.permission_center import create_approval_request

        approval_request = create_approval_request(
            storage,
            {
                "project_id": project_id,
                "workspace_path": workspace_path,
                "scope": "source",
                "action": "approve_source_connector_adapter_policy",
                "environment": environment,
                "risk_level": str(connector_policy.get("risk_level") or "medium"),
                "blocking": True,
                "target_type": "source_connector_adapter",
                "target_id": f"{_short_ref_key(source_ref)}:{connector_id}",
                "target_path": str(payload.get("endpoint") or payload.get("source_path") or ""),
                "target_refs": [source_ref, connector_id],
                "evidence_refs": _dedupe([_asset_ref(refresh), _asset_ref(policy_asset), *_strings(payload.get("evidence_refs")), *_strings(payload.get("references"))]),
                "reason": f"Approve connector adapter lifecycle policy before {connector_id} can access source {source_ref}",
                "source_policy": {
                    "source_ref": source_ref,
                    "connector_id": connector_id,
                    "network_access": bool(connector_policy.get("network_access")),
                    "file_access": bool(connector_policy.get("file_access")),
                    "default_network_execution_allowed": bool(connector_policy.get("default_network_execution_allowed")),
                    "adapter_lifecycle_required": bool(connector_policy.get("adapter_lifecycle_required")),
                    "rate_limit_policy": _rate_limit_policy(connector_policy, payload),
                    "callback_policy": _callback_policy(connector_policy, payload),
                },
            },
        )
        approval_status = "pending"

    if approval_status != "approved" and requires_approval:
        status = "approval_required"
    elif bool(connector_policy.get("network_access")):
        status = "network_execution_blocked_by_default"
    else:
        status = "adapter_lifecycle_recorded"

    receipt = _adapter_lifecycle_receipt(
        connector_id=connector_id,
        source_ref=source_ref,
        status=status,
        reason="network connectors are policy-recorded but not executed by default" if bool(connector_policy.get("network_access")) else "adapter lifecycle policy recorded without connector invocation",
        approval_status=approval_status,
        execute_requested=execute_requested,
        connector_policy=connector_policy,
        payload=payload,
    )
    trace, cost = _record_adapter_lifecycle_ledgers(storage, receipt, project_id=project_id, workspace_path=workspace_path)
    receipt["trace_span_path"] = trace.get("path", "")
    receipt["cost_ledger_path"] = cost.get("path", "")
    approval_ref = str(approval_request.get("path") or payload.get("approval_request_path") or payload.get("approval_request_ref") or "")
    sync_job = _write_adapter_sync_job(storage, {**payload, "approval_request_ref": approval_ref}, source_ref, policy_asset, refresh, receipt, status=status)
    return {
        "status": status,
        "allowed": bool(status == "adapter_lifecycle_recorded" and not connector_policy.get("network_access")),
        "adapter": _public_adapter_policy(connector_id, connector_policy),
        "sync_job": sync_job,
        "approval_request": approval_request,
        "execution_receipt": receipt,
        "network_access_used": False,
        "file_access_used": False,
        "subprocess_used": False,
    }


def _write_adapter_sync_job(
    storage: LocalStorage,
    payload: dict[str, Any],
    source_ref: str,
    policy_asset: dict[str, Any] | None,
    refresh: dict[str, Any] | None,
    receipt: dict[str, Any],
    *,
    status: str,
) -> dict[str, Any]:
    return create_source_sync_job(
        storage,
        {
            **payload,
            "source_ref": source_ref,
            "status": status,
            "sync_mode": "connector_adapter_lifecycle",
            "policy_ref": _asset_ref(policy_asset) or "missing_source_policy",
            "connector_execution": receipt["connector_execution"],
            "approval_request_ref": str(payload.get("approval_request_ref") or payload.get("approval_request_path") or ""),
            "refresh_report_ref": _asset_ref(refresh),
            "execution_receipt": receipt,
            "limits": {"rate_limit_policy": receipt["rate_limit_policy"], "budget_policy": receipt["budget_policy"]},
        },
    )


def _adapter_lifecycle_receipt(
    *,
    connector_id: str,
    source_ref: str,
    status: str,
    reason: str,
    approval_status: str,
    execute_requested: bool,
    connector_policy: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "receipt_id": make_id("source_connector_adapter_receipt", f"{_short_ref_key(source_ref)}:{connector_id}:{status}:{utc_now()}"),
        "receipt_kind": "source_connector_adapter_lifecycle",
        "status": status,
        "source_ref": source_ref,
        "connector_id": connector_id,
        "approval_status": approval_status or "missing",
        "execute_requested": execute_requested,
        "execution_performed": False,
        "network_access_used": False,
        "file_access_used": False,
        "subprocess_used": False,
        "connector_execution": {
            "connector_id": connector_id,
            "connector_kind": str(connector_policy.get("connector_kind") or "unknown"),
            "allowlisted": bool(connector_policy and connector_policy.get("allowlisted", True)),
            "network_access_allowed": bool(connector_policy.get("network_access")),
            "file_access_allowed": bool(connector_policy.get("file_access")),
            "default_network_execution_allowed": bool(connector_policy.get("default_network_execution_allowed")),
            "adapter_lifecycle_required": bool(connector_policy.get("adapter_lifecycle_required")),
            "execution_boundary": "adapter_lifecycle_no_connector_invocation",
        },
        "rate_limit_policy": _rate_limit_policy(connector_policy, payload),
        "callback_policy": _callback_policy(connector_policy, payload),
        "subprocess_policy": {
            "subprocess_allowed": False,
            "requires_separate_tool_gateway_approval": True,
        },
        "budget_policy": {
            "cost_cap_required": bool(connector_policy.get("network_access")),
            "default_cost_cap": 0.0,
            "currency": "USD",
        },
        "receipt_schema": connector_policy.get("receipt_schema", []) if isinstance(connector_policy.get("receipt_schema", []), list) else [],
        "reason": reason,
        "rollback_plan": ["no external side effects were performed", "discard SourceSyncJob plan if approval is rejected"],
        "created_at": utc_now(),
    }


def _public_adapter_policy(connector_id: str, policy: dict[str, Any]) -> dict[str, Any]:
    return {
        "connector_id": connector_id,
        "connector_kind": str(policy.get("connector_kind") or "unknown"),
        "network_access": bool(policy.get("network_access")),
        "file_access": bool(policy.get("file_access")),
        "risk_level": str(policy.get("risk_level") or "unknown"),
        "allowlisted": bool(policy.get("allowlisted", True)),
        "default_network_execution_allowed": bool(policy.get("default_network_execution_allowed")),
        "adapter_lifecycle_required": bool(policy.get("adapter_lifecycle_required")),
        "rate_limit_policy": policy.get("rate_limit_policy", {}) if isinstance(policy.get("rate_limit_policy", {}), dict) else {},
        "callback_policy": policy.get("callback_policy", {}) if isinstance(policy.get("callback_policy", {}), dict) else {},
        "receipt_schema": policy.get("receipt_schema", []) if isinstance(policy.get("receipt_schema", []), list) else [],
    }


def _rate_limit_policy(connector_policy: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    base = connector_policy.get("rate_limit_policy", {}) if isinstance(connector_policy.get("rate_limit_policy", {}), dict) else {}
    override = payload.get("rate_limit_policy", {}) if isinstance(payload.get("rate_limit_policy", {}), dict) else {}
    merged = {**base, **{key: value for key, value in override.items() if key in {"max_requests_per_minute", "burst", "cooldown_seconds", "retry_after_required"}}}
    merged["operator_override_present"] = bool(override)
    merged["network_access_used"] = False
    return merged


def _callback_policy(connector_policy: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    base = connector_policy.get("callback_policy", {}) if isinstance(connector_policy.get("callback_policy", {}), dict) else {}
    override = payload.get("callback_policy", {}) if isinstance(payload.get("callback_policy", {}), dict) else {}
    callback_url = str(override.get("callback_url") or payload.get("callback_url") or "")
    return {
        **base,
        "callback_url_redacted": _redact_endpoint(callback_url) if callback_url else "",
        "operator_override_present": bool(override or callback_url),
        "store_raw_callback_body": False,
        "raw_callback_body_included": False,
    }


def _record_adapter_lifecycle_ledgers(storage: LocalStorage, receipt: dict[str, Any], *, project_id: str, workspace_path: str) -> tuple[dict[str, Any], dict[str, Any]]:
    trace_id = make_id("trace", f"source-connector-adapter:{receipt.get('source_ref', '')}:{receipt.get('connector_id', '')}:{utc_now()}")
    trace = record_trace_span(
        storage,
        trace_id=trace_id,
        span_type="source_connector_adapter",
        name=f"adapter:{receipt.get('connector_id', '')}",
        status="blocked" if str(receipt.get("status") or "").startswith("blocked") or "blocked" in str(receipt.get("status") or "") else "succeeded",
        attributes={
            "source_ref": str(receipt.get("source_ref") or ""),
            "connector_id": str(receipt.get("connector_id") or ""),
            "status": str(receipt.get("status") or ""),
            "network_access_used": False,
            "file_access_used": False,
            "subprocess_used": False,
        },
        project_id=project_id,
        workspace_path=workspace_path,
    )
    cost = record_cost_ledger(
        storage,
        scope="source_governance",
        amount=0.0,
        currency="USD",
        source_type="source_connector_adapter_lifecycle",
        source_id=str(receipt.get("receipt_id") or ""),
        trace={"trace_id": trace_id},
        project_id=project_id,
        workspace_path=workspace_path,
        metadata={"connector_id": str(receipt.get("connector_id") or ""), "network_access_used": False, "file_access_used": False},
    )
    return trace, cost


def _redact_endpoint(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return "invalid-endpoint"
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}/..."
