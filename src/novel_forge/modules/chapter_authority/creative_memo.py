from __future__ import annotations

from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError

from .execution_artifacts import qualify_chapter_memo


def qualify_creative_memo(
    *, intent: Mapping[str, Any], intent_asset_version_id: str,
    result: Mapping[str, Any], execution_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    from .provider_output_contracts import validate_chapter_provider_output_schema

    validated = validate_chapter_provider_output_schema("memo", result)
    participants = {str(value) for scene in intent.get("scene_plans", []) for value in scene.get("participants", [])}
    choices = validated["creative_guidance"]["character_choices"]
    if any(choice["character_id"] not in participants for choice in choices):
        raise KernelError("CHAPTER_MEMO_CHARACTER_DRIFT", "creative choices require an exact frozen Scene participant")
    return qualify_chapter_memo(intent=intent, intent_asset_version_id=intent_asset_version_id,
                                result=validated, execution_evidence=execution_evidence)


def creative_memo_schema(*, legacy: bool = False) -> dict[str, Any]:
    def obj(properties):
        return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}

    text = {"type": "string", "minLength": 1, "maxLength": 2000}
    def rows(properties, maximum=32):
        return {"type": "array", "maxItems": maximum, "items": obj(properties)}

    return obj({
        "execution_strategy": text, "tension_strategy": text, "composition_strategy": text,
        "creative_guidance": obj({
            **{key: text for key in ("chapter_goal", "pov", "voice")},
            **{key: text if legacy else {"type": ["string", "null"]} for key in ("emotional_turn", "reader_promise", "ending_change")},
            "character_choices": rows({"character_id": text, "choice": text, "motivation": text,
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
