"""Layer-specific deterministic gates for the qualified Story Foundation.

Semantic literary judgment remains independent evidence.  These validators
prove structural completeness, explicit parent references, and cross-layer
coherence without copying upstream truth into downstream contracts.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError

from .foundation import FoundationBinding, FoundationRole, foundation_upstream_digest


_CREATIVE_FIELDS = (
    "target_reader",
    "why_worth_writing",
    "genre",
    "subgenre",
    "core_desire",
    "core_fear",
    "core_conflict",
    "narrative_engine",
    "differentiation",
    "emotional_contract",
    "serialization_potential",
)
_CHARACTER_FIELDS = (
    "desire",
    "need",
    "fear",
    "wound",
    "false_belief",
    "moral_boundary",
    "agency",
    "capability",
    "weakness",
    "voice",
    "secret",
)


def validate_foundation_layer(
    *,
    role: FoundationRole,
    content: Mapping[str, Any],
    parent_bindings: tuple[FoundationBinding, ...],
    parent_contents: Mapping[FoundationRole, Mapping[str, Any]],
) -> dict[str, Any]:
    """Fail closed on structural or cross-layer drift for one Foundation layer."""

    expected_parents = role.required_parents
    if tuple(item.role for item in parent_bindings) != expected_parents:
        raise KernelError(
            "FOUNDATION_PARENT_SET_INVALID",
            f"{role.value} does not bind its exact ordered parent set",
        )
    if set(parent_contents) != set(expected_parents):
        raise KernelError(
            "FOUNDATION_PARENT_CONTENT_MISSING",
            f"{role.value} parent content projection is incomplete",
        )
    validators = {
        FoundationRole.CREATIVE_FOUNDATION: _validate_creative,
        FoundationRole.THEME_CONTRACT: _validate_theme,
        FoundationRole.ENDING_INTENT: _validate_ending,
        FoundationRole.READER_PROMISE: _validate_reader_promise,
        FoundationRole.WORLD_BIBLE: _validate_world,
        FoundationRole.CHARACTER_CAST: _validate_characters,
    }
    validators[role](content, parent_contents)
    return {
        "schema_version": "foundation-layer-validation.v1",
        "role": role.value,
        "structural": "PASS",
        "cross_layer": "PASS",
        "parent_roles": [item.value for item in expected_parents],
        "upstream_digest": (
            foundation_upstream_digest(parent_bindings) if parent_bindings else ""
        ),
    }


def _required_fields(content: Mapping[str, Any], fields: tuple[str, ...], role: str) -> None:
    missing = [field for field in fields if content.get(field) in (None, "", [])]
    if missing:
        raise KernelError(
            "FOUNDATION_LAYER_STRUCTURAL_INVALID",
            f"{role} is missing: {', '.join(missing)}",
        )


def _validate_creative(
    content: Mapping[str, Any], _parents: Mapping[FoundationRole, Mapping[str, Any]]
) -> None:
    normalized = dict(content)
    aliases = {
        "target_reader": "target_audience",
        "why_worth_writing": "core_fantasy",
        "genre": "target_genre",
        "core_desire": "protagonist_mechanism",
        "core_fear": "antagonist_mechanism",
        "emotional_contract": "emotional_engine",
        "serialization_potential": "serialization_strategy",
    }
    for target, source in aliases.items():
        normalized.setdefault(target, content.get(source))
    _required_fields(normalized, _CREATIVE_FIELDS, "CREATIVE_FOUNDATION")


def _validate_theme(
    content: Mapping[str, Any], parents: Mapping[FoundationRole, Mapping[str, Any]]
) -> None:
    question = str(
        content.get("thematic_question")
        or content.get("theme_question")
        or content.get("question")
        or ""
    ).strip()
    if len(question) < 16 or ("?" not in question and "？" not in question):
        raise KernelError(
            "FOUNDATION_LAYER_STRUCTURAL_INVALID",
            "THEME_CONTRACT requires a concrete pressure-and-choice question",
        )
    _require_creative_alignment(content, parents)


def _validate_ending(
    content: Mapping[str, Any], parents: Mapping[FoundationRole, Mapping[str, Any]]
) -> None:
    if not any(
        content.get(field)
        for field in (
            "ending_direction",
            "main_problem_resolution",
            "protagonist_final_choice",
            "intent",
        )
    ):
        raise KernelError(
            "FOUNDATION_LAYER_STRUCTURAL_INVALID",
            "ENDING_INTENT requires a direction or protagonist final choice",
        )
    if str(content.get("protagonist_cost") or "").strip().lower() in {
        "none",
        "zero",
    }:
        raise KernelError(
            "FOUNDATION_LAYER_STRUCTURAL_INVALID",
            "ENDING_INTENT cannot declare a costless resolution",
        )
    _require_creative_alignment(content, parents)


def _validate_reader_promise(
    content: Mapping[str, Any], parents: Mapping[FoundationRole, Mapping[str, Any]]
) -> None:
    if not any(
        content.get(field)
        for field in ("reader_promise", "reading_promise", "promise", "contract")
    ):
        raise KernelError(
            "FOUNDATION_LAYER_STRUCTURAL_INVALID",
            "READER_PROMISE requires an explicit reader-facing promise",
        )
    _require_creative_alignment(content, parents)


def _validate_world(
    content: Mapping[str, Any], parents: Mapping[FoundationRole, Mapping[str, Any]]
) -> None:
    rules = content.get("rules") or content.get("world_rules")
    if not isinstance(rules, list) or not rules:
        raise KernelError(
            "FOUNDATION_LAYER_STRUCTURAL_INVALID",
            "WORLD_BIBLE requires governed world rules",
        )
    required = ("rule", "cost", "consequence", "narrative_function")
    for index, raw in enumerate(rules):
        if not isinstance(raw, Mapping):
            raise KernelError(
                "FOUNDATION_LAYER_STRUCTURAL_INVALID",
                f"WORLD_BIBLE rule {index} must be an object",
            )
        normalized = dict(raw)
        normalized.setdefault("consequence", raw.get("observable_consequence"))
        _required_fields(normalized, required, f"WORLD_BIBLE.rules[{index}]")
    _require_declared_parent_bindings(content, parents)


def _validate_characters(
    content: Mapping[str, Any], parents: Mapping[FoundationRole, Mapping[str, Any]]
) -> None:
    characters = content.get("characters") or content.get("character_system")
    if not isinstance(characters, list) or not characters:
        raise KernelError(
            "FOUNDATION_LAYER_STRUCTURAL_INVALID",
            "CHARACTER_CAST requires at least one causal character",
        )
    for index, raw in enumerate(characters):
        if not isinstance(raw, Mapping):
            raise KernelError(
                "FOUNDATION_LAYER_STRUCTURAL_INVALID",
                f"CHARACTER_CAST member {index} must be an object",
            )
        normalized = dict(raw)
        normalized.setdefault("false_belief", raw.get("falseBelief"))
        _required_fields(normalized, _CHARACTER_FIELDS, f"CHARACTER_CAST[{index}]")
        if not (raw.get("values") or raw.get("value_hierarchy")):
            raise KernelError(
                "FOUNDATION_LAYER_STRUCTURAL_INVALID",
                f"CHARACTER_CAST[{index}] requires values",
            )
        if not (raw.get("arc_direction") or raw.get("growth_arc")):
            raise KernelError(
                "FOUNDATION_LAYER_STRUCTURAL_INVALID",
                f"CHARACTER_CAST[{index}] requires an Arc direction",
            )
    _require_declared_parent_bindings(content, parents)


def _require_creative_alignment(
    content: Mapping[str, Any], parents: Mapping[FoundationRole, Mapping[str, Any]]
) -> None:
    _require_declared_parent_bindings(content, parents)
    creative = parents[FoundationRole.CREATIVE_FOUNDATION]
    declared_genre = str(content.get("genre") or "").strip().casefold()
    creative_genre = str(
        creative.get("genre") or creative.get("target_genre") or ""
    ).strip().casefold()
    if declared_genre and creative_genre and declared_genre != creative_genre:
        raise KernelError(
            "FOUNDATION_CROSS_LAYER_CONFLICT",
            "Foundation child genre contradicts Creative Foundation",
        )


def _require_declared_parent_bindings(
    content: Mapping[str, Any],
    parents: Mapping[FoundationRole, Mapping[str, Any]],
) -> None:
    refs = content.get("foundation_parent_bindings")
    if not isinstance(refs, Mapping):
        raise KernelError(
            "FOUNDATION_LINEAGE_DRIFT",
            "foundation_parent_bindings must freeze exact parent versions and hashes",
        )
    expected = {
        role.value: {
            "asset_version_id": str(parent.get("asset_version_id") or ""),
            "content_hash": str(parent.get("content_hash") or ""),
        }
        for role, parent in parents.items()
    }
    normalized: dict[str, dict[str, str]] = {}
    for role, value in refs.items():
        if not isinstance(value, Mapping) or set(value) != {
            "asset_version_id",
            "content_hash",
        }:
            raise KernelError(
                "FOUNDATION_LINEAGE_DRIFT",
                "Foundation parent binding fields must match exactly",
            )
        normalized[str(role)] = {
            "asset_version_id": str(value.get("asset_version_id") or ""),
            "content_hash": str(value.get("content_hash") or ""),
        }
    if normalized != expected:
        raise KernelError(
            "FOUNDATION_LINEAGE_DRIFT",
            "Foundation child was generated against different parent evidence",
        )


__all__ = ["validate_foundation_layer"]
