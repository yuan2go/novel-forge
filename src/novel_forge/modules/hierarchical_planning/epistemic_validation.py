from __future__ import annotations

from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError


def accepted_character_knowledge(story_state: Mapping[str, Any]) -> dict[str, set[str]]:
    known: dict[str, set[str]] = {}
    current = story_state.get("current_state") or {}
    for entry in current.get("character_knowledge", []):
        state = entry.get("state") or {}
        if state.get("status") != "KNOWN":
            continue
        character = str(state.get("character_id") or "")
        fact = str(state.get("fact_id") or state.get("proposition_id") or "")
        if character and fact:
            known.setdefault(character, set()).add(fact)
    return known


def bind_planned_knowledge_schema(schema, story_state):
    from copy import deepcopy

    value = deepcopy(schema)
    facts = sorted({fact for entries in accepted_character_knowledge(story_state).values() for fact in entries})
    declaration = value["properties"]["character_participation"]["items"]["properties"]["known_fact_ids"]
    declaration["items"] = {"type": "string", **({"enum": facts} if facts else {})}
    if not facts:
        declaration["maxItems"] = 0
    declaration["description"] = (
        "Only frozen accepted Character Knowledge at chapter entry. Select supplied IDs for this character; "
        "working prose observations, agreements and remembered experiences are not accepted fact IDs. "
        "When none are supplied, use []. Continue working experiences in prose without inventing accepted knowledge."
    )
    return value


def validate_planned_character_knowledge(
    plan: Mapping[str, Any], story_state: Mapping[str, Any]
) -> None:
    known = accepted_character_knowledge(story_state)
    for participation in plan.get("character_participation", []):
        character = str(participation.get("character_id") or "")
        declared = set(participation.get("known_fact_ids") or [])
        if not declared.issubset(known.get(character, set())):
            raise KernelError(
                "SCENE_ACCEPTED_KNOWLEDGE_MISMATCH",
                "Chapter participation cannot promote objective, reader, suspected or believed information to accepted Character Knowledge",
            )
