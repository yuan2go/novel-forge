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
