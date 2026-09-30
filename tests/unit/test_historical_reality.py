from __future__ import annotations

from pathlib import Path

from novel_forge.tools.historical_reality import (
    _historical_authorization_evidence,
    check_historical_reality,
    load_historical_reality_policy,
    validate_proof_scope,
)


ROOT = Path(__file__).resolve().parents[2]


def test_repository_has_no_historical_roadmap_authority() -> None:
    report = check_historical_reality(ROOT)

    assert report["status"] == "PASS", report["errors"]
    assert report["historical_roadmap_authority_count"] == 0
    assert report["eight_chapter_canonical_reference_count"] == 0
    assert report["stale_wp_pr_adr_roadmap_authority_count"] == 0
    assert report["unmanaged_historical_instruction_count"] == 0
    assert report["historical_test_authority_count"] == 0


def test_historical_authorization_exclusion_requires_exact_expired_or_non_grant_evidence() -> None:
    policy = load_historical_reality_policy(ROOT)
    excluded, errors = _historical_authorization_evidence(ROOT, policy)
    assert not errors
    assert len(excluded) == len(policy["immutable_historical_authorization_evidence"])

    path, identity = next(iter(policy["immutable_historical_authorization_evidence"].items()))
    tampered = {
        **policy,
        "immutable_historical_authorization_evidence": {
            path: {**identity, "sha256": "0" * 64}
        },
    }
    excluded, errors = _historical_authorization_evidence(ROOT, tampered)
    assert not excluded
    assert errors == [f"historical authorization content changed: {path}"]


def test_proof_scope_is_typed_and_rejects_retired_ontology() -> None:
    policy = load_historical_reality_policy(ROOT)
    valid = policy["backend_proof_scope"]

    assert validate_proof_scope(valid, policy=policy) == []

    retired = "EIGHT" + "_CHAPTER"
    invalid = {**valid, "proves": [*valid["proves"], retired]}
    assert validate_proof_scope(invalid, policy=policy) == [
        f"proof_scope.proves contains a retired current ontology: {retired}"
    ]


def test_reality_policy_separates_facts_from_roadmap() -> None:
    policy = load_historical_reality_policy(ROOT)

    assert policy["fact_types"] == {
        "current_runtime": "CURRENT_RUNTIME_FACT",
        "current_qualification": "CURRENT_QUALIFICATION_EVIDENCE",
        "historical_compatibility": "HISTORICAL_COMPATIBILITY_FACT",
        "product_narrative_roadmap": "NOT_REPOSITORY_AUTHORITY",
    }
    assert "next_wp" in policy["forbidden_machine_fields"]
    assert "evidence_ceilings" in policy["forbidden_machine_fields"]
