from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.modules.runtime_ledger import record_cost_ledger, record_trace_span
from novel_forge.modules.source_intake.diff_repair import plan_source_diff_repair
from novel_forge.modules.source_intake.service import (
    SOURCE_CONNECTOR_ALLOWLIST,
    _asset_ref,
    _connector_execution_receipt,
    _content_value,
    _dedupe,
    _display_path,
    _latest_related_asset,
    _resolve_governance_asset,
    create_source_refresh_report,
    create_source_snapshot,
)
from novel_forge.schemas import validate_common_fields
from novel_forge.storage.local import LocalStorage


def run_source_connector(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    storage.ensure_layout()
    sync_path = resolve_path(storage.root, payload.get("sync_job_path") or payload.get("source_sync_job_path") or payload.get("job_path"))
    sync_job = storage.read_json(sync_path)
    if not isinstance(sync_job, dict) or sync_job.get("type") != "source_sync_job":
        raise ValueError("sync_job_path must point to a source_sync_job asset")
    content = sync_job.get("content", {}) if isinstance(sync_job.get("content", {}), dict) else {}
    source_ref = str(payload.get("source_ref") or content.get("source_ref") or sync_job.get("source") or "")
    project_id = str(payload.get("project_id") or _metadata_value(sync_job, "project_id") or "")
    workspace_path = str(payload.get("workspace_path") or _metadata_value(sync_job, "workspace_path") or "")
    connector_execution = content.get("connector_execution", {}) if isinstance(content.get("connector_execution", {}), dict) else {}
    connector_id = str(payload.get("connector_id") or connector_execution.get("connector_id") or "manual_metadata_connector")
    connector_policy = SOURCE_CONNECTOR_ALLOWLIST.get(connector_id)
    trace_id = make_id("trace", f"source-connector-runner:{source_ref}:{connector_id}:{utc_now()}")
    approval = _read_approval_request(storage, payload.get("approval_request_path") or payload.get("approval_request_ref") or content.get("approval_request_ref"))
    if _approval_status(approval) != "approved":
        trace = _record_connector_trace(storage, trace_id, "skipped", connector_id, source_ref, project_id, workspace_path, {"reason": "approval_required"})
        return _blocked_result("approval_required", "approved ApprovalRequest is required before connector execution", trace)
    if not connector_policy or not bool(connector_policy.get("allowlisted", True)):
        trace = _record_connector_trace(storage, trace_id, "failed", connector_id, source_ref, project_id, workspace_path, {"reason": "connector_not_allowlisted"})
        return _blocked_result("blocked_connector_not_allowed", "connector is not in SOURCE_CONNECTOR_ALLOWLIST", trace)
    if bool(connector_policy.get("network_access")):
        trace = _record_connector_trace(storage, trace_id, "failed", connector_id, source_ref, project_id, workspace_path, {"reason": "network_connectors_denied"})
        receipt = _connector_execution_receipt(
            connector_id=connector_id,
            source_ref=source_ref,
            status="blocked_network_connector",
            reason="network connector execution is denied by the local sandbox; use connector adapter lifecycle evidence first",
            approval_status=_approval_status(approval),
            execute_requested=True,
            connector_policy=connector_policy,
        )
        sync_update = _update_connector_sync_job(storage, sync_path, sync_job, status="blocked_network_connector", receipt=receipt)
        return {
            **_blocked_result("blocked_network_connector", "network connector execution is denied by the local sandbox", trace),
            "sync_job": sync_update,
            "execution_receipt": sync_update["asset"]["content"]["execution_receipt"],
        }
    source_path = str(payload.get("source_path") or "").strip()
    if not source_path:
        trace = _record_connector_trace(storage, trace_id, "failed", connector_id, source_ref, project_id, workspace_path, {"reason": "source_path_required"})
        return _blocked_result("blocked_missing_source_path", "local connector execution requires source_path", trace)
    source_file = resolve_path(storage.root, source_path)
    allowed_roots = _allowed_roots(storage, payload.get("allowed_roots"))
    if not _path_within_allowed_roots(source_file, allowed_roots):
        trace = _record_connector_trace(
            storage,
            trace_id,
            "failed",
            connector_id,
            source_ref,
            project_id,
            workspace_path,
            {"reason": "path_outside_allowed_roots", "source_path": str(source_file), "allowed_roots": [str(root) for root in allowed_roots]},
        )
        return _blocked_result("blocked_path_outside_allowed_roots", "source_path is outside the approved connector sandbox roots", trace)
    try:
        data = source_file.read_bytes()
    except OSError as exc:
        trace = _record_connector_trace(storage, trace_id, "failed", connector_id, source_ref, project_id, workspace_path, {"reason": "file_read_failed", "error": str(exc)})
        return _blocked_result("failed_file_read", str(exc), trace)
    content_hash = hashlib.sha256(data).hexdigest()
    trace = _record_connector_trace(
        storage,
        trace_id,
        "succeeded",
        connector_id,
        source_ref,
        project_id,
        workspace_path,
        {"source_path": _safe_display_path(storage.root, source_file), "byte_count": len(data), "content_hash": content_hash},
    )
    cost = record_cost_ledger(
        storage,
        scope="source_governance",
        amount=0.0,
        currency="USD",
        source_type="source_connector_runner",
        source_id=str(content.get("job_id") or sync_job.get("id") or connector_id),
        trace={"trace_id": trace_id},
        project_id=project_id,
        workspace_path=workspace_path,
        metadata={"connector_id": connector_id, "network_access_used": False, "file_access_used": True},
    )
    policy_ref, risk_ref = _snapshot_governance_refs(storage, source_ref, sync_job, payload)
    snapshot = create_source_snapshot(
        storage,
        {
            "source_ref": source_ref,
            "source_type": str(payload.get("source_type") or connector_policy.get("connector_kind") or "local_file"),
            "source_path": _safe_display_path(storage.root, source_file),
            "content_hash": content_hash,
            "content": f"connector metadata only: sha256={content_hash}; bytes={len(data)}",
            "source_policy_path": policy_ref,
            "risk_report_path": risk_ref,
            "project_id": project_id,
            "workspace_path": workspace_path,
            "evidence_refs": _dedupe([_display_path(storage.root, sync_path), str(approval.get("path") or ""), trace.get("path", ""), cost.get("path", "")]),
        },
    )
    sync_update = _update_connector_sync_job(
        storage,
        sync_path,
        sync_job,
        status="completed",
        receipt={
            "receipt_id": make_id("source_connector_execution_receipt", f"{source_ref}:{connector_id}:completed:{utc_now()}"),
            "status": "completed",
            "source_ref": source_ref,
            "connector_id": connector_id,
            "approval_request_path": str(approval.get("path") or ""),
            "execution_performed": True,
            "network_access_used": False,
            "file_access_used": True,
            "source_path": _safe_display_path(storage.root, source_file),
            "byte_count": len(data),
            "content_hash": content_hash,
            "trace_span_path": trace.get("path", ""),
            "cost_ledger_path": cost.get("path", ""),
            "snapshot_path": snapshot.get("path", ""),
            "created_at": utc_now(),
        },
    )
    refresh = create_source_refresh_report(
        storage,
        {
            "source_ref": source_ref,
            "snapshot_path": snapshot["path"],
            "sync_job_path": sync_update["path"],
            "expected_content_hash": content_hash,
            "project_id": project_id,
            "workspace_path": workspace_path,
            "evidence_refs": [trace.get("path", ""), cost.get("path", ""), str(approval.get("path") or "")],
        },
    )
    diff_plan: dict[str, Any] = {}
    previous_snapshot_path = str(payload.get("previous_snapshot_path") or payload.get("old_snapshot_path") or "").strip()
    if previous_snapshot_path and bool(payload.get("create_diff_repair_plan", True)):
        diff_plan = plan_source_diff_repair(
            storage,
            {
                "source_ref": source_ref,
                "old_snapshot_path": previous_snapshot_path,
                "new_snapshot_path": snapshot["path"],
                "source_refresh_report_path": refresh["path"],
                "project_id": project_id,
                "workspace_path": workspace_path,
            },
        )
    return {
        "status": "completed",
        "source_ref": source_ref,
        "connector_id": connector_id,
        "sync_job": sync_update,
        "snapshot": snapshot,
        "refresh_report": refresh,
        "diff_repair_plan": diff_plan,
        "trace_span_path": trace.get("path", ""),
        "cost_ledger_path": cost.get("path", ""),
        "execution_receipt": sync_update["asset"]["content"]["execution_receipt"],
        "network_access_used": False,
        "file_access_used": True,
    }


def _blocked_result(status: str, reason: str, trace: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "execution_performed": False,
        "network_access_used": False,
        "file_access_used": False,
        "trace_span_path": trace.get("path", ""),
    }


def _snapshot_governance_refs(storage: LocalStorage, source_ref: str, sync_job: dict[str, Any], payload: dict[str, Any]) -> tuple[str, str]:
    content = sync_job.get("content", {}) if isinstance(sync_job.get("content", {}), dict) else {}
    refresh = _resolve_governance_asset(storage, content.get("refresh_report_ref"), "source_refresh_report")
    refresh_content = refresh.get("content", {}) if isinstance(refresh, dict) and isinstance(refresh.get("content", {}), dict) else {}
    governance_refs = refresh_content.get("governance_refs", {}) if isinstance(refresh_content.get("governance_refs", {}), dict) else {}
    policy = str(payload.get("source_policy_path") or payload.get("policy_ref") or content.get("policy_ref") or governance_refs.get("source_policy_ref") or "")
    risk = str(payload.get("risk_report_path") or payload.get("risk_ref") or governance_refs.get("source_risk_report_ref") or "")
    if not policy:
        policy = _asset_ref(_latest_related_asset(storage, "source_policy", source_ref))
    if not risk:
        risk = _asset_ref(_latest_related_asset(storage, "source_risk_report", source_ref))
    return policy, risk


def _update_connector_sync_job(storage: LocalStorage, sync_path: Path, sync_job: dict[str, Any], *, status: str, receipt: dict[str, Any]) -> dict[str, Any]:
    content = sync_job.get("content", {}) if isinstance(sync_job.get("content", {}), dict) else {}
    content["status"] = status
    content["execution_receipt"] = receipt
    connector_execution = content.get("connector_execution", {}) if isinstance(content.get("connector_execution", {}), dict) else {}
    receipt_execution = receipt.get("connector_execution", {}) if isinstance(receipt.get("connector_execution", {}), dict) else {}
    connector_execution["execution_boundary"] = str(receipt_execution.get("execution_boundary") or "sandboxed_local_file_connector")
    connector_execution["execution_performed"] = bool(receipt.get("execution_performed"))
    content["connector_execution"] = connector_execution
    content["updated_at"] = utc_now()
    sync_job["content"] = content
    metadata = sync_job.get("metadata", {}) if isinstance(sync_job.get("metadata", {}), dict) else {}
    metadata["asset_status"] = status
    metadata["connector_execution_status"] = status
    sync_job["metadata"] = metadata
    sync_job["updated_at"] = utc_now()
    errors = validate_common_fields(sync_job)
    if errors:
        raise ValueError("; ".join(errors))
    storage.write_json(sync_path, sync_job)
    return {"path": _display_path(storage.root, sync_path), "asset": storage.read_json(sync_path)}


def _allowed_roots(storage: LocalStorage, value: Any) -> list[Path]:
    roots = [resolve_path(storage.root, item).resolve() for item in value if str(item).strip()] if isinstance(value, list) else []
    return roots or [storage.root.resolve()]


def _path_within_allowed_roots(path: Path, allowed_roots: list[Path]) -> bool:
    resolved = path.resolve()
    for root in allowed_roots:
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _read_approval_request(storage: LocalStorage, approval_ref: Any) -> dict[str, Any]:
    text = str(approval_ref or "").strip()
    if not text:
        return {}
    try:
        path = resolve_path(storage.root, text)
        data = storage.read_json(path)
    except (OSError, TypeError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("type") != "approval_request":
        return {}
    return {"status": str(data.get("content", {}).get("status", "")) if isinstance(data.get("content", {}), dict) else "", "path": _display_path(storage.root, path), "asset": data}


def _approval_status(approval: dict[str, Any]) -> str:
    asset = approval.get("asset", {}) if isinstance(approval.get("asset", {}), dict) else {}
    content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
    return str(approval.get("status") or content.get("status") or "")


def _record_connector_trace(
    storage: LocalStorage,
    trace_id: str,
    status: str,
    connector_id: str,
    source_ref: str,
    project_id: str,
    workspace_path: str,
    attributes: dict[str, Any],
) -> dict[str, Any]:
    return record_trace_span(
        storage,
        trace_id=trace_id,
        span_type="source_connector",
        name=f"run:{connector_id}",
        status=status,
        attributes={"source_ref": source_ref, "connector_id": connector_id, **attributes},
        references=[source_ref],
        project_id=project_id,
        workspace_path=workspace_path,
    )


def _safe_display_path(root: Path, path: Path) -> str:
    try:
        return _display_path(root, path)
    except ValueError:
        return str(path)


def _metadata_value(asset: dict[str, Any], key: str) -> str:
    metadata = asset.get("metadata", {}) if isinstance(asset.get("metadata", {}), dict) else {}
    return str(metadata.get(key) or "")
