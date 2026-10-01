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


@pytest.mark.parametrize("grant_scope", ["none", "other_task", "other_producer", "other_book"])
def test_supervised_book_cannot_dispatch_strict_selected_model_without_exact_grant(grant_scope):
    from tests.unit.test_cost_aware_routing import generator_samples

    scope, model = prepared("draft")
    policy = deepcopy(scope.policy_snapshot)
    policy["policy"]["author_supervised_books"] = [{"book_id": "book", "author_id": "author", "reason": "Scoped author trial"}]
    grant = policy["policy"]["author_supervised_authorizations"][0]
    if grant_scope == "none":
        policy["policy"]["author_supervised_authorizations"] = []
    elif grant_scope == "other_task":
        grant["task_type"] = "memo"
    elif grant_scope == "other_producer":
        grant["producer_contract_hash"] = "sha256:" + "b"*64
    else:
        grant["book_id"] = "another-book"
    scope = replace(scope, policy_snapshot=policy)
    strict = CostAwareRouter().explain(scope, [model], {model.candidate_id: generator_samples()}, now=NOW)
    assert strict.to_dict()["status"] == "SELECTED"
    original = strict.to_dict()
    result = supervised_decision(strict, now=NOW).to_dict()
    assert result["status"] == "BLOCKED" and result["selected"] is None
    assert result["production_eligible"] is False
    assert result["candidates"][0]["strict_rejected_reasons"] == []
    assert result["candidates"][0]["rejected_reasons"] == ["AUTHOR_SUPERVISION_TASK_AUTHORIZATION_REQUIRED"]
    assert result["author_supervision"]["admission_contract_version"] == "author-supervision-admission.v2"
    assert strict.to_dict() == original
    strict_scope = replace(scope, policy_snapshot={})
    strict_mode = CostAwareRouter().explain(strict_scope, [model], {model.candidate_id: generator_samples()}, now=NOW)
    assert supervised_decision(strict_mode, now=NOW) == strict_mode


def test_frozen_legacy_author_selection_remains_verifiable_without_new_admission_marker():
    scope, model = prepared()
    snapshot = supervised_decision(CostAwareRouter().explain(scope, [model], {}, now=NOW), now=NOW).to_dict()
    snapshot["author_supervision"].pop("admission_contract_version")
    verify_frozen_supervision(snapshot)


def test_native_router_applies_book_authorization_gate_with_no_grants(monkeypatch):
    from unittest.mock import MagicMock
    from novel_forge.modules.production_execution import routing_runtime
    from novel_forge.modules.command_kernel import routing_bootstrap
    from tests.unit.test_cost_aware_routing import generator_samples

    class FrozenDatetime(routing_runtime.datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz is not None else NOW.replace(tzinfo=None)

    monkeypatch.setattr(routing_runtime, "datetime", FrozenDatetime)
    scope, model = prepared("draft")
    policy = deepcopy(scope.policy_snapshot)
    policy["policy"]["author_supervised_authorizations"] = []
    policy["policy"]["author_supervised_books"] = [{"book_id": "book", "author_id": "author", "reason": "Scoped author trial"}]
    router = routing_runtime.ProductionProviderRouter("unused", candidates=[model], task_money_limit="1", task_token_limit=100000)
    cursor, uow = MagicMock(), MagicMock()
    cursor.fetchone.return_value = (0, 0)
    uow.__enter__.return_value.cursor = cursor
    monkeypatch.setattr(routing_runtime, "AuthorityUnitOfWork", lambda _: uow)
    monkeypatch.setattr(routing_bootstrap, "load_bootstrap_authorization", lambda *args, **kwargs: None)
    monkeypatch.setattr(router.registry, "history", lambda **kwargs: ())
    monkeypatch.setattr(router.registry, "policy", lambda *args: policy)
    now = routing_runtime.datetime.now(routing_runtime.timezone.utc)
    monkeypatch.setattr(router.registry, "observations", lambda **kwargs: [replace(row, occurred_at=now.isoformat()) for row in generator_samples()])
    monkeypatch.setattr(router.registry, "available_candidates", lambda **kwargs: kwargs["candidates"])
    monkeypatch.setattr(router, "_candidate_budgets", lambda **kwargs: {})
    _, result = router.select(object(), task_type="draft", project_id="project", work_id="book", operation_id="operation",
        attempt_id="attempt", stable_key="review-routing-unit", input_tokens=1000, output_tokens=100,
        trace_id="trace", correlation_id="correlation", dry_run=True, producer_contract={"stage": "draft"})
    assert result["status"] == "BLOCKED"
    assert result["candidates"][0]["strict_rejected_reasons"] == []
    assert result["candidates"][0]["rejected_reasons"] == ["AUTHOR_SUPERVISION_TASK_AUTHORIZATION_REQUIRED"]


def test_previously_frozen_strict_selection_is_replayed_without_new_grant_gate(monkeypatch):
    from types import SimpleNamespace
    from novel_forge.modules.production_execution import author_supervision, routing_runtime
    from tests.unit.test_cost_aware_routing import generator_samples

    scope, model = prepared("draft")
    policy = deepcopy(scope.policy_snapshot)
    policy["policy"]["author_supervised_authorizations"] = []
    policy["policy"]["author_supervised_books"] = [{"book_id": "book", "author_id": "author", "reason": "Historical book mode"}]
    scope = replace(scope, policy_snapshot=policy, producer_contract_hash="",
        declared_requirements={"risk": "", "quality_floor": 0, "chapter": 0})
    frozen = CostAwareRouter().explain(scope, [model], {model.candidate_id: generator_samples()}, now=NOW).to_dict()
    assert frozen["status"] == "SELECTED"
    assert supervised_decision(CostAwareRouter().explain(scope, [model], {model.candidate_id: generator_samples()}, now=NOW), now=NOW).to_dict()["status"] == "BLOCKED"
    router = routing_runtime.ProductionProviderRouter("unused", candidates=[model], task_money_limit="1", task_token_limit=100000)
    monkeypatch.setattr(router.registry.query, "require", lambda **kwargs: SimpleNamespace(content=frozen, asset_version_id="old-frozen-route"))
    monkeypatch.setattr(router, "_selected_route", lambda base, snapshot: base)

    def reject_recomputation(*args, **kwargs):
        raise AssertionError("Frozen request must not be reinterpreted under new authorization semantics")

    monkeypatch.setattr(author_supervision, "supervised_decision", reject_recomputation)
    _, replay = router.select(object(), task_type="draft", project_id=scope.project_id, work_id=scope.work_id,
        operation_id=scope.operation_id, attempt_id=scope.attempt_id, stable_key="historical-route",
        input_tokens=scope.input_tokens, output_tokens=scope.output_tokens, trace_id="trace", correlation_id="correlation")
    assert replay == {**frozen, "asset_version_id": "old-frozen-route"}


@pytest.mark.parametrize("mismatch", [None, "candidate", "revision", "tokens", "amount"])
def test_strict_semantic_selection_in_supervised_book_obeys_exact_grant_without_quality_override(mismatch):
    from tests.unit.test_cost_aware_routing import samples

    scope, model = prepared("narrative_semantic_evaluation")
    policy = deepcopy(scope.policy_snapshot)
    policy["policy"]["author_supervised_books"] = [{"book_id": "book", "author_id": "author", "reason": "Scoped author trial"}]
    grant = policy["policy"]["author_supervised_authorizations"][0]
    if mismatch == "candidate":
        grant["candidate_id"] = "another-authorized-model"
    elif mismatch == "revision":
        grant["model_revision"] = "another-authorized-revision"
    elif mismatch == "tokens":
        grant["maximum_tokens"] = 1
    elif mismatch == "amount":
        grant["maximum_amount"] = "0"
    scope = replace(scope, policy_snapshot=policy,
        declared_requirements={"cross_model_review": {"purpose": "STRICT_QUALIFICATION",
            "generator": {"provider": "codex-cli", "model": "generator", "model_revision": "generator-revision"},
            "required_reviewer_provider": "deepseek", "target_content_hash": "sha256:"+"d"*64}})
    observations = [replace(row, quality_score=None, accepted=None, evidence_class="REFERENCE_EVALUATION",
        production_eligible=False, reference_agreed=True, reference_label_classes=("PASS" if i % 2 else "FAIL",),
        sample_identity=str(i), experiment_partition="CALIBRATION", reference_risk="HIGH", reference_context_tokens=1000,
        reference_protocol_hash="sha256:"+"1"*64) for i, row in enumerate(samples(n=80))]
    strict = CostAwareRouter().explain(scope, [model], {model.candidate_id: observations}, now=NOW)
    assert strict.to_dict()["status"] == "SELECTED"
    result = supervised_decision(strict, now=NOW)
    if mismatch is None:
        assert result == strict
    else:
        blocked = result.to_dict()
        assert blocked["status"] == "BLOCKED" and blocked["selected"] is None
        assert blocked.get("mode") != "AUTHOR_SUPERVISED"
        assert blocked["author_supervision"]["qualification_override"] is False
        reason = "AUTHOR_SUPERVISION_MODEL_MISMATCH" if mismatch in {"candidate", "revision"} else "AUTHOR_SUPERVISION_BUDGET_EXCEEDED"
        assert reason in blocked["candidates"][0]["rejected_reasons"]
    unqualified = CostAwareRouter().explain(scope, [model], {}, now=NOW)
    assert unqualified.to_dict()["status"] == "BLOCKED"
    assert supervised_decision(unqualified, now=NOW) == unqualified
