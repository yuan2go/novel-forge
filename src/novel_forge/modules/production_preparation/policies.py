from __future__ import annotations

ALWAYS_REQUIRED_ASSET_TYPES = (
    "chapter_plan",
    "style_policy",
    "quality_rubric",
    "operator_checklist",
    "operator_approval",
)

CONTINUING_CHAPTER_REQUIRED_ASSET_TYPES = (
    "canon_snapshot",
    "character_state_snapshot",
    "timeline_snapshot",
    "foreshadow_snapshot",
    "promise_ledger_snapshot",
    "reward_ledger_snapshot",
    "world_rule_snapshot",
    "power_state_snapshot",
)

OPTIONAL_CONTEXT_ASSET_TYPES = (
    "outline",
    "outline_version",
    "volume_arc",
    "world_bible",
    "character_card",
    "relationship_state_snapshot",
    "genre_profile",
    "platform_profile",
    "knowledge_pack",
    "material_asset",
    "reader_promise",
)

CONTEXT_VERSION_REF_KEYS = {
    "chapter_plan": "chapter_plan_version",
    "outline": "outline_version",
    "outline_version": "outline_version",
    "volume_arc": "volume_arc_version",
    "world_bible": "world_bible_version",
    "canon_snapshot": "canon_snapshot_version",
    "timeline_snapshot": "timeline_snapshot_version",
    "style_policy": "style_policy_version",
    "quality_rubric": "quality_rubric_version",
    "operator_checklist": "operator_checklist_version",
    "operator_approval": "operator_approval_version",
}
