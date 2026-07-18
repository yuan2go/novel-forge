from __future__ import annotations

from dataclasses import dataclass

from .contracts import ProductionInputRequirement, ProductionInputRole


CONTINUING_CHAPTER_REQUIRED_ASSET_TYPES = (
    "canon_snapshot",
    "character_state_snapshot",
    "relationship_state_snapshot",
    "timeline_snapshot",
    "foreshadow_snapshot",
    "promise_ledger_snapshot",
    "reward_ledger_snapshot",
    "world_rule_snapshot",
    "power_state_snapshot",
)

COLLECTION_ASSET_TYPES = frozenset(
    {
        "character_state_snapshot",
        "relationship_state_snapshot",
        "foreshadow_snapshot",
        "reader_promise",
        "reward_item",
        "world_rule",
        "knowledge_pack",
        "material_asset",
        "context_segment",
        "character_card",
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


_BASE_ALLOWED = (
    "chapter_plan", "outline", "outline_version", "volume_arc", "world_bible",
    "style_policy", "quality_profile", "quality_rubric", "platform_profile",
    "context_profile", "canon_snapshot", "character_state_snapshot",
    "relationship_state_snapshot", "timeline_snapshot", "foreshadow_snapshot",
    "promise_ledger_snapshot", "reward_ledger_snapshot", "world_rule_snapshot",
    "power_state_snapshot", "character_card", "genre_profile", "knowledge_pack",
    "material_asset", "reader_promise", "empty_state_declaration",
    "operator_checklist", "approval_decision",
    "structural_quality_report", "commercial_quality_report",
    "source_originality_quality_report", "longform_quality_report",
    "platform_quality_report",
)

STAGE_PROFILES = {
    stage: ProductionStageProfile(
        stage=stage,
        required_asset_types=("chapter_plan", "style_policy", "quality_rubric", "platform_profile")
        if stage in {"draft", "review", "revision", "canon_extraction", "quality"}
        else (),
        allowed_asset_types=_BASE_ALLOWED,
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
    )
    for stage in (
        "creative", "worldbuilding", "character", "outline", "chapter_plan",
        "draft", "review", "revision", "canon_extraction", "quality", "recap", "ending",
    )
}


def requirements_for(stage: str, chapter: int) -> tuple[ProductionInputRequirement, ...]:
    profile = STAGE_PROFILES[stage]
    required = list(profile.required_asset_types)
    if chapter > 1:
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
    "outline": "outline_version",
    "outline_version": "outline_version",
    "volume_arc": "volume_arc_version",
    "world_bible": "world_bible_version",
    "canon_snapshot": "canon_snapshot_version",
    "timeline_snapshot": "timeline_snapshot_version",
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
