from __future__ import annotations

from copy import deepcopy

import pytest

from novel_forge.modules.chapter_authority.execution_gateway import (
    _stage_semantic_contract,
)
from novel_forge.modules.chapter_authority.provider_output_contracts import (
    chapter_provider_output_schema,
    chapter_provider_output_schema_ref,
    validate_chapter_provider_output_against_schema,
    validate_chapter_provider_output_semantics,
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
    "plot_thread_changes",
    "resource_state_changes",
    "narrative_pattern_fingerprints",
    "theme_movements",
    "antagonist_pressure_changes",
)


def test_revision_prompt_requires_issue_resolution_and_language_continuity() -> None:
    contract = _stage_semantic_contract("revision")

    assert "Resolve every supplied review issue" in contract
    assert "Preserve the reader-facing language" in contract
    assert "resolved_issue_codes" in contract
    assert "smallest bounded edit" in contract
    assert "preserve all unrelated scenes" in contract
    assert "Never replace the full chapter with a summary or excerpt" in contract


def test_rereview_prompt_reports_only_acceptance_blocking_defects() -> None:
    contract = _stage_semantic_contract("rereview")

    assert "acceptance-blocking" in contract
    assert "minor polish" in contract
    assert "issues=[]" in contract


def test_quality_prompt_and_schema_version_require_dimension_evidence() -> None:
    contract = _stage_semantic_contract("quality_platform")

    assert "Every returned dimension" in contract
    assert "at least one concrete evidence location" in contract
    assert (
        chapter_provider_output_schema_ref("quality_platform")
        == "schema:chapter-provider-output:quality_platform:v2"
    )
    assert (
        chapter_provider_output_schema_ref("draft")
        == "schema:chapter-provider-output:draft:v1"
    )
    assert (
        chapter_provider_output_schema_ref("canon_extraction")
        == "schema:chapter-provider-output:canon_extraction:v2"
    )


def test_longform_quality_prompt_distinguishes_proven_noop_from_missing_state() -> None:
    contract = _stage_semantic_contract("quality_longform")

    assert "no state-changing use or claim" in contract
    assert "current state candidates contain no transition" in contract
    assert "PASSED with concrete no-op evidence" in contract
    assert "claims a state or transition" in contract
    assert "INSUFFICIENT_EVIDENCE" in contract


def test_canon_prompt_explains_unique_semantic_slot_encoding() -> None:
    contract = _stage_semantic_contract("canon_extraction")

    assert "(subject, predicate, impact_type)" in contract
    assert "at most once" in contract
    assert "authorizes_testimony" in contract
    assert "authorizes_public_identification" in contract


def test_canon_prompt_binds_transition_preconditions_to_accepted_state() -> None:
    contract = _stage_semantic_contract("canon_extraction")

    assert "accepted Story State" in contract
    assert "first occurrence" in contract
    assert "omit from_status, from_state, and from_tier" in contract


def test_canon_prompt_binds_fact_supersession_to_accepted_canon_event() -> None:
    contract = _stage_semantic_contract("canon_extraction")

    assert "accepted Canon facts" in contract
    assert "source_event_id" in contract
    assert "supersedes_event_id" in contract
    assert "omit the redundant fact" in contract
    assert "Never paraphrase an unchanged accepted fact" in contract


def test_canon_prompt_requires_character_knowledge_precondition_closure() -> None:
    contract = _stage_semantic_contract("canon_extraction")

    assert "requires_fact_ids" in contract
    assert "acquired_fact_ids" in contract
    assert "character-specific epistemic preconditions" in contract
    assert (
        "world-rule availability is not automatically character knowledge"
        in contract.lower()
    )
    assert "never add unsupported knowledge merely to satisfy validation" in contract


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
                        "effective_from_chapter": 1,
                        "supersedes_event_id": None,
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


def test_every_model_stage_schema_is_codex_strict_json_schema_compatible() -> None:
    """Codex strict output schemas must require every declared object property."""

    def assert_strict_object_contract(value: object, *, path: str) -> None:
        if isinstance(value, list):
            for index, item in enumerate(value):
                assert_strict_object_contract(item, path=f"{path}[{index}]")
            return
        if not isinstance(value, dict):
            return
        if value.get("type") == "object":
            properties = value.get("properties")
            assert isinstance(properties, dict), path
            assert set(value.get("required") or ()) == set(properties), path
            assert value.get("additionalProperties") is False, path
        for key, item in value.items():
            assert_strict_object_contract(item, path=f"{path}.{key}")

    for stage in (
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
    ):
        assert_strict_object_contract(
            chapter_provider_output_schema(stage),
            path=f"$.{stage}",
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


def test_schema_validation_supports_nullable_boolean_canon_fields() -> None:
    value = deepcopy(_valid("canon_extraction"))
    change_schema = chapter_provider_output_schema("canon_extraction")["properties"][
        "character_state_changes"
    ]["items"]
    value["character_state_changes"] = [
        {
            key: (
                False
                if key == "resurrection_authorized"
                else None
                if "null" in schema.get("type", [])
                else "character remains alive"
                if key == "summary"
                else "CHARACTER_STATE_CONFIRMED"
                if key == "impact_type"
                else 0
                if key == "evidence_start"
                else 1
                if key == "evidence_end"
                else 0.9
            )
            for key, schema in change_schema["properties"].items()
        }
    ]

    assert validate_chapter_provider_output_schema("canon_extraction", value) == value
    normalized = validate_chapter_provider_output_semantics("canon_extraction", value)
    assert normalized["character_state_changes"][0]["resurrection_authorized"] is False


def test_quality_schema_requires_evidence_for_every_dimension() -> None:
    schema = chapter_provider_output_schema("quality_platform")
    locations = schema["properties"]["dimensions"]["items"]["properties"][
        "evidence_locations"
    ]
    assert locations["minItems"] == 1
    value = deepcopy(_valid("quality_platform"))
    value["dimensions"][0]["evidence_locations"] = []  # type: ignore[index]

    with pytest.raises(KernelError) as raised:
        validate_chapter_provider_output_schema("quality_platform", value)

    assert raised.value.code == "CHAPTER_PROVIDER_OUTPUT_SCHEMA_INVALID"
    assert "at least 1 items" in str(raised.value)


def test_shared_schema_validation_supports_integer_const_and_max_items() -> None:
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "chapter": {"type": "integer", "minimum": 1, "maximum": 3},
            "scope": {"type": "string", "const": "chapter:3"},
            "beats": {
                "type": "array",
                "minItems": 1,
                "maxItems": 2,
                "items": {"type": "string"},
            },
        },
        "required": ["chapter", "scope", "beats"],
        "additionalProperties": False,
    }

    assert (
        validate_chapter_provider_output_against_schema(
            "planning-proof",
            schema,
            {"chapter": 3, "scope": "chapter:3", "beats": ["choice"]},
        )["chapter"]
        == 3
    )
    with pytest.raises(KernelError, match="frozen constant"):
        validate_chapter_provider_output_against_schema(
            "planning-proof",
            schema,
            {"chapter": 3, "scope": "chapter:2", "beats": ["choice"]},
        )


@pytest.mark.parametrize(
    "text",
    (
        '{"stage":"revision","revision_markdown":"reader-facing prose"}',
        "修订后的正文。\n\n## 自检\n所有问题均已处理。",
        "修订后的正文。\n\n## 修订证据引用\n- ISSUE-1",
    ),
)
def test_revision_semantics_rejects_operator_metadata_inside_reader_prose(
    text: str,
) -> None:
    value = {"text": text, "resolved_issue_codes": ["ISSUE-1"]}

    with pytest.raises(KernelError) as raised:
        validate_chapter_provider_output_semantics("revision", value)

    assert raised.value.code == "CHAPTER_PROVIDER_OUTPUT_SEMANTIC_INVALID"


def test_revision_semantics_accepts_clean_reader_facing_prose() -> None:
    value = {
        "text": "她烧掉地图，火光照亮每一名见证人的脸。",
        "resolved_issue_codes": ["COST_NOT_CONCRETE"],
    }

    assert validate_chapter_provider_output_semantics("revision", value) == value


def test_canon_semantics_rejects_contradictory_subject_predicate_slot() -> None:
    value = _valid("canon_extraction")
    value["canon_facts"].append(
        {
            **value["canon_facts"][0],
            "object": "concealed_record",
        }
    )

    with pytest.raises(KernelError) as raised:
        validate_chapter_provider_output_semantics("canon_extraction", value)

    assert raised.value.code == "CHAPTER_PROVIDER_OUTPUT_SEMANTIC_INVALID"


def test_canon_semantics_accepts_exact_duplicate_for_authority_deduplication() -> None:
    value = _valid("canon_extraction")
    value["canon_facts"].append(dict(value["canon_facts"][0]))

    normalized = validate_chapter_provider_output_semantics("canon_extraction", value)

    assert "supersedes_event_id" not in normalized["canon_facts"][0]


def test_revision_schema_tells_provider_text_is_reader_facing_prose_only() -> None:
    text_schema = chapter_provider_output_schema("revision")["properties"]["text"]

    assert "reader-facing" in text_schema["description"]
    assert "metadata" in text_schema["description"]


def test_unsupported_stage_fails_closed() -> None:
    with pytest.raises(KernelError) as raised:
        chapter_provider_output_schema("unknown")

    assert raised.value.code == "CHAPTER_PROVIDER_OUTPUT_SCHEMA_UNSUPPORTED"


def test_provider_schema_has_no_open_object_escape_hatch() -> None:
    def assert_closed(schema: object) -> None:
        if isinstance(schema, dict):
            if schema.get("type") == "object":
                assert schema.get("additionalProperties") is False
                assert set(schema.get("required") or ()).issubset(
                    (schema.get("properties") or {}).keys()
                )
            for child in schema.values():
                assert_closed(child)
        elif isinstance(schema, list):
            for child in schema:
                assert_closed(child)

    for stage in ("canon_extraction", "quality_structural", "reader_outcome"):
        assert_closed(chapter_provider_output_schema(stage))
