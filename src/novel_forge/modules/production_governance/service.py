from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.constants import DATA_DIRS
from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.audit_log import record_audit_event
from novel_forge.modules.common import resolve_path
from novel_forge.modules.os_envelope import is_production_environment
from novel_forge.modules.production_context import filter_project_safe_references
from novel_forge.modules.runtime_ledger import record_gate_result
from novel_forge.schemas import FallbackDecision, ProductionGovernanceReport, ProjectMetricSnapshot, validate_common_fields
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

GOVERNANCE_EVIDENCE_TYPES = {"publish_gate_report", "release_package", "production_governance_report", "gate_result"}
ISSUE_REQUIRED_FIELDS = ("dimension", "severity", "message", "recommendation")
GATE_REQUIRED_FIELDS = ("dimension", "status", "blocking")


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


def build_production_governance_evidence_drift_report(
    storage: LocalStorage,
    *,
    project_id: str = "",
    limit: int = 500,
    persist: bool = True,
) -> dict[str, Any]:
    """Scan production-readiness evidence for unstable gate/blocker contracts.

    The report is read-only. It does not rewrite historical gate results or
    publishing assets; operators use it to find caller seams that need repair
    before a final acceptance run.
    """

    storage.ensure_layout()
    rows = _governance_evidence_rows(storage, project_id=project_id, limit=limit)
    checked_rows = [_governance_evidence_contract_row(row) for row in rows]
    drift_rows = [row for row in checked_rows if row["drift_count"]]
    artifact_counts: dict[str, int] = {}
    drift_counts_by_type: dict[str, int] = {}
    for row in checked_rows:
        artifact_counts[row["asset_type"]] = artifact_counts.get(row["asset_type"], 0) + 1
        if row["drift_count"]:
            drift_counts_by_type[row["asset_type"]] = drift_counts_by_type.get(row["asset_type"], 0) + row["drift_count"]
    generated_at = utc_now()
    content = {
        "project_id": project_id,
        "snapshot_at": generated_at,
        "snapshot_kind": "production_governance_evidence_drift",
        "contract": "production-governance-evidence-drift-v1",
        "throughput": {
            "scanned_artifact_count": len(checked_rows),
            "drift_artifact_count": len(drift_rows),
            "limit": limit,
        },
        "quality": {
            "drift_count": sum(row["drift_count"] for row in drift_rows),
            "normalized_contract_coverage": round(1.0 - (len(drift_rows) / max(1, len(checked_rows))), 4),
            "drift_counts_by_type": drift_counts_by_type,
        },
        "task_health": {
            "failed": len(drift_rows),
            "running": 0,
            "waiting_handoff": 0,
            "dead_letters": 0,
            "blocking_drift_count": sum(1 for row in drift_rows if row["blocking"]),
        },
        "agent_health": {
            "scheduler_visible": True,
            "agent_center_gate_result_visible": bool(artifact_counts.get("gate_result", 0)),
        },
        "storage_health": {
            "scanned_dirs": list(DATA_DIRS),
            "artifact_counts": artifact_counts,
        },
        "recommendations": _governance_drift_recommendations(drift_rows),
        "rows": checked_rows,
        "drift_rows": drift_rows,
        "source_isolation": {
            "raw_source_text_included": False,
            "draft_text_included": False,
            "report_is_read_only": True,
        },
    }
    result = {
        "snapshot_kind": "production_governance_evidence_drift",
        "project_id": project_id,
        "content": content,
        "summary": {
            "scanned_artifact_count": len(checked_rows),
            "drift_artifact_count": len(drift_rows),
            "drift_count": content["quality"]["drift_count"],
            "blocking_drift_count": content["task_health"]["blocking_drift_count"],
            "artifact_counts": artifact_counts,
            "drift_counts_by_type": drift_counts_by_type,
        },
    }
    if not persist:
        return result
    asset = ProjectMetricSnapshot(
        title=f"Production governance evidence drift {project_id or 'all'}",
        source="production-governance",
        tags=["production-governance", "evidence-drift", "ops"],
        content=content,
        metadata={"project_id": project_id, "snapshot_kind": "production_governance_evidence_drift", "read_only": True},
        references=_dedupe([row["path"] for row in checked_rows[:50]]),
    )
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset)
    result["path"] = _display_path(storage.root, path)
    result["asset"] = storage.read_json(path)
    return result


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


def _governance_evidence_rows(storage: LocalStorage, *, project_id: str, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for category in DATA_DIRS:
        for path in reversed(storage.list_json(category)):
            data = _read_json_safe(storage, path)
            if data.get("type") not in GOVERNANCE_EVIDENCE_TYPES:
                continue
            row_project_id = _row_project_id(data)
            if project_id and row_project_id and row_project_id != project_id:
                continue
            rows.append({**data, "path": _display_path(storage.root, path), "project_id": row_project_id})
            if len(rows) >= max(1, int(limit or 500)):
                return rows
    return rows


def _governance_evidence_contract_row(row: dict[str, Any]) -> dict[str, Any]:
    asset_type = str(row.get("type") or "")
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    drifts: list[dict[str, Any]] = []
    if asset_type == "publish_gate_report":
        drifts.extend(_issue_contract_drifts(content.get("blocking_issues", []), container="publish_gate_report.blocking_issues"))
        drifts.extend(_gate_payload_drifts({"production_governance": content.get("production_governance", {}), "context_governance_gate": content.get("context_governance_gate", {})}, container="publish_gate_report"))
    elif asset_type == "release_package":
        evidence = content.get("release_gate_evidence", {}) if isinstance(content.get("release_gate_evidence", {}), dict) else {}
        drifts.extend(_issue_contract_drifts(content.get("known_risks", []), container="release_package.known_risks"))
        drifts.extend(_issue_contract_drifts(evidence.get("blocking_issues", []), container="release_package.release_gate_evidence.blocking_issues"))
        drifts.extend(_release_check_drifts(evidence.get("checks", [])))
        drifts.extend(_gate_payload_drifts({"context_governance_gate": content.get("context_governance_gate", {}), "production_governance": content.get("production_governance", {})}, container="release_package"))
    elif asset_type == "production_governance_report":
        gates = content.get("gate_statuses", {}) if isinstance(content.get("gate_statuses", {}), dict) else {}
        drifts.extend(_issue_contract_drifts(content.get("blocking_issues", []), container="production_governance_report.blocking_issues"))
        drifts.extend(_gate_payload_drifts(gates, container="production_governance_report.gate_statuses"))
    elif asset_type == "gate_result":
        drifts.extend(_gate_result_drifts(content))
    blocking = any(item.get("severity") in {"high", "critical"} for item in drifts)
    return {
        "asset_type": asset_type,
        "asset_id": str(row.get("id") or ""),
        "project_id": str(row.get("project_id") or ""),
        "path": str(row.get("path") or ""),
        "status": str(content.get("status") or content.get("decision") or ""),
        "drift_count": len(drifts),
        "blocking": blocking,
        "drifts": drifts,
    }


def _issue_contract_drifts(items: Any, *, container: str) -> list[dict[str, Any]]:
    if items in (None, ""):
        return []
    if not isinstance(items, list):
        return [_drift(container, "blocking_issues_not_list", "critical", "blocking issue container must be a list")]
    drifts: list[dict[str, Any]] = []
    for index, issue in enumerate(items):
        location = f"{container}[{index}]"
        if not isinstance(issue, dict):
            drifts.append(_drift(location, "blocking_issue_not_object", "critical", "blocking issue must be an object"))
            continue
        for field in ISSUE_REQUIRED_FIELDS:
            if not str(issue.get(field) or "").strip():
                drifts.append(_drift(location, f"missing_{field}", "high", f"blocking issue is missing {field}"))
    return drifts


def _gate_payload_drifts(gates: dict[str, Any], *, container: str) -> list[dict[str, Any]]:
    drifts: list[dict[str, Any]] = []
    for dimension, payload in gates.items():
        if not payload:
            continue
        location = f"{container}.{dimension}"
        if not isinstance(payload, dict):
            drifts.append(_drift(location, "gate_payload_not_object", "critical", "gate payload must be an object"))
            continue
        for field in GATE_REQUIRED_FIELDS:
            if field == "blocking":
                if not isinstance(payload.get(field), bool):
                    drifts.append(_drift(location, "missing_blocking", "high", "gate payload must include boolean blocking"))
            elif not str(payload.get(field) or "").strip():
                drifts.append(_drift(location, f"missing_{field}", "high", f"gate payload is missing {field}"))
        if str(payload.get("status") or "") == "passed" and "path" in payload and payload.get("path") is None:
            drifts.append(_drift(location, "invalid_path", "medium", "gate path must be a string when present"))
    return drifts


def _release_check_drifts(items: Any) -> list[dict[str, Any]]:
    if not items:
        return []
    if not isinstance(items, list):
        return [_drift("release_package.release_gate_evidence.checks", "checks_not_list", "critical", "release gate checks must be a list")]
    drifts: list[dict[str, Any]] = []
    required = ("dimension", "status", "expected_status", "path_field", "path", "blocking")
    for index, item in enumerate(items):
        location = f"release_package.release_gate_evidence.checks[{index}]"
        if not isinstance(item, dict):
            drifts.append(_drift(location, "check_not_object", "critical", "release gate check must be an object"))
            continue
        for field in required:
            if field == "blocking":
                if not isinstance(item.get(field), bool):
                    drifts.append(_drift(location, "missing_blocking", "high", "release gate check must include boolean blocking"))
            elif field not in item:
                drifts.append(_drift(location, f"missing_{field}", "high", f"release gate check is missing {field}"))
    return drifts


def _gate_result_drifts(content: dict[str, Any]) -> list[dict[str, Any]]:
    drifts: list[dict[str, Any]] = []
    for field in ("gate_id", "gate_kind", "status", "target_paths", "created_at"):
        if field == "target_paths":
            if not isinstance(content.get(field), list):
                drifts.append(_drift("gate_result", "missing_target_paths", "high", "gate_result target_paths must be a list"))
        elif not str(content.get(field) or "").strip():
            drifts.append(_drift("gate_result", f"missing_{field}", "high", f"gate_result is missing {field}"))
    if content.get("blocking") is not None and not isinstance(content.get("blocking"), bool):
        drifts.append(_drift("gate_result", "invalid_blocking", "medium", "gate_result blocking must be boolean when present"))
    return drifts


def _drift(location: str, code: str, severity: str, message: str) -> dict[str, Any]:
    return {
        "dimension": "production_governance_evidence_contract",
        "location": location,
        "code": code,
        "severity": severity,
        "message": message,
        "recommendation": "normalize production governance evidence before final acceptance",
    }


def _governance_drift_recommendations(drift_rows: list[dict[str, Any]]) -> list[str]:
    if not drift_rows:
        return ["Production governance evidence contracts are normalized for scanned assets"]
    return [
        "normalize blocker fields to dimension/severity/message/recommendation",
        "normalize gate fields to dimension/status/blocking/path where applicable",
        "rerun affected publishing or scheduler readiness surfaces after fixing caller seams",
    ]


def _row_project_id(data: dict[str, Any]) -> str:
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    return str(metadata.get("project_id") or content.get("project_id") or "")


def _read_json_safe(storage: LocalStorage, path: Path) -> dict[str, Any]:
    try:
        data = storage.read_json(path)
    except (FileNotFoundError, OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


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
