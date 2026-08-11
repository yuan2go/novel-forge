"""Structured Provider contracts for Source deconstruction and abstraction."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


DECONSTRUCTION_STAGE = "source.deconstruction.observe"
MKAOS_STAGE = "source.mkaos.extract"


def content_intelligence_output_schema(stage: str) -> dict[str, Any]:
    if stage == DECONSTRUCTION_STAGE:
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "findings": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 500,
                    "items": {
                        "type": "object",
                        "properties": {
                            "finding_code": {"type": "string", "minLength": 1},
                            "statement": {"type": "string", "minLength": 1},
                            "evidence_span_ids": {
                                "type": "array",
                                "items": {"type": "string", "minLength": 1},
                            },
                            "input_observation_asset_version_ids": {
                                "type": "array",
                                "items": {"type": "string", "minLength": 1},
                            },
                        },
                        "required": [
                            "finding_code",
                            "statement",
                        ],
                        "additionalProperties": False,
                        "anyOf": [
                            {
                                "required": ["evidence_span_ids"],
                                "properties": {
                                    "evidence_span_ids": {"minItems": 1}
                                },
                            },
                            {
                                "required": [
                                    "input_observation_asset_version_ids"
                                ],
                                "properties": {
                                    "input_observation_asset_version_ids": {
                                        "minItems": 1
                                    }
                                },
                            },
                        ],
                    },
                },
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "knowledge_status": {"const": "NOT_ABSTRACTED"},
            },
            "required": ["findings", "confidence", "knowledge_status"],
            "additionalProperties": False,
        }
    if stage == MKAOS_STAGE:
        string_list = {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "minLength": 1, "maxLength": 2_000},
        }
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "concept_name": {"type": "string", "minLength": 1},
                "discipline": {"type": "string", "minLength": 1},
                "abstract_principle": {"type": "string", "minLength": 1},
                "constraints": string_list,
                "conflict_generators": string_list,
                "review_checks": string_list,
                "copyright_boundaries": string_list,
            },
            "required": [
                "concept_name",
                "discipline",
                "abstract_principle",
                "constraints",
                "conflict_generators",
                "review_checks",
                "copyright_boundaries",
            ],
            "additionalProperties": False,
        }
    raise ValueError(f"unsupported content-intelligence stage: {stage}")


def content_intelligence_fixture_response(
    stage: str, inputs: Mapping[str, Any]
) -> dict[str, Any]:
    """Explicit protocol fixture; it never qualifies production knowledge."""

    if stage == DECONSTRUCTION_STAGE:
        evidence_ids = [
            str(item)
            for item in inputs.get("evidence_span_ids") or ()
            if str(item)
        ]
        analyzer = inputs.get("analyzer")
        dimension = (
            str(analyzer.get("dimension") or "structure")
            if isinstance(analyzer, Mapping)
            else "structure"
        )
        if not evidence_ids:
            observation_ids = [
                str(item)
                for item in inputs.get(
                    "input_observation_asset_version_ids"
                )
                or ()
                if str(item)
            ]
            if not observation_ids:
                raise ValueError(
                    "deconstruction fixture requires governed input identities"
                )
        else:
            observation_ids = []
        lineage = (
            {"evidence_span_ids": evidence_ids}
            if evidence_ids
            else {"input_observation_asset_version_ids": observation_ids}
        )
        return {
            "findings": [
                {
                    "finding_code": f"{dimension.upper()}_MECHANISM",
                    "statement": (
                        f"The evidence demonstrates an abstract {dimension} mechanism "
                        "that can be evaluated without retaining source expression."
                    ),
                    **lineage,
                }
            ],
            "confidence": 0.8,
            "knowledge_status": "NOT_ABSTRACTED",
        }
    if stage == MKAOS_STAGE:
        return {
            "concept_name": "Evidence-backed narrative mechanism",
            "discipline": "narrative_design",
            "abstract_principle": (
                "A reusable mechanism should connect reader expectation to an "
                "observable change while remaining independent of source expression."
            ),
            "constraints": [
                "Apply only when the target has comparable reader-state evidence."
            ],
            "conflict_generators": [
                "Make progress require a choice between two incompatible benefits."
            ],
            "review_checks": [
                "Verify that the mechanism changes reader expectation or story state."
            ],
            "copyright_boundaries": [
                "Do not reuse names, expressions, settings, scenes, or plot combinations."
            ],
        }
    raise ValueError(f"unsupported content-intelligence fixture stage: {stage}")


def validate_content_intelligence_output(
    stage: str,
    output_schema: Mapping[str, Any],
    value: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Validate the bounded domain contract used by real Provider backends."""

    expected = content_intelligence_output_schema(stage)
    if dict(output_schema) != expected:
        raise ValueError("content-intelligence output schema differs from Authority")
    payload = dict(value)
    required = set(expected["required"])
    if set(payload) != required:
        raise ValueError("content-intelligence output fields differ from schema")
    if stage == DECONSTRUCTION_STAGE:
        findings = payload.get("findings")
        confidence = payload.get("confidence")
        if (
            not isinstance(findings, list)
            or not 1 <= len(findings) <= 500
            or not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
            or not 0 <= float(confidence) <= 1
            or payload.get("knowledge_status") != "NOT_ABSTRACTED"
        ):
            raise ValueError("invalid deconstruction Provider output")
        for finding in findings:
            allowed_lineage = {
                "evidence_span_ids",
                "input_observation_asset_version_ids",
            }
            if (
                not isinstance(finding, Mapping)
                or not {"finding_code", "statement"}.issubset(finding)
                or set(finding) - {"finding_code", "statement"} - allowed_lineage
                or len(set(finding) & allowed_lineage) != 1
            ):
                raise ValueError("invalid deconstruction finding")
            lineage_values = finding.get(
                "evidence_span_ids",
                finding.get("input_observation_asset_version_ids"),
            )
            if not all(
                (
                    str(finding.get("finding_code") or "").strip(),
                    str(finding.get("statement") or "").strip(),
                    isinstance(lineage_values, list),
                    bool(lineage_values),
                )
            ):
                raise ValueError("incomplete deconstruction finding")
        return payload
    for field in ("concept_name", "discipline", "abstract_principle"):
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            raise ValueError(f"invalid MKAOS field: {field}")
    for field in (
        "constraints",
        "conflict_generators",
        "review_checks",
        "copyright_boundaries",
    ):
        values = payload.get(field)
        if not isinstance(values, list) or not values or any(
            not isinstance(item, str) or not item.strip() or len(item) > 2_000
            for item in values
        ):
            raise ValueError(f"invalid MKAOS field: {field}")
    return payload


__all__ = [
    "DECONSTRUCTION_STAGE",
    "MKAOS_STAGE",
    "content_intelligence_fixture_response",
    "content_intelligence_output_schema",
    "validate_content_intelligence_output",
]
