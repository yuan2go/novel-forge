from __future__ import annotations

from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError


def validate_planned_character_knowledge(
    plan: Mapping[str, Any], story_state: Mapping[str, Any]
) -> None:
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
    for participation in plan.get("character_participation", []):
        character = str(participation.get("character_id") or "")
        declared = set(participation.get("known_fact_ids") or [])
        if not declared.issubset(known.get(character, set())):
            raise KernelError(
                "SCENE_ACCEPTED_KNOWLEDGE_MISMATCH",
                "Chapter participation cannot promote objective, reader, suspected or believed information to accepted Character Knowledge",
            )
