from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.asset_scan import iter_json_objects
from novel_forge.core.constants import DATA_DIRS
from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.source_intake.service import _dedupe, _display_path, _strings
from novel_forge.schemas import ChangeImpactReport, validate_common_fields
from novel_forge.storage.local import LocalStorage


SOURCE_DERIVED_TYPES = {
    "knowledge_card",
    "material_card",
    "writing_template",
    "craft_template",
    "rule_card",
    "template_card",
    "analysis_conversion_report",
    "knowledge_usage_binding",
    "knowledge_pack_item",
    "style_generation_policy",
    "style_review_rule",
}


def sweep_source_stale_quarantine(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    """Create reviewable evidence for stale/quarantined source-derived assets.

    This is intentionally non-mutating: it does not delete assets, re-enable
    source-derived assets, dispatch AgentTasks, or regenerate prose.
    """

    storage.ensure_layout()
    project_id = str(payload.get("project_id") or "")
    workspace_path = str(payload.get("workspace_path") or "")
    categories = _scan_categories(payload)
    max_assets = _positive_int(payload.get("max_assets"), 1000)
    include_global = bool(payload.get("include_global"))

    impacted: list[dict[str, Any]] = []
    scanned_count = 0
    for category in categories:
        for path, data in iter_json_objects(storage, category, context="source stale/quarantine sweep"):
            if not _scope_matches(data, project_id=project_id, workspace_path=workspace_path, include_global=include_global):
                continue
            scanned_count += 1
            impact = _source_governance_impact(storage, path, data)
            if impact:
                impacted.append(impact)
            if scanned_count >= max_assets:
                break
        if scanned_count >= max_assets:
            break

    report = _write_sweep_report(
        storage,
        impacted=impacted,
        scanned_count=scanned_count,
        categories=categories,
        project_id=project_id,
        workspace_path=workspace_path,
        max_assets=max_assets,
    )
    review_issue = _write_sweep_review_issue(storage, report, impacted, project_id=project_id, workspace_path=workspace_path) if impacted else {}
    agent_tasks = _write_sweep_agent_tasks(storage, report, review_issue, impacted, project_id=project_id, workspace_path=workspace_path) if impacted else []
    updated_report = _update_sweep_report_links(storage, report["path"], review_issue, agent_tasks)

    blocking_count = sum(1 for item in impacted if str(item.get("severity") or "") == "blocking")
    return {
        "status": "blocked" if blocking_count else "review_required" if impacted else "clean",
        "sweep_report": updated_report,
        "review_issue": review_issue,
        "agent_tasks": agent_tasks,
        "scanned_count": scanned_count,
        "impacted_count": len(impacted),
        "blocking_count": blocking_count,
        "mutation_applied": False,
        "dispatch_applied": False,
        "raw_source_text_included": False,
    }


def _scan_categories(payload: dict[str, Any]) -> list[str]:
    requested = [item for item in _strings(payload.get("categories")) if item in DATA_DIRS]
    if requested:
        return requested
    return list(DATA_DIRS)


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _scope_matches(data: dict[str, Any], *, project_id: str, workspace_path: str, include_global: bool) -> bool:
    if not project_id and not workspace_path:
        return True
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    asset_project = str(metadata.get("project_id") or content.get("project_id") or "")
    asset_workspace = str(metadata.get("workspace_path") or content.get("workspace_path") or "")
    if project_id and asset_project and asset_project != project_id:
        return False
    if project_id and not asset_project and not include_global:
        return False
    if workspace_path and asset_workspace and asset_workspace != workspace_path:
        return False
    if workspace_path and not asset_workspace and not include_global:
        return False
    return True


def _source_governance_impact(storage: LocalStorage, path: Path, data: dict[str, Any]) -> dict[str, Any]:
    signals = _source_governance_signals(data)
    if not signals:
        return {}
    if not _is_source_governed_asset(data) and not any(signal in {"source_risk_quarantine", "source_policy_quarantine"} for signal in signals):
        return {}
    severity = "blocking" if any("quarantine" in signal for signal in signals) else "high"
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    source_refs = _source_refs(data)
    return {
        "asset_id": str(data.get("id") or ""),
        "path": _display_path(storage.root, path),
        "type": str(data.get("type") or ""),
        "title": _compact(str(data.get("title") or data.get("name") or "")),
        "severity": severity,
        "signals": signals,
        "source_refs": source_refs,
        "asset_status": str(metadata.get("asset_status") or content.get("asset_status") or ""),
        "source_diff_repair_status": str(metadata.get("source_diff_repair_status") or content.get("source_diff_repair_status") or ""),
        "context_selection": {
            "allowed": False,
            "signals": _dedupe([*signals, "source_governance_sweep_denied"]),
            "reason": "stale/quarantined source-derived asset must be reviewed before context selection",
        },
        "recommended_action": "operator_review_before_context_selection",
    }


def _source_governance_signals(data: dict[str, Any]) -> list[str]:
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    tags = {str(tag).strip().lower() for tag in data.get("tags", []) if str(tag).strip()} if isinstance(data.get("tags", []), list) else set()
    source_eligibility = content.get("source_eligibility") if isinstance(content.get("source_eligibility"), dict) else {}
    status_values = {
        str(metadata.get("asset_status") or "").strip().lower(),
        str(content.get("asset_status") or "").strip().lower(),
    }
    signals: list[str] = []
    if "stale" in status_values:
        signals.append("stale_asset_status")
    if any(value in {"quarantined", "quarantine"} for value in status_values):
        signals.append("quarantined_asset_status")
    if str(metadata.get("source_diff_repair_status") or content.get("source_diff_repair_status") or "").startswith("stale"):
        signals.append("source_diff_repair_stale")
    if bool(metadata.get("quarantine") or content.get("quarantine")):
        if data.get("type") == "source_risk_report":
            signals.append("source_risk_quarantine")
        elif data.get("type") == "source_policy":
            signals.append("source_policy_quarantine")
        else:
            signals.append("source_quarantine")
    if bool(source_eligibility.get("quarantine")):
        signals.append("source_eligibility_quarantine")
    if "quarantined" in tags or "source-quarantine" in tags:
        signals.append("quarantine_tag")
    return _dedupe(signals)


def _is_source_governed_asset(data: dict[str, Any]) -> bool:
    if str(data.get("type") or "") in SOURCE_DERIVED_TYPES | {"source_risk_report", "source_policy", "source_refresh_report", "source_snapshot"}:
        return True
    return bool(_source_refs(data))


def _source_refs(data: dict[str, Any]) -> list[str]:
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    source_eligibility = content.get("source_eligibility") if isinstance(content.get("source_eligibility"), dict) else {}
    refs: list[str] = []
    for container in (metadata, content, source_eligibility):
        for key in [
            "source_ref",
            "source_refs",
            "source_snapshot_ref",
            "source_snapshot_refs",
            "source_policy_ref",
            "source_policy_refs",
            "source_policy_path",
            "source_risk_report_ref",
            "source_risk_report_refs",
            "risk_report_path",
            "license_check_ref",
        ]:
            value = container.get(key)
            if isinstance(value, list):
                refs.extend(str(item) for item in value if str(item).strip())
            elif str(value or "").strip():
                refs.append(str(value))
    return [_compact(item, limit=180) for item in _dedupe(refs)[:12]]


def _write_sweep_report(
    storage: LocalStorage,
    *,
    impacted: list[dict[str, Any]],
    scanned_count: int,
    categories: list[str],
    project_id: str,
    workspace_path: str,
    max_assets: int,
) -> dict[str, Any]:
    sweep_id = make_id("source_stale_quarantine_sweep", f"{project_id}:{workspace_path}:{utc_now()}")
    severity_summary = _severity_summary(impacted)
    content = {
        "target_asset_id": project_id or "source-governance",
        "target_path": workspace_path or project_id or "source-governance",
        "sweep_id": sweep_id,
        "scanned_count": scanned_count,
        "max_assets": max_assets,
        "categories": categories,
        "impacted_assets": impacted,
        "impact_edges": _impact_edges(impacted),
        "severity_summary": severity_summary,
        "recommendation": "block_until_resolved" if severity_summary.get("blocking", 0) else "review_impacts" if impacted else "no_action",
        "context_selection_denials": [
            {
                "path": item.get("path", ""),
                "asset_id": item.get("asset_id", ""),
                "signals": item.get("signals", []),
                "reason": item.get("context_selection", {}).get("reason", ""),
            }
            for item in impacted
        ],
        "review_issue_paths": [],
        "agent_task_paths": [],
        "silent_mutation_allowed": False,
        "mutation_applied": False,
        "dispatch_applied": False,
        "raw_source_text_included": False,
        "created_at": utc_now(),
    }
    asset = ChangeImpactReport(
        id=sweep_id,
        title=f"Source stale/quarantine sweep: {project_id or 'global'}",
        source="source_intake.stale_sweep",
        tags=["source-governance", "stale-quarantine-sweep", content["recommendation"]],
        content=content,
        metadata={"project_id": project_id, "workspace_path": workspace_path, "asset_status": content["recommendation"], "use_in_generation_rag": False},
        references=[str(item.get("path") or "") for item in impacted],
    )
    data = asset.to_dict()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path)}


def _write_sweep_review_issue(
    storage: LocalStorage,
    report: dict[str, Any],
    impacted: list[dict[str, Any]],
    *,
    project_id: str,
    workspace_path: str,
) -> dict[str, Any]:
    from novel_forge.modules.review_issue import create_review_issue

    blocking = any(str(item.get("severity") or "") == "blocking" for item in impacted)
    issue_type = "source_leakage" if blocking else "source_snapshot_drift"
    return create_review_issue(
        storage,
        {
            "issue_type": issue_type,
            "severity": "critical" if blocking else "high",
            "blocking": True,
            "status": "open",
            "target_asset_id": project_id or "source-governance",
            "target_asset_type": "source_governance_sweep",
            "target_asset_path": str(report.get("path") or ""),
            "message": f"Source governance sweep found {len(impacted)} stale/quarantined source-derived asset(s); block context selection until reviewed.",
            "fix_suggestion": "Review impacted assets, approve source repair/regeneration or rollback, then rerun context selection.",
            "evidence_refs": _dedupe([str(report.get("path") or ""), *[str(item.get("path") or "") for item in impacted[:20]]]),
            "project_id": project_id,
            "workspace_path": workspace_path,
            "source_system": "source_intake.stale_sweep",
            "source_issue": {"impacted_count": len(impacted), "silent_mutation_allowed": False, "raw_source_text_included": False},
        },
    )


def _write_sweep_agent_tasks(
    storage: LocalStorage,
    report: dict[str, Any],
    review_issue: dict[str, Any],
    impacted: list[dict[str, Any]],
    *,
    project_id: str,
    workspace_path: str,
) -> list[dict[str, Any]]:
    from novel_forge.modules.agent_scheduler import create_agent_task

    report_path = str(report.get("path") or "")
    issue_path = str(review_issue.get("path") or "")
    evidence = {
        "source_stale_quarantine_sweep_path": report_path,
        "review_issue_path": issue_path,
        "impacted_count": len(impacted),
        "blocking_count": sum(1 for item in impacted if str(item.get("severity") or "") == "blocking"),
        "silent_mutation_allowed": False,
        "dispatch_allowed": False,
        "requires_operator_review": True,
        "raw_source_text_included": False,
    }
    return [
        create_agent_task(
            storage,
            agent_type="Quality Agent",
            operation="review-source-stale-quarantine-sweep",
            input_assets=[report_path, issue_path],
            output_targets=[{"asset_type": "review_issue", "purpose": "source governance review decision"}],
            status="needs_review",
            project_id=project_id,
            workspace_path=workspace_path,
            linked_review_issue_path=issue_path,
            evidence={**evidence, "sweep_phase": "review"},
        ),
        create_agent_task(
            storage,
            agent_type="Context Agent",
            operation="plan-source-context-exclusions",
            input_assets=[report_path, issue_path],
            output_targets=[{"asset_type": "context_bundle", "purpose": "exclude stale/quarantined source-derived assets"}],
            status="needs_review",
            project_id=project_id,
            workspace_path=workspace_path,
            linked_review_issue_path=issue_path,
            evidence={**evidence, "sweep_phase": "context_exclusion"},
        ),
    ]


def _update_sweep_report_links(storage: LocalStorage, report_path: str, review_issue: dict[str, Any], agent_tasks: list[dict[str, Any]]) -> dict[str, Any]:
    path = storage.root / report_path if not Path(report_path).is_absolute() else Path(report_path)
    data = storage.read_json(path)
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    content["review_issue_paths"] = _dedupe([str(review_issue.get("path") or "")])
    content["agent_task_paths"] = _dedupe([str(task.get("path") or "") for task in agent_tasks])
    data["content"] = content
    data["updated_at"] = utc_now()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    storage.write_json(path, data)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path)}


def _severity_summary(impacted: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"blocking": 0, "high": 0, "medium": 0, "low": 0}
    for item in impacted:
        severity = str(item.get("severity") or "low")
        if severity in summary:
            summary[severity] += 1
    summary["total"] = len(impacted)
    return summary


def _impact_edges(impacted: list[dict[str, Any]]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for item in impacted:
        for source_ref in item.get("source_refs", []) if isinstance(item.get("source_refs", []), list) else []:
            edges.append(
                {
                    "from": source_ref,
                    "to": str(item.get("path") or ""),
                    "relationship": "source_governance_blocks_context",
                    "signals": item.get("signals", []) if isinstance(item.get("signals", []), list) else [],
                }
            )
    return edges[:200]


def _compact(value: str, *, limit: int = 240) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 3] + "..."
