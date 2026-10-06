from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest

from novel_forge.modules.authority_handler_runtime.policy_commands import configure_owned_policy
from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.command_kernel.budget_runtime import BudgetReservationRequest, reserve_provider_budget, settle_provider_budget, resolve_provider_budget_failure
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_runtime import EffectCommandContext, plan_external_effect
from novel_forge.modules.production_execution.cost_routing import CostAwareRouter
from novel_forge.modules.production_execution.execution_template import paid_usage, template_decision
from novel_forge.modules.production_execution.routing_runtime import PostgresRoutingRegistry
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated, identifier, insert_definition, insert_operation, seed_authority_project_book, transaction
from tests.unit.test_creative_execution_template import template, membership
from tests.unit.test_cost_aware_routing import NOW, candidate, task


@pytest.fixture
def work():
    ensure_migrated()
    project, book = identifier("creative-project"), identifier("creative-book")
    seed_authority_project_book(project_id=project, workspace_id="fixture-workspace:" + project, book_id=book)
    operator = Principal("fixture-operator", PrincipalType.LOCAL_OPERATOR,
                         frozenset({"book.authority.execute"}), frozenset({project}), "isolated-test")
    value = template(book, {"account_ref": "fixture-account", "currency": "USD", "maximum_amount": "1", "authorization_ref": "fixture-paid-grant"})

    def configure(version="v1", selected=value):
        configure_owned_policy(database_url=DATABASE_URL, owner="PROVIDER_ROUTING", project_id=project,
            workspace_id="fixture-workspace", principal=operator, application_build_id="isolated-creative-test", commit_sha="a" * 40,
            idempotency_key=identifier("configure"), trace_id=identifier("trace"), correlation_id=project,
            content={"policy_version": version, "reason": "isolated native resource-policy regression", "task_overrides": [], "execution_templates": [selected]})

    configure()
    return project, book, configure


def request(work, provider="deepseek"):
    project, book, _ = work
    operation, definition = identifier("creative-op"), identifier("creative-definition")
    with transaction() as connection, connection.cursor() as cursor:
        insert_definition(cursor, definition)
        insert_operation(cursor, operation_id=operation, definition_name=definition,
                         project_id=project, status="EXECUTING", command_payload={"book_id": book})
    model = candidate() if provider == "deepseek" else membership()
    registry = PostgresRoutingRegistry(DATABASE_URL)
    from novel_forge.modules.production_execution.membership_identity import observed_paid_binding
    channel = {"resource_control_version": "billing-channel-resources.v1", "remaining_tokens": 100000,
               "remaining_money": "1" if provider == "deepseek" else None,
               "paid_authorized": True, "account_ref": "fixture-account",
               "billing_identity": observed_paid_binding("fixture-account", "fixture-credential")}
    t = task(project_id=project, work_id=book, operation_id=operation,
             policy_snapshot=registry.policy(project), budget_snapshot={"task_token_limit": 100000,
                 "task_money_limit": "1", "candidates": {model.candidate_id: channel}},
             chain_id="fixture-chain:" + operation, lineage_operation_ids=(operation,))
    decision = template_decision(CostAwareRouter().explain(t, [model], {}, now=NOW)).to_dict()
    assert decision["status"] == "SELECTED"
    effect = plan_external_effect(DATABASE_URL, EffectCommandContext(operation, project, "fixture-operator", identifier("trace"), project),
        effect_type="model.invoke", provider=provider, capability="model.fixture", stable_idempotency_key=identifier("effect"),
        request_payload={"stage": "classification", "max_output_tokens": 100,
            "_production_execution": {"book_id": book, "capability_runtime": {"routing_decision": decision}}},
        max_attempts=2, reversible=False, completion_policy="synchronous_final", model_id=model.model,
        request_timeout_seconds=60, reconciliation_mode="query")["external_effect_id"]
    return BudgetReservationRequest(operation, effect, project, "reservation:" + effect, provider,
        "USD" if provider == "deepseek" else "UNKNOWN", "0.6" if provider == "deepseek" else None, 1100,
        model_id=model.model, work_id=book, accounting_basis=model.pricing.accounting_basis,
        cost_authorization_ref="member-grant" if provider == "codex-cli" else "",
        call_caps={"project_total": 1}, token_caps={"project_total": 1})


def test_paid_concurrency_unknown_resume_and_membership_are_separate(work):
    requests = [request(work), request(work)]

    def reserve(value):
        try:
            return reserve_provider_budget(DATABASE_URL, value)
        except KernelError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(reserve, requests))
    assert sum(isinstance(value, dict) for value in outcomes) == 1
    assert "RESOURCE_ROUTE_RESELECT_REQUIRED" in outcomes
    index = next(i for i, value in enumerate(outcomes) if isinstance(value, dict))
    reservation = outcomes[index]
    resolve_provider_budget_failure(DATABASE_URL, project_id=work[0], reservation_id=reservation["reservation_id"], external_state_unknown=True)
    replay = reserve_provider_budget(DATABASE_URL, requests[index])
    assert replay["status"] == "HELD_UNKNOWN" and replay["execution_authorized"] is False
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        assert paid_usage(uow.cursor, project_id=work[0], book_id=work[1]) == Decimal("0.6")
    member = request(work, "codex-cli")
    reserved = reserve_provider_budget(DATABASE_URL, member)
    settled = settle_provider_budget(DATABASE_URL, reservation_id=reserved["reservation_id"], project_id=work[0],
        actual_amount=None, actual_tokens=999999, evidence={"fixture": True, "usage": "observed"})
    assert settled["status"] == "SETTLED" and not settled.get("budget_breach", False)


def test_settlement_is_idempotent_and_successor_cannot_reset_or_raise_paid_cap(work):
    first = request(work)
    reserved = reserve_provider_budget(DATABASE_URL, first)
    args = dict(reservation_id=reserved["reservation_id"], project_id=work[0], actual_amount="0.4", actual_tokens=50, evidence={"fixture": True})
    assert settle_provider_budget(DATABASE_URL, **args)["status"] == "SETTLED"
    assert settle_provider_budget(DATABASE_URL, **args)["replayed"]
    work[2]("v2")
    second = request(work)
    next_reservation = reserve_provider_budget(DATABASE_URL, second)
    assert next_reservation["status"] == "RESERVED"
    with pytest.raises(KernelError, match="PAID_WORK_BUDGET_EXHAUSTED"):
        reserve_provider_budget(DATABASE_URL, request(work))
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        assert paid_usage(uow.cursor, project_id=work[0], book_id=work[1]) == Decimal("1")
    raised = template(work[1], {"account_ref": "fixture-account", "currency": "USD", "maximum_amount": "2", "authorization_ref": "fixture-paid-grant"})
    with pytest.raises(KernelError, match="SUCCESSOR_EXPANSION_FORBIDDEN"):
        work[2]("v3", raised)


def test_proven_unsent_cancellation_reclaims_only_unconsumed_reservation(work):
    first = request(work)
    reserved = reserve_provider_budget(DATABASE_URL, first)
    result = resolve_provider_budget_failure(DATABASE_URL, project_id=work[0], reservation_id=reserved["reservation_id"], external_state_unknown=False)
    assert result["status"] == "RELEASED"
    assert reserve_provider_budget(DATABASE_URL, request(work))["status"] == "RESERVED"


def test_budget_race_cancels_only_proven_unsent_intent_and_keeps_a_new_route_key(work):
    from novel_forge.modules.command_kernel.resource_route_recovery import next_resource_effect_key
    first = request(work)
    reserve_provider_budget(DATABASE_URL, first)
    denied = request(work)
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT stable_idempotency_key,request_payload FROM authority_external_effect WHERE external_effect_id=%s", [denied.external_effect_id])
        key, frozen = uow.cursor.fetchone()
    with pytest.raises(KernelError, match="RESOURCE_ROUTE_RESELECT_REQUIRED"):
        reserve_provider_budget(DATABASE_URL, denied)
    successor_key = next_resource_effect_key(DATABASE_URL, project_id=work[0], operation_id=denied.operation_id, stable_key=key)
    assert successor_key != key
    assert next_resource_effect_key(DATABASE_URL, project_id=work[0], operation_id=denied.operation_id, stable_key=key) == successor_key
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT status,request_payload FROM authority_external_effect WHERE external_effect_id=%s", [denied.external_effect_id])
        assert uow.cursor.fetchone() == ("CANCELLED", frozen)
        assert paid_usage(uow.cursor, project_id=work[0], book_id=work[1]) == Decimal("0.6")
    assert reserve_provider_budget(DATABASE_URL, request(work, "codex-cli"))["status"] == "RESERVED"


def test_paid_dispatch_rejects_credential_rotation_and_soft_lane_caps_do_not_block(work):
    from novel_forge.modules.production_execution.membership_identity import observed_paid_binding
    from novel_forge.modules.production_execution.routing_runtime import ProductionProviderRouter
    value = request(work)
    identity = observed_paid_binding("fixture-account", "fixture-credential")
    router = ProductionProviderRouter(DATABASE_URL, candidates=(candidate(), membership()), task_money_limit="0", task_token_limit=100000,
        execution_environment="validation", money_caps={"operation": "0"}, token_caps={"project": 1}, call_caps={"project": 1},
        provider_billing_accounts={"deepseek": "fixture-account"}, provider_billing_identities={"deepseek": identity})
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT request_payload #> '{_production_execution,capability_runtime,routing_decision}' FROM authority_external_effect WHERE external_effect_id=%s", [value.external_effect_id])
        frozen = uow.cursor.fetchone()[0]
    budgets = router._candidate_budgets(project_id=work[0], work_id=work[1], operation_id=value.operation_id,
        stable_key="unexecuted-route", template=template(work[1], {"account_ref": "fixture-account", "currency": "USD", "maximum_amount": "1", "authorization_ref": "fixture-paid-grant"}))
    assert budgets["flash"]["remaining_money"] == "1" and budgets["flash"]["remaining_calls"] is None
    assert budgets["member"]["remaining_money"] is None and budgets["member"]["remaining_tokens"] == membership().context_limit
    router.provider_billing_identities["deepseek"] = observed_paid_binding("fixture-account", "another-fixture-credential")
    with pytest.raises(KernelError, match="PAID_BILLING_CREDENTIAL_DRIFT"):
        router._selected_route(None, frozen)


def test_reported_paid_overrun_holds_actual_charge_and_only_blocks_paid_channel(work):
    first = request(work)
    reserved = reserve_provider_budget(DATABASE_URL, first)
    with pytest.raises(KernelError, match="BUDGET_ACTUAL_EXCEEDS_RESERVATION"):
        settle_provider_budget(DATABASE_URL, reservation_id=reserved["reservation_id"], project_id=work[0],
            actual_amount="1.2", actual_tokens=50, evidence={"fixture": True, "reported_provider_charge": True})
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        assert paid_usage(uow.cursor, project_id=work[0], book_id=work[1]) == Decimal("1.2")
    with pytest.raises(KernelError, match="PAID_WORK_BUDGET_EXHAUSTED"):
        reserve_provider_budget(DATABASE_URL, request(work))
    assert reserve_provider_budget(DATABASE_URL, request(work, "codex-cli"))["status"] == "RESERVED"
