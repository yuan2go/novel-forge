from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace

import psycopg
import pytest

from novel_forge.modules.book_authority.opening import PostgresBookOpeningApplication
from novel_forge.modules.command_kernel.creative_budget_runtime import configure_creative_budget, get_creative_budget
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_runtime import (
    EffectCommandContext, accept_external_effect_receipt, mark_external_effect_unknown,
    plan_external_effect, prepare_effect_dispatch,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated, identifier
from tests.integration.book_opening_workflow_postgres_support import build_workflow_fixture
from tests.integration.test_core_functional_loops_postgres import RELEASE_SHA
from tests.unit.test_creative_budget_contract import budget_policy


@pytest.fixture(scope="module", autouse=True)
def _migrations():
    ensure_migrated()


def _capacity_fixture():
    fixture = build_workflow_fixture(target_chapter_count=6)
    policy = budget_policy()
    plan = policy["comparison_budget"]
    plan["experiment_id"] = identifier("capacity-budget")
    first = plan["arms"][0]
    first.update(project_id=fixture.project_id, book_id=fixture.book_id,
                 source_allocation={"calls": 0, "tokens": 0},
                 creation_allocation={"calls": 90, "tokens": 12_000_000},
                 repair_allocation={"calls": 10, "tokens": 2_000_000},
                 project_total={"calls": 100, "tokens": 14_000_000})
    plan["arms"][1]["project_id"] = identifier("unexecuted-budget-arm")
    for field in ("source_allocation", "creation_allocation", "repair_allocation", "project_total"):
        plan["arms"][1][field] = deepcopy(first[field])
    plan["shared_total"] = {"calls": 200, "tokens": 28_000_000}
    authorization = policy["authorization"]
    authorization.update(project_id=fixture.project_id, book_id=fixture.book_id,
                         authorized_cumulative_caps={"SOURCE": first["source_allocation"], "CREATION": first["creation_allocation"], "REPAIR": first["repair_allocation"]})
    configure_creative_budget(database_url=DATABASE_URL, policy=policy, project_id=fixture.project_id,
                             workspace_id=fixture.workspace_id, principal=fixture.principal,
                             application_build_id="capacity-continuation-test", commit_sha=RELEASE_SHA,
                             idempotency_key=identifier("capacity-grant"), trace_id=identifier("trace"), correlation_id=identifier("correlation"))
    initial = {"execution_mode": "PROVIDER_ALLOWED", "provider_call_limit": 48,
               "token_limit": 4_800_000, "per_call_token_limit": 100_000,
               "accounting_basis": "ACCOUNT_ENTITLEMENT", "cost_observability": "UNKNOWN",
               "authorization_ref": authorization["authorization_ref"]}
    def app(policy):
        return PostgresBookOpeningApplication(DATABASE_URL, narrative_search=fixture.opening.narrative_search,
                input_resolver=fixture.opening.input_resolver, application_build_id="capacity-continuation-test",
                commit_sha=RELEASE_SHA, provider_budget_policy=policy)
    fixture.opening = app(initial)
    admission = fixture.admit()
    return fixture, admission, app({**initial, "token_limit": 7_680_000, "per_call_token_limit": 160_000})


def _fail_before_result(fixture, monkeypatch):
    def fail(**_):
        raise KernelError("PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED", "isolated fixture: required context exceeds frozen capacity")
    monkeypatch.setattr(fixture.binder, "execute", fail)
    claim = fixture.claim(fixture.principal.principal_id)
    assert claim is not None
    with pytest.raises(KernelError, match="PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED"):
        fixture.execute(claim)


def test_capacity_continuation_is_causal_idempotent_and_fences_failed_source(monkeypatch):
    fixture, original, successor_app = _capacity_fixture()
    _fail_before_result(fixture, monkeypatch)
    failed = fixture.opening.require(original.opening_run_id)
    usage = get_creative_budget(DATABASE_URL, fixture.project_id)
    kwargs = dict(expected_version=failed["version"], reason="Increase only capacity for the exact unstarted request", principal=fixture.principal)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(successor_app.continue_unstarted_with_budget, original.opening_run_id, **kwargs) for _ in range(2)]
        outcomes = [future.result() for future in futures]
    assert len({item.opening_run_id for item in outcomes}) == 1
    successor = successor_app.require(outcomes[0].opening_run_id)
    assert successor["lifecycle"] == "ADMITTED"
    assert fixture.opening.require(original.opening_run_id) == failed
    assert get_creative_budget(DATABASE_URL, fixture.project_id) == usage
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT frozen_request,budget_scope_id FROM authority_book_opening_run WHERE opening_run_id=ANY(%s) ORDER BY opening_run_id", [[original.opening_run_id, successor["opening_run_id"]]])
        rows = uow.cursor.fetchall()
        assert rows[0][1] != rows[1][1]
        assert {key: value for key, value in rows[0][0].items() if key != "idempotency_key"} == {key: value for key, value in rows[1][0].items() if key != "idempotency_key"}
        uow.cursor.execute("SELECT causation_operation_id FROM authority_operation WHERE operation_id=%s", [successor["root_operation_id"]])
        assert uow.cursor.fetchone()[0] == failed["root_operation_id"]
        uow.cursor.execute("SELECT count(*) FROM authority_book_opening_capacity_continuation WHERE source_opening_run_id=%s", [original.opening_run_id])
        assert uow.cursor.fetchone()[0] == 1
    with pytest.raises(KernelError, match="CAPACITY_PREDECESSOR_FENCED"):
        fixture.opening.recovery.assess_recovery(original.opening_run_id, idempotency_key="after-successor", principal=fixture.principal)
    with pytest.raises(psycopg.errors.CheckViolation, match="CAPACITY_PREDECESSOR_FENCED"):
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute("UPDATE authority_book_opening_run SET updated_at=NOW() WHERE opening_run_id=%s", [original.opening_run_id])
    with pytest.raises(psycopg.errors.CheckViolation, match="CAPACITY_PREDECESSOR_FENCED"):
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute("DELETE FROM authority_book_opening_run WHERE opening_run_id=%s", [original.opening_run_id])
    assert successor_app.claim_next_node_execution(worker_id=fixture.principal.principal_id, project_id=fixture.project_id, lease_seconds=30, expected_opening_run_id=successor["opening_run_id"]) is not None


def test_capacity_continuation_rejects_unfailed_changed_scope_stale_and_unfunded(monkeypatch):
    fixture, original, successor_app = _capacity_fixture()
    reason = "capacity only"
    with pytest.raises(KernelError, match="CONTINUATION_SOURCE_INVALID"):
        successor_app.continue_unstarted_with_budget(original.opening_run_id, expected_version=0, reason=reason, principal=fixture.principal)
    _fail_before_result(fixture, monkeypatch)
    failed = fixture.opening.require(original.opening_run_id)
    with pytest.raises(KernelError, match="ACTOR_IDENTITY_INVALID"):
        successor_app.continue_unstarted_with_budget(original.opening_run_id, expected_version=failed["version"], reason=reason,
                principal=replace(fixture.principal, principal_id="another-operator"))
    with pytest.raises(KernelError, match="CONTINUATION_SOURCE_INVALID"):
        successor_app.continue_unstarted_with_budget(original.opening_run_id, expected_version=failed["version"]-1, reason=reason, principal=fixture.principal)
    excess = deepcopy(successor_app.provider_budget_policy)
    excess["token_limit"] = 15_000_000
    app = PostgresBookOpeningApplication(DATABASE_URL, narrative_search=fixture.opening.narrative_search,
            input_resolver=fixture.opening.input_resolver, application_build_id="capacity-continuation-test",
            commit_sha=RELEASE_SHA, provider_budget_policy=excess)
    with pytest.raises(KernelError, match="CONTINUATION_BUDGET_EXHAUSTED"):
        app.continue_unstarted_with_budget(original.opening_run_id, expected_version=failed["version"], reason=reason, principal=fixture.principal)
    assert fixture.opening.require(original.opening_run_id) == failed


def test_capacity_continuation_cannot_resend_after_provider_intent(monkeypatch):
    fixture, original, successor_app = _capacity_fixture()
    def return_then_fail(**kwargs):
        plan_external_effect(DATABASE_URL, EffectCommandContext(
            operation_id=kwargs["operation_id"], project_id=fixture.project_id,
            actor_id=fixture.principal.principal_id, trace_id=identifier("trace"), correlation_id=identifier("correlation")),
            effect_type="model.invoke", provider="fake_deterministic_provider", capability="model.fixture",
            stable_idempotency_key=identifier("unknown-provider-intent"), request_payload={"fixture": True}, max_attempts=1, reversible=False)
        raise KernelError("PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED", "synthetic post-result error must not qualify as zero work")
    monkeypatch.setattr(fixture.binder, "execute", return_then_fail)
    claim = fixture.claim(fixture.principal.principal_id)
    with pytest.raises(KernelError, match="PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED"):
        fixture.execute(claim)
    failed = fixture.opening.require(original.opening_run_id)
    with pytest.raises(KernelError, match="CONTINUATION_WORK_EXISTS"):
        successor_app.continue_unstarted_with_budget(original.opening_run_id, expected_version=failed["version"],
                reason="must reject unresolved Provider intent", principal=fixture.principal)
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT count(*) FROM authority_book_opening_capacity_continuation WHERE source_opening_run_id=%s", [original.opening_run_id])
        assert uow.cursor.fetchone()[0] == 0


@pytest.mark.parametrize("outcome", ["intent", "unknown", "retryable_failure", "success"])
def test_recovery_sees_planning_effect_before_any_candidate(monkeypatch, outcome):
    fixture, original, _ = _capacity_fixture()
    captured = {}
    def fail_after_effect(**kwargs):
        context = EffectCommandContext(operation_id=kwargs["operation_id"], project_id=fixture.project_id,
            actor_id=fixture.principal.principal_id, trace_id=identifier("trace"), correlation_id=identifier("correlation"))
        effect = plan_external_effect(DATABASE_URL, context, effect_type="model.invoke",
            provider="fake_deterministic_provider", capability="model.fixture",
            stable_idempotency_key=identifier("pre-candidate-effect"), request_payload={"fixture": True},
            max_attempts=2, reversible=False)
        captured.update(operation_id=kwargs["operation_id"], effect_id=effect["external_effect_id"])
        if outcome != "intent":
            dispatch = prepare_effect_dispatch(DATABASE_URL, context, effect_id=effect["external_effect_id"])
            if outcome == "unknown":
                mark_external_effect_unknown(DATABASE_URL, context, dispatch_id=dispatch["dispatch_id"], evidence={"fixture": "lost-response"})
            else:
                accept_external_effect_receipt(DATABASE_URL, context, dispatch_id=dispatch["dispatch_id"],
                    provider="fake_deterministic_provider", receipt_id=identifier("receipt"),
                    message_id=identifier("message"), payload_hash="sha256:"+"e"*64,
                    provider_correlation_id=identifier("provider-correlation"), generation=dispatch["generation"],
                    outcome=outcome, evidence={"fixture": True})
        raise KernelError("MODEL_EFFECT_RETRYABLE_PLANNING", "no Candidate persisted")
    monkeypatch.setattr(fixture.binder, "execute", fail_after_effect)
    claim = fixture.claim(fixture.principal.principal_id)
    with pytest.raises(KernelError, match="MODEL_EFFECT_RETRYABLE_PLANNING"):
        fixture.execute(claim)
    before = fixture.opening.require(original.opening_run_id)
    budget = get_creative_budget(DATABASE_URL, fixture.project_id)
    assessment = fixture.opening.recovery.assess_recovery(original.opening_run_id,
        idempotency_key="pre-candidate-assessment", principal=fixture.principal)
    assert assessment.disposition == ("PROVEN_SUCCESS" if outcome == "success" else "UNKNOWN_AMBIGUOUS")
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT snapshot FROM authority_book_opening_recovery_assessment WHERE recovery_assessment_id=%s", [assessment.recovery_assessment_id])
        snapshot = uow.cursor.fetchone()[0]
    assert snapshot["planning_generation"]["operation_id"] == captured["operation_id"]
    assert snapshot["planning_generation"]["candidate_asset_version_id"] == ""
    assert {item["effect_id"] for item in snapshot["external_effect"]["evidence"]} == {captured["effect_id"]}
    if outcome != "success":
        with pytest.raises(KernelError, match="EXTERNAL_EFFECT_RECONCILIATION_REQUIRED"):
            fixture.opening.recovery.recover(assessment.recovery_assessment_id, idempotency_key="no-blind-resend",
                reason="must reconcile the original Provider request", principal=fixture.principal)
        assert fixture.opening.require(original.opening_run_id)["current_execution_generation"] == before["current_execution_generation"]
    assert get_creative_budget(DATABASE_URL, fixture.project_id) == budget
