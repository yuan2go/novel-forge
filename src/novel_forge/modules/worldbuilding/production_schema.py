from copy import deepcopy
import json
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.hierarchical_planning.causal_domain import DIRECTOR_DIMENSIONS

from .dynamics import WorldTransition
from .production_planning import WorldProductionPolicy


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _strings() -> dict[str, Any]:
    return {
        "type": "array",
        "maxItems": 16,
        "items": {"type": "string", "minLength": 1},
    }


def world_transition_schema() -> dict[str, Any]:
    from novel_forge.modules.narrative_state.contracts import NarrativeStateKind
    from .dynamics import RequirementOperator

    text = {"type": "string", "minLength": 1}
    predicate = _object(
        {
            "requirement_id": text,
            "state_kind": {
                "type": "string",
                "enum": [item.value for item in NarrativeStateKind],
            },
            "entity_key": text,
            "field": text,
            "operator": {
                "type": "string",
                "enum": [item.value for item in RequirementOperator],
            },
            "value": {
                "anyOf": [
                    {"type": kind} for kind in ("string", "number", "boolean", "null")
                ]
            },
        }
    )
    predicate["description"] = (
        "Copy exact causal state identity and field. EXISTS may use null value; numeric comparison requires a numeric value. Epistemic bases must use character_knowledge or character_belief."
    )
    result = _object(
        {
            "transition_id": text,
            "actor_id": text,
            "camera": {
                "type": "string",
                "enum": ["ON_CAMERA", "OFF_CAMERA", "UNDERCURRENT"],
            },
            "story_time": _object(
                {
                    "timeline_id": text,
                    "start_ordinal": {"type": "integer", "minimum": 1},
                    "end_ordinal": {"type": "integer", "minimum": 1},
                    "precision": {
                        "type": "string",
                        "enum": ["EXACT", "ORDERED", "RANGE"],
                    },
                    "label": {"type": "string"},
                }
            ),
            "action": text,
            "state_kind": {
                "type": "string",
                "enum": [item.value for item in NarrativeStateKind],
            },
            "entity_key": text,
            "changes": {"type": "object", "minProperties": 1},
            "requirements": {
                "type": "array",
                "items": {
                    **deepcopy(predicate),
                    "properties": {
                        **predicate["properties"],
                        "state_kind": {
                            "type": "string",
                            "enum": [
                                item.value
                                for item in NarrativeStateKind
                                if item
                                not in {
                                    NarrativeStateKind.READER_KNOWLEDGE,
                                    NarrativeStateKind.DISCLOSURE_EVENT,
                                    NarrativeStateKind.READER_PROMISE,
                                    NarrativeStateKind.NARRATIVE_OBLIGATION,
                                }
                            ],
                        },
                    },
                },
            },
            "cause_refs": {
                "type": "array",
                "items": text,
                "minItems": 1,
                "uniqueItems": True,
            },
            "epistemic_basis": {
                "type": "array",
                "items": {
                    **deepcopy(predicate),
                    "properties": {
                        **predicate["properties"],
                        "state_kind": {
                            "type": "string",
                            "enum": ["character_knowledge", "character_belief"],
                        },
                    },
                },
            },
        }
    )
    result["description"] = (
        "Serialized WorldTransition, not prose. Copy approved actor/entity identities and exact frozen foundation or accepted causal references. story_time is an ordered object, never a chapter label string; end_ordinal must be at least start_ordinal. No invented prerequisites or inferred accepted facts."
    )
    return result


def world_generation_schema(
    policy: WorldProductionPolicy, *, audience_scoped: bool = False
) -> dict[str, Any]:
    transition = _object(
        {
            "payload_json": {
                "type": "string",
                "minLength": 2,
                "maxLength": 16384,
                "description": "JSON serialization of this typed contract: "
                + json.dumps(
                    world_transition_schema(), ensure_ascii=False, sort_keys=True
                ),
            }
        }
    )
    path = _object(
        {
            "path_id": {"type": "string", "minLength": 1},
            "rationale": {"type": "string", "minLength": 1},
            "steps": {
                "type": "array",
                "minItems": 1,
                "maxItems": policy.max_preparation_steps,
                "items": _object(
                    {
                        "transition": transition,
                        "chapter_offset": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": policy.planning_window_chapters - 1,
                        },
                    }
                ),
            },
        }
    )
    candidate = _object(
        {
            "transition": transition,
            **{
                key: _strings()
                for key in (
                    "affected_entities",
                    "world_consequences",
                    "arc_refs",
                    "obligation_refs",
                    "risks",
                    "soft_assumptions",
                    "narrative_preferences",
                )
            },
            "rationale": {"type": "string", "minLength": 1},
            "preparation_paths": {
                "type": "array",
                "maxItems": policy.max_paths_per_candidate,
                "items": path,
            },
            "information_scope": _object(
                {
                    "reader_exposure": {
                        "type": "string",
                        "enum": ["CONCEAL", "REVEAL"],
                    },
                    "reveal_event_ids": {
                        "type": "array",
                        "maxItems": 8,
                        "items": {"type": "string", "minLength": 1},
                    },
                }
            ),
        }
    )
    if audience_scoped:
        candidate["properties"]["information_scope"] = _object(
            {
                "disclosures": {
                    "type": "array",
                    "maxItems": 8,
                    "items": _object(
                        {
                            "disclosure_id": {"type": "string", "minLength": 1},
                            "event_id": {"type": "string", "minLength": 1},
                            "audience": {
                                "type": "string",
                                "minLength": 1,
                                "description": "READER or one exact character_id. Mixed audiences use distinct disclosure records; no implicit ALL.",
                            },
                            "mode": {
                                "type": "string",
                                "enum": [
                                    "HINT",
                                    "PARTIAL",
                                    "MISDIRECT",
                                    "CONFIRM",
                                    "WITHHOLD",
                                ],
                            },
                            "fields": {
                                "type": "array",
                                "maxItems": 16,
                                "items": {"type": "string", "minLength": 1},
                                "description": "Only explicit scalar event fields may be presented. WITHHOLD requires no fields. Private causes, decisions and summaries are never presentation fields.",
                            },
                            "presentation_channel": {"type": "string", "minLength": 1},
                            "claim_kind": {
                                "type": "string",
                                "enum": ["CURRENT_ASSERTION", "HISTORICAL_OCCURRENCE"],
                            },
                        }
                    ),
                }
            }
        )
    return _object(
        {
            "disposition": {"type": "string", "enum": ["CANDIDATES", "NO_OP", "DEFER"]},
            "reason": {"type": "string", "minLength": 1},
            "candidates": {
                "type": "array",
                "maxItems": policy.max_candidates,
                "items": candidate,
            },
        }
    )


def world_evaluation_schema(generated: Mapping[str, Any]) -> dict[str, Any]:
    ids = [
        candidate["transition"]["transition_id"]
        for candidate in generated["candidates"]
    ]
    return _object(
        {
            "evaluations": {
                "type": "array",
                "minItems": len(ids),
                "maxItems": len(ids),
                "items": _object(
                    {
                        "transition_id": {
                            "type": "string",
                            "enum": ids or ["NO_CANDIDATE"],
                        },
                        "dimensions": _object(
                            {
                                key: {"type": "number", "minimum": 0, "maximum": 1}
                                for key in DIRECTOR_DIMENSIONS
                            }
                        ),
                        "rationale": {"type": "string", "minLength": 1},
                        "preferred_path_id": {"type": "string"},
                    }
                ),
            }
        }
    )


def decode_world_generation(raw: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(raw))
    location = "$.candidates"
    try:
        for index, candidate in enumerate(result["candidates"]):
            location = f"$.candidates[{index}].transition.payload_json"
            candidate["transition"] = json.loads(
                candidate["transition"]["payload_json"]
            )
            WorldTransition.from_mapping(candidate["transition"])
            for path_index, path in enumerate(candidate["preparation_paths"]):
                for step_index, step in enumerate(path["steps"]):
                    location = f"$.candidates[{index}].preparation_paths[{path_index}].steps[{step_index}].transition.payload_json"
                    step["transition"] = json.loads(step["transition"]["payload_json"])
                    WorldTransition.from_mapping(step["transition"])
    except (KeyError, TypeError, ValueError) as exc:
        raise KernelError(
            "WORLD_PROVIDER_TRANSITION_INVALID",
            f"{location}: generated world transitions must decode to the declared typed contract; {exc}",
        ) from exc
    return result
