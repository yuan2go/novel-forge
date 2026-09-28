from copy import deepcopy
from dataclasses import replace
from datetime import timedelta

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution.author_supervision import (
    supervised_decision, validate_grants, verify_frozen_supervision,
)
from novel_forge.modules.production_execution.cost_routing import CostAwareRouter
from novel_forge.modules.production_execution.routing_policy import validate_routing_policy
from tests.unit.test_cost_aware_routing import NOW, candidate, task


def prepared(task_type="draft"):
    model = candidate(model_revision="revision-1")
    grant = {"authorization_id": "author:1", "book_id": "book", "task_type": task_type,
             "producer_contract_hash": "sha256:" + "a" * 64, "candidate_id": model.candidate_id,
             "model_revision": model.model_revision, "author_id": "author", "expires_at": (NOW + timedelta(hours=1)).isoformat(),
             "maximum_tokens": 100000, "maximum_amount": "1", "reason": "Author reviewed scoped trial"}
    policy = {"policy_version": "supervised-v1", "reason": "bounded author trial", "task_overrides": [],
              "author_supervised_authorizations": [grant]}
    validate_routing_policy(policy)
    scope = task(task_type=task_type, producer_contract_hash=grant["producer_contract_hash"],
                 policy_snapshot={"policy": policy, "actor_id": "author", "operation_id": "policy-op"},
                 budget_snapshot={"candidates": {model.candidate_id: {"remaining_calls": 2,
                    "scopes": {"tokens:book_total": {"cap": "100000"}}}}})
    return scope, model


@pytest.mark.parametrize("stage", ["draft", "revision", "canon_support", "book_plan.generate", "chapter_plan.generate"])
def test_trial_is_scoped_without_claiming_independent_qualification(stage):
    scope, model = prepared(stage)
    strict = CostAwareRouter().explain(scope, [model], {}, now=NOW)
    assert strict.to_dict()["status"] == "BLOCKED"
    decision = supervised_decision(strict, now=NOW).to_dict()
    assert decision["status"] == "AUTHOR_SUPERVISED_SELECTED"
    assert decision["independent_qualification_eligible"] is False
    assert decision["author_supervision"]["literary_qualification"] == "NOT_PROVEN"
    assert "BENCHMARK_INSUFFICIENT" in decision["selected"]["strict_rejected_reasons"]
    verify_frozen_supervision(decision)
    corrupted = deepcopy(decision)
    corrupted["task"]["work_id"] = "other-book"
    with pytest.raises(KernelError):
        verify_frozen_supervision(corrupted)


@pytest.mark.parametrize("change", ["book", "task", "producer"])
def test_grant_does_not_cross_scope(change):
    scope, model = prepared()
    scope = replace(scope, **{"book": {"work_id": "other"}, "task": {"task_type": "revision"},
                            "producer": {"producer_contract_hash": "sha256:" + "b" * 64}}[change])
    strict = CostAwareRouter().explain(scope, [model], {}, now=NOW)
    assert supervised_decision(strict, now=NOW) == strict


@pytest.mark.parametrize("failure", ["SCHEMA_REJECTION", "UNKNOWN_EXTERNAL_OUTCOME", "POLICY_REJECTION"])
def test_author_does_not_remove_technical_or_unknown_stops(failure):
    scope, model = prepared()
    scope = replace(scope, history=({"candidate_id": model.candidate_id, "failure_class": failure},))
    decision = supervised_decision(CostAwareRouter().explain(scope, [model], {}, now=NOW), now=NOW)
    assert decision.to_dict()["status"] == "BLOCKED"


def test_expiry_identity_budget_and_old_default_are_preserved():
    scope, model = prepared()
    strict = CostAwareRouter().explain(scope, [model], {}, now=NOW)
    with pytest.raises(KernelError):
        supervised_decision(strict, now=NOW + timedelta(hours=2))
    with pytest.raises(KernelError):
        validate_grants(scope.policy_snapshot["policy"], author_id="impostor")
    unbounded = replace(scope, budget_snapshot={})
    assert supervised_decision(CostAwareRouter().explain(unbounded, [model], {}, now=NOW), now=NOW).to_dict()["status"] == "BLOCKED"
    exhausted = replace(scope, remaining_tokens=1)
    assert supervised_decision(CostAwareRouter().explain(exhausted, [model], {}, now=NOW), now=NOW).to_dict()["status"] == "BLOCKED"
    legacy = replace(scope, policy_snapshot={})
    old = CostAwareRouter().explain(legacy, [model], {}, now=NOW)
    assert supervised_decision(old, now=NOW) == old
