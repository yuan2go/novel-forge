from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from novel_forge.modules.source_authority.deconstruction import (
    SUPPORTED_DECONSTRUCTION_DIMENSIONS,
)


DECONSTRUCTION_STAGE = "source.deconstruction.observe"
MKAOS_STAGE = "source.mkaos.extract"
CLASSIFICATION_STAGE = "source.content.classify"

_CONTENT_TYPES = (
    "WEB_NOVEL",
    "PUBLISHED_FICTION",
    "CLASSIC_LITERATURE",
    "WRITING_THEORY",
    "PROFESSIONAL_KNOWLEDGE",
    "HISTORY_SOCIAL_SCIENCE",
    "BIOGRAPHY_MEMOIR",
    "PHILOSOPHY_ESSAY",
    "PLATFORM_RULES",
    "UNKNOWN",
    "MIXED",
)


def compound_deconstruction_output_schema() -> dict[str, Any]:
    finding = {
        "type": "object",
        "properties": {
            "finding_code": {"type": "string", "minLength": 1},
            "statement": {"type": "string", "minLength": 1},
            "evidence_span_ids": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
        },
        "required": ["finding_code", "statement", "evidence_span_ids"],
        "additionalProperties": False,
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "observations": {
                "type": "array",
                "minItems": 1,
                "maxItems": 12,
                "items": {
                    "type": "object",
                    "properties": {
                        "dimension": {
                            "type": "string",
                            "enum": list(SUPPORTED_DECONSTRUCTION_DIMENSIONS),
                        },
                        "status": {
                            "type": "string",
                            "enum": [
                                "SUCCEEDED",
                                "NOT_APPLICABLE",
                                "FAILED_VALIDATION",
                            ]
                        },
                        "findings": {
                            "type": "array",
                            "minItems": 0,
                            "maxItems": 8,
                            "items": finding,
                        },
                        "confidence": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 1,
                        },
                        "knowledge_status": {
                            "type": "string",
                            "const": "NOT_ABSTRACTED",
                        },
                        "applicability_note": {
                            "type": "string",
                            "maxLength": 2_000,
                        },
                        "validation_errors": {
                            "type": "array",
                            "maxItems": 10,
                            "items": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 500,
                            },
                        },
                    },
                    "required": [
                        "dimension",
                        "status",
                        "findings",
                        "confidence",
                        "knowledge_status",
                        "applicability_note",
                        "validation_errors",
                    ],
                    "additionalProperties": False,
                },
            },
            "coverage_acknowledgement": {
                "type": "object",
                "properties": {
                    "scope_claim": {
                        "type": "string",
                        "enum": ["FULL_WORK", "BOUNDED_STRATIFIED_SAMPLE"]
                    },
                    "uncovered_material_acknowledged": {"type": "boolean"},
                },
                "required": ["scope_claim", "uncovered_material_acknowledged"],
                "additionalProperties": False,
            },
        },
        "required": ["observations", "coverage_acknowledgement"],
        "additionalProperties": False,
    }


def content_intelligence_output_schema(stage: str) -> dict[str, Any]:
    if stage == CLASSIFICATION_STAGE:
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "content_type": {"type": "string", "enum": list(_CONTENT_TYPES)},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "alternatives": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 5,
                    "items": {
                        "type": "object",
                        "properties": {
                            "content_type": {
                                "type": "string",
                                "enum": list(_CONTENT_TYPES),
                            },
                            "confidence": {
                                "type": "number",
                                "minimum": 0,
                                "maximum": 1,
                            },
                        },
                        "required": ["content_type", "confidence"],
                        "additionalProperties": False,
                    },
                },
                "evidence_codes": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 20,
                    "items": {"type": "string", "minLength": 1, "maxLength": 100},
                },
                "boundary_assessment": {
                    "type": "object",
                    "properties": {
                        "scope_kind": {
                            "type": "string",
                            "const": "FILE_DOCUMENT",
                        },
                        "suspected_document_count": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 10000,
                        },
                        "review_required": {"type": "boolean"},
                    },
                    "required": [
                        "scope_kind",
                        "suspected_document_count",
                        "review_required",
                    ],
                    "additionalProperties": False,
                },
            },
            "required": [
                "content_type",
                "confidence",
                "alternatives",
                "evidence_codes",
                "boundary_assessment",
            ],
            "additionalProperties": False,
        }
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
                                    "evidence_span_ids": {
                                        "type": "array",
                                        "minItems": 1,
                                    }
                                },
                            },
                            {
                                "required": ["input_observation_asset_version_ids"],
                                "properties": {
                                    "input_observation_asset_version_ids": {
                                        "type": "array",
                                        "minItems": 1
                                    }
                                },
                            },
                        ],
                    },
                },
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "knowledge_status": {
                    "type": "string",
                    "const": "NOT_ABSTRACTED",
                },
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
        tag_list = {
            "type": "array",
            "maxItems": 32,
            "items": {"type": "string", "minLength": 1, "maxLength": 200},
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
                "knowledge_kind": {
                    "type": "string",
                    "enum": ["NARRATIVE_INTELLIGENCE", "DOMAIN_INTELLIGENCE"]
                },
                "semantic_family": {
                    "type": "string",
                    "enum": [
                        "NARRATIVE_PRIMITIVE",
                        "NARRATIVE_MECHANISM",
                        "ARC_BEAT_PATTERN",
                        "CONFLICT_ESCALATION_REVERSAL_PAYOFF",
                        "CHARACTER_TRANSFORMATION",
                        "RELATIONSHIP",
                        "MYSTERY_CLUE_REVEAL",
                        "WORLD_CONSEQUENCE",
                        "FACTION_DYNAMICS",
                        "POWER_RESOURCE_PROGRESSION",
                        "READER_EMOTIONAL_CURVE",
                        "THEME_MORAL_DILEMMA",
                        "SCENE_INTERACTION",
                        "ANTI_PATTERN_FAILURE",
                        "PROFESSIONAL_CAUSAL_MECHANISM",
                    ]
                },
                "mechanism": {"type": "string", "minLength": 1, "maxLength": 2_000},
                "applicability": string_list,
                "failure_conditions": string_list,
                "selection_tags": {
                    "type": "object",
                    "properties": {
                        "genre": tag_list,
                        "conflict": tag_list,
                        "reader_effect": tag_list,
                        "theme": tag_list,
                    },
                    "required": ["genre", "conflict", "reader_effect", "theme"],
                    "additionalProperties": False,
                },
                "repetition_key": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 200,
                },
                "originality_boundary": {
                    "type": "object",
                    "properties": {
                        "source_specific_sequence_reusable": {
                            "type": "boolean",
                            "const": False,
                        },
                        "named_entity_substitution_allowed": {
                            "type": "boolean",
                            "const": False,
                        },
                        "expression_reuse_allowed": {
                            "type": "boolean",
                            "const": False,
                        },
                    },
                    "required": [
                        "source_specific_sequence_reusable",
                        "named_entity_substitution_allowed",
                        "expression_reuse_allowed",
                    ],
                    "additionalProperties": False,
                },
            },
            "required": [
                "concept_name",
                "discipline",
                "abstract_principle",
                "constraints",
                "conflict_generators",
                "review_checks",
                "copyright_boundaries",
                "knowledge_kind",
                "semantic_family",
                "mechanism",
                "applicability",
                "failure_conditions",
                "selection_tags",
                "repetition_key",
                "originality_boundary",
            ],
            "additionalProperties": False,
        }
    raise ValueError(f"unsupported content-intelligence stage: {stage}")


def content_intelligence_fixture_response(
    stage: str, inputs: Mapping[str, Any]
) -> dict[str, Any]:

    if stage == CLASSIFICATION_STAGE:
        return _classification_fixture(inputs)
    if stage == DECONSTRUCTION_STAGE:
        evidence_ids = [
            str(item) for item in inputs.get("evidence_span_ids") or () if str(item)
        ]
        compound = inputs.get("analyzers")
        if isinstance(compound, list) and compound:
            if not evidence_ids:
                raise ValueError(
                    "compound deconstruction fixture requires governed Source evidence"
                )
            observations = []
            for item in compound:
                if not isinstance(item, Mapping):
                    raise ValueError("compound analyzer fixture input is invalid")
                dimension = str(item.get("dimension") or "")
                if dimension not in SUPPORTED_DECONSTRUCTION_DIMENSIONS:
                    raise ValueError("compound analyzer dimension is invalid")
                observations.append(
                    {
                        "dimension": dimension,
                        "status": "SUCCEEDED",
                        "findings": [
                            {
                                "finding_code": f"{dimension.upper()}_MECHANISM",
                                "statement": (
                                    "The evidence demonstrates an abstract "
                                    f"{dimension} mechanism without retaining source "
                                    "expression."
                                ),
                                "evidence_span_ids": evidence_ids,
                            }
                        ],
                        "confidence": 0.8,
                        "knowledge_status": "NOT_ABSTRACTED",
                        "applicability_note": "Applicable to the bounded sample.",
                        "validation_errors": [],
                    }
                )
            sampling = inputs.get("sampling_manifest")
            whole_work = bool(
                isinstance(sampling, Mapping)
                and sampling.get("whole_work_analyzed") is True
            )
            return {
                "observations": observations,
                "coverage_acknowledgement": {
                    "scope_claim": (
                        "FULL_WORK" if whole_work else "BOUNDED_STRATIFIED_SAMPLE"
                    ),
                    "uncovered_material_acknowledged": not whole_work,
                },
            }
        analyzer = inputs.get("analyzer")
        dimension = (
            str(analyzer.get("dimension") or "structure")
            if isinstance(analyzer, Mapping)
            else "structure"
        )
        if not evidence_ids:
            observation_ids = [
                str(item)
                for item in inputs.get("input_observation_asset_version_ids") or ()
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
            "knowledge_kind": "NARRATIVE_INTELLIGENCE",
            "semantic_family": "CONFLICT_ESCALATION_REVERSAL_PAYOFF",
            "mechanism": (
                "Bind progress to a choice between incompatible benefits so the "
                "same causal event advances conflict and changes reader expectation."
            ),
            "applicability": [
                "Use when the target plan needs causally coupled progress and cost."
            ],
            "failure_conditions": [
                "Reject when the mechanism would reproduce a source-specific event sequence."
            ],
            "selection_tags": {
                "genre": [],
                "conflict": ["incompatible benefits", "cost of progress"],
                "reader_effect": ["anticipation", "tension"],
                "theme": ["choice and consequence"],
            },
            "repetition_key": "incompatible-benefit-progress-cost",
            "originality_boundary": {
                "source_specific_sequence_reusable": False,
                "named_entity_substitution_allowed": False,
                "expression_reuse_allowed": False,
            },
        }
    raise ValueError(f"unsupported content-intelligence fixture stage: {stage}")


def validate_content_intelligence_output(
    stage: str,
    output_schema: Mapping[str, Any],
    value: Mapping[str, Any],
) -> Mapping[str, Any]:

    compound_schema = compound_deconstruction_output_schema()
    is_compound = stage == DECONSTRUCTION_STAGE and dict(output_schema) == compound_schema
    expected = (
        compound_schema if is_compound else content_intelligence_output_schema(stage)
    )
    if dict(output_schema) != expected:
        raise ValueError("content-intelligence output schema differs from Authority")
    payload = dict(value)
    required = set(expected["required"])
    if set(payload) != required:
        raise ValueError("content-intelligence output fields differ from schema")
    if stage == CLASSIFICATION_STAGE:
        content_type = payload.get("content_type")
        confidence = payload.get("confidence")
        alternatives = payload.get("alternatives")
        evidence_codes = payload.get("evidence_codes")
        boundary = payload.get("boundary_assessment")
        if (
            content_type not in _CONTENT_TYPES
            or not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
            or not 0 <= float(confidence) <= 1
            or not isinstance(alternatives, list)
            or not 2 <= len(alternatives) <= 5
            or not isinstance(evidence_codes, list)
            or not evidence_codes
            or any(
                not isinstance(item, str) or not item.strip() or len(item) > 100
                for item in evidence_codes
            )
            or not isinstance(boundary, Mapping)
            or set(boundary)
            != {"scope_kind", "suspected_document_count", "review_required"}
            or boundary.get("scope_kind") != "FILE_DOCUMENT"
            or not isinstance(boundary.get("suspected_document_count"), int)
            or isinstance(boundary.get("suspected_document_count"), bool)
            or not 1 <= int(boundary["suspected_document_count"]) <= 10_000
            or not isinstance(boundary.get("review_required"), bool)
        ):
            raise ValueError("invalid Source classification Provider output")
        scores: dict[str, float] = {}
        for item in alternatives:
            if not isinstance(item, Mapping) or set(item) != {
                "content_type",
                "confidence",
            }:
                raise ValueError("invalid Source classification alternative")
            kind = item.get("content_type")
            score = item.get("confidence")
            if (
                kind not in _CONTENT_TYPES
                or kind in scores
                or not isinstance(score, (int, float))
                or isinstance(score, bool)
                or not 0 <= float(score) <= 1
            ):
                raise ValueError("invalid Source classification alternative")
            scores[str(kind)] = float(score)
        ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        if (
            ordered[0][0] != content_type
            or abs(ordered[0][1] - float(confidence)) > 0.000001
        ):
            raise ValueError("classification top alternative is inconsistent")
        return payload
    if stage == DECONSTRUCTION_STAGE:
        if is_compound:
            return _validate_compound_deconstruction(payload)
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
        if (
            not isinstance(values, list)
            or not values
            or any(
                not isinstance(item, str) or not item.strip() or len(item) > 2_000
                for item in values
            )
        ):
            raise ValueError(f"invalid MKAOS field: {field}")
    if payload.get("knowledge_kind") not in {
        "NARRATIVE_INTELLIGENCE",
        "DOMAIN_INTELLIGENCE",
    }:
        raise ValueError("invalid MKAOS knowledge_kind")
    if not isinstance(payload.get("semantic_family"), str):
        raise ValueError("invalid MKAOS semantic_family")
    for field in ("mechanism", "repetition_key"):
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            raise ValueError(f"invalid MKAOS field: {field}")
    for field in ("applicability", "failure_conditions"):
        values = payload.get(field)
        if not isinstance(values, list) or not values:
            raise ValueError(f"invalid MKAOS field: {field}")
    tags = payload.get("selection_tags")
    if (
        not isinstance(tags, Mapping)
        or set(tags)
        != {
            "genre",
            "conflict",
            "reader_effect",
            "theme",
        }
        or any(not isinstance(value, list) for value in tags.values())
    ):
        raise ValueError("invalid MKAOS selection_tags")
    boundary = payload.get("originality_boundary")
    if (
        not isinstance(boundary, Mapping)
        or set(boundary)
        != {
            "source_specific_sequence_reusable",
            "named_entity_substitution_allowed",
            "expression_reuse_allowed",
        }
        or any(value is not False for value in boundary.values())
    ):
        raise ValueError("invalid MKAOS originality_boundary")
    return payload


def _validate_compound_deconstruction(payload: dict[str, Any]) -> dict[str, Any]:
    observations = payload.get("observations")
    coverage = payload.get("coverage_acknowledgement")
    if (
        not isinstance(observations, list)
        or not 1 <= len(observations) <= 12
        or not isinstance(coverage, Mapping)
        or set(coverage)
        != {"scope_claim", "uncovered_material_acknowledged"}
        or coverage.get("scope_claim")
        not in {"FULL_WORK", "BOUNDED_STRATIFIED_SAMPLE"}
        or not isinstance(coverage.get("uncovered_material_acknowledged"), bool)
    ):
        raise ValueError("invalid compound deconstruction Provider output")
    dimensions: set[str] = set()
    for item in observations:
        if not isinstance(item, Mapping) or set(item) != {
            "dimension",
            "status",
            "findings",
            "confidence",
            "knowledge_status",
            "applicability_note",
            "validation_errors",
        }:
            raise ValueError("invalid compound deconstruction dimension result")
        dimension = str(item.get("dimension") or "")
        status = str(item.get("status") or "")
        findings = item.get("findings")
        confidence = item.get("confidence")
        applicability_note = item.get("applicability_note")
        validation_errors = item.get("validation_errors")
        if (
            dimension not in SUPPORTED_DECONSTRUCTION_DIMENSIONS
            or dimension in dimensions
            or status not in {"SUCCEEDED", "NOT_APPLICABLE", "FAILED_VALIDATION"}
            or not isinstance(findings, list)
            or len(findings) > 8
            or not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
            or not 0 <= float(confidence) <= 1
            or item.get("knowledge_status") != "NOT_ABSTRACTED"
            or not isinstance(applicability_note, str)
            or len(applicability_note) > 2_000
            or not isinstance(validation_errors, list)
            or len(validation_errors) > 10
            or any(
                not isinstance(error, str)
                or not error.strip()
                or len(error) > 500
                for error in validation_errors
            )
        ):
            raise ValueError("invalid compound deconstruction dimension result")
        dimensions.add(dimension)
        if status == "SUCCEEDED" and (not findings or validation_errors):
            raise ValueError("successful compound dimension lacks valid findings")
        if status == "NOT_APPLICABLE" and (
            findings or not applicability_note.strip() or validation_errors
        ):
            raise ValueError("NOT_APPLICABLE compound dimension is inconsistent")
        if status == "FAILED_VALIDATION" and not validation_errors:
            raise ValueError("failed compound dimension lacks validation errors")
        for finding in findings:
            if (
                not isinstance(finding, Mapping)
                or set(finding)
                != {"finding_code", "statement", "evidence_span_ids"}
                or not str(finding.get("finding_code") or "").strip()
                or not str(finding.get("statement") or "").strip()
                or not isinstance(finding.get("evidence_span_ids"), list)
                or not finding["evidence_span_ids"]
                or any(
                    not isinstance(identity, str) or not identity.strip()
                    for identity in finding["evidence_span_ids"]
                )
            ):
                raise ValueError("invalid compound deconstruction finding")
    return payload


def _classification_fixture(inputs: Mapping[str, Any]) -> dict[str, Any]:

    evidence = inputs.get("classification_evidence")
    samples = inputs.get("classification_samples")
    if (
        not isinstance(evidence, Mapping)
        or not isinstance(samples, list)
        or not samples
    ):
        raise ValueError("classification fixture requires bounded governed samples")
    text = "\n".join(
        str(item.get("content") or "") for item in samples if isinstance(item, Mapping)
    ).lower()
    signals = evidence.get("signals")
    if not isinstance(signals, Mapping):
        raise ValueError("classification fixture requires structural signals")
    path_tokens = {
        str(item).lower() for item in evidence.get("path_hints") or () if str(item)
    }
    scores = {kind: 0.0 for kind in _CONTENT_TYPES[:-2]}

    def add(kind: str, terms: tuple[str, ...], weight: float = 1.0) -> None:
        scores[kind] += weight * sum(term in text for term in terms)

    add(
        "WEB_NOVEL",
        (
            "cliffhanger",
            "chapter update",
            "reader retention",
            "爽点",
            "追读",
            "断章",
            "金手指",
        ),
        1.4,
    )
    add(
        "PUBLISHED_FICTION",
        (
            "scene",
            "dialogue",
            "protagonist",
            "narrator",
            "she said",
            "he said",
            "小说",
            "人物",
        ),
        1.0,
    )
    add(
        "CLASSIC_LITERATURE",
        ("tragedy", "fate", "symbol", "social class", "古典", "命运", "象征", "礼教"),
        1.0,
    )
    add(
        "WRITING_THEORY",
        (
            "craft",
            "plot",
            "hook",
            "pacing",
            "scene objective",
            "forward pressure",
            "写作",
            "叙事",
            "节奏",
        ),
        1.2,
    )
    add(
        "PROFESSIONAL_KNOWLEDGE",
        (
            "quorum",
            "consistency model",
            "algorithm",
            "protocol",
            "engineering",
            "clinical",
            "legal",
            "system design",
            "分布式",
            "工程",
            "专业",
        ),
        1.4,
    )
    add(
        "HISTORY_SOCIAL_SCIENCE",
        (
            "historical",
            "institution",
            "society",
            "archive",
            "empire",
            "revolution",
            "历史",
            "制度",
            "社会",
        ),
        1.1,
    )
    add(
        "BIOGRAPHY_MEMOIR",
        (
            "memoir",
            "my childhood",
            "my life",
            "autobiography",
            "回忆录",
            "我的一生",
            "童年",
        ),
        1.3,
    )
    add(
        "PHILOSOPHY_ESSAY",
        (
            "argument",
            "premise",
            "counterargument",
            "ethics",
            "epistemology",
            "哲学",
            "论证",
            "伦理",
        ),
        1.2,
    )
    add(
        "PLATFORM_RULES",
        (
            "platform policy",
            "eligibility",
            "prohibited content",
            "terms of service",
            "submission rule",
            "平台规则",
            "签约",
            "违规",
            "审核",
        ),
        1.6,
    )
    dialogue_ratio = float(signals.get("dialogue_line_ratio") or 0)
    citation_count = int(signals.get("citation_count") or 0)
    first_person = float(signals.get("first_person_density") or 0)
    chapter_markers = int(signals.get("chapter_marker_count") or 0)
    if dialogue_ratio >= 0.12:
        scores["PUBLISHED_FICTION"] += 1.4
    if chapter_markers >= 3:
        scores["WEB_NOVEL"] += 1.2
    if citation_count >= 2:
        scores["HISTORY_SOCIAL_SCIENCE"] += 0.8
        scores["PROFESSIONAL_KNOWLEDGE"] += 0.6
    if first_person >= 0.2:
        scores["BIOGRAPHY_MEMOIR"] += 1.0
    weak_path_hints = {
        "rules": "PLATFORM_RULES",
        "policy": "PLATFORM_RULES",
        "fiction": "PUBLISHED_FICTION",
        "novel": "WEB_NOVEL",
        "history": "HISTORY_SOCIAL_SCIENCE",
        "memoir": "BIOGRAPHY_MEMOIR",
        "theory": "WRITING_THEORY",
    }
    for token, kind in weak_path_hints.items():
        if token in path_tokens:
            scores[kind] += 0.25
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    top_kind, top_score = ordered[0]
    second_kind, second_score = ordered[1]
    if top_score < 1.0:
        kind = "UNKNOWN"
        confidence = 0.62
        alternatives = [
            {"content_type": "UNKNOWN", "confidence": confidence},
            {"content_type": top_kind, "confidence": 0.28},
        ]
    elif second_score >= 1.5 and top_score - second_score < 0.45:
        kind = "MIXED"
        confidence = 0.78
        alternatives = [
            {"content_type": "MIXED", "confidence": confidence},
            {"content_type": top_kind, "confidence": 0.11},
            {"content_type": second_kind, "confidence": 0.09},
        ]
    else:
        kind = top_kind
        confidence = min(0.97, 0.78 + top_score * 0.045)
        runner_up = min(0.19, max(0.01, second_score * 0.04))
        alternatives = [
            {"content_type": kind, "confidence": round(confidence, 6)},
            {"content_type": second_kind, "confidence": round(runner_up, 6)},
        ]
    return {
        "content_type": kind,
        "confidence": round(confidence, 6),
        "alternatives": alternatives,
        "evidence_codes": ["DETERMINISTIC_SIGNALS", "BOUNDED_SEMANTIC_SAMPLE"],
        "boundary_assessment": {
            "scope_kind": "FILE_DOCUMENT",
            "suspected_document_count": 1,
            "review_required": kind == "MIXED",
        },
    }


__all__ = [
    "CLASSIFICATION_STAGE",
    "DECONSTRUCTION_STAGE",
    "MKAOS_STAGE",
    "content_intelligence_fixture_response",
    "content_intelligence_output_schema",
    "compound_deconstruction_output_schema",
    "validate_content_intelligence_output",
]
