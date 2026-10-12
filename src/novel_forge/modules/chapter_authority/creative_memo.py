from __future__ import annotations

import json
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


def input_only_memo(intent, intent_asset_version_id, *, failed_operation_id=None):
    from .execution_artifacts import _hash, validate_chapter_memo
    mission = intent["chapter_mission"]
    result = {
        "execution_strategy": json.dumps(mission, ensure_ascii=False),
        "tension_strategy": "", "composition_strategy": "",
        "scene_directives": [{"scene_id": row["scene_id"],
            "directive": json.dumps(row, ensure_ascii=False)} for row in intent["scene_plans"]],
        "retrieval_queries": [str(intent.get("title") or mission.get("chapter_goal") or intent["chapter"])],
        "obligation_actions": [],
        "arc_actions": [{"arc_plan_version_id": row["arc_plan_version_id"],
            "action": json.dumps(row, ensure_ascii=False)} for row in mission.get("arc_contributions", [])],
        "stop_conditions": [],
    }
    content = qualify_chapter_memo(intent=intent, intent_asset_version_id=intent_asset_version_id,
        result=result, execution_evidence={"model_call": "NOT_RUN", "source": "FROZEN_EXECUTION_INTENT"})
    content["qualification"] = "INPUT_FALLBACK"
    content["enhancement_status"] = "FAILED" if failed_operation_id else "NOT_REQUESTED"
    if failed_operation_id:
        content["execution_evidence"]["failed_enhancement_operation_id"] = failed_operation_id
    content.pop("memo_fingerprint")
    content["memo_fingerprint"] = _hash(content)
    return validate_chapter_memo(content, intent=intent, intent_asset_version_id=intent_asset_version_id)


def optional_memo_completion(uow, operation):
    uow.cursor.execute("""SELECT memo.content,intent.content FROM authority_operation_output_asset output
        JOIN authority_asset_version memo USING(asset_version_id)
        JOIN authority_asset memo_asset ON memo_asset.asset_id=memo.asset_id
        JOIN authority_asset_version intent ON intent.asset_version_id=memo.content->>'source_chapter_execution_intent_asset_version_id'
        JOIN authority_asset intent_asset ON intent_asset.asset_id=intent.asset_id
        JOIN authority_operation owner ON owner.operation_id=output.operation_id
        WHERE output.operation_id=%s AND owner.project_id=%s AND owner.definition_name='chapter.memo.generate'
          AND memo_asset.project_id=owner.project_id AND intent_asset.project_id=owner.project_id
          AND memo_asset.asset_type='chapter_memo' AND intent_asset.asset_type='chapter_execution_intent'
          AND output.role='primary' AND memo.content->>'qualification'='INPUT_FALLBACK'
          AND memo.content->>'enhancement_status' IN ('NOT_REQUESTED','FAILED')
          AND owner.input_asset_snapshot @> jsonb_build_array(jsonb_build_object(
              'asset_version_id',intent.asset_version_id,'content_hash',intent.content_hash))""",
        [operation["operation_id"], operation["project_id"]])
    row = uow.cursor.fetchone()
    if row is None:
        return False
    if row[0].get("enhancement_status") == "FAILED":
        source = optional_memo_failure_source(uow.cursor, operation["operation_id"], operation["project_id"])
        if source != row[0]["execution_evidence"].get("failed_enhancement_operation_id"):
            return False
    from .execution_artifacts import validate_chapter_memo
    validate_chapter_memo(row[0], intent=row[1],
        intent_asset_version_id=row[0]["source_chapter_execution_intent_asset_version_id"])
    return True


def optional_memo_failure_source(cursor, operation_id, project_id):
    cursor.execute("""SELECT predecessor.operation_id FROM authority_saga_step_successor successor
        JOIN authority_operation predecessor ON predecessor.operation_id=successor.predecessor_operation_id
        WHERE successor.successor_operation_id=%s AND predecessor.project_id=%s
          AND predecessor.definition_name='chapter.memo.generate'
          AND predecessor.status IN ('FAILED_FINAL','DEAD_LETTER')
          AND EXISTS(SELECT 1 FROM authority_external_effect effect WHERE effect.operation_id=predecessor.operation_id
            AND effect.effect_type='model.invoke')
          AND NOT EXISTS(SELECT 1 FROM authority_external_effect effect WHERE effect.operation_id=predecessor.operation_id
            AND (effect.effect_type<>'model.invoke' OR (effect.status IN ('UNKNOWN','RECONCILIATION_REQUIRED')
              AND NOT EXISTS(SELECT 1 FROM authority_generation_isolation isolation
                WHERE isolation.external_effect_id=effect.external_effect_id))))""", [operation_id, project_id])
    row = cursor.fetchone()
    return row[0] if row else None


def require_optional_memo_fallback(cursor, source, policy):
    from novel_forge.modules.production_execution.execution_template import selected_book_template
    from novel_forge.modules.command_kernel.errors import KernelError
    admission = selected_book_template(cursor, project_id=source["project_id"],
        book_id=str(source["command_payload"].get("book_id") or ""))
    cursor.execute("""SELECT external_effect_id,request_hash,status FROM authority_external_effect
        WHERE operation_id=%s AND effect_type='model.invoke' ORDER BY external_effect_id""", [source["operation_id"]])
    effects = cursor.fetchall()
    cursor.execute("""SELECT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=%s
        AND (effect_type<>'model.invoke' OR status NOT IN ('SUCCEEDED','FAILED_FINAL','FAILED_RETRYABLE')))""", [source["operation_id"]])
    unsafe = cursor.fetchone()[0]
    if (not admission or source["definition_name"] != "chapter.memo.generate" or unsafe or not effects
        or policy.get("source_operation_id") != source["operation_id"]
        or policy.get("terminal_effects") != [list(row) for row in effects]
        or policy.get("provider_invoked") is not False):
        raise KernelError("OPTIONAL_MEMO_FALLBACK_INVALID", "Require an owned terminal optional enhancement and exact retained effects")
    return True
