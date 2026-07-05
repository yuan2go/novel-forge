from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.asset_scan import iter_json_objects, read_json_for_scan
from novel_forge.core.constants import DATA_DIRS
from novel_forge.modules.common import resolve_path
from novel_forge.storage.local import LocalStorage


def find_asset_binding(storage: LocalStorage, asset_type: str, value: str) -> dict[str, str] | None:
    if not value:
        return None
    candidate = resolve_path(storage.root, value)
    paths = [candidate] if candidate.exists() and candidate.is_file() else []
    for category in DATA_DIRS:
        paths.extend(storage.list_json(category))
    seen: set[Path] = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        data = _read_product_scan_asset(storage, path, context="product asset binding scan")
        if not data or data.get("type") != asset_type:
            continue
        display_path = display_path_for(storage.root, path)
        if value in {display_path, str(path), str(data.get("id", ""))}:
            return {"id": str(data.get("id", "")), "path": display_path}
    return None


def asset_records(storage: LocalStorage) -> list[dict[str, Any]]:
    records = []
    for category in DATA_DIRS:
        for path, data in iter_json_objects(storage, category, context="product asset record scan"):
            records.append(
                {
                    "id": str(data.get("id", "")),
                    "path": display_path_for(storage.root, path),
                    "absolute_path": path,
                    "category": category,
                    "type": data.get("type", ""),
                    "title": data.get("title") or data.get("name", ""),
                    "data": data,
                }
            )
    return records


def asset_path_by_id(storage: LocalStorage, category: str, asset_id: str) -> Path | None:
    if not asset_id:
        return None
    for path, data in iter_json_objects(storage, category, context="product asset id lookup"):
        if data.get("id") == asset_id:
            return path
    return None


def display_path_for(root: str | Path, path: Path) -> str:
    try:
        return str(path.relative_to(Path(root)))
    except ValueError:
        return str(path)


def _read_product_scan_asset(storage: LocalStorage, path: Path, *, context: str) -> dict[str, Any]:
    return read_json_for_scan(storage, path, context=context)
