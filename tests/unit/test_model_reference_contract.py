from __future__ import annotations

import pytest

from novel_forge.modules.chapter_quality_authority.model_reference import (
    MODEL_REFERENCE_PROTOCOL, require_model_reference_annotation, require_native_model_call, validate_panel,
)
from novel_forge.modules.chapter_quality_authority.reference_sampling import require_model_consensus_reference
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.routing_bootstrap import authorization_hash


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, query, arguments):
        assert "authority_external_effect" in query
        assert arguments[0] == "project:1"

    def fetchall(self):
        return self.rows


def source():
    return {"subject": {"asset_version_id": "subject:1", "content_hash": "sha256:" + "a" * 64},
        "author_baseline": {"asset_version_id": "baseline:1", "content_hash": "sha256:" + "b" * 64},
        "policy_hash": "sha256:" + "c" * 64, "producer_contract_hash": "sha256:" + "d" * 64,
        "protocol_version": MODEL_REFERENCE_PROTOCOL, "evaluation_version": "version:1",
        "dimension": "review_decision",
        "scope": {"scope_type": "CHAPTER", "chapter_start": 1, "chapter_end": 1}}


def native_row(*, fixture=False, effect_id="effect:1", session_id="session:1"):
    expected = source()
    evidence = {"real_model_call": True, "provider_id": "codex-cli", "model_id": "gpt-6.1-sol",
        "prompt_version": "prompt:1", "skill_version": "skill:1",
        "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
        "cost": {"amount": "0", "currency": "UNKNOWN"},
        "result": {"status": "PASSED", "score_range": [80, 90]},
        "production_execution": {"execution_request": {"project_id": "project:1", "operation_id": "operation:1",
            "attempt_id": "attempt:1", "external_effect_id": "effect:1", "stage": "model_reference_evaluate"},
            "execution_handle": {"operation_id": "operation:1", "attempt_id": "attempt:1",
                "local_execution_receipt_id": session_id, "backend_execution_id": session_id,
                "transport": "LOCAL_CLI_REMOTE_INFERENCE"},
            "process_evidence": {"local_execution_receipt_id": session_id,
                "transport": "LOCAL_CLI_REMOTE_INFERENCE",
                "model_authority": {"local_user_config_ignored": True,
                    "invocation_model": "gpt-6.1-sol", "invocation_reasoning_effort": "high"}},
            "route_snapshot": {"operation_id": "operation:1", "attempt_id": "attempt:1",
                "model_provider": "codex-cli", "model_id": "gpt-6.1-sol", "reasoning_effort": "high",
                "model_profile_hash": "sha256:" + "1" * 64, "route_policy_hash": "sha256:" + "2" * 64,
                "prompt_bundle_ref": "prompt:1", "skill_bundle_ref": "skill:1",
                "output_schema_ref": "schema:1", "context_bundle_ref": "context:1"},
            "input_manifest": {"ref": "input:1"},
            "output_manifest": {"output": "sha256:" + "3" * 64},
            "validation_manifest": {"status": "PASS"},
            "execution_result": {"outcome": "SUCCEEDED", "operation_id": "operation:1",
                "attempt_id": "attempt:1", "normalized_output_ref": "output:1",
                "output_manifest_ref": "manifest:1", "validation_report_ref": "validation:1"}}}
    content = {"stage": "model_reference_evaluate", "project_id": "project:1",
        "operation_id": "operation:1", "attempt_id": "attempt:1",
        "external_effect_id": "effect:1", "provider_evidence": evidence, "fixture_protocol_only": fixture}
    inputs = [{"project_id": "project:1", **expected[key]} for key in ("subject", "author_baseline")]
    request = {"input": {"model_reference": {**expected, "role": "BLIND_EVALUATION"}}}
    receipt = {"outcome": "success", "generation": 1, "evidence": evidence}
    return (content, authorization_hash(content), "operation:1", inputs, effect_id, request,
            authorization_hash(request), "gpt-6.1-sol", "attempt:1", 1, evidence, session_id,
            session_id, receipt, authorization_hash(evidence))


def test_native_model_call_requires_exact_effect_and_nonfixture_receipt(monkeypatch):
    from novel_forge.modules.command_kernel import routing_bootstrap
    from novel_forge.modules.chapter_quality_authority import model_reference_execution

    monkeypatch.setattr(model_reference_execution, "validate_model_reference_effect_inputs", lambda *args, **kwargs: None)

    monkeypatch.setattr(routing_bootstrap, "load_bootstrap_authorization", lambda *args, **kwargs: {
        "authorization": {"purpose": "MODEL_REFERENCE_CREATION",
            "model_reference": {**source(), "role": "BLIND_EVALUATION"}}})
    row = native_row()
    binding = {"asset_version_id": "model:1", "content_hash": row[1]}
    found = require_native_model_call(Rows([row]), project_id="project:1", binding=binding,
        expected=source(), role="BLIND_EVALUATION")
    assert found["external_effect_id"] == "effect:1"
    for changed in (native_row(fixture=True), native_row(effect_id="effect:other"), native_row(session_id="")):
        with pytest.raises(KernelError, match="MODEL_REFERENCE_PROVENANCE_INVALID"):
            require_native_model_call(Rows([changed]), project_id="project:1", binding=binding,
                expected=source(), role="BLIND_EVALUATION")


def test_native_model_call_rejects_peer_input_stale_baseline_and_mismatched_receipt(monkeypatch):
    from novel_forge.modules.command_kernel import routing_bootstrap
    from novel_forge.modules.chapter_quality_authority import model_reference_execution

    monkeypatch.setattr(model_reference_execution, "validate_model_reference_effect_inputs", lambda *args, **kwargs: None)

    monkeypatch.setattr(routing_bootstrap, "load_bootstrap_authorization", lambda *args, **kwargs: {
        "authorization": {"purpose": "MODEL_REFERENCE_CREATION",
            "model_reference": {**source(), "role": "BLIND_EVALUATION"}}})
    original = native_row()
    binding = {"asset_version_id": "model:1", "content_hash": original[1]}
    variants = []
    leaked = list(original)
    leaked[3] = [*leaked[3], {"asset_version_id": "peer-report", "content_hash": "sha256:" + "e" * 64}]
    variants.append(tuple(leaked))
    stale = list(original)
    stale[3] = [stale[3][0], {"asset_version_id": "baseline:old", "content_hash": "sha256:" + "b" * 64}]
    variants.append(tuple(stale))
    bad_receipt = list(original)
    bad_receipt[14] = "sha256:" + "f" * 64
    variants.append(tuple(bad_receipt))
    bad_request = list(original)
    bad_request[6] = "sha256:" + "f" * 64
    variants.append(tuple(bad_request))
    for changed in variants:
        with pytest.raises(KernelError, match="MODEL_REFERENCE_PROVENANCE_INVALID"):
            require_native_model_call(Rows([changed]), project_id="project:1", binding=binding,
                expected=source(), role="BLIND_EVALUATION")


def test_panel_requires_three_distinct_native_executions_and_reports_correlation():
    common = source()
    evaluations = [{**common, "blind": True, "asset_version_id": f"evaluation:{index}",
        "operation_id": f"operation:{index}", "attempt_id": f"attempt:{index}",
        "external_effect_id": f"effect:{index}", "session_id": f"session:{index}",
        "model_call_asset_version_id": f"model:{index}", "provider_id": "codex-cli",
        "model_id": "gpt-6.1-sol"} for index in (1, 2)]
    adjudication = {**common, "operation_id": "operation:3", "attempt_id": "attempt:3",
        "external_effect_id": "effect:3", "session_id": "session:3",
        "model_call_asset_version_id": "model:3", "provider_id": "codex-cli", "model_id": "gpt-6.1-sol",
        "source_evaluation_asset_version_ids": [item["asset_version_id"] for item in evaluations]}
    assert validate_panel(evaluations, adjudication)["same_model_correlated"] is True
    with pytest.raises(KernelError, match="MODEL_REFERENCE_PROVENANCE_INVALID"):
        validate_panel(evaluations, {**adjudication, "session_id": "session:2"})


def test_chapter_consumer_requires_exact_subject_scope_and_dimension(monkeypatch):
    from novel_forge.modules.chapter_quality_authority import model_reference

    panel = {"target_asset_version_id": "subject:1", "target_content_hash": "sha256:" + "a" * 64,
        "scope": {"scope_type": "CHAPTER", "chapter_start": 1, "chapter_end": 1},
        "labels": [{"dimension": "review_decision", "status": "PASSED", "score_range": [80, 90],
            "evaluation_version": "version:1", "adjudication_asset_version_id": "adjudication:1"}],
        "same_model_correlated": True, "evidence_refs": ["external-effect:effect:1"]}
    monkeypatch.setattr(model_reference, "require_model_panel_reference", lambda *args, **kwargs: panel)
    binding = {"basis": "MODEL_CONSENSUS", "protocol_version": MODEL_REFERENCE_PROTOCOL,
        "adjudications": [{"asset_version_id": "adjudication:1", "content_hash": "sha256:" + "b" * 64}]}
    kwargs = {"project_id": "project:1", "binding": binding, "target_id": "subject:1",
        "target_hash": "sha256:" + "a" * 64, "chapter": 1,
        "expected_dimensions": ("review_decision",), "allowed_statuses": {"PASSED", "BLOCKED"}}
    reference = require_model_consensus_reference(None, **kwargs)
    assert reference["reference_basis"] == "MODEL_CONSENSUS"
    assert reference["same_model_correlated"] is True
    with pytest.raises(KernelError, match="MODEL_REFERENCE_TARGET_INVALID"):
        require_model_consensus_reference(None, **{**kwargs, "chapter": 2})
    with pytest.raises(KernelError, match="MODEL_REFERENCE_COVERAGE_INCOMPLETE"):
        require_model_consensus_reference(None, **{**kwargs, "expected_dimensions": ("other",)})


def test_blind_provider_projection_rejects_peer_report_and_stale_author_baseline(monkeypatch):
    from novel_forge.modules.chapter_quality_authority import model_reference_execution

    frozen = {**source(), "role": "BLIND_EVALUATION"}
    subject = {"binding": frozen["subject"], "asset_type": "chapter_provider_sample", "content": {"text": "chapter"}}
    baseline = {"binding": frozen["author_baseline"], "asset_type": "creative_brief", "content": {"intent": "comedy"}}
    context = {"asset_version_id": "context:1", "content_hash": "sha256:" + "e" * 64,
        "projection": {"source_bindings": [frozen["subject"], frozen["author_baseline"]]}}
    monkeypatch.setattr(model_reference_execution, "_subject_projection", lambda *args, **kwargs: subject)
    monkeypatch.setattr(model_reference_execution, "_baseline_projection", lambda *args, **kwargs: baseline)
    monkeypatch.setattr(model_reference_execution, "_native_asset", lambda *args, **kwargs: {
        "asset_type": "context_bundle", "content": {"provider_context_view": context["projection"],
            "model_reference": frozen, "source_bindings": [frozen["subject"], frozen["author_baseline"]],
            "source_isolation": "FROZEN_MODEL_REFERENCE_ONLY"}})
    provider_input = {"model_reference": frozen, "subject": subject, "author_baseline": baseline, "context": context}
    model_reference_execution.validate_model_reference_effect_inputs(None, project_id="project:1",
        frozen=frozen, provider_input=provider_input)
    with pytest.raises(KernelError, match="MODEL_REFERENCE_INPUT_INVALID"):
        model_reference_execution.validate_model_reference_effect_inputs(None, project_id="project:1",
            frozen=frozen, provider_input={**provider_input, "peer_report": {"status": "PASSED"}})
    with pytest.raises(KernelError, match="MODEL_REFERENCE_INPUT_INVALID"):
        model_reference_execution.validate_model_reference_effect_inputs(None, project_id="project:1",
            frozen=frozen, provider_input={**provider_input, "author_baseline": {**baseline, "content": {"intent": "old"}}})


def test_model_record_rejects_human_identity_spoof_and_changed_model_result(monkeypatch):
    from novel_forge.modules.chapter_quality_authority import model_reference, reference_subject

    monkeypatch.setattr(reference_subject, "require_reference_subject", lambda *args, **kwargs: {
        **source()["subject"], "asset_type": "chapter_provider_sample"})
    native = {"operation_id": "operation:1", "attempt_id": "attempt:1", "external_effect_id": "effect:1",
        "provider_id": "codex-cli", "model_id": "gpt-6.1-sol", "session_id": "receipt:1",
        "result": {"status": "PASSED", "score_range": [80, 90]}}
    monkeypatch.setattr(model_reference, "require_native_model_call", lambda *args, **kwargs: native)
    model_call = {"asset_version_id": "model:1", "content_hash": "sha256:" + "f" * 64}
    record = {**source(), "model_call": model_call, "judgment": native["result"],
        "recording_actor_id": "service:reference", "blind": True,
        "model_call_asset_version_id": model_call["asset_version_id"],
        **{key: native[key] for key in ("operation_id", "attempt_id", "external_effect_id",
            "provider_id", "model_id", "session_id")}}
    assets = [record[key] for key in ("subject", "author_baseline", "model_call")]
    assert require_model_reference_annotation(None, project_id="project:1",
        definition_name="quality.model_reference_evaluation.record",
        payload={"model_reference": record}, actor_id="service:reference", input_assets=assets) == "subject:1"
    for changed in ({**record, "human_verified": True}, {**record, "evaluator_identity_class": "HUMAN"},
                    {**record, "judgment": {"status": "PASSED", "score_range": [90, 100]}}):
        with pytest.raises(KernelError, match="MODEL_REFERENCE_PROVENANCE_INVALID"):
            require_model_reference_annotation(None, project_id="project:1",
                definition_name="quality.model_reference_evaluation.record",
                payload={"model_reference": changed}, actor_id="service:reference", input_assets=assets)


def test_planning_agreement_consumes_model_panel_without_human_provenance():
    from novel_forge.modules.story_design_authority import scripted_qualification
    from novel_forge.modules.story_design_authority.evaluation_reference import reference_agreement

    expected = scripted_qualification("book_plan.generate")
    binding = {"basis": "MODEL_CONSENSUS", "protocol_version": MODEL_REFERENCE_PROTOCOL,
        "adjudications": [{"asset_version_id": "adjudication:1", "content_hash": "sha256:" + "a" * 64}]}
    report = reference_agreement(payload={"generator_operation_name": "book_plan.generate",
        "reference_evaluation": binding}, reference={"content": {"evaluation": expected},
        "work_requirements": False, "profile_version": "2.0.0",
        "model_reference": {"reference_basis": "MODEL_CONSENSUS", "same_model_correlated": True}},
        evaluation=expected)
    assert report["schema_version"] == "narrative-reference-agreement.v3"
    assert report["reference_basis"] == "MODEL_CONSENSUS"
    assert report["agreement_rate"] == 1
    assert "reference_author_actor_id" not in report
    assert report["production_qualification_eligible"] is False


def test_planning_model_reference_consumer_requires_exact_book_and_candidate(monkeypatch):
    from novel_forge.modules.chapter_quality_authority import model_reference, reference_subject
    from novel_forge.modules.story_design_authority import scripted_qualification
    from novel_forge.modules.story_design_authority import evaluation_reference

    binding = {"basis": "MODEL_CONSENSUS", "protocol_version": MODEL_REFERENCE_PROTOCOL,
        "adjudications": [{"asset_version_id": "adjudication:1", "content_hash": "sha256:" + "a" * 64}]}
    payload = {"reference_evaluation": binding, "candidate_asset_version_id": "candidate:1",
        "candidate_content_hash": "sha256:" + "b" * 64, "generation_operation_id": "generation:1",
        "generation_actor_id": "generator:1", "generator_operation_name": "book_plan.generate",
        "book_id": "book:1"}
    monkeypatch.setattr(reference_subject, "require_planning_reference_subject", lambda *args, **kwargs: {
        "generation_operation_id": "generation:1", "generation_actor_id": "generator:1", "content": {}})
    monkeypatch.setattr(evaluation_reference, "qualification_profile_options", lambda content: {
        "work_requirements": False, "profile_version": "2.0.0"})
    monkeypatch.setattr(evaluation_reference, "uses_work_requirements", lambda content: False)
    panel = {"target_asset_version_id": "candidate:1", "target_content_hash": "sha256:" + "b" * 64,
        "scope": {"scope_type": "BOOK", "book_id": "book:1"},
        "labels": [{"dimension": "narrative_semantic_evaluation", "status": "PASSED"}],
        "adjudicated_judgment": {"evaluation": scripted_qualification("book_plan.generate")}}
    monkeypatch.setattr(model_reference, "require_model_panel_reference", lambda *args, **kwargs: panel)
    found = evaluation_reference._require_reference_review(None, project_id="project:1",
        payload=payload, evaluator_actor_id="reviewer:1")
    assert found["model_reference"] == panel
    monkeypatch.setattr(model_reference, "require_model_panel_reference", lambda *args, **kwargs: {
        **panel, "scope": {"scope_type": "BOOK", "book_id": "book:other"}})
    with pytest.raises(KernelError, match="NARRATIVE_REFERENCE_COVERAGE_INCOMPLETE"):
        evaluation_reference._require_reference_review(None, project_id="project:1",
            payload=payload, evaluator_actor_id="reviewer:1")
