import pytest
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.canon_graph.source_spans import bind_source_spans, source_spans
from novel_forge.modules.chapter_authority.quality_correction_control import require_next_pass
from novel_forge.modules.revision.domain import retain_reviewed_draft, reuse_unchanged_review
from novel_forge.modules.review.diagnostics import prose_hash


def test_source_span_from_different_candidate_cannot_be_rebound():
    source = source_spans("他看见门开了。")
    output = {"canon_facts": [{"evidence_span_id": source["spans"][0]["span_id"]}]}
    with pytest.raises(KernelError, match="CANON_SOURCE_SPAN_INVALID"):
        bind_source_spans(output, "门一直关闭。")
    bound = bind_source_spans(output, "他看见门开了。")
    assert bound["canon_facts"][0]["evidence_quote"] == source["spans"][0]["quote"]
    assert "evidence_span_id" in output["canon_facts"][0]


def test_quality_pass_bound_and_no_progress_remain_separate_guards():
    control = {"maximum_passes": 3, "maximum_unchanged_candidates": 2}
    require_next_pass(completed_passes=1, candidate_hashes=["a", "b"], control=control)
    with pytest.raises(KernelError, match="QUALITY_CORRECTION_CONTROL_EXHAUSTED"):
        require_next_pass(completed_passes=3, candidate_hashes=["a", "b", "c"], control=control)
    with pytest.raises(KernelError, match="QUALITY_CORRECTION_NO_PROGRESS"):
        require_next_pass(completed_passes=2, candidate_hashes=["a", "a", "a"], control=control)


def test_unchanged_review_reuse_rejects_changed_text_and_stale_context():
    draft = {"text": "门开了。"}
    review = {"review_decision_contract": "work-review-decision.v1", "decision": "PASSED",
        "score": 90, "issues": [], "target_asset_version_id": "draft", "context_bundle_version_id": "context",
        "target_text_hash": prose_hash(draft["text"])}
    arguments = dict(draft=draft, draft_id="draft", draft_hash="draft-hash", review=review,
        review_id="review", review_hash="review-hash", context_id="context", context_hash="context-hash")
    retained = retain_reviewed_draft(**arguments)
    assert retained["revision_execution_decision"]["provider_dispatches"] == 0
    reused = reuse_unchanged_review(**arguments, revision=retained, revision_id="revision")
    assert reused["revision_quality_delta"]["score_delta"] == 0
    with pytest.raises(KernelError, match="REREVIEW_RETENTION_DRIFT"):
        reuse_unchanged_review(**arguments, revision={**retained, "text": "门关闭了。"}, revision_id="revision")
    with pytest.raises(KernelError, match="REVISION_DIAGNOSIS_STALE"):
        retain_reviewed_draft(**{**arguments, "context_id": "different-context"})


def test_objective_length_cannot_admit_other_fixture_dimensions():
    from tests.unit.test_creative_quality_admission import groups
    from novel_forge.modules.chapter_quality_authority.creative_validation import assess_coordinated_internal_quality
    reports = groups()
    row = next(row for group in reports for row in group["dimensions"] if row["dimension"] == "readability")
    row.update(fixture=True, calibration_status="FIXTURE_UNCALIBRATED")
    constraint = {"dimension": "chapter_length", "status": "PASSED", "target_asset_version_id": "draft"}
    result = assess_coordinated_internal_quality(groups=reports, target="draft", work_constraints=[constraint])
    assert result["version"] == "creative-quality-admission.v3"
    assert result["status"] == "BLOCKED"
    assert "readability" in result["blocked_dimensions"]
    assert result["strict_certification_eligible"] is False
    assert result["literary_qualification"] == "NOT_RUN"
    with pytest.raises(KernelError, match="VALIDATION_QUALITY_SCOPE_MISMATCH"):
        assess_coordinated_internal_quality(groups=reports, target="draft",
            work_constraints=[{**constraint, "target_asset_version_id": "forged"}])
    with pytest.raises(KernelError, match="VALIDATION_QUALITY_SCOPE_MISMATCH"):
        assess_coordinated_internal_quality(groups=reports, target="draft",
            work_constraints=[{**constraint, "dimension": "readability"}])


def test_retained_receipt_uses_exact_kernel_operation_scope(monkeypatch):
    from novel_forge.modules.chapter_authority import receipt_recovery
    class Cursor:
        def execute(self, *args):
            pass
        def fetchone(self):
            return ("actor", "trace", "correlation", "FAILED_FINAL")
    class Repository:
        def get_for_update(self, effect_id):
            return {"project_id": "project", "operation_id": "another-operation", "status": "SUCCEEDED"}
    monkeypatch.setattr(receipt_recovery, "ExternalEffectRepository", lambda cursor: Repository())
    with pytest.raises(KernelError, match="EFFECT_OPERATION_CONFLICT"):
        receipt_recovery._receipt(Cursor(), "effect", "project", source_operation_id="original-operation")


def test_retained_receipt_rejects_provider_evidence_hash_drift(monkeypatch):
    from novel_forge.modules.chapter_authority import receipt_recovery
    from novel_forge.modules.command_kernel import external_effect_runtime
    class Cursor:
        def __init__(self):
            self.rows = iter([("actor", "trace", "correlation", "FAILED_FINAL"),
                (1, {"result": "retained"}, "sha256:forged", {"evidence": {"result": "retained"}}, "VERIFIED")])
        def execute(self, *args):
            pass
        def fetchone(self):
            return next(self.rows)
    class Repository:
        def get_for_update(self, effect_id):
            return {"project_id": "project", "operation_id": "original-operation", "status": "SUCCEEDED"}
    monkeypatch.setattr(receipt_recovery, "ExternalEffectRepository", lambda cursor: Repository())
    monkeypatch.setattr(external_effect_runtime, "_validated_frozen_provider_capability_profile", lambda effect: {})
    with pytest.raises(KernelError, match="EFFECT_SUCCESS_RECEIPT_INVALID"):
        receipt_recovery._receipt(Cursor(), "effect", "project", source_operation_id="original-operation")


def test_reader_disclosure_lineage_cannot_authorize_world_state():
    from novel_forge.modules.canon_graph.world_reconciliation import bind_world_event_lineage, _validate_world_actual
    evidence = {"source_revision_asset_version_id": "candidate", "excerpt_digest": "exact-digest",
        "span": {"start": 0, "end": 3}}
    changes = {"disclosure_event": [{"story_time": {"tick": 1}, "extraction_evidence": evidence}]}
    bind_world_event_lineage(changes, reader_observation_lineage=True)
    change = changes["disclosure_event"][0]
    assert change["causality"]["cause_refs"] == ["observed:candidate:0:3"]
    assert change["reader_observation_lineage"]["source_revision_asset_version_id"] == "candidate"
    with pytest.raises(KernelError, match="READER_DISCLOSURE_SCOPE_INVALID"):
        _validate_world_actual({"state_kind": "world_state", "mutation": {"payload": change}}, {}, known_causes=set())


def test_quality_spans_preserve_frozen_applicability_and_exact_candidate():
    from novel_forge.modules.chapter_authority.provider_output_contracts import chapter_provider_output_schema, inline_shared_canon_schema
    from novel_forge.modules.chapter_quality_authority.applicability_contract import bind_quality_applicability_schema
    from novel_forge.modules.canon_graph.source_spans import bind_quality_applicability_spans, bind_quality_spans
    schema = chapter_provider_output_schema("quality_platform", work_requirements=True)
    baseline = {"method_requirements": {"chapter_length": {"status": "PROHIBITED"}}}
    schema = bind_quality_applicability_schema(schema, baseline, "platform")
    table = source_spans("他走进房间。")
    current = inline_shared_canon_schema(bind_quality_applicability_spans(schema, table))
    row = next(row for row in current["properties"]["dimensions"]["items"]["anyOf"]
        if row["properties"]["dimension"]["enum"] == ["chapter_length"])
    assert row["properties"]["gate_status"]["enum"] == ["NOT_APPLICABLE"]
    assert row["properties"]["score"] == {"type": "null"}
    assert row["properties"]["evidence_locations"]["maxItems"] == 0
    located = bind_quality_spans([{"span_id": table["spans"][0]["span_id"], "claim": "local evidence"}], "他走进房间。")
    assert located[0]["quote"] == "他走进房间。"
    with pytest.raises(KernelError, match="QUALITY_SOURCE_SPAN_INVALID"):
        bind_quality_spans([{"span_id": table["spans"][0]["span_id"], "claim": "local evidence"}], "她留在门外。")


def test_current_canon_envelope_validates_inner_schema_and_preserves_history():
    import json
    from novel_forge.api.authority_dependencies import validate_production_structured_result
    from novel_forge.modules.chapter_authority.execution_gateway import PostgresChapterExecutionContractBinder
    from novel_forge.modules.chapter_authority.provider_output_contracts import inline_shared_canon_schema
    from novel_forge.modules.production_execution.codex_configuration import codex_output_schema
    schema, reference = PostgresChapterExecutionContractBinder._provider_output_contract(stage="canon_extraction",
        request_payload={"input": {"source_span_table": source_spans("门开了。"),
            "accepted_transition_baselines": {}, "canonical_transition_results": []}}, prompt_contract_version="v12")
    assert reference == "schema:chapter-provider-output:canon_extraction:v30"
    inner = inline_shared_canon_schema(schema["x-host-payload-schema"])
    decoded = {key: [] for key, value in inner["properties"].items() if value.get("type") == "array"}
    decoded.update(extraction_status="NO_CHANGE", no_change_reason="No supported change")
    result = validate_production_structured_result("canon_extraction", schema,
        {"payload_json": json.dumps(decoded)}, output_schema_ref=reference)
    assert result["extraction_status"] == "NO_CHANGE"
    with pytest.raises(KernelError, match="CHAPTER_PROVIDER_OUTPUT_SCHEMA_INVALID"):
        validate_production_structured_result("canon_extraction", schema,
            {"payload_json": json.dumps({**decoded, "forged_field": True})}, output_schema_ref=reference)
    with pytest.raises(KernelError, match="CHAPTER_PROVIDER_OUTPUT_SCHEMA_INVALID"):
        validate_production_structured_result("canon_extraction", schema,
            {"payload_json": "malformed"}, output_schema_ref=reference)
    projected = codex_output_schema(schema, schema_ref=reference)
    assert "x-host-payload-schema" not in projected
    assert projected["required"] == ["payload_json"]
    assert codex_output_schema({}, schema_ref="schema:chapter-provider-output:canon_extraction:v25")["required"] == ["output_json"]
