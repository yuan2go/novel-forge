from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from novel_forge.core.constants import DATA_DIRS
from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.modules.mkaos import service as mkaos_service
from novel_forge.modules import mkaos_model_extraction
from novel_forge.schemas import ChangeImpactReport, RollbackPlan, RollbackResult, validate_common_fields
from novel_forge.storage.local import LocalStorage

MKAOS_LIFECYCLE_REPORT_TAG = "mkaos-lifecycle-transition"
DO_NOT_SELECT_STATES = {"quarantined", "deprecated", "do_not_select", "rejected"}
VALID_TRANSITIONS = {
    "knowledge_card_candidate": {
        "needs_review": {"approved", "rejected", "quarantined"},
        "pending": {"approved", "rejected", "quarantined"},
        "approved": {"quarantined"},
        "rejected": {"needs_review"},
        "quarantined": {"needs_review", "deprecated"},
    },
    "mkaos_model_extraction_candidate": {
        "pending": {"approved", "rejected", "quarantined"},
        "needs_review": {"approved", "rejected", "quarantined"},
        "approved": {"quarantined"},
        "rejected": {"needs_review"},
        "quarantined": {"needs_review", "deprecated"},
    },
    "knowledge_card": {
        "active": {"needs_review", "quarantined", "deprecated", "do_not_select"},
        "verified": {"needs_review", "quarantined", "deprecated", "do_not_select"},
        "needs_review": {"active", "verified", "quarantined", "deprecated", "do_not_select"},
        "quarantined": {"needs_review", "deprecated"},
        "deprecated": {"needs_review"},
        "do_not_select": {"needs_review", "deprecated"},
    },
    "rule_card": {
        "active": {"needs_review", "quarantined", "deprecated", "do_not_select"},
        "enabled": {"needs_review", "quarantined", "deprecated", "do_not_select"},
        "needs_review": {"active", "quarantined", "deprecated", "do_not_select"},
        "quarantined": {"needs_review", "deprecated"},
        "deprecated": {"needs_review"},
        "do_not_select": {"needs_review", "deprecated"},
    },
    "template_card": {
        "active": {"needs_review", "quarantined", "deprecated", "do_not_select"},
        "enabled": {"needs_review", "quarantined", "deprecated", "do_not_select"},
        "needs_review": {"active", "quarantined", "deprecated", "do_not_select"},
        "quarantined": {"needs_review", "deprecated"},
        "deprecated": {"needs_review"},
        "do_not_select": {"needs_review", "deprecated"},
    },
    "writing_template": {
        "active": {"needs_review", "quarantined", "deprecated", "do_not_select"},
        "enabled": {"needs_review", "quarantined", "deprecated", "do_not_select"},
        "needs_review": {"active", "quarantined", "deprecated", "do_not_select"},
        "quarantined": {"needs_review", "deprecated"},
        "deprecated": {"needs_review"},
        "do_not_select": {"needs_review", "deprecated"},
    },
    "review_rule_pack": {
        "active": {"needs_review", "quarantined", "deprecated", "do_not_select"},
        "enabled": {"needs_review", "quarantined", "deprecated", "do_not_select"},
        "needs_review": {"active", "quarantined", "deprecated", "do_not_select"},
        "quarantined": {"needs_review", "deprecated"},
        "deprecated": {"needs_review"},
        "do_not_select": {"needs_review", "deprecated"},
    },
}


def plan_mkaos_asset_lifecycle(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    storage.ensure_layout()
    target_ref = str(payload.get("target_ref") or payload.get("asset_ref") or payload.get("candidate_ref") or payload.get("knowledge_ref") or "").strip()
    if not target_ref:
        raise ValueError("target_ref is required")
    target_path, target = _resolve_mkaos_asset(storage, target_ref)
    target_type = str(target.get("type") or "")
    current_state = _asset_state(target)
    requested_state = _normalize_state(str(payload.get("requested_state") or payload.get("target_state") or payload.get("state") or "").strip())
    if not requested_state:
        raise ValueError("requested_state is required")
    valid = _transition_valid(target_type, current_state, requested_state)
    project_id = str(payload.get("project_id") or _asset_project_id(target) or "")
    workspace_path = str(payload.get("workspace_path") or _asset_workspace_path(target) or "")
    path_ref = _display_path(storage.root, target_path)
    severity = "high" if requested_state in DO_NOT_SELECT_STATES else "medium"
    recommendation = "review_impacts" if valid else "block_until_resolved"
    plan_id = make_id("change_impact_report", _short_token("mkaos-lifecycle", f"{target.get('id', '')}:{current_state}->{requested_state}:{utc_now()}"))
    content = {
        "target_asset_id": str(target.get("id") or ""),
        "target_asset_type": target_type,
        "target_path": path_ref,
        "project_id": project_id,
        "current_state": current_state,
        "requested_state": requested_state,
        "valid_transition": valid,
        "transition_plan": {
            "transition_id": plan_id,
            "target_ref": target_ref,
            "target_type": target_type,
            "target_path": path_ref,
            "from_state": current_state,
            "to_state": requested_state,
            "reason": str(payload.get("reason") or "mkaos lifecycle transition"),
            "actor": str(payload.get("actor") or "operator"),
            "approve_candidate_creates_knowledge_card": target_type in {"knowledge_card_candidate", "mkaos_model_extraction_candidate"} and requested_state == "approved",
            "metadata_only_for_existing_cards": target_type == "knowledge_card",
            "raw_source_text_included": False,
            "prose_mutation_included": False,
        },
        "context_exclusion": _context_exclusion_for_transition(target_type, requested_state),
        "impacted_assets": [{"id": str(target.get("id") or ""), "path": path_ref, "severity": severity}],
        "impact_edges": [{"source": path_ref, "target": path_ref, "relation": "mkaos_lifecycle_transition", "requires_review": True}],
        "severity_summary": {"blocking": 0 if valid else 1, "high": 1 if severity == "high" else 0, "medium": 1 if severity == "medium" else 0, "low": 0},
        "recommendation": recommendation,
        "review_issue_paths": [],
        "agent_task_paths": [],
        "lifecycle_contract": {
            "contract_version": "mkaos-asset-lifecycle-v1",
            "approval_required": True,
            "confirm_apply_required": True,
            "silent_content_rewrite_allowed": False,
            "raw_source_text_allowed": False,
            "auto_context_injection_allowed": False,
            "rollback_required": True,
        },
        "generated_at": utc_now(),
    }
    asset = ChangeImpactReport(
        id=plan_id,
        title=f"MKAOS lifecycle {target_type} {current_state}->{requested_state}",
        source=str(target.get("id") or target_ref),
        tags=["mkaos", "lifecycle", MKAOS_LIFECYCLE_REPORT_TAG, "valid" if valid else "invalid"],
        content=content,
        metadata={"project_id": project_id, "workspace_path": workspace_path, "asset_status": "needs_review", "use_in_generation_rag": False},
        references=[path_ref, str(target.get("id") or "")],
    )
    data = asset.to_dict()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset)
    return {"status": "planned" if valid else "blocked", "path": _display_path(storage.root, path), "asset": storage.read_json(path), "valid_transition": valid}


def apply_mkaos_asset_lifecycle(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    storage.ensure_layout()
    plan_path, plan = _resolve_lifecycle_plan(storage, payload.get("lifecycle_plan_path") or payload.get("plan_path"))
    content = plan.get("content", {}) if isinstance(plan.get("content", {}), dict) else {}
    if not bool(content.get("valid_transition")):
        raise ValueError("cannot apply invalid MKAOS lifecycle transition")
    project_id = str(payload.get("project_id") or _asset_project_id(plan) or content.get("project_id") or "")
    workspace_path = str(payload.get("workspace_path") or _asset_workspace_path(plan) or "")
    approval = _lifecycle_apply_approval(storage, payload, plan_path, plan, project_id=project_id, workspace_path=workspace_path)
    approval_status = _approval_status(approval)
    if approval_status != "approved":
        return {
            "status": "approval_required",
            "lifecycle_plan_path": _display_path(storage.root, plan_path),
            "approval_request": approval,
            "updated_assets": [],
            "created_assets": [],
            "rollback_plan": {},
            "mutation_applied": False,
            "reason": "MKAOS lifecycle transition requires approved ApprovalRequest",
        }
    if not bool(payload.get("confirm_apply")):
        return {
            "status": "ready_for_confirm",
            "lifecycle_plan_path": _display_path(storage.root, plan_path),
            "approval_request": approval,
            "updated_assets": [],
            "created_assets": [],
            "rollback_plan": {},
            "mutation_applied": False,
            "reason": "approved MKAOS lifecycle transition requires confirm_apply=true",
        }
    updated_assets, created_assets, rollback_actions, errors = _apply_lifecycle_transition(
        storage,
        plan,
        approval_path=str(approval.get("path") or payload.get("approval_request_path") or ""),
        actor=str(payload.get("actor") or "operator"),
    )
    rollback_plan = _write_lifecycle_rollback_plan(
        storage,
        plan,
        plan_path=_display_path(storage.root, plan_path),
        approval_path=str(approval.get("path") or payload.get("approval_request_path") or ""),
        actions=rollback_actions,
        project_id=project_id,
        workspace_path=workspace_path,
    )
    _record_lifecycle_apply_result(storage, plan_path, plan, approval_path=str(approval.get("path") or ""), rollback_plan_path=rollback_plan["path"], updated_assets=updated_assets, created_assets=created_assets, errors=errors)
    return {
        "status": "applied_with_errors" if errors else "applied",
        "lifecycle_plan_path": _display_path(storage.root, plan_path),
        "approval_request": approval,
        "updated_assets": updated_assets,
        "created_assets": created_assets,
        "rollback_plan": rollback_plan,
        "errors": errors,
        "mutation_applied": bool(updated_assets or created_assets),
        "dispatch_applied": False,
    }


def rollback_mkaos_asset_lifecycle(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    storage.ensure_layout()
    plan_path = resolve_path(storage.root, payload.get("rollback_plan_path") or payload.get("plan_path"))
    plan = storage.read_json(plan_path)
    if not isinstance(plan, dict) or plan.get("type") != "rollback_plan":
        raise ValueError("rollback_plan_path must point to a rollback_plan asset")
    content = plan.get("content", {}) if isinstance(plan.get("content", {}), dict) else {}
    if str(content.get("strategy") or "") != "restore_mkaos_lifecycle_transition":
        raise ValueError("rollback_plan_path must point to an MKAOS lifecycle rollback_plan")
    project_id = str(payload.get("project_id") or _asset_project_id(plan) or "")
    workspace_path = str(payload.get("workspace_path") or _asset_workspace_path(plan) or "")
    approval = _lifecycle_rollback_approval(storage, payload, plan_path, plan, project_id=project_id, workspace_path=workspace_path)
    approval_status = _approval_status(approval)
    if approval_status != "approved":
        return {
            "status": "approval_required",
            "rollback_plan_path": _display_path(storage.root, plan_path),
            "approval_request": approval,
            "applied_actions": [],
            "rollback_result": {},
            "rollback_applied": False,
            "reason": "MKAOS lifecycle rollback requires approved ApprovalRequest",
        }
    if not bool(payload.get("confirm_rollback")):
        return {
            "status": "ready_for_confirm",
            "rollback_plan_path": _display_path(storage.root, plan_path),
            "approval_request": approval,
            "applied_actions": [],
            "rollback_result": {},
            "rollback_applied": False,
            "reason": "approved MKAOS lifecycle rollback requires confirm_rollback=true",
        }
    applied_actions, errors = _apply_lifecycle_rollback_actions(storage, content.get("actions", []) if isinstance(content.get("actions", []), list) else [], actor=str(payload.get("actor") or "operator"))
    status = "failed" if errors else "applied"
    result = _write_lifecycle_rollback_result(
        storage,
        plan,
        plan_path=_display_path(storage.root, plan_path),
        status=status,
        applied_actions=applied_actions,
        errors=errors,
        approval_path=str(approval.get("path") or payload.get("approval_request_path") or ""),
        project_id=project_id,
        workspace_path=workspace_path,
    )
    content["rollback_status"] = status
    content["rollback_result_path"] = result["path"]
    content["rolled_back_at"] = utc_now()
    plan["content"] = content
    metadata = plan.get("metadata", {}) if isinstance(plan.get("metadata", {}), dict) else {}
    metadata["asset_status"] = status
    plan["metadata"] = metadata
    plan["updated_at"] = utc_now()
    errors_plan = validate_common_fields(plan)
    if errors_plan:
        raise ValueError("; ".join(errors_plan))
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


def _apply_lifecycle_transition(storage: LocalStorage, plan: dict[str, Any], *, approval_path: str, actor: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    content = plan.get("content", {}) if isinstance(plan.get("content", {}), dict) else {}
    transition = content.get("transition_plan", {}) if isinstance(content.get("transition_plan", {}), dict) else {}
    target_path, target = _resolve_mkaos_asset(storage, str(transition.get("target_path") or content.get("target_path") or transition.get("target_ref") or ""))
    target_type = str(target.get("type") or "")
    requested_state = str(transition.get("to_state") or content.get("requested_state") or "")
    before_payload = _deepcopy_json(target)
    updated_assets: list[dict[str, Any]] = []
    created_assets: list[dict[str, Any]] = []
    rollback_actions: list[dict[str, Any]] = [
        {
            "action": "restore_asset_payload",
            "target_path": _display_path(storage.root, target_path),
            "target_asset_id": str(target.get("id") or ""),
            "before_payload": before_payload,
        }
    ]
    errors: list[str] = []
    try:
        if target_type == "knowledge_card_candidate" and requested_state == "approved":
            approved = mkaos_service.approve_knowledge_candidate(storage, _display_path(storage.root, target_path), {"project_id": content.get("project_id") or _asset_project_id(target), "actor": actor})
            created = approved.get("knowledge", {}) if isinstance(approved.get("knowledge", {}), dict) else {}
            _mark_candidate_lifecycle_metadata(storage, target_path, requested_state, approval_path, actor)
            if created.get("path"):
                _mark_created_lifecycle_asset(storage, created["path"], approval_path, actor)
                created_assets.append({"path": created["path"], "asset_id": created.get("asset", {}).get("id", ""), "asset_type": "knowledge_card"})
                rollback_actions.append({"action": "mark_created_asset_superseded", "target_path": created["path"], "target_asset_id": created.get("asset", {}).get("id", "")})
        elif target_type == "mkaos_model_extraction_candidate" and requested_state == "approved":
            approved = mkaos_model_extraction.approve_candidate(storage, str(target.get("id") or ""), {"project_id": content.get("project_id") or _asset_project_id(target), "actor": actor})
            _mark_candidate_lifecycle_metadata(storage, target_path, requested_state, approval_path, actor)
            created = approved.get("knowledge_card", {}) if isinstance(approved.get("knowledge_card", {}), dict) else {}
            if created.get("path"):
                _mark_created_lifecycle_asset(storage, created["path"], approval_path, actor)
                created_assets.append({"path": created["path"], "asset_id": created.get("asset", {}).get("id", ""), "asset_type": "knowledge_card"})
                rollback_actions.append({"action": "mark_created_asset_superseded", "target_path": created["path"], "target_asset_id": created.get("asset", {}).get("id", "")})
        else:
            _apply_state_to_existing_asset(storage, target_path, requested_state, approval_path=approval_path, actor=actor)
        updated = storage.read_json(target_path)
        updated_assets.append({"path": _display_path(storage.root, target_path), "asset_id": str(updated.get("id") or ""), "asset_type": target_type, "state": _asset_state(updated)})
    except (OSError, TypeError, ValueError) as exc:
        errors.append(f"{_display_path(storage.root, target_path)}: {exc}")
    return updated_assets, created_assets, rollback_actions, errors


def _apply_state_to_existing_asset(storage: LocalStorage, target_path: Path, requested_state: str, *, approval_path: str, actor: str) -> None:
    data = storage.read_json(target_path)
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    content["status"] = requested_state
    metadata["asset_status"] = requested_state
    metadata["mkaos_lifecycle_state"] = requested_state
    metadata["mkaos_lifecycle_approval_request_path"] = approval_path
    metadata["mkaos_lifecycle_applied_at"] = utc_now()
    metadata["mkaos_lifecycle_applied_by"] = actor
    metadata["mkaos_lifecycle_content_rewrite"] = False
    if requested_state in DO_NOT_SELECT_STATES or requested_state == "needs_review":
        metadata["use_in_generation_rag"] = False
    if data.get("type") in {"rule_card", "template_card", "writing_template", "review_rule_pack"} and requested_state in DO_NOT_SELECT_STATES:
        content["enabled"] = False
    data["content"] = content
    data["metadata"] = metadata
    data["updated_at"] = utc_now()
    validation_errors = validate_common_fields(data)
    if validation_errors:
        raise ValueError("; ".join(validation_errors))
    storage.write_json(target_path, data)


def _mark_candidate_lifecycle_metadata(storage: LocalStorage, target_path: Path, state: str, approval_path: str, actor: str) -> None:
    data = storage.read_json(target_path)
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    content["status"] = state
    metadata["asset_status"] = state
    metadata["mkaos_lifecycle_state"] = state
    metadata["mkaos_lifecycle_approval_request_path"] = approval_path
    metadata["mkaos_lifecycle_applied_at"] = utc_now()
    metadata["mkaos_lifecycle_applied_by"] = actor
    metadata["use_in_generation_rag"] = False
    data["content"] = content
    data["metadata"] = metadata
    data["updated_at"] = utc_now()
    validation_errors = validate_common_fields(data)
    if validation_errors:
        raise ValueError("; ".join(validation_errors))
    storage.write_json(target_path, data)


def _mark_created_lifecycle_asset(storage: LocalStorage, path_ref: str, approval_path: str, actor: str) -> None:
    path, data = _resolve_asset_by_ref(storage, path_ref)
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    metadata["mkaos_lifecycle_created_by_transition"] = True
    metadata["mkaos_lifecycle_approval_request_path"] = approval_path
    metadata["mkaos_lifecycle_created_by"] = actor
    data["metadata"] = metadata
    data["updated_at"] = utc_now()
    validation_errors = validate_common_fields(data)
    if validation_errors:
        raise ValueError("; ".join(validation_errors))
    storage.write_json(path, data)


def _apply_lifecycle_rollback_actions(storage: LocalStorage, actions: list[dict[str, Any]], *, actor: str) -> tuple[list[dict[str, Any]], list[str]]:
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
            if action_type == "restore_asset_payload":
                before_payload = action.get("before_payload") if isinstance(action.get("before_payload"), dict) else {}
                if not before_payload:
                    raise ValueError("rollback action missing before_payload")
                restored = _deepcopy_json(before_payload)
                metadata = restored.get("metadata", {}) if isinstance(restored.get("metadata", {}), dict) else {}
                metadata["mkaos_lifecycle_rollback_at"] = utc_now()
                metadata["mkaos_lifecycle_rollback_actor"] = actor
                restored["metadata"] = metadata
                restored["updated_at"] = utc_now()
                validation_errors = validate_common_fields(restored)
                if validation_errors:
                    raise ValueError("; ".join(validation_errors))
                storage.write_json(path, restored)
            elif action_type == "mark_created_asset_superseded":
                metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
                content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
                metadata["asset_status"] = "superseded_by_lifecycle_rollback"
                metadata["use_in_generation_rag"] = False
                metadata["mkaos_lifecycle_rollback_at"] = utc_now()
                metadata["mkaos_lifecycle_rollback_actor"] = actor
                content["status"] = "superseded_by_lifecycle_rollback"
                data["content"] = content
                data["metadata"] = metadata
                data["updated_at"] = utc_now()
                validation_errors = validate_common_fields(data)
                if validation_errors:
                    raise ValueError("; ".join(validation_errors))
                storage.write_json(path, data)
            else:
                raise ValueError(f"unsupported lifecycle rollback action: {action_type}")
            applied.append({"action": action_type, "target_path": _display_path(storage.root, path), "status": "applied"})
        except (OSError, TypeError, ValueError) as exc:
            errors.append(f"{path_ref}: {exc}")
    return applied, errors


def _lifecycle_apply_approval(storage: LocalStorage, payload: dict[str, Any], plan_path: Path, plan: dict[str, Any], *, project_id: str, workspace_path: str) -> dict[str, Any]:
    approval_ref = str(payload.get("approval_request_path") or payload.get("approval_request_ref") or "").strip()
    if approval_ref:
        approval = _read_approval_request(storage, approval_ref)
        if approval:
            return approval
    from novel_forge.modules.permission_center import create_approval_request

    content = plan.get("content", {}) if isinstance(plan.get("content", {}), dict) else {}
    plan_ref = _display_path(storage.root, plan_path)
    return create_approval_request(
        storage,
        {
            "project_id": project_id,
            "workspace_path": workspace_path,
            "scope": "context",
            "action": "approve_mkaos_asset_lifecycle_apply",
            "environment": str(payload.get("environment") or "local"),
            "risk_level": "high" if content.get("requested_state") in DO_NOT_SELECT_STATES else "medium",
            "blocking": True,
            "target_type": "change_impact_report",
            "target_id": _short_token("mkaos-lifecycle", str(plan.get("id") or "")),
            "target_path": plan_ref,
            "target_refs": [str(content.get("target_path") or "")],
            "evidence_refs": [plan_ref, *_strings(payload.get("evidence_refs"))],
            "reason": "Apply MKAOS asset lifecycle transition",
            "required_before": ["mkaos_lifecycle_transition"],
            "rollback_plan": {"available": True, "strategy": "restore_mkaos_lifecycle_transition", "requires_operator_review": True},
        },
    )


def _lifecycle_rollback_approval(storage: LocalStorage, payload: dict[str, Any], plan_path: Path, plan: dict[str, Any], *, project_id: str, workspace_path: str) -> dict[str, Any]:
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
            "scope": "context",
            "action": "approve_mkaos_asset_lifecycle_rollback",
            "environment": str(payload.get("environment") or "local"),
            "risk_level": "high" if target_refs else "medium",
            "blocking": True,
            "target_type": "rollback_plan",
            "target_id": _short_token("mkaos-lifecycle-rollback", str(plan.get("id") or "")),
            "target_path": plan_ref,
            "target_refs": target_refs,
            "evidence_refs": [plan_ref, str(content.get("lifecycle_plan_path") or ""), *_strings(payload.get("evidence_refs"))],
            "reason": "Rollback MKAOS asset lifecycle transition",
            "required_before": ["mkaos_lifecycle_rollback"],
            "rollback_plan": {"available": False, "strategy": "manual_reapply_mkaos_lifecycle_transition_if_needed", "requires_operator_review": True},
        },
    )


def _write_lifecycle_rollback_plan(storage: LocalStorage, plan: dict[str, Any], *, plan_path: str, approval_path: str, actions: list[dict[str, Any]], project_id: str, workspace_path: str) -> dict[str, Any]:
    plan_id = make_id("rollback_plan", _short_token("mkaos-lifecycle", f"{plan.get('id', '')}:{utc_now()}"))
    transaction_id = make_id("mkaos_lifecycle", _short_token("mkaos-lifecycle-tx", f"{plan.get('id', '')}:{approval_path}:{utc_now()}"))
    content = {
        "plan_id": plan_id,
        "transaction_id": transaction_id,
        "strategy": "restore_mkaos_lifecycle_transition",
        "actions": actions,
        "rollback_status": "available" if actions else "not_required",
        "created_at": utc_now(),
        "lifecycle_plan_path": plan_path,
        "approval_request_path": approval_path,
        "raw_source_text_included": False,
        "prose_mutation_included": False,
        "requires_operator_review": True,
    }
    asset = RollbackPlan(
        id=plan_id,
        title=f"Rollback MKAOS lifecycle {plan.get('id', '')}",
        source=str(plan.get("id") or ""),
        tags=["mkaos", "lifecycle", "rollback-plan", content["rollback_status"]],
        content=content,
        metadata={"project_id": project_id, "workspace_path": workspace_path, "asset_status": content["rollback_status"], "use_in_generation_rag": False},
        references=[plan_path, approval_path, *[str(action.get("target_path") or "") for action in actions]],
    )
    data = asset.to_dict()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path)}


def _write_lifecycle_rollback_result(storage: LocalStorage, plan: dict[str, Any], *, plan_path: str, status: str, applied_actions: list[dict[str, Any]], errors: list[str], approval_path: str, project_id: str, workspace_path: str) -> dict[str, Any]:
    content = plan.get("content", {}) if isinstance(plan.get("content", {}), dict) else {}
    result_id = make_id("rollback_result", _short_token("mkaos-lifecycle-result", f"{content.get('plan_id', plan.get('id', ''))}:{status}:{utc_now()}"))
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
        title=f"MKAOS lifecycle rollback {status}",
        source=str(content.get("plan_id") or plan.get("id") or ""),
        tags=["mkaos", "lifecycle", "rollback-result", status],
        content=result_content,
        metadata={"project_id": project_id, "workspace_path": workspace_path, "asset_status": status, "use_in_generation_rag": False},
        references=[plan_path, approval_path, *[str(item.get("target_path") or "") for item in applied_actions]],
    )
    data = asset.to_dict()
    validation_errors = validate_common_fields(data)
    if validation_errors:
        raise ValueError("; ".join(validation_errors))
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path)}


def _record_lifecycle_apply_result(storage: LocalStorage, plan_path: Path, plan: dict[str, Any], *, approval_path: str, rollback_plan_path: str, updated_assets: list[dict[str, Any]], created_assets: list[dict[str, Any]], errors: list[str]) -> None:
    content = plan.get("content", {}) if isinstance(plan.get("content", {}), dict) else {}
    content["lifecycle_apply_result"] = {
        "status": "applied_with_errors" if errors else "applied",
        "approval_request_path": approval_path,
        "updated_assets": updated_assets,
        "created_assets": created_assets,
        "rollback_plan_path": rollback_plan_path,
        "errors": errors,
        "raw_source_text_included": False,
        "prose_mutation_included": False,
        "dispatch_applied": False,
        "applied_at": utc_now(),
    }
    plan["content"] = content
    metadata = plan.get("metadata", {}) if isinstance(plan.get("metadata", {}), dict) else {}
    metadata["asset_status"] = "applied_with_errors" if errors else "applied"
    metadata["mkaos_lifecycle_apply_status"] = metadata["asset_status"]
    plan["metadata"] = metadata
    plan["updated_at"] = utc_now()
    validation_errors = validate_common_fields(plan)
    if validation_errors:
        raise ValueError("; ".join(validation_errors))
    storage.write_json(plan_path, plan)


def _resolve_lifecycle_plan(storage: LocalStorage, ref: Any) -> tuple[Path, dict[str, Any]]:
    path, data = _resolve_asset_by_ref(storage, str(ref or ""))
    if not isinstance(data, dict) or data.get("type") != "change_impact_report":
        raise ValueError("lifecycle_plan_path must point to a change_impact_report")
    tags = {str(tag) for tag in data.get("tags", []) if str(tag)}
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    contract = content.get("lifecycle_contract", {}) if isinstance(content.get("lifecycle_contract", {}), dict) else {}
    if MKAOS_LIFECYCLE_REPORT_TAG not in tags and str(contract.get("contract_version") or "") != "mkaos-asset-lifecycle-v1":
        raise ValueError("lifecycle_plan_path must point to an MKAOS lifecycle plan")
    return path, data


def _resolve_mkaos_asset(storage: LocalStorage, ref: str) -> tuple[Path, dict[str, Any]]:
    path, data = _resolve_asset_by_ref(storage, ref)
    if str(data.get("type") or "") not in VALID_TRANSITIONS:
        raise ValueError("target_ref must point to a supported MKAOS lifecycle asset")
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
            if text in {str(data.get("id") or ""), str(content.get("report_id") or ""), str(content.get("candidate_id") or ""), str(content.get("transition_id") or ""), _display_path(storage.root, path)}:
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


def _asset_state(asset: dict[str, Any]) -> str:
    content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
    metadata = asset.get("metadata", {}) if isinstance(asset.get("metadata", {}), dict) else {}
    if content.get("status") or metadata.get("asset_status"):
        return _normalize_state(str(content.get("status") or metadata.get("asset_status") or "needs_review"))
    if asset.get("type") in {"rule_card", "template_card", "writing_template", "review_rule_pack"} and content.get("enabled") is True:
        return "enabled"
    return "needs_review"


def _normalize_state(value: str) -> str:
    text = str(value or "").strip().lower()
    if text in {"active", "verified", "needs_review", "approved", "rejected", "quarantined", "deprecated", "do_not_select", "pending"}:
        return text
    return text


def _transition_valid(asset_type: str, current_state: str, requested_state: str) -> bool:
    allowed = VALID_TRANSITIONS.get(asset_type, {}).get(current_state)
    if allowed is None and current_state == "approved" and asset_type == "knowledge_card":
        allowed = VALID_TRANSITIONS["knowledge_card"]["active"]
    return requested_state in (allowed or set())


def _context_exclusion_for_transition(asset_type: str, requested_state: str) -> dict[str, Any]:
    return {
        "target_asset_type": asset_type,
        "requested_state": requested_state,
        "exclude_target_from_generation_context": requested_state in DO_NOT_SELECT_STATES or asset_type != "knowledge_card",
        "candidate_assets_never_enter_generation_context": asset_type in {"knowledge_card_candidate", "mkaos_model_extraction_candidate"},
        "raw_source_text_included": False,
    }


def _asset_project_id(asset: dict[str, Any]) -> str:
    metadata = asset.get("metadata", {}) if isinstance(asset.get("metadata", {}), dict) else {}
    content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
    return str(metadata.get("project_id") or content.get("project_id") or "")


def _asset_workspace_path(asset: dict[str, Any]) -> str:
    metadata = asset.get("metadata", {}) if isinstance(asset.get("metadata", {}), dict) else {}
    content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
    return str(metadata.get("workspace_path") or content.get("workspace_path") or "")


def _display_path(root: Path, path: str | Path) -> str:
    candidate = Path(path)
    try:
        return str(candidate.relative_to(root))
    except ValueError:
        return str(candidate)


def _strings(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _deepcopy_json(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _short_token(prefix: str, value: str) -> str:
    text = str(value or "")
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"
