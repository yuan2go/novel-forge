from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from novel_forge.modules.authority_handler_runtime.policy_commands import configure_owned_policy
from novel_forge.modules.capability_packs.longform_profiles import LongformCapabilityPackProfile, build_world_sampling_pack_profile
from novel_forge.modules.capability_packs.validation_deployment import install_longform_validation_pack
from novel_forge.modules.command_kernel.external_effect_adapters import ProviderResult
from novel_forge.modules.command_kernel.creative_budget_runtime import _usage
from novel_forge.modules.content_authority.scheduler import ContentAuthorityScheduler
from novel_forge.modules.production_execution.routing_catalog import deepseek_candidates
from novel_forge.modules.production_execution.routing_runtime import ProductionProviderRouter, PostgresRoutingRegistry
from novel_forge.modules.story_planning_runtime.execution import _PlanningGatewayEffectAdapter
from novel_forge.modules.story_planning_runtime.world_sampling import (
    WorldProviderSampleCommand, admit_world_sample, prepare_world_sample, query_world_sample, world_sample_definitions, require_world_sample_source,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.unit.test_creative_budget_contract import provider_campaign_policy


def exercise_world_generator_sample(app, harness, *, book_id, source_operation_id):
    database_url = app.database_url
    project_id = harness.project_id
    operator = harness.principal("world-sample-operator", "story_planning.authority.execute", "provider.routing_policy.configure", "book.authority.execute")
    with AuthorityUnitOfWork(database_url) as uow:
        for reference_samples in (False, True):
            for definition in world_sample_definitions(application_build_id=app.application_build_id, commit_sha=app.commit_sha,
                                                       reference_samples=reference_samples):
                uow.repositories.definitions.register(definition)
        uow.cursor.execute("""SELECT dispatch.evidence FROM authority_external_effect effect
            JOIN authority_external_effect_dispatch dispatch USING(external_effect_id)
            WHERE effect.operation_id=%s AND effect.request_payload->>'stage'='world_candidates.generate' AND dispatch.status='SUCCEEDED'""", [source_operation_id])
        original_evidence = uow.cursor.fetchone()[0]
        uow.commit()
    profile = build_world_sampling_pack_profile(LongformCapabilityPackProfile(harness.pack_id, "story_planning_generators@1.10.0",
        harness._base_manifest, harness._base_catalog, "long-outline"), application_build_id=app.application_build_id, commit_sha=app.commit_sha)
    install_longform_validation_pack(database_url, profile=profile, pack_version="1.0.0", agent_generation=1,
        expected_activation_version=0, project_id=project_id, workspace_id=harness.workspace_id, book_id=book_id,
        application_build_id=app.application_build_id, commit_sha=app.commit_sha, compiler=harness.compiler,
        approver=harness.approver, agent_admin=harness.agent_admin, agent_domain="story_planning", agent_scope_type="BOOK")
    reference_profile = build_world_sampling_pack_profile(LongformCapabilityPackProfile(harness.pack_id, "story_planning_generators@1.10.0",
        harness._base_manifest, harness._base_catalog, "long-outline"), application_build_id=app.application_build_id,
        commit_sha=app.commit_sha, reference_samples=True)
    install_longform_validation_pack(database_url, profile=reference_profile, pack_version="1.0.0", agent_generation=1,
        expected_activation_version=0, project_id=project_id, workspace_id=harness.workspace_id, book_id=book_id,
        application_build_id=app.application_build_id, commit_sha=app.commit_sha, compiler=harness.compiler,
        approver=harness.approver, agent_admin=harness.agent_admin, agent_domain="story_planning", agent_scope_type="BOOK")
    resolver = app.execution_binder.resolver
    resolver.environment = resolver.runtime_profile = "validation"
    resolver.release_channel = "VALIDATION"
    preparer = resolver.execution_preparer
    preparer.max_cost_per_call = "1"
    preparer.planning_route = replace(preparer.planning_route, model_context_limit=200000)
    preparer.execution_transport.provider_router = ProductionProviderRouter(database_url,
        candidates=deepseek_candidates(available=True), execution_environment="validation", task_money_limit="1", task_token_limit=200000)
    command = WorldProviderSampleCommand(project_id, book_id, operator.principal_id, source_operation_id,
        "world_candidates.generate", "fixture-world-grant", project_id + ":world-sample")
    prepared = prepare_world_sample(app, command, principal=operator)
    expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    policy = provider_campaign_policy()
    arm = policy["comparison_budget"]["arms"][0]
    arm.update(project_id=project_id, book_id=book_id)
    with AuthorityUnitOfWork(database_url) as uow:
        usage = _usage(uow.cursor, policy["comparison_budget"], project_id)
    for phase, allocation in policy["authorization"]["authorized_cumulative_caps"].items():
        historical = usage["phases"][phase]
        new_calls = {"CALIBRATION": 1, "REFERENCE": 2}.get(phase, 0)
        allocation.update(calls=historical["calls_used_or_reserved"] + new_calls,
            tokens=max(historical["conservative_tokens"], historical["calls_used_or_reserved"] * 1000) + 200000 * new_calls,
            priced_usd="10" if historical["calls_used_or_reserved"] or phase in {"CALIBRATION", "REFERENCE"} else "0")
        arm[phase.lower() + "_allocation"] = dict(allocation)
    allocations = policy["authorization"]["authorized_cumulative_caps"].values()
    totals = {**{key: sum(row[key] for row in allocations) for key in ("calls", "tokens")},
              "priced_usd": str(sum(int(row["priced_usd"]) for row in allocations))}
    arm["project_total"] = totals
    policy["comparison_budget"].update(experiment_id=project_id, expires_at=expiry, shared_total=totals, entitlements=[])
    policy["authorization"].update(project_id=project_id, book_id=book_id)
    common = dict(database_url=database_url, project_id=project_id, workspace_id=harness.workspace_id,
        trace_id="fixture", correlation_id="fixture", application_build_id=app.application_build_id,
        commit_sha=app.commit_sha, principal=operator)
    configure_owned_policy(**common, owner="CREATIVE_EXPERIMENT_BUDGET", content=policy, idempotency_key=project_id + ":world-budget")
    candidate = deepseek_candidates(available=True)[0]
    grant = dict(authorization_id=command.authorization_id, reason="scripted World boundary regression", environment="validation",
        book_id=book_id, task_type=command.stage, logical_key=source_operation_id, generation_idempotency_key=command.idempotency_key,
        input_versions_hash=prepared["input_versions_hash"], command_hash=prepared["command_hash"], producer_contract_hash=prepared["producer_contract_hash"],
        candidate_id=candidate.candidate_id, model_revision=candidate.model_revision, expires_at=expiry,
        maximum_calls=1, maximum_tokens=200000, maximum_amount="1", currency="USD", purpose="BENCHMARK_CHALLENGER", production_eligible=False,
        campaign=dict(campaign_id=project_id, manifest_hash="sha256:" + "c" * 64, sample_id="world-generator", group_id=source_operation_id,
            partition="CALIBRATION", maximum_calls=3, maximum_tokens=600000, maximum_amount="3", expires_at=expiry))
    configure_owned_policy(**common, owner="PROVIDER_ROUTING", content={"policy_version": "world-fixture-v1", "reason": "fixture-only",
        "task_overrides": [], "bootstrap_authorizations": [grant]}, idempotency_key=project_id + ":world-router")
    admitted = admit_world_sample(app, command, principal=operator)
    assert admit_world_sample(app, command, principal=operator)["operation_id"] == admitted["operation_id"]
    calls = []

    def invoke(adapter, **kwargs):
        calls.append(kwargs)
        assert kwargs["request_payload"]["_production_execution"]["capability_runtime"]["routing_decision"]["task"]["producer_contract"] == prepared["producer_contract"]
        evidence = deepcopy(original_evidence)
        evidence.update(fixture_protocol_only=True, real_model_call=False, production_verified=False)
        evidence["production_execution"]["execution_request"] = adapter.binding.request.to_dict()
        return ProviderResult("success", "fixture-world-sample:" + kwargs["stable_idempotency_key"], evidence)

    scheduler = ContentAuthorityScheduler(database_url, registry=app.registry, worker_id=app.worker_id)
    with patch.object(_PlanningGatewayEffectAdapter, "execute", invoke):
        scheduler.run_or_recover(operation_id=admitted["operation_id"], project_id=project_id)
        scheduler.run_or_recover(operation_id=admitted["operation_id"], project_id=project_id)
    result = query_world_sample(database_url, project_id=project_id, book_id=book_id, operation_id=admitted["operation_id"])
    assert result["status"] == "SUCCEEDED" and len(calls) == 1
    samples = [item for item in result["outputs"] if item["asset_type"] == "world_provider_sample"]
    assert len(samples) == 1 and samples[0]["eligibility"] == "INELIGIBLE"
    assert samples[0]["sample"]["rule_validation"]["status"] == "PASSED"
    assert samples[0]["sample"]["execution_evidence"]["real_model_call"] is False
    assert not {item["asset_type"] for item in result["outputs"]}.intersection({"planning_generation_candidate", "narrative_governance_action", "world_preparation_generation"})
    campaign = PostgresRoutingRegistry(database_url).campaign(project_id=project_id, campaign_id=project_id)
    assert campaign["usage"]["calls_used_or_reserved"] == 1
    frozen = require_world_sample_source(database_url, project_id=project_id, book_id=book_id,
        source_operation_id=source_operation_id, stage="world_candidates.evaluate")
    from novel_forge.modules.story_planning_runtime.application import _command_from_payload
    from novel_forge.modules.story_planning_runtime.execution import PostgresPlanningExecutionPreparer
    generator_context = require_world_sample_source(database_url, project_id=project_id, book_id=book_id,
        source_operation_id=source_operation_id, stage="world_candidates.generate").context
    derived = PostgresPlanningExecutionPreparer._world_context_content(command=_command_from_payload(frozen.command_payload),
        base=generator_context, stage=frozen.stage, source=frozen.source)
    assert derived == frozen.context.content
    sample_target = {key: samples[0][key] for key in ("asset_version_id", "content_hash")}
    sample_reference = fixture_world_reference(app, harness, frozen, sample_target=sample_target)
    assert sample_reference["adjudications"]
    from novel_forge.modules.chapter_quality_authority.reference_subject import require_reference_subject
    from novel_forge.modules.command_kernel.errors import KernelError
    import pytest
    with AuthorityUnitOfWork(database_url) as uow:
        with pytest.raises(KernelError, match="QUALITY_REFERENCE_TARGET_INVALID"):
            require_reference_subject(uow.cursor, project_id=project_id, binding=sample_target)
        subject = require_reference_subject(uow.cursor, project_id=project_id, binding=sample_target,
            allowed_types=frozenset({"world_provider_sample"}))
        assert subject["generation_operation_id"] == admitted["operation_id"]
    reference = fixture_world_reference(app, harness, frozen)
    command = replace(command, stage="world_candidates.evaluate", authorization_id="fixture-world-reviewer",
                      idempotency_key=project_id + ":world-evaluator", reference_evaluation=reference)
    prepared = prepare_world_sample(app, command, principal=operator)
    review_grant = {**grant, "authorization_id": command.authorization_id, "task_type": command.stage,
        "generation_idempotency_key": command.idempotency_key, "input_versions_hash": prepared["input_versions_hash"],
        "command_hash": prepared["command_hash"], "producer_contract_hash": prepared["producer_contract_hash"],
        "purpose": "REFERENCE_EVALUATION", "reference_evaluation": reference,
        "campaign": {**grant["campaign"], "sample_id": "world-evaluator"}}
    configure_owned_policy(**common, owner="PROVIDER_ROUTING", content={"policy_version": "world-fixture-v2", "reason": "fixture-only",
        "task_overrides": [], "bootstrap_authorizations": [grant, review_grant]}, idempotency_key=project_id + ":world-router-v2")
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("""SELECT dispatch.evidence FROM authority_external_effect effect
            JOIN authority_external_effect_dispatch dispatch USING(external_effect_id)
            WHERE effect.operation_id=%s AND effect.request_payload->>'stage'='world_candidates.evaluate' AND dispatch.status='SUCCEEDED'""", [source_operation_id])
        original_evidence = uow.cursor.fetchone()[0]
    admitted = admit_world_sample(app, command, principal=operator)
    with patch.object(_PlanningGatewayEffectAdapter, "execute", invoke):
        scheduler.run_or_recover(operation_id=admitted["operation_id"], project_id=project_id)
        scheduler.run_or_recover(operation_id=admitted["operation_id"], project_id=project_id)
    result = query_world_sample(database_url, project_id=project_id, book_id=book_id, operation_id=admitted["operation_id"])
    assert result["status"] == "SUCCEEDED" and len(calls) == 2
    sample = next(item["sample"] for item in result["outputs"] if item["asset_type"] == "world_provider_sample")
    assert sample["reference_evaluation"]["score_range_agreement"] < 1
    assert sample["reference_evaluation"]["calibration_claim_allowed"] is False
    assert all("fixture-world-blind" not in str(call["request_payload"]["input"]) for call in calls)
    assert PostgresRoutingRegistry(database_url).campaign(project_id=project_id, campaign_id=project_id)["usage"]["calls_used_or_reserved"] == 2
    command = replace(command, generation_sample=sample_target, reference_evaluation=sample_reference,
        authorization_id="fixture-world-coldstart", idempotency_key=project_id + ":world-coldstart")
    from novel_forge.storage.authority_asset_store import AuthorityAssetQuery

    native_require = AuthorityAssetQuery.require

    def require_without_formal_generation(query, **kwargs):
        assert kwargs.get("logical_ref") not in {
            f"world_preparation/{source_operation_id}/generation",
            f"world_preparation/context/{source_operation_id}/world_candidates.evaluate"}
        return native_require(query, **kwargs)

    with patch.object(AuthorityAssetQuery, "require", require_without_formal_generation):
        prepared = prepare_world_sample(app, command, principal=operator)
        assert prepared["definition_version"] == "1.1.0"
        with pytest.raises(KernelError, match="QUALITY_REFERENCE_NOT_INDEPENDENT"):
            prepare_world_sample(app, replace(command, reference_evaluation=reference), principal=operator)
        label_author = harness.principal("world-fixture-human-1", "story_planning.authority.execute")
        with pytest.raises(KernelError, match="QUALITY_REFERENCE_NOT_INDEPENDENT"):
            prepare_world_sample(app, replace(command, actor_id=label_author.principal_id), principal=label_author)
        cold_grant = {**review_grant, "authorization_id": command.authorization_id,
            "generation_idempotency_key": command.idempotency_key, "input_versions_hash": prepared["input_versions_hash"],
            "command_hash": prepared["command_hash"], "producer_contract_hash": prepared["producer_contract_hash"],
            "reference_evaluation": sample_reference, "campaign": {**grant["campaign"], "sample_id": "world-coldstart"}}
        configure_owned_policy(**common, owner="PROVIDER_ROUTING", content={"policy_version": "world-fixture-v3", "reason": "fixture-only",
            "task_overrides": [], "bootstrap_authorizations": [grant, review_grant, cold_grant]}, idempotency_key=project_id + ":world-router-v3")
        admitted = admit_world_sample(app, command, principal=operator)
        with patch.object(_PlanningGatewayEffectAdapter, "execute", invoke):
            scheduler.run_or_recover(operation_id=admitted["operation_id"], project_id=project_id)
            scheduler.run_or_recover(operation_id=admitted["operation_id"], project_id=project_id)
    result = query_world_sample(database_url, project_id=project_id, book_id=book_id, operation_id=admitted["operation_id"])
    assert result["status"] == "SUCCEEDED" and len(calls) == 3
    sample = next(item["sample"] for item in result["outputs"] if item["asset_type"] == "world_provider_sample")
    assert sample["generation_sample"] == sample_target
    assert sample["reference_evaluation"]["score_range_agreement"] < 1
    assert sample["production_eligible"] is False
    assert all(item["eligibility"] == "INELIGIBLE" for item in result["outputs"] if item["asset_type"] in {"world_provider_sample", "context_bundle"})
    assert PostgresRoutingRegistry(database_url).campaign(project_id=project_id, campaign_id=project_id)["usage"]["calls_used_or_reserved"] == 3
    with AuthorityUnitOfWork(database_url) as uow:
        with pytest.raises(KernelError, match="AUTHORITY_INPUT_NOT_ELIGIBLE"):
            uow.repositories.chapter_authority.frozen_inputs(project_id, [sample_target])
    with pytest.raises(KernelError, match="QUALITY_REFERENCE_TARGET_INVALID"):
        prepare_world_sample(app, replace(command, generation_sample={**sample_target, "content_hash": "sha256:" + "0" * 64}), principal=operator)


def fixture_world_reference(app, harness, frozen, *, sample_target=None):
    from novel_forge.modules.content_authority import CONTENT_CODECS
    from novel_forge.modules.content_authority.application import ContentAuthorityApplication, ContentOperationRequest
    from novel_forge.modules.hierarchical_planning.causal_domain import DIRECTOR_DIMENSIONS

    content_app = ContentAuthorityApplication(app.database_url, application_build_id=app.application_build_id,
        commit_sha=app.commit_sha, integration_proven=CONTENT_CODECS, trusted_only=True)
    target = sample_target or frozen.stage.task["generation_ref"]
    chapter = int(frozen.command_payload["world_preparation_request"]["accepted_through_chapter"]) + 1
    adjudications = []
    for candidate in frozen.stage.task["generated_portfolio"]["candidates"]:
        for key in DIRECTOR_DIMENSIONS:
            dimension = candidate["transition"]["transition_id"] + ":" + key
            shared = dict(subject_asset_version_id=target["asset_version_id"], dimension=dimension, status="FAILED",
                protocol_version="fixture-world-blind", evaluation_version="fixture-world-labels", scope_type="CHAPTER",
                chapter_start=chapter, chapter_end=chapter)

            def author(name, actor_suffix, payload, inputs):
                principal = harness.principal(actor_suffix, "content.authority.execute", "content.operation:" + name)
                payload["evaluator_id" if "evaluation_id" in payload else "adjudicator_id"] = principal.principal_id
                result = content_app.execute(ContentOperationRequest(name, harness.project_id, harness.workspace_id,
                    principal.principal_id, "fixture", "fixture", harness.project_id + ":" + target["asset_version_id"] + ":" + dimension + ":" + actor_suffix,
                    {"evaluation" if "evaluation_id" in payload else "adjudication": payload,
                     **({"reference_sample": target} if sample_target else {})}, tuple(inputs)), principal=principal)
                return {"asset_version_id": result.asset_version_id, "content_hash": result.content_hash}

            humans = [author("quality.human_evaluation.record", "world-fixture-human-" + str(i),
                {**shared, "evaluation_id": harness.project_id + ":" + target["asset_version_id"] + ":" + dimension + ":" + str(i),
                 "evaluator_group": "SCRIPTED_INTEGRATION_FIXTURE", "evaluator_identity_class": "PROFESSIONAL_EDITOR",
                 "score": 0, "confidence": 0.8, "evidence": [{"fixture_protocol_only": True}], "blind": True}, [target]) for i in (1, 2)]
            adjudications.append(author("quality.adjudication.record", "world-fixture-adjudicator",
                {**shared, "adjudication_id": harness.project_id + ":" + target["asset_version_id"] + ":" + dimension + ":adjudication",
                 "adjudicator_identity_class": "PROFESSIONAL_EDITOR", "score_range": [0, 0],
                 "source_human_evaluation_asset_version_ids": [row["asset_version_id"] for row in humans],
                 "rationale": "Scripted contradictory labels exercise disagreement retention only."}, [target, *humans]))
    return {"protocol_version": "fixture-world-blind", "adjudications": adjudications}
