from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone

import pytest
from psycopg.types.json import Jsonb

from novel_forge.modules.production_execution.cost_routing import TaskPolicy, benchmark_snapshot
from novel_forge.modules.production_execution.routing_catalog import deepseek_candidates
from novel_forge.modules.production_execution.routing_runtime import PostgresRoutingRegistry
from tests.integration import test_provider_routing_postgres as support

scope = support.scope


@pytest.mark.parametrize("history", ["provider_failure", "receipt_replay", "predispatch_failure"])
def test_same_effect_provider_retry_retains_failure_without_penalizing_receipt_replay(scope, history):
    # WHY: Native-shaped synthetic evidence exercises SQL attribution, never real-model qualification.
    candidate = deepseek_candidates(available=True)[0]
    decision = {"status": "BENCHMARK_SELECTED", "mode": "BENCHMARK_CHALLENGER", "production_eligible": False,
        "selected": {"candidate": asdict(candidate)}, "policy": {"risk": "HIGH"},
        "task": {"chain_id": "chain", "input_hash": "sha256:" + "1" * 64, "input_tokens": 100,
                 "producer_contract_hash": "sha256:" + "a" * 64},
        "bootstrap_authorization": {"authorization": {"purpose": "BENCHMARK_CHALLENGER", "campaign": {
            "campaign_id": "fixture", "manifest_hash": "sha256:" + "d" * 64, "group_id": "input", "partition": "CALIBRATION"}}}}
    request = support.budget_request(scope, decision=decision)
    success = {"provider_id": candidate.provider, "model_id": candidate.model, "real_model_call": True,
        "usage": {"input_tokens": 100, "output_tokens": 50},
        "production_execution": {"execution_request": {"external_effect_id": request.external_effect_id, "stage": "draft"},
            "route_snapshot": {"reasoning_effort": candidate.reasoning}, "execution_result": {"outcome": "SUCCEEDED"},
            "process_evidence": {"served_model_identity_hash": "sha256:fixture-retry-cohort"}}}
    first = deepcopy(success)
    if history != "receipt_replay":
        first["production_execution"]["execution_result"]["outcome"] = "RETRYABLE_FAILURE"
        first["real_model_call"] = history == "provider_failure"
    support.write_asset(scope, "model_call_log", {"stage": "draft", "provider_evidence": first})
    if history == "receipt_replay":
        success["provider_invoked_this_attempt"] = False
        success["recovered_external_effect_success"] = True
    support.write_asset(scope, "model_call_log", {"stage": "draft", "provider_evidence": success})
    with support.transaction() as connection, connection.cursor() as cursor:
        dispatches = [(1, "SUCCEEDED", success)] if history == "receipt_replay" else [(1, "FAILED_RETRYABLE", first), (2, "SUCCEEDED", success)]
        for generation, status, evidence in dispatches:
            cursor.execute("""INSERT INTO authority_external_effect_dispatch(dispatch_id,external_effect_id,generation,status,payload_hash,evidence)
                VALUES(%s,%s,%s,%s,'fixture',%s)""", [support.identifier("dispatch"), request.external_effect_id, generation, status, Jsonb(evidence)])
        cursor.execute("UPDATE authority_external_effect SET status='SUCCEEDED' WHERE external_effect_id=%s", [request.external_effect_id])
    feedback = {request.external_effect_id: {"generator_quality_score": .99, "generator_protocol_hash": "sha256:" + "b" * 64,
        "generator_risk": "HIGH", "generator_context_tokens": 100, "evidence_refs": ["synthetic-adjudication"]}}
    registry = PostgresRoutingRegistry(support.DATABASE_URL, outcome_projection=lambda *args, **kwargs: feedback)
    rows = registry.observations(project_id=scope[0], task_type="draft", candidate=candidate)
    assert len(rows) == 1
    assert rows[0].generator_quality_score == .99
    assert rows[0].retried is (history == "provider_failure")
    assert rows[0].schema_success is (history != "provider_failure")
    snapshot = benchmark_snapshot(rows, now=datetime.now(timezone.utc), input_tokens=100,
        policy=TaskPolicy("HIGH", .8, 1, 0, quality_metric="GENERATOR_SCORE"))
    assert snapshot["quality_sample_count"] == (0 if history == "provider_failure" else 1)
    assert snapshot["schema_success"] == (0 if history == "provider_failure" else 1)


def _experiment_observation(scope, *, input_hash, producer_hash="sha256:" + "a" * 64,
                            source_kind="experiment", failed=False, served="sha256:fixture-retry-cohort", partition="CALIBRATION"):
    candidate = deepseek_candidates(available=True)[0]
    decision = {"status": "BENCHMARK_SELECTED", "mode": "BENCHMARK_CHALLENGER", "production_eligible": False,
        "selected": {"candidate": asdict(candidate)}, "policy": {"risk": "HIGH"},
        "task": {"chain_id": support.identifier("independent-operation-chain"), "input_hash": input_hash, "input_tokens": 100,
                 "producer_contract_hash": producer_hash},
        "bootstrap_authorization": {"authorization": {"purpose": "BENCHMARK_CHALLENGER", "campaign": {
            "campaign_id": "fixture", "manifest_hash": "sha256:" + "d" * 64, "sample_id": support.identifier("sample"),
            "group_id": "same-native-input", "partition": partition}}}}
    if source_kind == "production":
        decision.update(status="SELECTED", production_eligible=True)
        decision.pop("mode")
        decision.pop("bootstrap_authorization")
    request = support.budget_request(scope, decision=decision)
    evidence = {"provider_id": candidate.provider, "model_id": candidate.model, "real_model_call": True,
        "usage": {"input_tokens": 100, "output_tokens": 50, "prompt_cache_hit_tokens": 80},
        "production_execution": {"execution_request": {"external_effect_id": request.external_effect_id, "stage": "draft"},
            "route_snapshot": {"reasoning_effort": candidate.reasoning},
            "execution_result": {"outcome": "FINAL_FAILURE" if failed else "SUCCEEDED"},
            "process_evidence": {"served_model_identity_hash": served}}}
    record = support.write_asset(scope, "model_call_log", {"stage": "draft", "provider_evidence": evidence})
    with support.transaction() as connection, connection.cursor() as cursor:
        cursor.execute("""INSERT INTO authority_external_effect_dispatch(dispatch_id,external_effect_id,generation,status,payload_hash,evidence)
            VALUES(%s,%s,1,%s,'fixture',%s)""", [support.identifier("dispatch"), request.external_effect_id, "FAILED_FINAL" if failed else "SUCCEEDED", Jsonb(evidence)])
        cursor.execute("UPDATE authority_external_effect SET status=%s WHERE external_effect_id=%s", ["FAILED_FINAL" if failed else "SUCCEEDED", request.external_effect_id])
    return request.external_effect_id, "asset-version:" + record.asset_version_id


def test_input_retry_before_raw_log_limit_still_cannot_become_a_first_quality_sample(scope):
    original, original_ref = _experiment_observation(scope, input_hash="sha256:" + "1" * 64, failed=True)
    for index in range(199):
        _experiment_observation(scope, input_hash="sha256:" + format(index + 2, "064x"))
    replay, replay_ref = _experiment_observation(scope, input_hash="sha256:" + "1" * 64)
    feedback = {replay: {"generator_quality_score": .99, "generator_protocol_hash": "sha256:" + "b" * 64,
        "generator_risk": "HIGH", "generator_context_tokens": 100, "evidence_refs": ["synthetic-adjudication"]}}
    registry = PostgresRoutingRegistry(support.DATABASE_URL, outcome_projection=lambda *args, **kwargs: feedback)
    rows = registry.observations(project_id=scope[0], task_type="draft", candidate=deepseek_candidates(available=True)[0])
    assert len(rows) == 200
    assert original_ref not in {row.evidence_ref for row in rows}
    latest = next(row for row in rows if row.evidence_ref == replay_ref)
    assert latest.retried is True and latest.schema_success is True
    assert latest.generator_quality_score == .99
    assert latest.input_tokens == 100 and latest.cache_hit_tokens == 80
    snapshot = benchmark_snapshot(rows, now=datetime.now(timezone.utc), input_tokens=100,
        policy=TaskPolicy("HIGH", .8, 1, 0, quality_metric="GENERATOR_SCORE"))
    assert snapshot["quality_sample_count"] == 0
    assert snapshot["input_tokens"] == 20000 and snapshot["cache_hit_ratio"] == .8
    assert snapshot["uncertain"] is True
    with support.transaction() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT status FROM authority_external_effect WHERE external_effect_id=%s", [original])
        assert cursor.fetchone()[0] == "FAILED_FINAL"


@pytest.mark.parametrize("excluded_prior", ["production", "other_producer", "other_served_model", "old_dispatch", "old_holdout", "old_development"])
def test_input_repeat_guard_excludes_formal_source_and_incompatible_history(scope, excluded_prior):
    prior, prior_ref = _experiment_observation(scope, input_hash="sha256:" + "1" * 64, failed=True,
        producer_hash="sha256:" + ("c" if excluded_prior == "other_producer" else "a") * 64,
        served="sha256:other-served-model" if excluded_prior == "other_served_model" else "sha256:fixture-retry-cohort",
        source_kind="production" if excluded_prior == "production" else "experiment",
        partition="HOLDOUT" if excluded_prior == "old_holdout" else "DEVELOPMENT" if excluded_prior == "old_development" else "CALIBRATION")
    if excluded_prior.startswith("old_"):
        with support.transaction() as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE authority_external_effect_dispatch SET created_at=NOW()-INTERVAL '31 days' WHERE external_effect_id=%s", [prior])
            cursor.execute("UPDATE authority_asset_version SET created_at=NOW()-INTERVAL '31 days' WHERE asset_version_id=%s", [prior_ref.removeprefix("asset-version:")])
    _, latest_ref = _experiment_observation(scope, input_hash="sha256:" + "1" * 64)
    rows = PostgresRoutingRegistry(support.DATABASE_URL).observations(project_id=scope[0], task_type="draft", candidate=deepseek_candidates(available=True)[0])
    latest = next(row for row in rows if row.evidence_ref == latest_ref)
    assert latest.retried is (excluded_prior in {"old_holdout", "old_development"})
    assert latest.schema_success is True
    if excluded_prior.startswith("old_"):
        assert len(rows) == 1
