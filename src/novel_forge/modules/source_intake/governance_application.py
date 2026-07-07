from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.constants import DATA_DIRS
from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.modules.source_intake.service import _dedupe, _display_path, _metadata_value, _strings
from novel_forge.schemas import RollbackPlan, RollbackResult, validate_common_fields
from novel_forge.storage.local import LocalStorage

SUPPORTED_GOVERNANCE_REPORT_TYPES = {"mkaos_weight_governance_report", "change_impact_report"}


def apply_governance_recommendations(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    """Apply approved governance recommendations as reversible metadata-only changes."""
    storage.ensure_layout()
    report_path, report = _resolve_report(storage, payload.get("governance_report_path") or payload.get("report_path"))
    report_type = str(report.get("type") or "")
    project_id = str(payload.get("project_id") or _report_project_id(report) or "")
    workspace_path = str(payload.get("workspace_path") or _metadata_value(report, "workspace_path") or "")
    selected_refs = _selected_refs(payload)
    approval = _governance_apply_approval(storage, payload, report_path, report, project_id=project_id, workspace_path=workspace_path)
    approval_status = _approval_status(approval)
    if approval_status != "approved":
        return {
            "status": "approval_required",
            "governance_report_path": _display_path(storage.root, report_path),
            "approval_request": approval,
            "updated_assets": [],
            "rollback_plan": {},
            "mutation_applied": False,
            "reason": "governance application requires approved ApprovalRequest",
        }
    if not bool(payload.get("confirm_apply")):
        return {
            "status": "ready_for_confirm",
            "governance_report_path": _display_path(storage.root, report_path),
            "approval_request": approval,
            "updated_assets": [],
            "rollback_plan": {},
            "mutation_applied": False,
            "reason": "approved governance application requires confirm_apply=true before metadata changes",
        }

    if report_type == "mkaos_weight_governance_report":
        updated_assets, rollback_actions, errors = _apply_mkaos_weight_governance_metadata(
            storage,
            report,
            report_path=_display_path(storage.root, report_path),
            approval_path=str(approval.get("path") or payload.get("approval_request_path") or payload.get("approval_request_ref") or ""),
            actor=str(payload.get("actor") or "operator"),
            selected_refs=selected_refs,
        )
    else:
        updated_assets, rollback_actions, errors = _apply_change_impact_governance_metadata(
            storage,
            report,
            report_path=_display_path(storage.root, report_path),
            approval_path=str(approval.get("path") or payload.get("approval_request_path") or payload.get("approval_request_ref") or ""),
            actor=str(payload.get("actor") or "operator"),
            selected_refs=selected_refs,
        )

    report_content = report.get("content", {}) if isinstance(report.get("content", {}), dict) else {}
    task_updates, task_rollback_actions = _mark_governance_agent_tasks_dispatch_ready(
        storage,
        report_content.get("agent_task_paths", []) if isinstance(report_content.get("agent_task_paths", []), list) else [],
        approval_path=str(approval.get("path") or payload.get("approval_request_path") or payload.get("approval_request_ref") or ""),
    )
    rollback_actions.extend(task_rollback_actions)
    rollback_plan = _write_governance_rollback_plan(
        storage,
        report,
        report_path=_display_path(storage.root, report_path),
        approval_path=str(approval.get("path") or payload.get("approval_request_path") or payload.get("approval_request_ref") or ""),
        actions=rollback_actions,
        project_id=project_id,
        workspace_path=workspace_path,
    )
    _record_apply_result(
        storage,
        report_path,
        report,
        approval_path=str(approval.get("path") or ""),
        rollback_plan_path=str(rollback_plan.get("path") or ""),
        updated_assets=updated_assets,
        task_updates=task_updates,
        errors=errors,
    )
    return {
        "status": "applied_with_errors" if errors else "applied",
        "governance_report_path": _display_path(storage.root, report_path),
        "approval_request": approval,
        "updated_assets": updated_assets,
        "task_updates": task_updates,
        "rollback_plan": rollback_plan,
        "errors": errors,
        "mutation_applied": bool(updated_assets),
        "mutation_scope": "metadata_only",
        "dispatch_applied": False,
    }


def rollback_governance_application(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    storage.ensure_layout()
    plan_path = resolve_path(storage.root, payload.get("rollback_plan_path") or payload.get("plan_path"))
    plan = storage.read_json(plan_path)
    if not isinstance(plan, dict) or plan.get("type") != "rollback_plan":
        raise ValueError("rollback_plan_path must point to a rollback_plan asset")
    content = plan.get("content", {}) if isinstance(plan.get("content", {}), dict) else {}
    if str(content.get("strategy") or "") != "restore_governance_application_metadata":
        raise ValueError("rollback_plan_path must point to a governance application rollback_plan")
    project_id = str(payload.get("project_id") or _metadata_value(plan, "project_id") or "")
    workspace_path = str(payload.get("workspace_path") or _metadata_value(plan, "workspace_path") or "")
    approval = _governance_rollback_approval(storage, payload, plan_path, plan, project_id=project_id, workspace_path=workspace_path)
    approval_status = _approval_status(approval)
    if approval_status != "approved":
        return {
            "status": "approval_required",
            "rollback_plan_path": _display_path(storage.root, plan_path),
            "approval_request": approval,
            "applied_actions": [],
            "rollback_result": {},
            "rollback_applied": False,
            "reason": "governance application rollback requires approved ApprovalRequest",
        }
    if not bool(payload.get("confirm_rollback")):
        return {
            "status": "ready_for_confirm",
            "rollback_plan_path": _display_path(storage.root, plan_path),
            "approval_request": approval,
            "applied_actions": [],
            "rollback_result": {},
            "rollback_applied": False,
            "reason": "approved governance rollback requires confirm_rollback=true",
        }

    applied_actions, errors = _apply_governance_rollback_actions(storage, content.get("actions", []) if isinstance(content.get("actions", []), list) else [], actor=str(payload.get("actor") or "operator"))
    status = "failed" if errors else "applied"
    result = _write_governance_rollback_result(
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


def _apply_mkaos_weight_governance_metadata(
    storage: LocalStorage,
    report: dict[str, Any],
    *,
    report_path: str,
    approval_path: str,
    actor: str,
    selected_refs: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    content = report.get("content", {}) if isinstance(report.get("content", {}), dict) else {}
    recommendations = content.get("recommendations", []) if isinstance(content.get("recommendations", []), list) else []
    updated: list[dict[str, Any]] = []
    rollback_actions: list[dict[str, Any]] = []
    errors: list[str] = []
    for recommendation in recommendations:
        if not isinstance(recommendation, dict):
            continue
        target_id = str(recommendation.get("asset_id") or recommendation.get("knowledge_id") or "").strip()
        if not target_id:
            continue
        try:
            path, data = _resolve_asset_by_ref(storage, target_id)
            path_ref = _display_path(storage.root, path)
            if selected_refs and not _matches_selected_refs(data, path_ref, selected_refs):
                continue
            action = str(recommendation.get("recommended_action") or "keep")
            delta = _float(recommendation.get("weight_delta"), 0.0)
            review_required = bool(recommendation.get("review_required_before_apply") or recommendation.get("invalidation_recommendations"))
            risk_level = str(recommendation.get("risk_level") or "")
            if action == "keep" and delta == 0.0 and not review_required:
                continue
            before_metadata = dict(data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {})
            metadata = dict(before_metadata)
            metadata.update(
                {
                    "mkaos_governance_application_status": "applied_metadata_only",
                    "mkaos_governance_report_path": report_path,
                    "mkaos_governance_approval_request_path": approval_path,
                    "mkaos_governance_action": action,
                    "mkaos_governance_weight_delta": delta,
                    "mkaos_governance_risk_level": risk_level,
                    "mkaos_governance_review_required": review_required,
                    "mkaos_governance_applied_at": utc_now(),
                    "mkaos_governance_applied_by": actor,
                    "mkaos_governance_content_weight_mutated": False,
                }
            )
            if action == "quarantine":
                metadata["asset_status"] = "quarantined"
                metadata["use_in_generation_rag"] = False
            elif action == "deprecate":
                metadata["asset_status"] = "deprecated"
                metadata["use_in_generation_rag"] = False
            elif review_required or risk_level in {"high", "critical"}:
                metadata["asset_status"] = "needs_review"
                metadata["use_in_generation_rag"] = False
            else:
                metadata["mkaos_weight_adjustment_status"] = "approved_pending_selector_refresh"
            data["metadata"] = metadata
            data["updated_at"] = utc_now()
            validation_errors = validate_common_fields(data)
            if validation_errors:
                raise ValueError("; ".join(validation_errors))
            storage.write_json(path, data)
            updated.append({"path": path_ref, "asset_id": str(data.get("id") or ""), "action": action, "status": str(metadata.get("asset_status") or "metadata_applied"), "content_mutated": False})
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
            errors.append(f"{target_id}: {exc}")
    return updated, rollback_actions, errors


def _apply_change_impact_governance_metadata(
    storage: LocalStorage,
    report: dict[str, Any],
    *,
    report_path: str,
    approval_path: str,
    actor: str,
    selected_refs: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    content = report.get("content", {}) if isinstance(report.get("content", {}), dict) else {}
    impacted = content.get("impacted_assets", []) if isinstance(content.get("impacted_assets", []), list) else []
    recommendation = str(content.get("recommendation") or "review_impacts")
    updated: list[dict[str, Any]] = []
    rollback_actions: list[dict[str, Any]] = []
    errors: list[str] = []
    for item in impacted:
        if not isinstance(item, dict):
            continue
        path_ref = str(item.get("path") or "").strip()
        if not path_ref:
            continue
        try:
            path, data = _resolve_asset_by_ref(storage, path_ref)
            normalized_path = _display_path(storage.root, path)
            if selected_refs and not _matches_selected_refs(data, normalized_path, selected_refs):
                continue
            severity = str(item.get("severity") or "medium")
            before_metadata = dict(data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {})
            metadata = dict(before_metadata)
            asset_status = "stale" if recommendation in {"regenerate_downstream", "block_until_resolved"} or severity in {"high", "blocking"} else "needs_review"
            metadata.update(
                {
                    "asset_status": asset_status,
                    "governance_application_status": "applied_metadata_only",
                    "governance_report_path": report_path,
                    "governance_approval_request_path": approval_path,
                    "governance_recommendation": recommendation,
                    "governance_impact_severity": severity,
                    "governance_applied_at": utc_now(),
                    "governance_applied_by": actor,
                    "governance_content_mutated": False,
                }
            )
            if asset_status in {"stale", "needs_review"}:
                metadata["use_in_generation_rag"] = False
            data["metadata"] = metadata
            data["updated_at"] = utc_now()
            validation_errors = validate_common_fields(data)
            if validation_errors:
                raise ValueError("; ".join(validation_errors))
            storage.write_json(path, data)
            updated.append({"path": normalized_path, "asset_id": str(data.get("id") or ""), "severity": severity, "status": asset_status, "content_mutated": False})
            rollback_actions.append(
                {
                    "action": "restore_asset_metadata",
                    "target_path": normalized_path,
                    "target_asset_id": str(data.get("id") or ""),
                    "before_metadata": before_metadata,
                    "applied_metadata": metadata,
                }
            )
        except (OSError, TypeError, ValueError) as exc:
            errors.append(f"{path_ref}: {exc}")
    return updated, rollback_actions, errors


def _governance_apply_approval(
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

    target_refs = _target_refs_for_report(report)
    risk_level = _risk_level_for_report(report)
    report_ref = _display_path(storage.root, report_path)
    return create_approval_request(
        storage,
        {
            "project_id": project_id,
            "workspace_path": workspace_path,
            "scope": "source" if report.get("type") == "change_impact_report" else "context",
            "action": "approve_governance_recommendation_apply",
            "environment": str(payload.get("environment") or "local"),
            "risk_level": risk_level,
            "blocking": True,
            "target_type": str(report.get("type") or "governance_report"),
            "target_id": str(report.get("id") or ""),
            "target_path": report_ref,
            "target_refs": target_refs,
            "evidence_refs": _dedupe([report_ref, *_strings(payload.get("evidence_refs"))]),
            "reason": "Apply reviewable governance recommendations as reversible metadata-only changes",
            "required_before": ["governance_recommendation_metadata_application"],
            "rollback_plan": {
                "available": True,
                "strategy": "restore_governance_application_metadata",
                "requires_operator_review": True,
            },
        },
    )


def _governance_rollback_approval(
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
    plan_ref = _display_path(storage.root, plan_path)
    return create_approval_request(
        storage,
        {
            "project_id": project_id,
            "workspace_path": workspace_path,
            "scope": "source",
            "action": "approve_governance_application_rollback",
            "environment": str(payload.get("environment") or "local"),
            "risk_level": "high" if target_refs else "medium",
            "blocking": True,
            "target_type": "rollback_plan",
            "target_id": str(plan.get("id") or ""),
            "target_path": plan_ref,
            "target_refs": target_refs,
            "evidence_refs": _dedupe([plan_ref, str(content.get("governance_report_path") or ""), *_strings(payload.get("evidence_refs"))]),
            "reason": "Rollback previously approved governance metadata application",
            "required_before": ["governance_application_rollback"],
            "rollback_plan": {
                "available": False,
                "strategy": "manual_reapply_governance_recommendation_if_rollback_was_incorrect",
                "requires_operator_review": True,
            },
        },
    )


def _mark_governance_agent_tasks_dispatch_ready(storage: LocalStorage, task_paths: list[Any], *, approval_path: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    updates: list[dict[str, Any]] = []
    rollback_actions: list[dict[str, Any]] = []
    for item in task_paths:
        path_ref = str(item or "").strip()
        if not path_ref:
            continue
        try:
            path, data = _resolve_asset_by_ref(storage, path_ref)
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
                    "governance_application": True,
                }
            )
            content["evidence"] = evidence
            content["status"] = "approved_pending_dispatch"
            content["updated_at"] = utc_now()
            data["content"] = content
            metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
            metadata["asset_status"] = "approved_pending_dispatch"
            metadata["approval_request_path"] = approval_path
            metadata["governance_application_dispatch_ready"] = True
            data["metadata"] = metadata
            data["updated_at"] = utc_now()
            validation_errors = validate_common_fields(data)
            if validation_errors:
                raise ValueError("; ".join(validation_errors))
            storage.write_json(path, data)
            normalized_path = _display_path(storage.root, path)
            updates.append({"path": normalized_path, "status": "approved_pending_dispatch", "dispatch_applied": False})
            rollback_actions.append(
                {
                    "action": "restore_agent_task_state",
                    "target_path": normalized_path,
                    "target_asset_id": str(data.get("id") or ""),
                    "before_content": before_content,
                    "before_metadata": before_metadata,
                }
            )
        except (OSError, TypeError, ValueError) as exc:
            updates.append({"path": path_ref, "status": "failed", "error": str(exc), "dispatch_applied": False})
    return updates, rollback_actions


def _write_governance_rollback_plan(
    storage: LocalStorage,
    report: dict[str, Any],
    *,
    report_path: str,
    approval_path: str,
    actions: list[dict[str, Any]],
    project_id: str,
    workspace_path: str,
) -> dict[str, Any]:
    plan_id = make_id("rollback_plan", f"governance-application:{report.get('id', '')}:{utc_now()}")
    transaction_id = make_id("governance_application", f"{report.get('id', '')}:{approval_path}:{utc_now()}")
    content = {
        "plan_id": plan_id,
        "transaction_id": transaction_id,
        "strategy": "restore_governance_application_metadata",
        "actions": actions,
        "rollback_status": "available" if actions else "not_required",
        "created_at": utc_now(),
        "governance_report_path": report_path,
        "approval_request_path": approval_path,
        "raw_source_text_included": False,
        "prose_mutation_included": False,
        "requires_operator_review": True,
    }
    asset = RollbackPlan(
        id=plan_id,
        title=f"Rollback governance application {report.get('id', '')}",
        source=str(report.get("id") or ""),
        tags=["governance", "mkaos", "source-governance", "rollback-plan", content["rollback_status"]],
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


def _write_governance_rollback_result(
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
    result_id = make_id("rollback_result", f"governance-application:{content.get('plan_id', plan.get('id', ''))}:{status}:{utc_now()}")
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
        "prose_mutation_included": False,
    }
    asset = RollbackResult(
        id=result_id,
        title=f"Governance application rollback {status}",
        source=str(content.get("plan_id") or plan.get("id") or ""),
        tags=["governance", "rollback-result", status],
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


def _apply_governance_rollback_actions(storage: LocalStorage, actions: list[dict[str, Any]], *, actor: str) -> tuple[list[dict[str, Any]], list[str]]:
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
            path, data = _resolve_asset_by_ref(storage, path_ref)
            if action_type == "restore_agent_task_state":
                content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
                before_content = action.get("before_content", {}) if isinstance(action.get("before_content", {}), dict) else {}
                content["status"] = str(before_content.get("status") or content.get("status") or "needs_review")
                content["evidence"] = before_content.get("evidence", {}) if isinstance(before_content.get("evidence", {}), dict) else {}
                content["updated_at"] = utc_now()
                data["content"] = content
                data["metadata"] = dict(action.get("before_metadata", {}) if isinstance(action.get("before_metadata", {}), dict) else {})
            elif action_type == "restore_asset_metadata":
                data["metadata"] = dict(action.get("before_metadata", {}) if isinstance(action.get("before_metadata", {}), dict) else {})
            else:
                raise ValueError(f"unsupported governance rollback action: {action_type}")
            metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
            metadata["governance_rollback_at"] = utc_now()
            metadata["governance_rollback_actor"] = actor
            data["metadata"] = metadata
            data["updated_at"] = utc_now()
            validation_errors = validate_common_fields(data)
            if validation_errors:
                raise ValueError("; ".join(validation_errors))
            storage.write_json(path, data)
            applied.append({"action": action_type, "target_path": _display_path(storage.root, path), "status": "applied"})
        except (OSError, TypeError, ValueError) as exc:
            errors.append(f"{path_ref}: {exc}")
    return applied, errors


def _record_apply_result(
    storage: LocalStorage,
    report_path: Path,
    report: dict[str, Any],
    *,
    approval_path: str,
    rollback_plan_path: str,
    updated_assets: list[dict[str, Any]],
    task_updates: list[dict[str, Any]],
    errors: list[str],
) -> None:
    content = report.get("content", {}) if isinstance(report.get("content", {}), dict) else {}
    content["governance_application_result"] = {
        "status": "applied_with_errors" if errors else "applied",
        "approval_request_path": approval_path,
        "updated_assets": updated_assets,
        "task_updates": task_updates,
        "rollback_plan_path": rollback_plan_path,
        "errors": errors,
        "mutation_scope": "metadata_only",
        "raw_source_text_included": False,
        "prose_mutation_included": False,
        "dispatch_applied": False,
        "applied_at": utc_now(),
    }
    report["content"] = content
    metadata = report.get("metadata", {}) if isinstance(report.get("metadata", {}), dict) else {}
    metadata["asset_status"] = "applied_with_errors" if errors else "applied"
    metadata["governance_application_status"] = metadata["asset_status"]
    report["metadata"] = metadata
    report["updated_at"] = utc_now()
    validation_errors = validate_common_fields(report)
    if validation_errors:
        raise ValueError("; ".join(validation_errors))
    storage.write_json(report_path, report)


def _resolve_report(storage: LocalStorage, ref: Any) -> tuple[Path, dict[str, Any]]:
    path, data = _resolve_asset_by_ref(storage, str(ref or ""))
    if str(data.get("type") or "") not in SUPPORTED_GOVERNANCE_REPORT_TYPES:
        raise ValueError("governance_report_path must point to a supported governance report")
    return path, data


def _resolve_asset_by_ref(storage: LocalStorage, ref: str) -> tuple[Path, dict[str, Any]]:
    text = str(ref or "").strip()
    if not text:
        raise ValueError("asset reference must not be empty")
    try:
        direct = resolve_path(storage.root, text)
        data = storage.read_json(direct)
        if isinstance(data, dict):
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
            content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
            if text in {str(data.get("id") or ""), str(content.get("report_id") or ""), str(content.get("weight_governance_report_id") or ""), _display_path(storage.root, path)}:
                return path, data
    raise ValueError(f"asset not found: {text}")


def _read_approval_request(storage: LocalStorage, approval_ref: str) -> dict[str, Any]:
    try:
        path, data = _resolve_asset_by_ref(storage, approval_ref)
    except (OSError, TypeError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("type") != "approval_request":
        return {}
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    return {"status": str(content.get("status") or ""), "path": _display_path(storage.root, path), "asset": data}


def _approval_status(approval: dict[str, Any]) -> str:
    asset = approval.get("asset", {}) if isinstance(approval.get("asset", {}), dict) else {}
    content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
    return str(approval.get("status") or content.get("status") or "")


def _report_project_id(report: dict[str, Any]) -> str:
    content = report.get("content", {}) if isinstance(report.get("content", {}), dict) else {}
    return str(content.get("project_id") or _metadata_value(report, "project_id") or "")


def _target_refs_for_report(report: dict[str, Any]) -> list[str]:
    content = report.get("content", {}) if isinstance(report.get("content", {}), dict) else {}
    if report.get("type") == "mkaos_weight_governance_report":
        recommendations = content.get("recommendations", []) if isinstance(content.get("recommendations", []), list) else []
        return _dedupe([str(item.get("asset_id") or "") for item in recommendations if isinstance(item, dict)])
    impacted = content.get("impacted_assets", []) if isinstance(content.get("impacted_assets", []), list) else []
    return _dedupe([str(item.get("path") or "") for item in impacted if isinstance(item, dict)])


def _risk_level_for_report(report: dict[str, Any]) -> str:
    content = report.get("content", {}) if isinstance(report.get("content", {}), dict) else {}
    if report.get("type") == "mkaos_weight_governance_report":
        recommendations = content.get("recommendations", []) if isinstance(content.get("recommendations", []), list) else []
        for item in recommendations:
            if not isinstance(item, dict):
                continue
            if str(item.get("recommended_action") or "") in {"quarantine", "deprecate"} or str(item.get("risk_level") or "") in {"high", "critical"}:
                return "high"
        return "medium"
    summary = content.get("severity_summary", {}) if isinstance(content.get("severity_summary", {}), dict) else {}
    if int(summary.get("blocking", 0) or 0) > 0:
        return "critical"
    if int(summary.get("high", 0) or 0) > 0:
        return "high"
    return "medium"


def _selected_refs(payload: dict[str, Any]) -> set[str]:
    return set(_strings(payload.get("selected_target_refs")) or _strings(payload.get("selected_target_paths")) or _strings(payload.get("selected_asset_ids")))


def _matches_selected_refs(asset: dict[str, Any], path_ref: str, selected_refs: set[str]) -> bool:
    if not selected_refs:
        return True
    content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
    candidates = {
        str(asset.get("id") or ""),
        path_ref,
        str(content.get("knowledge_id") or ""),
        str(content.get("asset_id") or ""),
        str(content.get("report_id") or ""),
    }
    return bool(candidates & selected_refs)


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
