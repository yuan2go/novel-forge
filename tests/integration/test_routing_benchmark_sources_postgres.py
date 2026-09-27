from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import json

import pytest

from novel_forge.modules.authority_handler_runtime.policy_commands import configure_owned_policy
from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_runtime import EffectCommandContext, plan_external_effect
from novel_forge.modules.production_execution.cost_routing import CostAwareRouter, RoutingTask
from novel_forge.modules.production_execution.routing_catalog import deepseek_candidates
from novel_forge.modules.production_execution.routing_runtime import PostgresRoutingRegistry
from novel_forge.modules.production_execution.routing_sources import validate_binding
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import (
    DATABASE_URL, ensure_migrated, identifier, insert_definition, insert_operation,
    seed_authority_project_book, transaction,
)
from tests.integration.test_provider_routing_postgres import write_asset


RELEASE_SHA = "e" * 40


def test_native_benchmark_source_requires_explicit_two_project_approval_and_keeps_evidence_in_place(monkeypatch):
    ensure_migrated()
    source, target = identifier("benchmark-source"), identifier("benchmark-target")
    for project in (source, target):
        seed_authority_project_book(project_id=project, book_id="book:" + project)
    principal = Principal("benchmark-export-test-operator", PrincipalType.LOCAL_OPERATOR,
        frozenset({"book.authority.execute"}), frozenset({source, target}), "native-test")
    model = deepseek_candidates(available=True)[0]
    task_type, producer = "book_plan.generate", "sha256:" + "a" * 64
    expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    grant = {"authorization_id": "grant:" + source, "reason": "isolated synthetic evidence protocol test; no Provider",
        "environment": "validation", "book_id": "book:" + source, "task_type": task_type,
        "logical_key": "sample:one", "generation_idempotency_key": source + ":sample",
        "input_versions_hash": "sha256:" + "b" * 64, "command_hash": "sha256:" + "c" * 64,
        "producer_contract_hash": producer, "candidate_id": model.candidate_id, "model_revision": model.model_revision,
        "expires_at": expiry, "maximum_calls": 3, "maximum_tokens": 3000, "maximum_amount": "0.1",
        "currency": "USD", "purpose": "BENCHMARK_CHALLENGER", "production_eligible": False,
        "campaign": {"campaign_id": "campaign:" + source, "manifest_hash": "sha256:" + "d" * 64,
            "sample_id": "sample:one", "group_id": "group:one", "partition": "CALIBRATION",
            "maximum_calls": 3, "maximum_tokens": 3000, "maximum_amount": "0.1", "expires_at": expiry}}
    base = {"policy_version": "source-grants", "reason": "synthetic native source protocol", "task_overrides": [], "bootstrap_authorizations": [grant]}

    def configure(project, policy, *, actor=principal, key=None):
        return configure_owned_policy(database_url=DATABASE_URL, owner="PROVIDER_ROUTING", content=policy,
            project_id=project, workspace_id="workspace:" + project,
            idempotency_key=key or project + ":" + policy["policy_version"], trace_id="test:source-binding",
            correlation_id="test:source-binding", application_build_id="routing-source-test", commit_sha=RELEASE_SHA, principal=actor)

    configure(source, base)
    definition, operation = identifier("source-def"), identifier("source-op")
    with transaction() as connection, connection.cursor() as cursor:
        insert_definition(cursor, definition)
        insert_operation(cursor, operation_id=operation, definition_name=definition, project_id=source, status="EXECUTING")
    scope = (source, operation)
    decision = {"status": "BENCHMARK_SELECTED", "mode": "BENCHMARK_CHALLENGER", "production_eligible": False,
        "task": {"producer_contract_hash": producer, "input_hash": "sha256:" + "f" * 64, "input_tokens": 100},
        "policy": {"risk": "HIGH"}, "selected": {"candidate": asdict(model)},
        "bootstrap_authorization": {"authorization": grant}}

    def observation(fixture, *, effect=None):
        if effect is None:
            effect = plan_external_effect(DATABASE_URL, EffectCommandContext(operation, source, "test", "test", "test"),
                effect_type="model.invoke", provider="production_execution_gateway", capability="model.planning",
                stable_idempotency_key=identifier("source-effect"), request_payload={"stage": task_type,
                    "_production_execution": {"capability_runtime": {"routing_decision": decision}}}, max_attempts=1,
                reversible=False, completion_policy="synchronous_final", model_id=model.model,
                request_timeout_seconds=30, reconciliation_mode="unsupported")["external_effect_id"]
        evidence = {"provider_id": model.provider, "model_id": model.model, "real_model_call": True,
            "fixture_protocol_only": fixture, "usage": {"input_tokens": 100, "output_tokens": 10},
            "production_execution": {"execution_request": {"external_effect_id": effect, "stage": task_type},
                "route_snapshot": {"reasoning_effort": model.reasoning}, "execution_result": {"outcome": "SUCCEEDED"},
                "process_evidence": {"latency_seconds": 1, "served_model_identity_hash": "sha256:" + "9" * 64}}}
        document = write_asset(scope, "model_call_log", {"stage": task_type, "provider_evidence": evidence,
            "test_measurement_class": "SYNTHETIC_LEDGER_PROTOCOL_NOT_REAL_PROVIDER_OR_QUALIFICATION"})
        return document, effect

    first, effect = observation(False)
    duplicate, _ = observation(False, effect=effect)
    fixture, _ = observation(True)
    excluded, _ = observation(False)
    export = {"contract_version": "routing-benchmark-export.v1", "export_id": "export:" + source,
        "source_project_id": source, "target_project_id": target, "target_work_id": "book:" + target,
        "task_type": task_type, **{key: getattr(model, key) for key in ("candidate_id", "provider", "model", "reasoning", "model_revision")},
        "producer_contract_hash": producer, "campaign_id": grant["campaign"]["campaign_id"], "manifest_hash": grant["campaign"]["manifest_hash"],
        "campaign_expires_at": expiry, "expires_at": expiry, "reason": "finite isolated protocol test",
        "observations": [{"asset_version_id": item.asset_version_id, "content_hash": item.content_hash} for item in (first, duplicate, fixture)]}
    export_policy = {**base, "policy_version": "source-export", "benchmark_exports": [export]}
    with pytest.raises(PermissionError):
        configure(source, export_policy, actor=replace(principal, project_scope=frozenset({source})))
    approved = configure(source, export_policy)
    binding = {"export": export, "source_policy": {"policy_version": export_policy["policy_version"],
        "content_hash": approved["policy_hash"], "operation_id": approved["operation_id"]}}
    target_policy = {"policy_version": "target-binding", "reason": "consume exact approved source", "task_overrides": [], "benchmark_source_bindings": [binding]}
    with pytest.raises(PermissionError):
        configure(target, target_policy, actor=replace(principal, project_scope=frozenset({target})))
    registry = PostgresRoutingRegistry(DATABASE_URL)
    args = dict(project_id=target, work_id="book:" + target, task_type=task_type, candidate=model, producer_contract_hash=producer)
    assert registry.observations(**args) == []
    bound = configure(target, target_policy)
    replay = configure(target, target_policy)
    assert replay["replayed"] and replay["operation_id"] == bound["operation_id"]
    observed_projects = []

    def outcomes(cursor, *, project_id, effect_ids):
        observed_projects.append(project_id)
        return {}

    registry = PostgresRoutingRegistry(DATABASE_URL, outcome_projection=outcomes)
    observations = registry.observations(**args)
    assert len(observations) == 1 and observations[0].evidence_ref in {"asset-version:" + first.asset_version_id, "asset-version:" + duplicate.asset_version_id}
    assert "asset-version:" + excluded.asset_version_id not in {item.evidence_ref for item in observations}
    assert observed_projects == [source]
    assert observations[0].generator_quality_score is None and observations[0].production_eligible is False
    task = RoutingTask(task_type, target, "book:" + target, operation, "attempt", 100, 100, 1000, "1")
    assert CostAwareRouter().explain(task, [model], {model.candidate_id: observations}).to_dict()["status"] == "BLOCKED"
    for field, value in (("work_id", "different"), ("task_type", "chapter_plan.generate"), ("producer_contract_hash", "sha256:" + "8" * 64)):
        assert registry.observations(**{**args, field: value}) == []
    assert registry.observations(**{**args, "candidate": replace(model, model_revision="different")}) == []
    bad = deepcopy(target_policy)
    bad["policy_version"] = "bad-source-hash"
    bad["benchmark_source_bindings"][0]["source_policy"]["content_hash"] = "0" * 64
    with pytest.raises(KernelError, match="ROUTING_BENCHMARK_SOURCE_INVALID"):
        configure(target, bad)
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        with pytest.raises(KernelError, match="expired"):
            validate_binding(uow.cursor, binding, now=datetime.now(timezone.utc) + timedelta(hours=2))
    configure(source, {**base, "policy_version": "source-revoked", "benchmark_exports": []})
    with pytest.raises(KernelError, match="revoked"):
        registry.observations(**args)
    assert configure(target, target_policy)["replayed"] is True
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM authority_asset a JOIN authority_asset_version v USING(asset_id) WHERE a.project_id=%s AND a.asset_type='model_call_log'", [target])
        assert cursor.fetchone()[0] == 0
    print("ROUTING_SOURCE_EVIDENCE=" + json.dumps({
        "evidence_class": "SCRIPTED_NATIVE_POSTGRESQL_SELECTED_COHORT_PROTOCOL",
        "actual_real_model_calls": 0, "actual_human_reviews": 0, "qualification_status": "BLOCKED",
        "synthetic_model_log_fields_are_not_actual_provider_evidence": True,
        "source_project_id": source, "target_project_id": target,
        "source_approval": binding["source_policy"], "target_policy_operation_id": bound["operation_id"],
        "source_asset_refs": export["observations"], "excluded_asset_version_id": excluded.asset_version_id,
        "imported_observation_refs": [item.evidence_ref for item in observations],
        "metric_sample_count": 0, "duplicate_effects_counted_once": True,
        "fixture_excluded": True, "expired_and_revoked_sources_rejected": True,
        "permission_and_scope_checks": "PASS", "source_assets_copied": False,
        "cohort_scope": "EXACT_OPERATOR_APPROVED_FINITE_SUBSET; NOT_COMPLETE_CAMPAIGN_OR_RANDOM_SAMPLE_PROOF",
        "release_sha": RELEASE_SHA,
    }, ensure_ascii=False, sort_keys=True))
