from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.asset_scan import iter_json_objects
from novel_forge.core.constants import DATA_DIRS
from novel_forge.core.ids import utc_now
from novel_forge.modules.production_context import filter_project_safe_references
from novel_forge.schemas import ProjectMetricSnapshot, validate_common_fields
from novel_forge.storage.local import LocalStorage


SOURCE_GUARDED_APPLY_SNAPSHOT_KIND = "source_guarded_apply_readiness"


def build_source_guarded_apply_readiness_report(
    storage: LocalStorage,
    *,
    project_id: str = "",
    limit: int = 1000,
    persist: bool = True,
) -> dict[str, Any]:
    """Build a read-only readiness report for source repair/invalidation apply evidence."""
    storage.ensure_layout()
    scope_project_id = project_id or "system:workspace"
    scope_kind = "project" if project_id else "workspace"
    rows = _source_rows(storage, project_id=project_id, limit=max(1, int(limit or 1000)))
    repair_plans = [_repair_plan_row(path, row) for path, row in rows if _is_source_guarded_repair_plan(row)]
    approvals = [_approval_row(path, row) for path, row in rows if row.get("type") == "approval_request" and _is_source_approval(row)]
    stale_assets = [_stale_asset_row(path, row) for path, row in rows if _is_stale_source_derived_asset(row)]
    agent_tasks = [_agent_task_row(path, row) for path, row in rows if row.get("type") == "agent_task" and _is_source_guarded_agent_task(row)]
    rollback_plans = [_rollback_plan_row(path, row) for path, row in rows if row.get("type") == "rollback_plan" and _is_source_guarded_rollback_plan(row)]
    rollback_results = [_rollback_result_row(path, row) for path, row in rows if row.get("type") == "rollback_result" and _is_source_guarded_rollback_result(row)]

    pending_review_plans = [row for row in repair_plans if row["asset_status"] in {"needs_review", "ready_for_confirm", ""}]
    applied_plans = [row for row in repair_plans if row["asset_status"] in {"applied", "applied_with_errors"} or row["apply_result_status"] in {"applied", "applied_with_errors"}]
    pending_approvals = [row for row in approvals if row["status"] == "pending"]
    blocking_approvals = [row for row in pending_approvals if row["blocking"]]
    dispatch_ready_tasks = [row for row in agent_tasks if row["status"] == "approved_pending_dispatch"]
    review_tasks = [row for row in agent_tasks if row["status"] in {"needs_review", "planned"}]
    evidence_paths = _dedupe(
        [
            *[row["path"] for row in repair_plans],
            *[row["path"] for row in approvals],
            *[row["path"] for row in stale_assets],
            *[row["path"] for row in agent_tasks],
            *[row["path"] for row in rollback_plans],
            *[row["path"] for row in rollback_results],
        ]
    )
    if not repair_plans and not stale_assets and not agent_tasks:
        status = "missing"
    elif blocking_approvals or pending_review_plans or stale_assets or review_tasks:
        status = "review_required"
    else:
        status = "ready"
    operator_action = _operator_action(status, pending_review_count=len(pending_review_plans), stale_count=len(stale_assets), dispatch_ready_count=len(dispatch_ready_tasks))
    content = {
        "snapshot_kind": SOURCE_GUARDED_APPLY_SNAPSHOT_KIND,
        "contract": "source-guarded-apply-readiness-v1",
        "status": status,
        "project_id": scope_project_id,
        "snapshot_at": utc_now(),
        "throughput": {
            "repair_plan_count": len(repair_plans),
            "approval_request_count": len(approvals),
            "stale_asset_count": len(stale_assets),
            "agent_task_count": len(agent_tasks),
        },
        "quality": {
            "readiness_status": status,
            "pending_review_plan_count": len(pending_review_plans),
            "applied_plan_count": len(applied_plans),
            "blocking_approval_count": len(blocking_approvals),
            "stale_pending_regeneration_count": len(stale_assets),
            "silent_mutation_allowed": False,
            "connector_execution_performed": False,
            "dispatch_applied": False,
        },
        "task_health": {
            "review_task_count": len(review_tasks),
            "dispatch_ready_task_count": len(dispatch_ready_tasks),
            "rollback_plan_count": len(rollback_plans),
            "rollback_result_count": len(rollback_results),
            "operator_action": operator_action,
        },
        "agent_health": {
            "planned_agent_operations": sorted({row["operation"] for row in agent_tasks if row["operation"]}),
            "dispatch_boundary": "readiness report does not enqueue, dispatch, or recover AgentTasks",
        },
        "storage_health": {
            "evidence_path_count": len(evidence_paths),
            "asset_type": "project_metric_snapshot",
            "source_asset_types": sorted({row.get("asset_type", "") for row in [*repair_plans, *approvals, *stale_assets, *agent_tasks, *rollback_plans, *rollback_results] if row.get("asset_type")}),
        },
        "recommendations": [operator_action],
        "summary": {
            "repair_plan_count": len(repair_plans),
            "pending_review_plan_count": len(pending_review_plans),
            "applied_plan_count": len(applied_plans),
            "approval_request_count": len(approvals),
            "pending_approval_count": len(pending_approvals),
            "blocking_approval_count": len(blocking_approvals),
            "stale_pending_regeneration_count": len(stale_assets),
            "review_task_count": len(review_tasks),
            "dispatch_ready_task_count": len(dispatch_ready_tasks),
            "rollback_plan_count": len(rollback_plans),
            "rollback_result_count": len(rollback_results),
            "audit_required": True,
        },
        "repair_plans": repair_plans[:40],
        "approval_requests": approvals[:40],
        "stale_assets": stale_assets[:40],
        "agent_tasks": agent_tasks[:40],
        "rollback_plans": rollback_plans[:20],
        "rollback_results": rollback_results[:20],
        "evidence_paths": evidence_paths,
        "operator_action": operator_action,
        "mutation_policy": "read-only: never executes connectors, marks assets stale, dispatches regeneration, or applies rollback",
    }
    asset = ProjectMetricSnapshot(
        title=f"Source guarded apply readiness {project_id or 'workspace'}",
        tags=["source-governance", "guarded-apply-readiness", status],
        content=content,
        metadata={
            "project_id": scope_project_id,
            "scope_kind": scope_kind,
            "snapshot_kind": SOURCE_GUARDED_APPLY_SNAPSHOT_KIND,
            "asset_status": status,
            "use_in_generation_rag": False,
        },
        references=filter_project_safe_references(storage, scope_project_id, evidence_paths),
    )
    data = asset.to_dict()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    path = ""
    if persist:
        path = _display_path(storage.root, storage.write_asset_auto(asset))
        data = storage.read_json(storage.root / path)
    return {"status": status, "path": path, "asset": data, "summary": content["summary"]}


def _source_rows(storage: LocalStorage, *, project_id: str, limit: int) -> list[tuple[Path, dict[str, Any]]]:
    rows: list[tuple[Path, dict[str, Any]]] = []
    for category in DATA_DIRS:
        for path, data in iter_json_objects(storage, category, reverse=True, context="source guarded apply readiness"):
            if project_id and _project_id(data) not in {"", project_id}:
                continue
            rows.append((path, data))
            if len(rows) >= limit:
                return rows
    return rows


def _is_source_guarded_repair_plan(row: dict[str, Any]) -> bool:
    if row.get("type") != "change_impact_report":
        return False
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    tags = {str(tag) for tag in row.get("tags", []) if str(tag)}
    return "source-governance" in tags or str(content.get("source_diff", "")).strip() or str(content.get("source_refresh_report_ref") or "")


def _repair_plan_row(path: Path, row: dict[str, Any]) -> dict[str, Any]:
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    metadata = row.get("metadata", {}) if isinstance(row.get("metadata", {}), dict) else {}
    repair_plan = content.get("repair_plan", {}) if isinstance(content.get("repair_plan", {}), dict) else {}
    apply_result = content.get("apply_result", {}) if isinstance(content.get("apply_result", {}), dict) else {}
    return {
        "asset_type": "change_impact_report",
        "id": str(row.get("id") or ""),
        "path": _display_path_from_path(path),
        "asset_status": str(metadata.get("asset_status") or content.get("status") or ""),
        "recommendation": str(content.get("recommendation") or ""),
        "source_ref": str(content.get("source_ref") or metadata.get("source_ref") or ""),
        "impacted_count": len(content.get("impacted_assets", [])) if isinstance(content.get("impacted_assets", []), list) else 0,
        "agent_task_count": len(content.get("agent_task_paths", [])) if isinstance(content.get("agent_task_paths", []), list) else 0,
        "operator_approval_required": bool(content.get("repair_contract", {}).get("operator_approval_required")) if isinstance(content.get("repair_contract", {}), dict) else bool(repair_plan.get("operator_review_required")),
        "silent_mutation_allowed": bool(content.get("repair_contract", {}).get("silent_mutation_allowed")) if isinstance(content.get("repair_contract", {}), dict) else False,
        "apply_result_status": str(apply_result.get("status") or ""),
        "approval_request_path": str(apply_result.get("approval_request_path") or ""),
        "rollback_plan_path": str(apply_result.get("rollback_plan_path") or ""),
    }


def _is_source_approval(row: dict[str, Any]) -> bool:
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    return str(content.get("scope") or "") in {"source", "context"} and "source" in str(content.get("action") or "")


def _approval_row(path: Path, row: dict[str, Any]) -> dict[str, Any]:
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    target = content.get("target", {}) if isinstance(content.get("target", {}), dict) else {}
    return {
        "asset_type": "approval_request",
        "id": str(row.get("id") or content.get("request_id") or ""),
        "request_id": str(content.get("request_id") or ""),
        "path": _display_path_from_path(path),
        "scope": str(content.get("scope") or ""),
        "action": str(content.get("action") or ""),
        "status": str(content.get("status") or ""),
        "blocking": bool(content.get("blocking")),
        "target_type": str(target.get("target_type") or ""),
        "target_id": str(target.get("target_id") or ""),
    }


def _is_stale_source_derived_asset(row: dict[str, Any]) -> bool:
    metadata = row.get("metadata", {}) if isinstance(row.get("metadata", {}), dict) else {}
    status = str(metadata.get("asset_status") or "")
    repair_status = str(metadata.get("source_diff_repair_status") or "")
    return status in {"stale", "quarantined"} or repair_status.startswith("stale")


def _stale_asset_row(path: Path, row: dict[str, Any]) -> dict[str, Any]:
    metadata = row.get("metadata", {}) if isinstance(row.get("metadata", {}), dict) else {}
    return {
        "asset_type": str(row.get("type") or ""),
        "id": str(row.get("id") or ""),
        "path": _display_path_from_path(path),
        "asset_status": str(metadata.get("asset_status") or ""),
        "source_diff_repair_status": str(metadata.get("source_diff_repair_status") or ""),
        "approval_request_path": str(metadata.get("approval_request_path") or metadata.get("governance_approval_request_path") or ""),
        "use_in_generation_rag": bool(metadata.get("use_in_generation_rag", False)),
    }


def _is_source_guarded_agent_task(row: dict[str, Any]) -> bool:
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    operation = str(content.get("operation") or "")
    return operation.startswith("plan-source-derived") or operation in {"review-source-diff-repair-plan", "review-source-stale-quarantine-sweep"}


def _agent_task_row(path: Path, row: dict[str, Any]) -> dict[str, Any]:
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    evidence = content.get("evidence", {}) if isinstance(content.get("evidence", {}), dict) else {}
    return {
        "asset_type": "agent_task",
        "id": str(row.get("id") or content.get("task_id") or ""),
        "path": _display_path_from_path(path),
        "operation": str(content.get("operation") or ""),
        "status": str(content.get("status") or ""),
        "approval_request_path": str(evidence.get("approval_request_path") or content.get("approval_request_path") or ""),
        "source_diff_repair_report_path": str(evidence.get("source_diff_repair_report_path") or ""),
        "dispatch_allowed": bool(evidence.get("dispatch_allowed", False)),
    }


def _is_source_guarded_rollback_plan(row: dict[str, Any]) -> bool:
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    return "source_diff" in str(content.get("strategy") or "") or bool(content.get("source_diff_repair_report_path"))


def _rollback_plan_row(path: Path, row: dict[str, Any]) -> dict[str, Any]:
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    return {
        "asset_type": "rollback_plan",
        "id": str(row.get("id") or ""),
        "path": _display_path_from_path(path),
        "strategy": str(content.get("strategy") or ""),
        "approval_request_path": str(content.get("approval_request_path") or ""),
        "source_diff_repair_report_path": str(content.get("source_diff_repair_report_path") or ""),
    }


def _is_source_guarded_rollback_result(row: dict[str, Any]) -> bool:
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    return bool(content.get("rollback_plan_path")) and "source_diff" in str(content.get("rollback_type") or content.get("strategy") or content.get("rollback_plan_path") or "")


def _rollback_result_row(path: Path, row: dict[str, Any]) -> dict[str, Any]:
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    return {
        "asset_type": "rollback_result",
        "id": str(row.get("id") or ""),
        "path": _display_path_from_path(path),
        "status": str(content.get("status") or ""),
        "rollback_plan_path": str(content.get("rollback_plan_path") or ""),
    }


def _operator_action(status: str, *, pending_review_count: int, stale_count: int, dispatch_ready_count: int) -> str:
    if status == "missing":
        return "run source refresh/diff/stale sweep before guarded source apply promotion"
    if stale_count:
        return "review stale source-derived assets and dispatch approved regeneration through Agent Scheduler"
    if dispatch_ready_count:
        return "operator may dispatch approved source-derived regeneration tasks after reviewing evidence"
    if pending_review_count:
        return "review source diff repair plans and resolve ApprovalRequest evidence before confirm_apply"
    return "source guarded apply evidence is ready for the next governed step"


def _project_id(row: dict[str, Any]) -> str:
    metadata = row.get("metadata", {}) if isinstance(row.get("metadata", {}), dict) else {}
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    return str(metadata.get("project_id") or content.get("project_id") or "")


def _display_path(root: Path, path: str | Path) -> str:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        return str(candidate.relative_to(root))
    except ValueError:
        return str(candidate)


def _display_path_from_path(path: Path) -> str:
    try:
        return str(path.relative_to(path.parents[2]))
    except (IndexError, ValueError):
        return str(path)


def _dedupe(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result
