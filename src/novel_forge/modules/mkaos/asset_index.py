from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.asset_scan import iter_json_objects
from novel_forge.modules.common import resolve_path
from novel_forge.storage.local import LocalStorage


def find_asset(
    storage: LocalStorage,
    ref: str | Path,
    *,
    asset_type: str | None = None,
    categories: list[str] | None = None,
) -> tuple[Path, dict[str, Any]]:
    value = str(ref)
    if not value:
        raise FileNotFoundError("empty asset reference")
    if "/" in value or value.endswith(".json"):
        path = resolve_path(storage.root, value)
        data = storage.read_json(path)
        if isinstance(data, dict) and (not asset_type or data.get("type") == asset_type):
            return path, data
    for category in categories or ["raw", "knowledge", "quality_standards", "templates", "contexts", "runs", "continuity"]:
        for path, data in iter_json_objects(storage, category, reverse=True, context="mkaos asset scan"):
            if asset_type and data.get("type") != asset_type:
                continue
            if value in {str(data.get("id", "")), _display_path(storage.root, path)}:
                return path, data
    raise FileNotFoundError(f"asset not found: {ref}")


def list_assets(
    storage: LocalStorage,
    category: str,
    asset_type: str,
    *,
    project_id: str | None = None,
    mkaos_only: bool | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path, data in iter_json_objects(storage, category, reverse=True, context="mkaos asset scan"):
        if len(rows) >= limit:
            break
        if data.get("type") != asset_type:
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        record_project = str(metadata.get("project_id") or content.get("project_id") or "")
        if project_id and record_project and record_project != project_id:
            continue
        if mkaos_only is True and not (metadata.get("mkaos") or content.get("mkaos_source")):
            continue
        rows.append(asset_row(storage, path, data))
    return rows


def asset_row(storage: LocalStorage, path: Path, data: dict[str, Any]) -> dict[str, Any]:
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    return {
        "path": _display_path(storage.root, path),
        "id": data.get("id", ""),
        "type": data.get("type", ""),
        "title": data.get("title") or data.get("name", ""),
        "source": data.get("source", ""),
        "tags": data.get("tags", []),
        "project_id": metadata.get("project_id") or content.get("project_id") or "",
        "workspace_path": metadata.get("workspace_path") or content.get("workspace_path") or "",
        "status": content.get("status") or metadata.get("asset_status") or "",
        "risk_level": content.get("risk_level") or metadata.get("risk_level") or "",
        "content": content,
        "metadata": metadata,
        "updated_at": data.get("updated_at", ""),
        "asset": data,
    }


def _display_path(root: Path, path: str | Path) -> str:
    candidate = Path(path)
    try:
        return str(candidate.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(candidate)
