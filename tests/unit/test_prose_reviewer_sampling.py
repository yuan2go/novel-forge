from copy import deepcopy
from pathlib import Path

import pytest

from novel_forge.modules.book_followup_authority.prose_sample_feedback import (
    PROSE_ANNOTATION_VERSION, PROSE_REVIEWER_DIMENSIONS, prose_annotation_scope,
    prose_reviewer_contract, validate_prose_annotation,
)
from novel_forge.modules.book_followup_authority.prose_sampling import PROSE_SAMPLE_DEFINITION, prose_sample_definition
from novel_forge.modules.command_kernel.errors import KernelError
from tests.unit.test_longform_prose_editorial import manifest, report


def subject():
    frozen = manifest()
    window = frozen["windows"][0]
    return {"producer_contract_hash": "sha256:" + "a" * 64,
        "window": {"manifest_digest": frozen["manifest_digest"], "window": window},
        "content": {"sampled_output": report(frozen, window)}}


def annotation(target):
    span = target["window"]["window"]["spans"][0]
    return {**prose_annotation_scope(producer_contract_hash=target["producer_contract_hash"], window=target["window"]),
        "dimension": PROSE_REVIEWER_DIMENSIONS[0], "evidence": [{
            "manifest_digest": target["window"]["manifest_digest"], "window_id": target["window"]["window"]["window_id"],
            "sample_path": "/findings/0", "observation": "The asserted cost must follow from the quoted action.",
            "asset_version_id": span["asset_version_id"], "text_hash": span["text_hash"],
            "start": span["start"], "end": span["start"] + 2, "quote": span["text"][:2]}]}


@pytest.mark.parametrize("field,value", [("dimension", "coverage"), ("evaluation_version", "older-contract"),
    ("chapter_end", 2), ("protocol_version", "unknown")])
def test_reviewer_labels_bind_four_dimensions_and_exact_producer_scope(field, value):
    target = subject()
    value0 = annotation(target)
    validate_prose_annotation(subject=target, annotation=value0, human=True)
    with pytest.raises(KernelError, match="PROSE_REVIEWER_LABEL_SCOPE_INVALID"):
        validate_prose_annotation(subject=target, annotation={**value0, field: value}, human=True)


@pytest.mark.parametrize("field,value", [("quote", "not the text"), ("sample_path", "/coverage_complete"),
    ("window_id", "another-window"), ("start", -1), ("observation", "")])
def test_reviewer_labels_need_exact_source_and_review_locations(field, value):
    target, value0 = subject(), annotation(subject())
    value0["evidence"][0][field] = value
    with pytest.raises(KernelError, match="PROSE_REVIEWER_LABEL_EVIDENCE_INVALID"):
        validate_prose_annotation(subject=target, annotation=value0, human=True)


def test_sample_pack_keeps_formal_producer_artifacts_and_ineligible_output():
    from novel_forge.modules.book_followup_authority.definitions import book_followup_operation_definitions
    from novel_forge.modules.capability_packs.longform_profiles import build_longform_prose_review_pack_profile, build_longform_prose_review_sample_pack_profile
    from novel_forge.modules.capability_packs.operation_catalog import governed_workflow_binding_catalog
    from novel_forge.modules.content_authority.definitions import content_operation_definitions
    from novel_forge.storage.authority_repositories import definition_hash

    args = {"application_build_id": "sample-test", "commit_sha": "e" * 40}
    formal_definition = next(item for item in book_followup_operation_definitions(**args) if item["name"] == "longform.prose_review")
    definition = prose_sample_definition(**args)
    formal = build_longform_prose_review_pack_profile(Path(__file__).resolve().parents[2], operation_definition_hash=definition_hash(formal_definition))
    sample = build_longform_prose_review_sample_pack_profile(formal, operation_definition_hash=definition_hash(definition))
    assert sample.artifact_catalog == formal.artifact_catalog
    assert sample.manifest["identity"]["version"] == formal.manifest["identity"]["version"] == "1.3.0"
    assert sample.manifest["workflow_template"]["workflow_version"] == "1.0.0"
    assert sample.workflow_ref != formal.workflow_ref
    assert definition["completion_contract"]["required_asset_selectors"][0]["eligibility"] == "INELIGIBLE"
    assert definition["projection_consumers"] == ["independent_prose_reviewer_benchmark"]
    assert governed_workflow_binding_catalog(*sample.workflow_ref.split("@")).resolve("longform_prose_review").operation_name == PROSE_SAMPLE_DEFINITION
    annotations = content_operation_definitions(**args, reference_annotations=True, prose_reference_annotations=True)
    assert {item["definition_version"] for item in annotations} == {PROSE_ANNOTATION_VERSION}
    scope1 = prose_annotation_scope(producer_contract_hash=subject()["producer_contract_hash"], window=subject()["window"])
    changed = deepcopy(subject()["window"])
    changed["window"]["window_id"] = "different"
    assert prose_annotation_scope(producer_contract_hash=subject()["producer_contract_hash"], window=changed) != scope1
    assert prose_reviewer_contract(subject()["producer_contract_hash"])["dimensions"] == list(PROSE_REVIEWER_DIMENSIONS)


def test_prose_sample_requires_separate_reference_purpose_and_exact_frozen_binding():
    from novel_forge.modules.command_kernel.routing_bootstrap import validate_bootstrap_authorization
    from novel_forge.modules.production_execution.routing_policy import validate_routing_policy
    from tests.unit.test_routing_bootstrap import campaign_grant

    grant = {**campaign_grant(), "task_type": "longform_prose_review"}
    with pytest.raises(ValueError, match="ROUTING_REFERENCE_AUTHORIZATION_REQUIRED"):
        validate_bootstrap_authorization(grant)
    grant.update(purpose="REFERENCE_EVALUATION", reference_evaluation={
        "protocol_version": "prose-reviewer-independent-quality.v1", "asset_version_id": "window:v1",
        "content_hash": "sha256:" + "a" * 64})
    validate_bootstrap_authorization(grant)
    validate_routing_policy({"policy_version": "prose-test", "reason": "fixture", "task_overrides": [], "bootstrap_authorizations": [grant]})


@pytest.mark.parametrize("state,effects,budgets", [
    ("SUCCEEDED", ["SUCCEEDED"], ["SETTLED"]),
    ("FAILED_FINAL", ["UNKNOWN"], ["HELD_UNKNOWN"]),
    ("FAILED_FINAL", ["FAILED_FINAL"], ["HELD_UNKNOWN"]),
    ("RUNNING", [], []),
])
def test_prose_sampling_replacement_never_overwrites_success_or_unknown(state, effects, budgets):
    from novel_forge.modules.book_followup_authority.prose_sampling import ProseReviewSampleCommand, _require_predecessor

    class Cursor:
        def execute(self, *args):
            pass

        def fetchall(self):
            return next(self.rows)

    command = ProseReviewSampleCommand("project", "actor", "source", "grant", "new-request", "previous")
    payload = {"prose_sampling": {"source_operation_id": "source"}, "input_versions": ["window"],
        "reference_evaluation": {"protocol_version": "test"}, "routing_bootstrap_authorization": {"authorization": {
            "campaign": {"campaign_id": "campaign", "sample_id": "sample"}, "candidate_id": "candidate", "model_revision": "revision"}}}
    cursor = Cursor()
    cursor.rows = iter([[('previous', state, "actor", "old-request", payload)], [(v,) for v in effects], [(v,) for v in budgets]])
    with pytest.raises(KernelError, match="PROSE_SAMPLE_PREDECESSOR_NOT_REPLACEABLE"):
        _require_predecessor(cursor, command=command, payload=payload)


def test_native_prose_budget_keeps_remote_range_and_authorizes_its_upper_bound():
    from novel_forge.modules.command_kernel.creative_budget_scope import classify_business_scope, require_business_scope
    from tests.unit.test_single_book_budget_contract import single_book_policy

    frozen = {"chapter_start": 1, "chapter_end": 8, "manifest_digest": "exact-manifest", "spans": [
        {"chapter_number": 1, "acceptance_id": "accept-1", "asset_version_id": "draft-1:v1"},
        {"chapter_number": 8, "acceptance_id": "accept-8", "asset_version_id": "draft-8:v1"}]}
    identity = {"operation_name": "longform.prose_review", "capability": "model.longform_prose_review", "attempt_no": 1,
        "command_payload": {"payload": {}}, "request_payload": {"stage": "longform_prose_review", "input": {},
            "_production_execution": {"chapter": 0}}, "native_prose_scope": frozen}
    scope = classify_business_scope(identity)
    assert scope["chapter_number"] == 8 and scope["phase"] == "CREATION_LATE"
    assert scope["scope_sources"][-1]["value"] == frozen
    assert classify_business_scope(identity, dispatch_generation=2)["phase"] == "REPAIR"
    require_business_scope(single_book_policy(chapter=8), scope)
    with pytest.raises(KernelError, match="CREATIVE_BUDGET_BUSINESS_SCOPE_DENIED"):
        require_business_scope(single_book_policy(chapter=7), scope)
    identity.pop("native_prose_scope")
    with pytest.raises(KernelError, match="CREATIVE_BUDGET_BUSINESS_SCOPE_UNKNOWN"):
        classify_business_scope(identity)


@pytest.mark.parametrize("status,interval,score", [("PASSED", [85, 90], 0.85), ("FAILED", [85, 90], 0.0), ("PASSED", [0, 100], None)])
def test_independent_reviewer_projection_uses_only_adjudicated_lower_bounds(monkeypatch, status, interval, score):
    import novel_forge.modules.book_followup_authority.prose_sample_feedback as feedback
    import novel_forge.modules.chapter_quality_authority.reference_sampling as references
    from novel_forge.modules.command_kernel.routing_bootstrap import authorization_hash

    producer = {"prompt": "test-contract"}
    target = {**subject(), "producer_contract_hash": authorization_hash(producer), "generation_operation_id": "sample-op",
        "generation_actor_id": "sample-actor", "source_actor_id": "source-actor"}
    scope = prose_annotation_scope(producer_contract_hash=target["producer_contract_hash"], window=target["window"])
    human = {**annotation(target), "dimension": "finding_precision"}
    adjudication = {**scope, "dimension": "finding_precision", "source_human_evaluation_asset_version_ids": ["human"]}
    labels = [{"dimension": dim, "score_range": interval, "status": status} for dim in PROSE_REVIEWER_DIMENSIONS]
    request = {"_production_execution": {"capability_runtime": {"routing_decision": {"task": {
        "task_type": "longform_prose_review", "producer_contract": producer, "producer_contract_hash": authorization_hash(producer),
        "input_tokens": 3200}, "policy": {"risk": "MEDIUM"}}}}}

    class Cursor:
        def execute(self, *args):
            pass

        def fetchall(self):
            return next(self.rows)

        def fetchone(self):
            return ("attempt",)

    cursor = Cursor()
    cursor.rows = iter([[("effect", "sample-op", request, "sample", "digest")], [("label", "label-hash")]])
    monkeypatch.setattr(feedback, "require_prose_reference_subject", lambda *a, **kw: target)
    monkeypatch.setattr(references, "reference_provider_result", lambda *a, **kw: {
        "real_model_call": True, "result": target["content"]["sampled_output"], "model_call_asset_version_id": "model-log"})
    monkeypatch.setattr(references, "require_adjudicated_reference", lambda *a, **kw: {"labels": labels})
    monkeypatch.setattr(references, "reference_label_classes", lambda *a, **kw: ("PASS",))
    monkeypatch.setattr(references, "_native_label", lambda *a, **kw: (
        human if kw["asset_type"] == "human_evaluation" else adjudication, "unused-hash", "unused-actor"))
    actual = feedback.prose_sample_outcomes(cursor, project_id="project", effect_ids=["effect"])
    if score is None:
        assert actual == {}
    else:
        projected = actual["effect"]
        assert projected["independent_quality_score"] == score
        assert projected["independent_protocol_hash"] == authorization_hash(prose_reviewer_contract(authorization_hash(producer)))
        assert projected["accepted"] is None and projected["sample_promoted"] is False
        assert projected["evidence_refs"] == ["asset-version:sample", "asset-version:model-log", "asset-version:label"]
        assert not any(key.startswith("generator_") for key in projected)


def test_native_sample_api_uses_trusted_actor_and_rejects_wrong_book_or_grant(monkeypatch):
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import novel_forge.api.routers.prose_review as routes

    principal = SimpleNamespace(principal_id="trusted-operator")
    calls = []
    prepared = {"command_payload": {"book_run_id": "book-run"}, "provider_calls": 0}

    def prepare(command, **kwargs):
        calls.append(("prepare", command, kwargs["principal"]))
        if command.project_id == "denied":
            raise PermissionError("sample permission denied")
        return prepared

    def admit(command, **kwargs):
        calls.append(("admit", command, kwargs["principal"]))
        if command.authorization_id == "missing":
            raise KernelError("ROUTING_BOOTSTRAP_AUTHORIZATION_REQUIRED", "explicit reference grant required")
        return {"operation_id": "native-sample", "production_eligible": False}

    followup = SimpleNamespace(prepare_prose_sample=prepare, admit_prose_sample=admit)
    ctx = SimpleNamespace(services=SimpleNamespace(book_production=SimpleNamespace(followup=followup)))
    monkeypatch.setattr(routes, "build_trusted_principal_resolver", lambda: SimpleNamespace(resolve_api_principal=lambda: principal))
    app = FastAPI()
    app.include_router(routes.create_router(ctx))
    client = TestClient(app)
    path = "/product/production/book-authority/runs/book-run/prose-reviews/provider-samples"
    payload = {"project_id": "project", "source_operation_id": "native-review", "authorization_id": "grant", "idempotency_key": "sample-1"}
    assert client.post(path + "?dry_run=true", json=payload).json() == prepared
    assert [call[0] for call in calls] == ["prepare"]
    assert client.post(path, json=payload).json()["operation_id"] == "native-sample"
    assert all(call[1].actor_id == "trusted-operator" and call[2] is principal for call in calls)
    admissions = sum(call[0] == "admit" for call in calls)
    assert client.post(path.replace("book-run", "wrong-book"), json=payload).status_code == 409
    assert sum(call[0] == "admit" for call in calls) == admissions
    assert client.post(path, json={**payload, "project_id": "denied"}).status_code == 403
    response = client.post(path, json={**payload, "authorization_id": "missing"})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "ROUTING_BOOTSTRAP_AUTHORIZATION_REQUIRED"
    assert client.post(path, json={**payload, "actor_id": "forged-actor"}).status_code == 422
