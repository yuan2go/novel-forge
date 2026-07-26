from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from urllib.parse import urlsplit
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.os_envelope import is_production_environment
from novel_forge.modules.runtime_ledger import record_cost_ledger, record_trace_span
from novel_forge.modules.production_execution import (
    ExternalActionExecutionPort,
    ExternalActionKind,
    execute_external_action,
)
from novel_forge.modules.source_intake.service import (
    SOURCE_CONNECTOR_ALLOWLIST,
    _approval_status,
    _asset_ref,
    _dedupe,
    _latest_related_asset,
    _resolve_governance_asset,
    _short_ref_key,
    _source_ref,
    _strings,
    create_source_sync_job,
)
from novel_forge.storage.local import LocalStorage


CONTROLLED_CONNECTOR_KINDS = {"git", "rss", "public_domain"}


@dataclass(frozen=True, slots=True)
class ControlledConnectorPlan:
    connector_kind: str
    project_id: str
    endpoint: str
    allowlisted_hosts: tuple[str, ...]
    timeout_seconds: int
    max_retries: int
    max_requests_per_minute: int
    max_content_bytes: int
    allowed_media_types: tuple[str, ...]
    license_required: bool
    robots_tos_evidence_required: bool
    approval_required: bool
    network_enabled: bool = False


def plan_controlled_connector(
    *,
    connector_kind: str,
    project_id: str,
    endpoint: str,
    allowlisted_hosts: list[str],
    approval_granted: bool = False,
    timeout_seconds: int = 10,
    max_retries: int = 2,
    max_requests_per_minute: int = 20,
    max_content_bytes: int = 2_000_000,
    allowed_media_types: tuple[str, ...] = ("text/plain", "text/markdown", "application/xml", "application/rss+xml"),
) -> dict[str, Any]:
    """Return an ExternalEffect-shaped, no-default-network connector plan."""
    kind = connector_kind.strip().lower()
    if kind not in CONTROLLED_CONNECTOR_KINDS:
        raise ValueError("unsupported controlled connector kind")
    if not project_id or timeout_seconds <= 0 or max_retries < 0 or max_requests_per_minute <= 0:
        raise ValueError("invalid connector limits")
    parsed = urlsplit(endpoint)
    host = (parsed.hostname or "").lower()
    allowed = {item.lower() for item in allowlisted_hosts}
    if parsed.scheme not in {"https", "file"}:
        raise ValueError("connector endpoint scheme is not allowed")
    if parsed.scheme == "https" and host not in allowed:
        raise ValueError("connector endpoint host is not allowlisted")
    requires_approval = parsed.scheme == "https"
    plan = ControlledConnectorPlan(
        connector_kind=kind,
        project_id=project_id,
        endpoint=endpoint,
        allowlisted_hosts=tuple(sorted(allowed)),
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        max_requests_per_minute=max_requests_per_minute,
        max_content_bytes=max_content_bytes,
        allowed_media_types=allowed_media_types,
        license_required=True,
        robots_tos_evidence_required=parsed.scheme == "https",
        approval_required=requires_approval,
        network_enabled=False,
    )
    status = "READY_FOR_APPROVED_ADAPTER" if (not requires_approval or approval_granted) else "REQUIRES_APPROVAL"
    return {
        "status": status,
        "plan": asdict(plan),
        "external_effect_intent": {
            "capability": ExternalActionKind.SOURCE_FETCH.value,
            "status": "PLANNED",
            "project_id": project_id,
            "idempotency_key_required": True,
            "dispatch_allowed": bool(approval_granted and requires_approval),
        },
        "network_execution_performed": False,
        "connector_contract_version": "controlled-source-connector-v1",
    }


def execute_controlled_fixture(
    plan_result: dict[str, Any],
    *,
    content: bytes,
    media_type: str,
    license_metadata: dict[str, Any],
    robots_tos_evidence: dict[str, Any] | None = None,
    previous_checksum: str = "",
) -> dict[str, Any]:
    """Deterministic local/test adapter; never performs network access."""
    plan = plan_result.get("plan", {})
    if plan_result.get("status") != "READY_FOR_APPROVED_ADAPTER":
        raise ValueError("connector plan is not approved for adapter execution")
    if media_type not in plan.get("allowed_media_types", []):
        raise ValueError("connector media type is not allowed")
    if len(content) > int(plan.get("max_content_bytes", 0)):
        raise ValueError("connector content size limit exceeded")
    if not license_metadata.get("license_id") or license_metadata.get("commercial_use_allowed") is not True:
        raise ValueError("connector license evidence is incomplete")
    if plan.get("robots_tos_evidence_required") and not (
        robots_tos_evidence
        and robots_tos_evidence.get("robots_checked")
        and robots_tos_evidence.get("tos_checked")
    ):
        raise ValueError("robots/ToS evidence is required")
    decoded = content.decode("utf-8", errors="replace")
    injection_signals = [
        signal for signal in ("ignore previous instructions", "system prompt", "developer message")
        if signal in decoded.lower()
    ]
    checksum = "sha256:" + hashlib.sha256(content).hexdigest()
    changed = checksum != previous_checksum
    status = "QUARANTINED" if injection_signals else "SNAPSHOTTED"
    return {
        "status": status,
        "snapshot": {
            "project_id": plan["project_id"],
            "connector_kind": plan["connector_kind"],
            "checksum": checksum,
            "byte_count": len(content),
            "media_type": media_type,
            "license_metadata": dict(license_metadata),
            "prompt_injection_scan": {"passed": not injection_signals, "signals": injection_signals},
            "raw_content_persisted": False,
        },
        "receipt": {
            "capability": ExternalActionKind.SOURCE_FETCH.value,
            "status": "SUCCEEDED" if not injection_signals else "QUARANTINED",
            "checksum": checksum,
            "network_access_used": False,
            "fixture_adapter": True,
            "fixture_protocol_only": True,
            "real_model_call": False,
            "production_verified": False,
        },
        "source_diff": {"changed": changed, "previous_checksum": previous_checksum, "current_checksum": checksum},
        "downstream_invalidation_recommendation": "PLAN_REGENERATION" if changed else "NO_CHANGE",
        "audit": {"project_id": plan["project_id"], "connector_kind": plan["connector_kind"], "status": status},
    }


def fetch_remote_source_candidate(
    *,
    source_ref: str,
    connector_id: str,
    source_policy_ref: str,
    stable_idempotency_key: str,
    execution_port: ExternalActionExecutionPort,
) -> dict[str, Any]:
    """Fetch candidate bytes/metadata through PEP; source eligibility stays local."""

    candidate = execute_external_action(
        capability=ExternalActionKind.SOURCE_FETCH,
        request_payload={
            "source_ref": source_ref,
            "connector_id": connector_id,
            "source_policy_ref": source_policy_ref,
        },
        stable_idempotency_key=stable_idempotency_key,
        data_classification="SOURCE_MATERIAL",
        privacy_policy_ref="privacy-policy:source-intake:v1",
        rate_limit_policy_ref="rate-limit-policy:source-intake:v1",
        quota_policy_ref="quota-policy:source-intake:v1",
        execution_port=execution_port,
    )
    return {
        "candidate": dict(candidate.raw_output),
        "execution": candidate.evidence.to_dict(),
        "source_eligibility_decided": False,
        "asset_committed": False,
    }


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
