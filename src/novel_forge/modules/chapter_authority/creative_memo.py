from __future__ import annotations

from typing import Any, Mapping

from .execution_artifacts import qualify_chapter_memo


def qualify_creative_memo(
    *, intent: Mapping[str, Any], intent_asset_version_id: str,
    result: Mapping[str, Any], execution_evidence: Mapping[str, Any],
    character_references: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    from .provider_output_contracts import validate_chapter_provider_output_schema

    validated = validate_chapter_provider_output_schema("memo", result)
    from .character_references import normalize_character_choices
    validated = normalize_character_choices(intent, validated, character_references)
    return qualify_chapter_memo(intent=intent, intent_asset_version_id=intent_asset_version_id,
                                result=validated, execution_evidence=execution_evidence)


def creative_memo_schema(*, legacy: bool = False, character_references=None) -> dict[str, Any]:
    def obj(properties):
        return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}

    text = {"type": "string", "minLength": 1, "maxLength": 2000}
    def rows(properties, maximum=32):
        return {"type": "array", "maxItems": maximum, "items": obj(properties)}

    identity = {"enum": [r["character_id"] for r in character_references["bindings"]]} if character_references else text
    return obj({
        "execution_strategy": text, "tension_strategy": text, "composition_strategy": text,
        "creative_guidance": obj({
            **{key: text for key in ("chapter_goal", "pov", "voice")},
            **{key: text if legacy else {"type": ["string", "null"]} for key in ("emotional_turn", "reader_promise", "ending_change")},
            "character_choices": rows({"character_id": identity, "choice": text, "motivation": text,
                                       "cost": text if legacy else {"type": ["string", "null"]}}),
            "constraints": {"type": "array", **({"minItems": 1} if legacy else {}), "maxItems": 32, "items": text},
        }),
        "scene_directives": rows({
            "scene_id": text,
            "directive": text,
            "conflict_progression": text if legacy else {"type": ["string", "null"]},
            "information_release": text,
            "emotional_change": text if legacy else {"type": ["string", "null"]},
            "transition": text,
        }),
        "retrieval_queries": {"type": "array", "minItems": 1, "maxItems": 8, "items": text},
        "obligation_actions": rows({"obligation_id": text, "action": text}),
        "arc_actions": rows({"arc_plan_version_id": text, "action": text}),
        "stop_conditions": {"type": "array", **({"minItems": 1} if legacy else {}), "maxItems": 16, "items": text},
    })
