from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.constants import ASSET_DIR_BY_TYPE
from novel_forge.modules.common import resolve_path
from novel_forge.modules.review_issue import blocking_review_issues
from novel_forge.storage.local import LocalStorage

CANON_PLUGIN_REPORT_TYPES = {
    "fantasy_power_scale_report",
    "mystery_evidence_chain_report",
    "romance_relationship_state_report",
    "historical_faction_network_report",
    "sci_fi_rule_consistency_report",
    "horror_rule_contamination_report",
}

QUALITY_REPORT_TYPES = {"opening_3_report", "golden_10_report", "volume_30_report", "longform_100_report"}

PREFLIGHT_REQUIRED_DIMENSIONS = ["genre_strategy", "style_policy"]
RELEASE_REQUIRED_DIMENSIONS = [
    "genre_strategy",
    "style_policy",
    "genre_risk_gate",
    "style_drift_gate",
    "canon_graph_plugin",
    "quality_report",
    "provider_judge_result",
    "evaluation_gate",
    "review_issue_clear",
    "platform_upload_checklist",
]


def content_intelligence_preflight_gate(
    storage: LocalStorage,
    *,
    target_asset_id: str = "",
    target_asset_path: str | Path = "",
    project_id: str = "",
    workspace_path: str = "",
    required: bool = False,
) -> dict[str, Any]:
    statuses = {
        "genre_strategy": _latest_project_gate(storage, "genre_strategy_pack", project_id=project_id, expected_status="passed"),
        "style_policy": _latest_project_gate(storage, "style_generation_policy", project_id=project_id, expected_status="passed"),
    }
    return _gate_result(
        gate_name="content_intelligence_preflight",
        required_dimensions=PREFLIGHT_REQUIRED_DIMENSIONS,
        statuses=statuses,
        required=required,
        target_asset_id=target_asset_id,
        target_asset_path=target_asset_path,
        project_id=project_id,
        workspace_path=workspace_path,
        root=storage.root,
    )


def release_content_intelligence_gate(
    storage: LocalStorage,
    *,
    target_asset_id: str,
    target_asset_path: str | Path,
    project_id: str = "",
    workspace_path: str = "",
    platform_upload_checklist: dict[str, Any] | None = None,
    required: bool = False,
) -> dict[str, Any]:
    quality = _quality_report_gate(storage, target_asset_id=target_asset_id, target_asset_path=target_asset_path, project_id=project_id)
    statuses = {
        "genre_strategy": _latest_project_gate(storage, "genre_strategy_pack", project_id=project_id, expected_status="passed"),
        "style_policy": _latest_project_gate(storage, "style_generation_policy", project_id=project_id, expected_status="passed"),
        "genre_risk_gate": _latest_target_gate(storage, "genre_risk_gate", target_asset_id=target_asset_id, target_asset_path=target_asset_path, project_id=project_id, expected_status="passed", status_field="recommendation"),
        "style_drift_gate": _style_drift_gate(storage, target_asset_id=target_asset_id, target_asset_path=target_asset_path, project_id=project_id),
        "canon_graph_plugin": _canon_plugin_gate(storage, target_asset_id=target_asset_id, target_asset_path=target_asset_path, project_id=project_id),
        "quality_report": quality,
        "provider_judge_result": _provider_judge_gate(storage, quality),
        "evaluation_gate": _latest_target_gate(storage, "evaluation_gate", target_asset_id=target_asset_id, target_asset_path=target_asset_path, project_id=project_id, expected_status="passed"),
        "review_issue_clear": _review_issue_gate(storage, target_asset_id=target_asset_id, project_id=project_id),
        "platform_upload_checklist": _platform_upload_checklist_gate(platform_upload_checklist),
    }
    return _gate_result(
        gate_name="content_intelligence_release",
        required_dimensions=RELEASE_REQUIRED_DIMENSIONS,
        statuses=statuses,
        required=required,
        target_asset_id=target_asset_id,
        target_asset_path=target_asset_path,
        project_id=project_id,
        workspace_path=workspace_path,
        root=storage.root,
    )


def platform_upload_checklist_for_release(*, title: str, summary: str, text: str, channel: str, cover: dict[str, Any] | None = None) -> dict[str, Any]:
    cover_payload = cover if isinstance(cover, dict) else {}
    cover_required = bool(cover_payload.get("required"))
    checks = {
        "title_present": bool(str(title or "").strip()),
        "summary_present": bool(str(summary or "").strip()),
        "chapter_body_present": bool(str(text or "").strip()),
        "format_checked": "\x00" not in str(text or ""),
        "sensitive_word_checked": not _contains_sensitive_marker(str(title or "") + "\n" + str(summary or "") + "\n" + str(text or "")),
        "cover_checked": (not cover_required) or bool(cover_payload.get("asset_path") or cover_payload.get("status") == "ready"),
    }
    blocking = [name for name, passed in checks.items() if not passed]
    return {
        "status": "passed" if not blocking else "blocked",
        "channel": channel,
        "checks": checks,
        "blocking": bool(blocking),
        "blocking_checks": blocking,
    }


def _gate_result(
    *,
    gate_name: str,
    required_dimensions: list[str],
    statuses: dict[str, dict[str, Any]],
    required: bool,
    target_asset_id: str,
    target_asset_path: str | Path,
    project_id: str,
    workspace_path: str,
    root: Path,
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    for dimension in required_dimensions:
        status = statuses.get(dimension, {"status": "missing", "blocking": True, "path": ""})
        if required and (status.get("blocking") or status.get("status") != "passed"):
            issues.append(
                {
                    "dimension": f"content_intelligence.{dimension}",
                    "severity": "critical" if dimension in {"quality_report", "provider_judge_result", "review_issue_clear"} else "high",
                    "message": f"production requires passed V7 content intelligence evidence: {dimension}",
                    "current_status": status.get("status", "missing"),
                    "path": status.get("path", ""),
                    "recommendation": f"run or repair {dimension} before continuing",
                }
            )
    return {
        "gate": gate_name,
        "status": "blocked" if issues else "passed" if required else "skipped",
        "required": required,
        "blocking": bool(issues),
        "blocking_issues": issues,
        "target_asset_id": target_asset_id,
        "target_asset_path": _display_path(root, target_asset_path),
        "project_id": project_id,
        "workspace_path": workspace_path,
        "required_dimensions": required_dimensions,
        "gate_statuses": statuses,
        "evidence_refs": _dedupe([str(status.get("path") or "") for status in statuses.values()]),
    }


def _latest_project_gate(storage: LocalStorage, asset_type: str, *, project_id: str, expected_status: str) -> dict[str, Any]:
    asset = _latest_asset(storage, asset_type, project_id=project_id)
    if not asset:
        return {"status": "missing", "blocking": True, "path": ""}
    return {"status": expected_status, "blocking": False, "path": asset.get("path", ""), "asset_id": asset.get("id", "")}


def _latest_target_gate(
    storage: LocalStorage,
    asset_type: str,
    *,
    target_asset_id: str,
    target_asset_path: str | Path,
    project_id: str,
    expected_status: str,
    status_field: str = "status",
) -> dict[str, Any]:
    asset = _latest_asset(storage, asset_type, project_id=project_id, target_asset_id=target_asset_id, target_asset_path=target_asset_path)
    if not asset:
        return {"status": "missing", "blocking": True, "path": ""}
    content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
    status = str(content.get(status_field) or "").strip()
    if status in {"ready", "accepted", "succeeded", "success", "ok"}:
        status = "passed"
    blocking = bool(content.get("blocking")) or status != expected_status
    return {"status": status or "missing", "blocking": blocking, "path": asset.get("path", ""), "asset_id": asset.get("id", "")}


def _style_drift_gate(storage: LocalStorage, *, target_asset_id: str, target_asset_path: str | Path, project_id: str) -> dict[str, Any]:
    asset = _latest_asset(storage, "style_drift_report", project_id=project_id, target_asset_id=target_asset_id, target_asset_path=target_asset_path)
    if not asset:
        return {"status": "missing", "blocking": True, "path": ""}
    content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
    level = str(content.get("drift_level") or "").strip().lower()
    blocking = level in {"high", "critical"} or bool(content.get("blocking"))
    return {"status": "passed" if not blocking and level else "blocked", "blocking": blocking or not level, "path": asset.get("path", ""), "drift_level": level}


def _canon_plugin_gate(storage: LocalStorage, *, target_asset_id: str, target_asset_path: str | Path, project_id: str) -> dict[str, Any]:
    reports = [
        _latest_asset(storage, asset_type, project_id=project_id, target_asset_id=target_asset_id, target_asset_path=target_asset_path)
        for asset_type in CANON_PLUGIN_REPORT_TYPES
    ]
    reports = [report for report in reports if report]
    if not reports:
        return {"status": "missing", "blocking": True, "path": ""}
    blocking = False
    paths: list[str] = []
    for report in reports:
        content = report.get("content", {}) if isinstance(report.get("content", {}), dict) else {}
        paths.append(str(report.get("path") or ""))
        if int(content.get("blocking_issue_count", 0) or 0) > 0:
            blocking = True
    return {"status": "blocked" if blocking else "passed", "blocking": blocking, "path": paths[-1], "paths": paths}


def _quality_report_gate(storage: LocalStorage, *, target_asset_id: str, target_asset_path: str | Path, project_id: str) -> dict[str, Any]:
    reports = [
        _latest_asset(storage, asset_type, project_id=project_id, target_asset_id=target_asset_id, target_asset_path=target_asset_path)
        for asset_type in QUALITY_REPORT_TYPES
    ]
    reports = [report for report in reports if report]
    if not reports:
        return {"status": "missing", "blocking": True, "path": ""}
    report = reports[-1]
    content = report.get("content", {}) if isinstance(report.get("content", {}), dict) else {}
    recommendation = str(content.get("recommendation") or "").strip()
    judge_policy = content.get("judge_policy", {}) if isinstance(content.get("judge_policy", {}), dict) else {}
    provider_backed = str(judge_policy.get("mode") or "") == "provider_backed_judge"
    has_judge = bool(content.get("model_judge_result_paths"))
    blocking = recommendation != "ready" or not provider_backed or not has_judge
    return {
        "status": "passed" if not blocking else "blocked",
        "blocking": blocking,
        "path": report.get("path", ""),
        "asset_id": report.get("id", ""),
        "recommendation": recommendation,
        "provider_backed": provider_backed,
        "model_judge_result_paths": content.get("model_judge_result_paths", []),
    }


def _provider_judge_gate(storage: LocalStorage, quality_gate: dict[str, Any]) -> dict[str, Any]:
    paths = quality_gate.get("model_judge_result_paths", []) if isinstance(quality_gate.get("model_judge_result_paths", []), list) else []
    if not paths:
        return {"status": "missing", "blocking": True, "path": ""}
    existing: list[str] = []
    for path in paths:
        try:
            data = storage.read_json(resolve_path(storage.root, path))
        except (FileNotFoundError, ValueError):
            continue
        if data.get("type") == "model_judge_result":
            existing.append(str(path))
    return {"status": "passed" if existing else "missing", "blocking": not bool(existing), "path": existing[-1] if existing else "", "paths": existing}


def _review_issue_gate(storage: LocalStorage, *, target_asset_id: str, project_id: str) -> dict[str, Any]:
    rows = blocking_review_issues(storage, target_asset_id=target_asset_id, project_id=project_id or None)
    return {"status": "passed" if not rows else "blocked", "blocking": bool(rows), "path": "", "blocking_count": len(rows), "issue_paths": [str(row.get("path") or "") for row in rows]}


def _platform_upload_checklist_gate(checklist: dict[str, Any] | None) -> dict[str, Any]:
    payload = checklist if isinstance(checklist, dict) else {}
    status = str(payload.get("status") or "missing")
    blocking = bool(payload.get("blocking")) or status != "passed"
    return {"status": status, "blocking": blocking, "path": "", "summary": payload}


def _latest_asset(
    storage: LocalStorage,
    asset_type: str,
    *,
    project_id: str = "",
    target_asset_id: str = "",
    target_asset_path: str | Path = "",
) -> dict[str, Any]:
    category = ASSET_DIR_BY_TYPE.get(asset_type)
    categories = [category] if category else ["runs", "reviews", "genres", "styles", "publishing", "platforms"]
    rows: list[dict[str, Any]] = []
    target_display = _display_path(storage.root, target_asset_path)
    for item in categories:
        if not item:
            continue
        for path in storage.list_json(item):
            data = _read_json_safe(storage, path)
            if data.get("type") != asset_type:
                continue
            metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
            content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
            row_project = str(metadata.get("project_id") or content.get("project_id") or "")
            if project_id and row_project and row_project != project_id:
                continue
            if target_asset_id and not _target_matches(content, target_asset_id=target_asset_id):
                continue
            if target_display and not _target_path_matches(content, metadata, target_display=target_display):
                continue
            data["path"] = _display_path(storage.root, path)
            rows.append(data)
    return sorted(rows, key=lambda row: str(row.get("updated_at") or row.get("created_at") or row.get("content", {}).get("created_at", "")))[-1] if rows else {}


def _target_matches(content: dict[str, Any], *, target_asset_id: str) -> bool:
    ids = content.get("target_asset_ids") if isinstance(content.get("target_asset_ids"), list) else []
    return str(content.get("target_asset_id") or "") == target_asset_id or target_asset_id in {str(item) for item in ids}


def _target_path_matches(content: dict[str, Any], metadata: dict[str, Any], *, target_display: str) -> bool:
    candidates = {
        str(content.get("target_asset_path") or ""),
        str(content.get("source_draft_path") or ""),
        str(content.get("draft_path") or ""),
        str(metadata.get("target_asset_path") or ""),
    }
    return not any(candidates) or target_display in candidates


def _contains_sensitive_marker(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in ["forbidden_platform_term", "敏感违禁词", "平台禁词"])


def _read_json_safe(storage: LocalStorage, path: Path) -> dict[str, Any]:
    try:
        data = storage.read_json(path)
    except (FileNotFoundError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _display_path(root: Path, path: str | Path) -> str:
    if not path:
        return ""
    candidate = Path(path)
    try:
        return str(candidate.relative_to(root))
    except ValueError:
        return str(candidate)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result
