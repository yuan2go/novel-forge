from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest
from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.budget_runtime import (
    BudgetReservationRequest,
    reserve_provider_budget,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_runtime import (
    EffectCommandContext,
    plan_external_effect,
)
from novel_forge.modules.production_execution.cost_routing import (
    CostAwareRouter,
    RoutingTask,
)
from novel_forge.modules.production_execution.routing_catalog import deepseek_candidates
from novel_forge.modules.production_execution.routing_runtime import (
    PostgresRoutingRegistry,
    ProductionProviderRouter,
)
from novel_forge.storage.authority_asset_store import AuthorityAssetWriter
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    insert_definition,
    insert_operation,
    transaction,
)


@pytest.fixture
def scope():
    ensure_migrated()
    project, operation, definition = (
        identifier("router-project"),
        identifier("router-operation"),
        identifier("router-definition"),
    )
    with transaction() as connection, connection.cursor() as cursor:
        insert_definition(cursor, definition)
        insert_operation(
            cursor,
            operation_id=operation,
            definition_name=definition,
            project_id=project,
            status="EXECUTING",
        )
    return project, operation


def write_asset(scope, kind, content):
    project, operation = scope
    asset = identifier(kind)
    return AuthorityAssetWriter(DATABASE_URL).materialize_output(
        AuthorityAssetWriteCommand(
            operation,
            project,
            asset,
            kind,
            "routing-test.v1",
            "routing-test/" + asset,
            "test",
            asset,
            "evidence",
            content,
            "routing-test",
            "test-trace",
            "test-correlation",
        )
    )


def test_registry_projects_existing_model_and_quality_evidence_without_forging_acceptance(
    scope,
):
    registry = PostgresRoutingRegistry(DATABASE_URL)
    candidate = deepseek_candidates(available=True)[0]
    task = RoutingTask(
        "draft", scope[0], "book", scope[1], "attempt", 100, 100, 1000, "1"
    )
    assert (
        CostAwareRouter().explain(task, [candidate], {}).to_dict()["status"]
        == "BLOCKED"
    )
    for i in range(10):
        request = budget_request(
            scope, decision={"selected": {"candidate": asdict(candidate)}}
        )
        evidence = {
            "provider_id": candidate.provider,
            "model_id": candidate.model,
            "real_model_call": True,
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50,
                "prompt_cache_hit_tokens": 80,
            },
            "cost": {"amount": ".0001"},
            "production_execution": {
                "execution_request": {
                    "external_effect_id": request.external_effect_id,
                    "stage": "draft",
                },
                "route_snapshot": {"reasoning_effort": candidate.reasoning},
                "execution_result": {"outcome": "SUCCEEDED"},
                "process_evidence": {
                    "latency_seconds": 2,
                    "served_model_identity_hash": "sha256:fixture-served-cohort",
                },
            },
        }
        write_asset(
            scope, "model_call_log", {"stage": "draft", "provider_evidence": evidence}
        )
        draft = write_asset(scope, "draft_version", {"provider_evidence": evidence})
        write_asset(
            scope,
            "quality_score_report",
            {
                "target_asset_version_id": draft.asset_version_id,
                "aggregate_score": 99,
                "fixture": False,
                "provider_verified": True,
                "uncalibrated_dimensions": [],
                "gate": "PASSED",
            },
        )
    legacy_evidence = {
        **evidence,
        "production_execution": {
            **evidence["production_execution"],
            "execution_request": {
                "external_effect_id": "fixture-legacy-without-revision",
                "stage": "draft",
            },
        },
    }
    write_asset(
        scope,
        "model_call_log",
        {"stage": "draft", "provider_evidence": legacy_evidence},
    )
    missing_cohort_request = budget_request(
        scope, decision={"selected": {"candidate": asdict(candidate)}}
    )
    missing_cohort = {
        **evidence,
        "production_execution": {
            **evidence["production_execution"],
            "execution_request": {
                "external_effect_id": missing_cohort_request.external_effect_id,
                "stage": "draft",
            },
            "process_evidence": {"latency_seconds": 2},
        },
    }
    write_asset(
        scope, "model_call_log", {"stage": "draft", "provider_evidence": missing_cohort}
    )
    observations = registry.observations(
        project_id=scope[0], task_type="draft", candidate=candidate
    )
    assert len(observations) == 10
    assert all(row.accepted is None for row in observations)
    decision = CostAwareRouter().explain(
        task, [candidate], {candidate.candidate_id: observations}
    )
    assert decision.to_dict()["status"] == "SELECTED"
    saved = registry.save(
        decision,
        logical_ref="routing-test/frozen",
        trace_id="test",
        correlation_id="test",
    )
    replay = registry.query.require(project_id=scope[0], asset_id=decision.decision_id)
    assert replay.content == decision.to_dict()
    assert saved["asset_version_id"] == replay.asset_version_id
    assert replay.content["selected"]["benchmark"]["cache_hit_ratio"] == 0.8


def test_cold_start_persists_block_and_never_dispatches(scope):
    router = ProductionProviderRouter(
        DATABASE_URL,
        candidates=deepseek_candidates(available=True),
        task_money_limit="1",
        task_token_limit=1000,
    )
    with pytest.raises(KernelError, match="PROVIDER_ROUTING_BLOCKED"):
        router.select(
            SimpleNamespace(),
            task_type="draft",
            project_id=scope[0],
            work_id="book",
            operation_id=scope[1],
            attempt_id="attempt",
            stable_key="draft",
            input_tokens=100,
            output_tokens=100,
            trace_id="test",
            correlation_id="test",
        )
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM authority_asset WHERE project_id=%s AND asset_type='routing_decision'",
            [scope[0]],
        )
        assert cursor.fetchone()[0] == 1
        cursor.execute(
            "SELECT count(*) FROM authority_external_effect WHERE operation_id=%s",
            [scope[1]],
        )
        assert cursor.fetchone()[0] == 0


def test_unknown_outcome_dominates_cause_and_successful_agent_turns_do_not_join_other_chains(
    scope,
):
    registry = PostgresRoutingRegistry(DATABASE_URL)
    project, operation = scope
    for number in range(5):
        effect = identifier("effect")
        decision = {
            "task": {"chain_id": f"turn:{number}"},
            "selected": {
                "candidate": {
                    "candidate_id": "deepseek:flash",
                    "escalation_only": False,
                }
            },
        }
        payload = {
            "stage": "agent_session",
            "_production_execution": {
                "capability_runtime": {"routing_decision": decision}
            },
        }
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO authority_external_effect(external_effect_id,operation_id,project_id,effect_type,
                stable_idempotency_key,status,request_hash,request_payload) VALUES(%s,%s,%s,'model.invoke',%s,%s,%s,%s)""",
                [
                    effect,
                    operation,
                    project,
                    effect,
                    "UNKNOWN" if number == 4 else "SUCCEEDED",
                    effect,
                    Jsonb(payload),
                ],
            )
            cursor.execute(
                """INSERT INTO authority_external_effect_dispatch(dispatch_id,external_effect_id,generation,status,
                payload_hash,evidence) VALUES(%s,%s,1,'UNKNOWN',%s,%s)""",
                [
                    identifier("dispatch"),
                    effect,
                    effect,
                    Jsonb(
                        {
                            "production_execution": {
                                "process_evidence": {"failure_class": "TIMEOUT"}
                            }
                        }
                    ),
                ],
            )
    assert (
        registry.history(
            project_id=project,
            operation_id=operation,
            task_type="agent_session",
            chain_id="next-turn",
        )
        == ()
    )
    history = registry.history(
        project_id=project,
        operation_id=operation,
        task_type="agent_session",
        chain_id="turn:4",
    )
    assert len(history) == 1
    assert history[0]["failure_class"] == "UNKNOWN_EXTERNAL_OUTCOME"


@pytest.mark.parametrize(
    "dimension", ["work_total", "model_project_total", "project_monthly"]
)
def test_new_budget_dimensions_do_not_oversubscribe_under_concurrency(scope, dimension):
    project, operation = scope
    context = EffectCommandContext(operation, project, "test", "test", "test")
    requests = []
    for i in range(2):
        effect = plan_external_effect(
            DATABASE_URL,
            context,
            effect_type="model.invoke",
            provider="production_execution_gateway",
            capability="model.draft",
            stable_idempotency_key=identifier("effect"),
            request_payload={
                "stage": "draft",
                "_production_execution": {"book_id": "book:test"},
            },
            max_attempts=2,
            reversible=False,
            completion_policy="synchronous_final",
            model_id="deepseek-flash",
            request_timeout_seconds=30,
            reconciliation_mode="unsupported",
        )
        requests.append(
            BudgetReservationRequest(
                operation,
                str(effect["external_effect_id"]),
                project,
                identifier("reservation"),
                "deepseek",
                "USD",
                ".006",
                100,
                model_id="deepseek-flash",
                work_id="book:test",
                caps={dimension: ".01"},
            )
        )

    def reserve(request):
        try:
            return reserve_provider_budget(DATABASE_URL, request)["status"]
        except KernelError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(reserve, requests)) == [
            "BUDGET_CAP_EXCEEDED",
            "RESERVED",
        ]
    with pytest.raises(KernelError, match="BUDGET_SCOPE"):
        reserve_provider_budget(
            DATABASE_URL, replace(requests[0], model_id="different")
        )


def budget_request(scope, *, provider="deepseek", decision=None, new_operation=False):
    project, operation = scope
    if new_operation:
        operation, definition = (
            identifier("budget-operation"),
            identifier("budget-definition"),
        )
        with transaction() as connection, connection.cursor() as cursor:
            insert_definition(cursor, definition)
            insert_operation(
                cursor,
                operation_id=operation,
                definition_name=definition,
                project_id=project,
                status="EXECUTING",
            )
    model = "gpt-5.6-sol" if provider == "codex-cli" else "deepseek-flash"
    metadata = {"book_id": "book:test"}
    if decision is not None:
        metadata["capability_runtime"] = {"routing_decision": decision}
    effect = plan_external_effect(
        DATABASE_URL,
        EffectCommandContext(operation, project, "test", "test", "test"),
        effect_type="model.invoke",
        provider="production_execution_gateway",
        capability="model.draft",
        stable_idempotency_key=identifier("effect"),
        request_payload={
            "stage": "draft",
            "max_output_tokens": 40,
            "_production_execution": metadata,
        },
        max_attempts=4,
        reversible=False,
        completion_policy="synchronous_final",
        model_id=model,
        request_timeout_seconds=30,
        reconciliation_mode="unsupported",
    )
    entitlement = provider == "codex-cli"
    return BudgetReservationRequest(
        operation,
        str(effect["external_effect_id"]),
        project,
        identifier("reservation"),
        provider,
        "UNKNOWN" if entitlement else "USD",
        None if entitlement else ".006",
        100,
        model_id=model,
        work_id="book:test",
        accounting_basis="ACCOUNT_ENTITLEMENT" if entitlement else "PRICED",
        cost_authorization_ref=(decision or {})
        .get("selected", {})
        .get("candidate", {})
        .get("authorization_ref", "test-entitlement")
        if entitlement
        else "",
    )


def frozen_budget_decision(
    scope,
    *,
    provider="deepseek",
    chain="chain:test",
    quota=3,
    money="1",
    tokens=1000,
    attempts=4,
    escalations=2,
):
    entitlement = provider == "codex-cli"
    return {
        "status": "SELECTED",
        "task": {
            "project_id": scope[0],
            "operation_id": scope[1],
            "work_id": "book:test",
            "chain_id": chain,
            "budget_snapshot": {"task_money_limit": money, "task_token_limit": tokens},
        },
        "selected": {
            "candidate": {
                "provider": provider,
                "model": "gpt-5.6-sol" if entitlement else "deepseek-flash",
                "escalation_only": entitlement,
                "authorization_ref": identifier("authorization"),
                "quota_remaining": quota,
                "pricing": {
                    "accounting_basis": "ACCOUNT_ENTITLEMENT"
                    if entitlement
                    else "PRICED",
                    "currency": "UNKNOWN" if entitlement else "USD",
                    "input_miss_per_million": "1",
                    "output_per_million": "2",
                },
            }
        },
        "escalation_policy": {"max_attempts": attempts, "max_escalations": escalations},
    }


def reserve_outcome(request):
    try:
        return reserve_provider_budget(DATABASE_URL, request)["status"]
    except KernelError as exc:
        return exc.code


@pytest.mark.parametrize("dimension", ["project_total", "work_total", "global_total"])
def test_mixed_entitlement_and_priced_usage_share_lock(scope, dimension):
    from psycopg.errors import LockNotAvailable
    from novel_forge.modules.command_kernel.budget_runtime import (
        reserve_provider_budget_in_uow,
    )
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork

    # WHY: Different Operations prevent their row locks from masking a missing shared budget lock.
    requests = [
        budget_request(scope),
        budget_request(scope, provider="codex-cli", new_operation=True),
    ]
    if dimension == "global_total":
        with transaction() as connection, connection.cursor() as cursor:
            from novel_forge.modules.command_kernel.budget_runtime import (
                provider_usage_accounted_sql,
            )

            cursor.execute(
                f"SELECT COALESCE(sum(CASE WHEN status='SETTLED' THEN actual_tokens ELSE greatest(actual_tokens,estimated_tokens) END),0) FROM authority_budget_reservation WHERE {provider_usage_accounted_sql()}"
            )
            used = int(cursor.fetchone()[0])
    else:
        used = 0
    requests = [
        replace(request, token_caps={dimension: used + 150}) for request in requests
    ]
    with AuthorityUnitOfWork(DATABASE_URL) as first:
        reserve_provider_budget_in_uow(first, requests[0])

        def competing():
            with AuthorityUnitOfWork(DATABASE_URL) as second:
                second.cursor.execute("SET LOCAL lock_timeout='200ms'")
                return reserve_provider_budget_in_uow(second, requests[1])

        with ThreadPoolExecutor(max_workers=1) as pool:
            with pytest.raises(LockNotAvailable):
                pool.submit(competing).result(timeout=5)
        first.commit()
    assert reserve_outcome(requests[1]) == "BUDGET_TOKEN_CAP_EXCEEDED"


@pytest.mark.parametrize(
    "limits,error",
    [
        ({"money": ".01"}, "BUDGET_CAP_EXCEEDED"),
        ({"tokens": 150}, "BUDGET_TOKEN_CAP_EXCEEDED"),
        ({"attempts": 1}, "ROUTING_CHAIN_ATTEMPTS_EXHAUSTED"),
    ],
)
def test_frozen_chain_decisions_cannot_oversubscribe(scope, limits, error):
    requests = [
        budget_request(scope, decision=frozen_budget_decision(scope, **limits))
        for _ in range(2)
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(reserve_outcome, requests)) == sorted(
            ["RESERVED", error]
        )


def test_same_effect_reservation_generation_consumes_chain_attempt(scope):
    from novel_forge.modules.command_kernel.budget_runtime import (
        resolve_provider_budget_failure,
    )

    request = budget_request(scope, decision=frozen_budget_decision(scope, attempts=1))
    reservation = reserve_provider_budget(DATABASE_URL, request)
    resolve_provider_budget_failure(
        DATABASE_URL, reservation_id=reservation["reservation_id"], project_id=scope[0]
    )
    assert (
        reserve_outcome(replace(request, stable_idempotency_key=identifier("retry")))
        == "ROUTING_CHAIN_ATTEMPTS_EXHAUSTED"
    )


@pytest.mark.parametrize("legacy", [False, True])
def test_entitlement_settlement_reconstructs_model_and_work(scope, legacy):
    from novel_forge.modules.command_kernel.budget_runtime import settle_provider_budget

    request = replace(
        budget_request(scope, provider="codex-cli"),
        token_caps={"work_total": 200, "model_project_total": 200},
    )
    reservation = reserve_provider_budget(DATABASE_URL, request)
    if legacy:
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE authority_budget_reservation SET evidence=evidence-'model_id'-'work_id',version=version+1 WHERE reservation_id=%s",
                [reservation["reservation_id"]],
            )
    result = settle_provider_budget(
        DATABASE_URL,
        reservation_id=reservation["reservation_id"],
        project_id=scope[0],
        actual_amount=None,
        actual_tokens=150,
        evidence={
            "model_id": request.model_id,
            "token_accounting_precision": "APPLICATION_VISIBLE_UPPER_BOUND",
            "actual_token_source": "PROVIDER_USAGE_RECEIPT",
        },
    )
    assert result["status"] == "SETTLED"
    assert result["entitlement_usage_reconciled"] is True


def test_codex_quota_counts_paid_retries_of_same_effect(scope):
    from novel_forge.modules.command_kernel.budget_runtime import settle_provider_budget

    request = budget_request(
        scope,
        provider="codex-cli",
        decision=frozen_budget_decision(scope, provider="codex-cli", quota=1),
    )
    reservation = reserve_provider_budget(DATABASE_URL, request)
    settle_provider_budget(
        DATABASE_URL,
        reservation_id=reservation["reservation_id"],
        project_id=scope[0],
        actual_amount=None,
        actual_tokens=90,
        evidence={"model_id": request.model_id},
    )
    assert (
        reserve_outcome(replace(request, stable_idempotency_key=identifier("retry")))
        == "BUDGET_CALL_CAP_EXCEEDED"
    )


def test_routed_entitlement_cannot_relabel_priced_candidate(scope):
    request = budget_request(scope, decision=frozen_budget_decision(scope))
    assert (
        reserve_outcome(
            replace(
                request,
                currency="UNKNOWN",
                estimated_amount=None,
                accounting_basis="ACCOUNT_ENTITLEMENT",
                cost_authorization_ref="unexpected",
            )
        )
        == "ROUTING_BUDGET_ACCOUNTING_CONFLICT"
    )


def test_chain_entitlement_actual_usage_cannot_exceed_frozen_task_budget(scope):
    from novel_forge.modules.command_kernel.budget_runtime import settle_provider_budget

    request = replace(
        budget_request(
            scope,
            provider="codex-cli",
            decision=frozen_budget_decision(scope, provider="codex-cli", tokens=120),
        ),
        token_caps={"project_total": 200},
    )
    reservation = reserve_provider_budget(DATABASE_URL, request)
    with pytest.raises(KernelError, match="BUDGET_ACTUAL_EXCEEDS_RESERVATION"):
        settle_provider_budget(
            DATABASE_URL,
            reservation_id=reservation["reservation_id"],
            project_id=scope[0],
            actual_amount=None,
            actual_tokens=150,
            evidence={
                "token_accounting_precision": "APPLICATION_VISIBLE_UPPER_BOUND",
                "actual_token_source": "PROVIDER_USAGE_RECEIPT",
            },
        )
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT status FROM authority_budget_reservation WHERE reservation_id=%s",
            [reservation["reservation_id"]],
        )
        assert cursor.fetchone()[0] == "HELD_UNKNOWN"


def test_codex_quota_serializes_independent_frozen_chains(scope):
    first = frozen_budget_decision(
        scope, provider="codex-cli", chain="chain:first", quota=1
    )
    second = frozen_budget_decision(
        scope, provider="codex-cli", chain="chain:second", quota=1
    )
    second["selected"]["candidate"]["authorization_ref"] = first["selected"][
        "candidate"
    ]["authorization_ref"]
    requests = [
        budget_request(scope, provider="codex-cli", decision=decision)
        for decision in (first, second)
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(reserve_outcome, requests)) == [
            "BUDGET_CALL_CAP_EXCEEDED",
            "RESERVED",
        ]


def test_routed_reservation_cannot_underfund_frozen_price(scope):
    request = budget_request(scope, decision=frozen_budget_decision(scope))
    assert (
        reserve_outcome(replace(request, estimated_amount="0"))
        == "ROUTING_BUDGET_RESERVATION_INSUFFICIENT"
    )


def test_entitlement_authorization_must_match_selected_candidate(scope):
    request = budget_request(
        scope,
        provider="codex-cli",
        decision=frozen_budget_decision(scope, provider="codex-cli"),
    )
    assert (
        reserve_outcome(replace(request, cost_authorization_ref="different"))
        == "ROUTING_ESCALATION_AUTHORIZATION_CONFLICT"
    )


def test_chain_escalation_limit_applies_to_same_effect_retry(scope):
    from novel_forge.modules.command_kernel.budget_runtime import settle_provider_budget

    request = budget_request(
        scope,
        provider="codex-cli",
        decision=frozen_budget_decision(
            scope, provider="codex-cli", escalations=1, quota=10
        ),
    )
    reservation = reserve_provider_budget(DATABASE_URL, request)
    settle_provider_budget(
        DATABASE_URL,
        reservation_id=reservation["reservation_id"],
        project_id=scope[0],
        actual_amount=None,
        actual_tokens=90,
        evidence={"model_id": request.model_id},
    )
    assert (
        reserve_outcome(replace(request, stable_idempotency_key=identifier("retry")))
        == "ROUTING_ESCALATION_LIMIT_REACHED"
    )


@pytest.mark.parametrize("provider", ["deepseek", "codex-cli"])
def test_generic_call_caps_charge_each_paid_reservation_generation(scope, provider):
    from novel_forge.modules.command_kernel.budget_runtime import (
        provider_project_usage,
        settle_provider_budget,
    )

    request = replace(
        budget_request(scope, provider=provider), call_caps={"project_total": 2}
    )
    for _ in range(2):
        reservation = reserve_provider_budget(DATABASE_URL, request)
        replay = reserve_provider_budget(DATABASE_URL, request)
        assert replay["reservation_id"] == reservation["reservation_id"]
        settle_provider_budget(
            DATABASE_URL,
            reservation_id=reservation["reservation_id"],
            project_id=scope[0],
            actual_amount=None if provider == "codex-cli" else ".001",
            actual_tokens=90,
            evidence={"model_id": request.model_id},
        )
        request = replace(request, stable_idempotency_key=identifier("retry"))
    assert reserve_outcome(request) == "BUDGET_CALL_CAP_EXCEEDED"
    with transaction() as connection, connection.cursor() as cursor:
        assert provider_project_usage(cursor, scope[0])["calls_used_or_reserved"] == 2


@pytest.mark.parametrize("provider", ["deepseek", "codex-cli"])
def test_generic_call_caps_release_unsent_reservation_allowance(scope, provider):
    from novel_forge.modules.command_kernel.budget_runtime import (
        provider_project_usage,
        resolve_provider_budget_failure,
    )

    request = replace(
        budget_request(scope, provider=provider), call_caps={"project_total": 1}
    )
    first = reserve_provider_budget(DATABASE_URL, request)
    resolve_provider_budget_failure(
        DATABASE_URL, reservation_id=first["reservation_id"], project_id=scope[0]
    )
    with transaction() as connection, connection.cursor() as cursor:
        assert provider_project_usage(cursor, scope[0])["calls_used_or_reserved"] == 0
    assert (
        reserve_outcome(replace(request, stable_idempotency_key=identifier("retry")))
        == "RESERVED"
    )
    with transaction() as connection, connection.cursor() as cursor:
        assert provider_project_usage(cursor, scope[0])["calls_used_or_reserved"] == 1


def test_generic_call_cap_serializes_mixed_currency_operations(scope):
    requests = [
        replace(
            budget_request(scope, provider=provider, new_operation=True),
            call_caps={"project_total": 1},
        )
        for provider in ("deepseek", "codex-cli")
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(reserve_outcome, requests)) == [
            "BUDGET_CALL_CAP_EXCEEDED",
            "RESERVED",
        ]


@pytest.mark.parametrize("kind", ["call", "token", "money"])
def test_global_caps_do_not_exclude_other_projects_same_stable_key(scope, kind):
    from novel_forge.modules.command_kernel.budget_runtime import (
        provider_usage_accounted_sql,
    )

    first = budget_request(scope)
    second_scope = identifier("other-project"), scope[1]
    second = replace(
        budget_request(second_scope, new_operation=True),
        stable_idempotency_key=first.stable_idempotency_key,
    )
    with transaction() as connection, connection.cursor() as cursor:
        if kind == "money":
            cursor.execute(
                "SELECT COALESCE(sum(CASE WHEN status='SETTLED' THEN settled_amount ELSE reserved_amount END),0) FROM authority_budget_reservation WHERE currency='USD' AND status IN ('RESERVED','HELD_UNKNOWN','SETTLED')"
            )
        else:
            aggregate = (
                "count(*)"
                if kind == "call"
                else "COALESCE(sum(CASE WHEN status='SETTLED' THEN actual_tokens ELSE greatest(actual_tokens,estimated_tokens) END),0)"
            )
            cursor.execute(
                f"SELECT {aggregate} FROM authority_budget_reservation WHERE {provider_usage_accounted_sql()}"
            )
        used = cursor.fetchone()[0]
    reserve_provider_budget(DATABASE_URL, first)
    if kind == "money":
        from decimal import Decimal

        second = replace(second, caps={"global_total": str(used + Decimal(".01"))})
        expected = "BUDGET_CAP_EXCEEDED"
    elif kind == "token":
        second = replace(second, token_caps={"global_total": int(used) + 150})
        expected = "BUDGET_TOKEN_CAP_EXCEEDED"
    else:
        second = replace(second, call_caps={"global_total": int(used) + 1})
        expected = "BUDGET_CALL_CAP_EXCEEDED"
    assert reserve_outcome(second) == expected


def feedback_operation(scope, *, status="SUCCEEDED", book_id=""):
    operation, definition = (
        identifier("feedback-operation"),
        identifier("feedback-definition"),
    )
    with transaction() as connection, connection.cursor() as cursor:
        insert_definition(cursor, definition)
        insert_operation(
            cursor,
            operation_id=operation,
            definition_name=definition,
            project_id=scope[0],
            status=status,
            workspace_id=f"workspace:{scope[0]}" if book_id else "legacy-unknown",
            command_payload={"payload": {"book_id": book_id}} if book_id else None,
        )
    return operation


def feedback_effect(scope, payload=None):
    from novel_forge.modules.production_execution.cost_routing import snapshot_hash

    effect = identifier("synthetic-feedback-effect")
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute(
            """INSERT INTO authority_external_effect(external_effect_id,operation_id,project_id,effect_type,
            stable_idempotency_key,status,request_hash,request_payload) VALUES(%s,%s,%s,'model.invoke',%s,'SUCCEEDED',%s,%s)""",
            [
                effect,
                scope[1],
                scope[0],
                effect,
                snapshot_hash(payload or {}),
                Jsonb(payload or {}),
            ],
        )
    return effect


def fixture_planning_feedback(scope, defect="", *, accepted=True):
    # WHY: Synthetic SQL lineage validates projection boundaries; these rows prove no real Provider capability.
    from novel_forge.modules.production_execution.cost_routing import snapshot_hash
    from novel_forge.modules.story_design_authority.qualification import (
        scripted_qualification,
        validate_narrative_qualification,
    )
    from tests.integration.authority_postgres_support import seed_authority_project_book

    project, operation = scope
    book = identifier("feedback-book")
    seed_authority_project_book(project_id=project, book_id=book)
    operation = feedback_operation(scope, status="EXECUTING", book_id=book)
    scope = project, operation
    effect = feedback_effect(scope)
    candidate = write_asset(
        scope,
        "planning_generation_candidate",
        {
            "execution_evidence": {
                "external_receipt_ref": effect,
                "operation_id": operation,
            }
        },
    )
    evaluator_operation = feedback_operation(scope, status="EXECUTING")
    evaluator_scope = project, evaluator_operation
    evaluator_effect = feedback_effect(evaluator_scope)
    attempt = identifier("feedback-attempt")
    generation_operation = (
        feedback_operation(scope) if defect == "generation" else operation
    )
    generator = "chapter_plan.generate"
    evaluation = scripted_qualification(generator)
    if not accepted:
        evaluation["evaluations"][0]["criteria"][0].update(
            verdict="FAIL", repair_directive="Fixture repair required."
        )
    qualified = validate_narrative_qualification(
        generator_operation_name=generator, value=evaluation, require_pass=False
    )
    evidence = {
        "real_model_call": True,
        "fixture_protocol_only": defect == "fixture",
        "result": evaluation,
        "production_execution": {
            "execution_request": {
                "external_effect_id": evaluator_effect,
                "operation_id": evaluator_operation,
                "attempt_id": attempt,
                "project_id": project,
            },
            "route_snapshot": {"route_snapshot_id": "fixture-route"},
            "execution_handle": {"transport": "REMOTE_PROVIDER_API"},
        },
    }
    log = write_asset(
        evaluator_scope,
        "model_call_log",
        {
            "operation_id": evaluator_operation,
            "attempt_id": attempt,
            "stage": "narrative_semantic_evaluation",
            "target_lineage": {
                "target_asset_version_id": candidate.asset_version_id,
                "target_content_hash": candidate.content_hash,
                "generation_operation_id": generation_operation,
                "generator_operation_name": generator,
            },
            "provider_evidence": evidence,
        },
    )
    evaluation_hash = snapshot_hash({"fixture": "evaluation-lineage"})
    evaluated = write_asset(
        evaluator_scope,
        "narrative_design_evaluation",
        {
            "candidate_asset_version_id": candidate.asset_version_id,
            "candidate_content_hash": candidate.content_hash,
            "generation_operation_id": generation_operation,
            "evaluation_operation_id": evaluator_operation,
            "evaluation_attempt_id": attempt,
            "evaluator_execution_class": "MODEL_PROVIDER",
            "evaluation_evidence_hash": evaluation_hash,
            "evaluation": evaluation,
            "qualification": qualified.to_evidence(),
            "provider_execution": {
                "provider_evidence_hash": snapshot_hash(evidence),
                "provider_result_hash": snapshot_hash(evaluation),
                "route_snapshot_id": "fixture-route",
            },
            "provider_evidence_asset_version_ids": [log.asset_version_id],
        },
    )
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO authority_attempt(attempt_id,operation_id,attempt_number,status) VALUES(%s,%s,1,'SUCCEEDED')",
            [attempt, evaluator_operation],
        )
        generation_id, generation_attempt = (
            identifier("generation"),
            identifier("generation-attempt"),
        )
        cursor.execute(
            "INSERT INTO authority_attempt(attempt_id,operation_id,attempt_number,status) VALUES(%s,%s,1,'SUCCEEDED')",
            [generation_attempt, operation],
        )
        cursor.execute(
            """INSERT INTO authority_story_planning_generation(generation_id,operation_id,project_id,workspace_id,
            book_id,generator_operation_name,planning_scope,logical_key,input_snapshot,input_snapshot_hash,status,candidate_asset_version_id)
            VALUES(%s,%s,%s,%s,%s,%s,'CHAPTER',%s,'[]'::jsonb,%s,'CANDIDATE_MATERIALIZED',NULL)""",
            [
                generation_id,
                operation,
                project,
                f"workspace:{project}",
                book,
                generator,
                identifier("logical"),
                snapshot_hash([]),
            ],
        )
        cursor.execute(
            """INSERT INTO authority_story_planning_candidate(candidate_id,generation_id,project_id,book_id,candidate_asset_version_id,content_hash,attempt_id)
                       VALUES(%s,%s,%s,%s,%s,%s,%s)""",
            [
                identifier("candidate"),
                generation_id,
                project,
                book,
                candidate.asset_version_id,
                candidate.content_hash,
                generation_attempt,
            ],
        )
        cursor.execute(
            "UPDATE authority_story_planning_generation SET candidate_asset_version_id=%s,version=version+1 WHERE generation_id=%s",
            [candidate.asset_version_id, generation_id],
        )
        if defect != "incomplete":
            cursor.execute(
                "UPDATE authority_operation SET status='SUCCEEDED',version=version+1 WHERE operation_id=%s",
                [evaluator_operation],
            )
        for index, receipt in enumerate(qualified.receipts):
            if defect == "partial" and index == 0:
                continue
            cursor.execute(
                """INSERT INTO authority_narrative_design_qualification(
                qualification_id,project_id,book_id,asset_version_id,source_operation_id,candidate_content_hash,
                design_layer,profile_id,profile_version,profile_hash,capability_id,skill_ref,evaluator_execution_class,
                qualification_status,evaluation,evaluation_hash,qualification_hash,generation_operation_id,evaluation_operation_id,
                evaluation_attempt_id,evaluation_asset_version_id,evaluation_evidence_hash,trust_boundary,
                provider_model_call_asset_version_id,provider_model_call_content_hash,provider_evidence_hash,provider_result_hash,provider_route_snapshot_id)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'MODEL_PROVIDER',%s,%s,%s,%s,%s,%s,%s,%s,%s,'INDEPENDENT',%s,%s,%s,%s,%s)""",
                [
                    identifier("qualification"),
                    project,
                    book,
                    candidate.asset_version_id,
                    evaluator_operation,
                    candidate.content_hash,
                    receipt.layer.value,
                    receipt.profile_id,
                    receipt.profile_version,
                    receipt.profile_hash,
                    receipt.capability_id,
                    receipt.skill_ref,
                    receipt.status,
                    Jsonb(receipt.evidence),
                    receipt.evaluation_hash,
                    qualified.qualification_hash,
                    generation_operation,
                    evaluator_operation,
                    attempt,
                    evaluated.asset_version_id,
                    evaluation_hash,
                    log.asset_version_id,
                    snapshot_hash({}) if defect == "hash" else log.content_hash,
                    snapshot_hash(evidence),
                    snapshot_hash(evaluation),
                    "fixture-route",
                ],
            )
    return effect


@pytest.mark.parametrize(
    "defect", ["", "generation", "incomplete", "fixture", "hash", "partial"]
)
def test_planning_feedback_requires_complete_independent_fixture_lineage(scope, defect):
    from novel_forge.modules.production_execution.routing_feedback import (
        domain_gate_outcomes,
    )

    if defect == "hash":
        from psycopg.errors import RaiseException

        with pytest.raises(RaiseException, match="exact ModelCallLog"):
            fixture_planning_feedback(scope, defect)
        return
    effect = fixture_planning_feedback(scope, defect)
    with transaction() as connection, connection.cursor() as cursor:
        result = domain_gate_outcomes(cursor, project_id=scope[0], effect_ids=[effect])
    if defect:
        assert result == {}
    else:
        assert result[effect]["accepted"] is True
        assert result[effect]["metric"] == "DOMAIN_GATE_ACCEPTANCE.v1"


def test_planning_feedback_retains_failed_fixture_domain_review(scope):
    from novel_forge.modules.production_execution.routing_feedback import (
        planning_gate_outcomes,
    )

    effect = fixture_planning_feedback(scope, accepted=False)
    with transaction() as connection, connection.cursor() as cursor:
        assert (
            planning_gate_outcomes(cursor, project_id=scope[0], effect_ids=[effect])[
                effect
            ]["accepted"]
            is False
        )


def fixture_source_feedback(scope, *, decision="ACCEPT_IN_SCOPE", defect=""):
    # WHY: Real-shaped flags are synthetic test inputs, never a production benchmark or paid-call proof.
    from novel_forge.modules.production_execution.cost_routing import snapshot_hash
    from tests.integration.authority_postgres_support import seed_authority_project_book

    project, operation = scope
    seed_authority_project_book(
        project_id=project, book_id=identifier("source-feedback-book")
    )
    effect = feedback_effect(scope)
    target = write_asset(
        scope,
        "model_call_log",
        {
            "real_provider_proven": True,
            "production_execution": {
                "execution_request": {
                    "external_effect_id": effect,
                    "project_id": project,
                    "operation_id": operation,
                }
            },
        },
    )
    review_operation = (
        operation if defect == "self" else feedback_operation(scope, status="EXECUTING")
    )
    frozen_target = {
        "execution_asset_version_id": target.asset_version_id,
        "observation": {"findings": []},
    }
    review_effect = feedback_effect(
        (project, review_operation), {"input": {"review_target": frozen_target}}
    )
    review = {"decision": decision, "issues": []}
    write_asset(
        (project, review_operation),
        "model_call_log",
        {
            "real_provider_proven": True,
            "fixture_protocol_only": defect == "fixture",
            "production_execution": {
                "execution_request": {
                    "external_effect_id": review_effect,
                    "project_id": project,
                    "operation_id": review_operation,
                }
            },
            "narrative_review_binding": {
                "target_hash": snapshot_hash({})
                if defect == "target"
                else snapshot_hash(frozen_target),
                "review": review,
            },
        },
    )
    job, work = identifier("feedback-import"), identifier("feedback-work")
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute(
            """INSERT INTO authority_source_import_job(import_job_id,project_id,workspace_id,source_type,source_locator,
            import_policy,import_policy_hash,intelligence_policy_hash,mode,status,discovery_operation_id)
            VALUES(%s,%s,%s,'local_file','{}'::jsonb,'{}'::jsonb,%s,%s,'IMPORT','PROCESSING',%s)""",
            [
                job,
                project,
                f"workspace:{project}",
                snapshot_hash({}),
                snapshot_hash({}),
                operation,
            ],
        )
        cursor.execute(
            """INSERT INTO authority_source_import_work(work_id,import_job_id,project_id,work_kind,stable_key,operation_id,status,result)
            VALUES(%s,%s,%s,'DECONSTRUCTION',%s,%s,'SUCCEEDED',%s)""",
            [
                work,
                job,
                project,
                work,
                review_operation,
                Jsonb(
                    {
                        "phase": "REVIEW",
                        "output_validation": "PASSED",
                        "review": review,
                        "semantic_review_status": decision,
                        "issues": [{"severity": "BLOCKING"}]
                        if defect == "blocking"
                        else [],
                    }
                ),
            ],
        )
    if defect != "incomplete":
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE authority_operation SET status='SUCCEEDED',version=version+1 WHERE operation_id=%s",
                [review_operation],
            )
    return effect, review_effect


@pytest.mark.parametrize(
    "decision,defect,accepted",
    [
        ("ACCEPT_IN_SCOPE", "", True),
        ("REVISE", "", False),
        ("NEEDS_REVIEW", "", None),
        ("ACCEPT_IN_SCOPE", "self", None),
        ("ACCEPT_IN_SCOPE", "fixture", None),
        ("ACCEPT_IN_SCOPE", "target", None),
        ("ACCEPT_IN_SCOPE", "incomplete", None),
        ("ACCEPT_IN_SCOPE", "blocking", None),
    ],
)
def test_source_feedback_projects_target_acceptance_not_reviewer_quality(
    scope, decision, defect, accepted
):
    from novel_forge.modules.production_execution.routing_feedback import (
        domain_gate_outcomes,
    )

    effect, reviewer = fixture_source_feedback(scope, decision=decision, defect=defect)
    with transaction() as connection, connection.cursor() as cursor:
        result = domain_gate_outcomes(
            cursor, project_id=scope[0], effect_ids=[effect, reviewer]
        )
    assert reviewer not in result
    if accepted is None:
        assert result == {}
    else:
        assert result[effect]["accepted"] is accepted
        assert result[effect]["metric"] == "DOMAIN_GATE_ACCEPTANCE.v1"
