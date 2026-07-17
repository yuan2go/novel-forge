"""Storage-free deep character and evolving relationship validation."""
from __future__ import annotations

from typing import Any


CHARACTER_FIELDS = ("desire", "need", "fear", "wound", "false_belief", "value_hierarchy", "moral_boundary", "capability", "weakness", "agency", "voice", "public_identity", "private_identity", "secret", "relationship_goals", "conflict_style", "growth_arc", "failure_arc", "reader_charm_mechanism")


def build_character(*, project_id: str, creative_brief_version_id: str, world_bible_version_id: str, theme_question_version_id: str, profile: dict[str, Any]) -> dict[str, Any]:
    if profile.get("project_id") != project_id:
        raise ValueError("character is outside project scope")
    missing = [field for field in CHARACTER_FIELDS if profile.get(field) in (None, "", [])]
    if missing:
        raise ValueError("CharacterCard missing: " + ", ".join(missing))
    if not profile.get("capability_cost"):
        raise ValueError("character capability requires a cost")
    return {**profile, "creative_brief_version_id": creative_brief_version_id, "world_bible_version_id": world_bible_version_id, "theme_question_version_id": theme_question_version_id, "character_contract_version": "deep-character-v1"}


def build_relationship_state(*, project_id: str, left_character_version_id: str, right_character_version_id: str, state: dict[str, Any], previous_state_version_id: str = "") -> dict[str, Any]:
    required = ("relationship_edge", "power_relation", "trust_state", "debt", "dependency", "hidden_conflict", "relationship_arc")
    missing = [field for field in required if state.get(field) in (None, "")]
    if missing or left_character_version_id == right_character_version_id:
        raise ValueError("invalid relationship state: " + ", ".join(missing or ["distinct_characters_required"]))
    return {"project_id": project_id, "left_character_version_id": left_character_version_id, "right_character_version_id": right_character_version_id, "previous_state_version_id": previous_state_version_id, **state, "relationship_state_contract_version": "relationship-state-v1"}


__all__ = ["build_character", "build_relationship_state"]
