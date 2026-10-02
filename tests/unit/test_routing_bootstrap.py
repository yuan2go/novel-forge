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
        "generator_operation_name": "book_plan.generate",
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
        "task_type": "book_plan.generate",
        "logical_key": "world",
        "generation_idempotency_key": "sample-one",
        "input_versions_hash": authorization_hash(payload["input_versions"]),
        "command_hash": bootstrap_command_hash(payload),
        "producer_contract_hash": authorization_hash({"fixture_prompt": "v1"}),
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


@pytest.mark.parametrize("source_version", ["3.4.1", "3.5.0"])
def test_chapter_sample_rejects_changed_source_inputs_or_book_scope(source_version):
    from copy import deepcopy
    from novel_forge.modules.command_kernel.routing_bootstrap import validate_chapter_sample_origin

    source = {"book_id": "book", "chapter": 3, "preparation_report": {"craft": "approved"}}
    inputs = [{"asset_version_id": "context:v1", "content_hash": "sha256:" + "a" * 64}]
    origin = ("chapter.draft.generate", source_version, source, inputs)
    payload = {
        **source, "project_id": "project", "generator_operation_name": "draft",
        "logical_key": "native-draft", "idempotency_key": "sample-1",
        "input_versions": inputs, "routing_bootstrap_authorization_id": "grant",
        "chapter_predecessor_operation_id": "",
        "chapter_sampling": {"source_operation_id": "native-draft", "source_command_hash": authorization_hash(source)},
    }
    validate_chapter_sample_origin(payload, origin, project_id="project")
    for key, value in (("book_id", "another-book"), ("chapter", 4),
                       ("input_versions", []), ("generator_operation_name", "memo"),
                       ("preparation_report", {}), ("unexpected_override", True)):
        changed = deepcopy(payload)
        changed[key] = value
        with pytest.raises(KernelError, match="ROUTING_BOOTSTRAP_SCOPE_MISMATCH"):
            validate_chapter_sample_origin(changed, origin, project_id="project")
    with pytest.raises(KernelError, match="ROUTING_BOOTSTRAP_SCOPE_MISMATCH"):
        validate_chapter_sample_origin(payload, (origin[0], "3.3.0", source, inputs), project_id="project")
    target = {"asset_version_id": "sample:v1", "content_hash": "sha256:" + "b" * 64}
    reference = {**payload, "generator_operation_name": "review", "input_versions": [*inputs, target],
        "chapter_sampling": {**payload["chapter_sampling"], "generation_sample": target},
        "reference_evaluation": {"protocol_version": "frozen-labels", "adjudications": []}}
    validate_chapter_sample_origin(reference, origin, project_id="project")
    for key, value in (("generator_operation_name", "rereview"), ("input_versions", [target]),
                       ("preparation_report", {})):
        with pytest.raises(KernelError, match="ROUTING_BOOTSTRAP_SCOPE_MISMATCH"):
            validate_chapter_sample_origin({**reference, key: value}, origin, project_id="project")


def ordinary_decision(*, task_overrides=None, **candidate_overrides):
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
        "book_plan.generate",
        "project",
        "book",
        "operation",
        "attempt",
        1000,
        100,
        2000,
        ".01",
        producer_contract={"fixture_prompt": "v1"},
        producer_contract_hash=authorization_hash({"fixture_prompt": "v1"}),
    )
    return CostAwareRouter().explain(
        replace(task, **(task_overrides or {})),
        [replace(candidate, **candidate_overrides)],
        {},
        now=datetime(2026, 9, 16, tzinfo=timezone.utc),
    )


def entitlement_grant():
    return {**campaign_grant(), "accounting_basis": "ACCOUNT_ENTITLEMENT",
            "cost_authorization_ref": "fixture-codex-account", "currency": "UNKNOWN", "maximum_amount": None}


def codex_benchmark_decision(*, candidate_overrides=None, task_overrides=None, grant_overrides=None):
    grant = {**entitlement_grant(), **(grant_overrides or {})}
    _, _, snapshot = contract()
    snapshot.update(authorization=grant, authorization_hash=authorization_hash(grant))
    ordinary = ordinary_decision(
        **{"provider": "codex-cli", "model": "fixture-codex-model", "escalation_only": True,
           "quota_remaining": 1, "authorization_ref": "fixture-codex-account",
           "pricing": PricingSnapshot("fixture-account-v1", "2026-01-01T00:00:00+00:00",
               "2099-01-01T00:00:00+00:00", "0", "0", "0", currency="UNKNOWN", source="fixture-account",
               accounting_basis="ACCOUNT_ENTITLEMENT"), **(candidate_overrides or {})},
        task_overrides={"risk": "HIGH", "escalation_reason": "authorized high-risk calibration control", **(task_overrides or {})},
    )
    return ordinary, benchmark_decision(ordinary, snapshot, environment="validation").to_dict()


def test_codex_sampling_retains_unknown_money_and_production_escalation_restrictions():
    ordinary, sampled = codex_benchmark_decision()
    assert ordinary.to_dict()["status"] == "BLOCKED"
    assert sampled["status"] == "BENCHMARK_SELECTED"
    assert sampled["production_eligible"] is False
    assert sampled["selected"]["reservation_upper_bound"] is None
    assert "BENCHMARK_INSUFFICIENT" in sampled["selected"]["production_rejected_reasons"]
    _, blocked = codex_benchmark_decision(task_overrides={"escalation_reason": ""})
    assert blocked["status"] == "BLOCKED"
    assert "ESCALATION_THRESHOLD_NOT_MET" in blocked["candidates"][0]["rejected_reasons"]


def test_exact_source_entitlement_sample_selects_model_without_production_escalation():
    scope = {"task_type": "source.deconstruction.observe", "work_id": "source-corpus:project",
             "risk": "MEDIUM", "escalation_reason": ""}
    grant = {"task_type": scope["task_type"], "book_id": scope["work_id"]}
    ordinary, sampled = codex_benchmark_decision(task_overrides=scope, grant_overrides=grant)
    assert ordinary.to_dict()["status"] == "BLOCKED"
    assert "ESCALATION_THRESHOLD_NOT_MET" in ordinary.to_dict()["candidates"][0]["rejected_reasons"]
    assert sampled["status"] == "BENCHMARK_SELECTED"
    assert sampled["production_eligible"] is False
    assert sampled["task"]["risk"] == "MEDIUM"
    for invalid in ({"quota_remaining": 0}, {"authorization_ref": "other"},
                    {"context_limit": 500}, {"available": False}):
        _, rejected = codex_benchmark_decision(task_overrides=scope, grant_overrides=grant,
                                              candidate_overrides=invalid)
        assert rejected["status"] == "BLOCKED"
    _, production_scope = codex_benchmark_decision(task_overrides={**scope, "work_id": "book"},
                                                   grant_overrides={**grant, "book_id": "book"})
    assert production_scope["status"] == "BLOCKED"


def test_zero_router_money_cap_retains_entitlement_identity_quota_and_unknown_cost():
    from novel_forge.modules.production_execution.routing_runtime import ProductionProviderRouter

    router = ProductionProviderRouter("unused", candidates=(), task_money_limit="0", task_token_limit=4096)
    _, sampled = codex_benchmark_decision(task_overrides={"remaining_money": router.task_money_limit})
    assert sampled["status"] == "BENCHMARK_SELECTED"
    assert sampled["selected"]["candidate"]["pricing"]["accounting_basis"] == "ACCOUNT_ENTITLEMENT"
    assert sampled["selected"]["candidate"]["pricing"]["currency"] == "UNKNOWN"
    assert sampled["selected"]["reservation_upper_bound"] is None
    assert sampled["production_eligible"] is False
    for invalid in ({"quota_remaining": 0}, {"authorization_ref": "another-account"}):
        _, blocked = codex_benchmark_decision(task_overrides={"remaining_money": "0"}, candidate_overrides=invalid)
        assert blocked["status"] == "BLOCKED"


def test_zero_router_money_cap_rejects_priced_spending_and_invalid_limits():
    from novel_forge.modules.production_execution.routing_runtime import ProductionProviderRouter

    _, _, snapshot = contract()
    ordinary = ordinary_decision(task_overrides={"remaining_money": "0"})
    blocked = benchmark_decision(ordinary, snapshot, environment="validation").to_dict()
    assert blocked["status"] == "BLOCKED"
    assert "BUDGET_HARD_LIMIT" in blocked["candidates"][0]["rejected_reasons"]
    assert ProductionProviderRouter("unused", candidates=(), task_money_limit="1", task_token_limit=4096).task_money_limit == "1"
    for money, tokens in (("-1", 4096), ("NaN", 4096), ("Infinity", 4096), ("0", 0)):
        with pytest.raises(ValueError, match="ROUTING_NONNEGATIVE_MONEY_AND_POSITIVE_TOKEN_BUDGET_REQUIRED"):
            ProductionProviderRouter("unused", candidates=(), task_money_limit=money, task_token_limit=tokens)


@pytest.mark.parametrize("changes,reason", [
    ({"available": False}, "PROVIDER_UNAVAILABLE:"),
    ({"quota_remaining": 0}, "ESCALATION_CAPACITY_OR_AUTHORIZATION_MISSING"),
    ({"authorization_ref": "another-account"}, "BENCHMARK_ACCOUNTING_AUTHORIZATION_MISMATCH"),
    ({"model_revision": "changed-model"}, "BENCHMARK_AUTHORIZED_TARGET_MISMATCH"),
    ({"escalation_only": False}, "BENCHMARK_ACCOUNTING_AUTHORIZATION_MISMATCH"),
])
def test_codex_sampling_cannot_bypass_account_quota_availability_or_identity(changes, reason):
    _, result = codex_benchmark_decision(candidate_overrides=changes)
    assert result["status"] == "BLOCKED"
    assert reason in result["candidates"][0]["rejected_reasons"]


@pytest.mark.parametrize("changes", [
    {"maximum_amount": "0"}, {"currency": "USD"}, {"cost_authorization_ref": ""},
    {"accounting_basis": "PRICED"}, {"maximum_tokens": 0},
])
def test_entitlement_sampling_never_accepts_zero_usd_or_missing_authority(changes):
    from novel_forge.modules.command_kernel.routing_bootstrap import validate_bootstrap_authorization

    with pytest.raises(ValueError):
        validate_bootstrap_authorization({**entitlement_grant(), **changes})
    with pytest.raises(ValueError):
        validate_bootstrap_authorization({key: value for key, value in entitlement_grant().items() if key != "campaign"})


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
    assert sampled["policy"]["quality_floor"] == ordinary.to_dict()["policy"]["quality_floor"]
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


def test_world_sampling_requires_campaign_and_separate_reference_authority():
    from novel_forge.modules.command_kernel.routing_bootstrap import validate_bootstrap_authorization

    grant = {**contract()[1], "task_type": "world_candidates.generate"}
    with pytest.raises(ValueError, match="ROUTING_WORLD_CAMPAIGN_REQUIRED"):
        validate_bootstrap_authorization(grant)
    validate_bootstrap_authorization({**campaign_grant(), "task_type": "world_candidates.generate"})
    with pytest.raises(ValueError, match="ROUTING_REFERENCE_AUTHORIZATION_REQUIRED"):
        validate_bootstrap_authorization({**campaign_grant(), "task_type": "world_candidates.evaluate"})
    reference = {**campaign_grant(), "task_type": "world_candidates.evaluate", "purpose": "REFERENCE_EVALUATION",
        "reference_evaluation": {"protocol_version": "fixture-reference-v1",
            "adjudications": [{"asset_version_id": "fixture-label", "content_hash": "sha256:" + "a" * 64}]}}
    validate_bootstrap_authorization(reference)
    from novel_forge.modules.production_execution.routing_policy import validate_routing_policy
    validate_routing_policy({"policy_version": "fixture-world-v1", "reason": "fixture", "task_overrides": [],
                             "bootstrap_authorizations": [reference]})


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


def test_reference_model_arms_cannot_relabel_the_same_frozen_sample():
    from novel_forge.modules.command_kernel.routing_bootstrap import validate_bootstrap_history

    first = {**campaign_grant(), "task_type": "narrative_semantic_evaluation", "purpose": "REFERENCE_EVALUATION",
             "reference_evaluation": {"asset_version_id": "reference-one", "content_hash": "sha256:" + "a" * 64,
                                      "protocol_version": "blind-reference-v1"}}
    second = {**first, "authorization_id": "evaluator-two", "candidate_id": "pro"}
    validate_bootstrap_history([second], [first])
    for changed in ({"asset_version_id": "relabeled-reference"}, {"content_hash": "sha256:" + "b" * 64},
                    {"protocol_version": "revised-reference-v2"}):
        with pytest.raises(KernelError, match="ROUTING_CAMPAIGN_SAMPLE_REDEFINED"):
            validate_bootstrap_history([{**second, "reference_evaluation": {**first["reference_evaluation"], **changed}}], [first])


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


def test_adjudicated_reference_binding_requires_exact_scoped_native_labels():
    from copy import deepcopy
    from novel_forge.modules.command_kernel.routing_bootstrap import validate_reference_evaluation_binding

    binding = {"asset_version_id": "proxy:v1", "content_hash": "sha256:" + "a" * 64, "protocol_version": "labels-v2",
        "adjudicated_reference": {"adjudications": [{"asset_version_id": "adjudication:v1", "content_hash": "sha256:" + "b" * 64}],
            "scope": {"scope_type": "ARC", "chapter_start": 1, "chapter_end": 12}}}
    validate_reference_evaluation_binding(binding)
    for change in ("empty", "duplicate", "hash", "scope", "extra", "proxy-missing"):
        bad = deepcopy(binding)
        if change == "empty":
            bad["adjudicated_reference"]["adjudications"] = []
        elif change == "duplicate":
            bad["adjudicated_reference"]["adjudications"] *= 2
        elif change == "hash":
            bad["adjudicated_reference"]["adjudications"][0]["content_hash"] = "unbound"
        elif change == "scope":
            bad["adjudicated_reference"]["scope"]["scope_type"] = "CHAPTER"
        elif change == "extra":
            bad["adjudicated_reference"]["human_verified"] = True
        else:
            del bad["asset_version_id"]
        with pytest.raises(ValueError):
            validate_reference_evaluation_binding(bad)


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


@pytest.mark.parametrize("change", [
    {}, {"prompt_template": {"version": 2}}, {"context_policy": {"version": 2}},
    {"output_schema": {"content_hash": "sha256:" + "f" * 64}},
    {"judge_protocol": "changed"},
])
def test_sampling_rejects_unbound_or_changed_producer_before_selection(change):
    from novel_forge.modules.production_execution.cost_routing import RoutingDecision
    import json

    _, grant, snapshot = contract()
    ordinary = ordinary_decision().to_dict()
    if change:
        ordinary["task"]["producer_contract"] = {**ordinary["task"]["producer_contract"], **change}
        ordinary["task"]["producer_contract_hash"] = authorization_hash(ordinary["task"]["producer_contract"])
    else:
        grant.pop("producer_contract_hash")
        snapshot["authorization_hash"] = authorization_hash(grant)
    with pytest.raises(KernelError, match="ROUTING_BOOTSTRAP_PRODUCER_DRIFT"):
        benchmark_decision(RoutingDecision(json.dumps(ordinary)), snapshot, environment="validation")


def test_legacy_grant_can_be_reconciled_but_cannot_authorize_new_dispatch():
    from novel_forge.modules.command_kernel.routing_bootstrap import validate_bootstrap_producer

    _, grant, _ = contract()
    grant.pop("producer_contract_hash")
    validate_bootstrap_producer(grant, {}, require_bound=False)
    with pytest.raises(KernelError, match="ROUTING_BOOTSTRAP_PRODUCER_DRIFT"):
        validate_bootstrap_producer(grant, {})


def test_campaign_arms_cannot_compare_different_producer_versions():
    from novel_forge.modules.command_kernel.routing_bootstrap import validate_bootstrap_history

    original = campaign_grant()
    changed = {**original, "authorization_id": "new-model-arm", "candidate_id": "pro",
               "producer_contract_hash": authorization_hash({"fixture_prompt": "v2"})}
    with pytest.raises(KernelError, match="ROUTING_CAMPAIGN_SAMPLE_REDEFINED"):
        validate_bootstrap_history([changed], [original])


def test_zero_priced_campaign_cap_allows_authorized_entitlement_but_never_priced_spend():
    from novel_forge.modules.command_kernel.routing_bootstrap import validate_bootstrap_authorization
    grant = entitlement_grant()
    grant["campaign"] = {**grant["campaign"], "maximum_amount": "0"}
    validate_bootstrap_authorization(grant)
    _, sampled = codex_benchmark_decision(grant_overrides=grant)
    assert sampled["status"] == "BENCHMARK_SELECTED"
    assert sampled["selected"]["reservation_upper_bound"] is None
    assert sampled["selected"]["candidate"]["pricing"]["currency"] == "UNKNOWN"
    priced = {**campaign_grant(), "campaign": grant["campaign"]}
    with pytest.raises(ValueError, match="ROUTING_CAMPAIGN_GRANT_EXCEEDS_TOTAL"):
        validate_bootstrap_authorization(priced)
    with pytest.raises(ValueError, match="ROUTING_BOOTSTRAP_LIMIT_INVALID"):
        validate_bootstrap_authorization({**priced, "maximum_amount": "0"})
    with pytest.raises(ValueError, match="ROUTING_CAMPAIGN_LIMIT_INVALID"):
        validate_bootstrap_authorization({**grant, "campaign": {**grant["campaign"], "maximum_amount": "-1"}})


def diagnostic_escalation_fixture():
    ordinary, _ = codex_benchmark_decision(task_overrides={"escalation_reason": ""})
    value = ordinary.to_dict()
    task = RoutingTask(**{**value["task"], "history": tuple(value["task"]["history"])})
    raw_candidate = value["candidates"][0]["candidate"]
    candidate = ModelCandidate(**{**raw_candidate, "pricing": PricingSnapshot(**raw_candidate["pricing"])})
    grant = entitlement_grant()
    _, _, authorization = contract()
    authorization.update(authorization=grant, authorization_hash=authorization_hash(grant))
    return task, candidate, authorization


def test_exact_high_risk_diagnostic_grant_binds_reason_without_changing_production_gates():
    from novel_forge.modules.production_execution.routing_bootstrap import bind_diagnostic_escalation_reason

    task, candidate, authorization = diagnostic_escalation_fixture()
    frozen = bind_diagnostic_escalation_reason(task, [candidate], authorization, environment="validation")
    assert task.escalation_reason == ""
    assert frozen.escalation_reason == authorization["authorization"]["reason"]
    assert frozen.history == task.history == ()
    ordinary = CostAwareRouter().explain(frozen, [candidate], {})
    assert ordinary.to_dict()["status"] == "BLOCKED"
    assert "BENCHMARK_INSUFFICIENT" in ordinary.to_dict()["candidates"][0]["rejected_reasons"]
    sampled = benchmark_decision(ordinary, authorization, environment="validation").to_dict()
    assert sampled["status"] == "BENCHMARK_SELECTED"
    assert sampled["production_eligible"] is False
    with pytest.raises(KernelError, match="ROUTING_BOOTSTRAP_ENVIRONMENT_FORBIDDEN"):
        bind_diagnostic_escalation_reason(task, [candidate], authorization, environment="production")
    for mismatch in ({"project_id": "other"}, {"producer_contract_hash": "sha256:" + "f" * 64}):
        with pytest.raises(KernelError):
            bind_diagnostic_escalation_reason(replace(task, **mismatch), [candidate], authorization, environment="validation")
    for mismatch in ({"model_revision": "other"}, {"authorization_ref": "other"}):
        assert bind_diagnostic_escalation_reason(task, [replace(candidate, **mismatch)], authorization,
                                                environment="validation").escalation_reason == ""
    lower = replace(task, task_type="chapter_plan.generate", risk="MEDIUM")
    grant = {**authorization["authorization"], "task_type": lower.task_type}
    matching = {**authorization, "authorization": grant, "authorization_hash": authorization_hash(grant)}
    assert bind_diagnostic_escalation_reason(lower, [candidate], matching, environment="validation").escalation_reason == ""
    for change, reason in (({"available": False}, "PROVIDER_UNAVAILABLE:"),
                           ({"quota_remaining": 0}, "ESCALATION_CAPACITY_OR_AUTHORIZATION_MISSING")):
        rejected = CostAwareRouter().explain(frozen, [replace(candidate, **change)], {})
        sampled = benchmark_decision(rejected, authorization, environment="validation").to_dict()
        assert sampled["status"] == "BLOCKED"
        assert reason in sampled["candidates"][0]["rejected_reasons"]


def test_native_router_binds_admitted_diagnostic_before_explaining(monkeypatch):
    from unittest.mock import MagicMock
    from novel_forge.modules.production_execution import routing_runtime
    from novel_forge.modules.command_kernel import routing_bootstrap

    task, candidate, authorization = diagnostic_escalation_fixture()
    router = routing_runtime.ProductionProviderRouter("unused", candidates=[candidate],
        task_money_limit="0", task_token_limit=2000, execution_environment="validation")
    cursor = MagicMock()
    cursor.fetchone.return_value = (0, 0)
    uow = MagicMock()
    uow.__enter__.return_value.cursor = cursor
    monkeypatch.setattr(routing_runtime, "AuthorityUnitOfWork", lambda _: uow)
    monkeypatch.setattr(routing_bootstrap, "load_bootstrap_authorization", lambda *args, **kwargs: authorization)
    monkeypatch.setattr(router.registry, "history", lambda **kwargs: ())
    monkeypatch.setattr(router.registry, "policy", lambda *args: {})
    monkeypatch.setattr(router.registry, "observations", lambda **kwargs: [])
    monkeypatch.setattr(router.registry, "available_candidates", lambda **kwargs: kwargs["candidates"])
    monkeypatch.setattr(router, "_candidate_budgets", lambda **kwargs: {})
    _, result = router.select(object(), task_type=task.task_type, project_id=task.project_id,
        work_id=task.work_id, operation_id=task.operation_id, attempt_id=task.attempt_id,
        stable_key="operation:attempt:sample", input_tokens=1000, output_tokens=100,
        trace_id="trace", correlation_id="correlation", dry_run=True,
        producer_contract=task.producer_contract)
    assert result["status"] == "BENCHMARK_SELECTED"
    assert result["task"]["escalation_reason"] == authorization["authorization"]["reason"]
    assert result["task"]["history"] == []
    assert result["bootstrap_authorization"] == authorization


@pytest.mark.parametrize("limiting_scope", ["grant", "task", "provider"])
def test_complete_request_preflight_rejects_old_underestimated_decision(limiting_scope):
    from novel_forge.modules.production_execution.routing_runtime import validate_routed_reservation

    _, decision = codex_benchmark_decision()
    decision["task"]["remaining_tokens"] = 65536
    candidate_id = decision["selected"]["candidate"]["candidate_id"]
    decision["task"]["budget_snapshot"]["candidates"] = {candidate_id: {"remaining_tokens": 65536}}
    decision["bootstrap_authorization"]["authorization"]["maximum_tokens"] = 65536
    if limiting_scope == "grant":
        decision["bootstrap_authorization"]["authorization"]["maximum_tokens"] = 32768
    elif limiting_scope == "task":
        decision["task"]["remaining_tokens"] = 32768
    else:
        decision["task"]["budget_snapshot"]["candidates"][candidate_id]["remaining_tokens"] = 32768
    validate_routed_reservation(decision, reserved_tokens=32768, reserved_amount=None)
    with pytest.raises(KernelError, match="tokens=38825 exceeds available limit=32768"):
        validate_routed_reservation(decision, reserved_tokens=38825, reserved_amount=None)


def test_routing_complete_request_meter_rejects_oversized_diagnostic_before_selection():
    from novel_forge.modules.production_execution.provider_admission import provider_request_token_components

    task, candidate, authorization = diagnostic_escalation_fixture()
    components = provider_request_token_components(
        "x" * 20617, output_reserve=10000, framing_overhead=16, safety_margin=8192,
    )
    candidate = replace(candidate, context_limit=272000, output_limit=32000)
    task = replace(task, input_tokens=sum(components.values()) - 10000,
                   output_tokens=10000, remaining_tokens=65536, escalation_reason="approved diagnostic")
    grant = {**authorization["authorization"], "maximum_tokens": 32768,
             "campaign": {**authorization["authorization"]["campaign"], "maximum_tokens": 65536}}
    authorization = {**authorization, "authorization": grant, "authorization_hash": authorization_hash(grant)}
    ordinary = CostAwareRouter().explain(task, [candidate], {})
    result = benchmark_decision(ordinary, authorization, environment="validation").to_dict()
    assert result["status"] == "BLOCKED"
    assert result["candidates"][0]["estimated_total_tokens"] == 38825
    assert "BENCHMARK_AUTHORIZATION_BUDGET_EXCEEDED" in result["candidates"][0]["rejected_reasons"]
    task_limited = CostAwareRouter().explain(replace(task, remaining_tokens=32768), [candidate], {}).to_dict()
    assert "BUDGET_HARD_LIMIT" in task_limited["candidates"][0]["rejected_reasons"]


@pytest.mark.parametrize("version", ["3.3.0", "3.4.0", "3.4.2", "3.6.0", "4.0.0", "3.4.1-author-input.v1", None, []])
def test_chapter_sample_source_versions_reject_unsupported_contracts(version):
    from novel_forge.modules.command_kernel.routing_bootstrap import chapter_sample_source_version_supported

    assert not chapter_sample_source_version_supported(version)
