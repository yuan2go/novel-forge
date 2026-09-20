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
def test_bootstrap_router_freezes_grant_and_kernel_caps_same_effect_generations(tmp_path, scenario):
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
    expiry = datetime.now(timezone.utc) + timedelta(hours=1)
    grant = {
        "authorization_id": command.routing_bootstrap_authorization_id,
        "reason": "fixture-only Kernel authorization regression", "environment": "validation",
        "book_id": book, "task_type": command.generator_operation_name,
        "logical_key": command.logical_key, "generation_idempotency_key": command.idempotency_key,
        "input_versions_hash": snapshot_hash(dict(command.input_versions)),
        "command_hash": bootstrap_command_hash(_command_payload(command)),
        "candidate_id": candidate.candidate_id, "model_revision": candidate.model_revision,
        "expires_at": expiry.isoformat(), "maximum_calls": 1, "maximum_tokens": 4096,
        "maximum_amount": "0.1", "currency": "USD", "purpose": "BENCHMARK_CHALLENGER",
        "production_eligible": False,
        "campaign": {"campaign_id": "campaign:" + project, "manifest_hash": "sha256:" + "c" * 64,
                     "sample_id": "sample-one", "group_id": "group-one", "partition": "CALIBRATION",
                     "maximum_calls": 1, "maximum_tokens": 4096, "maximum_amount": "0.1",
                     "expires_at": expiry.isoformat()},
    }
    configure_owned_policy(
        database_url=DATABASE_URL, owner="PROVIDER_ROUTING",
        content={"policy_version": "bootstrap-kernel:v1", "reason": "fixture authorization",
                 "task_overrides": [], "bootstrap_authorizations": [grant]},
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

    class BudgetCheckingBinder(_ExternalEffectPepFixturePlanningBinder):
        def execute(self, **kwargs):
            operation, attempt = kwargs["operation_id"], kwargs["attempt_id"]
            stable_key = f"{operation}:{attempt}:fixture-bootstrap"
            _, decision = router.select(composition.gateway.routes["draft"],
                task_type=command.generator_operation_name, project_id=project, work_id=book,
                operation_id=operation, attempt_id=attempt, stable_key=stable_key,
                input_tokens=100, output_tokens=100, trace_id=command.trace_id,
                correlation_id=command.correlation_id, request_input={"fixture": True})
            assert decision["status"] == "BENCHMARK_SELECTED"
            assert decision["production_eligible"] is False
            assert decision["selected"]["benchmark"]["sample_count"] == 0
            context = EffectCommandContext(operation, project, principal.principal_id, command.trace_id, command.correlation_id)
            effect = plan_external_effect(DATABASE_URL, context,
                effect_type="model.invoke", provider="production_execution_gateway",
                capability="model.book_plan.generate", stable_idempotency_key=stable_key,
                request_payload={"stage": command.generator_operation_name, "max_output_tokens": 100,
                    "input": {"fixture": True}, "_production_execution": {"book_id": book,
                    "capability_runtime": {"routing_decision": decision}}},
                max_attempts=4, reversible=False, model_id=candidate.model, completion_policy="synchronous_final")
            request = BudgetReservationRequest(operation, effect["external_effect_id"], project,
                f"budget:{stable_key}:generation:1", candidate.provider, "USD", ".001", 200,
                model_id=candidate.model, work_id=book)
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
                    project_id=project, actual_amount=".0001", actual_tokens=30, evidence={"fixture": True})
                assert settled["status"] == "SETTLED"
                assert reserve_provider_budget(DATABASE_URL, request)["replayed"]
            retry = replace(request, stable_idempotency_key=f"budget:{stable_key}:generation:3")
            code = "ROUTING_BOOTSTRAP_QUOTA_EXCEEDED" if scenario == "success" else "ROUTING_BOOTSTRAP_RECONCILIATION_REQUIRED"
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
              "campaign": {**grant["campaign"], "sample_id": "sample-two"}}
    configure_owned_policy(
        database_url=DATABASE_URL, owner="PROVIDER_ROUTING",
        content={"policy_version": "bootstrap-kernel:v2", "reason": "fixture second sample",
                 "task_overrides": [], "bootstrap_authorizations": [second]},
        project_id=project, workspace_id=workspace, idempotency_key=f"{project}:policy-two",
        trace_id=command.trace_id, correlation_id=command.correlation_id,
        application_build_id="bootstrap-kernel-test", commit_sha=RELEASE_SHA, principal=principal,
    )
    campaign_error = ("ROUTING_CAMPAIGN_QUOTA_EXCEEDED" if scenario == "success"
                      else "ROUTING_CAMPAIGN_RECONCILIATION_REQUIRED")
    assert application.generate(command, principal=principal).candidate_asset_version_id
    report = PostgresRoutingRegistry(DATABASE_URL).campaign(project_id=project, campaign_id="campaign:" + project)
    assert report["usage"]["calls_used_or_reserved"] == 1
    assert report["usage"]["conservative_tokens"] == 30
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
