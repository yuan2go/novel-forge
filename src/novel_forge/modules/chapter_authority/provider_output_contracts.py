from __future__ import annotations

import json
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state.contracts import (
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
    """Represent a business-optional field in a Codex strict output schema."""

    value = dict(schema)
    expected = value.get("type")
    if not isinstance(expected, str):
        raise ValueError("nullable schema requires one concrete JSON type")
    value["type"] = [expected, "null"]
    return value


def _draft_schema() -> dict[str, Any]:
    return _object_schema(
        {"text": {"type": "string", "minLength": 1}},
        required=("text",),
    )


def _agent_session_schema() -> dict[str, Any]:
    """Strict provider contract for one governed Agent Harness turn."""

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


def _review_schema() -> dict[str, Any]:
    issue = _object_schema(
        {
            "code": {"type": "string", "minLength": 1},
            "severity": {
                "type": "string",
                "enum": [
                    "critical",
                    "blocker",
                    "blocking",
                    "high",
                    "major",
                    "medium",
                    "minor",
                    "low",
                ],
            },
            "message": {"type": "string", "minLength": 1},
        },
        required=("code", "severity", "message"),
    )
    return _object_schema(
        {
            "score": {"type": "number", "minimum": 0, "maximum": 100},
            "issues": {"type": "array", "items": issue},
        },
        required=("score", "issues"),
    )


def _revision_schema() -> dict[str, Any]:
    return _object_schema(
        {
            "text": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "Final reader-facing revised chapter prose only. Do not embed "
                    "JSON, analysis, self-checks, change logs, evidence appendices, "
                    "or other operator metadata in this string."
                ),
            },
            "resolved_issue_codes": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string", "minLength": 1},
            },
        },
        required=("text", "resolved_issue_codes"),
    )


def _canon_schema() -> dict[str, Any]:
    evidence_fields = {
        "evidence_start": {"type": "number", "minimum": 0},
        "evidence_end": {"type": "number", "minimum": 1},
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
            # Each semantic array owns its schema.  Sharing ``change`` here
            # lets a field-specific refinement silently mutate every other
            # Canon change contract.
            "items": (
                fact if field == "canon_facts" else json.loads(json.dumps(change))
            ),
            **({"minItems": 1} if field == "canon_facts" else {}),
        }
        for field in _CANON_FIELDS
    }
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
                "resolution_evidence": {"type": "array", "items": {"type": "string"}},
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
                            "start": {"type": "integer", "minimum": 0},
                            "end": {"type": "integer", "minimum": 1},
                            "summary": {"type": "string", "minLength": 1},
                        },
                        required=("start", "end", "summary"),
                    ),
                },
                "observed_consequence": _nullable(
                    {"type": "string", "minLength": 1}
                ),
                "observed_action": _nullable({"type": "string", "minLength": 1}),
                "observed_decision": _nullable(
                    {"type": "string", "minLength": 1}
                ),
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
                    "enum": [
                        "PROMISE",
                        "FORESHADOWING",
                        "MYSTERY",
                        "CONFLICT",
                        "OPEN_LOOP",
                        "HOOK",
                        "CHARACTER_COMMITMENT",
                        "READER_EXPECTATION",
                        "NARRATIVE_DEBT",
                    ],
                },
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
                            "asset_version_id": {"type": "string", "minLength": 1},
                            "event_id": {"type": "string", "minLength": 1},
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
    schema = _object_schema(
        properties,
        required=(*_CANON_FIELDS, "arc_evidence", "realization_evidence"),
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


def _quality_schema() -> dict[str, Any]:
    location = _object_schema(
        {
            "start": {"type": "number", "minimum": 0},
            "end": {"type": "number", "minimum": 1},
            "claim": {"type": "string", "minLength": 1},
        },
        required=("start", "end", "claim"),
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
                "minItems": 1,
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


def chapter_provider_output_schema(stage: str) -> dict[str, Any]:
    """Return the exact provider-facing result contract for a Chapter stage."""

    if stage == "draft":
        schema = _draft_schema()
    elif stage == "agent_session":
        schema = _agent_session_schema()
    elif stage in {"review", "rereview"}:
        schema = _review_schema()
    elif stage == "revision":
        schema = _revision_schema()
    elif stage == "canon_extraction":
        schema = _canon_schema()
    elif stage in _QUALITY_STAGES:
        schema = _quality_schema()
    elif stage == "reader_outcome":
        schema = _reader_outcome_schema()
    elif stage == "retrieval":
        schema = _retrieval_embedding_schema()
    else:
        raise KernelError(
            "CHAPTER_PROVIDER_OUTPUT_SCHEMA_UNSUPPORTED",
            f"Chapter Provider output schema is not defined for stage {stage}",
        )
    return {"$schema": _SCHEMA_DIALECT, **schema}


def chapter_provider_output_schema_ref(stage: str) -> str:
    chapter_provider_output_schema(stage)
    version = (
        "v12"
        if stage == "canon_extraction"
        else "v2"
        if stage in _QUALITY_STAGES
        else "v1"
    )
    return f"schema:chapter-provider-output:{stage}:{version}"


def validate_chapter_provider_output_schema(
    stage: str,
    value: object,
) -> dict[str, Any]:
    """Validate the strict JSON contract without adding a second schema runtime."""

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
    """Validate against the exact frozen schema supplied by the Capability runtime."""

    try:
        _validate(dict(schema), value, path="$", enforce_dialect=True)
    except ValueError as exc:
        raise KernelError(
            "CHAPTER_PROVIDER_OUTPUT_SCHEMA_INVALID",
            f"stage {stage}: {exc}",
        ) from exc
    # JSON round-tripping freezes a JSON-compatible copy for downstream semantics.
    return json.loads(json.dumps(value, ensure_ascii=False))


def validate_chapter_provider_output_semantics(
    stage: str,
    value: Mapping[str, Any],
) -> dict[str, Any]:
    """Reject structurally legal results that are not eligible stage outputs."""

    normalized = json.loads(json.dumps(value, ensure_ascii=False))
    if stage == "canon_extraction":
        normalized = _without_null_object_properties(normalized)
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
            if str(obligation.get("status") or "").upper() == "FULFILLED" and not (
                isinstance(obligation.get("payoff_evidence"), Mapping)
                and str(obligation["payoff_evidence"].get("asset_version_id") or "")
                and str(obligation["payoff_evidence"].get("event_id") or "")
            ):
                raise KernelError(
                    "CHAPTER_PROVIDER_OUTPUT_SEMANTIC_INVALID",
                    "fulfilled Narrative Obligation requires typed payoff evidence",
                )
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
                and evidence.get("observed_decision")
                and evidence.get("observed_state_deltas")
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

    text = str(normalized.get("text") or "").strip()
    if not text:
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
        or not issue_codes
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
    """Return a domain identity, never an evidence-location heuristic.

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
