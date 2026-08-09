from __future__ import annotations

import json
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError


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
    "reward_changes",
    "world_rule_usages",
    "power_state_changes",
    "narrative_pattern_fingerprints",
    "theme_movements",
    "antagonist_pressure_changes",
)
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


def _draft_schema() -> dict[str, Any]:
    return _object_schema(
        {"text": {"type": "string", "minLength": 1}},
        required=("text",),
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
            "effective_chapter": {"type": "number", "minimum": 1},
            **evidence_fields,
        },
        required=(
            "subject",
            "predicate",
            "object",
            "effective_chapter",
            *evidence_fields,
        ),
    )
    fact["description"] = (
        "Canonical facts only. Emit at most one item for each "
        "subject/predicate/impact_type semantic slot; never emit contradictory values."
    )
    change = _object_schema(
        {
            "summary": {"type": "string", "minLength": 1},
            **evidence_fields,
        },
        required=("summary", *evidence_fields),
    )
    return _object_schema(
        {
            field: {
                "type": "array",
                "items": fact if field == "canon_facts" else change,
                **({"minItems": 1} if field == "canon_facts" else {}),
            }
            for field in _CANON_FIELDS
        },
        required=_CANON_FIELDS,
    )


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


def chapter_provider_output_schema(stage: str) -> dict[str, Any]:
    """Return the exact provider-facing result contract for a Chapter stage."""

    if stage == "draft":
        schema = _draft_schema()
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
    else:
        raise KernelError(
            "CHAPTER_PROVIDER_OUTPUT_SCHEMA_UNSUPPORTED",
            f"Chapter Provider output schema is not defined for stage {stage}",
        )
    return {"$schema": _SCHEMA_DIALECT, **schema}


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
        fingerprints: dict[tuple[object, ...], str] = {}
        for field in _CANON_FIELDS:
            for item in normalized.get(field, []):
                impact = str(item.get("impact_type") or field)
                if field == "canon_facts":
                    slot: tuple[object, ...] = (
                        field,
                        str(item.get("subject") or ""),
                        impact,
                        str(item.get("predicate") or ""),
                    )
                else:
                    slot = (
                        field,
                        "",
                        impact,
                        float(item.get("evidence_start") or 0),
                        float(item.get("evidence_end") or 0),
                    )
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
    elif expected is not None:
        raise ValueError(f"{path} uses unsupported schema type {expected}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path} is not one of the allowed values")
    if "const" in schema and value != schema["const"]:
        raise ValueError(f"{path} must equal the frozen constant")
