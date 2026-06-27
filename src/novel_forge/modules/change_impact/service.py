from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.constants import DATA_DIRS
from novel_forge.core.ids import utc_now
from novel_forge.modules.common import resolve_path, run_metadata
from novel_forge.modules.production_context import filter_project_safe_references, project_scope_from_asset
from novel_forge.schemas import ChangeImpactReport, validate_common_fields
from novel_forge.storage.local import LocalStorage

HIGH_IMPACT_TYPES = {
    "chapter_plan",
    "chapter_plan_version",
    "draft_chapter",
    "draft_version",
    "review_report",
    "revision_plan",
    "chapter_audit_report",
    "publish_gate_report",
    "release_package",
}
BLOCKING_TYPES = {"publish_gate_report", "release_package"}


def create_change_impact_report(
    storage: LocalStorage,
    target_path: str | Path,
    *,
    max_depth: int = 4,
    project_id: str | None = None,
) -> dict[str, Any]:
    target_file = resolve_path(storage.root, target_path)
    target = storage.read_asset(target_file)
    target_ref = _display_path(storage.root, target_file)
    project = project_scope_from_asset(storage, target, input_path=target_file)
    scope_project_id = project_id or str(project.get("project_id", ""))
    records = _project_records(storage, scope_project_id)
    target_keys = {target.id, target_ref}
    impacted, edges = _downstream_impacts(records, target_keys, max_depth=max_depth)
    summary = _severity_summary(impacted)
    recommendation = _recommendation(summary)
    asset = ChangeImpactReport(
        title=f"Change impact for {target.title or target.id}",
        source=target.id,
        tags=["change-impact", recommendation],
        content={
            "target_asset_id": target.id,
            "target_asset_type": target.type,
            "target_path": target_ref,
            "project_id": scope_project_id,
            "max_depth": max_depth,
            "impacted_assets": impacted,
            "impact_edges": edges,
            "severity_summary": summary,
            "recommendation": recommendation,
            "generated_at": utc_now(),
        },
        metadata={
            "project_id": scope_project_id,
            "workspace_path": str(project.get("workspace_path", "")),
            "target_asset_path": target_ref,
            "run_metadata": run_metadata("change_impact_report", target),
        },
        references=filter_project_safe_references(
            storage,
            scope_project_id,
            _dedupe([target.id, target_ref, *[str(item.get("id", "")) for item in impacted], *[str(item.get("path", "")) for item in impacted]]),
        ),
    )
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "asset": asset.to_dict(), "validation": {"ok": True, "errors": []}}


def list_change_impact_reports(storage: LocalStorage, *, project_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in reversed(storage.list_json("continuity")):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "change_impact_report":
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if project_id and str(metadata.get("project_id", "")) != project_id:
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        rows.append(
            {
                "path": _display_path(storage.root, path),
                "id": data.get("id", ""),
                "title": data.get("title") or data.get("name", ""),
                "target_path": content.get("target_path", ""),
                "target_asset_type": content.get("target_asset_type", ""),
                "impacted_count": len(content.get("impacted_assets", []) if isinstance(content.get("impacted_assets", []), list) else []),
                "recommendation": content.get("recommendation", ""),
                "severity_summary": content.get("severity_summary", {}),
                "project_id": metadata.get("project_id", ""),
                "workspace_path": metadata.get("workspace_path", ""),
                "updated_at": data.get("updated_at", ""),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _project_records(storage: LocalStorage, project_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for category in DATA_DIRS:
        for path in storage.list_json(category):
            try:
                data = storage.read_json(path)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            if project_id:
                scope = project_scope_from_asset(storage, data, input_path=path)
                record_project_id = str(scope.get("project_id", ""))
                if record_project_id and record_project_id != project_id:
                    continue
            rows.append(
                {
                    "path": _display_path(storage.root, path),
                    "id": str(data.get("id", "")),
                    "type": str(data.get("type", "")),
                    "title": str(data.get("title") or data.get("name") or ""),
                    "data": data,
                    "refs": _reference_values(data),
                }
            )
    return rows


def _downstream_impacts(records: list[dict[str, Any]], target_keys: set[str], *, max_depth: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    impacted_by_path: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    frontier = set(target_keys)
    seen_keys = set(target_keys)
    for depth in range(1, max_depth + 1):
        next_frontier: set[str] = set()
        for record in records:
            if record["id"] in seen_keys or record["path"] in seen_keys:
                continue
            matched = sorted(frontier & set(record["refs"]))
            if not matched:
                continue
            severity = _severity(record["type"], depth)
            impacted_by_path[record["path"]] = {
                "id": record["id"],
                "path": record["path"],
                "type": record["type"],
                "title": record["title"],
                "depth": depth,
                "severity": severity,
                "reason": f"references changed asset via {', '.join(matched[:3])}",
                "recommended_action": _recommended_action(record["type"], severity),
            }
            for source in matched:
                edges.append({"source": source, "target": record["path"], "depth": depth, "relation": "references"})
            next_frontier.update({record["id"], record["path"]})
        if not next_frontier:
            break
        seen_keys.update(next_frontier)
        frontier = next_frontier
    impacted = sorted(impacted_by_path.values(), key=lambda item: (item["depth"], item["path"]))
    return impacted, edges


def _reference_values(data: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    for value in [data.get("source")]:
        if value:
            values.add(str(value))
    for reference in data.get("references", []) if isinstance(data.get("references", []), list) else []:
        if reference:
            values.add(str(reference))
    for payload in [
        data.get("content", {}) if isinstance(data.get("content", {}), dict) else {},
        data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {},
    ]:
        _collect_reference_like_values(payload, values)
    return values


def _collect_reference_like_values(value: Any, values: set[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower()
            if any(token in lowered for token in ["asset_id", "asset_path", "path", "source", "draft_id", "plan_id", "bundle_id"]):
                if isinstance(item, (str, int, float)):
                    values.add(str(item))
            _collect_reference_like_values(item, values)
    elif isinstance(value, list):
        for item in value:
            _collect_reference_like_values(item, values)


def _severity(asset_type: str, depth: int) -> str:
    if asset_type in BLOCKING_TYPES and depth <= 2:
        return "blocking"
    if asset_type in HIGH_IMPACT_TYPES and depth <= 3:
        return "high"
    if depth <= 2:
        return "medium"
    return "low"


def _recommended_action(asset_type: str, severity: str) -> str:
    if severity == "blocking":
        return "block publish and regenerate/review downstream artifact"
    if asset_type in {"draft_chapter", "draft_version", "review_report", "chapter_audit_report"}:
        return "rerun review or regenerate downstream chapter artifact"
    if asset_type in {"outline", "chapter_plan", "chapter_plan_version"}:
        return "review planning consistency before next generation"
    return "inspect lineage and confirm whether stale"


def _severity_summary(impacted: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"blocking": 0, "high": 0, "medium": 0, "low": 0}
    for item in impacted:
        severity = str(item.get("severity", "low"))
        summary[severity] = summary.get(severity, 0) + 1
    return summary


def _recommendation(summary: dict[str, int]) -> str:
    if summary.get("blocking", 0):
        return "block_until_resolved"
    if summary.get("high", 0):
        return "regenerate_downstream"
    if summary.get("medium", 0) or summary.get("low", 0):
        return "review_impacts"
    return "no_action"


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
