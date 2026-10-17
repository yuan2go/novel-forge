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


def _capacity_fixture(*, resource_successor=False):
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
    if resource_successor:
        from novel_forge.modules.authority_handler_runtime.policy_commands import configure_owned_policy
        from tests.unit.test_creative_execution_template import template
        value = template(fixture.book_id, member_authorization_ref=authorization["authorization_ref"])
        configure_owned_policy(database_url=DATABASE_URL, owner="PROVIDER_ROUTING", project_id=fixture.project_id,
            workspace_id=fixture.workspace_id, principal=fixture.principal, application_build_id="capacity-continuation-test",
            commit_sha=RELEASE_SHA, idempotency_key=identifier("resource-policy"), trace_id=identifier("trace"),
            correlation_id=fixture.book_id, content={"policy_version": "creative-v1", "reason": "native resource successor",
                "task_overrides": [], "execution_templates": [value]})
    fixture.opening = app(initial)
    admission = fixture.admit()
    successor = ({"resource_control_version": "billing-channel-resources.v1", "execution_mode": "PROVIDER_ALLOWED",
        "accounting_basis": "ACCOUNT_ENTITLEMENT", "authorization_ref": authorization["authorization_ref"],
        "cost_observability": "UNKNOWN", "per_call_token_limit": 160_000} if resource_successor else
        {**initial, "token_limit": 7_680_000, "per_call_token_limit": 160_000})
    return fixture, admission, app(successor)


def _fail_before_result(fixture, monkeypatch):
    import tempfile
    from novel_forge.api.authority_dependencies import build_production_execution_composition, build_story_planning_generation_application
    from novel_forge.infrastructure.settings import IndustrialSettings
    with tempfile.TemporaryDirectory(prefix="native-opening-capacity-") as root:
        settings = IndustrialSettings(root=root, database_url=DATABASE_URL, environment="test")
        env = {"NOVEL_FORGE_ENVIRONMENT": "test", "NOVEL_FORGE_COMMIT_SHA": RELEASE_SHA,
            "NOVEL_FORGE_APPLICATION_BUILD_ID": "capacity-continuation-test",
            "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2",
            "NOVEL_FORGE_PLANNING_PROVIDER": "scripted_provider_v2",
            "NOVEL_FORGE_PLANNING_CAPABILITY_PACK_ID": fixture.planning_pack_id,
            "NOVEL_FORGE_TEST_ALLOW_SCRIPTED_NARRATIVE_EVALUATION_FIXTURE": "true",
            "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": root}
        execution = build_production_execution_composition(settings, env=env)
        try:
            planning = build_story_planning_generation_application(settings, execution=execution, env=env)
            preparer = planning.execution_binder.resolver.execution_preparer
            preparer.planning_route = replace(preparer.planning_route, model_context_limit=64)
            with monkeypatch.context() as fault:
                fault.setattr(fixture.opening.narrative_search, "planning", planning)
                claim = fixture.claim(fixture.principal.principal_id)
                assert claim is not None
                with pytest.raises(KernelError, match="CONTEXT.*(BUDGET|CAPACITY)|PROVIDER_REQUEST_BUDGET_EXCEEDED"):
                    fixture.execute(claim)
        finally:
            execution.close()


def _historical_zero_work_failure(fixture, monkeypatch):
    def fail(*_args, **_):
        raise KernelError("PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED", "historical zero-preparation compatibility fixture")
    with monkeypatch.context() as fault:
        fault.setattr(fixture.opening.narrative_search, "explore", fail)
        claim = fixture.claim(fixture.principal.principal_id)
        with pytest.raises(KernelError, match="PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED"):
            fixture.execute(claim)


@pytest.mark.parametrize("resource_successor", [False, True])
def test_historical_zero_work_capacity_preserves_budget_and_predecessor_fences(monkeypatch, resource_successor):
    fixture, original, successor_app = _capacity_fixture(resource_successor=resource_successor)
    _historical_zero_work_failure(fixture, monkeypatch)
    failed = fixture.opening.require(original.opening_run_id)
    usage = get_creative_budget(DATABASE_URL, fixture.project_id)
    excess = deepcopy(fixture.opening.provider_budget_policy)
    excess["token_limit"] = 15_000_000
    excess["per_call_token_limit"] = 160_000
    app = PostgresBookOpeningApplication(DATABASE_URL, narrative_search=fixture.opening.narrative_search,
        input_resolver=fixture.opening.input_resolver, application_build_id="capacity-continuation-test",
        commit_sha=RELEASE_SHA, provider_budget_policy=excess)
    with pytest.raises(KernelError, match="CONTINUATION_BUDGET_EXHAUSTED"):
        app.continue_unstarted_with_budget(original.opening_run_id, expected_version=failed["version"],
            reason="Historical frozen cumulative authorization remains bounded", principal=fixture.principal)
    kwargs = dict(expected_version=failed["version"], reason="Historical zero-work capacity successor", principal=fixture.principal)
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: successor_app.continue_unstarted_with_budget(original.opening_run_id, **kwargs), range(2)))
    assert len({item.opening_run_id for item in outcomes}) == 1
    successor = successor_app.require(outcomes[0].opening_run_id)
    assert successor["lifecycle"] == "ADMITTED"
    assert fixture.opening.require(original.opening_run_id) == failed
    assert get_creative_budget(DATABASE_URL, fixture.project_id) == usage
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT frozen_request,budget_scope_id FROM authority_book_opening_run WHERE opening_run_id=ANY(%s) ORDER BY opening_run_id",
            [[original.opening_run_id, successor["opening_run_id"]]])
        rows = uow.cursor.fetchall()
        assert rows[0][1] != rows[1][1]
        assert {key: value for key, value in rows[0][0].items() if key != "idempotency_key"} == {
            key: value for key, value in rows[1][0].items() if key != "idempotency_key"}
        uow.cursor.execute("SELECT causation_operation_id FROM authority_operation WHERE operation_id=%s", [successor["root_operation_id"]])
        assert uow.cursor.fetchone() == (failed["root_operation_id"],)
        uow.cursor.execute("SELECT count(*) FROM authority_book_opening_capacity_continuation WHERE source_opening_run_id=%s", [original.opening_run_id])
        assert uow.cursor.fetchone() == (1,)
    with pytest.raises(KernelError, match="CAPACITY_PREDECESSOR_FENCED"):
        fixture.opening.recovery.assess_recovery(original.opening_run_id, idempotency_key="historical-fenced-source", principal=fixture.principal)
    for sql in ("UPDATE authority_book_opening_run SET updated_at=NOW() WHERE opening_run_id=%s",
                "DELETE FROM authority_book_opening_run WHERE opening_run_id=%s"):
        with pytest.raises(psycopg.errors.CheckViolation, match="CAPACITY_PREDECESSOR_FENCED"):
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute(sql, [original.opening_run_id])
    assert successor_app.claim_next_node_execution(worker_id=fixture.principal.principal_id, project_id=fixture.project_id,
        lease_seconds=30, expected_opening_run_id=successor["opening_run_id"]) is not None



@pytest.mark.parametrize("resource_successor", [False, True])
def test_capacity_continuation_is_causal_idempotent_and_fences_failed_source(monkeypatch, resource_successor):
    fixture, original, successor_app = _capacity_fixture(resource_successor=resource_successor)
    _fail_before_result(fixture, monkeypatch)
    failed = fixture.opening.require(original.opening_run_id)
    usage = get_creative_budget(DATABASE_URL, fixture.project_id)
    with pytest.raises(KernelError, match="CONTINUATION_SOURCE_INVALID"):
        successor_app.continue_unstarted_with_budget(original.opening_run_id,
            expected_version=failed["version"], reason="Prepared inputs are not zero work", principal=fixture.principal)
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("""SELECT o.operation_id,a.attempt_id,a.result FROM authority_operation o JOIN authority_attempt a USING(operation_id)
            WHERE o.project_id=%s AND o.definition_name='story_planning.generate'""", [fixture.project_id])
        attempts = uow.cursor.fetchall()
        assert len(attempts) == 1
        failure = attempts[0][2]
        assert failure["error_code"] == "TASK_CONTEXT_REQUIRED_BUDGET_EXCEEDED"
        assert failure["failure_details"]["reserved"] > failure["failure_details"]["limit"] == 64
        uow.cursor.execute("SELECT snapshot_id,snapshot_hash FROM authority_attempt_capability_pack_snapshot WHERE operation_id=%s", [attempts[0][0]])
        snapshot = uow.cursor.fetchone()
        assert all(snapshot)
        uow.cursor.execute("SELECT asset_version_id,content_hash FROM authority_operation_output_asset WHERE operation_id=%s ORDER BY asset_version_id", [attempts[0][0]])
        preparation = uow.cursor.fetchall()
        assert preparation
        uow.cursor.execute("SELECT count(*) FROM authority_external_effect WHERE operation_id=%s", [attempts[0][0]])
        assert uow.cursor.fetchone() == (0,)
    assessment = fixture.opening.recovery.assess_recovery(original.opening_run_id,
        idempotency_key="native-preflight", principal=fixture.principal)
    kwargs = dict(idempotency_key="native-preflight-resume", reason="Restore configured capacity without resending any call", principal=fixture.principal)
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: fixture.opening.recovery.recover(assessment.recovery_assessment_id, **kwargs), range(2)))
    assert sum(item.replayed for item in outcomes) == 1
    recovered = fixture.opening.require(original.opening_run_id)
    assert recovered["current_execution_generation"] == failed["current_execution_generation"] + 1
    assert get_creative_budget(DATABASE_URL, fixture.project_id) == usage
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT result FROM authority_attempt WHERE attempt_id=%s", [attempts[0][1]])
        assert uow.cursor.fetchone() == (failure,)
        uow.cursor.execute("SELECT asset_version_id,content_hash FROM authority_operation_output_asset WHERE operation_id=%s ORDER BY asset_version_id", [attempts[0][0]])
        assert uow.cursor.fetchall() == preparation
        uow.cursor.execute("SELECT snapshot_id,snapshot_hash FROM authority_attempt_capability_pack_snapshot WHERE operation_id=%s", [attempts[0][0]])
        assert uow.cursor.fetchone() == snapshot
    assert fixture.claim(fixture.principal.principal_id) is not None


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
    with pytest.raises(KernelError, match="CONTINUATION_SOURCE_INVALID"):
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
    with pytest.raises(KernelError, match="PLANNING_RUNTIME_CONTINUATION_DISPATCH_UNSAFE"):
        fixture.execute(claim)
    failed = fixture.opening.require(original.opening_run_id)
    with pytest.raises(KernelError, match="CONTINUATION_SOURCE_INVALID"):
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


def test_resource_policy_successor_preserves_completed_nodes_and_historical_scope(monkeypatch):
    from novel_forge.modules.book_authority.resource_succession import adopt_resource_policy, prospective_scope
    from novel_forge.modules.command_kernel.budget_runtime import assess_budget_scope_in_uow, lock_budget_scope_in_uow
    fixture, original, successor_app = _capacity_fixture(resource_successor=True)
    fixture.execute(fixture.claim(fixture.principal.principal_id))
    before = fixture.opening.require(original.opening_run_id)
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT node_receipt_id FROM authority_book_opening_node_receipt WHERE opening_run_id=%s", [original.opening_run_id])
        receipts = uow.cursor.fetchall()
        assert receipts
        scope = lock_budget_scope_in_uow(uow, budget_scope_id=before["budget_scope_id"], project_id=fixture.project_id)
    args = dict(opening_run_id=original.opening_run_id, expected_version=before["version"],
        principal=fixture.principal, idempotency_key="adopt-resource-policy:" + original.opening_run_id)
    adopted = adopt_resource_policy(successor_app, **args)
    assert adopt_resource_policy(successor_app, **args)["replayed"]
    assert adopted["source_policy_hash"] == scope["policy_hash"]
    assert fixture.opening.require(original.opening_run_id) == before
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        assert lock_budget_scope_in_uow(uow, budget_scope_id=before["budget_scope_id"], project_id=fixture.project_id) == scope
        modern = prospective_scope(uow, scope)
        assert modern["policy_snapshot"]["resource_control_version"] == "billing-channel-resources.v1"
        assert prospective_scope(uow, scope, operation_id=before["root_operation_id"]) == scope
        assessment = assess_budget_scope_in_uow(uow, budget_scope_id=before["budget_scope_id"], project_id=fixture.project_id,
            requested_tokens=160000, requested_amount=None)
        assert assessment["outcome"] == "ELIGIBLE" and assessment["headroom"]["tokens"] is None
        assert assessment["scope"]["resource_successor"]["source_policy_hash"] == scope["policy_hash"]
        uow.cursor.execute("SELECT node_receipt_id FROM authority_book_opening_node_receipt WHERE opening_run_id=%s", [original.opening_run_id])
        assert uow.cursor.fetchall() == receipts
    fixture.opening = successor_app
    _fail_before_result(fixture, monkeypatch)
    failed = fixture.opening.require(original.opening_run_id)
    assessment = successor_app.recovery.assess_recovery(original.opening_run_id,
        idempotency_key="resource-successor-recovery", principal=fixture.principal)
    assert assessment.snapshot["budget"]["outcome"] == "ELIGIBLE"
    successor_app.recovery.recover(assessment.recovery_assessment_id, idempotency_key="resource-successor-resume",
        reason="continue unexecuted work after adopting native resource policy", principal=fixture.principal)
    recovered = successor_app.require(original.opening_run_id)
    assert recovered["current_execution_generation"] == failed["current_execution_generation"] + 1
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT node_receipt_id FROM authority_book_opening_node_receipt WHERE opening_run_id=%s", [original.opening_run_id])
        assert uow.cursor.fetchall() == receipts


def test_resource_successor_cannot_adopt_an_unresolved_provider_intent(monkeypatch):
    from novel_forge.modules.book_authority.resource_succession import adopt_resource_policy
    fixture, original, successor_app = _capacity_fixture(resource_successor=True)
    def fail_after_intent(**kwargs):
        plan_external_effect(DATABASE_URL, EffectCommandContext(kwargs["operation_id"], fixture.project_id,
            fixture.principal.principal_id, identifier("trace"), identifier("correlation")),
            effect_type="model.invoke", provider="fake_deterministic_provider", capability="model.fixture",
            stable_idempotency_key=identifier("unresolved-intent"), request_payload={"fixture": True}, max_attempts=1, reversible=False)
        raise KernelError("PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED", "unresolved historical intent")
    monkeypatch.setattr(fixture.binder, "execute", fail_after_intent)
    with pytest.raises(KernelError):
        fixture.execute(fixture.claim(fixture.principal.principal_id))
    failed = fixture.opening.require(original.opening_run_id)
    with pytest.raises(KernelError, match="RESOURCE_SUCCESSOR_RECONCILIATION_REQUIRED"):
        adopt_resource_policy(successor_app, opening_run_id=original.opening_run_id,
            expected_version=failed["version"], principal=fixture.principal, idempotency_key="reject-unresolved")
