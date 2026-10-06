from __future__ import annotations
import json
import re
from typing import Any, Mapping
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state.contracts import (
    NarrativeObligationType,
    atomize_character_knowledge_changes,
    normalize_character_belief_changes,
    normalize_relationship_state_changes,
)

_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
_QUALITY_STAGES = {
    "quality_structural",
    "quality_commercial",
    "quality_source_originality",
    "quality_longform",
    "quality_platform",
}
_CANON_FIELDS = (
    "world_state_changes",
    "faction_state_changes",
    "location_state_changes",
    "consequence_changes",
    "conflict_state_changes",

    "canon_facts",
    "character_state_changes",
    "relationship_changes",
    "timeline_events",
    "foreshadow_changes",
    "promise_changes",
    "obligation_changes",
    "reward_changes",
    "world_rule_usages",
    "power_state_changes",
    "plot_thread_changes",
    "resource_state_changes",
    "narrative_pattern_fingerprints",
    "theme_movements",
    "antagonist_pressure_changes",
    "character_knowledge_changes",
    "character_belief_changes",
    "character_arc_changes",
    "arc_state_changes",
    "disclosure_events",
)
_CANON_SEMANTIC_IDENTITIES: dict[str, tuple[tuple[str, ...], ...]] = {
    "world_state_changes": (("world_state_id",),),
    "faction_state_changes": (("faction_id",),),
    "location_state_changes": (("location_id",),),
    "consequence_changes": (("consequence_id",),),
    "conflict_state_changes": (("conflict_id",),),

    "character_state_changes": (("character_id",),),
    "relationship_changes": (("source_id", "target_id"),),
    "timeline_events": (("event_id",),),
    "foreshadow_changes": (("thread_id",),),
    "promise_changes": (("promise_id",),),
    "obligation_changes": (("obligation_id",),),
    "reward_changes": (("reward_id",),),
    "world_rule_usages": (("rule_id",),),
    "power_state_changes": (("character_id",),),
    "plot_thread_changes": (("thread_id",),),
    "resource_state_changes": (("entity_id", "resource_id"),),
    "narrative_pattern_fingerprints": (("fingerprint_id",),),
    "theme_movements": (("entity_id",),),
    "antagonist_pressure_changes": (("antagonist_id",),),
    "character_knowledge_changes": (
        ("character_id", "fact_id"),
        ("character_id", "proposition_id"),
    ),
    "character_belief_changes": (
        ("character_id", "proposition_id"),
        ("character_id", "fact_id"),
    ),
    "character_arc_changes": (("character_id", "arc_id"),),
    "arc_state_changes": (("arc_id",),),
    "disclosure_events": (("disclosure_id",),),
}
_CANON_SCHEMA_REQUIRED_IDENTITIES: dict[str, tuple[str, ...]] = {
    "world_state_changes": ("world_state_id",),
    "faction_state_changes": ("faction_id",),
    "location_state_changes": ("location_id",),
    "consequence_changes": ("consequence_id",),
    "conflict_state_changes": ("conflict_id",),

    "character_state_changes": ("character_id",),
    "relationship_changes": ("source_id", "target_id"),
    "timeline_events": ("event_id",),
    "foreshadow_changes": ("thread_id",),
    "promise_changes": ("promise_id",),
    "obligation_changes": ("obligation_id",),
    "reward_changes": ("reward_id",),
    "world_rule_usages": ("rule_id",),
    "power_state_changes": ("character_id",),
    "plot_thread_changes": ("thread_id",),
    "resource_state_changes": ("entity_id", "resource_id"),
    "narrative_pattern_fingerprints": ("fingerprint_id",),
    "theme_movements": ("entity_id",),
    "antagonist_pressure_changes": ("antagonist_id",),
    "character_arc_changes": ("character_id", "arc_id"),
    "arc_state_changes": ("arc_id",),
}


_READER_STATE_FIELDS = (
    "continue_intent",
    "curiosity",
    "satisfaction",
    "confusion",
    "trust",
    "character_attachment",
    "antagonist_pressure",
    "promise_expectation",
    "payoff_satisfaction",
    "drop_risk",
    "repetition_fatigue",
)


def _object_schema(
    properties: dict[str, Any],
    *,
    required: tuple[str, ...] | list[str],
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:

    value = dict(schema)
    expected = value.get("type")
    if not isinstance(expected, str):
        raise ValueError("nullable schema requires one concrete JSON type")
    value["type"] = [expected, "null"]
    return value


def _scene_artifacts_schema() -> dict[str, Any]:
    return {"type": "array", "items": _object_schema({
        "slot_id": {"type": "string", "minLength": 1},
        "text": {"type": "string", "minLength": 1},
        "used_fact_ids": {"type": "array", "items": {"type": "string", "minLength": 1}},
    }, required=("slot_id", "text", "used_fact_ids"))}


def _draft_schema(*, legacy: bool = False) -> dict[str, Any]:
    if legacy:
        return _object_schema(
            {"text": {"type": "string", "minLength": 1}, "scene_artifacts": _scene_artifacts_schema()},
            required=("text", "scene_artifacts"),
        )
    return _object_schema(
        {"scene_artifacts": {**_scene_artifacts_schema(), "minItems": 1}},
        required=("scene_artifacts",),
    )


def _agent_session_schema() -> dict[str, Any]:

    json_envelope = _object_schema(
        {"payload_json": {"type": "string", "minLength": 2}},
        required=("payload_json",),
    )
    tool_call = _object_schema(
        {
            "tool_name": {"type": "string", "minLength": 1},
            "arguments": json_envelope,
            "reason": {"type": "string", "minLength": 1},
        },
        required=("tool_name", "arguments", "reason"),
    )
    return _object_schema(
        {
            "message": {"type": "string", "minLength": 1},
            "action": {"type": "string", "enum": ["TOOL_CALL", "FINAL"]},
            "tool_call": _nullable(tool_call),
            "final_response": _nullable(json_envelope),
        },
        required=("message", "action", "tool_call", "final_response"),
    )


def _review_schema(*, legacy: bool = False) -> dict[str, Any]:
    from novel_forge.modules.review.diagnostics import constrain_diagnosis_schema
    text = {"type": "string", "minLength": 1, "maxLength": 2000}
    location = (
        _object_schema({"start": {"type": "integer", "minimum": 0},
                        "end": {"type": "integer", "minimum": 1}, "quote": text},
                       required=("start", "end", "quote"))
        if legacy else _object_schema({"quote": text}, required=("quote",))
    )
    issue_fields = {
        "code": text, "severity": {"enum": ["blocking", "major", "minor"]},
        "message": text, "category": text,
        "judgment_kind": {"enum": ["SEMANTIC_CONFLICT", "AESTHETIC_SUGGESTION", "UNCERTAIN"]},
        "evidence": location, "violated_constraint": text, "revision_goal": text,
        "preserve": {"type": "array", "minItems": 1, "maxItems": 16, "items": text},
        "acceptance_criteria": {"type": "array", "minItems": 1, "maxItems": 16, "items": text},
    }
    check_fields = {
        "code": text, "status": {"enum": ["SATISFIED", "UNRESOLVED", "UNCERTAIN"]},
        "preservation": {"enum": ["PRESERVED", "REGRESSED", "UNCERTAIN"]},
        "evidence": location, "reason": text,
    }
    knowledge_fields = {
        "knowledge_card_asset_version_id": text,
        "status": {"enum": ["VERIFIED_IN_PROSE", "MISAPPLIED", "NOT_OBSERVED", "NOT_USED", "UNKNOWN"]},
        "evidence": _nullable(location), "reason": text,
        "conditions_checked": {"type": "array", "items": text},
        "exceptions_checked": {"type": "array", "items": text},
        "issue_codes": {"type": "array", "items": text},
    }
    return _object_schema({
        "score": {"type": "number", "minimum": 0, "maximum": 100},
        "issues": {"type": "array", "maxItems": 32, "items": constrain_diagnosis_schema(_object_schema(issue_fields, required=tuple(issue_fields)))},
        "resolution_checks": {"type": "array", "maxItems": 32, "items": _object_schema(check_fields, required=tuple(check_fields))},
        "knowledge_checks": {"type": "array", "items": _object_schema(knowledge_fields, required=tuple(knowledge_fields))},
    }, required=("score", "issues", "resolution_checks", "knowledge_checks"))


def _revision_schema(*, legacy: bool = False, targeted: bool = False, allow_noop: bool = False) -> dict[str, Any]:
    if legacy:
        return _object_schema(
            {
                "text": {
                    "type": "string", "minLength": 1,
                    "description": (
                        "Final reader-facing revised chapter prose only. Do not embed "
                        "JSON, analysis, self-checks, change logs, evidence appendices, "
                        "or other operator metadata in this string."
                    ),
                },
                "scene_artifacts": _scene_artifacts_schema(),
                "resolved_issue_codes": {"type": "array", "minItems": 0,
                                         "items": {"type": "string", "minLength": 1}},
            },
            required=("text", "resolved_issue_codes", "scene_artifacts"),
        )
    if targeted:
        return _object_schema({
            "resolved_issue_codes": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "edits": {"type": "array", "minItems": 0 if allow_noop else 1, "items": _object_schema({
                "quote": {"type": "string", "minLength": 1},
                "replacement": {"type": "string"},
                "issue_codes": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}},
            }, required=("quote", "replacement", "issue_codes"))},
        }, required=("resolved_issue_codes", "edits"))
    return _object_schema(
        {
            "scene_artifacts": {**_scene_artifacts_schema(), "minItems": 1},
            "resolved_issue_codes": {
                "type": "array",
                "minItems": 0,
                "items": {"type": "string", "minLength": 1},
            },
        },
        required=("resolved_issue_codes", "scene_artifacts"),
    )


def _canon_schema(*, causal_batch: bool = False, legacy: bool = False) -> dict[str, Any]:
    evidence_fields = {
        "evidence_quote": {"type": "string", "minLength": 1},
        "claim_kind": {"enum": ["OBJECTIVE_EVENT", "OBJECTIVE_STATE", "KNOWLEDGE_ACQUISITION", "BELIEF", "SUSPICION", "HEARSAY", "DIALOGUE_ASSERTION", "READER_DISCLOSURE"]},
        **({"evidence_start": {"type": "integer", "minimum": 0},
            "evidence_end": {"type": "integer", "minimum": 1}} if legacy else {}),
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "impact_type": {"type": "string", "minLength": 1},
    }
    fact = _object_schema(
        {
            "subject": {"type": "string", "minLength": 1},
            "predicate": {"type": "string", "minLength": 1},
            "object": {"type": "string", "minLength": 1},
            "effective_from_chapter": {"type": "number", "minimum": 1},
            "supersedes_event_id": _nullable({"type": "string"}),
            **evidence_fields,
        },
        required=(
            "subject",
            "predicate",
            "object",
            "effective_from_chapter",
            "supersedes_event_id",
            *evidence_fields,
        ),
    )
    fact["description"] = (
        "Canonical facts only. Emit at most one item for each "
        "subject/predicate/impact_type semantic slot. For multiple objects, combine a "
        "bundled fact or use precise relation-specific predicates; never emit different "
        "objects in the same semantic slot."
    )
    change_properties = {

        "summary": {"type": "string", "minLength": 1},
        "effective_from_chapter": {"type": "number", "minimum": 1},
        "supersedes_event_id": {"type": "string"},
        "event_id": {"type": "string"},
        "reward_id": {"type": "string"},
        "fingerprint_id": {"type": "string"},
        "antagonist_id": {"type": "string"},
        "character_id": {"type": "string"},
        "source_id": {"type": "string"},
        "target_id": {"type": "string"},
        "thread_id": {"type": "string"},
        "promise_id": {"type": "string"},
        "rule_id": {"type": "string"},
        "entity_id": {"type": "string"},
        "resource_id": {"type": "string"},
        "status": {"type": "string"},
        "from_status": {"type": "string"},
        "stance": {"type": "string"},
        "from_stance": {"type": "string"},
        "from_state": {"type": "string"},
        "from_stage": {"type": "string"},
        "life_status": {"type": "string"},
        "action_state": {"type": "string"},
        "canonical_name": {"type": "string"},
        "transition_kind": {"type": "string"},
        "state": {"type": "string"},
        "stage": {"type": "string"},
        "tier": {"type": "number"},
        "from_tier": {"type": "number"},
        "balance_before": {"type": "number"},
        "delta": {"type": "number"},
        "balance_after": {"type": "number"},
        "exception": {"type": "boolean"},
        "resurrection_authorized": {"type": "boolean"},
        "allow_negative_balance": {"type": "boolean"},
        "payoff_evidence": {"type": "string"},
        "cost": {"type": "string"},
        "requires_fact_ids": {
            "type": "array",
            "items": {"type": "string"},
        },
        "acquired_fact_ids": {
            "type": "array",
            "items": {"type": "string"},
        },
        "change_reasons": {
            "type": "array",
            "items": {"type": "string"},
        },
        "fact_id": {"type": "string"},
        "proposition_id": {"type": "string"},
        "disclosure_id": {"type": "string"},
        "arc_id": {"type": "string"},
        "audience": {"type": "string"},
        "disclosure_mode": {"type": "string"},
        "presentation_channel": {"type": "string"},
        "belief_confidence": {"type": "number", "minimum": 0, "maximum": 1},
        **evidence_fields,
    }
    if causal_batch:
        change_properties.update({
            "world_mechanism": _object_schema({"rule_id": {"type": "string"}, "asset_version_id": {"type": "string"}, "content_hash": {"type": "string"}}, required=("rule_id", "asset_version_id", "content_hash")),
            "causal_batch": _object_schema({
                "contract_version": {"type": "string", "enum": ["causal-batch-event.v1"]},
                "local_id": {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9_-]{0,63}$"},
                "depends_on": {"type": "array", "items": {"type": "string", "minLength": 1}, "uniqueItems": True, "maxItems": 128},
            }, required=("contract_version", "local_id", "depends_on")),
            "story_time": _object_schema({
                "timeline_id": {"type": "string", "minLength": 1},
                "start_ordinal": {"type": "integer", "minimum": 0},
                "end_ordinal": {"type": "integer", "minimum": 0},
                "precision": {"type": "string", "enum": ["EXACT", "ORDERED", "RANGE"]},
                "label": {"type": "string"},
            }, required=("timeline_id", "start_ordinal", "end_ordinal", "precision", "label")),
            "world_transition": _object_schema({"payload_json": {"type": "string", "minLength": 2}}, required=("payload_json",)),
        })
    change_required = {"summary", *evidence_fields}
    change = _object_schema(
        {
            key: (schema if key in change_required else _nullable(schema))
            for key, schema in change_properties.items()
        },
        required=tuple(change_properties),
    )
    properties = {
        field: {
            "type": "array",
            # WHY: Each semantic array owns its schema.  Sharing ``change`` here
            # lets a field-specific refinement silently mutate every other
            # Canon change contract.
            "items": (
                fact if field == "canon_facts" else json.loads(json.dumps(change))
            ),

        }
        for field in _CANON_FIELDS
    }
    for field, identity in {
        "world_state_changes": "world_state_id", "faction_state_changes": "faction_id",
        "location_state_changes": "location_id", "consequence_changes": "consequence_id",
        "conflict_state_changes": "conflict_id",
    }.items():
        item_schema = properties[field]["items"]
        item_schema["properties"][identity] = {"type": "string", "minLength": 1}
        item_schema["properties"]["world_transition"] = _object_schema({"payload_json": {"type": "string", "minLength": 2}}, required=("payload_json",))
        item_schema["required"].extend(key for key in (identity, "world_transition") if key not in item_schema["required"])
    properties["arc_evidence"] = {
        "type": "array",
        "items": _object_schema(
            {
                "arc_plan_version_id": {"type": "string", "minLength": 1},
                "observation_status": {
                    "type": "string",
                    "enum": ["OBSERVED", "NOT_OBSERVED", "NOT_MATERIALIZED", "UNKNOWN"],
                },
                "contribution_kind": {"type": "string", "minLength": 1},
                "progress_units": {"type": "integer", "minimum": 0},
                "effect_dimensions": {"type": "array", "items": {"type": "string"}},
                "milestone_ids": {"type": "array", "items": {"type": "string"}},
                "actual_consequences": {"type": "array", "items": {"type": "string"}},
                "obligation_ids": {"type": "array", "items": {"type": "string"}},
                "resolution_evidence": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "For OBSERVED only: final_candidate Unicode code-point-span references "
                        "encoded as chars:<start>-<end>:<summary>; empty otherwise."
                        if legacy else "For OBSERVED only: literal final-candidate prose quotes; empty otherwise."
                    ),
                },
                "completion_criterion_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "phase_to": _nullable({"type": "string"}),
            },
            required=(
                "arc_plan_version_id",
                "observation_status",
                "contribution_kind",
                "progress_units",
                "effect_dimensions",
                "milestone_ids",
                "actual_consequences",
                "obligation_ids",
                "resolution_evidence",
                "completion_criterion_ids",
                "phase_to",
            ),
        ),
    }
    properties["realization_evidence"] = {
        "type": "array",
        "items": _object_schema(
            {
                "planned_event_id": {"type": "string", "minLength": 1},
                "observed_event_id": _nullable({"type": "string", "minLength": 1}),
                "observation_status": {
                    "type": "string",
                    "enum": ["OBSERVED", "NOT_OBSERVED"],
                },
                "accepted_prose_evidence": {
                    "type": "array",
                    "items": _object_schema(
                        {
                            **({"start": {"type": "integer", "minimum": 0},
                                "end": {"type": "integer", "minimum": 1}} if legacy else
                               {"quote": {"type": "string", "minLength": 1}}),
                            "summary": {"type": "string", "minLength": 1},
                        },
                        required=("start", "end", "summary") if legacy else ("quote", "summary"),
                    ),
                },
                "observed_consequence": _nullable({"type": "string", "minLength": 1}),
                "observed_action": _nullable({"type": "string", "minLength": 1}),
                "observed_decision": _nullable({"type": "string", "minLength": 1}),
                "observed_cause_event_ids": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                },
                "observed_disclosures": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                },
                "observed_state_deltas": {
                    "type": "array",
                    "items": _object_schema(
                        {
                            "state_kind": {"type": "string", "minLength": 1},
                            "entity_id": {"type": "string", "minLength": 1},
                            "from_state": {"type": "string", "minLength": 1},
                            "to_state": {"type": "string", "minLength": 1},
                        },
                        required=(
                            "state_kind",
                            "entity_id",
                            "from_state",
                            "to_state",
                        ),
                    ),
                },
                "observed_state_event_ids": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                },
            },
            required=(
                "planned_event_id",
                "observed_event_id",
                "observation_status",
                "accepted_prose_evidence",
                "observed_consequence",
                "observed_action",
                "observed_decision",
                "observed_cause_event_ids",
                "observed_disclosures",
                "observed_state_deltas",
                "observed_state_event_ids",
            ),
        ),
    }
    properties["obligation_changes"] = {
        "type": "array",
        "items": _object_schema(
            {
                "obligation_id": {"type": "string", "minLength": 1},
                "obligation_type": {
                    "type": "string",
                    "enum": [kind.value for kind in NarrativeObligationType],
                },
                "causal_requirement": _nullable(_object_schema({"payload_json": {"type": "string", "minLength": 2}}, required=("payload_json",))),
                "causal_plan_asset_version_id": _nullable({"type": "string", "minLength": 1}),
                "from_status": _nullable({"type": "string"}),
                "status": {
                    "type": "string",
                    "enum": [
                        "PROPOSED",
                        "OPEN",
                        "DEVELOPING",
                        "DUE",
                        "FULFILLED",
                        "CANCELLED",
                    ],
                },
                "priority": {
                    "type": "string",
                    "enum": ["LOW", "MEDIUM", "HIGH", "CRITICAL"],
                },
                "target_window": _object_schema(
                    {
                        "status": {
                            "type": "string",
                            "enum": ["SCHEDULED", "UNSCHEDULED"],
                        },
                        "from_chapter": {"type": "integer", "minimum": 0},
                        "to_chapter": {"type": "integer", "minimum": 0},
                    },
                    required=("status", "from_chapter", "to_chapter"),
                ),
                "payoff_evidence": _nullable(
                    _object_schema(
                        {
                            "asset_version_id": {"type": "string", "minLength": 1,
                                "description": "Use $FINAL_CANDIDATE for prose payoff; CAUSAL_DEBT uses its exact accepted prerequisite draft." if legacy else "For CAUSAL_DEBT only: select the accepted prerequisite draft."},
                            "event_id": {"type": "string", "minLength": 1,
                                "description": "Use $CURRENT_CLAIM for prose payoff; CAUSAL_DEBT uses its exact accepted prerequisite event." if legacy else "For CAUSAL_DEBT only: select the accepted prerequisite event."},
                        },
                        required=("asset_version_id", "event_id"),
                    )
                ),
                "linked_arc_ids": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                },
                "summary": {"type": "string", "minLength": 1},
                **evidence_fields,
            },
            required=(
                "obligation_id",
                "obligation_type",
                "causal_requirement",
                "causal_plan_asset_version_id",
                "from_status",
                "status",
                "priority",
                "target_window",
                "payoff_evidence",
                "linked_arc_ids",
                "summary",
                *evidence_fields,
            ),
        ),
    }
    for field in ("arc_evidence", "realization_evidence"):
        properties[field]["items"]["properties"].update({
            "claim_kind": _nullable({"type": "string", "enum": ["NARRATIVE_OBSERVATION", None]}),
            "evidence_quote": _nullable({"type": "string", "minLength": 1}),
            **({"evidence_start": _nullable({"type": "integer", "minimum": 0}),
                "evidence_end": _nullable({"type": "integer", "minimum": 1})} if legacy else {}),
        })
        properties[field]["items"]["required"].extend(("claim_kind", "evidence_start", "evidence_end", "evidence_quote") if legacy else ("claim_kind", "evidence_quote"))
    properties.update({"extraction_status": {"enum": ["EXTRACTED", "NO_CHANGE"]}, "no_change_reason": {"type": "string"}})
    schema = _object_schema(
        properties,
        required=(*_CANON_FIELDS, "arc_evidence", "realization_evidence", "extraction_status", "no_change_reason"),
    )
    for field, identities in _CANON_SCHEMA_REQUIRED_IDENTITIES.items():
        change_schema = schema["properties"][field]["items"]
        for identity in identities:
            change_schema["properties"][identity] = {
                "type": "string",
                "minLength": 1,
            }
    knowledge_changes = schema["properties"]["character_knowledge_changes"]
    knowledge_changes["description"] = (
        "Atomic Character Knowledge events. Emit one item per character and fact or "
        "proposition identity; set status to UNKNOWN, SUSPECTED, KNOWN, or FORGOTTEN; "
        "leave the generic state field null; do not bundle multiple acquired_fact_ids."
    )
    knowledge_change = knowledge_changes["items"]
    knowledge_change["properties"]["character_id"] = {
        "type": "string",
        "minLength": 1,
    }
    knowledge_change["properties"]["status"] = {
        "type": "string",
        "enum": ["UNKNOWN", "SUSPECTED", "KNOWN", "FORGOTTEN"],
    }
    knowledge_change["properties"]["state"] = {
        "type": ["string", "null"],
        "enum": [None],
    }
    belief_changes = schema["properties"]["character_belief_changes"]
    belief_changes["description"] = (
        "Typed Character Belief events. Emit one item per character and fact or "
        "proposition identity; set stance to BELIEVES, DOUBTS, DISBELIEVES, or "
        "UNCERTAIN and belief_confidence from zero to one. Use from_stance only "
        "for an accepted compare-and-set baseline; leave generic state/status null."
    )
    belief_change = belief_changes["items"]
    belief_change["properties"]["character_id"] = {
        "type": "string",
        "minLength": 1,
    }
    belief_change["properties"]["stance"] = {
        "type": "string",
        "enum": ["BELIEVES", "DOUBTS", "DISBELIEVES", "UNCERTAIN"],
    }
    belief_change["properties"]["from_stance"] = {
        "type": ["string", "null"],
        "enum": ["BELIEVES", "DOUBTS", "DISBELIEVES", "UNCERTAIN", None],
    }
    belief_change["properties"]["belief_confidence"] = {
        "type": "number",
        "minimum": 0,
        "maximum": 1,
    }
    for alias in ("state", "status", "from_state", "from_status"):
        belief_change["properties"][alias] = {
            "type": ["string", "null"],
            "enum": [None],
        }
    relationship_changes = schema["properties"]["relationship_changes"]
    relationship_changes["description"] = (
        "Typed directed relationship transitions. Copy the exact source_id and "
        "target_id endpoints; entity_id is descriptive only and cannot replace "
        "either graph endpoint. Leave the generic character_id field null."
    )
    relationship_change = relationship_changes["items"]
    for endpoint in ("source_id", "target_id"):
        relationship_change["properties"][endpoint] = {
            "type": "string",
            "minLength": 1,
        }
    relationship_change["properties"]["character_id"] = {
        "type": ["string", "null"],
        "enum": [None],
    }
    disclosure_changes = schema["properties"]["disclosure_events"]
    disclosure_changes["description"] = (
        "Typed presentation events. Copy a stable disclosure_id, one fact or "
        "proposition identity, the exact audience, disclosure mode, and presentation "
        "channel. Disclosure is presentation evidence, not Reader Knowledge input."
    )
    disclosure_change = disclosure_changes["items"]
    disclosure_change["properties"]["disclosure_id"] = {
        "type": "string",
        "minLength": 1,
    }
    disclosure_change["properties"]["audience"] = {
        "type": "string",
        "minLength": 1,
    }
    disclosure_change["properties"]["disclosure_mode"] = {
        "type": "string",
        "enum": ["HINT", "PARTIAL", "MISDIRECT", "CONFIRM", "WITHHOLD"],
    }
    disclosure_change["properties"]["presentation_channel"] = {
        "type": "string",
        "minLength": 1,
    }
    return schema


def _quality_schema(*, legacy: bool = False) -> dict[str, Any]:
    location = _object_schema(
        ({
            "start": {"type": "number", "minimum": 0},
            "end": {"type": "number", "minimum": 1},
            "claim": {"type": "string", "minLength": 1},
        } if legacy else {
            "quote": {"type": "string", "minLength": 1},
            "claim": {"type": "string", "minLength": 1},
        }),
        required=("start", "end", "claim") if legacy else ("quote", "claim"),
    )
    dimension = _object_schema(
        {
            "dimension": {"type": "string", "minLength": 1},
            "gate_status": {
                "type": "string",
                "enum": [
                    "PASSED",
                    "PASSED_WITH_WARNINGS",
                    "FAILED",
                    "INSUFFICIENT_EVIDENCE",
                    "REQUIRES_HUMAN_REVIEW",
                ],
            },
            "score": {"type": "number", "minimum": 0, "maximum": 100},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "evidence_locations": {
                "type": "array",
                "minItems": 1 if legacy else 0,
                "items": location,
            },
            "issue_codes": {
                "type": "array",
                "items": {"type": "string"},
            },
            "revision_strategies": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        required=(
            "dimension",
            "gate_status",
            "score",
            "confidence",
            "evidence_locations",
            "issue_codes",
            "revision_strategies",
        ),
    )
    return _object_schema(
        {"dimensions": {"type": "array", "items": dimension, "minItems": 1}},
        required=("dimensions",),
    )


def _reader_outcome_schema() -> dict[str, Any]:
    reader_state = _object_schema(
        {
            field: {"type": "number", "minimum": 0, "maximum": 1}
            for field in _READER_STATE_FIELDS
        },
        required=_READER_STATE_FIELDS,
    )
    return _object_schema(
        {
            "reader_state": reader_state,
            "evidence": {
                "type": "array",
                "minItems": 1,
                "items": _object_schema(
                    {
                        "asset_version_id": {"type": "string", "minLength": 1},
                        "location": {"type": "string", "minLength": 1},
                        "claim": {"type": "string", "minLength": 1},
                    },
                    required=("asset_version_id", "location", "claim"),
                ),
            },
        },
        required=("reader_state", "evidence"),
    )


def _retrieval_embedding_schema() -> dict[str, Any]:
    return _object_schema(
        {
            "vectors": {
                "type": "array",
                "minItems": 1,
                "maxItems": 32,
                "items": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 8192,
                    "items": {"type": "number"},
                },
            },
            "embedding_model": {"type": "string", "minLength": 1},
            "embedding_dimensions": {"type": "integer", "minimum": 1},
        },
        required=("vectors", "embedding_model", "embedding_dimensions"),
    )


def _retrieval_query_expansion_schema() -> dict[str, Any]:
    string_ids = {
        "type": "array",
        "maxItems": 32,
        "uniqueItems": True,
        "items": {"type": "string", "minLength": 1, "maxLength": 200},
    }
    selectors = _object_schema(
        {
            key: dict(string_ids)
            for key in (
                "entity_ids",
                "character_ids",
                "relationship_ids",
                "arc_plan_version_ids",
                "obligation_ids",
            )
        },
        required=(),
    )
    temporal_range = _object_schema(
        {
            "from_chapter": {"type": "integer", "minimum": 0},
            "to_chapter": {"type": "integer", "minimum": 0},
        },
        required=("from_chapter", "to_chapter"),
    )
    query = _object_schema(
        {
            "query_id": {"type": "string", "minLength": 1, "maxLength": 160},
            "text": {"type": "string", "minLength": 1, "maxLength": 512},
            "reason": {"type": "string", "minLength": 1, "maxLength": 512},
            "targets": {**string_ids, "minItems": 1},
            "selectors": selectors,
            "temporal_range": temporal_range,
        },
        required=(
            "query_id",
            "text",
            "reason",
            "targets",
            "selectors",
            "temporal_range",
        ),
    )
    return _object_schema(
        {
            "contract_version": {
                "type": "string",
                "const": "retrieval-expansion-plan-v1",
            },
            "queries": {
                "type": "array",
                "minItems": 1,
                "maxItems": 4,
                "items": query,
            },
        },
        required=("contract_version", "queries"),
    )


def chapter_provider_output_schema(
    stage: str,
    *,
    causal_batch: bool = False,
    legacy_contract: bool = False,
    targeted_revision: bool = False,
    work_requirements: bool = False,
    allow_noop_revision: bool = False,
) -> dict[str, Any]:

    if stage == "memo":
        from .creative_memo import creative_memo_schema
        schema = creative_memo_schema(legacy=legacy_contract)
    elif stage == "draft":
        schema = _draft_schema(legacy=legacy_contract)
    elif stage == "agent_session":
        schema = _agent_session_schema()
    elif stage in {"review", "rereview"}:
        schema = _review_schema(legacy=legacy_contract)
    elif stage == "revision":
        schema = _revision_schema(legacy=legacy_contract, targeted=targeted_revision, allow_noop=allow_noop_revision)
    elif stage == "canon_extraction":
        schema = _canon_schema(causal_batch=causal_batch, legacy=legacy_contract)
    elif stage == "canon_support":
        schema = _object_schema({
            "coverage": {"enum": ["COMPLETE", "INCOMPLETE"]},
            "no_change_supported": {"type": "boolean"},
            "claims": {"type": "array", "maxItems": 256, "items": _object_schema({
                "claim_id": {"type": "string", "minLength": 1},
                "assessment": {"enum": ["SUPPORTED", "UNSUPPORTED", "UNCERTAIN"]},
                "observed_kind": {"type": "string", "minLength": 1},
                "reason": {"type": "string", "minLength": 1},
            }, required=("claim_id", "assessment", "observed_kind", "reason"))},
        }, required=("coverage", "no_change_supported", "claims"))
    elif stage in _QUALITY_STAGES:
        schema = _quality_schema(legacy=legacy_contract)
    elif stage in {"screenplay_generate", "screenplay_review", "screenplay_revision"}:
        from novel_forge.modules.book_followup_authority.screenplay import screenplay_output_schema
        schema = screenplay_output_schema(stage)
    elif stage == "longform_prose_review":
        from novel_forge.modules.book_followup_authority.prose_review import prose_review_output_schema
        schema = prose_review_output_schema()
    elif stage == "reader_outcome":
        schema = _reader_outcome_schema()
    elif stage == "retrieval":
        schema = _retrieval_embedding_schema()
    elif stage == "retrieval_query_expansion":
        schema = _retrieval_query_expansion_schema()
    elif stage == "context_compress":
        schema = _object_schema({
            "selected_unit_ids": {"type": "array", "maxItems": 256, "uniqueItems": True,
                                  "items": {"type": "string", "minLength": 1, "maxLength": 200}},
        }, required=("selected_unit_ids",))
    elif stage == "context_fidelity":
        identity_array = {"type": "array", "maxItems": 256, "uniqueItems": True,
                          "items": {"type": "string", "minLength": 1, "maxLength": 200}}
        schema = _object_schema({
            "supported": {"type": "boolean"},
            "coverage_complete": {"type": "boolean"},
            "missing_unit_ids": identity_array,
            "distorted_unit_ids": identity_array,
            "reason": {"type": "string", "minLength": 1, "maxLength": 4000},
        }, required=("supported", "coverage_complete", "missing_unit_ids", "distorted_unit_ids", "reason"))
    else:
        raise KernelError(
            "CHAPTER_PROVIDER_OUTPUT_SCHEMA_UNSUPPORTED",
            f"Chapter Provider output schema is not defined for stage {stage}",
        )
    if work_requirements and stage in _QUALITY_STAGES:
        dimension = schema["properties"]["dimensions"]["items"]["properties"]
        dimension["gate_status"]["enum"].append("NOT_APPLICABLE")
        dimension["score"]["type"] = ["number", "null"]
    return {"$schema": _SCHEMA_DIALECT, **schema}


def chapter_provider_output_schema_ref(
    stage: str,
    *,
    causal_batch: bool = False,
    legacy_contract: bool = False,
    targeted_revision: bool = False,
    work_requirements: bool = False,
    allow_noop_revision: bool = False,
) -> str:
    chapter_provider_output_schema(stage, causal_batch=causal_batch, legacy_contract=legacy_contract, targeted_revision=targeted_revision)
    version = (
        (
            ("v19" if causal_batch else "v18")
            if legacy_contract
            else (
                ("v23" if causal_batch else "v22")
                if work_requirements
                else ("v21" if causal_batch else "v20")
            )
        )
        if stage == "canon_extraction"
        else ("v4" if legacy_contract else "v5")
        if stage in {"review", "rereview"}
        else (
            "v2"
            if legacy_contract
            else "v5"
            if targeted_revision and stage == "revision" and allow_noop_revision
            else "v4"
            if targeted_revision and stage == "revision"
            else "v3"
        )
        if stage in {"draft", "revision"}
        else ("v2" if legacy_contract else "v4" if work_requirements else "v3")
        if stage in _QUALITY_STAGES
        else "v2"
        if stage in {"screenplay_generate", "screenplay_review", "screenplay_revision"}
        else "v1"
    )
    if stage == "memo" and not legacy_contract:
        version = "v2"
    return f"schema:chapter-provider-output:{stage}:{version}"


def is_targeted_revision_schema_ref(schema_ref: str) -> bool:
    return re.fullmatch(
        r"schema:chapter-provider-output:revision:(?:v[45]|cross-chapter-v[45])"
        r"(?::quality-targeted-v2)?(?::narrative-craft-v[23])?",
        schema_ref,
    ) is not None


def is_work_review_schema_ref(schema_ref: str) -> bool:
    return re.fullmatch(
        r"schema:chapter-provider-output:(?:review|rereview):(?:v6|cross-chapter-v6)"
        r"(?::quality-resolution-v1)?(?::narrative-craft-v[23])?",
        schema_ref,
    ) is not None


def allows_empty_revision_schema_ref(schema_ref: str) -> bool:
    return re.fullmatch(
        r"schema:chapter-provider-output:revision:(?:v5|cross-chapter-v5)"
        r"(?::narrative-craft-v[23])?",
        schema_ref,
    ) is not None


def canon_provider_array_fields() -> tuple[str, ...]:
    return (*_CANON_FIELDS, "arc_evidence", "realization_evidence")


def validate_chapter_provider_output_schema(
    stage: str,
    value: object,
) -> dict[str, Any]:

    return validate_chapter_provider_output_against_schema(
        stage,
        chapter_provider_output_schema(stage),
        value,
    )


def validate_chapter_provider_output_against_schema(
    stage: str,
    schema: Mapping[str, Any],
    value: object,
) -> dict[str, Any]:

    try:
        _validate(dict(schema), value, path="$", enforce_dialect=True)
    except ValueError as exc:
        raise KernelError(
            "CHAPTER_PROVIDER_OUTPUT_SCHEMA_INVALID",
            f"stage {stage}: {exc}",
        ) from exc
    # COMPATIBILITY: JSON round-tripping freezes a JSON-compatible copy for downstream semantics.
    return json.loads(json.dumps(value, ensure_ascii=False))


def validate_native_world_schema_fragment(
    stage: str, schema: Mapping[str, Any], value: object, *, output_schema_ref: str
) -> dict[str, Any]:
    from novel_forge.modules.command_kernel.routing_bootstrap import WORLD_SAMPLE_TASKS
    if (stage not in WORLD_SAMPLE_TASKS or output_schema_ref not in {f"schema:{stage}:v1", f"schema:{stage}:v2"}
            or "$schema" in schema or schema.get("type") != "object"
            or schema.get("additionalProperties") is not False or not schema.get("required")):
        raise KernelError("WORLD_PROVIDER_OUTPUT_CONTRACT_UNSUPPORTED", output_schema_ref)
    try:
        _validate(dict(schema), value, path="$")
    except ValueError as exc:
        raise KernelError("WORLD_PROVIDER_OUTPUT_SCHEMA_INVALID", f"{stage}: {exc}") from exc
    return json.loads(json.dumps(value, ensure_ascii=False))



def collect_native_world_schema_diagnostics(schema, value, *, path="$"):
    diagnostics = []
    def visit(shape, item, location):
        children = []
        local = dict(shape)
        if shape.get("type") == "object" and isinstance(item, dict):
            properties = shape.get("properties", {})
            children = [(child, item[key], f"{location}.{key}") for key, child in properties.items() if key in item]
            for key in shape.get("required", []):
                if key not in item:
                    diagnostics.append({"field_path": f"{location}.{key}", "constraint": "required field missing", "actual_type": "missing"})
            if shape.get("additionalProperties") is False:
                for key in sorted(set(item) - set(properties)):
                    diagnostics.append({"field_path": f"{location}.{key}", "constraint": "undeclared field", "actual_type": type(item[key]).__name__})
            local["required"] = []
            local["properties"] = {}
            local["additionalProperties"] = True
        elif shape.get("type") == "array" and isinstance(item, list):
            children = [(shape["items"], child, f"{location}[{index}]") for index, child in enumerate(item)] if "items" in shape else []
            local.pop("items", None)
        try:
            _validate(local, item, path=location)
        except ValueError as error:
            diagnostics.append({"field_path": location, "constraint": str(error), "actual_type": type(item).__name__})
        for child, raw, child_path in children:
            visit(child, raw, child_path)
    visit(schema, value, path)
    return diagnostics


def validate_chapter_provider_output_semantics(
    stage: str,
    value: Mapping[str, Any],
    *,
    host_bind_known_metadata: bool = False,
    output_schema_ref: str = "",
) -> dict[str, Any]:

    normalized = json.loads(json.dumps(value, ensure_ascii=False))
    work_requirements = output_schema_ref.endswith((":v22", ":v23"))
    if stage == "canon_extraction":
        if output_schema_ref:
            if output_schema_ref not in {
                "schema:chapter-provider-output:canon_extraction:v18",
                "schema:chapter-provider-output:canon_extraction:v19",
                "schema:chapter-provider-output:canon_extraction:v20",
                "schema:chapter-provider-output:canon_extraction:v21",
                "schema:chapter-provider-output:canon_extraction:v22",
                "schema:chapter-provider-output:canon_extraction:v23",
            }:
                raise KernelError(
                    "CHAPTER_PROVIDER_OUTPUT_CONTRACT_UNSUPPORTED",
                    "unknown frozen Canon output contract",
                )
            host_bind_known_metadata = output_schema_ref.endswith(
                (":v20", ":v21", ":v22", ":v23")
            )
        original_realization = {item.get("planned_event_id"): item for item in normalized.get("realization_evidence", [])}
        normalized = _without_null_object_properties(normalized)
        if work_requirements:
            for item in normalized.get("realization_evidence", []):
                original = original_realization[item.get("planned_event_id")]
                if "observed_decision" in original and original["observed_decision"] is None:
                    item["observed_decision"] = None
        try:
            normalized["character_knowledge_changes"] = (
                atomize_character_knowledge_changes(
                    normalized.get("character_knowledge_changes", [])
                )
            )
            normalized["character_belief_changes"] = normalize_character_belief_changes(
                normalized.get("character_belief_changes", [])
            )
            normalized["relationship_changes"] = normalize_relationship_state_changes(
                normalized.get("relationship_changes", [])
            )
        except KernelError as exc:
            raise KernelError(
                "CHAPTER_PROVIDER_OUTPUT_SEMANTIC_INVALID",
                str(exc),
            ) from exc
        for disclosure in normalized.get("disclosure_events", []):
            if not str(
                disclosure.get("fact_id") or disclosure.get("proposition_id") or ""
            ).strip():
                raise KernelError(
                    "CHAPTER_PROVIDER_OUTPUT_SEMANTIC_INVALID",
                    "Disclosure requires one fact_id or proposition_id",
                )
        for obligation in normalized.get("obligation_changes", []):
            if obligation.get("obligation_type") == "CAUSAL_DEBT":
                from novel_forge.modules.narrative_state.causal_obligations import (
                    causal_obligation_requirement,
                )

                causal_obligation_requirement(obligation)
            from novel_forge.modules.canon_graph.grounding import (
                validate_payoff_reference,
            )

            if (
                host_bind_known_metadata
                and obligation.get("status") == "FULFILLED"
                and obligation.get("obligation_type") != "CAUSAL_DEBT"
                and obligation.get("payoff_evidence") is None
            ):
                continue
            try:
                validate_payoff_reference(obligation)
            except KernelError as error:
                raise KernelError(
                    "CHAPTER_PROVIDER_OUTPUT_SEMANTIC_INVALID",
                    str(error),
                ) from error
        seen_arc_ids: set[str] = set()
        for evidence in normalized.get("arc_evidence", []):
            arc_id = str(evidence.get("arc_plan_version_id") or "")
            if arc_id in seen_arc_ids:
                raise KernelError(
                    "CHAPTER_PROVIDER_OUTPUT_SEMANTIC_INVALID",
                    "Arc evidence must contain one observation per frozen ArcPlan",
                )
            seen_arc_ids.add(arc_id)
            status = str(evidence.get("observation_status") or "")
            if status == "OBSERVED" and not evidence.get("resolution_evidence"):
                raise KernelError(
                    "CHAPTER_PROVIDER_OUTPUT_SEMANTIC_INVALID",
                    "observed Arc evidence requires accepted-prose location evidence",
                )
            if status != "OBSERVED" and int(evidence.get("progress_units") or 0):
                raise KernelError(
                    "CHAPTER_PROVIDER_OUTPUT_SEMANTIC_INVALID",
                    "unobserved Arc evidence cannot advance actual progress",
                )
        seen_realization_ids: set[str] = set()
        for evidence in normalized.get("realization_evidence", []):
            planned_event_id = str(evidence.get("planned_event_id") or "")
            if not planned_event_id or planned_event_id in seen_realization_ids:
                raise KernelError(
                    "CHAPTER_PROVIDER_OUTPUT_SEMANTIC_INVALID",
                    "realization evidence requires unique planned event identities",
                )
            seen_realization_ids.add(planned_event_id)
            observed = evidence.get("observation_status") == "OBSERVED"
            if observed != bool(
                evidence.get("observed_event_id")
                and evidence.get("accepted_prose_evidence")
                and evidence.get("observed_consequence")
                and evidence.get("observed_action")
                and (
                    work_requirements
                    or (
                        evidence.get("observed_decision")
                        and evidence.get("observed_state_deltas")
                    )
                )
            ):
                raise KernelError(
                    "CHAPTER_PROVIDER_OUTPUT_SEMANTIC_INVALID",
                    "observed realization evidence requires identity, prose location and consequence",
                )
        for field in _CANON_FIELDS:
            if field == "canon_facts":
                continue
            for item in normalized.get(field, []):
                if not _has_canon_change_identity(field, item):
                    expected = " or ".join(
                        "+".join(group)
                        for group in _CANON_SEMANTIC_IDENTITIES.get(field, ())
                    )
                    raise KernelError(
                        "CHAPTER_PROVIDER_OUTPUT_SEMANTIC_INVALID",
                        f"{field} requires canonical domain identity {expected}",
                    )
        for change in normalized.get("resource_state_changes", []):
            before = change.get("balance_before")
            delta = change.get("delta")
            after = change.get("balance_after")
            if delta is None:
                if after is None:
                    raise KernelError(
                        "CHAPTER_PROVIDER_OUTPUT_SEMANTIC_INVALID",
                        "initial Resource State requires balance_after",
                    )
                change["balance"] = after
            elif (
                before is None
                or after is None
                or float(before) + float(delta) != float(after)
            ):
                raise KernelError(
                    "CHAPTER_PROVIDER_OUTPUT_SEMANTIC_INVALID",
                    "Resource transition requires balance_before + delta = balance_after",
                )
        fingerprints: dict[tuple[object, ...], str] = {}
        for field in _CANON_FIELDS:
            for item in normalized.get(field, []):
                if field == "canon_facts":
                    slot: tuple[object, ...] = (
                        field,
                        str(item.get("subject") or ""),
                        str(item.get("impact_type") or field),
                        str(item.get("predicate") or ""),
                    )
                else:
                    slot = _canon_change_semantic_slot(field, item)
                    if item.get("causal_batch"):
                        slot += (item["causal_batch"]["local_id"],)
                fingerprint = json.dumps(
                    item, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
                previous = fingerprints.get(slot)
                if previous is not None and previous != fingerprint:
                    raise KernelError(
                        "CHAPTER_PROVIDER_OUTPUT_SEMANTIC_INVALID",
                        "Canon extraction contains contradictory changes for one semantic slot",
                    )
                fingerprints[slot] = fingerprint
        return normalized
    if stage != "revision":
        return normalized

    from .realization_composition import prose_from_output

    targeted = is_targeted_revision_schema_ref(output_schema_ref)
    if output_schema_ref.startswith("schema:chapter-provider-output:revision:") and (
        "v4" in output_schema_ref and not targeted
    ):
        raise KernelError("CHAPTER_PROVIDER_OUTPUT_CONTRACT_UNSUPPORTED", "unknown frozen targeted Revision contract")
    if targeted:
        replacements = [str(item["replacement"]) for item in normalized["edits"]]
        text = "\n".join(replacements).strip()
    else:
        text = prose_from_output(normalized).strip()
    if not text and not targeted:
        raise KernelError(
            "CHAPTER_PROVIDER_OUTPUT_SEMANTIC_INVALID",
            "Revision output has no reader-facing prose",
        )
    try:
        embedded = json.loads(text)
    except json.JSONDecodeError:
        embedded = None
    if isinstance(embedded, Mapping):
        raise KernelError(
            "CHAPTER_PROVIDER_OUTPUT_SEMANTIC_INVALID",
            "Revision text contains a serialized result object instead of chapter prose",
        )
    forbidden_markers = (
        "## 自检",
        "## 修订证据引用",
        "## self-check",
        "## revision evidence",
    )
    folded = text.casefold()
    marker = next(
        (item for item in forbidden_markers if item.casefold() in folded),
        None,
    )
    if marker is not None:
        raise KernelError(
            "CHAPTER_PROVIDER_OUTPUT_SEMANTIC_INVALID",
            f"Revision text contains operator-only metadata marker {marker}",
        )
    issue_codes = normalized.get("resolved_issue_codes")
    if (
        not isinstance(issue_codes, list)
        or len(issue_codes) != len(set(issue_codes))
    ):
        raise KernelError(
            "CHAPTER_PROVIDER_OUTPUT_SEMANTIC_INVALID",
            "Revision output requires unique resolved issue codes",
        )
    return normalized


def _canon_change_semantic_slot(
    field: str, item: Mapping[str, Any]
) -> tuple[object, ...]:
    """INVARIANT: Return a domain identity, never an evidence-location heuristic.

    One passage may legitimately produce multiple audience-specific Disclosure
    events or multiple typed state changes. Provider semantics are validated
    before this function, so reaching the fallback is a programming error.
    """
    for fields in _CANON_SEMANTIC_IDENTITIES.get(field, ()):
        values = tuple(str(item.get(key) or "") for key in fields)
        if all(values):
            return (field, *fields, *values)
    raise KernelError(
        "CHAPTER_PROVIDER_OUTPUT_SEMANTIC_INVALID",
        f"{field} has no canonical domain identity",
    )


def _has_canon_change_identity(field: str, item: Mapping[str, Any]) -> bool:
    return any(
        all(str(item.get(key) or "").strip() for key in fields)
        for fields in _CANON_SEMANTIC_IDENTITIES.get(field, ())
    )


def _validate(
    schema: dict[str, Any],
    value: object,
    *,
    path: str,
    enforce_dialect: bool = False,
) -> None:
    if enforce_dialect and schema.get("$schema") != _SCHEMA_DIALECT:
        raise ValueError("unsupported JSON Schema dialect")
    if "anyOf" in schema:
        for choice in schema["anyOf"]:
            try:
                _validate(choice, value, path=path)
                break
            except ValueError:
                continue
        else:
            raise ValueError(f"{path} violates every allowed structural combination")
    expected = schema.get("type")
    if isinstance(expected, list):
        allowed = tuple(str(item) for item in expected)
        if value is None and "null" in allowed:
            return
        concrete = tuple(item for item in allowed if item != "null")
        if len(concrete) != 1:
            raise ValueError(f"{path} uses unsupported schema type union {expected}")
        _validate({**schema, "type": concrete[0]}, value, path=path)
        return
    if expected == "object":
        if not isinstance(value, dict):
            raise ValueError(f"{path} must be an object")
        minimum = schema.get("minProperties")
        if isinstance(minimum, int) and len(value) < minimum:
            raise ValueError(f"{path} must contain at least {minimum} properties")
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                raise ValueError(f"{path}.{key} is required")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            unexpected = sorted(set(value) - set(properties))
            if unexpected:
                raise ValueError(f"{path}.{unexpected[0]} is not allowed")
        for key, child in properties.items():
            if key in value:
                _validate(child, value[key], path=f"{path}.{key}")
    elif expected == "array":
        if not isinstance(value, list):
            raise ValueError(f"{path} must be an array")
        minimum = schema.get("minItems")
        if isinstance(minimum, int) and len(value) < minimum:
            raise ValueError(f"{path} must contain at least {minimum} items")
        maximum = schema.get("maxItems")
        if isinstance(maximum, int) and len(value) > maximum:
            raise ValueError(f"{path} must contain at most {maximum} items")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                _validate(item_schema, item, path=f"{path}[{index}]")
    elif expected == "string":
        if not isinstance(value, str):
            raise ValueError(f"{path} must be a string")
        minimum = schema.get("minLength")
        if isinstance(minimum, int) and len(value) < minimum:
            raise ValueError(f"{path} must contain at least {minimum} characters")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            raise ValueError(f"{path} does not match the permitted pattern")
    elif expected == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{path} must be a number")
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and value < minimum:
            raise ValueError(f"{path} must be at least {minimum}")
        if maximum is not None and value > maximum:
            raise ValueError(f"{path} must be at most {maximum}")
    elif expected == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{path} must be an integer")
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and value < minimum:
            raise ValueError(f"{path} must be at least {minimum}")
        if maximum is not None and value > maximum:
            raise ValueError(f"{path} must be at most {maximum}")
    elif expected == "null":
        if value is not None:
            raise ValueError(f"{path} must be null")
    elif expected == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"{path} must be a boolean")
    elif expected is not None:
        raise ValueError(f"{path} uses unsupported schema type {expected}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path} is not one of the allowed values")
    if "const" in schema and value != schema["const"]:
        raise ValueError(f"{path} must equal the frozen constant")


def _without_null_object_properties(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_null_object_properties(item)
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, list):
        return [_without_null_object_properties(item) for item in value]
    return value
