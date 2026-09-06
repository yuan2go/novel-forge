from __future__ import annotations

from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError


REALITY_VIEWS = {
    "world": (
        "world_state",
        "world_rule",
        "faction_state",
        "location_state",
        "resource_state",
        "power_state",
    ),
    "characters": ("character_state", "character_arc", "relationship_state"),
    "epistemic": ("character_knowledge", "character_belief"),
    "reader": (
        "reader_knowledge",
        "reader_promise",
        "disclosure_event",
        "narrative_obligation",
    ),
    "obligations": ("narrative_obligation",),
}


def project_reality_view(
    reality: Mapping[str, Any], *, view: str, offset: int = 0, limit: int = 100
) -> dict[str, Any]:
    if (
        view not in REALITY_VIEWS
        or type(offset) is not int
        or offset < 0
        or type(limit) is not int
        or not 1 <= limit <= 200
    ):
        raise KernelError(
            "NARRATIVE_REALITY_VIEW_INVALID",
            "Reality view requires a known projection and bounded page",
        )
    entries = [
        {"state_kind": kind, **entry}
        for kind in REALITY_VIEWS[view]
        for entry in reality["current_state"].get(kind, [])
    ]
    entries.sort(key=lambda entry: (entry["state_kind"], entry["entity_key"]))
    selected = entries[offset : offset + limit]
    edges = [
        {
            "source_id": entry["state"]["source_id"],
            "target_id": entry["state"]["target_id"],
            "source_event_id": entry["source_event_id"],
            "entity_key": entry["entity_key"],
        }
        for entry in selected
        if entry["state_kind"] == "relationship_state"
    ]
    projection = {
        "contract_version": "narrative-reality-view.v1",
        "view": view,
        "revision_id": reality["revision_id"],
        "accepted_actual_version_id": reality["outcome_version_id"],
        "entries": selected,
        "edges": edges,
        "total": len(entries),
        "next_offset": offset + limit if offset + limit < len(entries) else None,
        "authority_mutated": False,
    }

    if view == "reader":
        projection["reader_information_roles"] = {
            "questions": [
                entry["entity_key"]
                for entry in selected
                if entry["state"].get("obligation_type")
                in {"MYSTERY", "INFORMATION_GAP", "OPEN_LOOP"}
            ],
            "expectations": [
                entry["entity_key"]
                for entry in selected
                if entry["state_kind"] == "reader_promise"
                or entry["state"].get("obligation_type")
                in {"READER_EXPECTATION", "PROMISE", "THEMATIC_PROMISE"}
            ],
            "suspicions": [
                entry["entity_key"]
                for entry in selected
                if entry["state_kind"] == "reader_knowledge"
                and entry["state"].get("status")
                in {"SUSPECTED", "HINTED", "MISDIRECTED"}
            ],
            "emotional_debts": [
                entry["entity_key"]
                for entry in selected
                if entry["state"].get("obligation_type") == "EMOTIONAL_DEBT"
            ],
        }
        projection["reader_information_proof_ceiling"] = (
            "ACCEPTED_NARRATED_AUDIENCE_INFORMATION_NOT_MEASURED_READER_RESPONSE"
        )
    return projection


def project_why_trace(reality: Mapping[str, Any], *, event_id: str) -> dict[str, Any]:
    events = {event["event_id"]: event for event in reality.get("events", [])}
    if event_id not in events:
        raise KernelError(
            "NARRATIVE_WHY_EVENT_UNKNOWN",
            "Why trace requires an event in the accepted Reality",
        )
    queue = [event_id]
    visited: set[str] = set()
    nodes = []
    edges = []
    external_refs: set[str] = set()
    while queue and len(nodes) < 64:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        event = events.get(current)
        if event is None:
            external_refs.add(current)
            continue
        nodes.append(event)
        for cause in event.get("causality", {}).get("cause_refs", []):
            edges.append({"cause": cause, "effect": current})
            if cause not in visited:
                queue.append(cause)
    return {
        "contract_version": "narrative-why-trace.v1",
        "revision_id": reality["revision_id"],
        "event_id": event_id,
        "nodes": nodes,
        "edges": edges,
        "external_evidence_refs": sorted(external_refs),
        "remaining_event_ids": sorted(set(queue) - visited),
        "complete_within_accepted_events": not queue and not external_refs,
        "authority_mutated": False,
    }
