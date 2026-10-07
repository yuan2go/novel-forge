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


def acceptance_assets():
    digest = "sha256:" + hashlib.sha256("她关上了门。".encode()).hexdigest()
    binding = {"contract_version": "grounded-canon.v1", "project_id": "p", "candidate_asset_version_id": "best:v1", "context_asset_version_id": "context:v1", "text_hash": digest, "semantic_status": "SUPPORTED_CANDIDATE"}
    contents = {
        "best_draft_candidate": {"text": "她关上了门。", "selected_source_asset_version_id": "revision:v1"},
        "canon_patch": {"grounding": binding, "source_asset_version_id": "best:v1"},
        "quality_score_report": {"target_asset_version_id": "best:v1", "canon_patch_version_id": "canon:v1", "review_asset_version_id": "review:v1", "context_bundle_version_id": "context:v1"},
        "re_review_report": {"diagnostic_contract_version": "actionable-diagnostics.v1", "target_text_hash": digest, "revision_version_id": "revision:v1", "context_bundle_version_id": "context:v1"},
    }
    ids = {"best_draft_candidate": "best:v1", "canon_patch": "canon:v1", "quality_score_report": "quality:v1", "re_review_report": "review:v1"}
    return {kind: {"asset_version_id": ids[kind], "content": content} for kind, content in contents.items()}


def test_book_acceptance_requires_same_final_prose_review_quality_and_canon():
    from novel_forge.modules.chapter_outcome.acceptance_contract import require_grounded_acceptance
    selected = acceptance_assets()
    assert require_grounded_acceptance(project_id="p", selected=selected)["candidate_asset_version_id"] == "best:v1"
    for kind, key in [("re_review_report", "target_text_hash"), ("re_review_report", "revision_version_id"), ("quality_score_report", "target_asset_version_id"), ("canon_patch", "source_asset_version_id")]:
        changed = acceptance_assets()
        changed[kind]["content"][key] = "stale"
        with pytest.raises(KernelError):
            require_grounded_acceptance(project_id="p", selected=changed)


def test_no_change_is_representable_by_current_provider_schema():
    from novel_forge.modules.chapter_authority.provider_output_contracts import chapter_provider_output_schema
    schema = chapter_provider_output_schema("canon_extraction", causal_batch=True)
    assert schema["properties"]["canon_facts"].get("minItems", 0) == 0


def test_plan_observation_cannot_bypass_final_prose_support():
    text = "她决定寻找密室。"
    with pytest.raises(KernelError):
        extract(text, {"extraction_status": "NO_CHANGE", "no_change_reason": "No objective changes",
                       "realization_evidence": [{"planned_event_id": "find-room", "observation_status": "OBSERVED",
                                                 "observed_action": "发现密室"}]})


def test_unexecuted_rule_reference_is_not_a_deterministic_derivation():
    text = "她看着那扇门。"
    with pytest.raises(KernelError):
        extract(text, {"extraction_status": "EXTRACTED", "facts": [fact(text, claim_kind="RULE_DERIVATION",
                        derivation_rule_ref="made-up-rule", premise_event_refs=["made-up-event"])]})


def test_supersession_requires_exact_current_entity_event_in_the_frozen_book():
    from novel_forge.modules.canon_graph.domain import build_canon_update
    from novel_forge.modules.canon_graph.grounding import grounded_claims
    text = "门打开了。"
    for source, expected in [("event:other-book", "BLOCKED"), ("event:door", "CLEAR")]:
        extraction = extract(text, {"extraction_status": "EXTRACTED", "facts": [fact(text, object="open", supersedes_event_id=source)]})
        extraction["grounding"] = validate_support_review(extraction=extraction, revision={"text": text}, revision_asset_version_id="final-candidate", result={
            "coverage": "COMPLETE", "no_change_supported": False,
            "claims": [{"claim_id": item["claim"]["grounded_claim_id"], "assessment": "SUPPORTED", "observed_kind": "OBJECTIVE_EVENT", "reason": "开门动作在文本中直接发生。"} for item in grounded_claims(extraction)]})
        patch = build_canon_update(project_id="book-project", revision={"text": text}, revision_asset_version_id="final-candidate",
            context_bundle_version_id="frozen-context", extraction=extraction,
            existing_facts=[{"subject": "door", "predicate": "status", "object": "closed", "source_event_id": "event:door"}])
        codes = {item["conflict_code"] for item in patch["conflicts"]}
        assert ("CANON_SUPERSESSION_SOURCE_INVALID" in codes) == (expected == "BLOCKED")


def payoff(text, evidence):
    return {
        'obligation_id': 'promise:return', 'obligation_type': 'PROMISE',
        'from_status': 'OPEN', 'status': 'FULFILLED', 'priority': 'HIGH',
        'target_window': {'status': 'SCHEDULED', 'from_chapter': 1, 'to_chapter': 1},
        'payoff_evidence': evidence, 'linked_arc_ids': [],
        'summary': 'The borrowed coin is returned.', 'evidence_start': 0,
        'evidence_end': len(text), 'evidence_quote': text,
        'claim_kind': 'OBJECTIVE_EVENT', 'confidence': 0.99,
        'impact_type': 'narrative_obligation_payoff',
    }


@pytest.mark.parametrize('evidence', [
    {'asset_version_id': 'other-book:unaccepted-draft', 'event_id': 'invented:accepted-event'},
    {'asset_version_id': 'final-candidate', 'event_id': 'invented:accepted-event'},
    {'asset_version_id': '$FINAL_CANDIDATE', 'event_id': 'invented:accepted-event'},
])
def test_grounding_rejects_provider_authored_payoff_authority_references(evidence):
    text = '她把借来的银币交还原主，兑现了昨日的承诺。'
    with pytest.raises(KernelError, match='payoff'):
        extract(text, {'extraction_status': 'EXTRACTED', 'obligation_changes': [payoff(text, evidence)]})


def grounded_payoff():
    text = '她把借来的银币交还原主，兑现了昨日的承诺。'
    output = {'extraction_status': 'EXTRACTED', 'obligation_changes': [payoff(text, {
        'asset_version_id': '$FINAL_CANDIDATE', 'event_id': '$CURRENT_CLAIM',
    })]}
    return extract(text, output)['obligation_changes'][0]


@pytest.mark.parametrize("work_requirements", [False, True])
@pytest.mark.parametrize("causal_batch", [False, True])
def test_current_contract_binds_prose_payoff_identity_after_semantic_extraction(work_requirements, causal_batch):
    from novel_forge.modules.chapter_authority.provider_output_contracts import (
        chapter_provider_output_schema_ref, validate_chapter_provider_output_semantics,
    )
    text = "她归还了借来的钱。"
    claim = payoff(text, None)
    claim.pop("evidence_start")
    claim.pop("evidence_end")
    validate_chapter_provider_output_semantics("canon_extraction", {
        "extraction_status": "EXTRACTED", "obligation_changes": [claim],
    }, host_bind_known_metadata=True)
    with pytest.raises(KernelError):
        validate_chapter_provider_output_semantics("canon_extraction", {
            "extraction_status": "EXTRACTED", "obligation_changes": [claim],
        })
    schema_ref = chapter_provider_output_schema_ref(
        "canon_extraction", causal_batch=causal_batch, work_requirements=work_requirements,
    )
    output = validate_chapter_provider_output_semantics("canon_extraction", {
        "extraction_status": "EXTRACTED",
        "obligation_changes": [claim],
    }, output_schema_ref=schema_ref)
    result = extract_grounded_candidates(
        project_id="book-project", revision={"chapter": 1, "text": text},
        revision_asset_version_id="final-candidate", context_bundle_version_id="frozen-context",
        provider_extraction={**output, "provider_output_schema_ref": schema_ref},
        work_requirements=work_requirements,
    )
    bound = result["obligation_changes"][0]
    assert bound["evidence_start"] == 0
    assert bound["payoff_evidence"]["asset_version_id"] == "final-candidate"
    assert bound["payoff_evidence"]["event_id"] == bound["grounded_claim_id"]
    assert bound["payoff_evidence"]["evidence_mode"] == "GROUNDED_FINAL_CANDIDATE_CLAIM"
    accepted = payoff_events(bound)[0].payload["payoff_evidence"]
    assert accepted["asset_version_id"] == "final-candidate"
    assert accepted["grounded_claim_id"] == bound["grounded_claim_id"]


@pytest.mark.parametrize("version", ["v18", "v19", "v26", "v200", "v210", "v22:unknown", ""])
def test_other_canon_contracts_do_not_acquire_null_payoff_binding(version):
    text = "她归还了借来的钱。"
    schema_ref = "schema:chapter-provider-output:canon_extraction:" + version if version else ""
    with pytest.raises(KernelError, match="typed payoff evidence"):
        extract(text, {"provider_output_schema_ref": schema_ref, "extraction_status": "EXTRACTED",
                       "obligation_changes": [payoff(text, None)]})
    if version in {"v18", "v19", ""}:
        result = extract(text, {"provider_output_schema_ref": schema_ref, "extraction_status": "EXTRACTED",
                               "obligation_changes": [payoff(text, {
                                   "asset_version_id": "$FINAL_CANDIDATE", "event_id": "$CURRENT_CLAIM",
                               })]})
        assert result["obligation_changes"][0]["payoff_evidence"]["asset_version_id"] == "final-candidate"


@pytest.mark.parametrize("obligation_type,evidence", [
    ("CAUSAL_DEBT", None), ("PROMISE", {}),
    ("PROMISE", {"asset_version_id": "provider-authored", "event_id": "invented"}),
])
@pytest.mark.parametrize("causal_batch", [False, True])
def test_work_canon_binding_does_not_replace_required_or_invalid_evidence(obligation_type, evidence, causal_batch):
    from novel_forge.modules.chapter_authority.provider_output_contracts import chapter_provider_output_schema_ref
    text = "她归还了借来的钱。"
    claim = {**payoff(text, evidence), "obligation_type": obligation_type}
    schema_ref = chapter_provider_output_schema_ref("canon_extraction", causal_batch=causal_batch, work_requirements=True)
    with pytest.raises(KernelError, match="payoff"):
        extract(text, {"provider_output_schema_ref": schema_ref, "extraction_status": "EXTRACTED",
                       "obligation_changes": [claim]})


def test_work_canon_binding_preserves_accepted_causal_payoff():
    from novel_forge.modules.chapter_authority.provider_output_contracts import chapter_provider_output_schema_ref
    text = "她归还了借来的钱。"
    evidence = {"asset_version_id": "accepted:prerequisite", "event_id": "accepted:event"}
    claim = {**payoff(text, evidence), "obligation_type": "CAUSAL_DEBT"}
    result = extract(text, {
        "provider_output_schema_ref": chapter_provider_output_schema_ref("canon_extraction", causal_batch=True, work_requirements=True),
        "extraction_status": "EXTRACTED", "obligation_changes": [claim],
    })
    assert result["obligation_changes"][0]["payoff_evidence"] == evidence


def payoff_events(change):
    from novel_forge.modules.narrative_state.contracts import events_from_canon_patch
    return events_from_canon_patch(
        project_id='book-project', book_id='book', source_chapter=1,
        chapter_outcome_id='outcome', canon_patch_asset_version_id='canon-patch',
        accepted_draft_asset_version_id='final-candidate', source_operation_id='operation',
        trace_id='trace', canon_patch={'obligation_changes': [change]},
    )


def test_payoff_citation_binds_final_candidate_then_exact_canon_source_and_replays():
    from copy import deepcopy
    change = grounded_payoff()
    citation = change['payoff_evidence']
    assert citation['asset_version_id'] == 'final-candidate'
    assert citation['event_id'] == change['grounded_claim_id']
    assert citation['evidence_mode'] == 'GROUNDED_FINAL_CANDIDATE_CLAIM'
    frozen = deepcopy(change)
    first = payoff_events(change)[0]
    actual = first.payload['payoff_evidence']
    assert actual['asset_version_id'] == 'final-candidate'
    assert actual['event_id'] == f'canon-patch#{first.state_kind.value}:0'
    assert actual['grounded_claim_id'] == change['grounded_claim_id']
    assert actual['evidence_mode'] == 'ACCEPTED_DRAFT_CANON_LINEAGE'
    assert first.payload['actual_payoff'] == actual
    assert change == frozen
    assert payoff_events(change)[0].to_dict() == first.to_dict()


@pytest.mark.parametrize('field, value', [
    ('asset_version_id', 'other-book:final-candidate'),
    ('event_id', 'another-candidate:claim'),
])
def test_accepted_payoff_rejects_candidate_or_claim_scope_tampering(field, value):
    change = grounded_payoff()
    change['payoff_evidence'][field] = value
    with pytest.raises(KernelError, match='payoff'):
        payoff_events(change)
