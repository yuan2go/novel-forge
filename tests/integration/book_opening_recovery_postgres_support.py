from __future__ import annotations

from dataclasses import dataclass
from types import MethodType
from unittest.mock import patch

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.book_authority import (
    BookProductionInputResolver,
    OpenBookProductionRequest,
    PostgresBookOpeningApplication,
)
from novel_forge.modules.command_kernel.cancellation import (
    CancelCommand,
    request_cancellation,
    resolve_cancellation,
)
from novel_forge.modules.command_kernel.attempt_runtime import (
    WorkerLeaseCommand,
    expire_attempt_lease,
)
from novel_forge.modules.runtime_job import RuntimeJobAuthority, RuntimeJobClaim
from novel_forge.modules.story_planning_runtime import (
    GENERATOR_INPUT_ROLES,
    PostgresNarrativeSearchApplication,
    StoryPlanningEvaluationCommand,
    StoryPlanningGenerationApplication,
    StoryPlanningGenerationCommand,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.workers.book_authority import execute_book_opening_claim
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    identifier,
    seed_authority_project_book,
)
from tests.integration.test_core_functional_loops_postgres import (
    RELEASE_SHA,
    _ExternalEffectPepFixturePlanningBinder,
    _principal,
    _seed_inputs,
)


class SimulatedBookOpeningProcessLoss(BaseException):
    """Cross the process boundary without invoking Exception recovery handlers."""


class _CrashBeforeExternalEffectPort:
    """Stop an admitted Evaluation Attempt before an ExternalEffect is planned."""

    production_execution_gateway_backed = True
    external_effect_backed = True

    def evaluate(self, *_args: object, **_kwargs: object) -> object:
        raise SimulatedBookOpeningProcessLoss("semantic evaluator process disappeared")


@dataclass(frozen=True, slots=True)
class LegacyBookOpeningOrphan:
    opening: PostgresBookOpeningApplication
    planning: StoryPlanningGenerationApplication
    principal: Principal
    evaluator: Principal
    opening_run_id: str
    runtime_job_id: str
    outer_claim: RuntimeJobClaim
    evaluation_command: StoryPlanningEvaluationCommand
    evaluation_operation_id: str
    evaluation_attempt_id: str
    evaluation_lease_id: str
    project_id: str

    def cross_layer_state(self) -> tuple[object, ...]:
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT opening.lifecycle,
                       runtime_job.status,
                       runtime_attempt.status,
                       runtime_lease.status,
                       runtime_lease.lease_expires_at < NOW(),
                       operation.status,
                       attempt.status,
                       lease.status,
                       (SELECT COUNT(*)
                        FROM authority_external_effect AS effect
                        WHERE effect.operation_id=operation.operation_id)
                FROM authority_book_opening_run AS opening
                JOIN authority_runtime_job AS runtime_job
                  ON runtime_job.runtime_job_id=%s
                 AND runtime_job.subject_id=opening.opening_run_id
                JOIN authority_runtime_job_attempt AS runtime_attempt
                  ON runtime_attempt.attempt_id=runtime_job.current_attempt_id
                JOIN authority_runtime_job_lease AS runtime_lease
                  ON runtime_lease.attempt_id=runtime_attempt.attempt_id
                 AND runtime_lease.fencing_token=runtime_job.current_fencing_token
                JOIN authority_operation AS operation
                  ON operation.operation_id=%s
                JOIN authority_attempt AS attempt
                  ON attempt.attempt_id=%s
                 AND attempt.operation_id=operation.operation_id
                JOIN authority_lease_acquisition AS lease
                  ON lease.lease_id=%s
                 AND lease.attempt_id=attempt.attempt_id
                WHERE opening.opening_run_id=%s
                """,
                [
                    self.runtime_job_id,
                    self.evaluation_operation_id,
                    self.evaluation_attempt_id,
                    self.evaluation_lease_id,
                    self.opening_run_id,
                ],
            )
            row = uow.cursor.fetchone()
        assert row is not None
        return tuple(row)


def create_legacy_book_opening_orphan() -> LegacyBookOpeningOrphan:
    """Reproduce the pre-closure orphan through current application paths.

    Direct SQL is used only to advance the test database clock boundary. All
    business transitions, Attempt lease expiry, and terminal cancellation use
    their existing Authority applications.
    """

    project_id = identifier("book-opening-recovery-project")
    workspace_id = identifier("book-opening-recovery-workspace")
    book_id = identifier("book-opening-recovery-book")
    seed_authority_project_book(
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
    )
    principal = _principal(project_id)
    evaluator = Principal(
        principal_id=f"book-opening-recovery-evaluator:{project_id}",
        principal_type=PrincipalType.LOCAL_OPERATOR,
        permissions=frozenset({"narrative_design.evaluate"}),
        project_scope=frozenset({project_id}),
        authentication_source="book-opening-recovery-regression",
    )
    generic = _seed_inputs(project_id, book_id)
    planning = StoryPlanningGenerationApplication(
        DATABASE_URL,
        execution_binder=_ExternalEffectPepFixturePlanningBinder(),
        application_build_id="book-opening-recovery-regression",
        commit_sha=RELEASE_SHA,
        semantic_evaluation_execution_port=_CrashBeforeExternalEffectPort(),
        narrative_evaluator_principal=evaluator,
    )

    # Materialize the exact pending BookPlan candidate without allowing the
    # convenience generate() call to perform its semantic evaluation inline.
    original_evaluate_pending = planning._evaluate_pending_if_required

    def leave_evaluation_pending(
        _self: StoryPlanningGenerationApplication, **values: object
    ) -> object:
        return values["advanced"]

    planning._evaluate_pending_if_required = MethodType(
        leave_evaluation_pending, planning
    )
    opening_idempotency_key = f"{project_id}:open-book"
    generation_command = StoryPlanningGenerationCommand(
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
        actor_id=principal.principal_id,
        generator_operation_name="book_plan.generate",
        logical_key="book:main",
        input_versions={
            role: generic[role]
            for role in GENERATOR_INPUT_ROLES["book_plan.generate"]
        },
        idempotency_key=(
            f"{opening_idempotency_key}:book_plan.generate:book:main:"
            "narrative-search:future-1"
        ),
        trace_id=f"trace:{project_id}:open-book",
        correlation_id=f"correlation:{project_id}",
    )
    candidate = planning.generate(generation_command, principal=principal)
    planning._evaluate_pending_if_required = original_evaluate_pending
    candidate_row = planning.require_candidate(candidate.candidate_asset_version_id)
    evaluation_command = StoryPlanningEvaluationCommand(
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
        actor_id=evaluator.principal_id,
        candidate_asset_version_id=candidate.candidate_asset_version_id,
        generation_operation_id=candidate.generation_operation_id,
        generator_operation_name="book_plan.generate",
        candidate_content_hash=str(candidate_row["content_hash"]),
        evaluator_execution_class="MODEL_PROVIDER",
        idempotency_key=f"{generation_command.idempotency_key}:semantic-evaluation",
        trace_id=generation_command.trace_id,
        correlation_id=generation_command.correlation_id,
    )

    narrative_search = PostgresNarrativeSearchApplication(
        DATABASE_URL, planning=planning
    )
    input_resolver = BookProductionInputResolver(
        DATABASE_URL,
        application_build_id="book-opening-recovery-regression",
        commit_sha=RELEASE_SHA,
        allow_scripted_qualification_fixture=True,
    )
    opening = PostgresBookOpeningApplication(
        DATABASE_URL,
        narrative_search=narrative_search,
        input_resolver=input_resolver,
        application_build_id="book-opening-recovery-regression",
        commit_sha=RELEASE_SHA,
    )
    opening_roles = {
        role
        for generator in (
            "book_plan.generate",
            "volume_plan.generate",
            "arc_plan.generate",
        )
        for role in GENERATOR_INPUT_ROLES[generator]
        if role not in {"book_plan", "volume_plan"}
    }
    request = OpenBookProductionRequest(
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
        actor_id=principal.principal_id,
        expected_book_version=int(generic["book_version"]),
        production_profile=generic["production_profile"],
        planning_input_versions={role: generic[role] for role in opening_roles},
        arc_logical_keys=("arc:central",),
        idempotency_key=opening_idempotency_key,
        trace_id=generation_command.trace_id,
        correlation_id=generation_command.correlation_id,
        initial_story_state_version=generic["initial_story_state"],
        initial_canon_snapshot_version=generic["initial_canon_snapshot"],
    )
    admission = opening.admit(request, principal=principal)
    runtime_jobs = RuntimeJobAuthority(DATABASE_URL)
    outer_claim = runtime_jobs.claim(
        runtime_group="book_opening",
        worker_id="book-opening-process-that-disappears",
        lease_seconds=30,
        job_kinds=("BOOK_OPENING_EXECUTE",),
        project_id=project_id,
    )
    assert outer_claim is not None

    def crash_inside_opening(*_args: object, **_kwargs: object) -> object:
        return planning.evaluate_candidate(
            evaluation_command,
            principal=evaluator,
            transition_principal=principal,
        )

    with (
        patch.object(opening, "_open_frozen", side_effect=crash_inside_opening),
        patch.object(
            RuntimeJobAuthority,
            "heartbeat",
            autospec=True,
            side_effect=lambda _authority, claim, lease_seconds: {
                "runtime_job_id": claim.runtime_job_id,
                "lease_seconds": lease_seconds,
            },
        ),
    ):
        try:
            execute_book_opening_claim(
                runtime_jobs,
                opening,
                principal,
                outer_claim,
                lease_seconds=30,
            )
        except SimulatedBookOpeningProcessLoss:
            pass
        else:
            raise AssertionError("process-loss fault did not cross the worker boundary")

    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT operation.operation_id, attempt.attempt_id, lease.lease_id,
                   lease.owner, lease.fencing_token
            FROM authority_operation AS operation
            JOIN authority_attempt AS attempt
              ON attempt.operation_id=operation.operation_id
            JOIN authority_lease_acquisition AS lease
              ON lease.attempt_id=attempt.attempt_id
            WHERE operation.project_id=%s
              AND operation.definition_name='story_design.semantic_evaluate'
              AND operation.idempotency_key=%s
            """,
            [project_id, evaluation_command.idempotency_key],
        )
        evaluation_identity = uow.cursor.fetchone()
        assert evaluation_identity is not None
        evaluation_operation_id = str(evaluation_identity[0])
        evaluation_attempt_id = str(evaluation_identity[1])
        evaluation_lease_id = str(evaluation_identity[2])
        evaluation_worker_id = str(evaluation_identity[3])
        evaluation_fencing_token = int(evaluation_identity[4])
        uow.cursor.execute(
            """
            UPDATE authority_runtime_job_lease
            SET lease_expires_at=NOW()-INTERVAL '1 second'
            WHERE lease_id=%s
            """,
            [outer_claim.lease_id],
        )
        uow.cursor.execute(
            """
            UPDATE authority_lease_acquisition
            SET expires_at=acquired_at+INTERVAL '1 microsecond'
            WHERE lease_id=%s
            """,
            [evaluation_lease_id],
        )
        uow.commit()

    expire_attempt_lease(
        DATABASE_URL,
        WorkerLeaseCommand(
            attempt_id=evaluation_attempt_id,
            project_id=project_id,
            worker_id=evaluation_worker_id,
            fencing_token=evaluation_fencing_token,
            trace_id=generation_command.trace_id,
            correlation_id=generation_command.correlation_id,
            causation_id=evaluation_operation_id,
        ),
    )
    cancellation = request_cancellation(
        DATABASE_URL,
        CancelCommand(
            operation_id=evaluation_operation_id,
            project_id=project_id,
            actor_id="book-opening-recovery-regression",
            reason="process disappeared before any ExternalEffect",
            expected_version=2,
            idempotency_key=f"cancel:{evaluation_operation_id}",
            trace_id=generation_command.trace_id,
            correlation_id=generation_command.correlation_id,
        ),
    )
    assert cancellation["status"] == "CANCELLATION_REQUESTED"
    resolved = resolve_cancellation(
        DATABASE_URL,
        operation_id=evaluation_operation_id,
        project_id=project_id,
        expected_version=3,
        resolution="no_external_effect",
        actor_id="book-opening-recovery-regression",
        reason="durable evidence proves no Provider effect exists",
        trace_id=generation_command.trace_id,
        correlation_id=generation_command.correlation_id,
    )
    assert resolved["status"] == "CANCELLED"

    return LegacyBookOpeningOrphan(
        opening=opening,
        planning=planning,
        principal=principal,
        evaluator=evaluator,
        opening_run_id=admission.opening_run_id,
        runtime_job_id=admission.runtime_job_id,
        outer_claim=outer_claim,
        evaluation_command=evaluation_command,
        evaluation_operation_id=evaluation_operation_id,
        evaluation_attempt_id=evaluation_attempt_id,
        evaluation_lease_id=evaluation_lease_id,
        project_id=project_id,
    )


__all__ = [
    "LegacyBookOpeningOrphan",
    "SimulatedBookOpeningProcessLoss",
    "create_legacy_book_opening_orphan",
]
