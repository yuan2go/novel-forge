from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.constants import ASSET_DIR_BY_TYPE
from novel_forge.modules.production_context import (
    build_production_context,
    profile_reference_ids,
    quality_dimensions_from_context,
)
from novel_forge.modules.platform_strategy import build_platform_strategy_pack
from novel_forge.storage.local import LocalStorage

FEEDBACK_TYPES = {"feedback_insight", "reader_sentiment_report"}
CONTINUITY_TYPES = {"continuity_bible", "foreshadowing_thread", "power_scale_rule", "chapter_continuity_report", "continuity_graph_snapshot", "canon_graph_snapshot"}


def build_planning_context(
    storage: LocalStorage,
    input_asset: Any,
    *,
    input_path: str | Path | None = None,
    workspace_path: str | None = None,
    chapter: int | None = None,
) -> dict[str, Any]:
    production_context = build_production_context(storage, input_asset, input_path=input_path, workspace_path=workspace_path)
    project_id = str(production_context.get("project", {}).get("project_id", "") or "")
    feedback_assets = _latest_project_assets(storage, FEEDBACK_TYPES, project_id, limit=8)
    continuity_assets = _latest_project_assets(storage, CONTINUITY_TYPES, project_id, limit=10)
    quality_dimensions = quality_dimensions_from_context(production_context)
    workspace_feedback = _workspace_feedback_constraints(storage, production_context)
    feedback_constraints = _dedupe([*_feedback_constraints(feedback_assets), *workspace_feedback["constraints"]])
    continuity_constraints = _continuity_constraints(production_context, continuity_assets)
    platform_strategy = _platform_strategy_context(storage, production_context, chapter=chapter)
    references = [
        *profile_reference_ids(production_context),
        *_asset_references(feedback_assets),
        *_asset_references(continuity_assets),
        *workspace_feedback["references"],
        platform_strategy.get("path", ""),
        platform_strategy.get("id", ""),
    ]
    return {
        "production_context": production_context,
        "project": production_context.get("project", {}),
        "project_config": production_context.get("project_config", {}),
        "profiles": _profile_summaries(production_context),
        "quality_standard": {
            "profile_id": _profile_id(production_context, "quality_standard_profile"),
            "dimensions": quality_dimensions,
            "threshold": production_context.get("project_config", {}).get("quality_threshold", 0),
            "content": _profile_content(production_context, "quality_standard_profile"),
        },
        "creative_strategy": {
            "profile_id": _profile_id(production_context, "creative_strategy_profile"),
            "content": _profile_content(production_context, "creative_strategy_profile"),
            "constraints": _creative_strategy_constraints(production_context),
        },
        "platform_strategy": platform_strategy,
        "continuity": {
            "profile_id": _profile_id(production_context, "continuity_bible"),
            "assets": [_asset_summary(asset) for asset in continuity_assets],
            "constraints": continuity_constraints,
        },
        "feedback": {
            "assets": [_asset_summary(asset) for asset in feedback_assets],
            "constraints": feedback_constraints,
            "workspace_memory": workspace_feedback["memory"],
        },
        "chapter": chapter,
        "required_context": {
            "project_profile": bool(production_context.get("project", {}).get("project_id")),
            "creative_strategy": bool(_profile_id(production_context, "creative_strategy_profile")),
            "quality_standard": bool(_profile_id(production_context, "quality_standard_profile")),
            "continuity": bool(_profile_id(production_context, "continuity_bible") or continuity_assets),
            "feedback": bool(feedback_assets or workspace_feedback["constraints"]),
            "platform_strategy": bool(platform_strategy.get("id")),
            "preflight_ready": production_context.get("preflight", {}).get("ready", False),
            "warnings": production_context.get("preflight", {}).get("warnings", []),
        },
        "references": _dedupe([str(item) for item in references if str(item).strip()]),
    }


def planning_context_metadata(context: dict[str, Any]) -> dict[str, Any]:
    production_context = context.get("production_context", {}) if isinstance(context.get("production_context", {}), dict) else {}
    project = production_context.get("project", {}) if isinstance(production_context.get("project", {}), dict) else {}
    required = context.get("required_context", {}) if isinstance(context.get("required_context", {}), dict) else {}
    return {
        "project_id": str(project.get("project_id", "")),
        "workspace_path": str(project.get("workspace_path", "")),
        "platform_profile_id": _profile_id(production_context, "platform_profile"),
        "genre_market_profile_id": _profile_id(production_context, "genre_market_profile"),
        "creative_strategy_profile_id": _profile_id(production_context, "creative_strategy_profile"),
        "quality_standard_profile_id": _profile_id(production_context, "quality_standard_profile"),
        "platform_strategy_pack_id": str(context.get("platform_strategy", {}).get("id", "")),
        "platform_strategy_pack_path": str(context.get("platform_strategy", {}).get("path", "")),
        "style_profile_id": _profile_id(production_context, "style_profile"),
        "style_blend_preset_id": _profile_id(production_context, "style_blend_preset"),
        "continuity_bible_id": _profile_id(production_context, "continuity_bible"),
        "feedback_asset_ids": [str(asset.get("id", "")) for asset in context.get("feedback", {}).get("assets", []) if asset.get("id")],
        "continuity_asset_ids": [str(asset.get("id", "")) for asset in context.get("continuity", {}).get("assets", []) if asset.get("id")],
        "planning_context_required": True,
        "planning_context_loaded": bool(required.get("preflight_ready")),
        "preflight_ready": production_context.get("preflight", {}).get("ready", False),
        "preflight_warnings": production_context.get("preflight", {}).get("warnings", []),
    }


def _latest_project_assets(storage: LocalStorage, asset_types: set[str], project_id: str, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    categories = _dedupe([ASSET_DIR_BY_TYPE.get(asset_type, "") for asset_type in sorted(asset_types)])
    for category in categories:
        if not category:
            continue
        for path in reversed(storage.list_json(category)):
            if len(rows) >= limit:
                return rows
            try:
                data = storage.read_json(path)
            except Exception:
                continue
            if not isinstance(data, dict) or data.get("type") not in asset_types:
                continue
            metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
            content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
            item_project_id = str(metadata.get("project_id") or content.get("project_id") or "")
            if project_id and item_project_id and item_project_id != project_id:
                continue
            if project_id and not item_project_id:
                continue
            rows.append(_asset_payload(storage, path, data))
    return rows[:limit]


def _profile_summaries(production_context: dict[str, Any]) -> dict[str, dict[str, Any]]:
    profiles = production_context.get("profiles", {}) if isinstance(production_context.get("profiles", {}), dict) else {}
    return {asset_type: _profile_summary(profile) for asset_type, profile in profiles.items() if isinstance(profile, dict)}


def _profile_summary(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": profile.get("id", ""),
        "type": profile.get("type", ""),
        "title": profile.get("title", ""),
        "path": profile.get("path", ""),
        "content": _trim(profile.get("content", {}), max_items=8, max_text=360),
    }


def _asset_summary(asset: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": asset.get("id", ""),
        "type": asset.get("type", ""),
        "title": asset.get("title", ""),
        "path": asset.get("path", ""),
        "content": _trim(asset.get("content", {}), max_items=8, max_text=360),
    }


def _asset_payload(storage: LocalStorage, path: Path, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": data.get("id", ""),
        "type": data.get("type", ""),
        "title": data.get("title") or data.get("name", ""),
        "path": _display_path(storage.root, path),
        "content": data.get("content", {}) if isinstance(data.get("content", {}), dict) else {},
        "metadata": data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {},
    }


def _feedback_constraints(assets: list[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for asset in assets:
        content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
        values.extend(_strings(content.get("next_generation_constraints")))
        values.extend(_strings(content.get("recommendations")))
        values.extend([f"avoid poison point: {item}" for item in _strings(content.get("poison_points"))])
        values.extend([f"preserve sweet point: {item}" for item in _strings(content.get("sweet_points"))])
        values.extend([f"reader expectation: {item}" for item in _strings(content.get("reader_expectations"))])
        adjustment = content.get("plot_adjustment_plan", {}) if isinstance(content.get("plot_adjustment_plan", {}), dict) else {}
        values.extend(_strings(adjustment.get("next_generation_constraints")))
        retention = content.get("retention_risk", {}) if isinstance(content.get("retention_risk", {}), dict) else {}
        if retention.get("level") in {"medium", "high"}:
            values.append(f"retention risk is {retention.get('level')}: increase clarity and forward momentum")
        for cluster in content.get("clusters", []) if isinstance(content.get("clusters", []), list) else []:
            if isinstance(cluster, dict) and cluster.get("label"):
                values.append(f"reader cluster signal: {cluster.get('label')}")
    return _dedupe(values)


def _workspace_feedback_constraints(storage: LocalStorage, production_context: dict[str, Any]) -> dict[str, Any]:
    workspace_path = str(production_context.get("project", {}).get("workspace_path", "") or "")
    if not workspace_path:
        return {"constraints": [], "references": [], "memory": {}}
    try:
        data = storage.read_json(Path(storage.root) / workspace_path)
    except Exception:
        return {"constraints": [], "references": [], "memory": {}}
    if not isinstance(data, dict):
        return {"constraints": [], "references": [], "memory": {}}
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    memory = content.get("memory", {}) if isinstance(content.get("memory", {}), dict) else {}
    reader_memory = memory.get("reader_feedback", {}) if isinstance(memory.get("reader_feedback", {}), dict) else {}
    strategy = reader_memory.get("next_chapter_strategy", {}) if isinstance(reader_memory.get("next_chapter_strategy", {}), dict) else {}
    values = [
        *_strings(content.get("feedback_constraints")),
        *_strings(strategy.get("constraints")),
        *_strings(strategy.get("recommended_actions")),
    ]
    if strategy.get("primary_strategy"):
        values.append(f"reader feedback strategy: {strategy.get('primary_strategy')}")
    follow_risk = reader_memory.get("follow_read_risk", {}) if isinstance(reader_memory.get("follow_read_risk", {}), dict) else {}
    if follow_risk.get("level") in {"medium", "high"}:
        values.append(f"follow-read risk is {follow_risk.get('level')}: repair clarity, momentum, and expected payoff")
    for row in reader_memory.get("character_heat", []) if isinstance(reader_memory.get("character_heat", []), list) else []:
        if isinstance(row, dict) and (row.get("name") or row.get("character")):
            values.append(f"reader character heat: {row.get('name') or row.get('character')} score {row.get('score', row.get('heat', row.get('mentions', '')))}")
    return {
        "constraints": _dedupe(values),
        "references": _dedupe([workspace_path, str(reader_memory.get("latest_report_id", "")), str(reader_memory.get("latest_report_path", ""))]),
        "memory": _trim(reader_memory, max_items=8, max_text=360),
    }


def _continuity_constraints(production_context: dict[str, Any], assets: list[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    profile = _profile_content(production_context, "continuity_bible")
    values.extend(_strings(profile.get("active_threads")))
    values.extend(_strings(profile.get("open_hooks")))
    values.extend(_strings(profile.get("foreshadowing")))
    values.extend(_strings(profile.get("continuity_rules")))
    for asset in assets:
        content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
        values.extend(_strings(content.get("open_threads")))
        values.extend(_strings(content.get("unresolved_hooks")))
        values.extend(_strings(content.get("foreshadowing")))
        values.extend(_strings(content.get("continuity_checks")))
        if content.get("risk_level"):
            values.append(f"{asset.get('type')} risk: {content.get('risk_level')}")
    return _dedupe(values)


def _creative_strategy_constraints(production_context: dict[str, Any]) -> list[str]:
    profile = _profile_content(production_context, "creative_strategy_profile")
    values: list[str] = []
    if profile.get("reader_promise"):
        values.append(f"reader promise: {profile.get('reader_promise')}")
    values.extend(_strings(profile.get("verification_rules")))
    rhythm = profile.get("pleasure_rhythm", {}) if isinstance(profile.get("pleasure_rhythm", {}), dict) else {}
    values.extend([f"pleasure rhythm {key}: {item}" for key, item in rhythm.items() if str(item).strip()])
    pacing = profile.get("platform_pacing", {}) if isinstance(profile.get("platform_pacing", {}), dict) else {}
    values.extend([f"platform pacing {key}: {item}" for key, item in pacing.items() if str(item).strip()])
    for hook in profile.get("long_hooks", []) if isinstance(profile.get("long_hooks", []), list) else []:
        if isinstance(hook, dict):
            values.append(f"long hook {hook.get('hook_id', '')}: {hook.get('status', '')} -> {hook.get('payoff_window', '')}")
        elif str(hook).strip():
            values.append(f"long hook: {hook}")
    return _dedupe(values)


def _profile_content(production_context: dict[str, Any], asset_type: str) -> dict[str, Any]:
    profiles = production_context.get("profiles", {}) if isinstance(production_context.get("profiles", {}), dict) else {}
    profile = profiles.get(asset_type)
    if not isinstance(profile, dict):
        return {}
    content = profile.get("content", {})
    return content if isinstance(content, dict) else {}


def _profile_id(production_context: dict[str, Any], asset_type: str) -> str:
    profiles = production_context.get("profiles", {}) if isinstance(production_context.get("profiles", {}), dict) else {}
    profile = profiles.get(asset_type)
    return str(profile.get("id", "")) if isinstance(profile, dict) else ""


def _platform_strategy_context(storage: LocalStorage, production_context: dict[str, Any], *, chapter: int | None) -> dict[str, Any]:
    project = production_context.get("project", {}) if isinstance(production_context.get("project", {}), dict) else {}
    config = production_context.get("project_config", {}) if isinstance(production_context.get("project_config", {}), dict) else {}
    platform_profile = _profile_content(production_context, "platform_profile")
    platform = str(config.get("target_platform") or platform_profile.get("platform_id") or platform_profile.get("platform_name") or "qidian")
    genre = str(config.get("genre") or "")
    try:
        pack = build_platform_strategy_pack(
            storage,
            {
                "project_id": str(project.get("project_id") or "local-system"),
                "workspace_path": str(project.get("workspace_path") or ""),
                "platform": platform,
                "genre": genre,
                "topic": str(project.get("title") or config.get("title") or "Project"),
                "chapter": chapter,
                "persist": True,
            },
        )
    except Exception as exc:
        return {"id": "", "path": "", "content": {}, "warning": str(exc)}
    asset = pack.get("asset", {}) if isinstance(pack.get("asset"), dict) else {}
    content = asset.get("content", {}) if isinstance(asset.get("content"), dict) else {}
    return {
        "id": str(asset.get("id", "")),
        "path": str(pack.get("path", "")),
        "platform_id": str(content.get("platform_id", "")),
        "platform_name": str(content.get("platform_name", "")),
        "content": _trim(content, max_items=16, max_text=500),
    }


def _asset_references(assets: list[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for asset in assets:
        values.extend([str(asset.get("id", "")), str(asset.get("path", ""))])
    return values


def _strings(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, dict):
        return [f"{key}: {item}" for key, item in value.items() if str(item).strip()]
    if str(value or "").strip():
        return [str(value).strip()]
    return []


def _trim(value: Any, *, max_items: int, max_text: int) -> Any:
    if isinstance(value, dict):
        return {str(key): _trim(item, max_items=max_items, max_text=max_text) for key, item in list(value.items())[:max_items]}
    if isinstance(value, list):
        return [_trim(item, max_items=max_items, max_text=max_text) for item in value[:max_items]]
    if isinstance(value, str):
        return value[:max_text]
    return value


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
