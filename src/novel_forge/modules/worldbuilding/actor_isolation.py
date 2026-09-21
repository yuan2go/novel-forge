from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state.reality import narrative_hash

ACTOR_STAGES = ("world_candidates.actor_0", "world_candidates.actor_1", "world_candidates.actor_2")
ACTOR_TRAITS = ("name", "desire", "need", "fear", "false_belief", "moral_boundary", "capability", "weakness", "behavioral_pattern", "risk_preference")
KNOWLEDGE_FIELDS = ("character_id", "fact_id", "proposition_id", "status", "stance", "proposition", "claim", "content", "statement", "description")


def validate_actor_policy(value: Mapping[str, Any], *, character_ids: list[str], policy: Any) -> dict[str, Any]:
    if set(value) != {"version", "actor_ids", "max_rounds", "max_actions_per_actor"} or value["version"] != "world-actor-experiment.v1":
        raise KernelError("WORLD_ACTOR_POLICY_INVALID", "an explicit bounded actor experiment policy is required")
    actors = value["actor_ids"]
    if (not isinstance(actors, list) or not 1 <= len(actors) <= 3
        or any(not isinstance(actor, str) or actor not in character_ids for actor in actors)
        or len(set(actors)) != len(actors) or any(type(value[key]) is not int or value[key] != 1 for key in ("max_rounds", "max_actions_per_actor"))
        or policy.version != "world-production-policy.v2" or policy.max_provider_stages != len(actors) + 2
        or policy.max_candidates > len(actors) or policy.max_paths_per_candidate != 1
        or policy.max_preparation_steps != 1 or policy.planning_window_chapters != 1):
        raise KernelError("WORLD_ACTOR_POLICY_INVALID", "experiment admits at most three approved actors, one action each and one frozen round plus judge and Director")
    return deepcopy(dict(value))


def actor_task(source: Mapping[str, Any], source_ref: Mapping[str, str], actor_id: str) -> dict[str, Any]:
    cast = next((item for item in source["character_definitions"] if item["character_id"] == actor_id), None)
    if cast is None or not str(cast.get("desire") or "").strip():
        raise KernelError("WORLD_ACTOR_GOAL_UNAVAILABLE", "actor needs its own approved desire before any dispatch")
    traits = {key: cast[key] for key in ACTOR_TRAITS if isinstance(cast.get(key), str)}
    observations = []
    for kind in ("character_knowledge", "character_belief"):
        for entry in source["reality"]["current_state"].get(kind, []):
            state = entry.get("state") or {}
            if state.get("character_id") != actor_id or (kind == "character_knowledge" and state.get("status") not in {"KNOWN", "SUSPECTED"}):
                continue
            projected = {key: state[key] for key in KNOWLEDGE_FIELDS if isinstance(state.get(key), (str, int, float, bool))}
            observations.append({"source_event_id": entry["source_event_id"], "kind": kind, "content": projected})
    if not observations:
        raise KernelError(
            "WORLD_ACTOR_KNOWLEDGE_UNAVAILABLE",
            "an actor needs its own frozen initial or accepted knowledge/belief before any dispatch",
        )
    private = {"actor_id": actor_id, "traits": traits, "observations": observations}
    return {
        "contract_version": "world-actor-task.v1", "role": "ACTOR", "source_ref": dict(source_ref),
        "baseline_id": source["reality"]["revision_id"], "baseline_kind": source["reality"]["baseline_kind"],
        "accepted_through_chapter": source["reality"]["chapter_number"], "private_observation": private,
        "projection_identity": narrative_hash(private), "policy": dict(source["policy"]), "fact_mutation_allowed": False,
        "instructions": "Choose one intended action from your own desire and supplied knowledge or beliefs. Other characters, global secrets, the outline and future events are unavailable. Beliefs are not objective facts. Do not invent acquired knowledge. Supply only a short action-basis summary and listed source IDs; never provide internal reasoning or a chain of thought. A judge determines feasibility and consequences, and cannot rewrite your intention.",
    }


def validate_actor_task(task: Mapping[str, Any]) -> None:
    allowed = {"contract_version", "role", "source_ref", "baseline_id", "baseline_kind", "accepted_through_chapter", "private_observation", "projection_identity", "policy", "fact_mutation_allowed", "instructions"}
    private = task.get("private_observation") or {}
    if (set(task) != allowed or task.get("contract_version") != "world-actor-task.v1" or task.get("role") != "ACTOR"
        or task.get("fact_mutation_allowed") is not False or set(private) != {"actor_id", "traits", "observations"}
        or task.get("projection_identity") != narrative_hash(private) or not set(private["traits"]).issubset(ACTOR_TRAITS)
        or any(row.get("content", {}).get("character_id") != private["actor_id"] or not set(row.get("content", {})).issubset(KNOWLEDGE_FIELDS) for row in private["observations"])):
        raise KernelError("WORLD_ACTOR_CONTEXT_LEAK", "actor request must contain only its frozen private projection")


def actor_output_schema(task: Mapping[str, Any]) -> dict[str, Any]:
    private = task["private_observation"]
    refs = ["APPROVED_SELF_TRAITS", *[row["source_event_id"] for row in private["observations"]]]
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "additionalProperties": False,
            "properties": {"actor_id": {"type": "string", "enum": [private["actor_id"]]},
                           "action": {"type": "string", "minLength": 1, "maxLength": 1000},
                           "basis_summary": {"type": "string", "minLength": 1, "maxLength": 1000},
                           "basis_refs": {"type": "array", "minItems": 1, "maxItems": 16, "items": {"type": "string", "enum": refs}}},
            "required": ["actor_id", "action", "basis_summary", "basis_refs"]}


def validate_actor_output(raw: Mapping[str, Any], task: Mapping[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.chapter_authority.provider_output_contracts import validate_chapter_provider_output_against_schema
    validate_chapter_provider_output_against_schema("actor", actor_output_schema(task), raw)
    return {**deepcopy(dict(raw)), "projection_identity": task["projection_identity"], "proposal_hash": narrative_hash(raw)}


def actor_judge_schema(schema: Mapping[str, Any], proposals: list[dict[str, Any]]) -> dict[str, Any]:
    result = deepcopy(dict(schema))
    result["properties"]["actor_adjudications"] = {
        "type": "array", "minItems": len(proposals), "maxItems": len(proposals),
        "items": {"type": "object", "additionalProperties": False,
                  "properties": {"actor_id": {"type": "string", "enum": [row["actor_id"] for row in proposals]},
                                 "proposal_hash": {"type": "string", "enum": [row["proposal_hash"] for row in proposals]},
                                 "decision": {"type": "string", "enum": ["EXECUTABLE", "REJECTED"]},
                                 "consequence_summary": {"type": "string", "minLength": 1}},
                  "required": ["actor_id", "proposal_hash", "decision", "consequence_summary"]}}
    result["required"].append("actor_adjudications")
    return result


def require_actor_judgments(generated: Mapping[str, Any], proposals: list[dict[str, Any]]) -> None:
    from novel_forge.modules.worldbuilding.production_schema import decode_world_generation
    by_actor = {row["actor_id"]: row for row in proposals}
    judgments = generated.get("actor_adjudications")
    if not isinstance(judgments, list) or len(judgments) != len(by_actor) or {row.get("actor_id") for row in judgments} != set(by_actor):
        raise KernelError("WORLD_ACTOR_JUDGMENT_INCOMPLETE", "all actor proposals need one exact adjudication before a world action")
    decoded = decode_world_generation({key: value for key, value in generated.items() if key not in {"actor_adjudications", "knowledge_translations"}})
    candidates = decoded["candidates"]
    for judgment in judgments:
        proposal = by_actor[judgment["actor_id"]]
        matching = [row for row in candidates if row["transition"]["actor_id"] == proposal["actor_id"]]
        if (judgment.get("proposal_hash") != proposal["proposal_hash"] or judgment.get("decision") not in {"EXECUTABLE", "REJECTED"}
            or bool(matching) != (judgment["decision"] == "EXECUTABLE") or len(matching) > 1
            or any(row["transition"]["action"] != proposal["action"] or row["preparation_paths"] for row in matching)):
            raise KernelError("WORLD_ACTOR_INTENT_REWRITTEN", "judge can accept or reject intention and determine consequences, but cannot invent actions or preparation branches")
    if any(row["transition"]["actor_id"] not in by_actor for row in candidates):
        raise KernelError("WORLD_ACTOR_INTENT_REWRITTEN", "judge introduced an unadmitted actor")
