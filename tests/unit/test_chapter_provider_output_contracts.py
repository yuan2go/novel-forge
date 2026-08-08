from __future__ import annotations

from copy import deepcopy

import pytest

from novel_forge.modules.chapter_authority.provider_output_contracts import (
    chapter_provider_output_schema,
    validate_chapter_provider_output_schema,
)
from novel_forge.modules.command_kernel.errors import KernelError


CANON_FIELDS = (
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


def _valid(stage: str) -> dict[str, object]:
    if stage == "draft":
        return {"text": "The choice closes the only safe road home."}
    if stage in {"review", "rereview"}:
        return {
            "score": 72,
            "issues": [
                {
                    "code": "COST_NOT_CONCRETE",
                    "severity": "blocking",
                    "message": "Make the irreversible cost visible.",
                }
            ],
        }
    if stage == "revision":
        return {
            "text": "She burns the map while the witnesses watch.",
            "resolved_issue_codes": ["COST_NOT_CONCRETE"],
        }
    if stage == "canon_extraction":
        return {
            field: (
                [
                    {
                        "subject": "protagonist",
                        "predicate": "made_choice",
                        "object": "exposed_record",
                        "effective_chapter": 1,
                        "evidence_start": 0,
                        "evidence_end": 24,
                        "confidence": 0.91,
                        "impact_type": "chapter_event",
                    }
                ]
                if field == "canon_facts"
                else []
            )
            for field in CANON_FIELDS
        }
    if stage.startswith("quality_"):
        return {
            "dimensions": [
                {
                    "dimension": "causal_clarity",
                    "gate_status": "PASSED",
                    "score": 91,
                    "confidence": 0.91,
                    "evidence_locations": [
                        {"start": 0, "end": 24, "claim": "visible choice"}
                    ],
                    "issue_codes": [],
                    "revision_strategies": [],
                }
            ]
        }
    if stage == "reader_outcome":
        return {
            "reader_state": {
                "continue_intent": 0.9,
                "curiosity": 0.8,
                "satisfaction": 0.8,
                "confusion": 0.1,
                "trust": 0.8,
                "character_attachment": 0.8,
                "antagonist_pressure": 0.7,
                "promise_expectation": 0.8,
                "payoff_satisfaction": 0.8,
                "drop_risk": 0.1,
                "repetition_fatigue": 0.1,
            },
            "evidence": [
                {
                    "asset_version_id": "draft:v2",
                    "location": "chapter",
                    "claim": "closing hook sustains curiosity",
                }
            ],
        }
    raise AssertionError(stage)


@pytest.mark.parametrize(
    "stage",
    (
        "draft",
        "review",
        "revision",
        "rereview",
        "canon_extraction",
        "quality_structural",
        "quality_commercial",
        "quality_source_originality",
        "quality_longform",
        "quality_platform",
        "reader_outcome",
    ),
)
def test_every_model_stage_has_a_strict_schema_and_accepts_its_contract(
    stage: str,
) -> None:
    schema = chapter_provider_output_schema(stage)

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert validate_chapter_provider_output_schema(stage, _valid(stage)) == _valid(
        stage
    )


def test_schema_validation_rejects_missing_required_field_before_semantics() -> None:
    with pytest.raises(KernelError) as raised:
        validate_chapter_provider_output_schema("review", {"score": 72})

    assert raised.value.code == "CHAPTER_PROVIDER_OUTPUT_SCHEMA_INVALID"
    assert "issues" in str(raised.value)


def test_schema_validation_rejects_additional_properties() -> None:
    value = _valid("draft")
    value["untrusted"] = True

    with pytest.raises(KernelError) as raised:
        validate_chapter_provider_output_schema("draft", value)

    assert raised.value.code == "CHAPTER_PROVIDER_OUTPUT_SCHEMA_INVALID"
    assert "untrusted" in str(raised.value)


def test_schema_validation_does_not_treat_boolean_as_number() -> None:
    value = deepcopy(_valid("quality_structural"))
    value["dimensions"][0]["confidence"] = True  # type: ignore[index]

    with pytest.raises(KernelError) as raised:
        validate_chapter_provider_output_schema("quality_structural", value)

    assert raised.value.code == "CHAPTER_PROVIDER_OUTPUT_SCHEMA_INVALID"
    assert "confidence" in str(raised.value)


def test_unsupported_stage_fails_closed() -> None:
    with pytest.raises(KernelError) as raised:
        chapter_provider_output_schema("unknown")

    assert raised.value.code == "CHAPTER_PROVIDER_OUTPUT_SCHEMA_UNSUPPORTED"


def test_provider_schema_has_no_open_object_escape_hatch() -> None:
    def assert_closed(schema: object) -> None:
        if isinstance(schema, dict):
            if schema.get("type") == "object":
                assert schema.get("additionalProperties") is False
                assert set(schema.get("required") or ()) == set(
                    (schema.get("properties") or {}).keys()
                )
            for child in schema.values():
                assert_closed(child)
        elif isinstance(schema, list):
            for child in schema:
                assert_closed(child)

    for stage in ("canon_extraction", "quality_structural", "reader_outcome"):
        assert_closed(chapter_provider_output_schema(stage))
