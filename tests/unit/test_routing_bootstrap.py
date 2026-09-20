from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.routing_bootstrap import (
    authorization_hash,
    bootstrap_command_hash,
    validate_bootstrap_scope,
)
from novel_forge.modules.production_execution.cost_routing import (
    CostAwareRouter,
    ModelCandidate,
    PricingSnapshot,
    RoutingTask,
)
from novel_forge.modules.production_execution.routing_bootstrap import (
    benchmark_decision,
)
from novel_forge.modules.production_execution.routing_policy import (
    validate_routing_policy,
)


def contract():
    payload = {
        "project_id": "project",
        "book_id": "book",
        "generator_operation_name": "world_candidates.generate",
        "logical_key": "world",
        "idempotency_key": "sample-one",
        "input_versions": {"brief": "version-one"},
        "routing_bootstrap_authorization_id": "grant-one",
    }
    grant = {
        "authorization_id": "grant-one",
        "reason": "independent benchmark collection",
        "environment": "validation",
        "book_id": "book",
        "task_type": "world_candidates.generate",
        "logical_key": "world",
        "generation_idempotency_key": "sample-one",
        "input_versions_hash": authorization_hash(payload["input_versions"]),
        "command_hash": bootstrap_command_hash(payload),
        "candidate_id": "flash",
        "model_revision": "revision-one",
        "expires_at": "2099-01-01T00:00:00+00:00",
        "maximum_calls": 1,
        "maximum_tokens": 2000,
        "maximum_amount": "0.01",
        "currency": "USD",
        "purpose": "BENCHMARK_CHALLENGER",
        "production_eligible": False,
    }
    snapshot = {
        "project_id": "project",
        "environment": "validation",
        "authorization": grant,
        "authorization_hash": authorization_hash(grant),
    }
    return payload, grant, snapshot


def ordinary_decision(**candidate_overrides):
    candidate = ModelCandidate(
        "flash",
        "deepseek",
        "deepseek-flash",
        "low",
        "flash",
        ("structured_output",),
        10000,
        2000,
        PricingSnapshot(
            "price-one",
            "2026-01-01T00:00:00+00:00",
            "2099-01-01T00:00:00+00:00",
            "1",
            "0.1",
            "2",
            source="official",
        ),
        "capability-one",
        model_revision="revision-one",
    )
    task = RoutingTask(
        "world_candidates.generate",
        "project",
        "book",
        "operation",
        "attempt",
        1000,
        100,
        2000,
        ".01",
    )
    return CostAwareRouter().explain(
        task,
        [replace(candidate, **candidate_overrides)],
        {},
        now=datetime(2026, 9, 16, tzinfo=timezone.utc),
    )


def test_benchmark_grant_preserves_unknown_quality_and_production_rejections():
    _, _, snapshot = contract()
    ordinary = ordinary_decision()
    assert ordinary.to_dict()["status"] == "BLOCKED"
    sampled = benchmark_decision(ordinary, snapshot, environment="validation").to_dict()
    assert sampled["status"] == "BENCHMARK_SELECTED"
    assert sampled["production_eligible"] is False
    assert (
        sampled["selected"]["expected_quality"]
        == ordinary.to_dict()["candidates"][0]["expected_quality"]
    )
    assert set(sampled["selected"]["production_rejected_reasons"]) == {
        "BENCHMARK_INSUFFICIENT",
        "QUALITY_FLOOR_NOT_MET",
    }
    assert sampled["policy"]["quality_floor"] == 0.75
    assert sampled["decision_id"] != ordinary.decision_id
    with pytest.raises(KernelError, match="validation runtime"):
        benchmark_decision(ordinary, snapshot, environment="production")
    with pytest.raises(KernelError, match="authorized task"):
        benchmark_decision(
            ordinary,
            {**snapshot, "project_id": "another-project"},
            environment="validation",
        )


@pytest.mark.parametrize(
    "overrides,reason",
    [
        ({"available": False}, "PROVIDER_UNAVAILABLE:"),
        ({"context_limit": 100}, "CONTEXT_CAPACITY_EXCEEDED"),
        ({"model_revision": "revision-two"}, "BENCHMARK_AUTHORIZED_TARGET_MISMATCH"),
    ],
)
def test_benchmark_grant_never_relaxes_availability_capacity_or_revision(
    overrides, reason
):
    _, _, snapshot = contract()
    result = benchmark_decision(
        ordinary_decision(**overrides), snapshot, environment="validation"
    ).to_dict()
    assert result["status"] == "BLOCKED"
    assert reason in result["candidates"][0]["rejected_reasons"]


def test_grant_is_exact_scoped_and_expiry_does_not_reinterpret_completed_replay():
    payload, grant, snapshot = contract()
    validate_bootstrap_scope(snapshot, payload)
    with pytest.raises(KernelError, match="admitted task"):
        validate_bootstrap_scope(
            snapshot, {**payload, "input_versions": {"brief": "version-two"}}
        )
    with pytest.raises(KernelError, match="admitted task"):
        validate_bootstrap_scope(
            snapshot,
            {**payload, "narrative_intelligence_package_id": "different-context"},
        )
    grant["expires_at"] = "2020-01-01T00:00:00+00:00"
    snapshot["authorization_hash"] = authorization_hash(grant)
    with pytest.raises(KernelError, match="expired"):
        validate_bootstrap_scope(snapshot, payload)
    validate_bootstrap_scope(snapshot, payload, check_expiry=False)


def test_governed_policy_rejects_unsafe_or_duplicate_grants():
    _, grant, _ = contract()
    policy = {
        "policy_version": "routing-one",
        "reason": "benchmark collection",
        "task_overrides": [],
        "bootstrap_authorizations": [grant],
    }
    validate_routing_policy(policy)
    for changed in (
        {"production_eligible": True},
        {"maximum_calls": 0},
        {"maximum_amount": "NaN"},
        {"environment": "production"},
        {"task_type": "classification"},
    ):
        with pytest.raises(KernelError):
            validate_routing_policy(
                {**policy, "bootstrap_authorizations": [{**grant, **changed}]}
            )
    with pytest.raises(KernelError):
        validate_routing_policy({**policy, "bootstrap_authorizations": [grant, grant]})


@pytest.mark.parametrize(
    "identity",
    [
        ("source.classify", "1.16.0", "book:story-planning-generation", "sample-one"),
        (
            "story_planning.generate",
            "1.15.0",
            "book:story-planning-generation",
            "sample-one",
        ),
        ("story_planning.generate", "1.16.0", "other-scope", "sample-one"),
        (
            "story_planning.generate",
            "1.16.0",
            "book:story-planning-generation",
            "other-request",
        ),
    ],
)
def test_bootstrap_requires_canonical_admitted_operation_contract(identity):
    from novel_forge.modules.command_kernel.routing_bootstrap import (
        load_bootstrap_authorization,
    )

    payload, _, snapshot = contract()
    payload["routing_bootstrap_authorization"] = snapshot

    class Cursor:
        def execute(self, *_args):
            pass

        def fetchone(self):
            return (payload, *identity)

    with pytest.raises(KernelError, match="ROUTING_BOOTSTRAP_SCOPE_MISMATCH"):
        load_bootstrap_authorization(
            Cursor(), project_id="project", operation_id="operation"
        )


def test_multistage_challenger_is_rejected_before_database_or_execution():
    from novel_forge.modules.authority_handler_runtime.routing_bootstrap import (
        freeze_planning_bootstrap_authorization,
    )

    payload, _, _ = contract()
    with pytest.raises(KernelError, match="one Planning generation stage"):
        freeze_planning_bootstrap_authorization(
            database_url="postgresql://must-not-connect",
            command_payload={
                **payload,
                "world_preparation_request": {"requested": True},
            },
            principal=SimpleNamespace(require=lambda *_: None),
            environment="validation",
        )


def campaign_grant():
    _, grant, _ = contract()
    return {**grant, "campaign": {
        "campaign_id": "campaign-one", "manifest_hash": "sha256:" + "c" * 64,
        "sample_id": "sample-one", "group_id": "work-one", "partition": "CALIBRATION",
        "maximum_calls": 4, "maximum_tokens": 8000, "maximum_amount": "0.04",
        "expires_at": grant["expires_at"],
    }}


def test_campaign_grants_share_frozen_identity_across_policy_versions():
    from novel_forge.modules.command_kernel.routing_bootstrap import validate_bootstrap_history
    grant = campaign_grant()
    validate_bootstrap_history([grant], [grant])
    other = {**grant, "authorization_id": "grant-two", "candidate_id": "pro"}
    validate_bootstrap_history([other], [grant])
    for change in ({"manifest_hash": "sha256:" + "d" * 64}, {"maximum_calls": 8}):
        with pytest.raises(KernelError, match="ROUTING_CAMPAIGN_REDEFINED"):
            validate_bootstrap_history(
                [{**other, "campaign": {**other["campaign"], **change}}], [grant])
    with pytest.raises(KernelError, match="AUTHORIZATION_REDEFINED"):
        validate_bootstrap_history([{**grant, "maximum_calls": 2}], [grant])
    with pytest.raises(KernelError, match="PROJECT_REBIND_FORBIDDEN"):
        validate_bootstrap_history([{**other, "campaign": {
            **other["campaign"], "campaign_id": "reset-attempt"}}], [grant])


@pytest.mark.parametrize("rename", [False, True])
def test_campaign_rejects_holdout_leakage_even_with_renamed_sample(rename):
    from novel_forge.modules.command_kernel.routing_bootstrap import validate_bootstrap_history
    grant = campaign_grant()
    changed = {**grant, "authorization_id": "holdout-grant", "campaign": {
        **grant["campaign"], "partition": "HOLDOUT",
        "sample_id": "renamed" if rename else "sample-one",
        "group_id": "renamed-work" if rename else "work-one",
    }}
    with pytest.raises(KernelError, match="HOLDOUT_LEAKAGE"):
        validate_bootstrap_history([changed], [grant])


def test_campaign_rejects_relabelled_sample_input_and_nonfinite_budget():
    from novel_forge.modules.command_kernel.routing_bootstrap import (
        validate_bootstrap_authorization, validate_bootstrap_history,
    )
    grant = campaign_grant()
    validate_bootstrap_authorization(grant)
    with pytest.raises(KernelError, match="SAMPLE_REDEFINED"):
        validate_bootstrap_history([
            {**grant, "authorization_id": "new", "input_versions_hash": "sha256:" + "f" * 64}
        ], [grant])
    for change in ({"maximum_amount": "NaN"}, {"maximum_amount": True}, {"maximum_amount": 1.0}, {"maximum_calls": True},
                   {"maximum_tokens": 0}, {"partition": "unknown"},
                   {"expires_at": "2099-01-01"}):
        with pytest.raises((ValueError, ArithmeticError)):
            validate_bootstrap_authorization({**grant, "campaign": {**grant["campaign"], **change}})
    with pytest.raises(ValueError, match="GRANT_EXCEEDS_TOTAL"):
        validate_bootstrap_authorization({**grant, "maximum_calls": 5})


def test_campaign_cannot_be_evaded_by_a_new_unbound_authorization():
    from novel_forge.modules.command_kernel.routing_bootstrap import validate_bootstrap_history
    grant = campaign_grant()
    legacy = {key: value for key, value in grant.items() if key != "campaign"}
    legacy["authorization_id"] = "legacy"
    validate_bootstrap_history([grant, legacy], [legacy])
    with pytest.raises(KernelError, match="CAMPAIGN_MEMBERSHIP_REQUIRED"):
        validate_bootstrap_history([legacy], [grant])
    with pytest.raises(KernelError, match="CAMPAIGN_MEMBERSHIP_REQUIRED"):
        validate_bootstrap_history([grant, legacy], [])


def test_identical_inputs_cannot_be_relabelled_as_an_independent_data_group():
    from novel_forge.modules.command_kernel.routing_bootstrap import validate_bootstrap_history
    grant = campaign_grant()
    renamed = {**grant, "authorization_id": "renamed-grant", "campaign": {
        **grant["campaign"], "sample_id": "renamed-sample", "group_id": "renamed-work"}}
    with pytest.raises(KernelError, match="INPUT_GROUP_REDEFINED"):
        validate_bootstrap_history([renamed], [grant])


def test_reference_grant_requires_exact_labels_and_campaign_isolation():
    payload, grant, snapshot = contract()
    reference = {"asset_version_id": "labels-v1", "content_hash": "sha256:" + "f" * 64,
                 "protocol_version": "independent-proxy-v1"}
    payload["reference_evaluation"] = reference
    grant.update(task_type="narrative_semantic_evaluation", purpose="REFERENCE_EVALUATION",
                 reference_evaluation=reference, command_hash=bootstrap_command_hash(payload),
                 campaign={"campaign_id": "campaign", "manifest_hash": "sha256:" + "a" * 64,
                           "sample_id": "sample", "group_id": "group", "partition": "CALIBRATION",
                           "maximum_calls": 1, "maximum_tokens": 2000, "maximum_amount": "0.01",
                           "expires_at": grant["expires_at"]})
    snapshot["authorization_hash"] = authorization_hash(grant)
    validate_bootstrap_scope(snapshot, payload)
    validate_routing_policy({"policy_version": "reference-v1", "reason": "reference sampling",
                             "task_overrides": [], "bootstrap_authorizations": [grant]})
    for change in ({"reference_evaluation": {**reference, "asset_version_id": "other"}},
                   {"reference_evaluation": None}):
        with pytest.raises(KernelError, match="admitted task"):
            validate_bootstrap_scope(snapshot, {**payload, **change})
    with pytest.raises(KernelError):
        validate_routing_policy({"policy_version": "reference-v2", "reason": "invalid reference",
                                "task_overrides": [], "bootstrap_authorizations": [
                                    {**grant, "purpose": "BENCHMARK_CHALLENGER"}]})


def test_reference_agreement_counts_disagreement_without_production_or_human_claims():
    from copy import deepcopy
    from novel_forge.modules.story_design_authority import scripted_qualification
    from novel_forge.modules.story_design_authority.evaluation_reference import reference_agreement

    expected = scripted_qualification("book_plan.generate")
    observed = deepcopy(expected)
    criterion = observed["evaluations"][0]["criteria"][0]
    criterion.update(verdict="FAIL", repair_directive="fixture negative contrast")
    report = reference_agreement(
        payload={"generator_operation_name": "book_plan.generate", "reference_evaluation": {
            "asset_version_id": "labels", "content_hash": "sha256:" + "a" * 64,
            "protocol_version": "proxy-v1"}},
        reference={"content": {"evaluation": expected}, "operation_id": "label-op",
                   "author_actor_id": "reference-operator"}, evaluation=observed,
    )
    assert sum(not item["agrees"] for item in report["criterion_agreement"]) == 1
    assert 0 < report["agreement_rate"] < 1
    assert report["production_qualification_eligible"] is False
    assert report["ground_truth_claimed"] is False
    assert report["human_preference_evidence"] is False
