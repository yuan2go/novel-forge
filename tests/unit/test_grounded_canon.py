from __future__ import annotations

import hashlib

import pytest

from novel_forge.modules.canon_graph.grounding import extract_grounded_candidates, validate_support_review
from novel_forge.modules.command_kernel.errors import KernelError


def extract(text, output, **revision_fields):
    return extract_grounded_candidates(
        project_id="book-project",
        revision={"chapter": 1, "text": text, **revision_fields},
        revision_asset_version_id="final-candidate",
        context_bundle_version_id="frozen-context",
        provider_extraction=output,
    )


def fact(text, **overrides):
    return {
        "subject": "door", "predicate": "status", "object": "closed",
        "evidence_start": 0, "evidence_end": len(text), "evidence_quote": text,
        "claim_kind": "OBJECTIVE_EVENT", **overrides,
    }


def test_final_extraction_does_not_inherit_deleted_writer_or_plan_assertions():
    result = extract(
        "她决定寻找密室。",
        {"extraction_status": "NO_CHANGE", "no_change_reason": "仅表达未来打算。"},
        canon_assertions=[{"subject": "hero", "predicate": "discovered", "object": "secret-room"}],
        character_knowledge_changes=[{"character_id": "hero", "fact_id": "secret-location"}],
    )
    assert result["semantic_change_count"] == 0
    assert result["character_knowledge_changes"] == []
    assert result["grounding"]["semantic_status"] == "PENDING_SUPPORT_REVIEW"
    assert result["grounding"]["extraction_status"] == "NO_CHANGE"


@pytest.mark.parametrize("change", [
    {"evidence_start": -1}, {"evidence_end": 200},
    {"evidence_start": 0.5}, {"evidence_quote": "门从未关闭"},
    {"source_revision_asset_version_id": "old-candidate"},
    {"source_text_hash": "sha256:old"},
    {"previous_state_project_id": "other-book"},
])
def test_grounding_rejects_unverifiable_or_stale_evidence(change):
    text = "🚪门关上了。"
    with pytest.raises(KernelError):
        extract(text, {"extraction_status": "EXTRACTED", "facts": [fact(text, **change)]})


def test_unicode_evidence_binds_untrimmed_final_text_and_remains_a_candidate():
    text = "  🚪门关上了。\n"
    result = extract(text, {
        "extraction_status": "EXTRACTED",
        "facts": [fact(text, evidence_start=2, evidence_end=8, evidence_quote=text[2:8])],
    })
    claim = next(x for x in result["canon_assertion_candidates"] if x["predicate"] == "status")
    assert claim["extraction_evidence"]["quote"] == text[2:8]
    assert result["grounding"]["text_hash"] == "sha256:" + hashlib.sha256(text.encode()).hexdigest()
    assert result["grounding"]["semantic_status"] == "PENDING_SUPPORT_REVIEW"


@pytest.mark.parametrize("kind", ["DIALOGUE_ASSERTION", "BELIEF", "HEARSAY", "PLAN", "AUTHOR_INTENT", "HYPOTHESIS"])
def test_nonobjective_claim_cannot_be_promoted_into_objective_canon(kind):
    text = "他说：反派已经死了。"
    with pytest.raises(KernelError):
        extract(text, {"extraction_status": "EXTRACTED", "facts": [fact(text, claim_kind=kind)]})


@pytest.mark.parametrize("output", [{}, {"extraction_status": "EXTRACTED"}, {"extraction_status": "NO_CHANGE"}])
def test_empty_or_failed_extraction_is_not_a_successful_noop(output):
    with pytest.raises(KernelError):
        extract("门关上了。", output)


@pytest.mark.parametrize("verdict", ["UNSUPPORTED", "UNCERTAIN"])
def test_literal_span_does_not_override_failed_semantic_support(verdict):
    text = "他说：反派已经死了。"
    extraction = extract(text, {"extraction_status": "EXTRACTED", "facts": [fact(text)]})
    claim = extraction["canon_assertion_candidates"][1]
    with pytest.raises(KernelError):
        validate_support_review(extraction=extraction, revision={"text": text}, revision_asset_version_id="final-candidate", result={
            "coverage": "COMPLETE", "no_change_supported": False,
            "claims": [{"claim_id": claim["grounded_claim_id"], "assessment": verdict,
                        "observed_kind": "DIALOGUE_ASSERTION", "reason": "对白不是死亡证据。"}],
        })


def test_support_review_cannot_reuse_old_prose_or_omit_a_claim():
    text = "门关上了。"
    extraction = extract(text, {"extraction_status": "EXTRACTED", "facts": [fact(text)]})
    for candidate, prose in [("old-candidate", text), ("final-candidate", "门打开了。"), ("final-candidate", text)]:
        with pytest.raises(KernelError):
            validate_support_review(extraction=extraction, revision={"text": prose}, revision_asset_version_id=candidate,
                                    result={"coverage": "COMPLETE", "no_change_supported": False, "claims": []})
