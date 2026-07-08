from __future__ import annotations

from hashlib import sha1
from pathlib import Path
from typing import Any

from novel_forge.core.constants import DATA_DIRS
from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.schemas import (
    BaseAsset,
    MKAOSSelectorGovernanceBindingApplicationReport,
    MKAOSSelectorGovernanceBindingProposal,
    RollbackPlan,
    RollbackResult,
    validate_common_fields,
)
from novel_forge.storage.local import LocalStorage

DO_NOT_SELECT_STATES = {"quarantined", "deprecated", "do_not_select", "rejected", "superseded_by_lifecycle_rollback"}


def refresh_mkaos_selector_governance(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    storage.ensure_layout()
    project_id = str(payload.get("project_id") or "")
    max_assets = max(1, int(payload.get("max_assets") or 1000))
    adjustments: dict[str, dict[str, Any]] = {}
    exclusions: dict[str, dict[str, Any]] = {}
    scanned = 0
    for path in storage.list_json("knowledge"):
        if scanned >= max_assets:
            break
        try:
            data = storage.read_json(path)
        except (OSError, TypeError, ValueError):
            continue
        if not isinstance(data, dict) or data.get("type") != "knowledge_card":
            continue
        if project_id and _asset_project_id(data) not in {"", project_id}:
            continue
        scanned += 1
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        knowledge_id = str(data.get("id") or "")
        if not knowledge_id:
            continue
        base_weight = _float(content.get("weight", metadata.get("weight", 1.0)), 1.0)
        delta = _float(metadata.get("mkaos_governance_weight_delta", metadata.get("selector_governance_weight_delta", 0.0)), 0.0)
        state = str(content.get("status") or metadata.get("asset_status") or "")
        lifecycle_state = str(metadata.get("mkaos_lifecycle_state") or "")
        excluded, reason = _selector_exclusion(metadata, state=state, lifecycle_state=lifecycle_state)
        evidence_refs = _evidence_refs(metadata)
        if delta != 0.0 or metadata.get("mkaos_governance_application_status") or metadata.get("mkaos_lifecycle_state"):
            adjustments[knowledge_id] = {
                "knowledge_id": knowledge_id,
                "path": _display_path(storage.root, path),
                "base_weight": base_weight,
                "weight_delta": delta,
                "effective_weight": max(0.0, base_weight + delta),
                "governance_action": str(metadata.get("mkaos_governance_action") or ""),
                "lifecycle_state": lifecycle_state,
                "evidence_refs": evidence_refs,
                "content_weight_mutated": False,
            }
        if excluded:
            exclusions[knowledge_id] = {
                "knowledge_id": knowledge_id,
                "path": _display_path(storage.root, path),
                "reason": reason,
                "state": state,
                "lifecycle_state": lifecycle_state,
                "evidence_refs": evidence_refs,
            }
    report_id = make_id("mkaos_selector_governance_report", f"{project_id or 'all'}-{utc_now()}")
    content = {
        "selector_governance_report_id": report_id,
        "project_id": project_id,
        "scanned_knowledge_count": scanned,
        "adjustments": adjustments,
        "exclusions": exclusions,
        "selector_policy_patch": {
            "weight_overrides": {knowledge_id: item["effective_weight"] for knowledge_id, item in adjustments.items()},
            "excluded_knowledge_ids": sorted(exclusions),
            "evidence_by_knowledge_id": {knowledge_id: item.get("evidence_refs", []) for knowledge_id, item in {**adjustments, **exclusions}.items()},
        },
        "refresh_contract": {
            "contract_version": "mkaos-selector-governance-refresh-v1",
            "content_weight_mutation_allowed": False,
            "selector_application_requires_explicit_report_ref": True,
            "raw_source_text_included": False,
            "prose_mutation_included": False,
        },
        "generated_at": utc_now(),
    }
    asset = BaseAsset(
        id=report_id,
        type="mkaos_selector_governance_report",
        title="MKAOS selector governance refresh",
        source="mkaos-selector-governance",
        tags=["mkaos", "selector-governance", "refresh"],
        content=content,
        metadata={"project_id": project_id, "asset_status": "active", "use_in_generation_rag": False, "selector_governance_report": True},
        references=sorted({ref for item in [*adjustments.values(), *exclusions.values()] for ref in item.get("evidence_refs", []) if ref}),
    )
    data = asset.to_dict()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset("runs", asset)
    return {"status": "refreshed", "path": _display_path(storage.root, path), "asset": storage.read_json(path), "adjustment_count": len(adjustments), "exclusion_count": len(exclusions)}


def load_selector_governance_policy(storage: LocalStorage, payload: dict[str, Any], *, project_id: str) -> dict[str, Any]:
    ref = str(payload.get("selector_governance_report_path") or payload.get("selector_governance_report_ref") or "").strip()
    if not ref and bool(payload.get("use_latest_selector_governance")):
        latest = _latest_selector_governance_report(storage, project_id=project_id)
        ref = latest.get("path", "")
    if not ref:
        return {}
    path, data = _resolve_selector_report(storage, ref)
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    return {
        "report_id": str(data.get("id") or content.get("selector_governance_report_id") or ""),
        "report_path": _display_path(storage.root, path),
        "weight_overrides": content.get("selector_policy_patch", {}).get("weight_overrides", {}) if isinstance(content.get("selector_policy_patch", {}), dict) else {},
        "excluded_knowledge_ids": content.get("selector_policy_patch", {}).get("excluded_knowledge_ids", []) if isinstance(content.get("selector_policy_patch", {}), dict) else [],
        "evidence_by_knowledge_id": content.get("selector_policy_patch", {}).get("evidence_by_knowledge_id", {}) if isinstance(content.get("selector_policy_patch", {}), dict) else {},
        "adjustments": content.get("adjustments", {}) if isinstance(content.get("adjustments", {}), dict) else {},
        "exclusions": content.get("exclusions", {}) if isinstance(content.get("exclusions", {}), dict) else {},
    }


def diff_mkaos_selector_governance(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    storage.ensure_layout()
    project_id = str(payload.get("project_id") or "")
    base_ref = str(payload.get("base_report_path") or payload.get("old_report_path") or payload.get("selector_governance_report_path") or "").strip()
    compare_ref = str(payload.get("compare_report_path") or payload.get("new_report_path") or "").strip()
    pack_ref = str(payload.get("knowledge_pack_path") or payload.get("knowledge_pack_ref") or payload.get("selector_decision_path") or "").strip()
    if not base_ref:
        raise ValueError("base_report_path or selector_governance_report_path is required")
    base_path, base_report = _resolve_selector_report(storage, base_ref)
    compare_report: dict[str, Any] = {}
    compare_path = Path("")
    pack: dict[str, Any] = {}
    pack_path = Path("")
    if compare_ref:
        compare_path, compare_report = _resolve_selector_report(storage, compare_ref)
    if pack_ref:
        pack_path, pack = _resolve_pack_or_selector_decision(storage, pack_ref)
    if not compare_report and not pack:
        raise ValueError("compare_report_path or knowledge_pack_path/selector_decision_path is required")

    base_policy = _selector_policy_patch(base_report)
    compare_policy = _selector_policy_patch(compare_report) if compare_report else {}
    report_diff = _diff_selector_policies(base_policy, compare_policy) if compare_report else {}
    pack_diff = _diff_selector_policy_against_pack(base_policy if not compare_report else compare_policy, pack) if pack else {}
    diff_id = make_id("mkaos_selector_governance_diff_report", f"{project_id or 'all'}-{utc_now()}")
    content = {
        "selector_governance_diff_report_id": diff_id,
        "project_id": project_id or _asset_project_id(base_report) or _asset_project_id(compare_report) or _asset_project_id(pack),
        "base_report_path": _display_path(storage.root, base_path),
        "compare_report_path": _display_path(storage.root, compare_path) if compare_report else "",
        "knowledge_pack_or_selector_path": _display_path(storage.root, pack_path) if pack else "",
        "report_diff": report_diff,
        "pack_diff": pack_diff,
        "summary": {
            "weight_changed_count": len(report_diff.get("weight_changed", [])) if report_diff else 0,
            "exclusion_added_count": len(report_diff.get("exclusions_added", [])) if report_diff else 0,
            "exclusion_removed_count": len(report_diff.get("exclusions_removed", [])) if report_diff else 0,
            "selected_now_excluded_count": len(pack_diff.get("selected_now_excluded", [])) if pack_diff else 0,
            "selected_weight_changed_count": len(pack_diff.get("selected_weight_changed", [])) if pack_diff else 0,
        },
        "diff_contract": {
            "contract_version": "mkaos-selector-governance-diff-v1",
            "mutation_applied": False,
            "adoption_applied": False,
            "raw_source_text_included": False,
            "prose_mutation_included": False,
        },
        "generated_at": utc_now(),
    }
    asset = BaseAsset(
        id=diff_id,
        type="mkaos_selector_governance_diff_report",
        title="MKAOS selector governance diff",
        source=str(base_report.get("id") or ""),
        tags=["mkaos", "selector-governance", "diff"],
        content=content,
        metadata={"project_id": content["project_id"], "asset_status": "reviewable", "use_in_generation_rag": False},
        references=[_display_path(storage.root, base_path), _display_path(storage.root, compare_path) if compare_report else "", _display_path(storage.root, pack_path) if pack else ""],
    )
    data = asset.to_dict()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset("runs", asset)
    return {"status": "diffed", "path": _display_path(storage.root, path), "asset": storage.read_json(path), **content["summary"]}


def propose_context_governance_binding(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    """Create a reviewable proposal for binding selector governance into a context build.

    This does not mutate Context Builder behavior. Adoption remains explicit through
    selector_governance_report_path after operator approval.
    """
    storage.ensure_layout()
    project_id = str(payload.get("project_id") or "")
    workspace_path = str(payload.get("workspace_path") or "")
    environment = str(payload.get("environment") or "local")
    report_ref = str(payload.get("selector_governance_report_path") or payload.get("selector_governance_report_ref") or "").strip()
    if not report_ref:
        latest = _latest_selector_governance_report(storage, project_id=project_id)
        report_ref = str(latest.get("path") or "")
    if not report_ref:
        raise ValueError("selector_governance_report_path is required when no latest report exists")
    report_path, report = _resolve_selector_report(storage, report_ref)
    report_project_id = _asset_project_id(report)
    if project_id and report_project_id and report_project_id != project_id:
        raise ValueError("selector_governance_report_path project_id does not match payload project_id")
    effective_project_id = project_id or report_project_id
    report_display_path = _display_path(storage.root, report_path)
    previous_ref = str(payload.get("knowledge_pack_path") or payload.get("knowledge_pack_ref") or payload.get("selector_decision_path") or "").strip()
    previous_path = ""
    if previous_ref:
        resolved_previous_path, _previous = _resolve_pack_or_selector_decision(storage, previous_ref)
        previous_path = _display_path(storage.root, resolved_previous_path)

    base_ref = str(payload.get("base_report_path") or payload.get("old_report_path") or "").strip()
    diff_report: dict[str, Any] = {}
    needs_report_diff = bool(base_ref and not _same_report_ref(report, report_display_path, base_ref))
    if needs_report_diff or previous_path:
        diff_payload: dict[str, Any] = {"project_id": effective_project_id, "base_report_path": base_ref or report_display_path}
        if needs_report_diff:
            diff_payload["compare_report_path"] = report_display_path
        if previous_path:
            diff_payload["knowledge_pack_path"] = previous_path
        diff_report = diff_mkaos_selector_governance(storage, diff_payload)

    report_content = report.get("content", {}) if isinstance(report.get("content", {}), dict) else {}
    diff_content = diff_report.get("asset", {}).get("content", {}) if isinstance(diff_report.get("asset", {}).get("content", {}), dict) else {}
    binding_id = make_id("mkaos_selector_governance_binding_proposal", f"{effective_project_id or 'all'}-{utc_now()}")
    report_patch = report_content.get("selector_policy_patch", {}) if isinstance(report_content.get("selector_policy_patch", {}), dict) else {}
    content = {
        "binding_proposal_id": binding_id,
        "project_id": effective_project_id,
        "status": "needs_approval",
        "binding_scope": str(payload.get("binding_scope") or "context_builder"),
        "target_stage": str(payload.get("target_stage") or payload.get("stage") or ""),
        "selector_governance_report_id": str(report.get("id") or report_content.get("selector_governance_report_id") or ""),
        "selector_governance_report_path": report_display_path,
        "previous_context_evidence_path": previous_path,
        "base_report_path": str(base_ref or ""),
        "diff_report_path": str(diff_report.get("path") or ""),
        "approval_request_path": "",
        "agent_task_path": "",
        "recommended_context_builder_payload_patch": {
            "selector_governance_report_path": report_display_path,
            "use_latest_selector_governance": False,
            "selector_governance_binding_proposal_id": binding_id,
        },
        "selector_policy_patch_summary": {
            "weight_override_count": len(report_patch.get("weight_overrides", {}) if isinstance(report_patch.get("weight_overrides", {}), dict) else {}),
            "excluded_knowledge_count": len(_strings(report_patch.get("excluded_knowledge_ids"))),
            "evidence_count": len(report_patch.get("evidence_by_knowledge_id", {}) if isinstance(report_patch.get("evidence_by_knowledge_id", {}), dict) else {}),
        },
        "risk_summary": {
            "diff_summary": diff_content.get("summary", {}) if isinstance(diff_content.get("summary", {}), dict) else {},
            "requires_operator_approval": True,
            "selected_now_excluded_count": _int(diff_content.get("summary", {}).get("selected_now_excluded_count") if isinstance(diff_content.get("summary", {}), dict) else 0, 0),
            "production_auto_adoption_allowed": False,
        },
        "binding_contract": {
            "contract_version": "context-governance-binding-proposal-v1",
            "mutation_applied": False,
            "adoption_applied": False,
            "context_build_executed": False,
            "approval_required_before_adoption": True,
            "explicit_selector_governance_report_path_required": True,
            "raw_source_text_included": False,
            "prose_mutation_included": False,
        },
        "forbidden_automatic_actions": [
            "do_not_auto_pass_selector_governance_report_path",
            "do_not_mutate_context_bundle",
            "do_not_mutate_knowledge_card_content_weight",
            "do_not_dispatch_agent_task_without_operator_approval",
        ],
        "generated_at": utc_now(),
    }
    proposal = MKAOSSelectorGovernanceBindingProposal(
        id=binding_id,
        title="MKAOS selector governance context binding proposal",
        source=str(report.get("id") or ""),
        tags=["mkaos", "selector-governance", "context-binding", "needs-approval"],
        content=content,
        metadata={
            "project_id": effective_project_id,
            "workspace_path": workspace_path,
            "asset_status": "needs_approval",
            "use_in_generation_rag": False,
            "mutation_applied": False,
            "adoption_applied": False,
        },
        references=_dedupe([report_display_path, previous_path, str(diff_report.get("path") or "")]),
    )
    data = proposal.to_dict()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    proposal_path = storage.write_asset("runs", proposal)
    proposal_display_path = _display_path(storage.root, proposal_path)
    approval = _create_binding_approval_request(
        storage,
        payload,
        project_id=effective_project_id,
        workspace_path=workspace_path,
        environment=environment,
        proposal_id=binding_id,
        proposal_path=proposal_display_path,
        evidence_refs=_dedupe([report_display_path, previous_path, str(diff_report.get("path") or "")]),
    )
    agent_task = _create_binding_agent_task(
        storage,
        project_id=effective_project_id,
        workspace_path=workspace_path,
        proposal_path=proposal_display_path,
        report_path=report_display_path,
        previous_path=previous_path,
        diff_path=str(diff_report.get("path") or ""),
        approval_path=str(approval.get("path") or ""),
        recommended_patch=content["recommended_context_builder_payload_patch"],
    )
    updated = _update_binding_proposal_links(storage, proposal_display_path, approval, agent_task)
    return {
        "status": "proposed",
        "path": updated["path"],
        "asset": updated["asset"],
        "approval_request": approval,
        "agent_task": agent_task,
        "diff_report": diff_report,
    }


def apply_context_governance_binding(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    storage.ensure_layout()
    proposal_path, proposal = _resolve_binding_proposal(storage, payload.get("binding_proposal_path") or payload.get("proposal_path") or payload.get("binding_proposal_ref"))
    content = proposal.get("content", {}) if isinstance(proposal.get("content", {}), dict) else {}
    project_id = str(payload.get("project_id") or _asset_project_id(proposal) or "")
    workspace_path = str(payload.get("workspace_path") or _metadata_value(proposal, "workspace_path") or "")
    existing_application = _existing_binding_application(storage, content)
    if existing_application and not bool(payload.get("force_reapply")):
        return {
            "status": "already_applied",
            "binding_proposal_path": _display_path(storage.root, proposal_path),
            "approval_request": _read_approval_request(storage, str(content.get("approval_request_path") or "")),
            "application_report": existing_application,
            "rollback_plan": _existing_rollback_plan(storage, existing_application.get("asset", {})),
            "agent_task_update": {},
            "context_builder_payload_patch": existing_application["asset"]["content"]["context_builder_payload_patch"],
            "applied": True,
        }
    approval = _binding_apply_approval(storage, payload, proposal_path, proposal, project_id=project_id, workspace_path=workspace_path)
    approval_status = _approval_status(approval)
    proposal_display_path = _display_path(storage.root, proposal_path)
    if approval_status != "approved":
        return {
            "status": "approval_required",
            "binding_proposal_path": proposal_display_path,
            "approval_request": approval,
            "application_report": {},
            "rollback_plan": {},
            "applied": False,
            "reason": "context governance binding apply requires approved ApprovalRequest",
        }
    if not bool(payload.get("confirm_apply")):
        return {
            "status": "ready_for_confirm",
            "binding_proposal_path": proposal_display_path,
            "approval_request": approval,
            "application_report": {},
            "rollback_plan": {},
            "applied": False,
            "reason": "approved context governance binding requires confirm_apply=true",
        }

    task_update, task_rollback_action = _mark_binding_agent_task_dispatch_ready(
        storage,
        str(content.get("agent_task_path") or ""),
        approval_path=str(approval.get("path") or payload.get("approval_request_path") or payload.get("approval_request_ref") or ""),
    )
    application = _write_binding_application_report(
        storage,
        proposal,
        proposal_path=proposal_display_path,
        approval_path=str(approval.get("path") or ""),
        task_update=task_update,
        project_id=project_id,
        workspace_path=workspace_path,
    )
    rollback_actions = [
        action
        for action in [task_rollback_action, _binding_application_rollback_action(application), _binding_proposal_rollback_action(proposal, proposal_display_path)]
        if action
    ]
    rollback_plan = _write_binding_rollback_plan(
        storage,
        application["asset"],
        application_path=application["path"],
        approval_path=str(approval.get("path") or ""),
        actions=rollback_actions,
        project_id=project_id,
        workspace_path=workspace_path,
    )
    application = _update_binding_application_links(storage, application["path"], rollback_plan)
    _record_binding_apply_result(storage, proposal_path, proposal, approval_path=str(approval.get("path") or ""), application_path=application["path"], rollback_plan_path=rollback_plan["path"])
    return {
        "status": "applied",
        "binding_proposal_path": proposal_display_path,
        "approval_request": approval,
        "application_report": application,
        "rollback_plan": rollback_plan,
        "agent_task_update": task_update,
        "context_builder_payload_patch": application["asset"]["content"]["context_builder_payload_patch"],
        "applied": True,
    }


def rollback_context_governance_binding(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    storage.ensure_layout()
    plan_path = resolve_path(storage.root, payload.get("rollback_plan_path") or payload.get("plan_path"))
    plan = storage.read_json(plan_path)
    if not isinstance(plan, dict) or plan.get("type") != "rollback_plan":
        raise ValueError("rollback_plan_path must point to a rollback_plan asset")
    content = plan.get("content", {}) if isinstance(plan.get("content", {}), dict) else {}
    if str(content.get("strategy") or "") != "rollback_context_governance_binding_application":
        raise ValueError("rollback_plan_path must point to a context governance binding rollback_plan")
    project_id = str(payload.get("project_id") or _asset_project_id(plan) or "")
    workspace_path = str(payload.get("workspace_path") or _metadata_value(plan, "workspace_path") or "")
    approval = _binding_rollback_approval(storage, payload, plan_path, plan, project_id=project_id, workspace_path=workspace_path)
    approval_status = _approval_status(approval)
    plan_display_path = _display_path(storage.root, plan_path)
    if approval_status != "approved":
        return {
            "status": "approval_required",
            "rollback_plan_path": plan_display_path,
            "approval_request": approval,
            "applied_actions": [],
            "rollback_result": {},
            "rollback_applied": False,
            "reason": "context governance binding rollback requires approved ApprovalRequest",
        }
    if not bool(payload.get("confirm_rollback")):
        return {
            "status": "ready_for_confirm",
            "rollback_plan_path": plan_display_path,
            "approval_request": approval,
            "applied_actions": [],
            "rollback_result": {},
            "rollback_applied": False,
            "reason": "approved context governance binding rollback requires confirm_rollback=true",
        }
    applied_actions, errors = _apply_binding_rollback_actions(storage, content.get("actions", []) if isinstance(content.get("actions", []), list) else [], actor=str(payload.get("actor") or "operator"))
    status = "failed" if errors else "applied"
    result = _write_binding_rollback_result(
        storage,
        plan,
        plan_path=plan_display_path,
        approval_path=str(approval.get("path") or ""),
        status=status,
        applied_actions=applied_actions,
        errors=errors,
        project_id=project_id,
        workspace_path=workspace_path,
    )
    return {
        "status": status,
        "rollback_plan_path": plan_display_path,
        "approval_request": approval,
        "applied_actions": applied_actions,
        "rollback_result": result,
        "rollback_applied": status == "applied",
        "errors": errors,
    }


def load_context_governance_binding_application(storage: LocalStorage, ref: str | Path, *, project_id: str = "", environment: str = "") -> dict[str, Any]:
    path, data = _resolve_asset_by_ref(storage, str(ref or ""))
    if not isinstance(data, dict) or data.get("type") != "mkaos_selector_governance_binding_application_report":
        raise ValueError("selector_governance_binding_application_report_path must point to a binding application report")
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    status = str(content.get("status") or metadata.get("asset_status") or "")
    if status != "applied":
        raise ValueError(f"selector governance binding application must be applied, got {status or 'unknown'}")
    effective_project_id = str(project_id or "")
    application_project_id = _asset_project_id(data)
    if effective_project_id and application_project_id and effective_project_id != application_project_id:
        raise ValueError("selector governance binding application project_id does not match context build project_id")
    contract = content.get("application_contract", {}) if isinstance(content.get("application_contract", {}), dict) else {}
    if contract.get("context_build_executed") is not False or contract.get("context_bundle_mutated") is not False:
        raise ValueError("selector governance binding application contract is not payload-only")
    patch = content.get("context_builder_payload_patch", {}) if isinstance(content.get("context_builder_payload_patch", {}), dict) else {}
    report_ref = str(patch.get("selector_governance_report_path") or content.get("selector_governance_report_path") or "").strip()
    if not report_ref:
        raise ValueError("selector governance binding application missing selector_governance_report_path")
    report_path, report = _resolve_selector_report(storage, report_ref)
    report_project_id = _asset_project_id(report)
    if effective_project_id and report_project_id and effective_project_id != report_project_id:
        raise ValueError("selector governance report project_id does not match context build project_id")
    return {
        "application_report_id": str(content.get("binding_application_id") or data.get("id") or ""),
        "application_report_path": _display_path(storage.root, path),
        "binding_proposal_id": str(content.get("binding_proposal_id") or ""),
        "binding_proposal_path": str(content.get("binding_proposal_path") or ""),
        "selector_governance_report_id": str(report.get("id") or report.get("content", {}).get("selector_governance_report_id") or ""),
        "selector_governance_report_path": _display_path(storage.root, report_path),
        "approval_request_path": str(content.get("approval_request_path") or ""),
        "rollback_plan_path": str(content.get("rollback_plan_path") or ""),
        "context_builder_payload_patch": {**patch, "selector_governance_report_path": _display_path(storage.root, report_path)},
        "application_contract": contract,
        "environment": str(environment or ""),
        "status": status,
        "payload_only": True,
    }


def _resolve_selector_report(storage: LocalStorage, ref: str) -> tuple[Path, dict[str, Any]]:
    path, data = _resolve_asset_by_ref(storage, ref)
    if not isinstance(data, dict) or data.get("type") != "mkaos_selector_governance_report":
        raise ValueError("selector_governance_report_path must point to a mkaos_selector_governance_report")
    return path, data


def _resolve_pack_or_selector_decision(storage: LocalStorage, ref: str) -> tuple[Path, dict[str, Any]]:
    path, data = _resolve_asset_by_ref(storage, ref)
    if not isinstance(data, dict) or data.get("type") not in {"knowledge_pack", "selector_decision"}:
        raise ValueError("knowledge_pack_path or selector_decision_path must point to a knowledge_pack or selector_decision")
    return path, data


def _selector_policy_patch(report: dict[str, Any]) -> dict[str, Any]:
    content = report.get("content", {}) if isinstance(report.get("content", {}), dict) else {}
    patch = content.get("selector_policy_patch", {}) if isinstance(content.get("selector_policy_patch", {}), dict) else {}
    return {
        "weight_overrides": patch.get("weight_overrides", {}) if isinstance(patch.get("weight_overrides", {}), dict) else {},
        "excluded_knowledge_ids": set(_strings(patch.get("excluded_knowledge_ids"))),
        "evidence_by_knowledge_id": patch.get("evidence_by_knowledge_id", {}) if isinstance(patch.get("evidence_by_knowledge_id", {}), dict) else {},
    }


def _diff_selector_policies(base: dict[str, Any], compare: dict[str, Any]) -> dict[str, Any]:
    base_weights = base.get("weight_overrides", {}) if isinstance(base.get("weight_overrides", {}), dict) else {}
    compare_weights = compare.get("weight_overrides", {}) if isinstance(compare.get("weight_overrides", {}), dict) else {}
    all_weight_ids = sorted(set(base_weights) | set(compare_weights))
    weight_added = [knowledge_id for knowledge_id in all_weight_ids if knowledge_id not in base_weights and knowledge_id in compare_weights]
    weight_removed = [knowledge_id for knowledge_id in all_weight_ids if knowledge_id in base_weights and knowledge_id not in compare_weights]
    weight_changed = [
        {
            "knowledge_id": knowledge_id,
            "from": _float(base_weights.get(knowledge_id), 0.0),
            "to": _float(compare_weights.get(knowledge_id), 0.0),
        }
        for knowledge_id in all_weight_ids
        if knowledge_id in base_weights and knowledge_id in compare_weights and _float(base_weights.get(knowledge_id), 0.0) != _float(compare_weights.get(knowledge_id), 0.0)
    ]
    base_exclusions = base.get("excluded_knowledge_ids", set()) if isinstance(base.get("excluded_knowledge_ids", set()), set) else set(_strings(base.get("excluded_knowledge_ids")))
    compare_exclusions = compare.get("excluded_knowledge_ids", set()) if isinstance(compare.get("excluded_knowledge_ids", set()), set) else set(_strings(compare.get("excluded_knowledge_ids")))
    return {
        "weight_added": weight_added,
        "weight_removed": weight_removed,
        "weight_changed": weight_changed,
        "exclusions_added": sorted(compare_exclusions - base_exclusions),
        "exclusions_removed": sorted(base_exclusions - compare_exclusions),
        "mutation_applied": False,
    }


def _diff_selector_policy_against_pack(policy: dict[str, Any], pack: dict[str, Any]) -> dict[str, Any]:
    content = pack.get("content", {}) if isinstance(pack.get("content", {}), dict) else {}
    if pack.get("type") == "selector_decision":
        selected = content.get("selected_knowledge", []) if isinstance(content.get("selected_knowledge", []), list) else []
        rejected = content.get("rejected_knowledge", []) if isinstance(content.get("rejected_knowledge", []), list) else []
    else:
        selected = content.get("pack_items", []) if isinstance(content.get("pack_items", []), list) else []
        rejected = content.get("selector_rejections", []) if isinstance(content.get("selector_rejections", []), list) else []
    selected_ids = {str(item.get("knowledge_id") or "") for item in selected if isinstance(item, dict)}
    rejected_ids = {str(item.get("knowledge_id") or "") for item in rejected if isinstance(item, dict)}
    excluded = policy.get("excluded_knowledge_ids", set()) if isinstance(policy.get("excluded_knowledge_ids", set()), set) else set(_strings(policy.get("excluded_knowledge_ids")))
    weight_overrides = policy.get("weight_overrides", {}) if isinstance(policy.get("weight_overrides", {}), dict) else {}
    selected_weight_changed = []
    for item in selected:
        if not isinstance(item, dict):
            continue
        knowledge_id = str(item.get("knowledge_id") or "")
        if knowledge_id not in weight_overrides:
            continue
        current_weight = _float(item.get("selector_decision", {}).get("weight", item.get("weight", 0.0)) if isinstance(item.get("selector_decision", {}), dict) else item.get("weight", 0.0), 0.0)
        next_weight = _float(weight_overrides.get(knowledge_id), current_weight)
        if current_weight != next_weight:
            selected_weight_changed.append({"knowledge_id": knowledge_id, "from": current_weight, "to": next_weight})
    return {
        "selected_now_excluded": sorted(selected_ids & excluded),
        "rejected_now_allowed": sorted(rejected_ids - excluded),
        "selected_weight_changed": selected_weight_changed,
        "mutation_applied": False,
    }


def _latest_selector_governance_report(storage: LocalStorage, *, project_id: str) -> dict[str, Any]:
    for path in reversed(storage.list_json("runs")):
        try:
            data = storage.read_json(path)
        except (OSError, TypeError, ValueError):
            continue
        if not isinstance(data, dict) or data.get("type") != "mkaos_selector_governance_report":
            continue
        if project_id and _asset_project_id(data) not in {"", project_id}:
            continue
        return {"path": _display_path(storage.root, path), "asset": data}
    return {}


def _selector_exclusion(metadata: dict[str, Any], *, state: str, lifecycle_state: str) -> tuple[bool, str]:
    normalized_state = str(lifecycle_state or state or "").strip()
    if normalized_state in DO_NOT_SELECT_STATES:
        return True, f"state:{normalized_state}"
    governance_action = str(metadata.get("mkaos_governance_action") or metadata.get("selector_governance_action") or "")
    if governance_action in {"quarantine", "deprecate", "do_not_select", "reject"}:
        return True, f"governance_action:{governance_action}"
    if metadata.get("selector_governance_excluded") is True:
        return True, "selector_governance_excluded"
    return False, ""


def _evidence_refs(metadata: dict[str, Any]) -> list[str]:
    refs = [
        str(metadata.get("mkaos_governance_report_path") or ""),
        str(metadata.get("mkaos_governance_approval_request_path") or ""),
        str(metadata.get("mkaos_lifecycle_approval_request_path") or ""),
    ]
    return [ref for ref in refs if ref]


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
            if text in {
                str(data.get("id") or ""),
                str(content.get("selector_governance_report_id") or ""),
                str(content.get("selector_governance_diff_report_id") or ""),
                str(content.get("binding_proposal_id") or ""),
                str(content.get("selector_governance_binding_proposal_id") or ""),
                str(content.get("selector_decision_id") or ""),
                str(content.get("knowledge_pack_id") or ""),
                _display_path(storage.root, path),
            }:
                return path, data
    raise ValueError(f"asset not found: {text}")


def _asset_project_id(asset: dict[str, Any]) -> str:
    metadata = asset.get("metadata", {}) if isinstance(asset.get("metadata", {}), dict) else {}
    content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
    return str(metadata.get("project_id") or content.get("project_id") or "")


def _metadata_value(asset: dict[str, Any], key: str) -> Any:
    metadata = asset.get("metadata", {}) if isinstance(asset.get("metadata", {}), dict) else {}
    return metadata.get(key)


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


def _resolve_binding_proposal(storage: LocalStorage, ref: Any) -> tuple[Path, dict[str, Any]]:
    path, data = _resolve_asset_by_ref(storage, str(ref or ""))
    if not isinstance(data, dict) or data.get("type") != "mkaos_selector_governance_binding_proposal":
        raise ValueError("binding_proposal_path must point to a mkaos_selector_governance_binding_proposal")
    return path, data


def _read_approval_request(storage: LocalStorage, approval_ref: str) -> dict[str, Any]:
    try:
        path, data = _resolve_asset_by_ref(storage, approval_ref)
    except (OSError, TypeError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("type") != "approval_request":
        return {}
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    return {"status": str(content.get("status") or ""), "path": _display_path(storage.root, path), "asset": data}


def _existing_binding_application(storage: LocalStorage, proposal_content: dict[str, Any]) -> dict[str, Any]:
    apply_result = proposal_content.get("binding_apply_result", {}) if isinstance(proposal_content.get("binding_apply_result", {}), dict) else {}
    application_ref = str(apply_result.get("application_report_path") or "")
    if not application_ref:
        return {}
    try:
        path, data = _resolve_asset_by_ref(storage, application_ref)
    except (OSError, TypeError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("type") != "mkaos_selector_governance_binding_application_report":
        return {}
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    if str(content.get("status") or "") != "applied":
        return {}
    return {"path": _display_path(storage.root, path), "asset": data}


def _existing_rollback_plan(storage: LocalStorage, application: dict[str, Any]) -> dict[str, Any]:
    content = application.get("content", {}) if isinstance(application.get("content", {}), dict) else {}
    plan_ref = str(content.get("rollback_plan_path") or "")
    if not plan_ref:
        return {}
    try:
        path, data = _resolve_asset_by_ref(storage, plan_ref)
    except (OSError, TypeError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("type") != "rollback_plan":
        return {}
    return {"path": _display_path(storage.root, path), "asset": data}


def _approval_status(approval: dict[str, Any]) -> str:
    asset = approval.get("asset", {}) if isinstance(approval.get("asset", {}), dict) else {}
    content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
    return str(approval.get("status") or content.get("status") or "")


def _same_report_ref(report: dict[str, Any], report_path: str, ref: str) -> bool:
    content = report.get("content", {}) if isinstance(report.get("content", {}), dict) else {}
    text = str(ref or "").strip()
    return text in {str(report.get("id") or ""), str(content.get("selector_governance_report_id") or ""), report_path}


def _binding_apply_approval(storage: LocalStorage, payload: dict[str, Any], proposal_path: Path, proposal: dict[str, Any], *, project_id: str, workspace_path: str) -> dict[str, Any]:
    content = proposal.get("content", {}) if isinstance(proposal.get("content", {}), dict) else {}
    approval_ref = str(payload.get("approval_request_path") or payload.get("approval_request_ref") or content.get("approval_request_path") or "").strip()
    if approval_ref:
        approval = _read_approval_request(storage, approval_ref)
        if approval:
            return approval
    from novel_forge.modules.permission_center import create_approval_request

    proposal_ref = _display_path(storage.root, proposal_path)
    return create_approval_request(
        storage,
        {
            "project_id": project_id,
            "workspace_path": workspace_path,
            "scope": "context",
            "action": "approve_selector_governance_binding",
            "environment": str(payload.get("environment") or "local"),
            "risk_level": "high" if str(payload.get("environment") or "") in {"production", "operating_system"} else "medium",
            "blocking": True,
            "target_type": "mkaos_selector_governance_binding_proposal",
            "target_id": _short_token("context-binding", str(content.get("binding_proposal_id") or proposal.get("id") or "")),
            "target_path": proposal_ref,
            "target_refs": [str(content.get("selector_governance_report_path") or "")],
            "evidence_refs": _dedupe([proposal_ref, str(content.get("diff_report_path") or ""), *_strings(payload.get("evidence_refs"))]),
            "reason": "Approve selector governance binding before context builder payload adoption",
            "required_before": ["context_builder.selector_governance_report_path", "production_context_build"],
            "rollback_plan": {"available": True, "strategy": "rollback_context_governance_binding_application", "requires_operator_review": True},
        },
    )


def _binding_rollback_approval(storage: LocalStorage, payload: dict[str, Any], plan_path: Path, plan: dict[str, Any], *, project_id: str, workspace_path: str) -> dict[str, Any]:
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
            "action": "approve_selector_governance_binding_rollback",
            "environment": str(payload.get("environment") or "local"),
            "risk_level": "medium",
            "blocking": True,
            "target_type": "rollback_plan",
            "target_id": _short_token("context-binding-rollback", str(content.get("plan_id") or plan.get("id") or "")),
            "target_path": plan_ref,
            "target_refs": [str(content.get("binding_application_path") or "")],
            "evidence_refs": _dedupe([plan_ref, str(content.get("binding_application_path") or ""), *_strings(payload.get("evidence_refs"))]),
            "reason": "Rollback selector governance binding application",
            "required_before": ["context_governance_binding_rollback"],
            "rollback_plan": {"available": False, "strategy": "reapply_context_governance_binding_if_needed", "requires_operator_review": True},
        },
    )


def _create_binding_approval_request(
    storage: LocalStorage,
    payload: dict[str, Any],
    *,
    project_id: str,
    workspace_path: str,
    environment: str,
    proposal_id: str,
    proposal_path: str,
    evidence_refs: list[str],
) -> dict[str, Any]:
    from novel_forge.modules.permission_center import create_approval_request

    risk_level = str(payload.get("risk_level") or ("high" if environment in {"production", "operating_system"} else "medium"))
    return create_approval_request(
        storage,
        {
            "project_id": project_id,
            "workspace_path": workspace_path,
            "scope": "context",
            "action": "approve_selector_governance_binding",
            "target_type": "mkaos_selector_governance_binding_proposal",
            "target_id": proposal_id,
            "target_path": proposal_path,
            "risk_level": risk_level,
            "environment": environment,
            "blocking": True,
            "reason": str(payload.get("reason") or "Approve selector governance report binding before production context build adoption."),
            "requested_by": str(payload.get("requested_by") or "mkaos-selector-governance"),
            "required_before": ["context_builder.selector_governance_report_path", "production_context_build"],
            "evidence_refs": evidence_refs,
            "target_refs": [proposal_path],
            "rollback_plan": {
                "rollback_supported": True,
                "rollback_action": "remove selector_governance_report_path from future context builder payloads",
                "mutation_applied_by_request": False,
            },
        },
    )


def _mark_binding_agent_task_dispatch_ready(storage: LocalStorage, task_path: str, *, approval_path: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if not task_path:
        return {}, {}
    path = resolve_path(storage.root, task_path)
    data = storage.read_json(path)
    if not isinstance(data, dict) or data.get("type") != "agent_task":
        raise ValueError("agent_task_path must point to an agent_task asset")
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    previous = {
        "content_status": str(content.get("status") or ""),
        "metadata_asset_status": str(metadata.get("asset_status") or ""),
        "metadata_approval_request_path": str(metadata.get("approval_request_path") or ""),
        "evidence": content.get("evidence", {}) if isinstance(content.get("evidence", {}), dict) else {},
    }
    evidence = dict(previous["evidence"])
    evidence.update(
        {
            "approval_request_path": approval_path,
            "dispatch_allowed": False,
            "approved_for_payload_adoption": True,
            "adoption_payload_only": True,
        }
    )
    content["status"] = "approved_pending_dispatch"
    content["evidence"] = evidence
    content["updated_at"] = utc_now()
    data["content"] = content
    metadata.update({"asset_status": "approved_pending_dispatch", "approval_request_path": approval_path})
    data["metadata"] = metadata
    data["updated_at"] = utc_now()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    storage.write_json(path, data)
    display_path = _display_path(storage.root, path)
    return (
        {"path": display_path, "status": "approved_pending_dispatch", "previous": previous},
        {"action": "restore_agent_task_state", "target_path": display_path, "previous": previous},
    )


def _write_binding_application_report(
    storage: LocalStorage,
    proposal: dict[str, Any],
    *,
    proposal_path: str,
    approval_path: str,
    task_update: dict[str, Any],
    project_id: str,
    workspace_path: str,
) -> dict[str, Any]:
    proposal_content = proposal.get("content", {}) if isinstance(proposal.get("content", {}), dict) else {}
    application_id = make_id("mkaos_selector_governance_binding_application_report", f"{project_id or 'all'}-{utc_now()}")
    patch = proposal_content.get("recommended_context_builder_payload_patch", {}) if isinstance(proposal_content.get("recommended_context_builder_payload_patch", {}), dict) else {}
    context_patch = {**patch, "selector_governance_binding_application_report_id": application_id}
    content = {
        "binding_application_id": application_id,
        "binding_proposal_id": str(proposal_content.get("binding_proposal_id") or proposal.get("id") or ""),
        "binding_proposal_path": proposal_path,
        "selector_governance_report_path": str(proposal_content.get("selector_governance_report_path") or ""),
        "approval_request_path": approval_path,
        "agent_task_path": str(proposal_content.get("agent_task_path") or ""),
        "agent_task_update": task_update,
        "context_builder_payload_patch": context_patch,
        "rollback_plan_path": "",
        "status": "applied",
        "application_contract": {
            "contract_version": "context-governance-binding-application-v1",
            "approval_verified": True,
            "context_build_executed": False,
            "context_bundle_mutated": False,
            "selector_governance_report_path_injected_automatically": False,
            "payload_patch_only": True,
            "raw_source_text_included": False,
            "prose_mutation_included": False,
        },
        "created_at": utc_now(),
    }
    asset = MKAOSSelectorGovernanceBindingApplicationReport(
        id=application_id,
        title="MKAOS selector governance binding application",
        source=str(proposal.get("id") or ""),
        tags=["mkaos", "selector-governance", "context-binding", "application", "applied"],
        content=content,
        metadata={"project_id": project_id, "workspace_path": workspace_path, "asset_status": "applied", "use_in_generation_rag": False},
        references=_dedupe([proposal_path, approval_path, str(proposal_content.get("selector_governance_report_path") or ""), str(proposal_content.get("diff_report_path") or "")]),
    )
    data = asset.to_dict()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset("runs", asset)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path)}


def _binding_application_rollback_action(application: dict[str, Any]) -> dict[str, Any]:
    app_path = str(application.get("path") or "")
    if not app_path:
        return {}
    return {"action": "mark_binding_application_rolled_back", "target_path": app_path, "previous_status": "applied"}


def _binding_proposal_rollback_action(proposal: dict[str, Any], proposal_path: str) -> dict[str, Any]:
    content = proposal.get("content", {}) if isinstance(proposal.get("content", {}), dict) else {}
    metadata = proposal.get("metadata", {}) if isinstance(proposal.get("metadata", {}), dict) else {}
    return {
        "action": "restore_binding_proposal_apply_state",
        "target_path": proposal_path,
        "previous": {
            "content_status": str(content.get("status") or "needs_approval"),
            "metadata_asset_status": str(metadata.get("asset_status") or "needs_approval"),
            "binding_apply_result": content.get("binding_apply_result", {}),
        },
    }


def _write_binding_rollback_plan(
    storage: LocalStorage,
    application: dict[str, Any],
    *,
    application_path: str,
    approval_path: str,
    actions: list[dict[str, Any]],
    project_id: str,
    workspace_path: str,
) -> dict[str, Any]:
    app_content = application.get("content", {}) if isinstance(application.get("content", {}), dict) else {}
    plan_id = make_id("rollback_plan", _short_token("context-binding", f"{application.get('id', '')}:{utc_now()}"))
    transaction_id = make_id("context_governance_binding", _short_token("context-binding-tx", f"{application.get('id', '')}:{approval_path}:{utc_now()}"))
    content = {
        "plan_id": plan_id,
        "transaction_id": transaction_id,
        "strategy": "rollback_context_governance_binding_application",
        "actions": actions,
        "rollback_status": "available",
        "binding_application_path": application_path,
        "binding_proposal_path": str(app_content.get("binding_proposal_path") or ""),
        "approval_request_path": approval_path,
        "created_at": utc_now(),
        "raw_source_text_included": False,
        "prose_mutation_included": False,
        "context_bundle_mutation_included": False,
        "requires_operator_review": True,
    }
    asset = RollbackPlan(
        id=plan_id,
        title="Rollback context governance binding application",
        source=str(application.get("id") or ""),
        tags=["mkaos", "selector-governance", "context-binding", "rollback-plan"],
        content=content,
        metadata={"project_id": project_id, "workspace_path": workspace_path, "asset_status": "available", "use_in_generation_rag": False},
        references=_dedupe([application_path, approval_path, str(app_content.get("binding_proposal_path") or ""), *[str(action.get("target_path") or "") for action in actions]]),
    )
    data = asset.to_dict()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path)}


def _update_binding_application_links(storage: LocalStorage, application_path: str, rollback_plan: dict[str, Any]) -> dict[str, Any]:
    path = resolve_path(storage.root, application_path)
    data = storage.read_json(path)
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    content["rollback_plan_path"] = str(rollback_plan.get("path") or "")
    content["updated_at"] = utc_now()
    data["content"] = content
    refs = data.get("references", []) if isinstance(data.get("references", []), list) else []
    data["references"] = _dedupe([*[str(ref) for ref in refs], str(rollback_plan.get("path") or "")])
    data["updated_at"] = utc_now()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    storage.write_json(path, data)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path)}


def _record_binding_apply_result(storage: LocalStorage, proposal_path: Path, proposal: dict[str, Any], *, approval_path: str, application_path: str, rollback_plan_path: str) -> None:
    content = proposal.get("content", {}) if isinstance(proposal.get("content", {}), dict) else {}
    content["status"] = "applied"
    content["binding_apply_result"] = {
        "status": "applied",
        "approval_request_path": approval_path,
        "application_report_path": application_path,
        "rollback_plan_path": rollback_plan_path,
        "context_build_executed": False,
        "context_bundle_mutated": False,
        "applied_at": utc_now(),
    }
    proposal["content"] = content
    metadata = proposal.get("metadata", {}) if isinstance(proposal.get("metadata", {}), dict) else {}
    metadata["asset_status"] = "applied"
    metadata["binding_apply_status"] = "applied"
    proposal["metadata"] = metadata
    proposal["updated_at"] = utc_now()
    errors = validate_common_fields(proposal)
    if errors:
        raise ValueError("; ".join(errors))
    storage.write_json(proposal_path, proposal)


def _apply_binding_rollback_actions(storage: LocalStorage, actions: list[dict[str, Any]], *, actor: str) -> tuple[list[dict[str, Any]], list[str]]:
    applied: list[dict[str, Any]] = []
    errors: list[str] = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        action_type = str(action.get("action") or "")
        target_path = str(action.get("target_path") or "")
        try:
            path = resolve_path(storage.root, target_path)
            data = storage.read_json(path)
            if action_type == "restore_agent_task_state":
                previous = action.get("previous", {}) if isinstance(action.get("previous", {}), dict) else {}
                content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
                metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
                content["status"] = str(previous.get("content_status") or "needs_review")
                content["evidence"] = previous.get("evidence", {}) if isinstance(previous.get("evidence", {}), dict) else {}
                content["updated_at"] = utc_now()
                data["content"] = content
                metadata["asset_status"] = str(previous.get("metadata_asset_status") or content["status"])
                previous_approval_path = str(previous.get("metadata_approval_request_path") or "")
                if previous_approval_path:
                    metadata["approval_request_path"] = previous_approval_path
                else:
                    metadata.pop("approval_request_path", None)
                metadata["rollback_actor"] = actor
                data["metadata"] = metadata
                data["updated_at"] = utc_now()
                validation_errors = validate_common_fields(data)
                if validation_errors:
                    raise ValueError("; ".join(validation_errors))
                storage.write_json(path, data)
            elif action_type == "mark_binding_application_rolled_back":
                content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
                metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
                content["status"] = "rolled_back"
                content["rolled_back_at"] = utc_now()
                content["rolled_back_by"] = actor
                data["content"] = content
                metadata["asset_status"] = "rolled_back"
                metadata["rollback_actor"] = actor
                data["metadata"] = metadata
                data["updated_at"] = utc_now()
                validation_errors = validate_common_fields(data)
                if validation_errors:
                    raise ValueError("; ".join(validation_errors))
                storage.write_json(path, data)
            elif action_type == "restore_binding_proposal_apply_state":
                previous = action.get("previous", {}) if isinstance(action.get("previous", {}), dict) else {}
                content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
                metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
                content["status"] = str(previous.get("content_status") or "needs_approval")
                if previous.get("binding_apply_result"):
                    content["binding_apply_result"] = previous.get("binding_apply_result")
                else:
                    content.pop("binding_apply_result", None)
                content["updated_at"] = utc_now()
                data["content"] = content
                metadata["asset_status"] = str(previous.get("metadata_asset_status") or content["status"])
                metadata["binding_apply_status"] = "rolled_back"
                metadata["rollback_actor"] = actor
                data["metadata"] = metadata
                data["updated_at"] = utc_now()
                validation_errors = validate_common_fields(data)
                if validation_errors:
                    raise ValueError("; ".join(validation_errors))
                storage.write_json(path, data)
            else:
                errors.append(f"unsupported rollback action: {action_type}")
                continue
            applied.append({"action": action_type, "target_path": _display_path(storage.root, path), "status": "applied"})
        except (OSError, TypeError, ValueError) as exc:
            errors.append(f"{action_type}:{target_path}:{exc}")
    return applied, errors


def _write_binding_rollback_result(
    storage: LocalStorage,
    plan: dict[str, Any],
    *,
    plan_path: str,
    approval_path: str,
    status: str,
    applied_actions: list[dict[str, Any]],
    errors: list[str],
    project_id: str,
    workspace_path: str,
) -> dict[str, Any]:
    content = plan.get("content", {}) if isinstance(plan.get("content", {}), dict) else {}
    result_id = make_id("rollback_result", _short_token("context-binding-result", f"{content.get('plan_id', plan.get('id', ''))}:{status}:{utc_now()}"))
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
        title=f"Context governance binding rollback {status}",
        source=str(content.get("plan_id") or plan.get("id") or ""),
        tags=["mkaos", "selector-governance", "context-binding", "rollback-result", status],
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


def _create_binding_agent_task(
    storage: LocalStorage,
    *,
    project_id: str,
    workspace_path: str,
    proposal_path: str,
    report_path: str,
    previous_path: str,
    diff_path: str,
    approval_path: str,
    recommended_patch: dict[str, Any],
) -> dict[str, Any]:
    from novel_forge.modules.agent_scheduler import create_agent_task

    evidence = {
        "context_governance_binding_proposal_path": proposal_path,
        "selector_governance_report_path": report_path,
        "previous_context_evidence_path": previous_path,
        "selector_governance_diff_report_path": diff_path,
        "approval_request_path": approval_path,
        "recommended_context_builder_payload_patch": recommended_patch,
        "dispatch_allowed": False,
        "adoption_applied": False,
        "mutation_applied": False,
        "requires_operator_review": True,
        "raw_source_text_included": False,
    }
    return create_agent_task(
        storage,
        agent_type="Context Agent",
        operation="review-context-governance-binding",
        input_assets=[ref for ref in [proposal_path, report_path, previous_path, diff_path, approval_path] if ref],
        output_targets=[
            {"asset_type": "context_build_plan", "purpose": "operator-approved selector governance report binding"},
            {"asset_type": "context_bundle", "purpose": "future explicit selector_governance_report_path adoption"},
        ],
        status="needs_review",
        project_id=project_id,
        workspace_path=workspace_path,
        evidence=evidence,
    )


def _update_binding_proposal_links(storage: LocalStorage, proposal_path: str, approval: dict[str, Any], agent_task: dict[str, Any]) -> dict[str, Any]:
    path = storage.root / proposal_path if not Path(proposal_path).is_absolute() else Path(proposal_path)
    data = storage.read_json(path)
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    approval_path = str(approval.get("path") or "")
    task_path = str(agent_task.get("path") or "")
    content["approval_request_path"] = approval_path
    content["approval_request_id"] = str(approval.get("asset", {}).get("content", {}).get("request_id") or approval.get("asset", {}).get("id") or "")
    content["agent_task_path"] = task_path
    content["agent_task_id"] = str(agent_task.get("asset", {}).get("content", {}).get("task_id") or agent_task.get("asset", {}).get("id") or "")
    content["updated_at"] = utc_now()
    data["content"] = content
    references = data.get("references", []) if isinstance(data.get("references", []), list) else []
    data["references"] = _dedupe([*[str(ref) for ref in references], approval_path, task_path])
    data["updated_at"] = utc_now()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    storage.write_json(path, data)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path)}


def _dedupe(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _short_token(prefix: str, value: str) -> str:
    digest = sha1(str(value or "").encode("utf-8")).hexdigest()[:12]
    safe_prefix = "".join(ch.lower() if ch.isalnum() else "-" for ch in str(prefix or "token")).strip("-") or "token"
    return f"{safe_prefix}-{digest}"


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
