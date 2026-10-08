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


@pytest.mark.parametrize("owner", ["classification", "deconstruction", "knowledge"])
def test_benchmark_execution_cannot_be_committed_by_source_or_knowledge_authority(owner):
    from novel_forge.modules.source_authority.profiling_application import _classification_execution_binding
    from novel_forge.modules.source_authority.deconstruction_application import _execution_proof as observation_proof
    from novel_forge.modules.mkaos_authority.application import _execution_proof as knowledge_proof

    content = {"qualification_status": "BENCHMARK_ONLY", "production_execution_gateway_backed": True,
               "real_provider_proven": True, "production_verified": True}
    with pytest.raises(KernelError, match="SOURCE_BENCHMARK_CANNOT_COMMIT"):
        if owner == "classification":
            _classification_execution_binding({"content": content}, evidence_class="PROVIDER_QUALIFIED",
                scope_hash="scope", classifier_contract_hash="classifier", classification_input_hash="input",
                classification_output_hash="output", allow_fixture=False)
        elif owner == "deconstruction":
            observation_proof(content, evidence_class="PROVIDER_QUALIFIED")
        else:
            knowledge_proof(content)


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
    from novel_forge.modules.source_import.corpus_ingestion.narrative_contracts import narrative_schema, review_schema, mechanism_observation_schema
    from novel_forge.modules.source_import.execution_contracts import grounded_knowledge_output_schema

    schemas = (
        content_intelligence_output_schema(CLASSIFICATION_STAGE),
        content_intelligence_output_schema(DECONSTRUCTION_STAGE),
        content_intelligence_output_schema(MKAOS_STAGE),
        compound_deconstruction_output_schema(),
        narrative_schema(), review_schema(), mechanism_observation_schema(),
        grounded_knowledge_output_schema(),
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


@pytest.mark.parametrize("stage,inputs,quotes", [
    (DECONSTRUCTION_STAGE, {"reading_context": {"dimensions": ["character_choice_cost"]}, "source_segments": [{"text": "research"}]}, True),
    (DECONSTRUCTION_STAGE, {"reading_context": {"phase": "REVIEW"}, "source_segments": [{"text": "research"}], "review_target": {}}, False),
    (DECONSTRUCTION_STAGE, {"reading_context": {"phase": "SYNTHESIZE"}, "input_observations": [{}]}, False),
    (CLASSIFICATION_STAGE, {"classification_samples": [{"content": "research"}]}, False),
    (MKAOS_STAGE, {"input_observations": [{}]}, False),
])
def test_actual_source_prompt_separates_exact_research_evidence_from_abstraction(stage, inputs, quotes):
    from hashlib import sha256
    from types import SimpleNamespace
    from novel_forge.modules.source_import.execution import PostgresContentIntelligenceExecutionPort
    from novel_forge.modules.chapter_authority.execution_gateway import _materialize_source_intelligence_prompt

    spec = SimpleNamespace(stage=stage, input_payload=inputs, methodology_content="Governed methodology",
        methodology_content_hash="sha256:" + sha256(b"Governed methodology").hexdigest(),
        capability="deconstruction.observe" if stage == DECONSTRUCTION_STAGE else "source.content.classify" if stage == CLASSIFICATION_STAGE else "mkaos.knowledge.extract",
        prompt_id="source.contract", prompt_version="2.0.0", skill_id="source.skill", skill_version="1.0",
        output_schema={"type": "object", "properties": {}})
    materialization = PostgresContentIntelligenceExecutionPort._materialization(None, spec)
    prompt, evidence = _materialize_source_intelligence_prompt(
        target_scope={"scope_kind": "chapter", "scope_id": "s", "project_id": "p", "book_id": "source-corpus:p"},
        stage=stage, inputs=inputs, materialization=materialization)
    assert ("supports[].support_text" in prompt) == quotes
    assert ("Do not quote, reproduce, or preserve source expression" in prompt) != quotes
    assert evidence["source_bytes_persisted_in_external_effect"] is False
    assert evidence["system_instruction"]["version"] == "1.1"
    assert materialization["source_isolation"]["raw_source_allowed_in_generation_context"] is False


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


def test_bounded_reading_delivers_frozen_neighbors_without_promoting_targets(monkeypatch):
    from types import SimpleNamespace
    from novel_forge.modules.source_authority.deconstruction import default_analyzer_contracts
    from novel_forge.modules.source_import.corpus_ingestion import narrative_execution as execution
    from novel_forge.modules.source_import.corpus_ingestion.runtime import CorpusIngestionRuntime

    units = [
        {"source_unit_version_id": f"unit:{i}", "ordinal": i,
         "role": "TARGET" if i in (1, 2) else "ALLOWED_CONTEXT"}
        for i in range(4)
    ]
    plan = {"identity": "frozen", "units": units,
            "contract": {"context_before": 1, "context_after": 1}}
    payload = {"narrative_reading": plan, "unit_index": 0,
               "source_document_id": "source:1",
               "analyzer": default_analyzer_contracts()["conflict"].to_dict()}
    monkeypatch.setattr(CorpusIngestionRuntime, "_load", lambda *_: ({"status": "RUNNING"}, {}, None))
    monkeypatch.setattr(execution, "curated_provider_gate", lambda *_: None)
    delivered = []
    class InputCaptured(Exception):
        pass
    def capture(app, worker, selected):
        delivered.extend(selected)
        raise InputCaptured()
    monkeypatch.setattr(execution, "_source_inputs", capture)
    with pytest.raises(InputCaptured):
        execution.execute_reading(SimpleNamespace(database_url="unused", _require_execution_port=lambda: None), None, payload)
    assert [u["source_unit_version_id"] for u in delivered] == ["unit:0", "unit:1", "unit:2"]
    assert [u["role"] for u in delivered] == ["ALLOWED_CONTEXT", "TARGET", "ALLOWED_CONTEXT"]
    assert units[2]["role"] == "TARGET"


def test_delivered_neighbor_receipt_counts_only_target_coverage():
    from novel_forge.modules.source_import.corpus_ingestion.reading_evidence import materialized_input_manifest, receipt_input_evidence

    bindings = [
        {"source_unit_version_id": "neighbor", "role": "ALLOWED_CONTEXT", "chunk_ranges": [
            {"source_chunk_asset_version_id": "c0", "byte_start": 0, "byte_end": 3}]},
        {"source_unit_version_id": "target", "role": "TARGET", "chunk_ranges": [
            {"source_chunk_asset_version_id": "c1", "byte_start": 0, "byte_end": 3}]},
    ]
    inputs = {"source_segments": [{"source_chunk_asset_version_id": "c0", "content": "甲"}, {"source_chunk_asset_version_id": "c1", "content": "乙"}],
              "reading_context": {"reading_identity": "frozen", "unit_versions": ["neighbor", "target"], "unit_bindings": bindings}}
    manifest = materialized_input_manifest(inputs, {}, {})
    assert manifest["target_units"] == ["target"]
    assert manifest["supporting_units"] == ["neighbor"]
    assert [s["role"] for s in manifest["actual_text_inputs"]] == ["SUPPORTING_CONTEXT", "TARGET_TEXT"]
    assert manifest["actual_text_inputs"][0]["unit_ranges"][0]["source_unit_version_id"] == "neighbor"
    result = receipt_input_evidence([{"manifest": manifest, "returned": True}], {"narrative_reading": {"identity": "frozen", "processing_id": "p", "units": bindings}})
    assert result["coverage"]["allowed_context_not_read"] == []


def test_empty_observation_retains_bounded_evidence_without_forcing_knowledge():
    from novel_forge.modules.source_authority.deconstruction import ObservationEvidenceSpan, validate_observation_payload
    payload = {"findings": [], "confidence": 0.0, "knowledge_status": "NOT_ABSTRACTED",
               "scope_limitations": "No supported mechanism in the actual supplied section."}
    span = ObservationEvidenceSpan("chunk:v1", 0, 3, "sha256:" + "a" * 64)
    assert validate_observation_payload(payload, evidence_spans=(span,)) == payload
    with pytest.raises(KernelError):
        validate_observation_payload({**payload, "scope_limitations": ""}, evidence_spans=(span,))


def test_mechanism_observation_preserves_conditions_and_uncertainty():
    from novel_forge.modules.source_import.corpus_ingestion.narrative_contracts import (
        mechanism_observation_schema, validate_narrative, validate_abstraction_lineage,
    )
    text = "Only a sealed vessel retains pressure; an open vent defeats this mechanism."
    inputs = {"observation_contract": {"version": "v2"}, "analyzer": {"dimension": "causal_constraints"},
              "source_segments": [{"source_chunk_asset_version_id": "chunk:v3", "content": text}]}
    output = content_intelligence_fixture_response(DECONSTRUCTION_STAGE, inputs)
    finding = output["findings"][0]
    finding["certainty"] = "TEXT_EXPLICIT"
    finding["details"].update(mechanism="Enclosure retains pressure", preconditions="Vessel is sealed", exceptions="An open vent", failure_conditions="Seal breaks", misuse_risks="Assuming an open vessel is pressurized")
    validate_content_intelligence_output(DECONSTRUCTION_STAGE, mechanism_observation_schema(), output)
    observed, spans = validate_narrative(output, segments=tuple(inputs["source_segments"]), lower_ids=(), dimensions=["causal_constraints"])
    assert observed["findings"][0]["details"]["exceptions"] == "An open vent"
    assert spans[0].chunk_byte_end == len(text.encode())
    assert "supports" not in observed["findings"][0]
    candidate = {"source_finding_codes": [finding["finding_code"]], "epistemic_status": "SUPPORTED_INFERENCE"}
    validate_abstraction_lineage(candidate, observed)
    observed["findings"][0]["certainty"] = "HYPOTHESIS"
    with pytest.raises(KernelError, match="SOURCE_ABSTRACTION_EPISTEMIC_PROMOTION"):
        validate_abstraction_lineage(candidate, observed)
    with pytest.raises(KernelError, match="SOURCE_ABSTRACTION_FINDING_UNKNOWN"):
        validate_abstraction_lineage({**candidate, "source_finding_codes": ["unread"]}, observed)


def test_neighbor_evidence_cannot_be_counted_as_target_observation():
    from novel_forge.modules.source_import.corpus_ingestion.narrative_contracts import validate_narrative
    inputs = {"observation_contract": {}, "analyzer": {"dimension": "causal_constraints"},
              "source_segments": [{"source_chunk_asset_version_id": "neighbor", "content": "甲"}]}
    inputs["observation_contract"] = {"version": "v2"}
    output = content_intelligence_fixture_response(DECONSTRUCTION_STAGE, inputs)
    bindings = ({"source_unit_version_id": "unit:v1", "role": "ALLOWED_CONTEXT", "chunk_ranges": [{"source_chunk_asset_version_id": "neighbor", "byte_start": 0, "byte_end": 3}]},)
    with pytest.raises(KernelError, match="NARRATIVE_TARGET_SUPPORT_REQUIRED"):
        validate_narrative(output, segments=tuple(inputs["source_segments"]), lower_ids=(), dimensions=["causal_constraints"], unit_bindings=bindings)
    bindings = ({**bindings[0], "role": "TARGET"},)
    observed, _ = validate_narrative(output, segments=tuple(inputs["source_segments"]), lower_ids=(), dimensions=["causal_constraints"], unit_bindings=bindings)
    assert observed["findings"][0]["source_unit_evidence"][0]["source_unit_version_id"] == "unit:v1"


def test_strict_projection_empty_optional_lineage_normalizes_without_weakening_evidence():
    from novel_forge.modules.source_import.execution_contracts import content_intelligence_output_schema, validate_content_intelligence_output, DECONSTRUCTION_STAGE
    value={'findings':[{'finding_code':'mechanism','statement':'conditional inference','evidence_span_ids':['chapter:1'],'input_observation_asset_version_ids':[]}],'confidence':0.7,'knowledge_status':'NOT_ABSTRACTED'}
    result=validate_content_intelligence_output(DECONSTRUCTION_STAGE,content_intelligence_output_schema(DECONSTRUCTION_STAGE),value)
    assert result['findings'][0]['evidence_span_ids']==['chapter:1']
    assert 'input_observation_asset_version_ids' not in result['findings'][0]
    assert value['findings'][0]['input_observation_asset_version_ids']==[]
    for changes in ({'evidence_span_ids':[]},{'input_observation_asset_version_ids':['observation:1']}):
        with pytest.raises(ValueError):
            validate_content_intelligence_output(DECONSTRUCTION_STAGE,content_intelligence_output_schema(DECONSTRUCTION_STAGE),{**value,'findings':[{**value['findings'][0],**changes}]})


@pytest.mark.parametrize("receipt", [None, {"reused_external_effect_id": "other"}, {"reused_external_effect_id": "original"}])
def test_completion_recovery_reuses_only_exact_receipt_without_dispatch(monkeypatch, receipt):
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from novel_forge.modules.source_import.execution import PostgresContentIntelligenceExecutionPort
    from novel_forge.modules.command_kernel.errors import KernelError
    import novel_forge.modules.source_import.execution as module
    from novel_forge.storage.source_authority_repositories import SourceAuthorityRepository
    from novel_forge.modules.command_kernel import routing_bootstrap

    monkeypatch.setattr(module, "AuthorityUnitOfWork", MagicMock())
    monkeypatch.setattr(SourceAuthorityRepository, "catalog_execution_binding", lambda *a: None)
    monkeypatch.setattr(routing_bootstrap, "load_bootstrap_authorization", lambda *a, **k: None)
    port = object.__new__(PostgresContentIntelligenceExecutionPort)
    port.database_url = "fixture:no-database"
    port._replay_succeeded_effect = MagicMock(return_value=receipt)
    port.transport = MagicMock()
    spec = SimpleNamespace(stage="deconstruction", capability="deconstruction.observe",
        methodology_content_hash="fixture", input_payload={}, context_contract={})
    worker = SimpleNamespace(project_id="fixture-project", causation_id="fixture-operation")
    if receipt and receipt["reused_external_effect_id"] == "original":
        assert port._execute(worker=worker, spec=spec, reuse_effect_id="original") == receipt
    else:
        with pytest.raises(KernelError, match="SOURCE_COMPLETION_RECOVERY_RECEIPT_MISMATCH"):
            port._execute(worker=worker, spec=spec, reuse_effect_id="original")
    assert port.transport.mock_calls == []


@pytest.mark.parametrize("effect_status,operation_status,chained", [
    ("UNKNOWN", "FAILED_FINAL", False), ("SUCCEEDED", "CANCELLED", False),
    ("SUCCEEDED", "FAILED_FINAL", True), ("SUCCEEDED", "FAILED_FINAL", False),
])
def test_completion_recovery_admission_rejects_unknown_terminal_changes_and_chains(monkeypatch, effect_status, operation_status, chained):
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from novel_forge.modules.source_import.corpus_ingestion import reading_recovery as module

    payload = {"phase": "REVIEW", "narrative_reading": {"identity": "fixture"}}
    if chained:
        payload["completion_recovery"] = {"source_operation_id": "earlier"}
    repository = MagicMock()
    repository.frozen_operation.return_value = {"name": "source.import.deconstruction.execute", "payload": payload}
    repository.work_by_operation.return_value = {"status": "FAILED_FINAL", "failure": {"code": "PROGRAMMING_BUG"}, "import_job_id": "fixture-job"}
    repository.job.return_value = {"status": "PROCESSING"}
    monkeypatch.setattr(module, "SourceImportRepository", lambda *a: repository)
    monkeypatch.setattr(module, "require_curated_operation_current", lambda *a: None)
    uow = MagicMock()
    uow.cursor.fetchone.return_value = (operation_status,)
    uow.cursor.fetchall.return_value = [("original-effect", effect_status, "deconstruction.observe", "fixture-cache")]
    if effect_status == "SUCCEEDED" and operation_status == "FAILED_FINAL" and not chained:
        assert module._completed_stage_source(SimpleNamespace(), uow, "fixture-project", "original")[2] == "original-effect"
    else:
        with pytest.raises(KernelError, match="SOURCE_COMPLETION_RECOVERY_NOT_ELIGIBLE"):
            module._completed_stage_source(SimpleNamespace(), uow, "fixture-project", "original")
