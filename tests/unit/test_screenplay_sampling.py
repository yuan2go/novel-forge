from copy import deepcopy

import pytest

from novel_forge.modules.book_followup_authority.screenplay import SCREENPLAY_STAGES, validate_candidate
from novel_forge.modules.book_followup_authority.screenplay_sampling import screenplay_sample_definition, sample_definition_name
from novel_forge.modules.book_followup_authority.screenplay_sample_execution import upstream_projection, expand_sample_inputs
from novel_forge.modules.book_followup_authority.screenplay_sample_feedback import (
    screenplay_reference_contract, screenplay_annotation_scope, validate_screenplay_annotation,
)
from novel_forge.modules.capability_packs.screenplay_profiles import build_screenplay_pack_profile
from novel_forge.modules.capability_packs.screenplay_sample_profiles import build_screenplay_sampling_profile
from novel_forge.modules.capability_packs.operation_catalog import governed_workflow_binding_catalog
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.routing_bootstrap import authorization_hash
from novel_forge.modules.content_authority.definitions import content_operation_definitions
from tests.unit.test_screenplay import source, candidate
from pathlib import Path


def test_screenplay_sample_pack_preserves_formal_producer_and_versioned_ineligible_outputs():
    root = Path(__file__).resolve().parents[2]
    for stage in SCREENPLAY_STAGES:
        definition = screenplay_sample_definition(application_build_id="test", commit_sha="a" * 40, stage=stage)
        formal = build_screenplay_pack_profile(root, stage=stage, operation_definition_hash="sha256:" + "1" * 64)
        sample = build_screenplay_sampling_profile(formal, stage=stage, operation_definition_hash=authorization_hash(definition))
        assert sample.manifest["identity"]["version"] == formal.manifest["identity"]["version"] == "1.1.0"
        assert sample.manifest["workflow_template"]["workflow_version"] == "1.0.0"
        for artifact in formal.artifact_catalog["artifacts"]:
            if artifact["kind"] != "CONTEXT_POLICY":
                assert artifact in sample.artifact_catalog["artifacts"]
        context = next(item for item in sample.artifact_catalog["artifacts"] if item["ref"] == sample.manifest["context_sources"]["policy_id"])
        assert set(context["content"]["allowed_asset_types"]) == set(sample.manifest["context_sources"]["allowed_asset_types"])
        workflow, version = sample.workflow_ref.split("@")
        catalog = governed_workflow_binding_catalog(workflow, version)
        assert catalog.bindings()[0].operation_name == sample_definition_name(stage)
        assert definition["completion_contract"]["required_asset_selectors"][0]["eligibility"] == "INELIGIBLE"
    definitions = content_operation_definitions(application_build_id="test", commit_sha="a" * 40,
        reference_annotations=True, screenplay_reference_annotations=True)
    assert {item["definition_version"] for item in definitions} == {"2.6.0"}


def test_upstream_projection_contains_only_exact_candidate_review_not_grant_or_human_labels():
    generated = {"stage": "screenplay_generate", "sampled_output": {"scenes": []}, "campaign": "private-label"}
    projected = upstream_projection("screenplay_review", generated)
    assert projected == {"screenplay_candidate": {"scenes": []}}
    review = {"stage": "screenplay_review", "sampled_output": {"verdict": "REVISE"}, "input_candidate": {"scenes": []}}
    assert set(upstream_projection("screenplay_revision", review)) == {"screenplay_candidate", "screenplay_review"}
    with pytest.raises(KernelError, match="STAGE_INVALID"):
        upstream_projection("screenplay_revision", generated)
    assert {item["asset_type"] for item in expand_sample_inputs([{"asset_type": "screenplay_provider_sample", "projection": projected}])} == {"screenplay_candidate"}


def test_screenplay_independent_labels_bind_exact_source_producer_and_located_evidence():
    contract = source()
    contract.update(source_units=[{"unit_id": "u1", "text": "我的承诺尚未完成。"}],
        accepted_source_evidence={"units": [{"chapter_number": 1}]})
    subject = {"source": contract, "producer_contract_hash": "sha256:" + "1" * 64,
        "generation_actor_ids": ["author"], "content": {"stage": "screenplay_generate", "sampled_output": validate_candidate(candidate(source()), source())}}
    annotation = {**screenplay_annotation_scope(subject), "dimension": "DIALOGUE", "evaluator_id": "independent",
        "evidence": [{"source_digest": contract["source_digest"], "scene_id": "s1", "beat_id": "b1", "unit_id": "u1",
            "start": 0, "end": 2, "quote": "我的", "observation": "证词可定位，承诺尚未兑现。"}]}
    validate_screenplay_annotation(subject=subject, annotation=annotation, human=True)
    for key, value, error in (("evaluator_id", "author", "NOT_INDEPENDENT"), ("evaluation_version", "old-contract", "SCOPE_INVALID"), ("dimension", "self_score", "SCOPE_INVALID")):
        with pytest.raises(KernelError, match=error):
            validate_screenplay_annotation(subject=subject, annotation={**annotation, key: value}, human=True)
    changed = deepcopy(annotation)
    changed["evidence"][0]["quote"] = "伪造"
    with pytest.raises(KernelError, match="EVIDENCE_INVALID"):
        validate_screenplay_annotation(subject=subject, annotation=changed, human=True)
    assert screenplay_reference_contract("screenplay_review", subject["producer_contract_hash"])["independent_blind_humans_required"] == 2


def test_screenplay_grants_require_finite_campaign_and_evaluator_purpose():
    from tests.unit.test_routing_bootstrap import contract
    from novel_forge.modules.production_execution.routing_policy import validate_routing_policy
    from novel_forge.modules.command_kernel.routing_bootstrap import validate_bootstrap_history
    for stage in SCREENPLAY_STAGES:
        _, grant, _ = contract()
        grant["task_type"] = stage
        grant["campaign"] = {"campaign_id": "screenplay-campaign", "manifest_hash": "sha256:" + "a" * 64,
            "sample_id": stage, "group_id": stage, "partition": "CALIBRATION", "maximum_calls": 4,
            "maximum_tokens": 8000, "maximum_amount": "0.04", "expires_at": grant["expires_at"]}
        if stage == "screenplay_review":
            grant.update(purpose="REFERENCE_EVALUATION", reference_evaluation={"asset_version_id": "source",
                "content_hash": "sha256:" + "b" * 64, "protocol_version": "screenplay-independent-quality.v1"})
        policy = {"policy_version": "screenplay-v1", "reason": "bounded sample", "task_overrides": [], "bootstrap_authorizations": [grant]}
        validate_routing_policy(policy)
        changed = deepcopy(grant)
        changed["campaign"]["maximum_calls"] = 5
        changed["authorization_id"] = "new-grant"
        with pytest.raises(KernelError, match="ROUTING_CAMPAIGN_REDEFINED"):
            validate_bootstrap_history([changed], [grant])
        del grant["campaign"]
        with pytest.raises(KernelError, match="ROUTING_POLICY_SCHEMA_INVALID"):
            validate_routing_policy(policy)
