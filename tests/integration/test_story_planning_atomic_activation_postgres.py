from __future__ import annotations

from uuid import uuid4

import pytest

from novel_forge.modules.story_planning_runtime import (
    GENERATOR_INPUT_ROLES,
    PlanningGenerationStatus,
    StoryPlanningGenerationApplication,
    StoryPlanningGenerationCommand,
)
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


def test_story_design_activation_and_typed_binding_rollback_and_retry_together() -> (
    None
):
    ensure_migrated()
    suffix = uuid4().hex
    project_id = f"atomic-planning-activation:{suffix}"
    workspace_id = f"workspace:{project_id}"
    book_id = f"book:{project_id}"
    seed_authority_project_book(
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
    )
    inputs = _seed_inputs(project_id, book_id, target_chapter_count=6)
    principal = _principal(project_id)
    application = StoryPlanningGenerationApplication(
        DATABASE_URL,
        execution_binder=_ExternalEffectPepFixturePlanningBinder(
            target_chapter_count=6
        ),
        application_build_id="atomic-planning-activation-test",
        commit_sha=RELEASE_SHA,
        allow_scripted_evaluation_fixture=True,
    )
    command = StoryPlanningGenerationCommand(
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
        actor_id=principal.principal_id,
        generator_operation_name="book_plan.generate",
        logical_key="book:atomic-main",
        input_versions={
            role: inputs[role] for role in GENERATOR_INPUT_ROLES["book_plan.generate"]
        },
        idempotency_key=f"{project_id}:generate",
        trace_id=f"trace:{project_id}",
        correlation_id=f"correlation:{project_id}",
    )
    generated = application.generate(command, principal=principal)
    assert generated.status is PlanningGenerationStatus.APPROVAL_PENDING
    application.approve_candidate(
        generated.candidate_asset_version_id,
        principal=principal,
        idempotency_key=f"{command.idempotency_key}:approve",
        trace_id=command.trace_id,
        correlation_id=command.correlation_id,
    )

    def fail_between_projections(point: str) -> None:
        if point == "after_story_design_activation_before_binding":
            raise RuntimeError("injected atomic activation rollback")

    application.planning.fault_injector = fail_between_projections
    activation_key = f"{command.idempotency_key}:activate"
    with pytest.raises(RuntimeError, match="injected atomic activation rollback"):
        application.activate_candidate(
            generated.candidate_asset_version_id,
            principal=principal,
            idempotency_key=activation_key,
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
        )

    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT state.lifecycle, state.approval,
                   COUNT(active.asset_version_id), COUNT(binding.binding_id),
                   COUNT(transition.transition_operation_id)
            FROM authority_story_design_version_state AS state
            LEFT JOIN authority_story_design_active_version AS active
              ON active.project_id=state.project_id
             AND active.asset_version_id=state.asset_version_id
            LEFT JOIN story_plan_binding AS binding
              ON binding.project_id=state.project_id
             AND binding.asset_version_id=state.asset_version_id
            LEFT JOIN authority_story_design_transition AS transition
              ON transition.project_id=state.project_id
             AND transition.asset_version_id=state.asset_version_id
             AND transition.transition_type='ACTIVATE'
            WHERE state.project_id=%s AND state.asset_version_id=%s
            GROUP BY state.lifecycle, state.approval
            """,
            [project_id, generated.candidate_asset_version_id],
        )
        rolled_back = uow.cursor.fetchone()
        uow.cursor.execute(
            """
            SELECT status, COUNT(*) OVER ()
            FROM authority_operation
            WHERE idempotency_scope='project:story-design-transition'
              AND idempotency_key=%s
            """,
            [f"{activation_key}:story-design"],
        )
        prepared = uow.cursor.fetchone()
    assert rolled_back == ("MATERIALIZED", "APPROVED", 0, 0, 0)
    assert prepared == ("SUCCEEDED", 1)

    def lose_committed_response(point: str) -> None:
        if point == "after_operation_completion_before_response":
            raise RuntimeError("injected committed response loss")

    application.planning.fault_injector = lose_committed_response
    with pytest.raises(RuntimeError, match="injected committed response loss"):
        application.activate_candidate(
            generated.candidate_asset_version_id,
            principal=principal,
            idempotency_key=activation_key,
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
        )

    application.planning.fault_injector = None
    activated = application.activate_candidate(
        generated.candidate_asset_version_id,
        principal=principal,
        idempotency_key=activation_key,
        trace_id=command.trace_id,
        correlation_id=command.correlation_id,
    )
    replay = application.activate_candidate(
        generated.candidate_asset_version_id,
        principal=principal,
        idempotency_key=activation_key,
        trace_id=command.trace_id,
        correlation_id=command.correlation_id,
    )

    assert activated["story_design"]["lifecycle"] == "ACTIVE"
    assert activated["planning_binding"]["replayed"] is True
    assert activated["planning_binding"]["asset_version_id"] == (
        generated.candidate_asset_version_id
    )
    assert replay["planning_binding"]["replayed"] is True
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT COUNT(DISTINCT active.asset_version_id),
                   COUNT(DISTINCT binding.binding_id),
                   COUNT(DISTINCT transition.transition_operation_id),
                   COUNT(DISTINCT outbox.outbox_id) FILTER (
                     WHERE outbox.topic='story_design.transitioned'
                       AND outbox.payload->>'transition'='ACTIVATE'
                   ),
                   COUNT(DISTINCT outbox.outbox_id) FILTER (
                     WHERE outbox.topic='story_plan.bound'
                   )
            FROM authority_story_design_version_state AS state
            LEFT JOIN authority_story_design_active_version AS active
              ON active.project_id=state.project_id
             AND active.asset_version_id=state.asset_version_id
            LEFT JOIN story_plan_binding AS binding
              ON binding.project_id=state.project_id
             AND binding.asset_version_id=state.asset_version_id
            LEFT JOIN authority_story_design_transition AS transition
              ON transition.project_id=state.project_id
             AND transition.asset_version_id=state.asset_version_id
             AND transition.transition_type='ACTIVATE'
            LEFT JOIN outbox_event AS outbox
              ON outbox.project_id=state.project_id
             AND outbox.payload->>'asset_version_id'=state.asset_version_id
             AND outbox.topic IN (
               'story_design.transitioned', 'story_plan.bound'
             )
            WHERE state.project_id=%s AND state.asset_version_id=%s
            """,
            [project_id, generated.candidate_asset_version_id],
        )
        committed = uow.cursor.fetchone()
    assert committed == (1, 1, 1, 1, 1)
