from dataclasses import asdict
import json
from typing import Any, Mapping

from novel_forge.modules.narrative_state.contracts import (
    NarrativeCausality,
    NarrativeCoordinate,
    NarrativeIdentity,
    NarrativeScope,
    NarrativeStateEvent,
    ReducerSemantics,
    narrative_event_id,
)
from novel_forge.modules.narrative_state.reducers import preview_state_events

from .dynamics import WorldTransition


def preview_preparation_transition(
    *,
    reality: Mapping[str, Any],
    transition: WorldTransition,
    chapter_number: int,
    path_id: str,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    previous = next(
        (
            entry
            for entry in reality.get("current_state", {}).get(
                transition.state_kind.value, []
            )
            if entry["entity_key"] == transition.entity_key
        ),
        {},
    )
    local_id = f"local:{transition.transition_id}"
    semantic = dict(
        state_kind=transition.state_kind,
        scope=NarrativeScope(str(reality["project_id"]), str(reality["book_id"])),
        identity=NarrativeIdentity(
            transition.state_kind.value,
            transition.entity_key,
            (("entity_key", transition.entity_key),),
        ),
        coordinate=NarrativeCoordinate(chapter_number, chapter_number),
        semantics=ReducerSemantics.TRANSITION,
        payload={
            **transition.changes,
            "world_transition": {
                "payload_json": json.dumps(
                    asdict(transition), sort_keys=True, separators=(",", ":")
                )
            },
        },
        supersedes_event_id="",
        provenance={"planning_baseline": reality["revision_id"], "path_id": path_id},
        confidence=1.0,
        coverage="PRIVATE_PREPARATION_SIMULATION",
        evidence={},
        event_version=3,
        entity_version=int(previous.get("entity_version") or 0) + 1,
        canon_status="NON_CANON_OBSERVATION",
        story_time=transition.story_time,
        causality=NarrativeCausality(
            cause_refs=transition.cause_refs,
            participant_ids=(transition.actor_id,),
            precondition_refs=tuple(
                requirement.requirement_id for requirement in transition.requirements
            ),
            effect_kinds=("STATE",),
        ),
    )
    event = NarrativeStateEvent(event_id=narrative_event_id(**semantic), **semantic)
    current = preview_state_events(previous=dict(reality), events=[event])
    entry = next(
        entry
        for entry in current[transition.state_kind.value]
        if entry["source_event_id"] == event.event_id
    )
    entry["source_event_id"] = local_id
    entry["story_time"] = transition.story_time.to_dict()
    return current, {**event.to_dict(), "event_id": local_id}
