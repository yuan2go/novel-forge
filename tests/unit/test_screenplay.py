from copy import deepcopy

import pytest

from novel_forge.modules.book_authority.completion_domain import completion_digest
from novel_forge.modules.book_followup_authority.screenplay import (
    SCREENPLAY_DIMENSIONS, screenplay_output_schema, validate_candidate, validate_review,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution.cost_routing import task_policy


def source():
    value = {"schema_version": "screenplay-source.v1", "scene_plan": [{"scene_id": "s1", "source_unit_ids": ["u1"],
        "participants": ["mara"], "location": "廊下", "time": "雨前", "required_fact_ids": ["vow"]}],
        "policy": {"allowed_changes": ["动作外化"], "knowledge_contract": {
            "character_known_fact_ids": {"mara": ["vow"]}, "reader_allowed_fact_ids": ["vow"]}}}
    value["source_digest"] = completion_digest(value)
    return value


def candidate(contract):
    return {"schema_version": "scene-screenplay.v1", "source_digest": contract["source_digest"], "scenes": [{
        "scene_id": "s1", "source_unit_ids": ["u1"], "participants": ["mara"], "location": "廊下", "time": "雨前",
        "retained_fact_ids": ["vow"], "adaptation_changes": ["动作外化"], "beats": [
            {"beat_id": "b1", "kind": "DIALOGUE", "character_id": "mara", "text": "我的承诺还没有完。", "fact_ids": ["vow"]}]}]}


def test_screenplay_freezes_source_structure_knowledge_and_preservation():
    contract = source()
    valid = candidate(contract)
    assert validate_candidate(valid, contract)["candidate_digest"] == completion_digest(valid)
    for field, replacement, code in (("source_unit_ids", ["unknown"], "FIDELITY"),
        ("retained_fact_ids", [], "FIDELITY"), ("adaptation_changes", ["改变承诺结局"], "FIDELITY")):
        output = deepcopy(valid)
        output["scenes"][0][field] = replacement
        with pytest.raises(KernelError, match=code):
            validate_candidate(output, contract)
    output = deepcopy(valid)
    output["scenes"][0]["beats"][0]["fact_ids"] = ["other-character-secret"]
    with pytest.raises(KernelError, match="KNOWLEDGE"):
        validate_candidate(output, contract)
    output = deepcopy(valid)
    output["scenes"][0]["beats"][0]["kind"] = "ACTION"
    with pytest.raises(KernelError, match="ACTION_SPEAKER"):
        validate_candidate(output, contract)


def test_screenplay_review_preserves_negative_unknown_and_rejects_false_approval():
    contract = source()
    output = validate_candidate(candidate(contract), contract)
    review = {"schema_version": "screenplay-review.v1", "source_digest": contract["source_digest"],
        "candidate_digest": output["candidate_digest"], "verdict": "INDETERMINATE",
        "reviewed_dimensions": list(SCREENPLAY_DIMENSIONS), "findings": [], "rationale": "证据不足，保留候选。"}
    assert validate_review(review, contract, output)["verdict"] == "INDETERMINATE"
    review["candidate_digest"] = "another-version"
    with pytest.raises(KernelError, match="SCOPE"):
        validate_review(review, contract, output)
    review["candidate_digest"] = output["candidate_digest"]
    review.update(verdict="APPROVE", findings=[{"finding_id": "f1", "scene_id": "s1", "beat_id": "b1", "dimension": "DIALOGUE",
        "severity": "MAJOR", "description": "对白与行动未衔接", "preservation_requirement": "保留承诺"}])
    with pytest.raises(KernelError, match="CONTRADICTORY"):
        validate_review(review, contract, output)


def test_screenplay_schema_does_not_accept_novel_text_envelope():
    with pytest.raises(KernelError, match="OUTPUT_CONTRACT"):
        validate_candidate({"text": "小说正文"}, source())
    assert "scenes" in screenplay_output_schema("screenplay_generate")["required"]
    assert task_policy("screenplay_generate").quality_metric == "GENERATOR_SCORE"
    assert task_policy("screenplay_review").quality_metric == "INDEPENDENT_REVIEWER_SCORE"


def test_screenplay_budget_classification_preserves_exact_source_and_revision_cost():
    from novel_forge.modules.command_kernel.creative_budget_contract import classify_phase
    from novel_forge.modules.command_kernel.creative_budget_scope import classify_business_scope
    identity = {"operation_name": "screenplay_revision", "capability": "model.screenplay_revision", "attempt_no": 1,
        "command_payload": {"payload": {}}, "request_payload": {"stage": "screenplay_revision", "input": {}, "_production_execution": {"chapter": 0}}}
    assert classify_phase(identity["operation_name"], identity["capability"], identity["request_payload"], 1) == "REPAIR"
    with pytest.raises(KernelError, match="BUSINESS_SCOPE_UNKNOWN"):
        classify_business_scope(identity)
    identity["native_screenplay_scope"] = {"units": [{"unit_id": "u1"}], "source_revision_id": "exact-version", "chapter_start": 1, "chapter_end": 2}
    result = classify_business_scope(identity)
    assert result["phase"] == "REPAIR" and result["chapter_number"] == 2
    assert result["scope_sources"][-1]["value"]["source_revision_id"] == "exact-version"


def test_screenplay_v2_craft_has_located_uncertainty_and_isolated_optional_omission():
    contract = source()
    contract["schema_version"] = "screenplay-source.v2"
    contract["screenplay_craft"] = {"strategy": {"uses": [{"use_id": "use1", "scene_id": "s1", "knowledge_card_asset_version_id": "card1"}]},
        "decisions": [{"scene_id": "s1", "knowledge_card_asset_version_id": "card1", "required": True}]}
    contract["source_digest"] = completion_digest({key: value for key, value in contract.items() if key != "source_digest"})
    output = candidate(contract)
    output.update(schema_version="scene-screenplay.v2", craft_realizations=[{"use_id": "use1", "scene_id": "s1", "decision": "ADOPT", "beat_ids": ["b1"], "reason": "在既有对白中采用已批准技法。"}])
    validated = validate_candidate(output, contract)
    review = {"schema_version": "screenplay-review.v2", "source_digest": contract["source_digest"], "candidate_digest": validated["candidate_digest"],
        "verdict": "INDETERMINATE", "reviewed_dimensions": list(SCREENPLAY_DIMENSIONS), "findings": [], "rationale": "定位成立但效果证据不足。",
        "craft_checks": [{"use_id": "use1", "scene_id": "s1", "beat_ids": ["b1"], "status": "UNCERTAIN", "interference": "UNCERTAIN", "reason": "效果不明"}]}
    assert validate_review(review, contract, validated)["craft_checks"][0]["status"] == "UNCERTAIN"
    review["verdict"] = "APPROVE"
    with pytest.raises(KernelError, match="CRAFT_REVIEW_UNRESOLVED"):
        validate_review(review, contract, validated)
    output["craft_realizations"][0].update(decision="OMIT", beat_ids=[])
    with pytest.raises(KernelError, match="CRAFT_REALIZATION_INVALID"):
        validate_candidate(output, contract)


def test_screenplay_provider_schema_replays_v1_and_explicitly_freezes_v2():
    from novel_forge.modules.chapter_authority.execution_gateway import PostgresChapterExecutionContractBinder
    old, old_ref = PostgresChapterExecutionContractBinder._provider_output_contract(stage="screenplay_generate", request_payload={"input": {"source_digest": "old"}})
    new, new_ref = PostgresChapterExecutionContractBinder._provider_output_contract(stage="screenplay_generate", request_payload={"input": {"source_digest": "new", "screenplay_source_contract": "screenplay-source.v2"}})
    assert old["properties"]["schema_version"]["const"] == "scene-screenplay.v1"
    assert new["properties"]["schema_version"]["const"] == "scene-screenplay.v2"
    assert old_ref.endswith(":v1") and new_ref.endswith(":v2")
    assert "craft_realizations" not in old["properties"] and "craft_realizations" in new["required"]


def test_screenplay_export_uses_frozen_names_and_old_versions_keep_ids():
    from novel_forge.modules.book_followup_authority.screenplay import screenplay_text
    contract = source()
    raw = candidate(contract)
    assert "mara：" in screenplay_text(raw)
    contract["character_display"] = {"contract_version": "screenplay-character-display.v1", "scenes": {"s1": {"mara": "闻澈"}},
        "sources": [{"cast_asset_version_id": "exact-cast", "cast_content_hash": "exact-hash"}]}
    contract["source_digest"] = completion_digest({key: value for key, value in contract.items() if key != "source_digest"})
    raw["source_digest"] = contract["source_digest"]
    validated = validate_candidate(raw, contract)
    assert validated["scenes"][0]["beats"][0]["character_id"] == "mara"
    assert validated["candidate_digest"] == completion_digest(raw)
    assert "闻澈：" in screenplay_text(validated) and "mara：" not in screenplay_text(validated)
    assert validated["character_display"] == contract["character_display"]
