from __future__ import annotations

import pytest

from novel_forge.modules.production_execution import default_capability_registry
from novel_forge.modules.source_import.execution_contracts import (
    CLASSIFICATION_STAGE,
    DECONSTRUCTION_STAGE,
    MKAOS_STAGE,
    compound_deconstruction_output_schema,
    content_intelligence_fixture_response,
    content_intelligence_output_schema,
    validate_content_intelligence_output,
)
from novel_forge.modules.source_authority.deconstruction import AnalyzerContract


def _inputs(content: str) -> dict[str, object]:
    return {
        "classification_evidence": {
            "signals": {
                "dialogue_line_ratio": 0,
                "citation_count": 0,
                "first_person_density": 0,
                "chapter_marker_count": 0,
            },
            "path_hints": ["corpus", "document", "md"],
        },
        "classification_samples": [
            {
                "source_chunk_asset_version_id": "source-chunk:one:v1",
                "content": content,
            }
        ],
    }


def test_source_content_classification_is_registered_and_bounded() -> None:
    definition = default_capability_registry().resolve("source.content.classify")
    assert definition.domain.value == "source"
    schema = content_intelligence_output_schema(CLASSIFICATION_STAGE)
    assert schema["additionalProperties"] is False
    assert schema["properties"]["alternatives"]["maxItems"] == 5


def test_fixture_classifier_uses_semantics_and_routes_heterogeneous_documents() -> None:
    fiction = content_intelligence_fixture_response(
        CLASSIFICATION_STAGE,
        _inputs('The protagonist entered the scene. "I did not invite you," she said.'),
    )
    professional = content_intelligence_fixture_response(
        CLASSIFICATION_STAGE,
        _inputs(
            "A quorum and consistency model constrain a distributed system protocol."
        ),
    )
    assert fiction["content_type"] == "PUBLISHED_FICTION"
    assert professional["content_type"] == "PROFESSIONAL_KNOWLEDGE"
    assert fiction["content_type"] != professional["content_type"]


def test_malformed_unknown_or_inconsistent_classifier_output_fails_validation() -> None:
    schema = content_intelligence_output_schema(CLASSIFICATION_STAGE)
    output = content_intelligence_fixture_response(
        CLASSIFICATION_STAGE, _inputs("uninterpretable material")
    )
    assert output["content_type"] == "UNKNOWN"
    validate_content_intelligence_output(CLASSIFICATION_STAGE, schema, output)
    malformed = {**output, "confidence": 0.99}
    with pytest.raises(ValueError, match="top alternative"):
        validate_content_intelligence_output(CLASSIFICATION_STAGE, schema, malformed)


def test_mkaos_extraction_requires_structured_originality_safe_intelligence() -> None:
    schema = content_intelligence_output_schema(MKAOS_STAGE)
    output = content_intelligence_fixture_response(MKAOS_STAGE, {})
    assert output["semantic_family"] == "CONFLICT_ESCALATION_REVERSAL_PAYOFF"
    assert output["originality_boundary"] == {
        "source_specific_sequence_reusable": False,
        "named_entity_substitution_allowed": False,
        "expression_reuse_allowed": False,
    }
    assert schema["additionalProperties"] is False
    validate_content_intelligence_output(MKAOS_STAGE, schema, output)

    unsafe = {
        **output,
        "originality_boundary": {
            **output["originality_boundary"],
            "named_entity_substitution_allowed": True,
        },
    }
    with pytest.raises(ValueError, match="originality_boundary"):
        validate_content_intelligence_output(MKAOS_STAGE, schema, unsafe)


def test_compound_deconstruction_keeps_typed_dimensions_in_one_bounded_output() -> None:
    analyzers = [
        AnalyzerContract(
            analyzer_id=f"novel-forge.test.{dimension}",
            analyzer_version="1.0",
            dimension=dimension,
            schema_version="source-deconstruction-observation.v1",
            prompt_id="source.test.compound",
            prompt_version="1.0",
            skill_id="published-fiction-craft-analysis",
            skill_version="1.0",
            capability_id="deconstruction.observe",
            capability_version="1.0",
            provider_policy_version="1.0",
            aggregation_policy_version="3.0",
            recommended_scales=("BOOK",),
        ).to_dict()
        for dimension in ("structure", "conflict", "pacing")
    ]
    inputs = {
        "analyzers": analyzers,
        "evidence_span_ids": ["source-evidence-span:one"],
        "sampling_manifest": {"whole_work_analyzed": False},
    }
    output = content_intelligence_fixture_response(DECONSTRUCTION_STAGE, inputs)
    schema = compound_deconstruction_output_schema()

    validated = validate_content_intelligence_output(
        DECONSTRUCTION_STAGE, schema, output
    )

    assert [item["dimension"] for item in validated["observations"]] == [
        "structure",
        "conflict",
        "pacing",
    ]
    assert validated["coverage_acknowledgement"] == {
        "scope_claim": "BOUNDED_STRATIFIED_SAMPLE",
        "uncovered_material_acknowledged": True,
    }


def test_compound_not_applicable_result_cannot_smuggle_findings() -> None:
    schema = compound_deconstruction_output_schema()
    output = {
        "observations": [
            {
                "dimension": "character_choice_cost",
                "status": "NOT_APPLICABLE",
                "findings": [
                    {
                        "finding_code": "INVENTED_ARC",
                        "statement": "This should not be accepted.",
                        "evidence_span_ids": ["source-evidence-span:one"],
                    }
                ],
                "confidence": 0.5,
                "knowledge_status": "NOT_ABSTRACTED",
                "applicability_note": "The source contains no character arc.",
                "validation_errors": [],
            }
        ],
        "coverage_acknowledgement": {
            "scope_claim": "BOUNDED_STRATIFIED_SAMPLE",
            "uncovered_material_acknowledged": True,
        },
    }
    with pytest.raises(ValueError, match="NOT_APPLICABLE"):
        validate_content_intelligence_output(DECONSTRUCTION_STAGE, schema, output)
