from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from novel_forge.modules.authority_handler_runtime.policy_commands import configure_owned_policy
from novel_forge.modules.capability_packs.longform_profiles import LongformCapabilityPackProfile, build_world_sampling_pack_profile
from novel_forge.modules.capability_packs.validation_deployment import install_longform_validation_pack
from novel_forge.modules.command_kernel.creative_budget_runtime import _usage
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_adapters import ProviderResult
from novel_forge.modules.content_authority.scheduler import ContentAuthorityScheduler
from novel_forge.modules.production_execution.routing_catalog import deepseek_candidates
from novel_forge.modules.production_execution.routing_runtime import ProductionProviderRouter
from novel_forge.modules.story_planning_runtime.execution import _PlanningGatewayEffectAdapter
from novel_forge.modules.story_planning_runtime.world_sampling import (
    WorldProviderSampleCommand, actor_sample_outcomes, admit_world_sample, prepare_world_sample,
    query_world_sample, require_world_sample_source, world_sample_definitions,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration import test_core_functional_loops_postgres as core
from tests.integration import test_world_actor_isolation_postgres as actors
from tests.unit.test_creative_budget_contract import provider_campaign_policy


def test_native_actor_sample_independent_feedback_does_not_advance_accepted_state(request, monkeypatch):
    captured = {}
    harness_type, composition_factory = core.CapabilityPackPostgresHarness, core.build_book_production_composition

    def harness(*args, **kwargs):
        value = harness_type(*args, **kwargs)
        captured["harness"] = value
        return value

    def composition(*args, **kwargs):
        value = composition_factory(*args, **kwargs)
        captured["app"] = value.planning
        return value

    monkeypatch.setattr(core, "CapabilityPackPostgresHarness", harness)
    monkeypatch.setattr(core, "build_book_production_composition", composition)
    actors.test_actor_receipt_recovery_continues_through_native_acceptances(request, monkeypatch)
    exercise_actor_sample(captured["app"], captured["harness"])


def exercise_actor_sample(app, harness):
    database_url, project_id = app.database_url, harness.project_id
    stage = "world_candidates.actor_0"
    operator = harness.principal("actor-sample-operator", "story_planning.authority.execute", "provider.routing_policy.configure", "book.authority.execute")
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("""SELECT operation.operation_id,generation.book_id FROM authority_operation operation
            JOIN authority_story_planning_generation generation USING(operation_id)
            WHERE operation.project_id=%s AND operation.status='SUCCEEDED'
              AND operation.command_payload#>>'{payload,generator_operation_name}'='chapter_plan.generate'
            ORDER BY operation.created_at DESC LIMIT 1""", [project_id])
        source_operation_id, book_id = uow.cursor.fetchone()
        for definition in world_sample_definitions(application_build_id=app.application_build_id, commit_sha=app.commit_sha):
            uow.repositories.definitions.register(definition)
        uow.cursor.execute("""SELECT dispatch.evidence FROM authority_external_effect effect
            JOIN authority_external_effect_dispatch dispatch USING(external_effect_id)
            WHERE effect.operation_id=%s AND effect.request_payload->>'stage'=%s AND dispatch.status='SUCCEEDED'""", [source_operation_id, stage])
        original_evidence = uow.cursor.fetchone()[0]
        uow.cursor.execute("SELECT accepted_through_chapter,active_story_state_version_id,active_canon_snapshot_version_id FROM authority_book_production WHERE project_id=%s AND book_id=%s", [project_id, book_id])
        accepted_before = uow.cursor.fetchall()
        uow.cursor.execute("SELECT count(*) FROM authority_asset asset JOIN authority_asset_version version USING(asset_id) WHERE asset.project_id=%s AND asset.asset_type IN ('world_actor_proposal','world_preparation_generation','narrative_governance_action')", [project_id])
        production_before = uow.cursor.fetchone()[0]
        uow.commit()
    profile = build_world_sampling_pack_profile(LongformCapabilityPackProfile(harness.pack_id, "story_planning_generators@1.10.0",
        harness._base_manifest, harness._base_catalog, "long-outline"), application_build_id=app.application_build_id, commit_sha=app.commit_sha)
    install_longform_validation_pack(database_url, profile=profile, pack_version="1.0.0", agent_generation=1,
        expected_activation_version=0, project_id=project_id, workspace_id=harness.workspace_id, book_id=book_id,
        application_build_id=app.application_build_id, commit_sha=app.commit_sha, compiler=harness.compiler,
        approver=harness.approver, agent_admin=harness.agent_admin, agent_domain="story_planning", agent_scope_type="BOOK")
    resolver = app.execution_binder.resolver
    resolver.environment = resolver.runtime_profile = "validation"
    resolver.release_channel = "VALIDATION"
    preparer = resolver.execution_preparer
    preparer.max_cost_per_call = "1"
    preparer.planning_route = replace(preparer.planning_route, model_context_limit=200000)
    candidate = deepseek_candidates(available=True)[0]
    preparer.execution_transport.provider_router = ProductionProviderRouter(database_url,
        candidates=(candidate,), execution_environment="validation", task_money_limit="1", task_token_limit=200000)
    command = WorldProviderSampleCommand(project_id, book_id, operator.principal_id, source_operation_id,
        stage, "fixture-actor-grant", project_id + ":actor-sample")
    prepared = prepare_world_sample(app, command, principal=operator)
    assert prepared["provider_calls"] == 0
    assert prepared["producer_contract"]["output_schema"]["ref"] == "schema:world_candidates.actor_0:v2"
    contract = prepared["generator_evaluation_contract"]
    assert len(contract["dimensions"]) == 4 and contract["independent_humans_required"] == 2
    frozen = require_world_sample_source(database_url, project_id=project_id, book_id=book_id, source_operation_id=source_operation_id, stage=stage)
    assert frozen.stage.task["role"] == "ACTOR" and frozen.stage.task["contract_version"] == "world-actor-task.v2"
    for judge_stage in ("world_candidates.generate", "world_candidates.evaluate"):
        native_judge = require_world_sample_source(database_url, project_id=project_id, book_id=book_id, source_operation_id=source_operation_id, stage=judge_stage)
        assert {row["actor_id"] for row in native_judge.stage.task["actor_proposals"]} == {"mara", "ilya"}
    expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    policy = provider_campaign_policy()
    arm = policy["comparison_budget"]["arms"][0]
    arm.update(project_id=project_id, book_id=book_id)
    with AuthorityUnitOfWork(database_url) as uow:
        usage = _usage(uow.cursor, policy["comparison_budget"], project_id)
    for phase, allocation in policy["authorization"]["authorized_cumulative_caps"].items():
        historical = usage["phases"][phase]
        count = 1 if phase == "CALIBRATION" else 0
        allocation.update(calls=historical["calls_used_or_reserved"] + count,
            tokens=max(historical["conservative_tokens"], historical["calls_used_or_reserved"] * 1000) + 200000 * count,
            priced_usd="10" if historical["calls_used_or_reserved"] or count else "0")
        arm[phase.lower() + "_allocation"] = dict(allocation)
    allocations = policy["authorization"]["authorized_cumulative_caps"].values()
    totals = {**{key: sum(row[key] for row in allocations) for key in ("calls", "tokens")}, "priced_usd": str(sum(int(row["priced_usd"]) for row in allocations))}
    arm["project_total"] = totals
    policy["comparison_budget"].update(experiment_id=project_id, expires_at=expiry, shared_total=totals, entitlements=[])
    policy["authorization"].update(project_id=project_id, book_id=book_id)
    common = dict(database_url=database_url, project_id=project_id, workspace_id=harness.workspace_id,
        trace_id="fixture", correlation_id="fixture", application_build_id=app.application_build_id, commit_sha=app.commit_sha, principal=operator)
    configure_owned_policy(**common, owner="CREATIVE_EXPERIMENT_BUDGET", content=policy, idempotency_key=project_id + ":actor-budget")
    grant = dict(authorization_id=command.authorization_id, reason="synthetic actor sample boundary regression", environment="validation",
        book_id=book_id, task_type=stage, logical_key=source_operation_id, generation_idempotency_key=command.idempotency_key,
        input_versions_hash=prepared["input_versions_hash"], command_hash=prepared["command_hash"], producer_contract_hash=prepared["producer_contract_hash"],
        candidate_id=candidate.candidate_id, model_revision=candidate.model_revision, expires_at=expiry,
        maximum_calls=1, maximum_tokens=200000, maximum_amount="1", currency="USD", purpose="BENCHMARK_CHALLENGER", production_eligible=False,
        campaign=dict(campaign_id=policy["comparison_budget"]["experiment_id"], manifest_hash=policy["comparison_budget"]["manifest_hash"], sample_id="actor-sample", group_id=source_operation_id,
            partition="CALIBRATION", maximum_calls=1, maximum_tokens=200000, maximum_amount="1", expires_at=expiry))
    configure_owned_policy(**common, owner="PROVIDER_ROUTING", content={"policy_version": "actor-fixture-v1", "reason": "fixture-only",
        "task_overrides": [], "bootstrap_authorizations": [grant]}, idempotency_key=project_id + ":actor-router")
    admitted = admit_world_sample(app, command, principal=operator)
    assert admit_world_sample(app, command, principal=operator)["operation_id"] == admitted["operation_id"]
    calls = []

    def invoke(adapter, **kwargs):
        calls.append(kwargs)
        decision = kwargs["request_payload"]["_production_execution"]["capability_runtime"]["routing_decision"]
        assert decision["task"]["producer_contract"] == prepared["producer_contract"]
        assert decision["selected"]["candidate"]["candidate_id"] == candidate.candidate_id
        assert decision["task"]["producer_contract"]["output_schema"]["ref"] == "schema:world_candidates.actor_0:v2"
        evidence = deepcopy(original_evidence)
        # WHY: Native-shaped synthetic receipts exercise feedback joins, not a real Provider claim.
        evidence.update(fixture_protocol_only=False, real_model_call=True, production_verified=False)
        evidence["production_execution"]["execution_request"] = adapter.binding.request.to_dict()
        evidence["provider_id"], evidence["model_id"] = candidate.provider, candidate.model
        evidence["production_execution"]["route_snapshot"]["reasoning_effort"] = candidate.reasoning
        evidence["production_execution"]["process_evidence"].update(served_model_identity_hash="sha256:" + "f" * 64, model_revision=candidate.model_revision)
        return ProviderResult("success", "synthetic-actor:" + kwargs["stable_idempotency_key"], evidence)

    scheduler = ContentAuthorityScheduler(database_url, registry=app.registry, worker_id=app.worker_id)
    with patch.object(_PlanningGatewayEffectAdapter, "execute", invoke):
        scheduler.run_or_recover(operation_id=admitted["operation_id"], project_id=project_id)
        scheduler.run_or_recover(operation_id=admitted["operation_id"], project_id=project_id)
    result = query_world_sample(database_url, project_id=project_id, book_id=book_id, operation_id=admitted["operation_id"])
    assert result["status"] == "SUCCEEDED" and len(calls) == 1
    sample = next(item for item in result["outputs"] if item["asset_type"] == "world_provider_sample")
    assert sample["sample"]["rule_validation"]["status"] == "PASSED" and sample["eligibility"] == "INELIGIBLE"
    effect_ids = [row["external_effect_id"] for row in result["effects"]]
    with AuthorityUnitOfWork(database_url) as uow:
        assert actor_sample_outcomes(uow.cursor, project_id=project_id, effect_ids=effect_ids) == {}
    target = {key: sample[key] for key in ("asset_version_id", "content_hash")}
    with pytest.raises(KernelError, match="WORLD_SAMPLE_SOURCE_DRIFT"):
        prepare_world_sample(app, replace(command, stage="world_candidates.evaluate", generation_sample=target), principal=operator)
    actor_reference(app, harness, frozen=frozen, target=target, contract=contract)
    with AuthorityUnitOfWork(database_url) as uow:
        outcomes = actor_sample_outcomes(uow.cursor, project_id=project_id, effect_ids=effect_ids)
        assert set(outcomes) == set(effect_ids)
        feedback = next(iter(outcomes.values()))
        assert feedback["generator_quality_score"] == .84
        assert feedback["accepted"] is None and feedback["sample_promoted"] is False
        assert feedback["assessment_basis"] == "INDEPENDENT_HUMAN_ADJUDICATION"
        uow.cursor.execute("SELECT accepted_through_chapter,active_story_state_version_id,active_canon_snapshot_version_id FROM authority_book_production WHERE project_id=%s AND book_id=%s", [project_id, book_id])
        accepted_after = uow.cursor.fetchall()
        assert accepted_after == accepted_before
        uow.cursor.execute("SELECT count(*) FROM authority_asset asset JOIN authority_asset_version version USING(asset_id) WHERE asset.project_id=%s AND asset.asset_type IN ('world_actor_proposal','world_preparation_generation','narrative_governance_action')", [project_id])
        assert uow.cursor.fetchone()[0] == production_before
        with pytest.raises(KernelError, match="AUTHORITY_INPUT_NOT_ELIGIBLE"):
            uow.repositories.chapter_authority.frozen_inputs(project_id, [target])
    if path := os.environ.get("NOVEL_FORGE_ACTOR_SAMPLE_EVIDENCE_PATH"):
        from novel_forge.storage.narrative_reality_repositories import NarrativeRealityRepository

        with AuthorityUnitOfWork(database_url) as uow:
            uow.cursor.execute("SELECT book_run_id FROM authority_book_production WHERE project_id=%s AND book_id=%s", [project_id, book_id])
            book_run_id = uow.cursor.fetchone()[0]
            realities = [NarrativeRealityRepository(uow.cursor).require(book_run_id=book_run_id, chapter_number=chapter) for chapter in (1, 2)]
            promises = [next(row for row in reality["current_state"]["narrative_obligation"] if row["state"]["obligation_id"] == "mara:protect-witnesses") for reality in realities]
            uow.cursor.execute("""SELECT e.external_effect_id,e.status,e.request_payload,d.dispatch_id,d.status,r.external_receipt_id
                FROM authority_external_effect e JOIN authority_external_effect_dispatch d USING(external_effect_id)
                LEFT JOIN authority_external_receipt r USING(dispatch_id)
                WHERE e.operation_id=%s ORDER BY e.external_effect_id,d.generation""", [admitted["operation_id"]])
            effects = [{"effect_id": row[0], "status": row[1], "routing_decision": row[2]["_production_execution"]["capability_runtime"]["routing_decision"],
                        "dispatch_id": row[3], "dispatch_status": row[4], "receipt_id": row[5]} for row in uow.cursor.fetchall()]
            uow.cursor.execute("SELECT external_effect_id,status FROM authority_external_effect WHERE project_id=%s AND status NOT IN ('SUCCEEDED','FAILED_FINAL','DEAD_LETTER','CANCELLED')", [project_id])
            unresolved = uow.cursor.fetchall()
        evidence = {"proof_ceiling": "SCRIPTED_PROVIDER_PRODUCTION_WIRING_ONLY", "synthetic_provider_and_human_fixture": True,
            "actual_real_model_calls": 0, "actual_human_evaluations": 0, "project_id": project_id, "book_id": book_id,
            "book_run_id": book_run_id, "source_operation_id": source_operation_id, "sample_operation_id": admitted["operation_id"],
            "formal_acceptances": [{"chapter": chapter, "revision_id": reality["revision_id"], "obligation": promise} for chapter, reality, promise in zip((1, 2), realities, promises, strict=True)],
            "before_frontier_story_state_canon": accepted_before, "after_frontier_story_state_canon": accepted_after,
            "production_asset_count_before_and_after": production_before, "prepared_producer_contract": prepared["producer_contract"],
            "producer_contract_hash": prepared["producer_contract_hash"], "human_protocol": contract,
            "sample": sample, "feedback": feedback, "effects": effects, "provider_dispatches": len(calls),
            "unresolved_effects": unresolved, "ineligible_production_consumer_rejected": True}
        Path(path).write_text(json.dumps(evidence, ensure_ascii=False, indent=2, default=str) + "\n")


def actor_reference(app, harness, *, frozen, target, contract):
    from novel_forge.modules.content_authority import CONTENT_CODECS
    from novel_forge.modules.content_authority.application import ContentAuthorityApplication, ContentOperationRequest

    content_app = ContentAuthorityApplication(app.database_url, application_build_id=app.application_build_id,
        commit_sha=app.commit_sha, integration_proven=CONTENT_CODECS, trusted_only=True)
    chapter = int(frozen.stage.task["accepted_through_chapter"]) + 1
    for dimension in contract["dimensions"]:
        shared = dict(subject_asset_version_id=target["asset_version_id"], dimension=dimension, status="PASSED",
            protocol_version=contract["protocol_version"], evaluation_version=contract["evaluation_version"], scope_type="CHAPTER", chapter_start=chapter, chapter_end=chapter)

        def author(name, suffix, payload, inputs):
            principal = harness.principal(suffix, "content.authority.execute", "content.operation:" + name)
            payload["evaluator_id" if "evaluation_id" in payload else "adjudicator_id"] = principal.principal_id
            response = content_app.execute(ContentOperationRequest(name, harness.project_id, harness.workspace_id,
                principal.principal_id, "synthetic", "synthetic", target["asset_version_id"] + ":" + dimension + ":" + suffix,
                {"evaluation" if "evaluation_id" in payload else "adjudication": payload, "reference_sample": target}, tuple(inputs)), principal=principal)
            return {"asset_version_id": response.asset_version_id, "content_hash": response.content_hash}

        humans = [author("quality.human_evaluation.record", "actor-synthetic-human-" + str(i),
            {**shared, "evaluation_id": target["asset_version_id"] + ":" + dimension + ":" + str(i),
             "evaluator_group": "SYNTHETIC_NATIVE_SHAPE", "evaluator_identity_class": "PROFESSIONAL_EDITOR",
             "score": 85, "confidence": .8, "evidence": [{"note": "Synthetic projection regression; no actual human judgement"}], "blind": True}, [target]) for i in (1, 2)]
        author("quality.adjudication.record", "actor-synthetic-adjudicator",
            {**shared, "adjudication_id": target["asset_version_id"] + ":" + dimension + ":adjudication",
             "adjudicator_identity_class": "PROFESSIONAL_EDITOR", "score_range": [84, 86],
             "source_human_evaluation_asset_version_ids": [row["asset_version_id"] for row in humans],
             "rationale": "Synthetic independent-author protocol fixture; no actual human evaluation occurred."}, [target, *humans])
