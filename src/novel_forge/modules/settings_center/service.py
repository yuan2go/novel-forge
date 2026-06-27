from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.agent_runs import AgentExecutionContext
from novel_forge.modules.production_context import project_scope_from_asset
from novel_forge.schemas import LocalSettingsProfile, validate_common_fields
from novel_forge.storage.local import LocalStorage

SETTINGS_TYPES = {"local_settings_profile", "model_profile", "prompt_version", "prompt_regression_report"}


def list_settings_assets(
    storage: LocalStorage,
    *,
    project_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for category in ["runs", "platforms", "quality_standards", "styles"]:
        for path in reversed(storage.list_json(category)):
            data = storage.read_json(path)
            if not isinstance(data, dict):
                continue
            if data.get("type") not in SETTINGS_TYPES and data.get("type") not in {"platform_profile", "quality_standard_profile", "style_profile"}:
                continue
            metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
            if project_id and metadata.get("project_id") not in {project_id, ""}:
                continue
            rows.append(_settings_row(storage, path, data))
            if len(rows) >= limit:
                return rows
    rows.sort(key=lambda item: (item.get("updated_at", ""), item.get("path", "")), reverse=True)
    return rows[:limit]


def create_local_settings_profile(
    storage: LocalStorage,
    *,
    title: str = "Local production settings",
    profile_id: str | None = None,
    model_routing: dict[str, Any] | None = None,
    storage_config: dict[str, Any] | None = None,
    agent_defaults: dict[str, Any] | None = None,
    validation: dict[str, Any] | None = None,
    status: str = "active",
    workspace_path: str | None = None,
) -> dict[str, Any]:
    project = project_scope_from_asset(storage, {}, workspace_path=workspace_path)
    project_id = str(project.get("project_id", ""))
    workspace = str(project.get("workspace_path", workspace_path or ""))
    with AgentExecutionContext(
        storage,
        agent_key="settings",
        operation="create-local-settings-profile",
        output_types=["local_settings_profile"],
        workspace_path=workspace,
        sla_seconds=180,
    ) as run:
        settings = IndustrialSettings.from_env(root=storage.root)
        content = {
            "profile_id": profile_id or make_id("local_settings_profile", title),
            "local_mode": True,
            "model_routing": _merge(
                {
                    "default_provider": "local-rules",
                    "default_model": "local-rules",
                    "requires_benchmark_before_switch": True,
                    "allowed_providers": ["local-rules", "openai", "anthropic", "deepseek", "ollama"],
                },
                model_routing or {},
            ),
            "storage": _merge(
                {
                    "root": str(storage.root),
                    "postgres_strict": bool(settings.postgres_write_strict),
                    "postgres_write_through": bool(settings.postgres_write_through),
                    "qdrant_enabled": bool(settings.qdrant_url),
                    "minio_enabled": bool(settings.minio_endpoint),
                },
                storage_config or {},
            ),
            "agent_defaults": _merge(
                {
                    "permission_profiles_required": True,
                    "tool_allowlist_enforced": True,
                    "sla_seconds": 1800,
                    "human_gate_for_high_risk": True,
                },
                agent_defaults or {},
            ),
            "validation": _merge(
                {
                    "strict_local_prod": bool(settings.postgres_write_strict),
                    "schema_validation_required": True,
                    "project_scope_guard_required": True,
                    "copyright_boundary_required": True,
                },
                validation or {},
            ),
            "status": status,
            "updated_at": utc_now(),
        }
        asset = LocalSettingsProfile(
            title=title,
            tags=["settings", "local-production", status],
            content=content,
            metadata={
                "project_id": project_id,
                "workspace_path": workspace,
                "workflow": "local-settings-profile",
                "saas_features": "disabled",
            },
            references=[workspace] if workspace else [],
        )
        run.guard("write_local_settings_profile", "local_settings_profile")
        result = _write(storage, asset)
        run.succeed(output_assets=[result["path"]])
        return result


def _settings_row(storage: LocalStorage, path: Path, data: dict[str, Any]) -> dict[str, Any]:
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    return {
        "path": _display_path(storage.root, path),
        "id": data.get("id", ""),
        "type": data.get("type", ""),
        "title": data.get("title") or data.get("name", ""),
        "project_id": metadata.get("project_id", ""),
        "workspace_path": metadata.get("workspace_path", ""),
        "status": content.get("status", metadata.get("asset_status", "")),
        "provider": content.get("provider") or content.get("model_routing", {}).get("default_provider", ""),
        "model_name": content.get("model_name") or content.get("model_routing", {}).get("default_model", ""),
        "strict_local_prod": content.get("validation", {}).get("strict_local_prod", ""),
        "summary": _summary(content),
        "updated_at": data.get("updated_at", ""),
    }


def _summary(content: dict[str, Any]) -> str:
    if "local_mode" in content:
        validation = content.get("validation", {}) if isinstance(content.get("validation", {}), dict) else {}
        routing = content.get("model_routing", {}) if isinstance(content.get("model_routing", {}), dict) else {}
        return f"local={content.get('local_mode')} provider={routing.get('default_provider', '')} strict={validation.get('strict_local_prod')}"
    if "capabilities" in content:
        return f"capabilities={len(content.get('capabilities', {}))}"
    if "template" in content:
        return str(content.get("template", ""))[:120]
    return str(content)[:120]


def _merge(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    merged = {**left}
    for key, value in right.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _write(storage: LocalStorage, asset: Any) -> dict[str, Any]:
    data = asset.to_dict()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "asset": data, "validation": {"ok": True, "errors": []}}


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
