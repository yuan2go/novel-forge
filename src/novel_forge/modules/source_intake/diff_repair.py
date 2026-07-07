from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.constants import DATA_DIRS
from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.modules.source_intake.service import _asset_ref, _dedupe, _display_path, _metadata_value, _resolve_governance_asset, _short_ref_key, _strings
from novel_forge.schemas import ChangeImpactReport, RollbackPlan, RollbackResult, validate_common_fields
from novel_forge.storage.local import LocalStorage


SOURCE_DIFF_BLOCKING_TYPES = {"publish_gate_report", "release_package"}
SOURCE_DIFF_HIGH_IMPACT_TYPES = {
    "context_bundle",
    "context_build_plan",
    "draft_chapter",
    "draft_version",
    "review_report",
    "revision_task",
    "revision_plan",
    "quality_score_report",
    "publish_gate_report",
    "release_package",
}
SOURCE_DIFF_REVIEW_TYPES = {
    "knowledge_card",
    "knowledge_pack",
    "knowledge_usage_event",
    "material_card",
    "material_usage_event",
    "writing_template",
    "review_rule",
    "analysis_conversion_report",
    "chapter_plan",
    "chapter_plan_version",
}
SOURCE_DIFF_IGNORED_TYPES = {
    "source_policy",
    "license_check_result",
    "source_risk_report",
    "source_snapshot",
    "source_sync_job",
    "source_refresh_report",
    "approval_request",
}


def plan_source_diff_repair(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    storage.ensure_layout()
    old_resolved = _resolve_asset_with_path(storage, payload.get("old_snapshot_path") or payload.get("old_snapshot_ref"), "source_snapshot")
    new_resolved = _resolve_asset_with_path(storage, payload.get("new_snapshot_path") or payload.get("new_snapshot_ref"), "source_snapshot")
    if not old_resolved or not new_resolved:
        raise ValueError("old_snapshot_path and new_snapshot_path must resolve to source_snapshot assets")
    old_path, old_snapshot = old_resolved
    new_path, new_snapshot = new_resolved
    old_content = old_snapshot.get("content", {}) if isinstance(old_snapshot.get("content", {}), dict) else {}
    new_content = new_snapshot.get("content", {}) if isinstance(new_snapshot.get("content", {}), dict) else {}
    source_ref = str(payload.get("source_ref") or new_content.get("source_ref") or old_content.get("source_ref") or old_snapshot.get("source") or "")
    project_id = str(payload.get("project_id") or _metadata_value(new_snapshot, "project_id") or _metadata_value(old_snapshot, "project_id") or "")
    workspace_path = str(payload.get("workspace_path") or _metadata_value(new_snapshot, "workspace_path") or _metadata_value(old_snapshot, "workspace_path") or "")
    refresh_report = _resolve_governance_asset(storage, payload.get("source_refresh_report_path") or payload.get("refresh_report_ref"), "source_refresh_report")
    diff = _source_snapshot_diff(old_snapshot, new_snapshot)
    lineage_keys = _source_diff_lineage_keys(storage.root, old_path, old_snapshot, new_path, new_snapshot)
    impacted = _source_diff_downstream_impacts(storage, lineage_keys, old_path=old_path, new_path=new_path, project_id=project_id, diff=diff)
    impact_edges = [
        {
            "source": str(match),
            "target": item["path"],
            "relation": "source_snapshot_reference",
            "requires_review": True,
        }
        for item in impacted
        for match in item.get("matched_refs", [])
    ]
    summary = _source_diff_severity_summary(impacted)
    recommendation = _source_diff_recommendation(summary, diff)
    report_id = str(payload.get("report_id") or make_id("change_impact_report", f"source-diff:{_short_ref_key(_asset_ref(old_snapshot))}:{_short_ref_key(_asset_ref(new_snapshot))}:{utc_now()}"))
    old_ref = _display_path(storage.root, old_path)
    new_ref = _display_path(storage.root, new_path)
    repair_plan = _source_diff_repair_plan(impacted, diff)
    asset = ChangeImpactReport(
        id=report_id,
        title=str(payload.get("title") or f"Source diff repair plan: {source_ref or old_ref}"),
        source=_asset_ref(old_snapshot) or source_ref,
        tags=_dedupe(["source-governance", "source-diff", recommendation, diff["status"], "needs-review"]),
        content={
            "target_asset_id": _asset_ref(old_snapshot),
            "target_asset_type": "source_snapshot",
            "target_path": old_ref,
            "project_id": project_id,
            "source_ref": source_ref,
            "old_snapshot_path": old_ref,
            "new_snapshot_path": new_ref,
            "source_refresh_report_ref": _asset_ref(refresh_report),
            "source_diff": diff,
            "impacted_assets": impacted,
            "impact_edges": impact_edges,
            "severity_summary": summary,
            "recommendation": recommendation,
            "repair_plan": repair_plan,
            "review_issue_paths": [],
            "agent_task_paths": [],
            "repair_contract": {
                "raw_source_text_included": False,
                "silent_mutation_allowed": False,
                "auto_invalidation_applied": False,
                "auto_regeneration_dispatched": False,
                "operator_approval_required": bool(impacted or diff["status"] == "changed"),
                "allowed_actions": ["review_diff", "approve_invalidation", "approve_regeneration_task"],
                "forbidden_actions": ["rewrite_knowledge_card_silently", "rewrite_material_card_silently", "mutate_context_bundle_silently"],
            },
            "generated_at": utc_now(),
        },
        metadata={
            "project_id": project_id,
            "workspace_path": workspace_path,
            "asset_status": "needs_review" if impacted or diff["status"] == "changed" else "current",
            "target_asset_path": old_ref,
            "source_ref": source_ref,
            "use_in_generation_rag": False,
            "raw_source_text_included": False,
        },
        references=_dedupe([old_ref, new_ref, _asset_ref(old_snapshot), _asset_ref(new_snapshot), _asset_ref(refresh_report), *[item["path"] for item in impacted], *[item["id"] for item in impacted]]),
    )
    report = _write_change_impact_report(storage, asset)
    review_issue = _write_source_diff_review_issue(storage, report, old_snapshot, new_snapshot, impacted, diff, project_id=project_id, workspace_path=workspace_path)
    agent_tasks = _write_source_diff_agent_tasks(storage, report, review_issue, impacted, project_id=project_id, workspace_path=workspace_path)
    updated = _update_source_diff_report_links(storage, report["path"], review_issue, agent_tasks)
    return {
        "status": "needs_review" if review_issue else "current",
        "path": report["path"],
        "asset": updated,
        "source_diff": diff,
        "impacted_assets": impacted,
        "review_issue": review_issue,
        "agent_tasks": agent_tasks,
        "mutation_applied": False,
        "dispatch_applied": False,
    }


def apply_source_diff_repair(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    storage.ensure_layout()
    report_path = resolve_path(storage.root, payload.get("repair_plan_path") or payload.get("change_impact_report_path") or payload.get("report_path"))
    report = storage.read_json(report_path)
    if not isinstance(report, dict) or report.get("type") != "change_impact_report":
        raise ValueError("repair_plan_path must point to a change_impact_report")
    content = report.get("content", {}) if isinstance(report.get("content", {}), dict) else {}
    project_id = str(payload.get("project_id") or content.get("project_id") or _asset_project_id(report) or "")
    workspace_path = str(payload.get("workspace_path") or _metadata_value(report, "workspace_path") or "")
    approval = _source_diff_apply_approval(storage, payload, report_path, report, project_id=project_id, workspace_path=workspace_path)
    approval_status = _approval_status(approval)
    if approval_status != "approved":
        return {
            "status": "approval_required",
            "repair_plan_path": _display_path(storage.root, report_path),
            "approval_request": approval,
            "updated_assets": [],
            "rollback_plan": {},
            "mutation_applied": False,
            "dispatch_applied": False,
            "reason": "source diff repair apply requires approved ApprovalRequest",
        }
    if not bool(payload.get("confirm_apply")):
        return {
            "status": "ready_for_confirm",
            "repair_plan_path": _display_path(storage.root, report_path),
            "approval_request": approval,
            "updated_assets": [],
            "rollback_plan": {},
            "mutation_applied": False,
            "dispatch_applied": False,
            "reason": "approved source diff repair requires confirm_apply=true before stale marking",
        }
    impacted = content.get("impacted_assets", []) if isinstance(content.get("impacted_assets", []), list) else []
    updated_assets, rollback_actions, errors = _apply_source_diff_stale_marks(
        storage,
        impacted,
        report_path=_display_path(storage.root, report_path),
        approval_path=str(approval.get("path") or payload.get("approval_request_path") or payload.get("approval_request_ref") or ""),
        actor=str(payload.get("actor") or "operator"),
    )
    task_updates, task_rollback_actions = _mark_source_diff_agent_tasks_dispatch_ready(
        storage,
        content.get("agent_task_paths", []) if isinstance(content.get("agent_task_paths", []), list) else [],
        approval_path=str(approval.get("path") or payload.get("approval_request_path") or payload.get("approval_request_ref") or ""),
    )
    rollback_plan = _write_source_diff_rollback_plan(
        storage,
        report,
        report_path=_display_path(storage.root, report_path),
        approval_path=str(approval.get("path") or payload.get("approval_request_path") or payload.get("approval_request_ref") or ""),
        actions=[*rollback_actions, *task_rollback_actions],
        project_id=project_id,
        workspace_path=workspace_path,
    )
    content["apply_result"] = {
        "status": "applied_with_errors" if errors else "applied",
        "approval_request_path": str(approval.get("path") or ""),
        "updated_assets": updated_assets,
        "task_updates": task_updates,
        "rollback_plan_path": rollback_plan.get("path", ""),
        "errors": errors,
        "mutation_scope": "metadata_stale_marking_only",
        "raw_source_text_included": False,
        "dispatch_applied": False,
        "applied_at": utc_now(),
    }
    report["content"] = content
    metadata = report.get("metadata", {}) if isinstance(report.get("metadata", {}), dict) else {}
    metadata["asset_status"] = "applied_with_errors" if errors else "applied"
    metadata["source_diff_apply_status"] = metadata["asset_status"]
    report["metadata"] = metadata
    report["updated_at"] = utc_now()
    validation_errors = validate_common_fields(report)
    if validation_errors:
        raise ValueError("; ".join(validation_errors))
    storage.write_json(report_path, report)
    return {
        "status": "applied_with_errors" if errors else "applied",
        "repair_plan_path": _display_path(storage.root, report_path),
        "approval_request": approval,
        "updated_assets": updated_assets,
        "task_updates": task_updates,
        "rollback_plan": rollback_plan,
        "errors": errors,
        "mutation_applied": bool(updated_assets),
        "dispatch_applied": False,
    }


def rollback_source_diff_repair(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    storage.ensure_layout()
    plan_path = resolve_path(storage.root, payload.get("rollback_plan_path") or payload.get("plan_path"))
    plan = storage.read_json(plan_path)
    if not isinstance(plan, dict) or plan.get("type") != "rollback_plan":
        raise ValueError("rollback_plan_path must point to a rollback_plan asset")
    content = plan.get("content", {}) if isinstance(plan.get("content", {}), dict) else {}
    project_id = str(payload.get("project_id") or _metadata_value(plan, "project_id") or "")
    workspace_path = str(payload.get("workspace_path") or _metadata_value(plan, "workspace_path") or "")
    approval = _source_diff_rollback_approval(storage, payload, plan_path, plan, project_id=project_id, workspace_path=workspace_path)
    approval_status = _approval_status(approval)
    if approval_status != "approved":
        return {
            "status": "approval_required",
            "rollback_plan_path": _display_path(storage.root, plan_path),
            "approval_request": approval,
            "applied_actions": [],
            "rollback_result": {},
            "rollback_applied": False,
            "reason": "source diff repair rollback requires approved ApprovalRequest",
        }
    if not bool(payload.get("confirm_rollback")):
        return {
            "status": "ready_for_confirm",
            "rollback_plan_path": _display_path(storage.root, plan_path),
            "approval_request": approval,
            "applied_actions": [],
            "rollback_result": {},
            "rollback_applied": False,
            "reason": "approved rollback requires confirm_rollback=true",
        }
    actions = content.get("actions", []) if isinstance(content.get("actions", []), list) else []
    applied_actions, errors = _apply_source_diff_rollback_actions(storage, actions, actor=str(payload.get("actor") or "operator"))
    status = "failed" if errors else "applied"
    result = _write_source_diff_rollback_result(
        storage,
        plan,
        plan_path=_display_path(storage.root, plan_path),
        status=status,
        applied_actions=applied_actions,
        errors=errors,
        approval_path=str(approval.get("path") or payload.get("approval_request_path") or payload.get("approval_request_ref") or ""),
        project_id=project_id,
        workspace_path=workspace_path,
    )
    content["rollback_status"] = status
    content["rollback_result_path"] = result.get("path", "")
    content["rolled_back_at"] = utc_now()
    plan["content"] = content
    metadata = plan.get("metadata", {}) if isinstance(plan.get("metadata", {}), dict) else {}
    metadata["asset_status"] = status
    plan["metadata"] = metadata
    plan["updated_at"] = utc_now()
    validation_errors = validate_common_fields(plan)
    if validation_errors:
        raise ValueError("; ".join(validation_errors))
    storage.write_json(plan_path, plan)
    return {
        "status": status,
        "rollback_plan_path": _display_path(storage.root, plan_path),
        "approval_request": approval,
        "applied_actions": applied_actions,
        "errors": errors,
        "rollback_result": result,
        "rollback_applied": bool(applied_actions) and not errors,
    }


def _write_change_impact_report(storage: LocalStorage, asset: ChangeImpactReport) -> dict[str, Any]:
    data = asset.to_dict()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path)}


def _source_diff_apply_approval(
    storage: LocalStorage,
    payload: dict[str, Any],
    report_path: Path,
    report: dict[str, Any],
    *,
    project_id: str,
    workspace_path: str,
) -> dict[str, Any]:
    approval_ref = str(payload.get("approval_request_path") or payload.get("approval_request_ref") or "").strip()
    if approval_ref:
        approval = _read_approval_request(storage, approval_ref)
        if approval:
            return approval
    from novel_forge.modules.permission_center import create_approval_request

    content = report.get("content", {}) if isinstance(report.get("content", {}), dict) else {}
    impacted = content.get("impacted_assets", []) if isinstance(content.get("impacted_assets", []), list) else []
    risk_level = "critical" if any(str(item.get("severity") or "") == "blocking" for item in impacted) else "high" if impacted else "medium"
    return create_approval_request(
        storage,
        {
            "project_id": project_id,
            "workspace_path": workspace_path,
            "scope": "source",
            "action": "approve_source_diff_repair_apply",
            "environment": str(payload.get("environment") or "local"),
            "risk_level": risk_level,
            "blocking": True,
            "target_type": "change_impact_report",
            "target_id": str(report.get("id") or ""),
            "target_path": _display_path(storage.root, report_path),
            "target_refs": [str(item.get("path") or "") for item in impacted if isinstance(item, dict)],
            "evidence_refs": _dedupe([
                _display_path(storage.root, report_path),
                *[str(path) for path in content.get("review_issue_paths", []) if str(path).strip()],
                *_strings(payload.get("evidence_refs")),
            ]),
            "reason": "Apply source diff repair stale marking for source-derived downstream assets",
            "required_before": ["source_diff_stale_marking", "source_derived_regeneration_task_dispatch"],
            "rollback_plan": {
                "available": True,
                "strategy": "restore_previous_asset_metadata_from_rollback_plan",
                "requires_operator_review": True,
            },
        },
    )


def _read_approval_request(storage: LocalStorage, approval_ref: str) -> dict[str, Any]:
    try:
        path = resolve_path(storage.root, approval_ref)
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


def _apply_source_diff_stale_marks(
    storage: LocalStorage,
    impacted: list[dict[str, Any]],
    *,
    report_path: str,
    approval_path: str,
    actor: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    updated: list[dict[str, Any]] = []
    rollback_actions: list[dict[str, Any]] = []
    errors: list[str] = []
    for item in impacted:
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity") or "")
        if severity not in {"blocking", "high", "medium", "low"}:
            continue
        path_ref = str(item.get("path") or "")
        if not path_ref:
            continue
        try:
            path = resolve_path(storage.root, path_ref)
            data = storage.read_json(path)
            if not isinstance(data, dict):
                raise ValueError("impacted asset is not a JSON object")
            before_metadata = dict(data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {})
            metadata = dict(before_metadata)
            metadata.update(
                {
                    "asset_status": "stale",
                    "source_diff_repair_status": "stale_pending_regeneration",
                    "invalidated_by_source_diff_report": report_path,
                    "invalidated_by_approval_request": approval_path,
                    "invalidated_severity": severity,
                    "invalidated_reason": "approved source snapshot diff repair",
                    "invalidated_at": utc_now(),
                    "invalidated_by": actor,
                    "use_in_generation_rag": False,
                }
            )
            data["metadata"] = metadata
            data["updated_at"] = utc_now()
            validation_errors = validate_common_fields(data)
            if validation_errors:
                raise ValueError("; ".join(validation_errors))
            storage.write_json(path, data)
            updated.append({"path": path_ref, "asset_id": str(data.get("id") or ""), "severity": severity, "status": "stale"})
            rollback_actions.append(
                {
                    "action": "restore_asset_metadata",
                    "target_path": path_ref,
                    "target_asset_id": str(data.get("id") or ""),
                    "before_metadata": before_metadata,
                    "applied_metadata": metadata,
                }
            )
        except (OSError, TypeError, ValueError) as exc:
            errors.append(f"{path_ref}: {exc}")
    return updated, rollback_actions, errors


def _source_diff_rollback_approval(
    storage: LocalStorage,
    payload: dict[str, Any],
    plan_path: Path,
    plan: dict[str, Any],
    *,
    project_id: str,
    workspace_path: str,
) -> dict[str, Any]:
    approval_ref = str(payload.get("approval_request_path") or payload.get("approval_request_ref") or "").strip()
    if approval_ref:
        approval = _read_approval_request(storage, approval_ref)
        if approval:
            return approval
    from novel_forge.modules.permission_center import create_approval_request

    content = plan.get("content", {}) if isinstance(plan.get("content", {}), dict) else {}
    target_refs = [str(action.get("target_path") or "") for action in content.get("actions", []) if isinstance(action, dict)]
    return create_approval_request(
        storage,
        {
            "project_id": project_id,
            "workspace_path": workspace_path,
            "scope": "source",
            "action": "approve_source_diff_repair_rollback",
            "environment": str(payload.get("environment") or "local"),
            "risk_level": "high" if target_refs else "medium",
            "blocking": True,
            "target_type": "rollback_plan",
            "target_id": f"source-diff-rollback-{_short_ref_key(str(plan.get('id') or ''))}",
            "target_path": _display_path(storage.root, plan_path),
            "target_refs": target_refs,
            "evidence_refs": _dedupe([_display_path(storage.root, plan_path), str(content.get("source_diff_repair_report_path") or ""), *_strings(payload.get("evidence_refs"))]),
            "reason": "Rollback source diff repair stale marking and dispatch-ready task state",
            "required_before": ["source_diff_repair_rollback"],
            "rollback_plan": {
                "available": False,
                "strategy": "manual_reapply_source_diff_repair_if_rollback_was_incorrect",
                "requires_operator_review": True,
            },
        },
    )


def _apply_source_diff_rollback_actions(storage: LocalStorage, actions: list[dict[str, Any]], *, actor: str) -> tuple[list[dict[str, Any]], list[str]]:
    applied: list[dict[str, Any]] = []
    errors: list[str] = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        action_type = str(action.get("action") or "")
        path_ref = str(action.get("target_path") or "")
        if not path_ref:
            continue
        try:
            path = resolve_path(storage.root, path_ref)
            data = storage.read_json(path)
            if not isinstance(data, dict):
                raise ValueError("rollback target is not a JSON object")
            if action_type == "restore_asset_metadata":
                data["metadata"] = dict(action.get("before_metadata", {}) if isinstance(action.get("before_metadata", {}), dict) else {})
            elif action_type == "restore_agent_task_state":
                content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
                before_content = action.get("before_content", {}) if isinstance(action.get("before_content", {}), dict) else {}
                content["status"] = str(before_content.get("status") or content.get("status") or "needs_review")
                content["evidence"] = before_content.get("evidence", {}) if isinstance(before_content.get("evidence", {}), dict) else {}
                content["updated_at"] = utc_now()
                data["content"] = content
                data["metadata"] = dict(action.get("before_metadata", {}) if isinstance(action.get("before_metadata", {}), dict) else {})
            else:
                raise ValueError(f"unsupported rollback action: {action_type}")
            metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
            metadata["source_diff_rollback_at"] = utc_now()
            metadata["source_diff_rollback_actor"] = actor
            data["metadata"] = metadata
            data["updated_at"] = utc_now()
            validation_errors = validate_common_fields(data)
            if validation_errors:
                raise ValueError("; ".join(validation_errors))
            storage.write_json(path, data)
            applied.append({"action": action_type, "target_path": path_ref, "status": "applied"})
        except (OSError, TypeError, ValueError) as exc:
            errors.append(f"{path_ref}: {exc}")
    return applied, errors


def _write_source_diff_rollback_result(
    storage: LocalStorage,
    plan: dict[str, Any],
    *,
    plan_path: str,
    status: str,
    applied_actions: list[dict[str, Any]],
    errors: list[str],
    approval_path: str,
    project_id: str,
    workspace_path: str,
) -> dict[str, Any]:
    content = plan.get("content", {}) if isinstance(plan.get("content", {}), dict) else {}
    result_id = make_id("rollback_result", f"{content.get('plan_id', plan.get('id', ''))}:{status}:{utc_now()}")
    result_content = {
        "result_id": result_id,
        "plan_id": str(content.get("plan_id") or plan.get("id") or ""),
        "transaction_id": str(content.get("transaction_id") or ""),
        "status": status,
        "applied_actions": applied_actions,
        "errors": errors,
        "approval_request_path": approval_path,
        "created_at": utc_now(),
        "raw_source_text_included": False,
    }
    asset = RollbackResult(
        id=result_id,
        title=f"Source diff repair rollback {status}",
        source=str(content.get("plan_id") or plan.get("id") or ""),
        tags=["source-governance", "source-diff", "rollback-result", status],
        content=result_content,
        metadata={"project_id": project_id, "workspace_path": workspace_path, "asset_status": status, "use_in_generation_rag": False},
        references=_dedupe([plan_path, approval_path, *[str(item.get("target_path") or "") for item in applied_actions]]),
    )
    data = asset.to_dict()
    validation_errors = validate_common_fields(data)
    if validation_errors:
        raise ValueError("; ".join(validation_errors))
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path)}


def _mark_source_diff_agent_tasks_dispatch_ready(storage: LocalStorage, task_paths: list[Any], *, approval_path: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    updates: list[dict[str, Any]] = []
    rollback_actions: list[dict[str, Any]] = []
    for item in task_paths:
        path_ref = str(item or "").strip()
        if not path_ref:
            continue
        try:
            path = resolve_path(storage.root, path_ref)
            data = storage.read_json(path)
            if not isinstance(data, dict) or data.get("type") != "agent_task":
                raise ValueError("task path does not point to an agent_task")
            content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
            before_content = {"status": content.get("status", ""), "evidence": content.get("evidence", {}) if isinstance(content.get("evidence", {}), dict) else {}}
            before_metadata = dict(data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {})
            evidence = content.get("evidence", {}) if isinstance(content.get("evidence", {}), dict) else {}
            evidence.update(
                {
                    "approval_request_path": approval_path,
                    "approval_status": "approved",
                    "dispatch_allowed": True,
                    "queue_dispatch_performed": False,
                    "silent_mutation_allowed": False,
                }
            )
            content["evidence"] = evidence
            content["status"] = "approved_pending_dispatch"
            content["updated_at"] = utc_now()
            data["content"] = content
            metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
            metadata["asset_status"] = "approved_pending_dispatch"
            metadata["approval_request_path"] = approval_path
            data["metadata"] = metadata
            data["updated_at"] = utc_now()
            validation_errors = validate_common_fields(data)
            if validation_errors:
                raise ValueError("; ".join(validation_errors))
            storage.write_json(path, data)
            updates.append({"path": path_ref, "status": "approved_pending_dispatch", "dispatch_applied": False})
            rollback_actions.append(
                {
                    "action": "restore_agent_task_state",
                    "target_path": path_ref,
                    "target_asset_id": str(data.get("id") or ""),
                    "before_content": before_content,
                    "before_metadata": before_metadata,
                }
            )
        except (OSError, TypeError, ValueError) as exc:
            updates.append({"path": path_ref, "status": "failed", "error": str(exc), "dispatch_applied": False})
    return updates, rollback_actions


def _write_source_diff_rollback_plan(
    storage: LocalStorage,
    report: dict[str, Any],
    *,
    report_path: str,
    approval_path: str,
    actions: list[dict[str, Any]],
    project_id: str,
    workspace_path: str,
) -> dict[str, Any]:
    plan_id = make_id("rollback_plan", f"source-diff-repair:{report.get('id', '')}:{utc_now()}")
    transaction_id = make_id("source_diff_repair_apply", f"{report.get('id', '')}:{approval_path}:{utc_now()}")
    content = {
        "plan_id": plan_id,
        "transaction_id": transaction_id,
        "strategy": "restore_source_diff_stale_metadata",
        "actions": actions,
        "rollback_status": "available" if actions else "not_required",
        "created_at": utc_now(),
        "source_diff_repair_report_path": report_path,
        "approval_request_path": approval_path,
        "raw_source_text_included": False,
        "requires_operator_review": True,
    }
    asset = RollbackPlan(
        id=plan_id,
        title=f"Rollback source diff repair {report.get('id', '')}",
        source=str(report.get("id") or ""),
        tags=["source-governance", "source-diff", "rollback-plan", content["rollback_status"]],
        content=content,
        metadata={"project_id": project_id, "workspace_path": workspace_path, "asset_status": content["rollback_status"], "use_in_generation_rag": False},
        references=_dedupe([report_path, approval_path, *[str(action.get("target_path") or "") for action in actions]]),
    )
    data = asset.to_dict()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path)}


def _resolve_asset_with_path(storage: LocalStorage, ref: Any, expected_type: str = "") -> tuple[Path, dict[str, Any]] | None:
    text = str(ref or "").strip()
    if not text:
        return None
    try:
        direct = resolve_path(storage.root, text)
        data = storage.read_json(direct)
        if isinstance(data, dict) and (not expected_type or data.get("type") == expected_type):
            return direct, data
    except (OSError, TypeError, ValueError):
        pass
    for category in DATA_DIRS:
        for path in reversed(storage.list_json(category)):
            try:
                data = storage.read_json(path)
            except (OSError, TypeError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            if expected_type and data.get("type") != expected_type:
                continue
            content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
            if text in {
                str(data.get("id", "")),
                str(content.get("snapshot_id", "")),
                str(content.get("report_id", "")),
                _display_path(storage.root, path),
            }:
                return path, data
    return None


def _source_snapshot_diff(old_snapshot: dict[str, Any], new_snapshot: dict[str, Any]) -> dict[str, Any]:
    old_content = old_snapshot.get("content", {}) if isinstance(old_snapshot.get("content", {}), dict) else {}
    new_content = new_snapshot.get("content", {}) if isinstance(new_snapshot.get("content", {}), dict) else {}
    fields = ["content_hash", "source_path", "source_type", "line_range", "span", "source_policy_ref", "risk_report_ref"]
    changes: list[dict[str, Any]] = []
    for field in fields:
        old_value = old_content.get(field)
        new_value = new_content.get(field)
        if old_value != new_value:
            changes.append({"field": field, "old": old_value, "new": new_value, "severity": _source_diff_field_severity(field)})
    return {
        "status": "changed" if changes else "unchanged",
        "changed_fields": [str(item["field"]) for item in changes],
        "changes": changes,
        "content_hash_changed": old_content.get("content_hash") != new_content.get("content_hash"),
        "source_path_changed": old_content.get("source_path") != new_content.get("source_path"),
        "raw_text_included": False,
        "diff_basis": "SourceSnapshot metadata/hash comparison only; raw source text is not included",
    }


def _source_diff_field_severity(field: str) -> str:
    if field in {"content_hash", "source_policy_ref", "risk_report_ref"}:
        return "high"
    if field in {"source_path", "source_type"}:
        return "medium"
    return "low"


def _source_diff_lineage_keys(root: Path, old_path: Path, old_snapshot: dict[str, Any], new_path: Path, new_snapshot: dict[str, Any]) -> set[str]:
    del new_path, new_snapshot
    keys: set[str] = {_display_path(root, old_path)}
    content = old_snapshot.get("content", {}) if isinstance(old_snapshot.get("content", {}), dict) else {}
    for value in [
        old_snapshot.get("id"),
        old_snapshot.get("source"),
        content.get("snapshot_id"),
        content.get("source_ref"),
        content.get("source_path"),
        content.get("source_policy_ref"),
        content.get("risk_report_ref"),
    ]:
        if str(value or "").strip():
            keys.add(str(value).strip())
    return keys


def _source_diff_downstream_impacts(
    storage: LocalStorage,
    lineage_keys: set[str],
    *,
    old_path: Path,
    new_path: Path,
    project_id: str,
    diff: dict[str, Any],
    max_assets: int = 120,
) -> list[dict[str, Any]]:
    impacted: list[dict[str, Any]] = []
    skip_paths = {_display_path(storage.root, old_path), _display_path(storage.root, new_path)}
    for category in DATA_DIRS:
        for path in storage.list_json(category):
            if len(impacted) >= max_assets:
                return impacted
            path_ref = _display_path(storage.root, path)
            if path_ref in skip_paths:
                continue
            try:
                data = storage.read_json(path)
            except (OSError, TypeError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            asset_type = str(data.get("type") or "")
            if asset_type in SOURCE_DIFF_IGNORED_TYPES or asset_type == "change_impact_report":
                continue
            if project_id and _asset_project_id(data) not in {"", project_id}:
                continue
            refs = _source_diff_reference_values(data)
            matches = sorted(lineage_keys & refs)
            if not matches:
                continue
            severity = _source_diff_asset_severity(asset_type, diff)
            impacted.append(
                {
                    "id": str(data.get("id") or ""),
                    "path": path_ref,
                    "type": asset_type,
                    "title": str(data.get("title") or data.get("name") or ""),
                    "severity": severity,
                    "matched_refs": matches[:8],
                    "reason": "asset references stale or refreshed source governance evidence",
                    "recommended_action": _source_diff_recommended_action(asset_type, severity),
                    "mutation_allowed": False,
                    "requires_operator_review": True,
                }
            )
    return sorted(impacted, key=lambda item: ({"blocking": 0, "high": 1, "medium": 2, "low": 3}.get(item["severity"], 9), item["path"]))


def _source_diff_reference_values(data: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    for value in [data.get("id"), data.get("source")]:
        if str(value or "").strip():
            values.add(str(value).strip())
    for reference in data.get("references", []) if isinstance(data.get("references", []), list) else []:
        if str(reference or "").strip():
            values.add(str(reference).strip())
    for payload in [
        data.get("content", {}) if isinstance(data.get("content", {}), dict) else {},
        data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {},
    ]:
        _collect_source_diff_refs(payload, values)
    return values


def _collect_source_diff_refs(value: Any, values: set[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower()
            if any(token in lowered for token in ["source", "snapshot", "policy_ref", "risk_report", "evidence_ref", "asset_ref", "asset_path", "path"]):
                if isinstance(item, (str, int, float)) and str(item).strip():
                    values.add(str(item).strip())
            _collect_source_diff_refs(item, values)
    elif isinstance(value, list):
        for item in value:
            _collect_source_diff_refs(item, values)


def _asset_project_id(data: dict[str, Any]) -> str:
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    return str(metadata.get("project_id") or content.get("project_id") or "")


def _source_diff_asset_severity(asset_type: str, diff: dict[str, Any]) -> str:
    if asset_type in SOURCE_DIFF_BLOCKING_TYPES:
        return "blocking" if diff.get("content_hash_changed") else "high"
    if asset_type in SOURCE_DIFF_HIGH_IMPACT_TYPES:
        return "high" if diff.get("content_hash_changed") else "medium"
    if asset_type in SOURCE_DIFF_REVIEW_TYPES:
        return "medium" if diff.get("content_hash_changed") else "low"
    return "low"


def _source_diff_recommended_action(asset_type: str, severity: str) -> str:
    if severity == "blocking":
        return "block publish until source diff is reviewed and release evidence is regenerated"
    if asset_type in {"context_bundle", "context_build_plan"}:
        return "invalidate context selection after operator approval and rebuild context from approved source-derived assets"
    if asset_type in {"knowledge_card", "knowledge_pack", "material_card", "writing_template", "review_rule"}:
        return "review source-derived abstraction and regenerate only through an approved repair task"
    if asset_type in {"draft_chapter", "draft_version", "review_report", "revision_plan", "revision_task"}:
        return "rerun review/revision after approved source repair and context invalidation"
    return "inspect lineage and confirm whether the asset remains valid"


def _source_diff_severity_summary(impacted: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"blocking": 0, "high": 0, "medium": 0, "low": 0}
    for item in impacted:
        severity = str(item.get("severity") or "low")
        summary[severity] = summary.get(severity, 0) + 1
    return summary


def _source_diff_recommendation(summary: dict[str, int], diff: dict[str, Any]) -> str:
    if summary.get("blocking"):
        return "block_until_resolved"
    if summary.get("high"):
        return "regenerate_downstream"
    if summary.get("medium") or summary.get("low") or diff.get("status") == "changed":
        return "review_impacts"
    return "no_action"


def _source_diff_repair_plan(impacted: list[dict[str, Any]], diff: dict[str, Any]) -> dict[str, Any]:
    impacted_types = sorted({str(item.get("type") or "") for item in impacted if str(item.get("type") or "").strip()})
    return {
        "status": "needs_review" if impacted or diff.get("status") == "changed" else "current",
        "changed_fields": diff.get("changed_fields", []),
        "impacted_types": impacted_types,
        "steps": [
            "review source snapshot metadata/hash diff",
            "confirm license and risk policy still allow downstream abstract assets",
            "approve invalidation before any source-derived context, material, or knowledge asset is marked stale",
            "plan regeneration/re-review tasks after invalidation approval",
        ]
        if impacted or diff.get("status") == "changed"
        else ["no downstream repair required"],
        "operator_review_required": bool(impacted or diff.get("status") == "changed"),
        "auto_apply": False,
    }


def _write_source_diff_review_issue(
    storage: LocalStorage,
    report: dict[str, Any],
    old_snapshot: dict[str, Any],
    new_snapshot: dict[str, Any],
    impacted: list[dict[str, Any]],
    diff: dict[str, Any],
    *,
    project_id: str,
    workspace_path: str,
) -> dict[str, Any]:
    if not impacted and diff.get("status") != "changed":
        return {}
    from novel_forge.modules.review_issue import create_review_issue

    blocking = any(str(item.get("severity") or "") == "blocking" for item in impacted)
    high = any(str(item.get("severity") or "") == "high" for item in impacted) or bool(diff.get("content_hash_changed"))
    severity = "critical" if blocking else "high" if high else "medium"
    report_asset = report.get("asset", {}) if isinstance(report.get("asset", {}), dict) else {}
    report_content = report_asset.get("content", {}) if isinstance(report_asset.get("content", {}), dict) else {}
    return create_review_issue(
        storage,
        {
            "issue_type": "source_snapshot_drift",
            "severity": severity,
            "blocking": bool(blocking or high),
            "status": "open",
            "target_asset_id": _asset_ref(old_snapshot),
            "target_asset_type": "source_snapshot",
            "target_asset_path": str(report_content.get("old_snapshot_path") or ""),
            "message": f"Source snapshot drift affects {len(impacted)} downstream asset(s); repair must be operator-approved before invalidation or regeneration.",
            "fix_suggestion": "Review the source diff report, approve invalidation, then regenerate/re-review downstream source-derived assets through planned AgentTasks.",
            "evidence_refs": _dedupe([str(report.get("path") or ""), _asset_ref(old_snapshot), _asset_ref(new_snapshot)]),
            "project_id": project_id,
            "workspace_path": workspace_path,
            "source_system": "source_intake.diff_repair",
            "source_issue": {"source_diff": diff, "impacted_count": len(impacted), "silent_mutation_allowed": False},
        },
    )


def _write_source_diff_agent_tasks(
    storage: LocalStorage,
    report: dict[str, Any],
    review_issue: dict[str, Any],
    impacted: list[dict[str, Any]],
    *,
    project_id: str,
    workspace_path: str,
) -> list[dict[str, Any]]:
    if not review_issue and not impacted:
        return []
    from novel_forge.modules.agent_scheduler import create_agent_task

    report_path = str(report.get("path") or "")
    issue_path = str(review_issue.get("path") or "")
    input_assets = _dedupe([report_path, issue_path])
    evidence = {
        "source_diff_repair_report_path": report_path,
        "review_issue_path": issue_path,
        "impacted_count": len(impacted),
        "silent_mutation_allowed": False,
        "dispatch_allowed": False,
        "requires_operator_approval": True,
    }
    tasks = [
        create_agent_task(
            storage,
            agent_type="Quality Agent",
            operation="review-source-diff-repair-plan",
            input_assets=input_assets,
            output_targets=[{"asset_type": "review_issue", "purpose": "source diff repair decision"}],
            status="needs_review",
            project_id=project_id,
            workspace_path=workspace_path,
            linked_review_issue_path=issue_path,
            evidence={**evidence, "repair_phase": "review"},
        )
    ]
    if impacted:
        tasks.append(
            create_agent_task(
                storage,
                agent_type="Context Agent",
                operation="plan-source-derived-invalidation",
                input_assets=input_assets,
                output_targets=[{"asset_type": "change_impact_report", "purpose": "approved invalidation plan"}],
                status="needs_review",
                project_id=project_id,
                workspace_path=workspace_path,
                linked_review_issue_path=issue_path,
                evidence={**evidence, "repair_phase": "invalidation_plan"},
            )
        )
    if any(str(item.get("severity") or "") in {"blocking", "high", "medium"} for item in impacted):
        tasks.append(
            create_agent_task(
                storage,
                agent_type="Workflow Agent",
                operation="plan-source-derived-regeneration",
                input_assets=input_assets,
                output_targets=[
                    {"asset_type": "revision_task", "purpose": "regenerate stale source-derived asset after approval"},
                    {"asset_type": "context_bundle", "purpose": "rebuild context after approved invalidation"},
                ],
                status="needs_review",
                project_id=project_id,
                workspace_path=workspace_path,
                linked_review_issue_path=issue_path,
                evidence={**evidence, "repair_phase": "regeneration_plan"},
            )
        )
    return tasks


def _update_source_diff_report_links(storage: LocalStorage, report_path: str, review_issue: dict[str, Any], agent_tasks: list[dict[str, Any]]) -> dict[str, Any]:
    path = resolve_path(storage.root, report_path)
    data = storage.read_json(path)
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    content["review_issue_paths"] = _dedupe([str(review_issue.get("path") or "")])
    content["agent_task_paths"] = _dedupe([str(task.get("path") or "") for task in agent_tasks])
    content["repair_plan"]["planned_agent_operations"] = [str(task.get("asset", {}).get("content", {}).get("operation") or "") for task in agent_tasks]
    data["content"] = content
    data["updated_at"] = utc_now()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    storage.write_json(path, data)
    return storage.read_json(path)
