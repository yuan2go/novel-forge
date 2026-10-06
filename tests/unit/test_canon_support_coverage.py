from copy import deepcopy

import pytest

from novel_forge.modules.chapter_authority.canon_support_coverage import (
    bind_claim_identifiers, combine_review, coverage_partition,
)
from novel_forge.modules.chapter_authority.provider_output_contracts import chapter_provider_output_schema, validate_chapter_provider_output_against_schema
from novel_forge.modules.command_kernel.errors import KernelError


def source():
    extraction = {"world_state_changes": [
        {"grounded_claim_id": "exact-a", "claim_kind": "OBJECTIVE_EVENT"},
        {"grounded_claim_id": "exact-b", "claim_kind": "OBJECTIVE_STATE"},
    ]}
    review = {"coverage": "COMPLETE", "no_change_supported": False, "claims": [
        {"claim_id": "exact-a", "assessment": "SUPPORTED", "observed_kind": "OBJECTIVE_EVENT", "reason": "Located independent assessment."},
        {"claim_id": "typo-b", "assessment": "SUPPORTED", "observed_kind": "OBJECTIVE_STATE", "reason": "Unassigned evidence must not be guessed."},
    ]}
    return extraction, review


def test_unknown_identifier_is_unassigned_and_only_exact_unresolved_claim_is_reassessed():
    extraction, prior = source()
    before = deepcopy(prior)
    partition = coverage_partition(extraction, prior)
    assert partition["unassigned_claim_ids"] == ["typo-b"]
    assert [item["claim"]["grounded_claim_id"] for item in partition["unresolved_claims"]] == ["exact-b"]
    fresh = {"coverage": "COMPLETE", "claims": [
        {"claim_id": "exact-b", "assessment": "UNSUPPORTED", "observed_kind": "OBJECTIVE_STATE", "reason": "Fresh disagreement remains real."},
    ]}
    combined = combine_review(extraction, prior, fresh)
    assert combined["claims"] == [before["claims"][0], fresh["claims"][0]]
    assert prior == before
    with pytest.raises(KernelError, match="CANON_GROUNDING_INVALID"):
        combine_review(extraction, prior, {"coverage": "COMPLETE", "claims": prior["claims"]})


@pytest.mark.parametrize("change", [{"assessment": "UNCERTAIN"}, {"assessment": "UNSUPPORTED"}, {"observed_kind": "DIALOGUE_ASSERTION"}, {"reason": ""}])
def test_coverage_recovery_cannot_erase_a_known_semantic_disagreement(change):
    extraction, prior = source()
    prior["claims"][0].update(change)
    with pytest.raises(KernelError, match="CANON_SUPPORT_SEMANTIC_REPAIR_REQUIRED"):
        coverage_partition(extraction, prior)


def test_duplicate_assessments_are_unresolved_and_valid_completed_support_cannot_recover():
    extraction, prior = source()
    prior["claims"] = [prior["claims"][0], prior["claims"][0]]
    with pytest.raises(KernelError, match="CANON_SUPPORT_COVERAGE_NOT_APPLICABLE"):
        coverage_partition(extraction, prior)
    prior["claims"] = source()[1]["claims"]
    prior["claims"][1]["claim_id"] = "exact-b"
    with pytest.raises(KernelError, match="CANON_SUPPORT_COVERAGE_NOT_APPLICABLE"):
        coverage_partition(extraction, prior)


def test_provider_schema_freezes_exact_identifiers_and_count_without_changing_assessments():
    extraction, prior = source()
    partition = coverage_partition(extraction, prior)
    schema = bind_claim_identifiers(chapter_provider_output_schema("canon_support"), partition["unresolved_claims"])
    fresh = {"coverage": "COMPLETE", "no_change_supported": False, "claims": [
        {"claim_id": "exact-b", "assessment": "UNCERTAIN", "observed_kind": "OBJECTIVE_STATE", "reason": "Actual uncertainty."},
    ]}
    validate_chapter_provider_output_against_schema("canon_support", schema, fresh)
    fresh["claims"][0]["claim_id"] = "typo-b"
    with pytest.raises(KernelError):
        validate_chapter_provider_output_against_schema("canon_support", schema, fresh)
