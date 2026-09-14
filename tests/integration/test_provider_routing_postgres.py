from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
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
                    "external_effect_id": f"test-effect:{i}",
                    "stage": "draft",
                },
                "route_snapshot": {"reasoning_effort": candidate.reasoning},
                "execution_result": {"outcome": "SUCCEEDED"},
                "process_evidence": {"latency_seconds": 2},
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
