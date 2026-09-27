import pytest

from novel_forge.modules.canon_graph.grounding import text_hash
from novel_forge.modules.chapter_quality_authority.canon_support_reference import (
    reference_dimensions, validate_sample_result, valid_located_evidence,
)
from novel_forge.modules.chapter_quality_authority.reference_sampling import chapter_reference_agreement
from novel_forge.modules.command_kernel.errors import KernelError


def source():
    return {"grounding": {"contract_version": "grounded-canon.v1", "candidate_asset_version_id": "draft:1",
        "text_hash": text_hash("他没有走。"), "extraction_status": "EXTRACTED"},
        "canon_assertion_candidates": [{"grounded_claim_id": "claim:1", "claim_kind": "OBJECTIVE_EVENT"}]}


def result(assessment="UNSUPPORTED"):
    return {"coverage": "COMPLETE", "no_change_supported": False, "claims": [
        {"claim_id": "claim:1", "assessment": assessment, "observed_kind": "OBJECTIVE_EVENT", "reason": "正文明确没有离开。"}]}


def test_supported_and_negative_support_are_valid_sample_judgments():
    for assessment in ("SUPPORTED", "UNSUPPORTED", "UNCERTAIN"):
        validate_sample_result(source(), {"text": "他没有走。"}, "draft:1", result(assessment))
    with pytest.raises(KernelError, match="CANON_GROUNDING_INVALID"):
        validate_sample_result(source(), {"text": "他走了。"}, "draft:1", result())
    duplicated = result()
    duplicated["claims"] *= 2
    with pytest.raises(KernelError, match="CANON_GROUNDING_INVALID"):
        validate_sample_result(source(), {"text": "他没有走。"}, "draft:1", duplicated)


def test_claim_reference_preserves_false_pass_uncertainty_and_wrong_kind():
    reference = {"labels": [{"dimension": "canon_support:claim:1", "status": "FAILED", "score_range": [0, 100]}],
        "canon_support_claim_kinds": {"claim:1": "OBJECTIVE_EVENT"}}
    assert chapter_reference_agreement(reference, stage="canon_support", result=result())["status_accuracy"] == 1
    wrong = chapter_reference_agreement(reference, stage="canon_support", result=result("SUPPORTED"))
    assert wrong["status_accuracy"] == 0
    assert wrong["comparisons"][0]["score_in_range"] is None
    uncertain = chapter_reference_agreement(reference, stage="canon_support", result=result("UNCERTAIN"))
    assert uncertain["comparisons"][0]["observed_status"] == "INSUFFICIENT_EVIDENCE"
    wrong_kind = result("SUPPORTED")
    wrong_kind["claims"][0]["observed_kind"] = "HEARSAY"
    assert chapter_reference_agreement(reference, stage="canon_support", result=wrong_kind)["status_accuracy"] == 1


def test_no_change_coverage_has_its_own_reference_and_cannot_hide_claims():
    extraction = {"grounding": {**source()["grounding"], "extraction_status": "NO_CHANGE"}}
    assert reference_dimensions(extraction) == ("canon_no_change",)
    reference = {"labels": [{"dimension": "canon_no_change", "status": "FAILED", "score_range": [0, 100]}],
        "canon_support_claim_kinds": {}}
    output = {"coverage": "COMPLETE", "claims": [], "no_change_supported": False}
    validate_sample_result(extraction, {"text": "他没有走。"}, "draft:1", output)
    assert chapter_reference_agreement(reference, stage="canon_support", result=output)["status_accuracy"] == 1
    with pytest.raises(KernelError, match="QUALITY_REFERENCE_RESULT_INVALID"):
        chapter_reference_agreement(reference, stage="canon_support", result=result())


def test_human_support_evidence_is_bound_to_exact_claim_and_prose():
    row = {"claim_id": "claim:1", "source_asset_version_id": "draft:1", "start": 0, "end": 5,
        "quote": "他没有走。", "rationale": "否定句不支持离开这一抽取。"}
    assert valid_located_evidence(row, dimension="canon_support:claim:1", revision_id="draft:1", text="他没有走。")
    for key, value in (("claim_id", "another"), ("source_asset_version_id", "draft:2"), ("quote", "他走了。"), ("rationale", "")):
        changed = {**row, key: value}
        assert not valid_located_evidence(changed, dimension="canon_support:claim:1", revision_id="draft:1", text="他没有走。")


def test_canon_support_native_definitions_catalog_and_risk_policy_agree():
    from novel_forge.modules.chapter_authority.definitions import chapter_provider_sample_definitions
    from novel_forge.modules.capability_packs.operation_catalog import chapter_sampling_workflow_binding_catalog
    from novel_forge.modules.production_execution.cost_routing import task_policy
    definition = next(row for row in chapter_provider_sample_definitions(application_build_id="fixture", commit_sha="a" * 40)
        if row["name"] == "chapter.provider.sample.canon_support")
    assert definition["policy"]["source_definition_name"] == "chapter.canon.propose_changes"
    binding = chapter_sampling_workflow_binding_catalog(reference=True).resolve("canon_proposal")
    assert binding.stage == "canon_support"
    assert binding.operation_name == definition["name"]
    assert task_policy("canon_support").quality_metric == "REFERENCE_AGREEMENT"


def test_reference_sample_identity_ignores_generated_ids_but_keeps_claim_semantics():
    from copy import deepcopy
    from novel_forge.modules.chapter_quality_authority.canon_support_reference import sample_identity
    original = source()
    changed = deepcopy(original)
    changed["grounding"]["candidate_asset_version_id"] = "draft:2"
    changed["canon_assertion_candidates"][0]["grounded_claim_id"] = "new-claim"
    assert sample_identity(original, text="他没有走。") == sample_identity(changed, text="他没有走。")
    changed["canon_assertion_candidates"][0]["claim_kind"] = "HEARSAY"
    assert sample_identity(original, text="他没有走。") != sample_identity(changed, text="他没有走。")
