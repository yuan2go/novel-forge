from __future__ import annotations

from dataclasses import dataclass

from .contracts import ProductionInputRequirement, ProductionInputRole


CONTINUING_CHAPTER_REQUIRED_ASSET_TYPES = (
    "story_state_snapshot",
    "canon_snapshot",
)

COLLECTION_ASSET_TYPES = frozenset(
    {
        "reader_promise",
        "reward_item",
        "world_rule",
        "knowledge_pack",
        "material_asset",
        "context_segment",
        "character_card",
        "arc_plan",
    }
)


@dataclass(frozen=True, slots=True)
class ProductionStageProfile:
    stage: str
    required_asset_types: tuple[str, ...]
    allowed_asset_types: tuple[str, ...]
    forbidden_asset_types: tuple[str, ...]
    maximum_raw_source_ratio: float
    source_expression_policy: str
    evidence_only_types: tuple[str, ...]
    review_only_types: tuple[str, ...]
    copyright_mode: str
    compression_policy: str
    knowledge_pack_policy: str


_BASE_ALLOWED = (
    "chapter_plan", "arc_plan", "outline", "outline_version", "volume_arc", "world_bible",
    "creative_brief", "theme_question", "theme_arc", "closure_plan",
    "style_policy", "quality_profile", "quality_rubric", "platform_profile",
    "context_profile", "story_state_snapshot", "canon_snapshot",
    "character_card", "genre_profile", "knowledge_pack",
    "material_asset", "reader_promise", "empty_state_declaration",
    "context_segment", "context_bundle",
    "draft_version", "review_rule", "review_report", "re_review_report", "canon_patch",
    "operator_checklist", "approval_decision",
    "structural_quality_report", "commercial_quality_report",
    "source_originality_quality_report", "longform_quality_report",
    "platform_quality_report",
)

_STATE_TYPES = frozenset(CONTINUING_CHAPTER_REQUIRED_ASSET_TYPES)
_QUALITY_REPORT_TYPES = frozenset({
    "structural_quality_report", "commercial_quality_report",
    "source_originality_quality_report", "longform_quality_report",
    "platform_quality_report",
})
_STAGE_EXCLUDED = {
    "creative": _STATE_TYPES | _QUALITY_REPORT_TYPES | {
        "chapter_plan", "outline", "outline_version", "volume_arc", "world_bible",
        "draft_version", "review_rule", "review_report", "re_review_report",
        "canon_patch", "closure_plan",
    },
    "worldbuilding": _STATE_TYPES | _QUALITY_REPORT_TYPES | {
        "chapter_plan", "draft_version", "review_rule", "review_report",
        "re_review_report", "canon_patch", "closure_plan",
    },
    "character": _STATE_TYPES | _QUALITY_REPORT_TYPES | {
        "chapter_plan", "draft_version", "review_rule", "review_report",
        "re_review_report", "canon_patch", "closure_plan",
    },
    "outline": _QUALITY_REPORT_TYPES | {
        "chapter_plan", "draft_version", "review_rule", "review_report",
        "re_review_report", "canon_patch",
    },
    "chapter_plan": _QUALITY_REPORT_TYPES | {
        "draft_version", "review_rule", "review_report", "re_review_report", "canon_patch",
    },
    # Quality reports are frozen as evidence-only inputs for the downstream
    # quality fan-in.  DraftContextView still excludes their expression.
    "draft": {
        "draft_version", "review_rule", "review_report", "re_review_report", "canon_patch",
    },
    "review": _QUALITY_REPORT_TYPES | {"review_report", "re_review_report", "canon_patch"},
    "revision": _QUALITY_REPORT_TYPES | {"re_review_report", "canon_patch"},
    "canon_extraction": _QUALITY_REPORT_TYPES,
    "quality": frozenset(),
    "recap": frozenset(),
    "ending": frozenset(),
}
_STAGE_REQUIRED = {
    "creative": ("style_policy", "quality_rubric", "platform_profile"),
    "worldbuilding": ("creative_brief", "style_policy"),
    "character": ("creative_brief", "world_bible", "style_policy"),
    "outline": ("creative_brief", "world_bible", "style_policy"),
    "chapter_plan": ("outline", "world_bible", "style_policy"),
    "draft": ("chapter_plan", "style_policy", "quality_rubric", "platform_profile"),
    "review": ("chapter_plan", "draft_version", "quality_rubric", "platform_profile"),
    "revision": ("chapter_plan", "draft_version", "review_report", "style_policy"),
    "canon_extraction": ("draft_version",),
    "quality": ("draft_version", "re_review_report", "quality_rubric", "platform_profile"),
    "recap": ("canon_snapshot",),
    "ending": ("closure_plan", "theme_arc", "canon_snapshot"),
}

STAGE_PROFILES = {
    stage: ProductionStageProfile(
        stage=stage,
        required_asset_types=_STAGE_REQUIRED[stage],
        allowed_asset_types=tuple(
            asset_type for asset_type in _BASE_ALLOWED
            if asset_type not in _STAGE_EXCLUDED[stage]
        ),
        forbidden_asset_types=("raw_source", "source_chunk", "eval_only", "quarantined_source"),
        maximum_raw_source_ratio=0.0,
        source_expression_policy="abstract_safe_content_only",
        evidence_only_types=(
            "quality_rubric", "operator_checklist", "structural_quality_report",
            "commercial_quality_report", "source_originality_quality_report",
            "longform_quality_report", "platform_quality_report",
        ),
        review_only_types=("review_rule",),
        copyright_mode="fail_closed",
        compression_policy="safe_summary_then_structured_facts",
        knowledge_pack_policy="CAPABILITY_OPTIONAL",
    )
    for stage in _STAGE_REQUIRED
}


def requirements_for(
    stage: str,
    chapter: int,
    *,
    capability_required_asset_types: tuple[str, ...] = (),
) -> tuple[ProductionInputRequirement, ...]:
    profile = STAGE_PROFILES[stage]
    required = list(profile.required_asset_types)
    unsupported = set(capability_required_asset_types) - set(
        profile.allowed_asset_types
    )
    if unsupported:
        raise ValueError(
            "capability requires assets forbidden for this stage: "
            + ", ".join(sorted(unsupported))
        )
    required.extend(capability_required_asset_types)
    if chapter > 1 and stage in {
        "chapter_plan", "draft", "review", "revision", "canon_extraction",
        "quality", "recap", "ending",
    }:
        required.extend(CONTINUING_CHAPTER_REQUIRED_ASSET_TYPES)
    required_set = set(required)
    requirements = []
    for asset_type in profile.allowed_asset_types:
        role = (
            ProductionInputRole.PLAN if asset_type == "chapter_plan"
            else ProductionInputRole.PROFILE if asset_type.endswith("profile") or asset_type in {"quality_rubric", "style_policy", "context_profile"}
            else ProductionInputRole.STATE if asset_type in CONTINUING_CHAPTER_REQUIRED_ASSET_TYPES
            else ProductionInputRole.APPROVAL if asset_type == "approval_decision"
            else ProductionInputRole.GOVERNANCE if asset_type == "operator_checklist"
            else ProductionInputRole.CONTEXT
        )
        requirements.append(
            ProductionInputRequirement(
                asset_type=asset_type,
                role=role,
                required=asset_type in required_set,
                cardinality="many" if asset_type in COLLECTION_ASSET_TYPES else "one",
            )
        )
    return tuple(requirements)


CONTEXT_VERSION_REF_KEYS = {
    "chapter_plan": "chapter_plan_version",
    "arc_plan": "selected_arc_plan_versions",
    "outline": "outline_version",
    "outline_version": "outline_version",
    "volume_arc": "volume_arc_version",
    "world_bible": "world_bible_version",
    "canon_snapshot": "canon_snapshot_version",
    "story_state_snapshot": "story_state_snapshot_version",
    "style_policy": "style_policy_version",
    "quality_profile": "quality_profile_version",
    "quality_rubric": "quality_profile_version",
    "platform_profile": "platform_profile_version",
    "context_profile": "context_profile_version",
}

ALWAYS_REQUIRED_ASSET_TYPES = STAGE_PROFILES["draft"].required_asset_types
OPTIONAL_CONTEXT_ASSET_TYPES = tuple(
    item for item in _BASE_ALLOWED if item not in ALWAYS_REQUIRED_ASSET_TYPES
)
