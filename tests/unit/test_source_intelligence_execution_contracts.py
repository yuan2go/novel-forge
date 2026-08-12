from __future__ import annotations

import pytest

from novel_forge.modules.production_execution import default_capability_registry
from novel_forge.modules.source_import.execution_contracts import (
    CLASSIFICATION_STAGE,
    content_intelligence_fixture_response,
    content_intelligence_output_schema,
    validate_content_intelligence_output,
)


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
