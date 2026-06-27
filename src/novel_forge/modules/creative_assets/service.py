from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from novel_forge.core.constants import ASSET_DIR_BY_TYPE
from novel_forge.core.ids import utc_now
from novel_forge.modules.agent_runs import AgentExecutionContext
from novel_forge.schemas import SCHEMA_CLASSES, validate_common_fields
from novel_forge.storage.local import LocalStorage


@dataclass(frozen=True)
class CreativeLibraryDefinition:
    key: str
    title: str
    title_zh: str
    description: str
    description_zh: str
    asset_types: tuple[str, ...]
    categories: tuple[str, ...]


CREATIVE_LIBRARY_DEFINITIONS: tuple[CreativeLibraryDefinition, ...] = (
    CreativeLibraryDefinition(
        key="topic_library",
        title="Topic Library",
        title_zh="题材库",
        description="Platform profiles, genre market profiles, creative strategy, topic seeds, and fit reports.",
        description_zh="平台配置、题材市场画像、创作策略、题材种子和适配评估。",
        asset_types=("platform_profile", "genre_market_profile", "creative_strategy_profile", "topic_seed", "topic_fit_report"),
        categories=("platforms", "genres", "topics"),
    ),
    CreativeLibraryDefinition(
        key="material_library",
        title="Material Library",
        title_zh="素材库",
        description="Reusable material cards, asset sets, and craft templates.",
        description_zh="可复用素材卡、资产集合和写作技法模板。",
        asset_types=("material_card", "asset_collection", "writing_template", "craft_template"),
        categories=("materials", "templates"),
    ),
    CreativeLibraryDefinition(
        key="knowledge_library",
        title="Knowledge Library",
        title_zh="知识库",
        description="Multidisciplinary knowledge cards with source and license boundaries.",
        description_zh="带来源、许可和抽象边界的多学科知识卡。",
        asset_types=("knowledge_card",),
        categories=("knowledge",),
    ),
    CreativeLibraryDefinition(
        key="setting_bible",
        title="Setting Bible",
        title_zh="设定书",
        description="World bible, character cards, continuity state, foreshadowing, and power rules.",
        description_zh="世界观、人物、连续性、伏笔和战力规则。",
        asset_types=("world_bible", "character_card", "continuity_bible", "foreshadowing_thread", "power_scale_rule"),
        categories=("worlds", "characters", "continuity"),
    ),
    CreativeLibraryDefinition(
        key="style_center",
        title="Style Center",
        title_zh="文风中心",
        description="Parameterized style profiles, decomposition reports, blend presets, and reviews.",
        description_zh="参数化文风画像、风格拆解、混合预设和文风审稿。",
        asset_types=("style_profile", "style_decomposition_report", "style_blend_preset", "style_review_report"),
        categories=("styles", "reviews"),
    ),
    CreativeLibraryDefinition(
        key="quality_standards",
        title="Quality Standards",
        title_zh="精品标准",
        description="Quality standard profiles, review rule packs, and scoring reports.",
        description_zh="精品标准、审稿规则包和评分报告。",
        asset_types=("quality_standard_profile", "review_rule_pack", "quality_score_report"),
        categories=("quality_standards", "reviews"),
    ),
)

_LIBRARIES_BY_KEY = {definition.key: definition for definition in CREATIVE_LIBRARY_DEFINITIONS}
_LIBRARY_BY_TYPE = {
    asset_type: definition.key
    for definition in CREATIVE_LIBRARY_DEFINITIONS
    for asset_type in definition.asset_types
}


def list_creative_libraries(
    storage: LocalStorage,
    *,
    project_id: str | None = None,
    include_global: bool = True,
    limit_per_library: int = 12,
) -> list[dict[str, Any]]:
    return [
        {
            **_library_definition_payload(definition),
            "assets": list_creative_assets(
                storage,
                definition.key,
                project_id=project_id,
                include_global=include_global,
                limit=limit_per_library,
            ),
        }
        for definition in CREATIVE_LIBRARY_DEFINITIONS
    ]


def list_creative_assets(
    storage: LocalStorage,
    library_key: str,
    *,
    project_id: str | None = None,
    include_global: bool = True,
    keyword: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    definition = _library_definition(library_key)
    if limit < 1:
        raise ValueError("limit must be greater than zero")
    keyword_lower = (keyword or "").strip().lower()
    rows: list[dict[str, Any]] = []
    for category in definition.categories:
        for path in storage.list_json(category):
            data = storage.read_json(path)
            if not isinstance(data, dict):
                continue
            if data.get("type") not in definition.asset_types:
                continue
            if not _matches_project(data, project_id, include_global=include_global):
                continue
            if keyword_lower and keyword_lower not in _asset_search_text(data):
                continue
            rows.append(_creative_asset_row(storage, path, data, definition.key))
    rows.sort(key=lambda item: (item.get("updated_at", ""), item.get("path", "")), reverse=True)
    return rows[:limit]


def create_creative_asset(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    asset_type = str(payload.get("asset_type") or payload.get("type") or "").strip()
    if asset_type not in _LIBRARY_BY_TYPE:
        allowed = ", ".join(sorted(_LIBRARY_BY_TYPE))
        raise ValueError(f"unsupported creative asset type: {asset_type}; allowed: {allowed}")

    title = str(payload.get("title") or payload.get("name") or "").strip()
    if not title:
        raise ValueError("title must not be empty")

    project_id = str(payload.get("project_id") or "").strip()
    workspace_path = str(payload.get("workspace_path") or "").strip()
    scope = str(payload.get("scope") or "project").strip()
    if scope not in {"project", "global"}:
        raise ValueError("scope must be project or global")
    if scope == "project":
        project_id, workspace_path = _resolve_project_scope(storage, project_id, workspace_path)

    content = _merge_dicts(_default_content(asset_type, title, project_id), payload.get("content") or {})
    metadata = _merge_dicts(
        _default_metadata(asset_type, project_id=project_id, workspace_path=workspace_path, scope=scope),
        payload.get("metadata") or {},
    )
    tags = _dedupe([*_default_tags(asset_type), *[str(tag) for tag in payload.get("tags") or []]])
    references = [str(reference) for reference in payload.get("references") or [] if str(reference).strip()]
    cls = SCHEMA_CLASSES[asset_type]
    asset = cls(
        title=title,
        source=str(payload.get("source") or "").strip(),
        tags=tags,
        content=content,
        metadata=metadata,
        references=references,
    )
    data = asset.to_dict()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    with AgentExecutionContext(
        storage,
        agent_key="creative_asset",
        operation="create-creative-asset",
        output_types=[asset_type],
        workspace_path=workspace_path,
        sla_seconds=300,
    ) as run:
        run.guard("write_creative_asset", asset_type)
        path = storage.write_asset_auto(asset)
        result = {
            "path": str(path.relative_to(storage.root)),
            "library": _LIBRARY_BY_TYPE[asset_type],
            "asset": data,
            "validation": {"ok": True, "errors": []},
        }
        run.succeed(output_assets=[result["path"]])
        return result


def creative_asset_schema() -> dict[str, Any]:
    return {
        "libraries": [_library_definition_payload(definition) for definition in CREATIVE_LIBRARY_DEFINITIONS],
        "asset_types": {
            asset_type: {
                "library": library_key,
                "category": ASSET_DIR_BY_TYPE.get(asset_type, ""),
                "default_content": _default_content(asset_type, "Untitled", "project"),
                "default_tags": _default_tags(asset_type),
            }
            for asset_type, library_key in sorted(_LIBRARY_BY_TYPE.items())
        },
    }


def _library_definition(library_key: str) -> CreativeLibraryDefinition:
    try:
        return _LIBRARIES_BY_KEY[library_key]
    except KeyError as exc:
        raise ValueError(f"unknown creative library: {library_key}") from exc


def _library_definition_payload(definition: CreativeLibraryDefinition) -> dict[str, Any]:
    return {
        "key": definition.key,
        "title": definition.title,
        "title_zh": definition.title_zh,
        "description": definition.description,
        "description_zh": definition.description_zh,
        "asset_types": list(definition.asset_types),
        "categories": list(definition.categories),
    }


def _creative_asset_row(storage: LocalStorage, path: Path, data: dict[str, Any], library_key: str) -> dict[str, Any]:
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    return {
        "path": str(path.relative_to(storage.root)),
        "category": ASSET_DIR_BY_TYPE.get(str(data.get("type", "")), path.parent.name),
        "library": library_key,
        "type": data.get("type", ""),
        "id": data.get("id", ""),
        "title": data.get("title") or data.get("name", ""),
        "tags": data.get("tags", []) if isinstance(data.get("tags"), list) else [],
        "source": data.get("source", ""),
        "project_id": metadata.get("project_id", ""),
        "workspace_path": metadata.get("workspace_path", ""),
        "scope": metadata.get("library_scope", "project" if metadata.get("project_id") else "global"),
        "risk_level": metadata.get("risk_level") or metadata.get("copyright_risk") or "unknown",
        "asset_status": metadata.get("asset_status", "active"),
        "updated_at": data.get("updated_at", ""),
        "preview": _preview_content(data.get("content", {})),
    }


def _matches_project(data: dict[str, Any], project_id: str | None, *, include_global: bool) -> bool:
    if not project_id:
        return True
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    if str(metadata.get("library_scope", "")).strip() == "global":
        return include_global
    record_project_id = str(metadata.get("project_id") or content.get("project_id") or "").strip()
    if record_project_id == project_id:
        return True
    return include_global and not record_project_id


def _resolve_project_scope(storage: LocalStorage, project_id: str, workspace_path: str) -> tuple[str, str]:
    if project_id and workspace_path:
        return project_id, workspace_path
    candidates: list[tuple[str, str]] = []
    for path in storage.list_json("workspaces"):
        data = storage.read_json(path)
        if not isinstance(data, dict):
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        candidate_id = str(content.get("project_id") or data.get("id") or "")
        candidate_path = str(path.relative_to(storage.root))
        if project_id and candidate_id == project_id:
            return candidate_id, candidate_path
        if workspace_path and candidate_path == workspace_path:
            return candidate_id, candidate_path
        candidates.append((candidate_id, candidate_path))
    if not project_id and not workspace_path and len(candidates) == 1:
        return candidates[0]
    if project_id:
        raise ValueError(f"project not found: {project_id}")
    raise ValueError("project_id/workspace_path is required when creating project-scoped creative assets")


def _default_content(asset_type: str, title: str, project_id: str) -> dict[str, Any]:
    defaults: dict[str, dict[str, Any]] = {
        "platform_profile": {
            "platform_id": "custom",
            "platform_name": title,
            "business_model": "custom",
            "reader_expectation": ["clear hook", "stable update", "genre promise"],
            "chapter_length_range": {"min": 1800, "ideal": 2500, "max": 3500},
            "update_frequency": "daily",
            "opening_rules": {
                "first_3_chapters_goal": "establish conflict, promise, and hook",
                "first_10_chapters_goal": "stabilize main line and reader expectation",
            },
            "review_risks": ["weak hook", "platform mismatch", "repetitive filler"],
            "genre_fit": ["custom"],
            "style_tendency": ["clear", "direct", "hook-driven"],
        },
        "genre_market_profile": {
            "genre": title,
            "platform_id": "custom",
            "reader_promise": "clear genre payoff with differentiated execution",
            "common_hooks": ["opening anomaly", "choice pressure", "chapter-end reversal"],
            "common_conflicts": ["protagonist vs external pressure", "protagonist vs hidden cost"],
            "fatigue_points": ["slow setup", "unclear promise", "repeated scenes"],
            "differentiation_axes": ["occupation", "setting rule", "relationship pressure"],
            "chapter_rhythm_template": "hook -> pressure -> choice -> consequence -> next hook",
        },
        "creative_strategy_profile": {
            "strategy_id": "creative_strategy_custom_v1",
            "reader_promise": "deliver a clear genre promise with visible choice pressure and chapter-end curiosity",
            "volume_goals": {
                "volume_1": "establish protagonist pressure, core world rule, repeatable conflict engine, and first long hook",
                "current_volume": "convert every chapter into pressure, choice, cost, payoff, and next obligation",
            },
            "pleasure_rhythm": {
                "chapter_loop": ["hook", "pressure", "choice", "cost", "payoff", "next_hook"],
                "sweet_points": ["competence reveal", "relationship pressure", "rule discovery"],
                "poison_points_to_avoid": ["unclear motive", "slow exposition", "repeated scene function"],
                "density_target": {"hook_every_beats": 4, "payoff_every_chapters": 2},
            },
            "long_hooks": [
                {"hook_id": "core_mystery", "status": "seeded", "payoff_window": "volume_1_end"},
                {"hook_id": "relationship_pressure", "status": "planned", "payoff_window": "mid_volume"},
            ],
            "platform_pacing": {
                "opening_window": "first_3_chapters",
                "retention_window": "first_10_chapters",
                "update_cadence": "daily",
                "chapter_length_target": 2500,
            },
            "verification_rules": [
                "chapter plan must state reader promise and next hook",
                "chapter plan must include at least one choice-cost beat",
                "draft must not bypass long-form continuity or RAG quality gates",
            ],
        },
        "topic_seed": {
            "logline": "A differentiated project premise with a visible conflict engine.",
            "reader_attraction": "clear promise, repeatable hooks, character pressure",
            "differentiation": "abstracted original mechanism; do not reuse protected characters or plots",
            "platform_id": "custom",
            "genre": "custom",
            "reader_promise": "deliver a stable emotional and plot promise",
            "differentiation_axes": ["mechanism", "setting", "relationship"],
        },
        "topic_fit_report": {
            "topic_seed_id": "topic_seed_pending",
            "platform_id": "custom",
            "genre": "custom",
            "scores": {
                "platform_fit": 70,
                "reader_promise": 70,
                "differentiation": 70,
                "serialization_potential": 70,
                "risk": 30,
            },
            "recommendation": "develop_with_adjustments",
            "must_adjust": ["tighten opening hook", "clarify reader promise"],
        },
        "material_card": {
            "usable_patterns": ["abstract reusable production pattern"],
            "prompt_fragments": ["Convert this abstract pattern into an original scene mechanic."],
            "do_not_copy": ["names", "sentences", "unique settings", "plot sequence combinations"],
            "use_cases": ["outline", "chapter_plan", "draft_context"],
        },
        "asset_collection": {
            "purpose": "curated creative asset set for a concrete production task",
            "asset_paths": [],
            "selection_criteria": ["project fit", "license boundary reviewed", "abstraction level is safe"],
            "use_cases": ["context_builder", "chapter_plan", "review"],
            "excluded_assets": [],
        },
        "knowledge_card": {
            "principles": ["abstract reusable knowledge principle"],
            "constraints": ["cite source boundary", "avoid raw text reuse"],
            "review_checks": ["principle is abstract", "source license reviewed"],
        },
        "world_bible": {
            "setting": "Project setting premise",
            "rules": ["rule must create conflict and constraint"],
            "conflict_system": "how setting rules create repeatable story pressure",
        },
        "character_card": {
            "role": "core cast",
            "external_goal": "visible story goal",
            "internal_need": "emotional or moral need",
            "motivation_chain": ["desire", "pressure", "choice", "cost"],
        },
        "continuity_bible": {
            "project_id": project_id or "project",
            "worldview_rules": ["canon rule"],
            "timeline": ["chapter-level continuity marker"],
            "entities": ["character/place/object continuity entity"],
            "open_threads": ["unresolved setup"],
            "constraints": ["do not contradict established canon"],
        },
        "foreshadowing_thread": {
            "thread_id": "thread_custom",
            "setup": "planned setup",
            "payoff_plan": "planned payoff",
            "status": "planned",
            "related_chapters": [],
        },
        "power_scale_rule": {
            "scale_id": "scale_custom",
            "levels": ["baseline", "advanced", "peak"],
            "constraints": ["victory must respect cost and limitation"],
            "violation_checks": ["sudden power jump without setup"],
        },
        "style_profile": {
            "style_id": "style_custom",
            "name": title,
            "scope": "project",
            "source_boundary": {
                "source_asset_ids": [],
                "derived_from_protected_text": False,
                "copyright_risk": "low",
                "allowed_usage": "parameter_only",
            },
            "language_parameters": {
                "sentence_length": "mixed",
                "paragraph_density": "medium",
                "dialogue_ratio": 0.35,
                "description_ratio": 0.25,
                "abstract_exposition_ratio": 0.1,
                "sensory_detail_level": "medium",
                "metaphor_density": "low",
            },
            "narrative_parameters": {
                "pov": "third_limited",
                "narrative_distance": "medium",
                "information_release": "layered",
                "hook_frequency": "scene_end",
            },
            "emotion_parameters": {
                "dominant_mood": ["tension", "curiosity"],
                "emotion_curve": "pressure -> choice -> consequence",
                "reader_feeling_target": ["want to know what happens next"],
            },
            "forbidden_patterns": [
                "do not reuse source-specific metaphors",
                "do not reuse proper nouns",
                "do not imitate a specific author",
            ],
        },
        "style_decomposition_report": {
            "source_asset_id": "source_pending",
            "extract_level": "abstract_parameters_only",
            "style_features": {"sentence_length": "mixed", "information_density": "medium"},
            "usable_parameters": {"hook_frequency": "scene_end"},
            "do_not_copy": ["signature phrasing", "proper nouns", "source-specific metaphors"],
            "risk_level": "low",
        },
        "style_blend_preset": {
            "name": title,
            "components": [{"style_profile_id": "style_custom", "weight": 1.0}],
            "conflict_resolution": {"sentence_length": "project_default", "description_ratio": "cap_0.30"},
        },
        "style_review_report": {
            "target_draft_id": "draft_pending",
            "expected_style_profile_id": "style_custom",
            "style_match_score": 75,
            "drift_points": [],
            "ai_taste_points": [],
            "rewrite_suggestions": ["reduce generic phrasing", "tighten concrete sensory detail"],
            "copyright_style_risk": "low",
        },
        "quality_standard_profile": {
            "standard_id": "quality_custom_v1",
            "name": title,
            "platform_id": "custom",
            "genre": "custom",
            "target_length": "custom",
            "dimensions": {
                "opening_hook": {"weight": 0.15, "threshold": 80},
                "reader_promise": {"weight": 0.12, "threshold": 75},
                "plot_causality": {"weight": 0.12, "threshold": 80},
                "character_drive": {"weight": 0.1, "threshold": 75},
                "chapter_rhythm": {"weight": 0.12, "threshold": 80},
                "style_consistency": {"weight": 0.08, "threshold": 75},
                "originality_safety": {"weight": 0.12, "threshold": 85},
                "long_form_stability": {"weight": 0.1, "threshold": 75},
                "platform_compliance": {"weight": 0.09, "threshold": 90},
            },
            "hard_gates": ["copyright_boundary_passed", "platform_compliance_passed", "no_major_continuity_break"],
        },
        "review_rule_pack": {
            "rule_pack_id": "review_rules_custom_v1",
            "name": title,
            "dimensions": {"chapter_quality": {"weight": 1.0, "threshold": 80}},
            "checks": ["plot causality", "character consistency", "hook strength", "originality boundary"],
            "severity_policy": {"blocker": "must_fix", "major": "revise", "minor": "track"},
        },
        "quality_score_report": {
            "target_asset_id": "asset_pending",
            "standard_id": "quality_custom_v1",
            "overall_score": 75,
            "scores": {"opening_hook": 75, "plot_causality": 75, "originality_safety": 85},
            "gate_results": {"copyright_boundary_passed": True, "platform_compliance_passed": True},
            "recommendation": "revise_before_publish",
        },
        "writing_template": {
            "template_id": "writing_template_custom",
            "name": title,
            "template_kind": "chapter_hook",
            "structure": ["setup pressure", "choice", "consequence", "next hook"],
            "usage_constraints": ["adapt to project canon", "avoid copied scenes"],
            "anti_copy_rules": ["no protected names", "no source-specific scene sequence"],
        },
        "craft_template": {
            "template_id": "craft_template_custom",
            "name": title,
            "craft_domain": "conflict",
            "pattern": "pressure reveals choice, choice creates cost, cost opens next hook",
            "use_cases": ["outline", "chapter_plan", "review"],
            "risks": ["formulaic repetition", "unclear character motive"],
        },
    }
    return deepcopy(defaults[asset_type])


def _default_metadata(asset_type: str, *, project_id: str, workspace_path: str, scope: str) -> dict[str, Any]:
    metadata = {
        "asset_status": "draft",
        "library_key": _LIBRARY_BY_TYPE[asset_type],
        "library_scope": scope,
        "created_by": "creative_asset_workbench",
        "created_at": utc_now(),
    }
    if scope == "global":
        metadata["project_id"] = project_id or "local-system"
        metadata["workspace_path"] = workspace_path or "local-system"
    if project_id:
        metadata["project_id"] = project_id
    if workspace_path:
        metadata["workspace_path"] = workspace_path
    if asset_type in {
        "material_card",
        "knowledge_card",
        "style_profile",
        "style_decomposition_report",
        "style_blend_preset",
        "writing_template",
        "craft_template",
    }:
        metadata["copyright_boundary"] = "abstract structure and parameterized craft asset only"
        metadata["risk_level"] = "low"
    return metadata


def _default_tags(asset_type: str) -> list[str]:
    tags = ["creative-asset", _LIBRARY_BY_TYPE[asset_type], asset_type.replace("_", "-")]
    if asset_type.startswith("style_"):
        tags.append("style")
    if asset_type.startswith("quality_") or asset_type == "review_rule_pack":
        tags.append("quality")
    return tags


def _merge_dicts(base: dict[str, Any], patch: Any) -> dict[str, Any]:
    if not isinstance(patch, dict):
        raise ValueError("content and metadata patches must be objects")
    merged = deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _asset_search_text(data: dict[str, Any]) -> str:
    return str(
        {
            "id": data.get("id", ""),
            "type": data.get("type", ""),
            "title": data.get("title", ""),
            "name": data.get("name", ""),
            "source": data.get("source", ""),
            "tags": data.get("tags", []),
            "content": data.get("content", {}),
            "metadata": data.get("metadata", {}),
        }
    ).lower()


def _preview_content(content: Any) -> str:
    if not isinstance(content, dict):
        return ""
    for key in [
        "reader_promise",
        "logline",
        "recommendation",
        "setting",
        "role",
        "name",
        "pattern",
        "summary",
    ]:
        value = content.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:240]
    return ", ".join(sorted(str(key) for key in content.keys()))[:240]
