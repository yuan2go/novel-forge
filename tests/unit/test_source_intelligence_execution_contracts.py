from __future__ import annotations

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution import default_capability_registry
from novel_forge.modules.source_import.execution import (
    _order_compound_observations,
)
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


def test_actual_reading_manifest_uses_materialized_bytes_and_context_roles():
    from novel_forge.modules.source_import.corpus_ingestion.reading_evidence import (
        materialized_input_manifest,
    )

    inputs = {
        "source_segments": [
            {"source_chunk_asset_version_id": "chunk:v2", "content": "甲乙"}
        ],
        "reading_context": {
            "reading_identity": "reading:1",
            "unit_versions": ["unit:v2"],
        },
        "review_target": {"observation": {"findings": []}},
    }
    manifest = materialized_input_manifest(
        inputs, {"input_text_hash": "request-hash"}, {"prompt": "v2"}
    )
    assert manifest["actual_text_inputs"][0]["byte_end"] == 6
    assert manifest["actual_text_inputs"][0]["content_hash"].startswith("sha256:")
    assert manifest["context_roles"]["review_target"].startswith("sha256:")
    assert "甲乙" not in str(manifest)
    aggregate = materialized_input_manifest(
        {"input_observations": [{"asset_version_id": "obs:1", "observation": {}}]},
        {},
        {},
    )
    assert aggregate["actual_text_inputs"] == []
    assert aggregate["lower_observation_inputs"] == ["obs:1"]


def test_failed_and_unconfirmed_reading_receipts_do_not_share_coverage():
    from novel_forge.modules.source_import.corpus_ingestion.reading_evidence import (
        receipt_input_evidence,
    )

    payload = {
        "narrative_reading": {
            "identity": "reading",
            "processing_id": "processing",
            "units": [],
        }
    }
    manifest = {
        "actual_text_inputs": [{"source_chunk_asset_version_id": "sent"}],
        "target_units": ["unit"],
    }
    for status in ("PREPARED", "PLANNED", "UNKNOWN", "RECONCILIATION_REQUIRED"):
        value = receipt_input_evidence(
            [{"manifest": manifest, "status": status}], payload
        )
        assert value["coverage"]["actual_text_inputs"] == []
    returned = receipt_input_evidence(
        [
            {
                "manifest": manifest,
                "returned": True,
                "status": "SUCCEEDED",
                "reused": True,
            }
        ],
        payload,
    )
    assert returned["coverage"]["actual_text_inputs"] == manifest["actual_text_inputs"]
    assert returned["input_receipts"][0]["reused"]
    old = receipt_input_evidence([{"returned": True, "status": "SUCCEEDED"}], payload)
    assert old["coverage"]["input_state"] == "NOT_RECORDED"
    assert old["coverage"]["actual_text_inputs"] == []
    legacy_timeout = receipt_input_evidence(
        [{"manifest": manifest, "status": "FAILED_RETRYABLE", "external_state_unknown": True}], payload
    )
    assert legacy_timeout["input_receipts"][0]["state"] == "UNKNOWN"
    assert legacy_timeout["coverage"]["actual_text_inputs"] == []


def test_frozen_target_denominator_includes_missing_empty_and_blocked_units():
    from novel_forge.modules.source_import.corpus_ingestion.reading_progress import (
        target_progress,
    )

    plans = {
        "p": {
            "identity": "reading",
            "processing_id": "p",
            "units": [
                {"source_unit_version_id": f"unit:{i}", "ordinal": i, "role": "TARGET"}
                for i in range(3)
            ],
        }
    }
    rows = [
        {
            "reading_identity": "reading",
            "unit_index": "0",
            "phase": "OBSERVE",
            "operation_id": "o",
            "status": "SUCCEEDED",
            "input_state": "CONFIRMED_RETURNED",
        },
        {
            "reading_identity": "reading",
            "unit_index": "0",
            "phase": "REVIEW",
            "operation_id": "r",
            "status": "SUCCEEDED",
            "decision": "ACCEPT_IN_SCOPE",
            "semantic_evidence": "AGENT_REVIEW_ONLY",
            "has_observation": False,
        },
        {
            "reading_identity": "reading",
            "unit_index": "1",
            "phase": "REVIEW",
            "operation_id": "b",
            "status": "BLOCKED",
            "decision": "NEEDS_REVIEW",
        },
    ]
    result = target_progress(plans, rows)
    assert result["target_units"] == 3
    assert result["processed_target_units"] == 1
    assert result["no_applicable_findings"] == 1
    assert not result["coverage_complete"]
    assert [t["status"] for t in result["target_outcomes"]] == [
        "NO_APPLICABLE_FINDINGS",
        "NEEDS_REVIEW",
        "NOT_EXPANDED",
    ]
    assert target_progress(plans, rows + rows)["processed_target_units"] == 1


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


def _properties_without_explicit_type(
    schema: object, *, path: tuple[str, ...] = ()
) -> list[str]:
    if isinstance(schema, list):
        return [
            missing
            for index, item in enumerate(schema)
            for missing in _properties_without_explicit_type(
                item, path=(*path, str(index))
            )
        ]
    if not isinstance(schema, dict):
        return []
    missing = []
    properties = schema.get("properties")
    if isinstance(properties, dict):
        missing.extend(
            ".".join((*path, "properties", str(name)))
            for name, value in properties.items()
            if not isinstance(value, dict) or "type" not in value
        )
    for name, value in schema.items():
        missing.extend(
            _properties_without_explicit_type(value, path=(*path, str(name)))
        )
    return missing


def test_codex_source_output_schemas_type_every_declared_property() -> None:
    from novel_forge.modules.production_execution.codex_configuration import codex_output_schema
    from novel_forge.modules.source_import.corpus_ingestion.narrative_contracts import narrative_schema, review_schema

    schemas = (
        content_intelligence_output_schema(CLASSIFICATION_STAGE),
        content_intelligence_output_schema(DECONSTRUCTION_STAGE),
        content_intelligence_output_schema(MKAOS_STAGE),
        compound_deconstruction_output_schema(),
        narrative_schema(), review_schema(),
    )
    assert [
        missing
        for schema in schemas
        for missing in _properties_without_explicit_type(codex_output_schema(schema))
    ] == []
    assert narrative_schema()["properties"]["knowledge_status"] == {"const": "NOT_ABSTRACTED"}
    for value, expected in [(True, "boolean"), (3, "integer"), (0.5, "number"), (None, "null")]:
        assert codex_output_schema({"const": value})["type"] == expected



def test_source_content_classification_is_registered_and_bounded() -> None:
    definition = default_capability_registry().resolve("source.content.classify")
    assert definition.domain.value == "source"
    schema = content_intelligence_output_schema(CLASSIFICATION_STAGE)
    assert schema["additionalProperties"] is False
    assert schema["properties"]["alternatives"]["maxItems"] == 5
    assert (
        "including content_type" in schema["properties"]["alternatives"]["description"]
    )


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


def test_compound_deconstruction_canonicalizes_provider_dimension_order() -> None:
    observations = [
        {"dimension": "structure"},
        {"dimension": "pacing"},
        {"dimension": "conflict"},
    ]

    ordered = _order_compound_observations(
        observations,
        requested_dimensions=("structure", "conflict", "pacing"),
    )

    assert [item["dimension"] for item in ordered] == [
        "structure",
        "conflict",
        "pacing",
    ]
    with pytest.raises(
        KernelError, match="SOURCE_COMPOUND_ANALYSIS_DIMENSION_MISMATCH"
    ):
        _order_compound_observations(
            observations,
            requested_dimensions=("structure", "conflict", "chapter_hook"),
        )


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


def test_bounded_narrative_evidence_and_blocker_continuity():
    import copy
    import pytest
    from novel_forge.modules.command_kernel.errors import KernelError
    from novel_forge.modules.source_import.corpus_ingestion.narrative_contracts import (
        narrative_schema,
        review_schema,
        validate_narrative,
        reconcile_review,
    )
    from novel_forge.modules.source_import.execution_contracts import (
        validate_content_intelligence_output,
        DECONSTRUCTION_STAGE,
    )

    raw = "她收到密信。她相信城门仍开着，但叙述者没有确认。"
    output = {
        "findings": [
            {
                "finding_code": "belief",
                "statement": "The actor believes the gate is open; objective confirmation is unknown.",
                "dimension": "information_gap",
                "certainty": "TEXT_EXPLICIT",
                "perspective": "CHARACTER_BELIEF",
                "entity_ids": ["actor"],
                "caused_by": [],
                "causal_basis": "",
                "details": {
                    k: "UNKNOWN"
                    for k in (
                        "preconditions",
                        "action_or_change",
                        "choice",
                        "cost",
                        "outcome",
                        "information_basis",
                        "scope_boundary",
                    )
                },
                "supports": [
                    {
                        "chunk_id": "c1",
                        "byte_start": 0,
                        "byte_end": len(raw.encode()),
                        "support_text": raw,
                    }
                ],
                "input_observation_asset_version_ids": [],
            }
        ],
        "entities": [{"entity_id": "actor", "role": "recipient"}],
        "confidence": 0.7,
        "knowledge_status": "NOT_ABSTRACTED",
        "scope_limitations": "No later chapter has been read.",
    }
    segments = ({"source_chunk_asset_version_id": "c1", "content": raw},)
    validate_content_intelligence_output(
        DECONSTRUCTION_STAGE, narrative_schema(), output
    )
    observed, spans = validate_narrative(
        output, segments=segments, lower_ids=(), dimensions=["information_gap"]
    )
    assert len(spans) == 1 and "supports" not in observed["findings"][0]
    assert observed["findings"][0]["perspective"] == "CHARACTER_BELIEF"
    assert observed["findings"][0]["evidence_span_ids"] == [spans[0].evidence_span_id]
    for mutation, code in (
        ({"chunk_id": "outside"}, "OUT_OF_SCOPE"),
        ({"byte_start": 1}, "UTF8_BOUNDARY"),
        ({"support_text": "城门已经打开。"}, "TEXT_MISMATCH"),
        ({"byte_end": len(raw.encode()) + 1}, "OUT_OF_SCOPE"),
    ):
        changed = copy.deepcopy(output)
        changed["findings"][0]["supports"][0].update(mutation)
        with pytest.raises(KernelError, match=code):
            validate_narrative(
                changed, segments=segments, lower_ids=(), dimensions=["information_gap"]
            )
    for field, value, code in (
        ("entity_ids", ["invented"], "REFERENCE_INVALID"),
        ("caused_by", ["belief"], "CAUSAL_REFERENCE_INVALID"),
        (
            "input_observation_asset_version_ids",
            ["other-project"],
            "LOWER_OBSERVATION_INVALID",
        ),
    ):
        changed = copy.deepcopy(output)
        changed["findings"][0][field] = value
        with pytest.raises(KernelError, match=code):
            validate_narrative(
                changed, segments=segments, lower_ids=(), dimensions=["information_gap"]
            )
    issue = {
        "issue_id": "knowledge",
        "finding_code": "belief",
        "category": "EPISTEMIC_CONFUSION",
        "severity": "BLOCKING",
        "reason": "Belief does not confirm objective state.",
        "repair_goal": "Preserve uncertainty.",
        "acceptance_condition": "No objective claim without evidence.",
    }
    review = {
        "decision": "ACCEPT_IN_SCOPE",
        "issues": [],
        "resolved_issue_ids": [],
        "preserve_requirements": [],
        "scope_limitations": "Agent review only.",
    }
    validate_content_intelligence_output(DECONSTRUCTION_STAGE, review_schema(), review)
    with pytest.raises(KernelError, match="UNRESOLVED_BLOCKERS"):
        reconcile_review(review, [issue], {"belief"})
    with pytest.raises(KernelError, match="UNDECLARED_RESOLUTION"):
        reconcile_review(
            {**review, "issues": [{**issue, "severity": "ADVISORY"}]},
            [issue],
            {"belief"},
        )
    with pytest.raises(KernelError, match="IDENTITY_DUPLICATE"):
        reconcile_review(
            {**review, "issues": [issue, {**issue, "severity": "ADVISORY"}]},
            [],
            {"belief"},
        )
    assert (
        reconcile_review(
            {**review, "resolved_issue_ids": ["knowledge"]}, [issue], {"belief"}
        )
        == []
    )
    with pytest.raises(KernelError, match="FINDING_DROPPED"):
        reconcile_review(
            {**review, "resolved_issue_ids": ["knowledge"]}, [issue], set()
        )
    with pytest.raises(KernelError, match="UNKNOWN_RESOLUTION"):
        reconcile_review(
            {**review, "resolved_issue_ids": ["invented"]}, [issue], {"belief"}
        )
    empty = {**output, "findings": [], "entities": []}
    validate_content_intelligence_output(
        DECONSTRUCTION_STAGE, narrative_schema(), empty
    )
    assert validate_narrative(
        empty, segments=segments, lower_ids=(), dimensions=["information_gap"]
    ) == (empty, ())


def test_recorded_usage_requires_observed_nonnegative_integer_counts():
    from novel_forge.modules.source_import.execution import _recorded_token_usage

    assert _recorded_token_usage({"total_tokens": 0}) == 0
    assert _recorded_token_usage({"input_tokens": 14, "output_tokens": 3}) == 17
    for usage in ({}, {"total_tokens": None}, {"total_tokens": True},
                  {"total_tokens": -1}, {"input_tokens": 4},
                  {"total_tokens": 0, "availability": "UNAVAILABLE"}):
        assert _recorded_token_usage(usage) is None


def test_source_local_timeout_is_unknown_remote_outcome():
    from novel_forge.modules.source_import.execution import _source_gateway_provider_result
    from novel_forge.modules.production_execution import ExecutionOutcome, ExecutionRuntimeClass

    class Contract:
        def __init__(self, **values):
            self.__dict__.update(values)
        def to_dict(self):
            return {}

    binding = Contract(request=Contract(execution_id="fixture-timeout"),
        route_snapshot=Contract(model_provider="codex-cli", model_id="fixture-model"),
        input_manifest=Contract(prompt_bundle_version="1", skill_bundle_version="1"))
    record = Contract(raw_evidence={}, process_receipt=Contract(local_termination_only=True))
    session = Contract(evidence_store=Contract(get_record=lambda _:record))
    handle = Contract(transport=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
        backend_execution_id="fixture-execution", provider_request_id=None)
    for outcome in (ExecutionOutcome.TIMED_OUT, ExecutionOutcome.CANCELLED):
        result = Contract(outcome=outcome, started_at="2026-09-11T00:00:00Z", normalized_output_ref=None, usage_receipt_ref=None,
            cost_receipt_ref=None, raw_output_ref=None)
        adapted = _source_gateway_provider_result(binding=binding, session=session, handle=handle, result=result)
        assert adapted.outcome == "unknown"
        assert adapted.evidence["external_state_unknown"] is True

    result.started_at = None
    adapted = _source_gateway_provider_result(binding=binding, session=session, handle=handle, result=result)
    assert adapted.outcome == "cancelled"
