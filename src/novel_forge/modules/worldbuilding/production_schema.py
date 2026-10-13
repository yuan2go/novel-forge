from copy import deepcopy
import json
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.hierarchical_planning.causal_domain import DIRECTOR_DIMENSIONS

from .dynamics import WorldTransition
from .production_planning import WorldProductionPolicy


def world_transition_payload_schema(*, agency: bool = False, working_observations: bool = False) -> dict[str, Any]:
    return world_transition_schema(agency=agency, working_observations=working_observations)


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


def _frozen_world_transition_schema() -> dict[str, Any]:
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
            "transition_id": {**text, "description": "Use a batch-local name matching [A-Za-z][A-Za-z0-9_-]{0,63}, without a local: prefix. In cause_refs, refer to a preparation event as local:<name>; other references must be exact supplied foundation or accepted event identities."},
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
                "description": "Every approved character action requires a nonempty basis referring to that actor's supplied character_knowledge or character_belief state and satisfying its exact predicate. An approved character definition or foundation cause is not acquired knowledge. Do not invent a basis when the accepted initial state is empty; return NO_OP or DEFER with the missing support explained instead of an executable character action.",
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


def world_transition_schema(*, agency: bool = False, working_observations: bool = False) -> dict[str, Any]:
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
    if working_observations and not agency:
        raise KernelError("WORLD_WORKING_AGENCY_REQUIRED", "Working observation references require the scoped agency contract")
    if not agency:
        return _frozen_world_transition_schema()
    result = _object(
        {
            "transition_id": {
                **text,
                "description": "Use a batch-local name matching [A-Za-z][A-Za-z0-9_-]{0,63}, without a local: prefix. In cause_refs, refer to a preparation event as local:<name>; other references must be exact supplied foundation or accepted event identities.",
            },
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
                "description": "Information-dependent decisions require the actor's own supplied knowledge/belief predicates. Under world-agency.v2 classify action_mode explicitly. ROUTINE cannot grant epistemic state; PERCEPTION needs objective source predicates and cause refs. Own-character knowledge acquisition binds changes.observation_source {state_kind,entity_key,field,value} to an EQUALS source predicate. Sources precede perception, and a later information-dependent decision depends on that actor's acquisition. No borrowed, reader, future or self-supporting knowledge. Proposed steps remain unaccepted. NO_OP/DEFER only when actually appropriate to the story.",
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
    if not agency:
        result["properties"]["epistemic_basis"]["description"] = (
            "Every approved character action requires a nonempty basis referring to that actor's supplied character_knowledge or character_belief state and satisfying its exact predicate. An approved character definition or foundation cause is not acquired knowledge. Do not invent a basis when the accepted initial state is empty; return NO_OP or DEFER with the missing support explained instead of an executable character action."
        )
    if agency:
        result["properties"]["action_mode"] = {
            "type": "string",
            "enum": ["ROUTINE", "PERCEPTION", "INFORMATION_DEPENDENT"],
            "description": "ROUTINE: ordinary non-epistemic agency supported by supplied Foundation or accepted causes, never hidden-information decisions. PERCEPTION: observe an available objective source. INFORMATION_DEPENDENT: act on this character's own knowledge/belief. Director checks the classification against action and effects.",
        }
        result["required"].append("action_mode")
        result["properties"]["changes"]["description"] = (
            "Use state-kind semantics: resource_state is quantitative inventory/balance (initial balance or reconciled balance_before/delta/balance_after). Nonquantitative availability/access/status belongs to world_state for the exact approved entity. character_knowledge is one own character/proposition with status KNOWN and observation_source for PERCEPTION. Changes are proposals, not accepted facts. Never invent a numeric balance for a document's access status."
        )
    result["description"] = (
        "Serialized WorldTransition, not prose. Copy approved actor/entity identities and exact frozen foundation or accepted causal references. story_time is an ordered object, never a chapter label string; end_ordinal must be at least start_ordinal. No invented prerequisites or inferred accepted facts."
    )
    if working_observations:
        result["description"] = "Serialized WorldTransition proposal with exact supplied Foundation, accepted or selected-working causal references. Working evidence remains unreviewed and cannot establish objective facts or accepted knowledge. story_time is an ordered object; preserve actor, source identity and attributed information."
        result["properties"]["transition_id"]["description"] = (
            "Use a bare batch-local name matching [A-Za-z][A-Za-z0-9_-]{0,63}. In cause_refs use local:<name> for preparation events; other references must be exact supplied Foundation, accepted event or selected-working observation source_event_id identities. Working observations are unreviewed candidate experience, not accepted history or objective World facts."
        )
        result["properties"]["epistemic_basis"]["description"] += (
            " Own selected-working observation entries may supply their exact state_kind, entity_key and proposition predicate. Preserve attribution and perspective; a represented belief or hearsay may be wrong. Do not replace missing observation entries with invented knowledge or use reader-only disclosure."
        )
        result["properties"]["action_mode"]["description"] = "ROUTINE: ordinary non-epistemic agency supported by supplied Foundation, accepted or working experience; never a hidden-information decision. PERCEPTION: observe an available objective source. INFORMATION_DEPENDENT: act on this character's own supplied knowledge or represented belief. Director checks classification and the located working passages."
    return result


def _frozen_world_generation_schema(
    policy: WorldProductionPolicy, *, audience_scoped: bool = False,
    arc_refs: tuple[str, ...] | None = None, obligation_refs: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    transition = _object(
        {
            "payload_json": {
                "type": "string",
                "minLength": 2,
                "maxLength": 16384,
                "description": "JSON serialization of this typed contract: "
                + json.dumps(
                    _frozen_world_transition_schema(), ensure_ascii=False, sort_keys=True
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
            "affected_entities": {**_strings(), "minItems": 1},
            "world_consequences": {**_strings(), "minItems": 1},
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
    for key, allowed in (("arc_refs", arc_refs), ("obligation_refs", obligation_refs)):
        if allowed is not None:
            candidate["properties"][key] = {"type": "array", "maxItems": len(allowed),
                "items": {"type": "string", **({"enum": list(allowed)} if allowed else {})},
                "description": "Only these exact native references are authorized; use an empty array when none applies."}
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


def world_generation_schema(
    policy: WorldProductionPolicy, *, audience_scoped: bool = False,
    arc_refs: tuple[str, ...] | None = None, obligation_refs: tuple[str, ...] | None = None,
    agency: bool = False,
    working_observations: bool = False,
) -> dict[str, Any]:
    if working_observations and not agency:
        raise KernelError("WORLD_WORKING_AGENCY_REQUIRED", "Working observation references require the scoped agency contract")
    if not agency:
        return _frozen_world_generation_schema(policy, audience_scoped=audience_scoped, arc_refs=arc_refs, obligation_refs=obligation_refs)
    transition = _object(
        {
            "payload_json": {
                "type": "string",
                "minLength": 2,
                "maxLength": 16384,
                "description": "JSON serialization of this typed contract: "
                + json.dumps(
                    world_transition_schema(agency=agency, working_observations=working_observations),
                    ensure_ascii=False,
                    sort_keys=True,
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
            "affected_entities": {**_strings(), "minItems": 1},
            "world_consequences": {**_strings(), "minItems": 1},
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
    for key, allowed in (("arc_refs", arc_refs), ("obligation_refs", obligation_refs)):
        if allowed is not None:
            candidate["properties"][key] = {"type": "array", "maxItems": len(allowed),
                "items": {"type": "string", **({"enum": list(allowed)} if allowed else {})},
                "description": "Only these exact native references are authorized; use an empty array when none applies."}
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


def _frozen_world_evaluation_schema(generated: Mapping[str, Any]) -> dict[str, Any]:
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


def world_evaluation_schema(
    generated: Mapping[str, Any], *, agency: bool = False
) -> dict[str, Any]:
    if not agency:
        return _frozen_world_evaluation_schema(generated)
    ids = [
        candidate["transition"]["transition_id"]
        for candidate in generated["candidates"]
    ]
    result = _object(
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
    if agency:
        paths = list(agency_transition_paths(generated))
        result["properties"]["action_classifications"] = {
            "type": "array",
            "minItems": len(paths),
            "maxItems": len(paths),
            "items": _object(
                {
                    "field_path": {"type": "string", "enum": paths or ["NO_CANDIDATE"]},
                    "supported": {"type": "boolean"},
                    "rationale": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Check actual action and effects: ordinary agency cannot conceal a decision using unacquired/private information; perception needs an available source and correctly ordered actor scope. Report unsupported classifications separately from soft literary scores.",
                    },
                }
            ),
        }
        result["required"].append("action_classifications")
    return result


def _frozen_decode_world_generation(raw: Mapping[str, Any]) -> dict[str, Any]:
    from .dynamics import require_contract_fields

    def historical_transition(value):
        require_contract_fields(value, required={"transition_id", "actor_id", "camera", "story_time", "action", "state_kind", "entity_key", "changes", "requirements", "cause_refs"}, optional={"epistemic_basis"})
        return WorldTransition.from_mapping(value)

    result = deepcopy(dict(raw))
    location = "$.candidates"
    try:
        for index, candidate in enumerate(result["candidates"]):
            location = f"$.candidates[{index}].transition.payload_json"
            candidate["transition"] = json.loads(
                candidate["transition"]["payload_json"]
            )
            historical_transition(candidate["transition"])
            for path_index, path in enumerate(candidate["preparation_paths"]):
                for step_index, step in enumerate(path["steps"]):
                    location = f"$.candidates[{index}].preparation_paths[{path_index}].steps[{step_index}].transition.payload_json"
                    step["transition"] = json.loads(step["transition"]["payload_json"])
                    historical_transition(step["transition"])
    except (KeyError, TypeError, ValueError) as exc:
        raise KernelError(
            "WORLD_PROVIDER_TRANSITION_INVALID",
            f"{location}: generated world transitions must decode to the declared typed contract; {exc}",
        ) from exc
    return result


def decode_world_generation(raw: Mapping[str, Any], *, agency: bool = False) -> dict[str, Any]:
    if not agency:
        return _frozen_decode_world_generation(raw)
    from novel_forge.modules.chapter_authority.provider_output_contracts import (
        collect_native_world_schema_diagnostics,
    )

    result = deepcopy(dict(raw))
    diagnostics = []
    for index, candidate in enumerate(result.get("candidates", [])):
        slots = [
            (candidate, "transition", f"$.candidates[{index}].transition.payload_json")
        ]
        for path_index, path in enumerate(candidate.get("preparation_paths", [])):
            for step_index, step in enumerate(path.get("steps", [])):
                slots.append(
                    (
                        step,
                        "transition",
                        f"$.candidates[{index}].preparation_paths[{path_index}].steps[{step_index}].transition.payload_json",
                    )
                )
        for owner, key, location in slots:
            try:
                value = json.loads(owner[key]["payload_json"])
            except (KeyError, TypeError, ValueError) as error:
                diagnostics.append({"field_path": location, "constraint": str(error)})
                continue
            owner[key] = value
            defects = collect_native_world_schema_diagnostics(
                world_transition_schema(
                    agency=True
                ),
                value,
                path=location,
            )
            diagnostics.extend(defects)
            if not defects:
                try:
                    WorldTransition.from_mapping(value)
                except (KernelError, TypeError, ValueError) as error:
                    diagnostics.append(
                        {"field_path": location, "constraint": str(error)}
                    )
    if diagnostics:
        raise KernelError(
            "WORLD_PROVIDER_TRANSITION_INVALID",
            json.dumps({"diagnostics": diagnostics}, ensure_ascii=False),
        )
    return result


def agency_transition_paths(generated):
    result = {}
    for index, candidate in enumerate(generated["candidates"]):
        result[f"$.candidates[{index}].transition"] = candidate["transition"]
        for path_index, path in enumerate(candidate["preparation_paths"]):
            for step_index, step in enumerate(path["steps"]):
                result[
                    f"$.candidates[{index}].preparation_paths[{path_index}].steps[{step_index}].transition"
                ] = step["transition"]
    return result
