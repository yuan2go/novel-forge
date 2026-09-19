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
