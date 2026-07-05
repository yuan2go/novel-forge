from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from novel_forge.core.constants import ASSET_DIR_BY_TYPE, DATA_DIRS, SKILL_NAMES
from novel_forge.core.ids import utc_now
from novel_forge.schemas import BaseAsset, asset_from_dict
from novel_forge.storage.locks import StorageLock

NOVEL_KG_SOURCE_TYPES = {
    "character_card",
    "world_bible",
    "continuity_bible",
    "foreshadowing_thread",
    "power_scale_rule",
    "review_rule_pack",
    "quality_standard_profile",
    "writing_template",
    "craft_template",
    "material_card",
    "knowledge_card",
    "knowledge_usage_binding",
    "rule_card",
    "template_card",
    "knowledge_pack",
    "outline",
    "outline_version",
    "long_form_macro_plan",
    "chapter_plan",
    "chapter_plan_version",
    "draft_chapter",
    "draft_version",
    "chapter_audit_report",
    "review_report",
    "review_issue",
    "revision_task",
    "revision_plan",
    "canon_graph_snapshot",
    "canon_patch",
    "canon_database",
    "chapter_state",
    "chapter_pattern_report",
    "fact_ledger",
    "arc_plan",
    "foreshadowing_graph",
    "motif_budget_report",
    "character_state_ledger",
    "villain_operation_plan",
    "reward_ledger",
}


class LocalStorage:
    def __init__(self, root: str | Path = ".") -> None:
        self.root = Path(root).resolve()
        self.data_root = self.root / "data"

    def ensure_layout(self) -> None:
        for rel in DATA_DIRS:
            (self.data_root / rel).mkdir(parents=True, exist_ok=True)
        for rel in ["indexes", "backups", ".locks"]:
            (self.data_root / rel).mkdir(parents=True, exist_ok=True)
        for rel in ["examples/sample_inputs", "examples/sample_outputs", "examples/sample_project"]:
            (self.root / rel).mkdir(parents=True, exist_ok=True)

    def data_dir(self, category: str) -> Path:
        return self.data_root / category

    def write_json(self, path: str | Path, data: Any) -> Path:
        resolved = self.root / path if not Path(path).is_absolute() else Path(path)
        self._enforce_project_scope_write(resolved, data)
        with StorageLock(self.root, str(resolved.relative_to(self.root)) if resolved.is_relative_to(self.root) else resolved.name):
            self._write_json_atomic(resolved, data, backup_existing=True)
        self._sync_postgres_write_through(resolved)
        self._mark_novel_kg_dirty(resolved, data)
        return resolved

    def read_json(self, path: str | Path) -> Any:
        resolved = self.root / path if not Path(path).is_absolute() else Path(path)
        return json.loads(resolved.read_text(encoding="utf-8"))

    def write_asset(self, category: str, asset: BaseAsset) -> Path:
        self.ensure_layout()
        path = self.data_dir(category) / f"{asset.id}.json"
        data = asset.to_dict()
        self._enforce_project_scope_write(path, data)
        with StorageLock(self.root, f"{category}-{asset.id}"):
            self._write_json_atomic(path, data, backup_existing=True)
        self._sync_postgres_write_through(path)
        self._mark_novel_kg_dirty(path, data)
        return path

    def write_asset_auto(self, asset: BaseAsset) -> Path:
        category = ASSET_DIR_BY_TYPE.get(asset.type)
        if not category:
            raise ValueError(f"no data directory mapping for asset type: {asset.type}")
        return self.write_asset(category, asset)

    def list_json(self, category: str) -> list[Path]:
        folder = self.data_dir(category)
        if not folder.exists():
            return []
        return sorted(folder.glob("*.json"), key=lambda path: path.stat().st_mtime)

    def latest(self, category: str) -> Path:
        files = self.list_json(category)
        if not files:
            raise FileNotFoundError(f"no JSON assets found in data/{category}")
        return files[-1]

    def read_asset(self, path: str | Path) -> BaseAsset:
        data = self.read_json(path)
        if not isinstance(data, dict):
            raise ValueError(f"asset JSON must be an object: {path}")
        return asset_from_dict(data)

    def counts(self) -> dict[str, int]:
        return {category: len(self.list_json(category)) for category in DATA_DIRS}

    def _write_json_atomic(self, path: Path, data: Any, backup_existing: bool) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if backup_existing and path.exists() and _is_data_asset_path(self, path):
            self._backup_existing(path)
        tmp_path = path.with_name(f".{path.name}.tmp")
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp_path.replace(path)

    def _backup_existing(self, path: Path) -> Path:
        relative = path.relative_to(self.root)
        stamp = utc_now().replace(":", "").replace("-", "")
        backup_path = self.data_root / "backups" / relative.with_suffix(f".{stamp}.json")
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup_path)
        return backup_path

    def _sync_postgres_write_through(self, path: Path) -> None:
        if not _is_data_asset_path(self, path):
            return
        try:
            from novel_forge.infrastructure.settings import IndustrialSettings
            from novel_forge.storage.postgres import PostgresAssetStore

            settings = IndustrialSettings.from_env(root=self.root)
            if not settings.database_url or not settings.postgres_write_through:
                return
            PostgresAssetStore.from_settings(settings).sync_asset(self, path)
        except Exception:
            try:
                from novel_forge.infrastructure.settings import IndustrialSettings

                strict = IndustrialSettings.from_env(root=self.root).postgres_write_strict
            except Exception:
                strict = False
            if strict:
                raise

    def _enforce_project_scope_write(self, path: Path, data: Any) -> None:
        if os.environ.get("NOVEL_FORGE_DISABLE_PROJECT_SCOPE_WRITE_GUARD", "").strip().lower() in {"1", "true", "yes"}:
            return
        if not _is_data_asset_path(self, path) or not isinstance(data, dict):
            return
        if data.get("type") == "project_workspace_state":
            return
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        project_id = str(metadata.get("project_id") or content.get("project_id") or "")
        if not project_id:
            return
        refs = _asset_reference_values(data)
        project_index = _project_id_index_for_references(self, refs)
        for ref in refs:
            linked_project_id = project_index.get(ref, "")
            if linked_project_id and linked_project_id != project_id:
                relative = str(path.relative_to(self.root)) if path.is_relative_to(self.root) else str(path)
                raise ValueError(
                    f"cross-project write rejected for {relative}: reference {ref} belongs to {linked_project_id}, not {project_id}"
                )

    def _mark_novel_kg_dirty(self, path: Path, data: Any) -> None:
        if not _is_data_asset_path(self, path) or not isinstance(data, dict):
            return
        asset_type = str(data.get("type", ""))
        if asset_type not in NOVEL_KG_SOURCE_TYPES:
            return
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        project_id = str(metadata.get("project_id") or content.get("project_id") or "")
        workspace_path = str(metadata.get("workspace_path") or content.get("workspace_path") or "")
        dirty_path = self.data_root / "indexes" / "novel_kg_dirty.json"
        dirty_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            dirty = self.read_json(dirty_path) if dirty_path.exists() else {}
        except Exception:
            dirty = {}
        entries = dirty.get("entries", []) if isinstance(dirty, dict) and isinstance(dirty.get("entries", []), list) else []
        relative = str(path.relative_to(self.root)) if path.is_relative_to(self.root) else str(path)
        entry_key = (project_id, workspace_path, relative)
        merged: list[dict[str, Any]] = []
        replaced = False
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            key = (str(entry.get("project_id", "")), str(entry.get("workspace_path", "")), str(entry.get("path", "")))
            if key == entry_key:
                entry = {**entry, "asset_type": asset_type, "asset_id": str(data.get("id", "")), "updated_at": utc_now()}
                replaced = True
            merged.append(entry)
        if not replaced:
            merged.append(
                {
                    "project_id": project_id,
                    "workspace_path": workspace_path,
                    "path": relative,
                    "asset_id": str(data.get("id", "")),
                    "asset_type": asset_type,
                    "updated_at": utc_now(),
                }
            )
        payload = {"type": "novel_kg_dirty_index", "updated_at": utc_now(), "entries": merged[-500:]}
        self._write_json_atomic(dirty_path, payload, backup_existing=False)


def _is_data_asset_path(storage: LocalStorage, path: Path) -> bool:
    try:
        relative = path.relative_to(storage.data_root)
    except ValueError:
        return False
    return len(relative.parts) >= 2 and relative.parts[0] in DATA_DIRS


def _asset_reference_values(data: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    source = str(data.get("source", "") or "")
    if source:
        values.add(source)
    if isinstance(data.get("references", []), list):
        values.update(str(item) for item in data.get("references", []) if str(item).strip())
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    for payload in [content, metadata]:
        for key in ["source_asset_id", "source_asset_path", "handoff_id", "handoff_path", "batch_item_id", "batch_item_path"]:
            value = payload.get(key)
            if value:
                values.add(str(value))
    return values


def _project_id_for_reference(storage: LocalStorage, reference: str) -> str:
    if not _reference_may_be_asset(reference):
        return ""
    value = str(reference or "").strip()
    candidate = storage.root / value
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
            try:
                relative = str(path.relative_to(storage.root))
            except ValueError:
                relative = str(path)
            if reference in {str(data.get("id", "")), relative}:
                return _project_id_from_data(data)
    return ""


def _project_id_index_for_references(storage: LocalStorage, references: set[str]) -> dict[str, str]:
    index: dict[str, str] = {}
    categories: list[str] = []
    for reference in references:
        if not _reference_may_be_asset(reference):
            continue
        value = str(reference or "").strip()
        candidate = storage.root / value
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


def _index_project_reference(storage: LocalStorage, index: dict[str, str], path: Path, data: Any) -> None:
    if not isinstance(data, dict):
        return
    project_id = _project_id_from_data(data)
    if not project_id:
        return
    asset_id = str(data.get("id", "") or "")
    if asset_id:
        index[asset_id] = project_id
    try:
        relative = str(path.relative_to(storage.root))
    except ValueError:
        relative = str(path)
    index[relative] = project_id
    index[str(path)] = project_id


def _cached_category_project_index(storage: LocalStorage, category: str) -> dict[str, str]:
    paths = storage.list_json(category)
    signature = (
        len(paths),
        max((path.stat().st_mtime_ns for path in paths if path.exists()), default=0),
    )
    cache = getattr(storage, "_project_scope_write_guard_index_cache", None)
    if not isinstance(cache, dict):
        cache = {}
        setattr(storage, "_project_scope_write_guard_index_cache", cache)
    cached = cache.get(category)
    if isinstance(cached, tuple) and len(cached) == 2 and cached[0] == signature and isinstance(cached[1], dict):
        return cached[1]
    index: dict[str, str] = {}
    for path in paths:
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        _index_project_reference(storage, index, path, data)
    cache[category] = (signature, index)
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
