from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from novel_forge.core.asset_scan import iter_json_objects
from novel_forge.core.constants import DATA_DIRS
from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.source_intake.service import _dedupe, _display_path
from novel_forge.modules.source_intake.stale_sweep import SOURCE_DERIVED_TYPES
from novel_forge.schemas import ChangeImpactReport, validate_common_fields
from novel_forge.storage.local import LocalStorage


def sweep_source_retention_expiry(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    storage.ensure_layout()
    project_id = str(payload.get("project_id") or "")
    workspace_path = str(payload.get("workspace_path") or "")
    policy = _retention_policy(payload)
    max_assets = _positive_int(payload.get("max_assets"), 1000)
    include_global = bool(payload.get("include_global"))

    expired_snapshots = _expired_snapshots(storage, project_id=project_id, workspace_path=workspace_path, include_global=include_global, max_assets=max_assets, policy=policy)
    snapshot_refs = _snapshot_ref_index(expired_snapshots)
    derived_impacts = _expired_source_derived_assets(
        storage,
        snapshot_refs,
        project_id=project_id,
        workspace_path=workspace_path,
        include_global=include_global,
        max_assets=max_assets,
    )
    impacted = [*expired_snapshots, *derived_impacts]
    report = _write_retention_report(storage, impacted=impacted, policy=policy, project_id=project_id, workspace_path=workspace_path)
    review_issue = _write_retention_review_issue(storage, report, impacted, project_id=project_id, workspace_path=workspace_path) if impacted else {}
    agent_tasks = _write_retention_agent_tasks(storage, report, review_issue, impacted, project_id=project_id, workspace_path=workspace_path) if impacted else []
    updated_report = _update_retention_report_links(storage, report["path"], review_issue, agent_tasks)
    return {
        "status": "review_required" if impacted else "clean",
        "retention_report": updated_report,
        "review_issue": review_issue,
        "agent_tasks": agent_tasks,
        "expired_snapshot_count": len(expired_snapshots),
        "expired_source_derived_count": len(derived_impacts),
        "impacted_count": len(impacted),
        "mutation_applied": False,
        "delete_applied": False,
        "dispatch_applied": False,
        "raw_source_text_included": False,
    }


def _retention_policy(payload: dict[str, Any]) -> dict[str, Any]:
    provided = payload.get("retention_policy", {}) if isinstance(payload.get("retention_policy", {}), dict) else {}
    return {
        "max_snapshot_age_days": _positive_int(payload.get("max_snapshot_age_days") or provided.get("max_snapshot_age_days"), 30),
        "max_source_derived_age_days": _positive_int(payload.get("max_source_derived_age_days") or provided.get("max_source_derived_age_days"), 90),
        "delete_allowed": False,
        "auto_invalidate_allowed": False,
        "operator_review_required": True,
    }


def _expired_snapshots(
    storage: LocalStorage,
    *,
    project_id: str,
    workspace_path: str,
    include_global: bool,
    max_assets: int,
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    impacted: list[dict[str, Any]] = []
    scanned = 0
    for path, data in iter_json_objects(storage, "raw", context="source retention snapshot sweep"):
        if data.get("type") != "source_snapshot":
            continue
        if not _scope_matches(data, project_id=project_id, workspace_path=workspace_path, include_global=include_global):
            continue
        scanned += 1
        age = _asset_age_days(data, ["captured_at", "created_at"])
        if age is None or age <= int(policy["max_snapshot_age_days"]):
            continue
        impacted.append(
            {
                "asset_id": str(data.get("id") or ""),
                "path": _display_path(storage.root, path),
                "type": "source_snapshot",
                "title": _compact(str(data.get("title") or "")),
                "severity": "high",
                "signals": ["source_snapshot_expired"],
                "age_days": age,
                "max_age_days": int(policy["max_snapshot_age_days"]),
                "source_refs": _source_refs(data),
                "context_selection": {"allowed": False, "signals": ["source_snapshot_expired"], "reason": "source snapshot is past retention policy and must be reviewed before reuse"},
                "recommended_action": "review_snapshot_refresh_or_invalidate_downstream",
            }
        )
        if scanned >= max_assets:
            break
    return impacted


def _expired_source_derived_assets(
    storage: LocalStorage,
    snapshot_refs: set[str],
    *,
    project_id: str,
    workspace_path: str,
    include_global: bool,
    max_assets: int,
) -> list[dict[str, Any]]:
    if not snapshot_refs:
        return []
    impacted: list[dict[str, Any]] = []
    scanned = 0
    for category in DATA_DIRS:
        for path, data in iter_json_objects(storage, category, context="source retention derived sweep"):
            if data.get("type") not in SOURCE_DERIVED_TYPES:
                continue
            if not _scope_matches(data, project_id=project_id, workspace_path=workspace_path, include_global=include_global):
                continue
            scanned += 1
            refs = set(_source_refs(data))
            matched = sorted(ref for ref in refs if ref in snapshot_refs)
            if not matched:
                continue
            impacted.append(
                {
                    "asset_id": str(data.get("id") or ""),
                    "path": _display_path(storage.root, path),
                    "type": str(data.get("type") or ""),
                    "title": _compact(str(data.get("title") or "")),
                    "severity": "high",
                    "signals": ["expired_source_snapshot_dependency"],
                    "source_refs": matched,
                    "context_selection": {"allowed": False, "signals": ["expired_source_snapshot_dependency"], "reason": "asset depends on an expired SourceSnapshot"},
                    "recommended_action": "review_and_plan_regeneration_or_reapproval",
                }
            )
            if scanned >= max_assets:
                break
        if scanned >= max_assets:
            break
    return impacted


def _write_retention_report(
    storage: LocalStorage,
    *,
    impacted: list[dict[str, Any]],
    policy: dict[str, Any],
    project_id: str,
    workspace_path: str,
) -> dict[str, Any]:
    report_id = make_id("source_retention_expiry_sweep", f"{project_id}:{workspace_path}:{utc_now()}")
    content = {
        "target_asset_id": project_id or "source-governance",
        "target_path": workspace_path or project_id or "source-governance",
        "report_id": report_id,
        "retention_policy": policy,
        "impacted_assets": impacted,
        "impact_edges": _impact_edges(impacted),
        "severity_summary": _severity_summary(impacted),
        "recommendation": "review_impacts" if impacted else "no_action",
        "cleanup_plan": {
            "delete_allowed": False,
            "auto_invalidate_allowed": False,
            "operator_review_required": bool(impacted),
            "steps": ["review expired source evidence", "refresh or reapprove source", "plan downstream invalidation/regeneration if still needed"] if impacted else [],
        },
        "review_issue_paths": [],
        "agent_task_paths": [],
        "mutation_applied": False,
        "delete_applied": False,
        "dispatch_applied": False,
        "raw_source_text_included": False,
        "created_at": utc_now(),
    }
    asset = ChangeImpactReport(
        id=report_id,
        title=f"Source retention expiry sweep: {project_id or 'global'}",
        source="source_intake.retention_sweep",
        tags=["source-governance", "retention-expiry-sweep", content["recommendation"]],
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


def _write_retention_review_issue(storage: LocalStorage, report: dict[str, Any], impacted: list[dict[str, Any]], *, project_id: str, workspace_path: str) -> dict[str, Any]:
    from novel_forge.modules.review_issue import create_review_issue

    return create_review_issue(
        storage,
        {
            "issue_type": "source_snapshot_drift",
            "severity": "high",
            "blocking": True,
            "status": "open",
            "target_asset_id": project_id or "source-governance",
            "target_asset_type": "source_retention_expiry_sweep",
            "target_asset_path": str(report.get("path") or ""),
            "message": f"Source retention sweep found {len(impacted)} expired source-governance impact(s); review before source-derived context reuse.",
            "fix_suggestion": "Refresh/reapprove expired source evidence or plan downstream invalidation/regeneration. Do not delete evidence automatically.",
            "evidence_refs": _dedupe([str(report.get("path") or ""), *[str(item.get("path") or "") for item in impacted[:20]]]),
            "project_id": project_id,
            "workspace_path": workspace_path,
            "source_system": "source_intake.retention_sweep",
            "source_issue": {"impacted_count": len(impacted), "delete_allowed": False, "raw_source_text_included": False},
        },
    )


def _write_retention_agent_tasks(storage: LocalStorage, report: dict[str, Any], review_issue: dict[str, Any], impacted: list[dict[str, Any]], *, project_id: str, workspace_path: str) -> list[dict[str, Any]]:
    from novel_forge.modules.agent_scheduler import create_agent_task

    report_path = str(report.get("path") or "")
    issue_path = str(review_issue.get("path") or "")
    evidence = {
        "source_retention_expiry_report_path": report_path,
        "review_issue_path": issue_path,
        "impacted_count": len(impacted),
        "delete_allowed": False,
        "auto_invalidate_allowed": False,
        "dispatch_allowed": False,
        "requires_operator_review": True,
        "raw_source_text_included": False,
    }
    return [
        create_agent_task(
            storage,
            agent_type="Quality Agent",
            operation="review-source-retention-expiry-sweep",
            input_assets=[report_path, issue_path],
            output_targets=[{"asset_type": "review_issue", "purpose": "source retention review decision"}],
            status="needs_review",
            project_id=project_id,
            workspace_path=workspace_path,
            linked_review_issue_path=issue_path,
            evidence={**evidence, "retention_phase": "review"},
        ),
        create_agent_task(
            storage,
            agent_type="Workflow Agent",
            operation="plan-source-retention-cleanup",
            input_assets=[report_path, issue_path],
            output_targets=[{"asset_type": "change_impact_report", "purpose": "operator-approved cleanup/invalidation plan"}],
            status="needs_review",
            project_id=project_id,
            workspace_path=workspace_path,
            linked_review_issue_path=issue_path,
            evidence={**evidence, "retention_phase": "cleanup_plan"},
        ),
    ]


def _update_retention_report_links(storage: LocalStorage, report_path: str, review_issue: dict[str, Any], agent_tasks: list[dict[str, Any]]) -> dict[str, Any]:
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


def _snapshot_ref_index(items: list[dict[str, Any]]) -> set[str]:
    refs: set[str] = set()
    for item in items:
        for value in [item.get("asset_id"), item.get("path")]:
            if str(value or "").strip():
                refs.add(str(value))
    return refs


def _asset_age_days(data: dict[str, Any], keys: list[str]) -> int | None:
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    for key in keys:
        value = content.get(key) or data.get(key)
        parsed = _parse_datetime(value)
        if parsed:
            return max(0, int((datetime.now(timezone.utc) - parsed).total_seconds() // 86400))
    return None


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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


def _source_refs(data: dict[str, Any]) -> list[str]:
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    source_eligibility = content.get("source_eligibility") if isinstance(content.get("source_eligibility"), dict) else {}
    refs: list[str] = []
    for container in (metadata, content, source_eligibility):
        for key in ["source_ref", "source_refs", "source_snapshot_ref", "source_snapshot_refs", "source_policy_ref", "source_policy_refs", "source_risk_report_ref", "source_risk_report_refs", "risk_report_path"]:
            value = container.get(key)
            if isinstance(value, list):
                refs.extend(str(item) for item in value if str(item).strip())
            elif str(value or "").strip():
                refs.append(str(value))
    if isinstance(data.get("references", []), list):
        refs.extend(str(item) for item in data.get("references", []) if str(item).strip())
    return [_compact(item, limit=180) for item in _dedupe(refs)[:20]]


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
            edges.append({"from": source_ref, "to": str(item.get("path") or ""), "relationship": "source_retention_expiry_impacts_asset", "signals": item.get("signals", []) if isinstance(item.get("signals", []), list) else []})
    return edges[:200]


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _compact(value: str, *, limit: int = 240) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 3] + "..."
