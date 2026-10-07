from copy import deepcopy

import pytest

from novel_forge.modules.canon_graph.grounding import extract_grounded_candidates, validate_support_review
from novel_forge.modules.canon_graph.source_spans import bind_source_spans, extraction_diagnostics, source_spans
from novel_forge.modules.chapter_authority.execution_gateway import PostgresChapterExecutionContractBinder
from novel_forge.modules.chapter_authority.provider_output_contracts import validate_chapter_provider_output_against_schema
from novel_forge.modules.command_kernel.errors import KernelError


def test_unicode_spans_bind_exact_candidate_without_rewriting_expression():
    text = "周澄看见名字。\n🚪门关上了。"
    table = source_spans(text)
    span = next(s for s in table["spans"] if s["quote"] == "🚪门关上了。")
    original = {"extraction_status": "EXTRACTED", "canon_facts": [{
        "subject": "door", "predicate": "status", "object": "closed",
        "claim_kind": "OBJECTIVE_EVENT", "evidence_span_id": span["span_id"],
    }]}
    frozen = deepcopy(original)
    bound = bind_source_spans(original, text)
    assert original == frozen
    assert bound["canon_facts"][0]["evidence_quote"] == text[span["start"]:span["end"]]
    result = extract_grounded_candidates(project_id="p", revision={"text": text, "chapter": 1},
        revision_asset_version_id="candidate", context_bundle_version_id="context", provider_extraction=bound)
    assert result["grounding"]["semantic_status"] == "PENDING_SUPPORT_REVIEW"
    with pytest.raises(KernelError):
        validate_support_review(extraction=result, revision={"text": text}, revision_asset_version_id="candidate",
            result={"coverage": "COMPLETE", "no_change_supported": False, "claims": []})


def test_stale_span_and_unobserved_claim_reject_together():
    old = source_spans("他看见名字。")["spans"][0]["span_id"]
    with pytest.raises(KernelError) as failure:
        bind_source_spans({"canon_facts": [{"evidence_span_id": old}],
            "arc_evidence": [{"observation_status": "NOT_OBSERVED", "evidence_span_id": old}]}, "她看见名字。")
    assert "canon_facts" in failure.value.message
    assert "unobserved" in failure.value.message


def test_schema_binds_only_source_span_ids_and_preserves_legacy_quotes():
    table = source_spans("周澄看见名字。")
    schema, ref = PostgresChapterExecutionContractBinder._provider_output_contract(
        stage="canon_extraction", request_payload={"input": {"source_span_table": table}}, prompt_contract_version="v9")
    assert ref.endswith(":v24")
    fields = schema["properties"]["canon_facts"]["items"]["properties"]
    assert "evidence_quote" not in fields
    assert fields["evidence_span_id"]["enum"] == [s["span_id"] for s in table["spans"]]
    value = {key: [] for key, field in schema["properties"].items() if field.get("type") == "array"}
    value.update(extraction_status="NO_CHANGE", no_change_reason="Nothing happened.")
    validate_chapter_provider_output_against_schema("canon_extraction", schema, value)
    legacy, ref = PostgresChapterExecutionContractBinder._provider_output_contract(
        stage="canon_extraction", request_payload={"input": {}}, prompt_contract_version="v9")
    assert ref.endswith(":v22")
    assert "evidence_quote" in legacy["properties"]["canon_facts"]["items"]["properties"]


def test_repair_reports_all_missing_quotes_and_inner_contract_defects():
    output = {"canon_facts": [{"evidence_quote": "她关门了。"}], "character_state_changes": [{
        "evidence_quote": "她记住了。", "world_transition": {"payload_json": "{}"}}]}
    defects = extraction_diagnostics(output, "周澄关门了。", agency=True)
    paths = {d["field_path"] for d in defects}
    assert "$.canon_facts[0].evidence_quote" in paths
    assert "$.character_state_changes[0].evidence_quote" in paths
    assert "$.character_state_changes[0].world_transition.action_mode" in paths
    assert "$.character_state_changes[0].world_transition.actor_id" in paths

@pytest.mark.parametrize("schema_ref", ["schema:chapter-provider-output:review:v7", "schema:chapter-provider-output:rereview:cross-chapter-v7"])
def test_current_scoped_review_does_not_turn_low_score_into_forced_revision(schema_ref):
    from novel_forge.modules.chapter_authority.model_effects import normalize_model_output
    result = normalize_model_output("review", {"score": 60, "issues": [], "knowledge_checks": []}, output_schema_ref=schema_ref)
    assert result["decision"] == "PASSED"
    assert result["review_decision_contract"] == "work-review-decision.v1"


def test_compact_schema_shares_exact_identity_enum_with_native_validation():
    import json
    from novel_forge.modules.production_execution.codex_configuration import codex_output_schema
    from novel_forge.modules.chapter_authority.provider_output_contracts import _validate
    table = source_spans("周澄看见名字。\n🚪门关上了。")
    legacy, _ = PostgresChapterExecutionContractBinder._provider_output_contract(
        stage="canon_extraction", request_payload={"input": {"source_span_table": table}}, prompt_contract_version="v9")
    compact, ref = PostgresChapterExecutionContractBinder._provider_output_contract(
        stage="canon_extraction", request_payload={"input": {"source_span_table": table, "source_span_schema_contract": "local-evidence-ref.v1"}}, prompt_contract_version="v9")
    assert ref.endswith(":v25")
    assert len(json.dumps(compact)) < len(json.dumps(legacy))
    def expand(node):
        if isinstance(node, list):
            return [expand(value) for value in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            return expand(compact["$defs"][node["$ref"].rsplit("/", 1)[1]])
        return {key: expand(value) for key, value in node.items() if key != "$defs"}
    assert expand(compact) == legacy
    projected = codex_output_schema(compact)
    assert projected["$defs"]["candidateEvidenceSpan"]["enum"] == [s["span_id"] for s in table["spans"]]
    field = compact["properties"]["canon_facts"]["items"]["properties"]["evidence_span_id"]
    _validate(field, table["spans"][0]["span_id"], path="$", root_schema=compact)
    for invalid in ("foreign-span", None, 1):
        with pytest.raises(ValueError):
            _validate(field, invalid, path="$", root_schema=compact)
    value = {key: [] for key, field in legacy["properties"].items() if field.get("type") == "array"}
    value.update(extraction_status="NO_CHANGE", no_change_reason="Nothing happened.")
    validate_chapter_provider_output_against_schema("canon_extraction", compact, value)


@pytest.mark.parametrize("schema", [
    {"$ref": "https://example.com/schema"},
    {"$ref": "#/$defs/missing"},
    {"$ref": "#/$defs/cycle", "$defs": {"cycle": {"$ref": "#/$defs/cycle"}}},
])
def test_native_schema_rejects_external_missing_and_cyclic_references(schema):
    with pytest.raises(KernelError):
        validate_chapter_provider_output_against_schema("canon_extraction", schema, "value")


def test_capacity_successor_does_not_admit_other_routing_blocks():
    from novel_forge.modules.chapter_authority.canon_contract_recovery import capacity_rejection
    decision = {"status": "BLOCKED", "selected": None,
        "task": {"operation_id": "op", "task_type": "canon_extraction", "input_tokens": 200, "output_tokens": 50,
            "producer_contract": {"output_schema": {"ref": "schema:chapter-provider-output:canon_extraction:v24"}}},
        "candidates": [{"candidate": {"context_limit": 240}, "rejected_reasons": ["CONTEXT_CAPACITY_EXCEEDED", "BUDGET_HARD_LIMIT"]}]}
    assert capacity_rejection(decision, "op")
    assert not capacity_rejection(decision, "other")
    for reason in ("TEMPLATE_MODEL_UNAUTHORIZED", "PROVIDER_UNAVAILABLE", "QUALITY_FLOOR_NOT_MET"):
        blocked = deepcopy(decision);blocked["candidates"][0]["rejected_reasons"].append(reason)
        assert not capacity_rejection(blocked, "op")


def test_exact_span_pattern_accepts_only_current_table_and_avoids_expanded_enum_growth():
    from novel_forge.modules.chapter_authority.provider_output_contracts import _validate
    table = source_spans("周澄看见名字。\n🚪门关上了。")
    schema, ref = PostgresChapterExecutionContractBinder._provider_output_contract(
        stage="canon_extraction", request_payload={"input": {"source_span_table": table, "source_span_schema_contract": "local-evidence-pattern.v1"}}, prompt_contract_version="v9")
    assert ref.endswith(":v26")
    identity = schema["$defs"]["candidateEvidenceSpan"]
    assert "enum" not in identity
    from novel_forge.modules.canon_graph.source_spans import expanded_enum_choices
    assert expanded_enum_choices(schema) < 1000
    for span in table["spans"]:
        _validate(identity, span["span_id"], path="$")
    for invalid in ("foreign", table["spans"][0]["span_id"] + "suffix"):
        with pytest.raises(ValueError):
            _validate(identity, invalid, path="$")


def test_typed_envelope_retains_full_host_contract_and_validates_before_normalization():
    import json
    from novel_forge.api.authority_dependencies import validate_production_structured_result
    from novel_forge.modules.production_execution.codex_configuration import codex_output_schema
    table = source_spans("周澄看见名字。")
    schema, ref = PostgresChapterExecutionContractBinder._provider_output_contract(
        stage="canon_extraction", request_payload={"input": {"source_span_table": table, "source_span_schema_contract": "typed-extraction-json.v1"}}, prompt_contract_version="v9")
    transport = codex_output_schema(schema)
    assert ref.endswith(":v27")
    assert set(transport["properties"]) == {"payload_json"}
    assert "x-host-payload-schema" not in transport
    from novel_forge.modules.chapter_authority.provider_output_contracts import canon_provider_array_fields
    value = {key: [] for key in canon_provider_array_fields()}
    value.update(extraction_status="NO_CHANGE", no_change_reason="No observed changes.")
    validated = validate_production_structured_result("canon_extraction", schema, {"payload_json": json.dumps(value)}, output_schema_ref=ref)
    assert validated["extraction_status"] == "NO_CHANGE"
    assert "payload_json" not in validated
    for invalid in ("not JSON", json.dumps({}), json.dumps({**value, "canon_facts": "[]"})):
        with pytest.raises(KernelError, match="CHAPTER_PROVIDER_OUTPUT_SCHEMA_INVALID"):
            validate_production_structured_result("canon_extraction", schema, {"payload_json": invalid}, output_schema_ref=ref)
    foreign = {**value, "canon_facts": [{"subject": "door", "predicate": "status", "object": "closed", "effective_from_chapter": 1,
        "supersedes_event_id": None, "evidence_span_id": "foreign-span", "claim_kind": "OBJECTIVE_EVENT", "confidence": 0.9, "impact_type": "world_fact"}]}
    with pytest.raises(KernelError, match="CHAPTER_PROVIDER_OUTPUT_SCHEMA_INVALID"):
        validate_production_structured_result("canon_extraction", schema, {"payload_json": json.dumps(foreign)}, output_schema_ref=ref)


def test_quality_spans_and_host_applicability_preserve_exact_candidate_contract():
    from novel_forge.modules.canon_graph.source_spans import bind_quality_spans, require_quality_dimensions
    text = "周澄看见名字。\n🚪门关上了。"
    table = source_spans(text)
    schema, ref = PostgresChapterExecutionContractBinder._provider_output_contract(
        stage="quality_commercial", prompt_contract_version="v9", request_payload={"input": {
            "quality_span_contract": "literal-source-spans.v1", "source_span_table": table,
            "dimension_applicability": {"reward": "APPLICABLE", "golden_opening": "NOT_APPLICABLE"}}})
    assert ref.endswith(":v5")
    rows = [{"dimension": "reward", "gate_status": "PASSED", "score": 80,
             "evidence_locations": [{"span_id": table["spans"][0]["span_id"], "claim": "观察获得信息"}],
             "confidence": 0.9, "issue_codes": [], "revision_strategies": []},
            {"dimension": "golden_opening", "gate_status": "NOT_APPLICABLE", "score": None,
             "evidence_locations": [], "confidence": 1, "issue_codes": [], "revision_strategies": []}]
    from novel_forge.modules.chapter_authority.provider_output_contracts import _validate
    item_schema = schema["properties"]["dimensions"]["items"]
    for row in rows:
        _validate(item_schema, row, path="$", root_schema=schema)
    bound = bind_quality_spans(rows[0]["evidence_locations"], text)
    assert bound == [{"quote": table["spans"][0]["quote"], "claim": "观察获得信息"}]
    require_quality_dimensions(rows, ("reward", "golden_opening"))
    for invalid in ({**rows[0], "gate_status": "NOT_APPLICABLE"}, {**rows[1], "score": 90}):
        with pytest.raises(ValueError):
            _validate(item_schema, invalid, path="$", root_schema=schema)
    with pytest.raises(KernelError, match="QUALITY_SOURCE_SPAN_INVALID"):
        bind_quality_spans(rows[0]["evidence_locations"], text + "后来。")
    with pytest.raises(KernelError, match="QUALITY_DIMENSION_COVERAGE_INVALID"):
        require_quality_dimensions([rows[0], rows[0]], ("reward", "golden_opening"))
