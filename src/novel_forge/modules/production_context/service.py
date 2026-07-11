from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.constants import ASSET_DIR_BY_TYPE, SKILL_NAMES
from novel_forge.core.ids import utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.storage.local import LocalStorage

PROFILE_BINDINGS = {
    "platform_profile": ("platform_profile_id", "platform_profile_path"),
    "genre_market_profile": ("genre_market_profile_id", "genre_market_profile_path"),
    "creative_strategy_profile": ("creative_strategy_profile_id", "creative_strategy_profile_path"),
    "quality_standard_profile": ("quality_standard_profile_id", "quality_standard_profile_path"),
    "style_profile": ("style_profile_id", "style_profile_path"),
    "style_blend_preset": ("style_blend_preset_id", "style_blend_preset_path"),
    "continuity_bible": ("continuity_bible_id", "continuity_bible_path"),
}
OPTIONAL_PROFILE_TYPES = {"style_blend_preset"}
REQUIRED_PROFILE_TYPES = tuple(asset_type for asset_type in PROFILE_BINDINGS if asset_type not in OPTIONAL_PROFILE_TYPES)


def build_production_context(
    storage: LocalStorage,
    input_asset: Any,
    *,
    input_path: str | Path | None = None,
    workspace_path: str | None = None,
) -> dict[str, Any]:
    project = project_scope_from_asset(storage, input_asset, input_path=input_path, workspace_path=workspace_path)
    binding_events = ensure_required_project_bindings(storage, project)
    if binding_events:
        refreshed = project_scope_from_asset(storage, input_asset, input_path=input_path, workspace_path=project.get("workspace_path", ""))
        project = refreshed or project
    config = project.get("project_config", {}) if isinstance(project.get("project_config", {}), dict) else {}
    warnings: list[str] = []
    profiles: dict[str, dict[str, Any] | None] = {}
    for asset_type in PROFILE_BINDINGS:
        profile, warning = _resolve_profile(storage, asset_type, project, config)
        profiles[asset_type] = profile
        if warning and asset_type not in OPTIONAL_PROFILE_TYPES:
            warnings.append(warning)
    payload = {
        "project": {
            "project_id": project.get("project_id", ""),
            "workspace_path": project.get("workspace_path", ""),
            "title": project.get("title", ""),
        },
        "project_config": config,
        "profiles": profiles,
        "preflight": {
            "ready": not warnings,
            "warnings": warnings,
            "missing": [asset_type for asset_type, profile in profiles.items() if profile is None and asset_type not in OPTIONAL_PROFILE_TYPES],
            "binding_events": binding_events,
        },
    }
    payload["profile_references"] = profile_reference_ids(payload)
    return payload


def ensure_required_project_bindings(storage: LocalStorage, project: dict[str, Any]) -> list[dict[str, str]]:
    """Create or bind required V6 production profiles for a project.

    This keeps old CLI/workflow entry points aligned with the product project
    flow: when a project can be resolved, chapter production always has platform,
    genre, quality, style, and continuity inputs.
    """

    project_id = str(project.get("project_id", "") or "")
    workspace_path = str(project.get("workspace_path", "") or "")
    if not project_id or not workspace_path:
        return []
    workspace_file = resolve_path(storage.root, workspace_path)
    if not workspace_file.exists():
        return []
    try:
        workspace_data = storage.read_json(workspace_file)
    except Exception:
        return []
    if not isinstance(workspace_data, dict):
        return []
    content = workspace_data.get("content", {}) if isinstance(workspace_data.get("content", {}), dict) else {}
    config = content.get("project_config", {}) if isinstance(content.get("project_config", {}), dict) else {}
    events: list[dict[str, str]] = []
    changed = False
    for asset_type in REQUIRED_PROFILE_TYPES:
        id_key, path_key = PROFILE_BINDINGS[asset_type]
        existing = None
        for value in [config.get(path_key), config.get(id_key)]:
            existing = _asset_by_path_or_id(storage, str(value or ""), asset_type)
            if existing:
                break
        if not existing:
            existing = _latest_project_asset(storage, asset_type, project_id)
        if existing and existing.get("path"):
            normalized, migration_event = _normalize_profile_storage(storage, existing)
            if migration_event:
                existing = normalized
                events.append(migration_event)
                changed = True
            if config.get(id_key) != existing.get("id") or config.get(path_key) != existing.get("path"):
                config[id_key] = str(existing.get("id", ""))
                config[path_key] = str(existing.get("path", ""))
                events.append({"asset_type": asset_type, "action": "bound_existing", "path": str(existing.get("path", ""))})
                changed = True
            continue
        created = _create_default_profile_asset(storage, project, asset_type)
        config[id_key] = created["id"]
        config[path_key] = created["path"]
        events.append({"asset_type": asset_type, "action": "created_default", "path": created["path"]})
        changed = True
    if changed:
        content["project_config"] = config
        workspace_data["content"] = content
        workspace_data["updated_at"] = utc_now()
        metadata = workspace_data.get("metadata", {}) if isinstance(workspace_data.get("metadata", {}), dict) else {}
        metadata["production_bindings_ready"] = True
        workspace_data["metadata"] = metadata
        storage.write_json(workspace_file, workspace_data)
        project["project_config"] = config
    return events


def quality_dimensions_from_context(context: dict[str, Any]) -> list[str]:
    profile = _profile(context, "quality_standard_profile")
    content = profile.get("content", {}) if profile else {}
    dimensions = content.get("dimensions", {}) if isinstance(content, dict) else {}
    if isinstance(dimensions, dict) and dimensions:
        return [str(key) for key in dimensions.keys()]
    return []


def profile_reference_ids(context: dict[str, Any]) -> list[str]:
    values: list[str] = []
    profiles = context.get("profiles", {}) if isinstance(context.get("profiles", {}), dict) else {}
    for profile in profiles.values():
        if not isinstance(profile, dict):
            continue
        asset_id = str(profile.get("id", "") or "")
        path = str(profile.get("path", "") or "")
        if asset_id:
            values.append(asset_id)
        if path:
            values.append(path)
    return _dedupe(values)


def filter_project_safe_references(storage: LocalStorage, project_id: str, references: list[str]) -> list[str]:
    refs = _dedupe([reference for reference in references if reference])
    if not project_id:
        return refs
    project_index = _project_id_index_for_references(storage, refs)
    safe: list[str] = []
    for reference in refs:
        if not _reference_may_be_asset(reference):
            safe.append(reference)
            continue
        linked_project_id = project_index.get(reference, "")
        if linked_project_id and linked_project_id != project_id:
            continue
        safe.append(reference)
    return _dedupe(safe)


def project_scope_from_asset(
    storage: LocalStorage,
    input_asset: Any,
    *,
    input_path: str | Path | None = None,
    workspace_path: str | None = None,
) -> dict[str, Any]:
    explicit = _workspace_path(storage, workspace_path)
    if explicit:
        return explicit
    data = input_asset.to_dict() if hasattr(input_asset, "to_dict") else input_asset
    if isinstance(data, dict):
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        for value in [
            metadata.get("workspace_path"),
            metadata.get("workspace_id"),
            metadata.get("project_id"),
            content.get("workspace_path"),
            content.get("project_id"),
        ]:
            project = _workspace_path(storage, str(value or ""))
            if project:
                return project
        direct_project_id = str(metadata.get("project_id") or content.get("project_id") or "").strip()
        if direct_project_id:
            return {
                "project_id": direct_project_id,
                "workspace_path": str(metadata.get("workspace_path") or content.get("workspace_path") or ""),
                "title": "",
                "project_config": {},
            }
        for reference in data.get("references", []) if isinstance(data.get("references", []), list) else []:
            project = _workspace_path(storage, str(reference or ""))
            if project:
                return project
    if input_path:
        try:
            raw = storage.read_json(resolve_path(storage.root, input_path))
        except Exception:
            raw = None
        if isinstance(raw, dict):
            return project_scope_from_asset(storage, raw)
    projects = _project_rows(storage)
    if len(projects) == 1:
        return projects[0]
    return {"project_id": "", "workspace_path": "", "title": "", "project_config": {}}


def _resolve_profile(
    storage: LocalStorage,
    asset_type: str,
    project: dict[str, Any],
    config: dict[str, Any],
) -> tuple[dict[str, Any] | None, str]:
    id_key, path_key = PROFILE_BINDINGS[asset_type]
    for value in [config.get(path_key), config.get(id_key)]:
        profile = _asset_by_path_or_id(storage, str(value or ""), asset_type)
        if profile:
            return profile, ""
    fallback = _latest_project_asset(storage, asset_type, str(project.get("project_id", "")))
    if fallback:
        return fallback, f"{asset_type} not explicitly bound; using latest project asset"
    global_fallback = _latest_project_asset(storage, asset_type, "")
    if global_fallback:
        return global_fallback, f"{asset_type} not project-bound; using latest global asset"
    return None, f"missing {asset_type}"


def _asset_by_path_or_id(storage: LocalStorage, value: str, asset_type: str) -> dict[str, Any] | None:
    if not value:
        return None
    candidates: list[Path] = []
    candidate = resolve_path(storage.root, value)
    if candidate.exists() and candidate.is_file():
        candidates.append(candidate)
    category = ASSET_DIR_BY_TYPE.get(asset_type)
    if category:
        candidates.extend(reversed(storage.list_json(category)))
    for path in candidates:
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != asset_type:
            continue
        if value in {str(data.get("id", "")), _display_path(storage.root, path), str(path)}:
            return _asset_payload(storage, path, data)
    return None


def _project_id_for_reference(storage: LocalStorage, reference: str) -> str:
    if not _reference_may_be_asset(reference):
        return ""
    value = str(reference or "").strip()
    candidate = resolve_path(storage.root, value)
    if not candidate.exists() and not value.startswith("data/"):
        candidate = storage.data_root / value
    if candidate.exists() and candidate.is_file():
        try:
            data = storage.read_json(candidate)
        except Exception:
            return ""
        return _project_id_from_data(data)
    if "/" in value or value.endswith(".json"):
        return ""
    for category in _candidate_categories_for_reference(reference):
        for path in storage.list_json(category):
            try:
                data = storage.read_json(path)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            if reference in {str(data.get("id", "")), _display_path(storage.root, path)}:
                return _project_id_from_data(data)
    return ""


def _project_id_index_for_references(storage: LocalStorage, references: list[str]) -> dict[str, str]:
    index: dict[str, str] = {}
    categories: list[str] = []
    for reference in references:
        if not _reference_may_be_asset(reference):
            continue
        value = str(reference or "").strip()
        candidate = resolve_path(storage.root, value)
        if not candidate.exists() and not value.startswith("data/"):
            candidate = storage.data_root / value
        if candidate.exists() and candidate.is_file():
            try:
                data = storage.read_json(candidate)
            except Exception:
                continue
            _index_project_reference(storage, index, candidate, data)
            continue
        if "/" in value or value.endswith(".json"):
            continue
        categories.extend(_candidate_categories_for_reference(reference))
    for category in list(dict.fromkeys(categories)):
        if category == "runs":
            continue
        index.update(_cached_category_project_index(storage, category))
    return index


def _index_project_reference(storage: LocalStorage, index: dict[str, str], path: Path, data: Any) -> list[str]:
    if not isinstance(data, dict):
        return []
    project_id = _project_id_from_data(data)
    if not project_id:
        return []
    keys: list[str] = []
    asset_id = str(data.get("id", "") or "")
    if asset_id:
        index[asset_id] = project_id
        keys.append(asset_id)
    display_path = _display_path(storage.root, path)
    index[display_path] = project_id
    keys.append(display_path)
    index[str(path)] = project_id
    keys.append(str(path))
    return keys


def _cached_category_project_index(storage: LocalStorage, category: str) -> dict[str, str]:
    paths = storage.list_json(category)
    cache = getattr(storage, "_production_context_project_ref_index_cache", None)
    if not isinstance(cache, dict):
        cache = {}
        setattr(storage, "_production_context_project_ref_index_cache", cache)
    cached = cache.setdefault(category, {"index": {}, "paths": {}})
    if not isinstance(cached, dict):
        cached = {"index": {}, "paths": {}}
        cache[category] = cached
    index = cached.get("index")
    path_entries = cached.get("paths")
    if not isinstance(index, dict) or not isinstance(path_entries, dict):
        index = {}
        path_entries = {}
        cached["index"] = index
        cached["paths"] = path_entries
    current_paths = {str(path): path for path in paths}
    for path_key in list(path_entries.keys()):
        if path_key in current_paths:
            continue
        entry = path_entries.pop(path_key, {})
        for key in entry.get("keys", []) if isinstance(entry, dict) else []:
            index.pop(key, None)
    for path in paths:
        path_key = str(path)
        try:
            mtime_ns = path.stat().st_mtime_ns
        except OSError:
            continue
        entry = path_entries.get(path_key)
        if isinstance(entry, dict) and entry.get("mtime_ns") == mtime_ns:
            continue
        if isinstance(entry, dict):
            for key in entry.get("keys", []):
                index.pop(key, None)
        try:
            data = storage.read_json(path)
        except Exception:
            path_entries[path_key] = {"mtime_ns": mtime_ns, "keys": []}
            continue
        path_entries[path_key] = {
            "mtime_ns": mtime_ns,
            "keys": _index_project_reference(storage, index, path, data),
        }
    return index


def _candidate_categories_for_reference(reference: str) -> list[str]:
    value = str(reference or "").strip()
    if "/" in value or value.endswith(".json"):
        return list(dict.fromkeys(ASSET_DIR_BY_TYPE.values()))
    categories: list[str] = []
    for asset_type, category in ASSET_DIR_BY_TYPE.items():
        prefix = asset_type.replace("_", "-")
        if value.startswith(f"{prefix}-"):
            categories.append(category)
    if value.startswith(("project-", "workspace-")):
        categories.append(ASSET_DIR_BY_TYPE.get("project_workspace_state", "workspaces"))
    return list(dict.fromkeys(categories))


def _reference_may_be_asset(reference: str) -> bool:
    value = str(reference or "").strip()
    if not value:
        return False
    if value in SKILL_NAMES:
        return False
    if value.startswith(("http://", "https://", "skill:", "mailto:")):
        return False
    if "/" in value or value.endswith(".json"):
        return True
    asset_prefixes = {asset_type.replace("_", "-") for asset_type in ASSET_DIR_BY_TYPE}
    asset_prefixes.update({"project", "workspace"})
    return any(value.startswith(f"{prefix}-") for prefix in asset_prefixes)


def _project_id_from_data(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    if data.get("type") == "project_workspace_state":
        return str(content.get("project_id") or data.get("id") or "")
    return str(metadata.get("project_id") or content.get("project_id") or "")


def _latest_project_asset(storage: LocalStorage, asset_type: str, project_id: str) -> dict[str, Any] | None:
    category = ASSET_DIR_BY_TYPE.get(asset_type)
    if not category:
        return None
    for path in reversed(storage.list_json(category)):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != asset_type:
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        record_project = str(metadata.get("project_id") or "")
        if project_id:
            if record_project == project_id:
                return _asset_payload(storage, path, data)
        elif not record_project:
            return _asset_payload(storage, path, data)
    return None


def _create_default_profile_asset(storage: LocalStorage, project: dict[str, Any], asset_type: str) -> dict[str, str]:
    from novel_forge.modules.creative_assets import create_creative_asset

    title_by_type = {
        "platform_profile": f"{project.get('title') or 'Project'} platform profile",
        "genre_market_profile": f"{project.get('title') or 'Project'} genre market profile",
        "creative_strategy_profile": f"{project.get('title') or 'Project'} creative strategy",
        "quality_standard_profile": f"{project.get('title') or 'Project'} quality standard",
        "style_profile": f"{project.get('title') or 'Project'} style profile",
        "continuity_bible": f"{project.get('title') or 'Project'} continuity bible",
    }
    created = create_creative_asset(
        storage,
        {
            "asset_type": asset_type,
            "title": title_by_type.get(asset_type, f"{project.get('title') or 'Project'} {asset_type}"),
            "scope": "project",
            "project_id": str(project.get("project_id", "")),
            "workspace_path": str(project.get("workspace_path", "")),
            "metadata": {
                "project_asset_role": f"project-binding:{asset_type}",
                "asset_status": "active",
                "auto_created_for_production_context": True,
            },
        },
    )
    return {"id": str(created["asset"]["id"]), "path": str(created["path"])}


def _normalize_profile_storage(storage: LocalStorage, profile: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str] | None]:
    asset_type = str(profile.get("type", ""))
    expected_category = ASSET_DIR_BY_TYPE.get(asset_type, "")
    current_path = str(profile.get("path", "") or "")
    if not expected_category or not current_path or current_path.startswith(f"data/{expected_category}/"):
        return profile, None
    source_path = resolve_path(storage.root, current_path)
    if not source_path.exists() or not source_path.is_file():
        return profile, None
    if asset_type not in {"continuity_bible", "foreshadowing_thread", "power_scale_rule"}:
        return profile, None
    try:
        data = storage.read_json(source_path)
    except Exception:
        return profile, None
    if not isinstance(data, dict) or data.get("type") != asset_type:
        return profile, None
    dest_path = storage.data_dir(expected_category) / source_path.name
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    if _display_path(storage.root, dest_path) != current_path:
        metadata.setdefault("migrated_from_path", current_path)
        metadata["storage_category"] = expected_category
        data["metadata"] = metadata
        data["updated_at"] = utc_now()
        if not dest_path.exists():
            storage.write_json(dest_path, data)
    normalized = _asset_payload(storage, dest_path, data)
    return normalized, {
        "asset_type": asset_type,
        "action": "migrated_storage_category",
        "from_path": current_path,
        "path": _display_path(storage.root, dest_path),
    }


def _profile(context: dict[str, Any], asset_type: str) -> dict[str, Any]:
    profiles = context.get("profiles", {}) if isinstance(context.get("profiles", {}), dict) else {}
    profile = profiles.get(asset_type)
    return profile if isinstance(profile, dict) else {}


def _workspace_path(storage: LocalStorage, value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    candidate = resolve_path(storage.root, value)
    if candidate.exists() and candidate.is_file():
        try:
            data = storage.read_json(candidate)
        except Exception:
            data = None
        if isinstance(data, dict) and data.get("type") == "project_workspace_state":
            return _project_payload(storage, candidate, data)
    for path in storage.list_json("workspaces"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if value in {str(data.get("id", "")), str(content.get("project_id", "")), _display_path(storage.root, path), str(path)}:
            return _project_payload(storage, path, data)
    return None


def _project_rows(storage: LocalStorage) -> list[dict[str, Any]]:
    rows = []
    for path in storage.list_json("workspaces"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if isinstance(data, dict) and data.get("type") == "project_workspace_state":
            rows.append(_project_payload(storage, path, data))
    return rows


def _project_payload(storage: LocalStorage, path: Path, data: dict[str, Any]) -> dict[str, Any]:
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    return {
        "id": data.get("id", ""),
        "project_id": content.get("project_id", data.get("id", "")),
        "workspace_path": _display_path(storage.root, path),
        "title": data.get("title") or data.get("name", ""),
        "project_config": content.get("project_config", {}) if isinstance(content.get("project_config", {}), dict) else {},
    }


def _asset_payload(storage: LocalStorage, path: Path, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": _display_path(storage.root, path),
        "id": data.get("id", ""),
        "type": data.get("type", ""),
        "title": data.get("title") or data.get("name", ""),
        "content": data.get("content", {}) if isinstance(data.get("content", {}), dict) else {},
        "metadata": data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {},
    }


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
