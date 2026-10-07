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
from novel_forge.modules.story_planning_runtime.domain import STORY_PLANNING_OPERATION_DEFINITION_REF


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


def _native_world_sample_source(monkeypatch, version, *, reference=False, stage="world_candidates.generate"):
    from dataclasses import asdict
    from unittest.mock import Mock
    from novel_forge.modules.command_kernel.routing_bootstrap import authorization_hash
    from novel_forge.modules.story_planning_runtime import world_sampling
    from novel_forge.modules.story_planning_runtime.world_preparation import PlanningWorldPreparation
    from novel_forge.modules.worldbuilding.production_planning import WorldProductionPolicy
    from novel_forge.storage.authority_asset_store import AuthorityAssetDocument
    from tests.unit.test_story_planning_runtime import _command as planning_command

    request = {"book_run_id": "run", "input_snapshot_id": "snapshot", "accepted_through_chapter": 0,
               "story_state_version_id": "state", "canon_version_id": "canon"}
    command = replace(planning_command("chapter_plan.generate"), world_preparation_request=request,
                      execution_contract_version=version)
    payload = _command_payload(command)

    def document(ref, asset_type, content):
        return AuthorityAssetDocument(command.project_id, ref, "fixture", ref, asset_type, ref + ":v1", 1,
            "ACTIVE", "ELIGIBLE", "CLEAR", authorization_hash(content), content, "2026-10-05T00:00:00Z")

    dependency = document("chapter-group", "planning_generation_candidate", {"chapter": 1})
    inputs = [{"role": "chapter_group_plan", "asset_version_id": dependency.asset_version_id,
               "content_hash": dependency.content_hash, "asset_type": dependency.asset_type}]
    source = document("world_preparation/source-op/source", "world_preparation_source", {"contract": {
        "contract_version": "world-preparation-source.v2", "request": request,
        "policy": asdict(WorldProductionPolicy()), "intent": {}, "world_foundation": {},
        "character_definitions": [], "planning_window": {}, "entity_ids": [],
        "reality": {"project_id": command.project_id, "book_id": command.book_id, "revision_id": "reality",
                    "baseline_kind": "CANON", "chapter_number": 0, "current_state": {}, "foundation_cause_refs": [],
                    **({"epistemic_contract": "world-agency.v2"} if version == "1.21.0" else {})},
    }})
    source_ref = {"asset_version_id": source.asset_version_id, "content_hash": source.content_hash}
    generated = {"disposition": "NO_CANDIDATE", "reason": "No legal action", "candidates": []}
    generation = document("world_preparation/source-op/generation", "world_generation_portfolio",
                          {"contract": {"source": source_ref, "output": generated}})
    generation_ref = {"asset_version_id": generation.asset_version_id, "content_hash": generation.content_hash}
    provider_stage = (PlanningWorldPreparation.generation_stage(source.content["contract"], source_ref, {})
        if stage == "world_candidates.generate" or reference else
        PlanningWorldPreparation.evaluation_stage(source.content["contract"], source_ref, generation.content["contract"], generation_ref, {}))
    context_stage = "world_candidates.generate" if reference else stage
    context = document("world_preparation/context/source-op/" + context_stage, "context_bundle", {
        "project_id": command.project_id, "book_id": command.book_id, "logical_key": command.logical_key,
        "world_preparation": provider_stage.task, "token_budget": provider_stage.task["policy"]["context_token_budget"],
    })
    documents = {item.logical_ref: item for item in (dependency, source, generation, context)}
    query = Mock()
    query.require.side_effect = lambda **kwargs: next(item for item in documents.values()
        if item.project_id == kwargs["project_id"] and
        (item.asset_version_id == kwargs.get("asset_version_id") or item.logical_ref == kwargs.get("logical_ref")))
    monkeypatch.setattr(world_sampling, "AuthorityAssetDocumentRepository", lambda cursor: query)
    binding = {"asset_version_id": "sample:v1", "content_hash": authorization_hash(generated)} if reference else None
    if reference:
        from novel_forge.modules.chapter_quality_authority import reference_subject
        monkeypatch.setattr(reference_subject, "require_reference_subject", lambda *args, **kwargs: {
            **binding, "content": {"source_operation_id": "source-op", "sampled_output": generated,
                "source": source_ref, "context": {"asset_version_id": context.asset_version_id, "content_hash": context.content_hash}},
        })
    cursor = Mock()
    row = ("story_planning.generate", version, payload, inputs, authorization_hash(inputs), inputs)
    cursor.fetchone.side_effect = lambda: row if cursor.execute.call_count == 1 else (1,)
    return cursor, row, binding, query


@pytest.mark.parametrize("version", ["1.16.0", "1.17.0", "1.18.0", "1.19.0", STORY_PLANNING_OPERATION_DEFINITION_REF.rpartition("@")[2]])
@pytest.mark.parametrize("stage,reference", [
    ("world_candidates.generate", False), ("world_candidates.evaluate", False), ("world_candidates.evaluate", True),
])
def test_world_sampling_accepts_current_and_frozen_adjacent_sources(monkeypatch, version, stage, reference):
    from copy import deepcopy
    from novel_forge.modules.story_planning_runtime.world_sampling import _require_world_sample_source
    cursor, row, binding, _ = _native_world_sample_source(monkeypatch, version, stage=stage, reference=reference)
    frozen_row = deepcopy(row)
    frozen = _require_world_sample_source(cursor, project_id="project-1", book_id="book-1",
                                         source_operation_id="source-op", stage=stage, generation_sample=binding)
    assert frozen.command_payload["execution_contract_version"] == version
    assert frozen.stage.name == stage
    assert bool(frozen.derived_context) == reference
    assert frozen.definition_version == ("1.1.0" if reference else "1.0.0")
    assert row == frozen_row


@pytest.mark.parametrize("damage", ["old_version", "source_branch_version", "future_version", "definition", "generator", "book", "repair", "bootstrap", "hash"])
def test_world_sampling_version_compatibility_preserves_source_admission_checks(monkeypatch, damage):
    from novel_forge.modules.story_planning_runtime.world_sampling import _require_world_sample_source
    version = STORY_PLANNING_OPERATION_DEFINITION_REF.rpartition("@")[2]
    cursor, row, _, query = _native_world_sample_source(monkeypatch, version)
    changed = list(row)
    if damage in {"old_version", "source_branch_version", "future_version"}:
        changed[1] = {"old_version": "1.15.0", "source_branch_version": "1.20.0", "future_version": "1.22.0"}[damage]
    elif damage == "definition":
        changed[0] = "other.generate"
    elif damage == "hash":
        changed[4] = "sha256:" + "0" * 64
    else:
        field, value = {"generator": ("generator_operation_name", "book_plan.generate"),
            "book": ("book_id", "another-book"), "repair": ("repair_of_operation_id", "parent"),
            "bootstrap": ("routing_bootstrap_authorization_id", "benchmark-grant")}[damage]
        changed[2][field] = value
    cursor.fetchone.side_effect = lambda: tuple(changed)
    with pytest.raises(KernelError, match="WORLD_SAMPLE_SOURCE_INVALID"):
        _require_world_sample_source(cursor, project_id="project-1", book_id="book-1",
                                     source_operation_id="source-op", stage="world_candidates.generate")
    query.require.assert_not_called()


@pytest.mark.parametrize("damage,code", [
    ("inputs", "WORLD_SAMPLE_INPUT_DRIFT"), ("source", "WORLD_SAMPLE_SOURCE_DRIFT"),
    ("context", "WORLD_SAMPLE_CONTEXT_DRIFT"), ("provenance", "WORLD_SAMPLE_PROVENANCE_INVALID"),
])
def test_current_world_source_still_requires_frozen_inputs_and_native_evidence(monkeypatch, damage, code):
    from novel_forge.modules.story_planning_runtime.world_sampling import _require_world_sample_source
    version = STORY_PLANNING_OPERATION_DEFINITION_REF.rpartition("@")[2]
    cursor, row, _, query = _native_world_sample_source(monkeypatch, version)
    if damage == "inputs":
        row = (*row[:5], [])
    elif damage in {"source", "context"}:
        original_require = query.require.side_effect

        def damaged_document(**kwargs):
            item = original_require(**kwargs)
            if damage == "source" and item.asset_type == "world_preparation_source":
                return replace(item, content={"contract": {**item.content["contract"], "request": {"book_run_id": "other-run"}}})
            if damage == "context" and item.asset_type == "context_bundle":
                return replace(item, content_hash="sha256:" + "0" * 64)
            return item

        query.require.side_effect = damaged_document
    cursor.fetchone.side_effect = lambda: row if cursor.execute.call_count == 1 else (None if damage == "provenance" else (1,))
    with pytest.raises(KernelError) as error:
        _require_world_sample_source(cursor, project_id="project-1", book_id="book-1",
                                     source_operation_id="source-op", stage="world_candidates.generate")
    assert error.value.code == code


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


@pytest.mark.parametrize("field,value", [("contract_version", "world-preparation-source.v1"), ("epistemic_contract", "world-agency.v1")])
def test_current_world_sampling_cannot_reinterpret_historical_source_contract(monkeypatch, field, value):
    from novel_forge.modules.story_planning_runtime.world_sampling import _require_world_sample_source
    cursor, _, _, query = _native_world_sample_source(monkeypatch, "1.21.0")
    original = query.require.side_effect
    def changed(**kwargs):
        document = original(**kwargs)
        if document.asset_type == "world_preparation_source":
            contract = dict(document.content["contract"])
            if field == "epistemic_contract":
                contract["reality"] = {**contract["reality"], field: value}
            else:
                contract[field] = value
            return replace(document, content={"contract": contract})
        return document
    query.require.side_effect = changed
    with pytest.raises(KernelError, match="WORLD_SAMPLE_SOURCE_DRIFT"):
        _require_world_sample_source(cursor, project_id="project-1", book_id="book-1", source_operation_id="source-op", stage="world_candidates.generate")
