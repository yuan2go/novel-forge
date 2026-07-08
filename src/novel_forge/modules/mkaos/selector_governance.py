from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.constants import DATA_DIRS
from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.schemas import BaseAsset, MKAOSSelectorGovernanceBindingProposal, validate_common_fields
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


def _same_report_ref(report: dict[str, Any], report_path: str, ref: str) -> bool:
    content = report.get("content", {}) if isinstance(report.get("content", {}), dict) else {}
    text = str(ref or "").strip()
    return text in {str(report.get("id") or ""), str(content.get("selector_governance_report_id") or ""), report_path}


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


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
