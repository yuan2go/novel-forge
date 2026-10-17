from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from novel_forge.modules.authority_handler_runtime.policy_commands import (
    configure_owned_policy,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.routing_bootstrap import bootstrap_command_hash
from novel_forge.modules.story_planning_runtime.application import _command_payload
from novel_forge.modules.hierarchical_planning import PlanContractType
from novel_forge.modules.production_execution.cost_routing import snapshot_hash
from novel_forge.modules.production_execution.routing_catalog import deepseek_candidates
from novel_forge.modules.story_design_authority import (
    DesignTransition,
    StoryDesignTransitionCommand,
    scripted_qualification,
)
from novel_forge.modules.story_planning_runtime import (
    GENERATOR_INPUT_ROLES,
    PlanningGenerationStatus,
    StoryPlanningEvaluationCommand,
    StoryPlanningGenerationApplication,
    StoryPlanningGenerationCommand,
)
from novel_forge.modules.story_planning_runtime.execution import _planning_repair_routing_lineage
from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    seed_authority_project_book,
)
from tests.integration.test_core_functional_loops_postgres import (
    RELEASE_SHA,
    _ExternalEffectPepFixturePlanningBinder,
    _principal,
    _seed_inputs,
)


def test_bootstrap_candidate_is_frozen_reviewable_and_permanently_ineligible():
    ensure_migrated()
    project_id = f"planning-bootstrap:{uuid4().hex}"
    workspace_id, book_id = f"workspace:{project_id}", f"book:{project_id}"
    seed_authority_project_book(
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
    )
    inputs = _seed_inputs(project_id, book_id, target_chapter_count=6)
    principal = _principal(project_id)
    binder = _ExternalEffectPepFixturePlanningBinder(target_chapter_count=6)
    binder.resolver = SimpleNamespace(environment="validation")
    application = StoryPlanningGenerationApplication(
        DATABASE_URL,
        execution_binder=binder,
        application_build_id="bootstrap-isolation-test",
        commit_sha=RELEASE_SHA,
        allow_scripted_evaluation_fixture=True,
    )
    command = StoryPlanningGenerationCommand(
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
        actor_id=principal.principal_id,
        generator_operation_name="book_plan.generate",
        logical_key="book:bootstrap",
        input_versions={
            role: inputs[role] for role in GENERATOR_INPUT_ROLES["book_plan.generate"]
        },
        idempotency_key=f"{project_id}:generate",
        trace_id=f"trace:{project_id}",
        correlation_id=f"correlation:{project_id}",
        routing_bootstrap_authorization_id="bootstrap:one",
    )
    candidate = deepseek_candidates(available=True)[0]
    authorization = {
        "authorization_id": "bootstrap:one",
        "reason": "bounded candidate isolation test",
        "environment": "validation",
        "book_id": book_id,
        "task_type": "book_plan.generate",
        "logical_key": command.logical_key,
        "generation_idempotency_key": command.idempotency_key,
        "input_versions_hash": snapshot_hash(dict(command.input_versions)),
        "command_hash": bootstrap_command_hash(_command_payload(command)),
        "producer_contract_hash": snapshot_hash({"fixture_prompt": "v1"}),
        "candidate_id": candidate.candidate_id,
        "model_revision": candidate.model_revision,
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "maximum_calls": 1,
        "maximum_tokens": 4096,
        "maximum_amount": "0.1",
        "currency": "USD",
        "purpose": "BENCHMARK_CHALLENGER",
        "production_eligible": False,
    }
    configuration = {
        "policy_version": "bootstrap-isolation:v1",
        "reason": "explicit bounded validation",
        "task_overrides": [],
        "bootstrap_authorizations": [authorization],
    }

    def configure(policy, key):
        return configure_owned_policy(
            database_url=DATABASE_URL,
            owner="PROVIDER_ROUTING",
            content=policy,
            project_id=project_id,
            workspace_id=workspace_id,
            idempotency_key=key,
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
            application_build_id="bootstrap-isolation-test",
            commit_sha=RELEASE_SHA,
            principal=principal,
        )

    configure(configuration, "configure:v1")
    generated = application.generate(command, principal=principal)
    assert generated.status is PlanningGenerationStatus.EVALUATION_PENDING
    frozen = application.frozen_generation_command(generated.generation_operation_id)
    snapshot = frozen["routing_bootstrap_authorization"]
    assert snapshot["authorization"] == authorization
    document = AuthorityAssetQuery(DATABASE_URL).require(
        project_id=project_id,
        asset_version_id=generated.candidate_asset_version_id,
    )
    assert document.content["routing_eligibility"] == "BENCHMARK_ONLY"
    assert document.content["routing_bootstrap_authorization"] == snapshot
    assert document.eligibility == "INELIGIBLE"
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            "SELECT COUNT(*) FROM authority_narrative_design_qualification WHERE generation_operation_id=%s",
            [generated.generation_operation_id],
        )
        assert uow.cursor.fetchone()[0] == 0
    configure(
        {
            **configuration,
            "policy_version": "bootstrap-isolation:v2",
            "bootstrap_authorizations": [],
        },
        "configure:v2",
    )
    replay = application.generate(command, principal=principal)
    assert replay.replayed
    assert replay.candidate_asset_version_id == generated.candidate_asset_version_id
    assert (
        application.frozen_generation_command(generated.generation_operation_id)
        == frozen
    )
    with pytest.raises(KernelError, match="PLANNING_GENERATION_COMMAND_IDENTITY_DRIFT"):
        application.generate(
            replace(command, routing_bootstrap_authorization_id="bootstrap:forged"),
            principal=principal,
        )

    evaluator = replace(principal, principal_id="independent-fixture-evaluator")
    evaluated = application.evaluate_candidate(
        StoryPlanningEvaluationCommand(
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            actor_id=evaluator.principal_id,
            candidate_asset_version_id=document.asset_version_id,
            generation_operation_id=generated.generation_operation_id,
            generator_operation_name=command.generator_operation_name,
            candidate_content_hash=document.content_hash,
            evaluator_execution_class="SCRIPTED_FIXTURE",
            idempotency_key="evaluate:bootstrap",
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
            evaluation=scripted_qualification(command.generator_operation_name),
        ),
        principal=evaluator,
        transition_principal=principal,
    )
    assert evaluated.status is PlanningGenerationStatus.EVALUATION_PENDING
    retained = AuthorityAssetQuery(DATABASE_URL).require(
        project_id=project_id,
        asset_version_id=document.asset_version_id,
    )
    assert retained.eligibility == "INELIGIBLE"
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            "SELECT evaluator_execution_class,qualification_status FROM authority_narrative_design_qualification WHERE generation_operation_id=%s",
            [generated.generation_operation_id],
        )
        qualifications = uow.cursor.fetchall()
    assert qualifications and set(qualifications) == {("SCRIPTED_FIXTURE", "PASS")}
    for action in (application.approve_candidate, application.activate_candidate):
        with pytest.raises(KernelError, match="PLANNING_BENCHMARK_ONLY"):
            action(
                document.asset_version_id,
                principal=principal,
                idempotency_key="forbidden:promotion",
                trace_id=command.trace_id,
                correlation_id=command.correlation_id,
            )
    with pytest.raises(KernelError, match="PLANNING_BENCHMARK_ONLY"):
        application.planning.bind_active_contract(
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            asset_version_id=document.asset_version_id,
            contract_type=PlanContractType.BOOK,
            actor_id=principal.principal_id,
            principal=principal,
            idempotency_key="forbidden:direct-binding",
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
        )
    with pytest.raises(
        KernelError, match="PLANNING_GENERATION_INPUT_AUTHORITY_INVALID"
    ):
        application.generate(
            replace(
                command,
                routing_bootstrap_authorization_id="",
                idempotency_key="forbidden:input",
                input_versions={
                    **dict(command.input_versions),
                    "creative_foundation": document.asset_version_id,
                },
            ),
            principal=principal,
        )
    with pytest.raises(KernelError, match="PLANNING_BENCHMARK_ONLY"):
        application.generate(
            replace(
                command,
                routing_bootstrap_authorization_id="",
                idempotency_key="forbidden:repair-input",
                repair_of_candidate_id=document.asset_version_id,
                repair_number=1,
                repair_reason="cannot promote benchmark evidence by repair",
            ),
            principal=principal,
        )
    for transition in (
        DesignTransition.QUALIFY,
        DesignTransition.APPROVE,
        DesignTransition.ACTIVATE,
    ):
        with pytest.raises(KernelError, match="PLANNING_BENCHMARK_ONLY"):
            application.story_design.transition(
                StoryDesignTransitionCommand(
                    project_id=project_id,
                    workspace_id=workspace_id,
                    actor_id=principal.principal_id,
                    trace_id=command.trace_id,
                    correlation_id=command.correlation_id,
                    idempotency_key=f"forbidden:{transition.value}",
                    asset_version_id=document.asset_version_id,
                    content_hash=document.content_hash,
                    logical_key=command.logical_key,
                    generator_operation_name=command.generator_operation_name,
                    transition=transition,
                    planning_scope=command.planning_scope,
                    expected_version=int(evaluated.story_design_state["version"]),
                ),
                principal=principal,
            )


def test_semantic_planning_repair_retains_real_authority_candidate_lineage(monkeypatch):
    from novel_forge.modules.story_planning_runtime import application as planning_application

    ensure_migrated()
    project_id = f"planning-semantic-repair:{uuid4().hex}"
    workspace_id, book_id = f"workspace:{project_id}", f"book:{project_id}"
    seed_authority_project_book(project_id=project_id, workspace_id=workspace_id, book_id=book_id)
    inputs = _seed_inputs(project_id, book_id, target_chapter_count=6)
    principal = _principal(project_id)
    evaluations = []

    def independent_fixture_evaluation(generator, **profile_options):
        result = scripted_qualification(generator, **profile_options)
        if not evaluations:
            criterion = result["evaluations"][0]["criteria"][0]
            criterion.update(verdict="FAIL", repair_directive="Make the causal conflict sustainable")
        evaluations.append(result)
        return result

    monkeypatch.setattr(planning_application, "scripted_qualification", independent_fixture_evaluation)
    application = StoryPlanningGenerationApplication(
        DATABASE_URL, execution_binder=_ExternalEffectPepFixturePlanningBinder(target_chapter_count=6),
        application_build_id="semantic-repair-lineage-test", commit_sha=RELEASE_SHA,
        allow_scripted_evaluation_fixture=True,
    )
    command = StoryPlanningGenerationCommand(
        project_id=project_id, workspace_id=workspace_id, book_id=book_id,
        actor_id=principal.principal_id, generator_operation_name="book_plan.generate",
        logical_key="book:semantic-repair", input_versions={
            role: inputs[role] for role in GENERATOR_INPUT_ROLES["book_plan.generate"]
        }, idempotency_key=f"{project_id}:generate", trace_id=f"trace:{project_id}",
        correlation_id=f"correlation:{project_id}",
    )
    generated = application.generate(command, principal=principal)
    assert generated.status is PlanningGenerationStatus.APPROVAL_PENDING
    assert len(evaluations) == 2
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """SELECT generation.operation_id,generation.candidate_asset_version_id,
                      operation.causation_operation_id,operation.command_payload->'payload'
               FROM authority_story_planning_generation generation
               JOIN authority_operation operation USING(operation_id)
               WHERE generation.project_id=%s AND generation.logical_key=%s ORDER BY generation.repair_number""",
            [project_id, command.logical_key],
        )
        rows = uow.cursor.fetchall()
        uow.cursor.execute(
            "SELECT COUNT(*) FROM authority_narrative_design_qualification WHERE project_id=%s AND qualification_status='FAIL'",
            [project_id],
        )
        assert uow.cursor.fetchone()[0] >= 1
    assert len(rows) == 2
    original, repaired = rows
    assert repaired[2] == original[0]
    assert repaired[3]["repair_of_candidate_id"] == original[1]
    assert not repaired[3].get("repair_of_operation_id")
    lineage = _planning_repair_routing_lineage(
        DATABASE_URL, project_id=project_id, book_id=book_id,
        generator_operation_name=command.generator_operation_name,
        operation_id=repaired[0], repair_of_operation_id="",
        repair_of_candidate_id=original[1],
    )
    assert lineage == (original[0], repaired[0])
    replay = application.generate(command, principal=principal)
    assert replay.candidate_asset_version_id == generated.candidate_asset_version_id
    assert len(evaluations) == 2
