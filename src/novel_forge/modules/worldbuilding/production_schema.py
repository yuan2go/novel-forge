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


def world_generation_schema(policy: WorldProductionPolicy) -> dict[str, Any]:
    transition = _object(
        {"payload_json": {"type": "string", "minLength": 2, "maxLength": 16384}}
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
    try:
        for candidate in result["candidates"]:
            candidate["transition"] = json.loads(
                candidate["transition"]["payload_json"]
            )
            WorldTransition.from_mapping(candidate["transition"])
            for path in candidate["preparation_paths"]:
                for step in path["steps"]:
                    step["transition"] = json.loads(step["transition"]["payload_json"])
                    WorldTransition.from_mapping(step["transition"])
    except (KeyError, TypeError, ValueError) as exc:
        raise KernelError(
            "WORLD_PROVIDER_TRANSITION_INVALID",
            "generated world transitions must decode to the declared typed contract",
        ) from exc
    return result
