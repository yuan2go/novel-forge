from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_design_authority import (
    DesignTransition,
    GENERATOR_CATALOG,
    PlanningScope,
    StoryDesignTransitionCommand,
)
from novel_forge.modules.story_design_authority.application import (
    PostgresStoryDesignAssetAuthority,
)
from novel_forge.modules.story_planning_runtime import (
    GENERATOR_INPUT_ROLES,
    PlanningGenerationResult,
    PlanningGenerationStatus,
    StoryPlanningGenerationCommand,
)
from novel_forge.modules.story_planning_runtime.application import (
    StoryPlanningGenerationApplication,
    _command_from_payload,
    _command_payload,
)


def _command() -> StoryPlanningGenerationCommand:
    return StoryPlanningGenerationCommand(
        project_id="project-1",
        workspace_id="workspace-1",
        book_id="book-1",
        actor_id="operator:planner",
        generator_operation_name="book_plan.generate",
        logical_key="book:benchmark",
        input_versions={
            role: f"asset:{role}:v1"
            for role in GENERATOR_INPUT_ROLES["book_plan.generate"]
        },
        idempotency_key="generation:benchmark",
        trace_id="trace:benchmark",
        correlation_id="correlation:benchmark",
        routing_bootstrap_authorization_id="bootstrap:one",
    )


def _principal() -> Principal:
    return Principal(
        principal_id="operator:planner",
        principal_type=PrincipalType.LOCAL_OPERATOR,
        permissions=frozenset({"story_design.authority.execute"}),
        project_scope=frozenset({"project-1"}),
        authentication_source="test",
    )


def test_bootstrap_reference_roundtrips_without_changing_historical_commands():
    command = _command()
    payload = _command_payload(command)
    assert payload["routing_bootstrap_authorization_id"] == "bootstrap:one"
    assert _command_from_payload(payload) == command
    historical = _command_payload(
        replace(command, routing_bootstrap_authorization_id="")
    )
    assert "routing_bootstrap_authorization_id" not in historical
    assert _command_payload(_command_from_payload(historical)) == historical
    with pytest.raises(ValueError, match="bootstrap"):
        replace(command, auto_approve_low_risk=True)


def test_world_sampling_api_preserves_scope_and_trusted_actor(monkeypatch):
    from dataclasses import asdict
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from novel_forge.api.models import product_model_map
    from novel_forge.api.routers import book_authority
    from novel_forge.api.routers.context import ProductRouterContext
    from novel_forge.modules.story_planning_runtime import world_sampling

    principal = replace(_principal(), permissions=frozenset({"story_planning.authority.execute"}))
    captured = []

    def prepared(app, command, *, principal):
        captured.append((command, principal))
        return {"status": "PREPARED_NO_PROVIDER_CALL", "provider_calls": 0}

    monkeypatch.setattr(world_sampling, "prepare_world_sample", prepared)
    monkeypatch.setattr(book_authority, "build_trusted_principal_resolver",
                        lambda: SimpleNamespace(resolve_api_principal=lambda **_: principal))
    app = FastAPI()
    app.include_router(book_authority.create_router(ProductRouterContext(app_settings=SimpleNamespace(), models=product_model_map(),
        services=SimpleNamespace(book_production=SimpleNamespace(planning=SimpleNamespace())))))
    command = world_sampling.WorldProviderSampleCommand("project-1", "book-1", "caller-string", "source-op",
        "world_candidates.generate", "unapproved-grant", "preflight-key")
    with TestClient(app) as client:
        response = client.post("/product/production/book-authority/books/book-1/world-provider-samples?dry_run=true", json=asdict(command))
        assert response.status_code == 200 and response.json()["provider_calls"] == 0
        rejected = client.post("/product/production/book-authority/books/another-book/world-provider-samples?dry_run=true", json=asdict(command))
        assert rejected.status_code != 200
    assert len(captured) == 1 and captured[0][0].actor_id == principal.principal_id
    assert captured[0][1] is principal


@pytest.mark.parametrize("operation_status,effect_status,dispatch_status,replaceable", [
    ("SUCCEEDED", None, None, False), ("FAILED_FINAL", "UNKNOWN", None, False),
    ("FAILED_FINAL", "FAILED_FINAL", "SUCCEEDED", False),
    ("FAILED_FINAL", "FAILED_FINAL", "FAILED_FINAL", True), ("FAILED_FINAL", None, None, True),
])
def test_world_sample_replacement_requires_proven_terminal_failure(operation_status, effect_status, dispatch_status, replaceable):
    from unittest.mock import Mock
    from novel_forge.modules.story_planning_runtime.world_sampling import WorldProviderSampleCommand, require_world_sample_predecessor

    command = WorldProviderSampleCommand("project", "book", "operator", "source", "world_candidates.generate", "new-grant", "new-key", "prior")
    grant = {"campaign": {"campaign_id": "campaign", "sample_id": "sample"}, "candidate_id": "flash", "model_revision": "revision"}
    payload = {"world_sampling": {"source_operation_id": "source"}, "input_versions": [{"asset_version_id": "input", "content_hash": "hash"}],
               "routing_bootstrap_authorization": {"authorization": grant}}
    rows = [[("prior", operation_status, "operator", "old-key", payload)], [("effect", effect_status)] if effect_status else []]
    if dispatch_status:
        rows.append([(dispatch_status,)])
    cursor = Mock()
    cursor.fetchall.side_effect = rows
    if replaceable:
        require_world_sample_predecessor(cursor, command=command, payload=payload)
    else:
        with pytest.raises(KernelError, match="WORLD_SAMPLE_PREDECESSOR_NOT_REPLACEABLE"):
            require_world_sample_predecessor(cursor, command=command, payload=payload)


def test_native_planning_api_binds_authorization_reference_and_trusted_actor(
    monkeypatch,
):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from novel_forge.api.models import product_model_map
    from novel_forge.api.routers import book_authority
    from novel_forge.api.routers.context import ProductRouterContext

    principal = _principal()
    captured = []

    def generate(command, *, principal):
        captured.append((command, principal))
        return PlanningGenerationResult(
            "operation:one",
            "candidate:v1",
            PlanningGenerationStatus.EVALUATION_PENDING,
            {"qualification": "STRUCTURALLY_VALID"},
        )

    monkeypatch.setattr(
        book_authority,
        "build_trusted_principal_resolver",
        lambda: SimpleNamespace(resolve_api_principal=lambda **_: principal),
    )
    application = FastAPI()
    application.include_router(
        book_authority.create_router(
            ProductRouterContext(
                app_settings=SimpleNamespace(),
                models=product_model_map(),
                services=SimpleNamespace(
                    book_production=SimpleNamespace(
                        planning=SimpleNamespace(generate=generate)
                    )
                ),
            )
        )
    )
    with TestClient(application) as client:
        response = client.post(
            "/product/production/book-authority/books/book-1/planning-generations",
            json=_command_payload(_command()),
        )
    assert response.status_code == 200, response.text
    assert captured[0][0].routing_bootstrap_authorization_id == "bootstrap:one"
    assert captured[0][0].actor_id == principal.principal_id
    assert captured[0][0].auto_approve_low_risk is False
    assert captured[0][1] is principal


def test_bootstrap_generation_stops_before_automatic_evaluator():
    application = object.__new__(StoryPlanningGenerationApplication)
    advanced = PlanningGenerationResult(
        "operation:one",
        "candidate:v1",
        PlanningGenerationStatus.EVALUATION_PENDING,
        {"qualification": "STRUCTURALLY_VALID"},
    )
    result = application._evaluate_pending_if_required(
        advanced=advanced,
        generation_command=_command(),
        principal=_principal(),
    )
    assert result is advanced


@pytest.mark.parametrize("environment", ["production", ""])
def test_bootstrap_generation_rejects_nonvalidation_even_before_replay(environment):
    application = object.__new__(StoryPlanningGenerationApplication)
    application.execution_binder = SimpleNamespace(
        resolver=SimpleNamespace(environment=environment)
    )
    principal = replace(
        _principal(), permissions=frozenset({"story_planning.authority.execute"})
    )
    with pytest.raises(KernelError, match="ROUTING_BOOTSTRAP_ENVIRONMENT_FORBIDDEN"):
        application.generate(_command(), principal=principal)


def test_bootstrap_qualified_candidate_never_becomes_eligible_or_approval_pending():
    application = object.__new__(StoryPlanningGenerationApplication)
    application.story_design = SimpleNamespace(
        require=lambda **_: {
            "lifecycle": "MATERIALIZED",
            "qualification": "STRUCTURALLY_VALID",
            "approval": "NOT_REQUESTED",
            "version": 3,
        }
    )
    application._require_narrative_qualification_summary = lambda **_: {
        "status": "PASS"
    }
    recorded = []
    application._update_generation_status = lambda *args: recorded.append(args)
    result = application._advance_candidate(
        operation_id="operation:one",
        candidate_asset_version_id="candidate:v1",
        candidate_content_hash="sha256:" + "a" * 64,
        command=_command(),
        principal=_principal(),
        replayed=False,
        definition=GENERATOR_CATALOG["book_plan.generate"],
    )
    assert result.status is PlanningGenerationStatus.EVALUATION_PENDING
    assert result.story_design_state["qualification"] == "STRUCTURALLY_VALID"
    assert recorded == [("operation:one", "EVALUATION_PENDING")]


@pytest.mark.parametrize(
    "transition",
    [
        DesignTransition.QUALIFY,
        DesignTransition.SUBMIT_APPROVAL,
        DesignTransition.APPROVE,
        DesignTransition.ACTIVATE,
    ],
)
def test_story_design_owner_rejects_bootstrap_promotion(monkeypatch, transition):
    from novel_forge.storage.authority_asset_store import AuthorityAssetQuery

    monkeypatch.setattr(
        AuthorityAssetQuery,
        "require",
        lambda *_args, **_kwargs: SimpleNamespace(
            content={"routing_eligibility": "BENCHMARK_ONLY"}
        ),
    )
    application = object.__new__(PostgresStoryDesignAssetAuthority)
    application.database_url = "postgresql://unused"
    command = StoryDesignTransitionCommand(
        project_id="project-1",
        workspace_id="workspace-1",
        actor_id="operator:planner",
        trace_id="trace:one",
        correlation_id="correlation:one",
        idempotency_key="transition:one",
        asset_version_id="candidate:v1",
        content_hash="sha256:" + "a" * 64,
        logical_key="book:benchmark",
        generator_operation_name="book_plan.generate",
        transition=transition,
        planning_scope=PlanningScope.BOOK,
        expected_version=3,
    )
    with pytest.raises(KernelError, match="PLANNING_BENCHMARK_ONLY"):
        application.prepare_transition(command, principal=_principal())
