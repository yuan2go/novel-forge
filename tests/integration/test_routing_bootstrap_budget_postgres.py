from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from novel_forge.api.authority_dependencies import build_production_execution_composition
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.authority_handler_runtime.policy_commands import configure_owned_policy
from novel_forge.modules.command_kernel.budget_runtime import (
    BudgetReservationRequest,
    assert_provider_execution_authorized,
    reserve_provider_budget,
    resolve_provider_budget_failure,
    settle_provider_budget,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.routing_bootstrap import bootstrap_command_hash
from novel_forge.modules.story_planning_runtime.application import _command_payload
from novel_forge.modules.command_kernel.external_effect_adapters import FakeDeterministicProvider, ProviderResult
from novel_forge.modules.command_kernel.external_effect_runtime import (
    EffectCommandContext, dispatch_external_effect, plan_external_effect,
)
from novel_forge.modules.production_execution.cost_routing import snapshot_hash
from novel_forge.modules.production_execution.routing_catalog import deepseek_candidates
from novel_forge.modules.production_execution.routing_runtime import ProductionProviderRouter, PostgresRoutingRegistry
from novel_forge.modules.story_planning_runtime import (
    GENERATOR_INPUT_ROLES, StoryPlanningGenerationApplication, StoryPlanningGenerationCommand,
)
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated, identifier, seed_authority_project_book
from tests.integration.test_core_functional_loops_postgres import (
    RELEASE_SHA, _ExternalEffectPepFixturePlanningBinder, _principal, _seed_inputs,
)


class _ExplicitFixtureTransport(FakeDeterministicProvider):
    provider = "production_execution_gateway"
    production_execution_gateway_backed = True
    capability_profile = {**FakeDeterministicProvider.capability_profile, "provider": provider}

    def execute(self, **kwargs):
        result = super().execute(**kwargs)
        return ProviderResult(result.outcome, result.provider_correlation_id, {**result.evidence, "fixture": True})


@pytest.mark.parametrize("scenario", ["success", "timeout_after"])
@pytest.mark.parametrize("accounting_basis", ["PRICED", "ACCOUNT_ENTITLEMENT"])
def test_bootstrap_router_freezes_grant_and_kernel_caps_same_effect_generations(tmp_path, scenario, accounting_basis):
    ensure_migrated()
    project = identifier("bootstrap-kernel-fixture")
    workspace, book = f"workspace:{project}", f"book:{project}"
    seed_authority_project_book(project_id=project, workspace_id=workspace, book_id=book)
    principal = _principal(project)
    inputs = _seed_inputs(project, book, target_chapter_count=6)
    command = StoryPlanningGenerationCommand(
        project_id=project, workspace_id=workspace, book_id=book,
        actor_id=principal.principal_id, generator_operation_name="book_plan.generate",
        logical_key="book:bootstrap-kernel", input_versions={role: inputs[role] for role in GENERATOR_INPUT_ROLES["book_plan.generate"]},
        idempotency_key=f"{project}:sample", trace_id="fixture:trace", correlation_id="fixture:correlation",
        routing_bootstrap_authorization_id="bootstrap-kernel:grant",
    )
    candidate = deepseek_candidates(available=True)[0]
    entitlement = accounting_basis == "ACCOUNT_ENTITLEMENT"
    if entitlement:
        candidate = replace(candidate, candidate_id="fixture-codex", provider="codex-cli", model="fixture-codex-model",
            model_revision="sha256:" + "f" * 64,
            escalation_only=True, authorization_ref="fixture-codex-entitlement", quota_remaining=5,
            pricing=replace(candidate.pricing, accounting_basis=accounting_basis, currency="UNKNOWN",
                version="fixture-account-v1", source="fixture-account-authorization",
                input_miss_per_million="0", input_hit_per_million="0", output_per_million="0"))
    expiry = datetime.now(timezone.utc) + timedelta(hours=1)
    grant = {
        "authorization_id": command.routing_bootstrap_authorization_id,
        "reason": "fixture-only Kernel authorization regression", "environment": "validation",
        "book_id": book, "task_type": command.generator_operation_name,
        "logical_key": command.logical_key, "generation_idempotency_key": command.idempotency_key,
        "input_versions_hash": snapshot_hash(dict(command.input_versions)),
        "command_hash": bootstrap_command_hash(_command_payload(command)),
        "producer_contract_hash": snapshot_hash({"fixture_prompt": "v1"}),
        "candidate_id": candidate.candidate_id, "model_revision": candidate.model_revision,
        "expires_at": expiry.isoformat(), "maximum_calls": 1, "maximum_tokens": 4096,
        "maximum_amount": "0.1", "currency": "USD", "purpose": "BENCHMARK_CHALLENGER",
        "production_eligible": False,
        "campaign": {"campaign_id": "campaign:" + project, "manifest_hash": "sha256:" + "c" * 64,
                     "sample_id": "sample-one", "group_id": "group-one", "partition": "CALIBRATION",
                     "maximum_calls": 1, "maximum_tokens": 4096, "maximum_amount": "0.1",
                     "expires_at": expiry.isoformat()},
    }
    if entitlement:
        grant["campaign"]["maximum_amount"] = "0"
        grant.update(accounting_basis=accounting_basis, currency="UNKNOWN", maximum_amount=None,
                     cost_authorization_ref=candidate.authorization_ref)
    overrides = [{"work_id": book, "task_type": command.generator_operation_name,
                  "risk": "HIGH", "quality_floor": 0.9,
                  "escalation_reason": "explicit fixture-only high-risk control"}] if entitlement else []
    configure_owned_policy(
        database_url=DATABASE_URL, owner="PROVIDER_ROUTING",
        content={"policy_version": "bootstrap-kernel:v1", "reason": "fixture authorization",
                 "task_overrides": overrides, "bootstrap_authorizations": [grant]},
        project_id=project, workspace_id=workspace, idempotency_key=f"{project}:policy",
        trace_id=command.trace_id, correlation_id=command.correlation_id,
        application_build_id="bootstrap-kernel-test", commit_sha=RELEASE_SHA, principal=principal,
    )
    composition = build_production_execution_composition(
        IndustrialSettings(root=tmp_path, database_url=DATABASE_URL), env={
            "NOVEL_FORGE_ENVIRONMENT": "test", "NOVEL_FORGE_MODEL_PROVIDER": "mock",
            "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(tmp_path / "objects"),
            "NOVEL_FORGE_COMMIT_SHA": RELEASE_SHA,
        },
    )
    router = ProductionProviderRouter(DATABASE_URL, candidates=(candidate,),
        task_money_limit="0.1", task_token_limit=4096, execution_environment="validation")

    class ExpiredClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return (expiry + timedelta(seconds=1)).astimezone(tz)

    campaign_error = ""
    campaign_configured = False

    class BudgetCheckingBinder(_ExternalEffectPepFixturePlanningBinder):
        def execute(self, **kwargs):
            nonlocal campaign_configured
            operation, attempt = kwargs["operation_id"], kwargs["attempt_id"]
            stable_key = f"{operation}:{attempt}:fixture-bootstrap"
            _, decision = router.select(composition.gateway.routes["draft"],
                task_type=command.generator_operation_name, project_id=project, work_id=book,
                operation_id=operation, attempt_id=attempt, stable_key=stable_key,
                input_tokens=100, output_tokens=100, trace_id=command.trace_id,
                correlation_id=command.correlation_id, request_input={"fixture": True},
                producer_contract={"fixture_prompt": "v1"})
            assert decision["status"] == "BENCHMARK_SELECTED"
            assert decision["production_eligible"] is False
            assert decision["selected"]["benchmark"]["sample_count"] == 0
            context = EffectCommandContext(operation, project, principal.principal_id, command.trace_id, command.correlation_id)
            effect = plan_external_effect(DATABASE_URL, context,
                effect_type="model.invoke", provider="production_execution_gateway",
                capability="planning.book.generate", stable_idempotency_key=stable_key,
                request_payload={"stage": command.generator_operation_name, "max_output_tokens": 100,
                    "input": {"planning_command": {"repair_number": 0}}, "_production_execution": {"book_id": book, "attempt_id": attempt,
                    "capability_runtime": {"routing_decision": decision}}},
                max_attempts=4, reversible=False, model_id=candidate.model, completion_policy="synchronous_final")
            request = BudgetReservationRequest(operation, effect["external_effect_id"], project,
                f"budget:{stable_key}:generation:1", candidate.provider, "UNKNOWN" if entitlement else "USD", None if entitlement else ".001", 200,
                model_id=candidate.model, work_id=book, accounting_basis=accounting_basis,
                cost_authorization_ref=candidate.authorization_ref if entitlement else "")
            forged = plan_external_effect(DATABASE_URL, context,
                effect_type="model.invoke", provider="production_execution_gateway",
                capability="model.book_plan.generate", stable_idempotency_key=stable_key + ":forged",
                request_payload={"max_output_tokens": 100, "_production_execution": {
                    "book_id": book, "capability_runtime": {"routing_decision": {
                        **decision, "asset_version_id": "missing-routing-asset",
                    }}}}, max_attempts=1, reversible=False, model_id=candidate.model)
            with pytest.raises(KernelError, match="ROUTING_DECISION_INTEGRITY_FAILURE"):
                reserve_provider_budget(DATABASE_URL, replace(request,
                    external_effect_id=forged["external_effect_id"], stable_idempotency_key=request.stable_idempotency_key + ":forged"))
            if entitlement and not campaign_configured:
                from tests.unit.test_creative_budget_contract import provider_campaign_policy

                with pytest.raises(KernelError, match="CREATIVE_BUDGET_AUTHORIZATION_REQUIRED"):
                    reserve_provider_budget(DATABASE_URL, request)
                policy = provider_campaign_policy()
                plan = policy["comparison_budget"]
                plan.update(experiment_id=grant["campaign"]["campaign_id"], manifest_hash=grant["campaign"]["manifest_hash"])
                plan["arms"][0].update(project_id=project, book_id=book)
                plan["entitlements"][0].update(tokens=4096)
                policy["authorization"].update(project_id=project, book_id=book)
                configure_owned_policy(database_url=DATABASE_URL, owner="CREATIVE_EXPERIMENT_BUDGET",
                    content=policy, project_id=project, workspace_id=workspace, idempotency_key=project + ":whole-campaign",
                    trace_id=command.trace_id, correlation_id=command.correlation_id,
                    application_build_id="bootstrap-kernel-test", commit_sha=RELEASE_SHA, principal=principal)
                campaign_configured = True
            if entitlement:
                with pytest.raises(KernelError, match="ROUTING_BOOTSTRAP_ACCOUNTING_INVALID"):
                    reserve_provider_budget(DATABASE_URL, replace(request, cost_authorization_ref="another-account"))
            if campaign_error:
                with pytest.raises(KernelError, match=campaign_error):
                    reserve_provider_budget(DATABASE_URL, request)
                return super().execute(**kwargs)
            first = reserve_provider_budget(DATABASE_URL, request)
            assert reserve_provider_budget(DATABASE_URL, request)["replayed"]
            resolve_provider_budget_failure(DATABASE_URL, reservation_id=first["reservation_id"],
                project_id=project, external_state_unknown=False)
            request = replace(request, stable_idempotency_key=f"budget:{stable_key}:generation:2")
            reserved = reserve_provider_budget(DATABASE_URL, request)
            with patch("novel_forge.modules.command_kernel.routing_bootstrap.datetime", ExpiredClock):
                with pytest.raises(KernelError, match="ROUTING_BOOTSTRAP_EXPIRED"):
                    assert_provider_execution_authorized(DATABASE_URL, operation_id=operation,
                        external_effect_id=effect["external_effect_id"], project_id=project,
                        budget_reservation_id=reserved["reservation_id"])
            dispatched = dispatch_external_effect(DATABASE_URL, context,
                effect_id=effect["external_effect_id"], worker_id="fixture-bootstrap-worker", lease_seconds=60,
                adapter=_ExplicitFixtureTransport(scenario), budget_reservation_id=reserved["reservation_id"])
            assert dispatched["outcome"] == ("success" if scenario == "success" else "unknown")
            # Explicit fixture settlement checks authorization after expiry; no paid Provider was called.
            with patch("novel_forge.modules.command_kernel.routing_bootstrap.datetime", ExpiredClock):
                settled = settle_provider_budget(DATABASE_URL, reservation_id=reserved["reservation_id"],
                    project_id=project, actual_amount=None if entitlement else ".0001", actual_tokens=30, evidence={"fixture": True})
                assert settled["status"] == "SETTLED"
                assert reserve_provider_budget(DATABASE_URL, request)["replayed"]
            retry = replace(request, stable_idempotency_key=f"budget:{stable_key}:generation:3")
            code = "ROUTING_BOOTSTRAP_QUOTA_EXCEEDED" if scenario == "success" else "ROUTING_BOOTSTRAP_RECONCILIATION_REQUIRED"
            if entitlement:
                code = "BUDGET_IDEMPOTENCY_CONFLICT"
            with pytest.raises(KernelError, match=code):
                reserve_provider_budget(DATABASE_URL, retry)
            return super().execute(**kwargs)

    binder = BudgetCheckingBinder(target_chapter_count=6)
    binder.resolver = SimpleNamespace(environment="validation")
    application = StoryPlanningGenerationApplication(DATABASE_URL, execution_binder=binder,
        application_build_id="bootstrap-kernel-test", commit_sha=RELEASE_SHA,
        allow_scripted_evaluation_fixture=True)
    result = application.generate(command, principal=principal)
    assert result.candidate_asset_version_id
    command = replace(command, idempotency_key=f"{project}:new-run-key",
                      logical_key="book:new-sample", routing_bootstrap_authorization_id="grant-two")
    second = {**grant, "authorization_id": "grant-two", "logical_key": command.logical_key,
              "generation_idempotency_key": command.idempotency_key,
              "command_hash": bootstrap_command_hash(_command_payload(command)),
        "producer_contract_hash": snapshot_hash({"fixture_prompt": "v1"}),
              "campaign": {**grant["campaign"], "sample_id": "sample-two"}}
    configure_owned_policy(
        database_url=DATABASE_URL, owner="PROVIDER_ROUTING",
        content={"policy_version": "bootstrap-kernel:v2", "reason": "fixture second sample",
                 "task_overrides": overrides, "bootstrap_authorizations": [second]},
        project_id=project, workspace_id=workspace, idempotency_key=f"{project}:policy-two",
        trace_id=command.trace_id, correlation_id=command.correlation_id,
        application_build_id="bootstrap-kernel-test", commit_sha=RELEASE_SHA, principal=principal,
    )
    campaign_error = ("ROUTING_CAMPAIGN_QUOTA_EXCEEDED" if scenario == "success"
                      else "ROUTING_CAMPAIGN_RECONCILIATION_REQUIRED")
    if entitlement:
        campaign_error = "CREATIVE_BUDGET_EXHAUSTED"
    assert application.generate(command, principal=principal).candidate_asset_version_id
    report = PostgresRoutingRegistry(DATABASE_URL).campaign(project_id=project, campaign_id="campaign:" + project)
    assert report["usage"]["calls_used_or_reserved"] == 1
    assert report["usage"]["conservative_tokens"] == 30
    if entitlement:
        assert report["usage"]["settled_or_reserved_usd"] is None
        assert report["usage"]["total_monetary_cost_status"] == "UNKNOWN"
        assert report["usage"]["unpriced_calls"] == 1
        assert report["usage"]["entitlements"] == [{"provider": "codex-cli", "authorization_ref": candidate.authorization_ref,
                                                   "calls_used_or_reserved": 1, "conservative_tokens": 30, "usd": None}]
    else:
        assert float(report["usage"]["settled_or_reserved_usd"]) == .0001
    assert len(report["grants"]) == 2
    assert report["scope"] == "BOOTSTRAP_SAMPLING_ONLY"
    assert report["state"] == ("ACCOUNTED" if scenario == "success" else "RECONCILIATION_REQUIRED")
    with pytest.raises(KernelError, match="ROUTING_CAMPAIGN_PROJECT_REBIND_FORBIDDEN"):
        configure_owned_policy(
            database_url=DATABASE_URL, owner="PROVIDER_ROUTING",
            content={"policy_version": "bootstrap-kernel:v3", "reason": "fixture reset attempt",
                     "task_overrides": [], "bootstrap_authorizations": [{**second,
                         "authorization_id": "grant-three", "campaign": {
                             **second["campaign"], "campaign_id": "renamed-campaign"}}]},
            project_id=project, workspace_id=workspace, idempotency_key=f"{project}:policy-three",
            trace_id=command.trace_id, correlation_id=command.correlation_id,
            application_build_id="bootstrap-kernel-test", commit_sha=RELEASE_SHA, principal=principal,
        )


@pytest.mark.parametrize("reference_author", ["independent", "generator", "unknown", "trusted_projection"])
def test_native_reference_evaluation_stays_out_of_domain_qualification(tmp_path, reference_author, monkeypatch):
    from novel_forge.modules.content_authority import ContentAuthorityApplication, ContentOperationRequest
    from novel_forge.modules.content_authority.definitions import CONTENT_INTEGRATION_PROVEN
    from novel_forge.modules.story_design_authority import scripted_qualification
    from dataclasses import asdict
    from novel_forge.modules.story_design_authority.evaluation_runtime import (
        NarrativeProviderEvaluation, NarrativeSemanticEvaluationCommand, evaluation_command_payload,
    )
    from novel_forge.modules.story_planning_runtime import StoryPlanningEvaluationCommand
    from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
    from novel_forge.storage.authority_asset_store import AuthorityAssetWriter
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork

    ensure_migrated()
    project = identifier("reference-bootstrap-fixture")
    workspace, book = "workspace:" + project, "book:" + project
    seed_authority_project_book(project_id=project, workspace_id=workspace, book_id=book)
    principal = _principal(project)
    evaluator = replace(principal, principal_id="independent-evaluator:" + project)
    inputs = _seed_inputs(project, book, target_chapter_count=6)
    command = StoryPlanningGenerationCommand(
        project_id=project, workspace_id=workspace, book_id=book, actor_id=principal.principal_id,
        generator_operation_name="book_plan.generate", logical_key="reference-target",
        input_versions={role: inputs[role] for role in GENERATOR_INPUT_ROLES["book_plan.generate"]},
        idempotency_key=project + ":generate", trace_id="trace:reference", correlation_id="correlation:reference",
        routing_bootstrap_authorization_id="generation-grant",
    )
    candidate = deepseek_candidates(available=True)[0]
    expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    campaign = {"campaign_id": "campaign:" + project, "manifest_hash": "sha256:" + "c" * 64,
                "sample_id": "generation", "group_id": "target-one", "partition": "CALIBRATION",
                "maximum_calls": 4, "maximum_tokens": 16384, "maximum_amount": "0.4", "expires_at": expiry}
    grant = {
        "authorization_id": "generation-grant", "reason": "fixture-only reference sampling",
        "environment": "validation", "book_id": book, "task_type": "book_plan.generate",
        "logical_key": command.logical_key, "generation_idempotency_key": command.idempotency_key,
        "input_versions_hash": snapshot_hash(dict(command.input_versions)),
        "command_hash": bootstrap_command_hash(_command_payload(command)),
        "producer_contract_hash": snapshot_hash({"fixture_prompt": "v1"}),
        "candidate_id": candidate.candidate_id, "model_revision": candidate.model_revision,
        "expires_at": expiry, "maximum_calls": 2, "maximum_tokens": 4096, "maximum_amount": "0.1",
        "currency": "USD", "purpose": "BENCHMARK_CHALLENGER", "production_eligible": False,
        "campaign": campaign,
    }

    def configure(version, grants):
        configure_owned_policy(
            database_url=DATABASE_URL, owner="PROVIDER_ROUTING",
            content={"policy_version": version, "reason": "fixture reference authorization",
                     "task_overrides": [], "bootstrap_authorizations": grants},
            project_id=project, workspace_id=workspace, idempotency_key=project + ":" + version,
            trace_id=command.trace_id, correlation_id=command.correlation_id,
            application_build_id="reference-fixture", commit_sha=RELEASE_SHA, principal=principal,
        )

    configure("reference-fixture:v1", [grant])
    binder = _ExternalEffectPepFixturePlanningBinder(target_chapter_count=6)
    binder.resolver = SimpleNamespace(environment="validation")
    application = StoryPlanningGenerationApplication(
        DATABASE_URL, execution_binder=binder, application_build_id="reference-fixture",
        commit_sha=RELEASE_SHA, allow_scripted_evaluation_fixture=True,
    )
    generated = application.generate(command, principal=principal)
    assert generated.candidate_asset_version_id
    candidate_hash = application.require_candidate(generated.candidate_asset_version_id)["content_hash"]
    labeled = scripted_qualification("book_plan.generate")
    adjudicated_reference = None
    if reference_author in {"independent", "trusted_projection"}:
        adjudicated_reference = _exercise_planning_reference_annotations(project=project, workspace=workspace, principal=principal,
            target={"asset_version_id": generated.candidate_asset_version_id, "content_hash": candidate_hash}, evaluation=labeled,
            projection_fixture=reference_author == "trusted_projection")
    labeler = replace(principal,
        principal_id=(principal.principal_id if reference_author == "generator" else "label-operator:" + project),
        permissions=principal.permissions | {"content.authority.execute", "content.operation:story_design.review.author"})
    authored = ContentAuthorityApplication(DATABASE_URL, application_build_id="reference-fixture",
        commit_sha=RELEASE_SHA, integration_proven=CONTENT_INTEGRATION_PROVEN, trusted_only=True).execute(
        ContentOperationRequest(definition_name="story_design.review.author", project_id=project,
            workspace_id=workspace, actor_id=labeler.principal_id, trace_id=command.trace_id,
            correlation_id=command.correlation_id, idempotency_key=project + ":reference-labels",
            payload={"candidate_asset_version_id": generated.candidate_asset_version_id,
                     "candidate_content_hash": candidate_hash,
                     "evaluation": labeled, "review_rationale": "Explicit synthetic labels for isolation regression"},
            input_assets=({"asset_version_id": generated.candidate_asset_version_id,
                           "content_hash": candidate_hash},)), principal=labeler)
    review = StoryPlanningEvaluationCommand(
        project_id=project, workspace_id=workspace, book_id=book, actor_id=evaluator.principal_id,
        candidate_asset_version_id=generated.candidate_asset_version_id,
        candidate_content_hash=candidate_hash,
        generation_operation_id=generated.generation_operation_id, generator_operation_name="book_plan.generate",
        evaluator_execution_class="MODEL_PROVIDER", idempotency_key=project + ":reference-evaluate",
        trace_id=command.trace_id, correlation_id=command.correlation_id,
        routing_bootstrap_authorization_id="reference-grant",
        reference_evaluation={"asset_version_id": authored.asset_version_id,
                              "content_hash": authored.content_hash, "protocol_version": "fixture-labels-v1",
                              **({"adjudicated_reference": adjudicated_reference} if adjudicated_reference else {})},
    )
    semantic_command = NarrativeSemanticEvaluationCommand(**asdict(review))
    payload = evaluation_command_payload(semantic_command, generation_actor_id=principal.principal_id,
                                         opening_execution_binding={})
    if reference_author != "generator":
        prepared = application.semantic_evaluation.prepare_reference_evaluation(semantic_command, principal=evaluator)
        assert prepared["payload"] == payload
        assert prepared["command_hash"] == bootstrap_command_hash(payload)
        assert prepared["provider_calls"] == 0 and prepared["authorized"] is False
        if adjudicated_reference:
            short = {**adjudicated_reference, "adjudications": adjudicated_reference["adjudications"][:-1]}
            with pytest.raises(KernelError, match="QUALITY_REFERENCE_COVERAGE_INCOMPLETE"):
                application.semantic_evaluation.prepare_reference_evaluation(replace(semantic_command,
                    reference_evaluation={**review.reference_evaluation, "adjudicated_reference": short}), principal=evaluator)
            wrong_scope = {**adjudicated_reference, "scope": {**adjudicated_reference["scope"], "chapter_end": 5}}
            with pytest.raises(KernelError, match="QUALITY_REFERENCE_NOT_INDEPENDENT"):
                application.semantic_evaluation.prepare_reference_evaluation(replace(semantic_command,
                    reference_evaluation={**review.reference_evaluation, "adjudicated_reference": wrong_scope}), principal=evaluator)
            same_human = replace(evaluator, principal_id="planning-fixture-human-1")
            with pytest.raises(KernelError, match="QUALITY_REFERENCE_NOT_INDEPENDENT"):
                application.semantic_evaluation.prepare_reference_evaluation(replace(semantic_command,
                    actor_id=same_human.principal_id), principal=same_human)
    else:
        with pytest.raises(KernelError, match="NARRATIVE_REFERENCE_NOT_INDEPENDENT"):
            application.semantic_evaluation.prepare_reference_evaluation(semantic_command, principal=evaluator)
    reference_grant = {**grant, "authorization_id": "reference-grant", "purpose": "REFERENCE_EVALUATION",
                       "task_type": "narrative_semantic_evaluation", "logical_key": review.candidate_asset_version_id,
                       "generation_idempotency_key": review.idempotency_key,
                       "input_versions_hash": snapshot_hash(payload["input_versions"]),
                       "command_hash": bootstrap_command_hash(payload),
                       "reference_evaluation": review.reference_evaluation,
                       "campaign": {**campaign, "sample_id": "reference"}}
    configure("reference-fixture:v2", [grant, reference_grant])
    composition = build_production_execution_composition(
        IndustrialSettings(root=tmp_path, database_url=DATABASE_URL), env={
            "NOVEL_FORGE_ENVIRONMENT": "test", "NOVEL_FORGE_MODEL_PROVIDER": "mock",
            "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(tmp_path / "objects"),
            "NOVEL_FORGE_COMMIT_SHA": RELEASE_SHA})
    router = ProductionProviderRouter(DATABASE_URL, candidates=(candidate,), task_money_limit="0.1",
                                     task_token_limit=4096, execution_environment="validation")

    class ReferenceFixturePort:
        production_execution_gateway_backed = True
        external_effect_backed = True
        database_url = DATABASE_URL
        model_port = SimpleNamespace(capability_binder=SimpleNamespace(pack_environment="validation"))
        invocations = 0
        failure_code = ""
        unknown_effect = False

        def evaluate(self, request, *, candidate: object, generator_operation_name, profiles):
            self.invocations += 1
            if self.failure_code:
                raise KernelError(self.failure_code, "Explicit reference recovery fixture")
            from novel_forge.modules.story_design_authority.replacement_gate import assert_narrative_replacement_execution_gate

            gate = assert_narrative_replacement_execution_gate(DATABASE_URL, project_id=project, operation_id=request.operation_id)
            assert gate["execution_authority"] == "COMMAND_KERNEL"
            assert len(request.inputs) == 1
            assert request.inputs[0].asset_version_id != authored.asset_version_id
            key = request.operation_id + ":reference-fixture"
            _, decision = router.select(composition.gateway.routes["draft"],
                task_type="narrative_semantic_evaluation", project_id=project, work_id=book,
                operation_id=request.operation_id, attempt_id=request.attempt_id, stable_key=key,
                input_tokens=100, output_tokens=100, trace_id=request.trace_id,
                correlation_id=request.correlation_id, request_input={"fixture": True},
                producer_contract={"fixture_prompt": "v1"})
            assert decision["status"] == "BENCHMARK_SELECTED"
            context = EffectCommandContext(request.operation_id, project, request.actor_id,
                                           request.trace_id, request.correlation_id)
            effect = plan_external_effect(DATABASE_URL, context, effect_type="model.invoke",
                provider="production_execution_gateway", capability="model.narrative_semantic_evaluation",
                stable_idempotency_key=key, request_payload={"max_output_tokens": 100,
                    "_production_execution": {"book_id": book, "capability_runtime": {"routing_decision": decision}}},
                max_attempts=1, reversible=False, model_id=decision["selected"]["candidate"]["model"])
            reserved = reserve_provider_budget(DATABASE_URL, BudgetReservationRequest(
                request.operation_id, effect["external_effect_id"], project, key + ":budget",
                "deepseek", "USD", ".001", 200, work_id=book,
                model_id=decision["selected"]["candidate"]["model"]))
            dispatched = dispatch_external_effect(DATABASE_URL, context,
                effect_id=effect["external_effect_id"], worker_id="reference-fixture", lease_seconds=60,
                adapter=_ExplicitFixtureTransport("timeout_after" if self.unknown_effect else "success"),
                budget_reservation_id=reserved["reservation_id"])
            if self.unknown_effect:
                assert dispatched["outcome"] == "unknown"
                raise KernelError("EXTERNAL_EFFECT_RESULT_UNKNOWN", "Explicit reference ambiguity fixture")
            assert dispatched["outcome"] == "success"
            settle_provider_budget(DATABASE_URL, reservation_id=reserved["reservation_id"], project_id=project,
                                   actual_amount=".0001", actual_tokens=30, evidence={"fixture": True})
            # WHY: Synthetic native-shaped evidence exercises projection; no real Provider or human labels are produced.
            selected = decision["selected"]["candidate"]
            provider_evidence = {"real_model_call": True, "provider_id": selected["provider"], "model_id": selected["model"],
                "result": labeled, "usage": {"input_tokens": 100, "output_tokens": 100}, "cost": {"amount": ".0001", "currency": "USD"},
                "production_execution": {"execution_request": {"project_id": project, "operation_id": request.operation_id,
                    "attempt_id": request.attempt_id, "stage": "narrative_semantic_evaluation", "external_effect_id": effect["external_effect_id"]},
                    "execution_result": {"outcome": "SUCCEEDED"}, "route_snapshot": {"reasoning_effort": selected["reasoning"]},
                    "process_evidence": {"served_model_identity_hash": "sha256:" + "f" * 64, "model_revision": selected["model_revision"]}}}
            log_content = {"stage": "narrative_semantic_evaluation", "operation_id": request.operation_id, "attempt_id": request.attempt_id,
                "target_lineage": {"target_asset_version_id": review.candidate_asset_version_id, "target_content_hash": candidate_hash,
                    "generation_operation_id": generated.generation_operation_id, "generator_operation_name": "book_plan.generate"},
                "provider_evidence": provider_evidence} if reference_author == "trusted_projection" else {"fixture": True, "fixture_protocol_only": True}
            log = AuthorityAssetWriter(DATABASE_URL).materialize_output(AuthorityAssetWriteCommand(
                operation_id=request.operation_id, project_id=project, asset_id=key + ":model-log",
                asset_type="model_call_log", schema_version="model-call-log.v1",
                logical_ref="reference-fixture/" + request.operation_id + ".json", category="fixture",
                output_key="model_call_log", role="model_evidence" if reference_author == "trusted_projection" else "provider_evidence",
                content=log_content, qualification_policy="fixture-only-v1",
                trace_id=request.trace_id, correlation_id=request.correlation_id))
            return NarrativeProviderEvaluation(labeled, log.asset_version_id, log.content_hash,
                snapshot_hash(provider_evidence if reference_author == "trusted_projection" else {"fixture": True}), snapshot_hash(labeled), "synthetic-reference",
                "synthetic-reference-v1", decision["decision_id"], "synthetic-prompt-v1",
                "synthetic-skill-v1", True)

    port = ReferenceFixturePort()
    application.semantic_evaluation.execution_port = port
    application.semantic_evaluation.registry.item.handler.execution_port = port
    if reference_author == "generator":
        with pytest.raises(KernelError, match="NARRATIVE_REFERENCE_NOT_INDEPENDENT"):
            application.evaluate_candidate(review, principal=evaluator, transition_principal=principal)
        assert port.invocations == 0
        return
    result = application.evaluate_candidate(review, principal=evaluator, transition_principal=principal)
    assert result.evaluation_content["reference_evaluation"]["agreement_rate"] == 1
    reference_result = result.evaluation_content["reference_evaluation"]
    assert reference_result["schema_version"] == ("narrative-reference-agreement.v2" if adjudicated_reference else "narrative-reference-agreement.v1")
    if adjudicated_reference:
        assert reference_result["adjudicated_reference"]["scope"] == adjudicated_reference["scope"]
        assert reference_result["reference_basis"] == "ADJUDICATED_SUBJECTIVE_EVIDENCE"
    assert result.evaluation_content["production_qualification_eligible"] is False
    assert application.evaluate_candidate(review, principal=evaluator, transition_principal=principal).replayed
    assert port.invocations == 1
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        from novel_forge.modules.authority_handler_runtime.routing_feedback import domain_gate_outcomes
        uow.cursor.execute("SELECT external_effect_id FROM authority_external_effect WHERE operation_id=%s", [result.lineage.evaluation_operation_id])
        effect_ids = [row[0] for row in uow.cursor.fetchall()]
        with monkeypatch.context() as guard:
            def forbid_reopened_reference_uow(*args, **kwargs):
                raise AssertionError("Reference projection must query its existing authenticated transaction")
            guard.setattr("novel_forge.modules.story_design_authority.evaluation_reference.AuthorityUnitOfWork", forbid_reopened_reference_uow)
            outcomes = domain_gate_outcomes(uow.cursor, project_id=project, effect_ids=effect_ids)
        if reference_author == "trusted_projection":
            assert len(outcomes) == 1
            projected = outcomes[effect_ids[0]]
            assert projected["reference_agreed"] is True and projected["accepted"] is None
            assert projected["reference_label_classes"] == ("PASS",)
        else:
            assert outcomes == {}
        uow.cursor.execute("SELECT count(*) FROM authority_narrative_design_qualification WHERE project_id=%s AND asset_version_id=%s", [project, generated.candidate_asset_version_id])
        assert uow.cursor.fetchone()[0] == 0
        uow.cursor.execute("SELECT status FROM authority_story_planning_generation WHERE operation_id=%s", [generated.generation_operation_id])
        assert uow.cursor.fetchone()[0] == "EVALUATION_PENDING"
    if reference_author == "trusted_projection":
        observations = PostgresRoutingRegistry(DATABASE_URL, outcome_projection=domain_gate_outcomes).observations(
            project_id=project, task_type="narrative_semantic_evaluation", candidate=candidate,
            producer_contract_hash=snapshot_hash({"fixture_prompt": "v1"}))
        assert len(observations) == 1 and observations[0].reference_agreed is True
        assert observations[0].reference_label_classes == ("PASS",) and observations[0].production_eligible is False
        assert observations[0].reference_protocol_hash == projected["reference_protocol_hash"]
    comparison = replace(review, idempotency_key=project + ":reference-pro", routing_bootstrap_authorization_id="reference-pro-grant")
    pro = deepseek_candidates(available=True)[1]
    comparison_payload = evaluation_command_payload(NarrativeSemanticEvaluationCommand(**asdict(comparison)),
        generation_actor_id=principal.principal_id, opening_execution_binding={})
    comparison_grant = {**reference_grant, "authorization_id": comparison.routing_bootstrap_authorization_id,
                        "candidate_id": pro.candidate_id, "model_revision": pro.model_revision,
                        "generation_idempotency_key": comparison.idempotency_key,
                        "command_hash": bootstrap_command_hash(comparison_payload)}
    configure("reference-fixture:v3", [grant, reference_grant, comparison_grant])
    router = ProductionProviderRouter(DATABASE_URL, candidates=(pro,), task_money_limit="0.1",
                                     task_token_limit=4096, execution_environment="validation")
    compared = application.evaluate_candidate(comparison, principal=evaluator, transition_principal=principal)
    assert compared.lineage.evaluation_operation_id != result.lineage.evaluation_operation_id
    assert compared.lineage.candidate_content_hash == result.lineage.candidate_content_hash
    assert compared.evaluation_content["reference_evaluation"] == result.evaluation_content["reference_evaluation"]
    assert port.invocations == 2
    from psycopg.errors import CheckViolation

    with pytest.raises(CheckViolation, match="NARRATIVE_REFERENCE_CANNOT_QUALIFY_PRODUCTION"):
        application.semantic_evaluation._record_qualifications(
            semantic_command, replace(result.lineage, evaluator_execution_class="SCRIPTED_FIXTURE",
                provider_model_call_asset_version_id="", provider_model_call_content_hash="",
                provider_evidence_hash="", provider_result_hash="", provider_route_snapshot_id=""),
            result.qualification,
        )
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT count(*) FROM authority_narrative_evaluation_execution_head WHERE project_id=%s AND candidate_asset_version_id=%s", [project, generated.candidate_asset_version_id])
        assert uow.cursor.fetchone()[0] == 0
    usage = PostgresRoutingRegistry(DATABASE_URL).campaign(project_id=project, campaign_id="campaign:" + project)
    assert usage["usage"]["calls_used_or_reserved"] == 2
    assert {operation["purpose"] for operation in usage["operations"]} == {"BENCHMARK_CHALLENGER", "REFERENCE_EVALUATION"}
    grants = [grant, reference_grant, comparison_grant]

    def grant_review(command, model, version):
        command_payload = evaluation_command_payload(NarrativeSemanticEvaluationCommand(**asdict(command)),
            generation_actor_id=principal.principal_id, opening_execution_binding={})
        grants.append({**reference_grant, "authorization_id": command.routing_bootstrap_authorization_id,
                       "candidate_id": model.candidate_id, "model_revision": model.model_revision,
                       "generation_idempotency_key": command.idempotency_key,
                       "command_hash": bootstrap_command_hash(command_payload)})
        configure(version, grants)

    duplicate = replace(review, idempotency_key=project + ":duplicate",
                        routing_bootstrap_authorization_id="duplicate-grant")
    grant_review(duplicate, candidate, "reference-fixture:v4")
    with pytest.raises(KernelError, match="NARRATIVE_REFERENCE_PREDECESSOR_REQUIRED"):
        application.evaluate_candidate(duplicate, principal=evaluator, transition_principal=principal)
    duplicate = replace(duplicate, idempotency_key=project + ":duplicate-linked",
                        routing_bootstrap_authorization_id="duplicate-linked-grant",
                        reference_predecessor_operation_id=result.lineage.evaluation_operation_id)
    grant_review(duplicate, candidate, "reference-fixture:v5")
    with pytest.raises(KernelError, match="NARRATIVE_REFERENCE_PREDECESSOR_NOT_REPLACEABLE"):
        application.evaluate_candidate(duplicate, principal=evaluator, transition_principal=principal)
    assert port.invocations == 2

    maximum = deepseek_candidates(available=True)[2]
    failed = replace(review, idempotency_key=project + ":failure",
                     routing_bootstrap_authorization_id="failure-grant")
    grant_review(failed, maximum, "reference-fixture:v6")
    router = ProductionProviderRouter(DATABASE_URL, candidates=(maximum,), task_money_limit="0.1",
                                     task_token_limit=4096, execution_environment="validation")
    port.unknown_effect = reference_author == "unknown"
    port.failure_code = "" if port.unknown_effect else "MODEL_EFFECT_FINAL_REFERENCE_FIXTURE"
    with pytest.raises(KernelError, match="EXTERNAL_EFFECT_RESULT_UNKNOWN" if port.unknown_effect else port.failure_code):
        application.evaluate_candidate(failed, principal=evaluator, transition_principal=principal)
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT operation_id,status FROM authority_operation WHERE project_id=%s AND idempotency_key=%s",
                           [project, failed.idempotency_key])
        failed_id, status = uow.cursor.fetchone()
        assert status in ({"RECONCILIATION_REQUIRED", "WAITING_EXTERNAL_RESULT"} if port.unknown_effect else {"FAILED_FINAL"})
    recovered = replace(failed, idempotency_key=project + ":recovered",
                        routing_bootstrap_authorization_id="recovery-grant",
                        reference_predecessor_operation_id=failed_id)
    grant_review(recovered, maximum, "reference-fixture:v7")
    if port.unknown_effect:
        with pytest.raises(KernelError, match="NARRATIVE_REFERENCE_PREDECESSOR_NOT_REPLACEABLE"):
            application.evaluate_candidate(recovered, principal=evaluator, transition_principal=principal)
        assert port.invocations == 3
        usage = PostgresRoutingRegistry(DATABASE_URL).campaign(project_id=project, campaign_id="campaign:" + project)
        assert usage["usage"]["calls_used_or_reserved"] == 3
        assert usage["state"] == "RECONCILIATION_REQUIRED"
        return
    port.failure_code = ""
    repaired = application.evaluate_candidate(recovered, principal=evaluator, transition_principal=principal)
    assert repaired.lineage.evaluation_operation_id != failed_id
    assert application.evaluate_candidate(recovered, principal=evaluator, transition_principal=principal).replayed
    assert port.invocations == 4
    usage = PostgresRoutingRegistry(DATABASE_URL).campaign(project_id=project, campaign_id="campaign:" + project)
    assert usage["usage"]["calls_used_or_reserved"] == 3
    operations = {item["operation_id"]: item for item in usage["operations"]}
    assert operations[failed_id]["status"] == "FAILED_FINAL"
    assert operations[repaired.lineage.evaluation_operation_id]["causation_operation_id"] == failed_id


def _exercise_planning_reference_annotations(*, project, workspace, principal, target, evaluation, projection_fixture=False):
    from novel_forge.modules.content_authority import ContentAuthorityApplication, ContentOperationRequest
    from novel_forge.modules.content_authority.definitions import CONTENT_INTEGRATION_PROVEN
    from novel_forge.modules.chapter_quality_authority.reference_subject import require_reference_subject
    from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork

    app = ContentAuthorityApplication(DATABASE_URL, application_build_id="reference-fixture", commit_sha=RELEASE_SHA,
        integration_proven=CONTENT_INTEGRATION_PROVEN, trusted_only=True)
    common = dict(subject_asset_version_id=target["asset_version_id"],
        protocol_version="fixture-labels-v1", evaluation_version="fixture-planning-editor-v1",
        scope_type="ARC", chapter_start=1, chapter_end=6)

    def author(name, actor, payload, inputs):
        labeler = replace(principal, principal_id=actor,
            permissions=principal.permissions | {"content.authority.execute", "content.operation:" + name})
        request = ContentOperationRequest(name, project, workspace, actor, "fixture", "fixture", project + ":" + actor + ":" + payload["dimension"],
            {"evaluation" if "evaluation_id" in payload else "adjudication": payload, "reference_sample": target}, tuple(inputs))
        result = app.execute(request, principal=labeler)
        assert app.execute(request, principal=labeler).replayed
        with pytest.raises(KernelError, match="QUALITY_REFERENCE_ANNOTATION_INVALID"):
            app.admit(replace(request, idempotency_key=request.idempotency_key + ":wrong-actor"),
                principal=replace(labeler, principal_id="different-author"))
        return {"asset_version_id": result.asset_version_id, "content_hash": result.content_hash}

    adjudications = []
    for layer in evaluation["evaluations"]:
        for criterion in layer["criteria"]:
            dimension = layer["layer"] + ":" + criterion["criterion"]
            score = 100 if criterion["verdict"] == "PASS" else 0
            fields = {**common, "dimension": dimension, "status": "PASSED" if score else "FAILED"}
            humans = [author("quality.human_evaluation.record", "planning-fixture-human-" + str(i),
                {**fields, "evaluation_id": project + ":human:" + str(i) + ":" + dimension, "evaluator_id": "planning-fixture-human-" + str(i),
                 "evaluator_group": "SYNTHETIC_NATIVE_SHAPE" if projection_fixture else "SCRIPTED_INTEGRATION_FIXTURE", "evaluator_identity_class": "PROFESSIONAL_EDITOR",
                 "score": score, "confidence": 0.8, "evidence": [{"note": "Synthetic database projection regression"}] if projection_fixture else [{"fixture_protocol_only": True}], "blind": True}, [target]) for i in (1, 2)]
            adjudications.append(author("quality.adjudication.record", "planning-fixture-adjudicator",
                {**fields, "adjudication_id": project + ":adjudication:" + dimension, "adjudicator_id": "planning-fixture-adjudicator",
                 "adjudicator_identity_class": "PROFESSIONAL_EDITOR", "score_range": [score, score],
                 "source_human_evaluation_asset_version_ids": [row["asset_version_id"] for row in humans],
                 "rationale": "Synthetic annotation isolation regression only."}, [target, *humans]))
    document = AuthorityAssetQuery(DATABASE_URL).require(project_id=project, asset_version_id=target["asset_version_id"])
    assert document.lifecycle == "CANDIDATE" and document.eligibility == "INELIGIBLE" and document.content_hash == target["content_hash"]
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        subject = require_reference_subject(uow.cursor, project_id=project, binding=target,
            allowed_types=frozenset({"planning_generation_candidate"}))
        assert subject["asset_type"] == "planning_generation_candidate"
        with pytest.raises(KernelError, match="QUALITY_REFERENCE_TARGET_INVALID"):
            require_reference_subject(uow.cursor, project_id=project, binding={**target, "content_hash": "sha256:" + "0" * 64},
                allowed_types=frozenset({"planning_generation_candidate"}))
        with pytest.raises(KernelError, match="AUTHORITY_INPUT_NOT_ELIGIBLE"):
            uow.repositories.chapter_authority.frozen_inputs(project, [target])
        uow.cursor.execute("""SELECT operation.definition_version,count(effect.external_effect_id)
            FROM authority_operation operation JOIN authority_operation_output_asset output USING(operation_id)
            LEFT JOIN authority_external_effect effect USING(operation_id)
            WHERE output.asset_version_id=%s GROUP BY operation.definition_version""", [adjudications[-1]["asset_version_id"]])
        assert uow.cursor.fetchone() == ("2.4.0", 0)
    return {"adjudications": adjudications, "scope": {key: common[key] for key in ("scope_type", "chapter_start", "chapter_end")}}
