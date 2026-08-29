from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from types import MethodType
from typing import Any
from unittest.mock import patch

from psycopg.types.json import Jsonb

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
from novel_forge.modules.command_kernel.budget_runtime import (
    BudgetScopeRequest,
    create_or_get_budget_scope_in_uow,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.attempt_runtime import (
    WorkerLeaseCommand,
    expire_attempt_lease,
)
from novel_forge.modules.runtime_job import RuntimeJobAuthority, RuntimeJobClaim
from novel_forge.modules.story_planning_runtime import (
    GENERATOR_INPUT_ROLES,
    NarrativeSearchRequest,
    PostgresNarrativeSearchApplication,
    StoryPlanningEvaluationCommand,
    StoryPlanningGenerationApplication,
    StoryPlanningGenerationCommand,
    canonical_hash,
)
from novel_forge.modules.story_planning_runtime.search_application import (
    DEFAULT_SEARCH_DIRECTIVES,
)
from novel_forge.modules.story_design_authority import scripted_qualification
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


class _ModelBackedPlanningBinder(_ExternalEffectPepFixturePlanningBinder):
    """Keep deterministic candidate transport while exercising model semantics."""

    def execute(self, **kwargs: Any):  # type: ignore[no-untyped-def]
        candidate = super().execute(**kwargs)
        return replace(
            candidate,
            evidence=replace(candidate.evidence, fixture_protocol_only=False),
        )


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


def _seed_legacy_monolithic_opening(
    *,
    opening: PostgresBookOpeningApplication,
    request: OpenBookProductionRequest,
) -> tuple[str, str]:
    """Persist one post-0103/pre-0104 v2 Opening history for regression tests.

    This is deliberately test-only historical seeding. It must not call the
    current admission command because that command owns the v3 workflow graph.
    The RuntimeJob remains ordinary production work, so claim, activation,
    process loss, convergence, and recovery still execute through real
    Authority paths.
    """

    opening_run_id = identifier("book-opening-recovery-run")
    opening_execution_id = identifier("book-opening-recovery-execution")
    runtime_job_id = identifier("book-opening-recovery-runtime-job")
    frozen_request = request.to_dict()
    frozen_request_digest = canonical_hash(frozen_request)
    runtime_input = {
        "opening_run_id": opening_run_id,
        "observed_version": 0,
        "frozen_request_digest": frozen_request_digest,
        "opening_execution_id": opening_execution_id,
        "execution_generation": 1,
        "recovery_intent_id": "",
        "replacement_evaluation_operation_id": "",
        "semantic_evaluation_operation_id": "",
        "semantic_evaluation_execution_id": "",
        "semantic_evaluation_generation": 0,
        "semantic_execution_mode": "NONE",
    }
    runtime_input_hash = canonical_hash(runtime_input)
    started_at = datetime.now(timezone.utc)
    deadline_at = started_at + timedelta(seconds=opening.provider_budget_window_seconds)

    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT created_by_operation_id
            FROM authority_book
            WHERE project_id=%s AND workspace_id=%s AND book_id=%s
            FOR KEY SHARE
            """,
            [request.project_id, request.workspace_id, request.book_id],
        )
        book = uow.cursor.fetchone()
        if book is None:
            raise AssertionError("legacy Opening fixture has no Book Authority owner")
        root_operation_id = str(book[0])
        uow.cursor.execute(
            """
            INSERT INTO authority_book_opening_run(
                opening_run_id,project_id,workspace_id,book_id,
                root_operation_id,stable_idempotency_key,lifecycle,
                frozen_request,frozen_request_digest,
                execution_contract_version,recovery_state,
                workflow_contract_version,current_workflow_node_id,
                workflow_graph_revision,workflow_graph_hash
            ) VALUES (%s,%s,%s,%s,%s,%s,'ADMITTED',%s,%s,
                      'book-opening-execution-v2','READY',
                      'legacy-monolithic-v2',NULL,0,'')
            """,
            [
                opening_run_id,
                request.project_id,
                request.workspace_id,
                request.book_id,
                root_operation_id,
                request.idempotency_key,
                Jsonb(frozen_request),
                frozen_request_digest,
            ],
        )
        budget_scope = create_or_get_budget_scope_in_uow(
            uow,
            BudgetScopeRequest(
                project_id=request.project_id,
                owner_kind="BOOK_OPENING",
                owner_id=opening_run_id,
                stable_idempotency_key=f"book-opening-budget:{opening_run_id}",
                currency="USD",
                policy_contract_version="book-opening-provider-budget.v1",
                policy_snapshot=opening.provider_budget_policy,
                started_at=started_at,
                deadline_at=deadline_at,
                created_by_operation_id=root_operation_id,
                budget_timezone="UTC",
            ),
        )
        uow.cursor.execute(
            """
            UPDATE authority_book_opening_run
            SET budget_scope_id=%s,budget_scope_revision=%s,
                budget_contract_state='BOUND'
            WHERE opening_run_id=%s
            """,
            [
                budget_scope["budget_scope_id"],
                budget_scope["revision"],
                opening_run_id,
            ],
        )
        uow.cursor.execute(
            """
            INSERT INTO authority_runtime_job(
                runtime_job_id,job_kind,runtime_group,subject_kind,
                subject_id,project_id,dedupe_key,input_snapshot,input_hash,
                max_attempts,lease_loss_policy
            ) VALUES (%s,'BOOK_OPENING_EXECUTE','book_opening',
                      'BOOK_OPENING_RUN',%s,%s,%s,%s,%s,1,
                      'AUTHORITY_CONVERGENCE_REQUIRED')
            """,
            [
                runtime_job_id,
                opening_run_id,
                request.project_id,
                f"{opening_run_id}:generation:1",
                Jsonb(runtime_input),
                runtime_input_hash,
            ],
        )
        uow.cursor.execute(
            """
            INSERT INTO authority_book_opening_execution(
                opening_execution_id,opening_run_id,generation,
                runtime_job_id,lifecycle,frozen_request_digest,
                input_snapshot_hash,policy_snapshot_hash,
                authority_contract_hash,workflow_transition_kind,
                source_checkpoint_sequence,source_checkpoint_hash
            ) VALUES (%s,%s,1,%s,'SCHEDULED',%s,%s,%s,%s,
                      'LEGACY_MONOLITHIC',0,'')
            """,
            [
                opening_execution_id,
                opening_run_id,
                runtime_job_id,
                frozen_request_digest,
                runtime_input_hash,
                opening.recovery._execution_policy_digest(),
                opening.recovery._authority_digest(),
            ],
        )
        uow.cursor.execute(
            """
            UPDATE authority_book_opening_run
            SET current_execution_id=%s,current_execution_generation=1
            WHERE opening_run_id=%s
            """,
            [opening_execution_id, opening_run_id],
        )
        uow.commit()
    return opening_run_id, runtime_job_id


def create_legacy_book_opening_orphan(
    *,
    evaluator_execution_class: str = "MODEL_PROVIDER",
    semantic_evaluation_execution_port: Any | None = None,
    terminalize_evaluation: bool = True,
    successful_search_branches_before_crash: int = 0,
) -> LegacyBookOpeningOrphan:
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
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        for asset_type in ("reader_segment_profile", "reader_contract"):
            asset_id = f"fixture:{project_id}:opening:{asset_type}"
            version_id = f"{asset_id}:v1"
            content = {"book_id": book_id, "role": asset_type}
            uow.cursor.execute(
                """
                INSERT INTO authority_asset(asset_id,project_id,asset_type)
                VALUES (%s,%s,%s)
                """,
                [asset_id, project_id, asset_type],
            )
            uow.cursor.execute(
                """
                INSERT INTO authority_asset_version(
                    asset_version_id,asset_id,version_number,lifecycle,
                    eligibility,governance,content,content_hash,schema_version
                ) VALUES (%s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',%s,%s,%s)
                """,
                [
                    version_id,
                    asset_id,
                    Jsonb(content),
                    canonical_hash(content),
                    f"{asset_type}.v1",
                ],
            )
        uow.commit()
    if evaluator_execution_class not in {"MODEL_PROVIDER", "SCRIPTED_FIXTURE"}:
        raise ValueError("unsupported recovery regression evaluator class")
    scripted = evaluator_execution_class == "SCRIPTED_FIXTURE"
    if scripted and semantic_evaluation_execution_port is not None:
        raise ValueError("scripted Evaluation cannot install a Provider execution port")
    if (
        not 0
        <= successful_search_branches_before_crash
        < len(DEFAULT_SEARCH_DIRECTIVES)
    ):
        raise ValueError("successful search branch prefix is outside the fixture")
    if successful_search_branches_before_crash and not scripted:
        raise ValueError("successful branch prefix requires scripted Evaluation")
    planning = StoryPlanningGenerationApplication(
        DATABASE_URL,
        execution_binder=(
            _ExternalEffectPepFixturePlanningBinder()
            if scripted
            else _ModelBackedPlanningBinder()
        ),
        application_build_id="book-opening-recovery-regression",
        commit_sha=RELEASE_SHA,
        semantic_evaluation_execution_port=(
            None
            if scripted
            else semantic_evaluation_execution_port or _CrashBeforeExternalEffectPort()
        ),
        allow_scripted_evaluation_fixture=scripted,
        narrative_evaluator_principal=evaluator,
    )

    narrative_search = PostgresNarrativeSearchApplication(
        DATABASE_URL, planning=planning
    )

    # Open the exact Planning-owned NarrativeSearch and materialize its first
    # branch candidate without allowing the convenience generate() call to
    # perform semantic evaluation inline.  Recovery must bind this exact
    # search/branch lineage; a lookalike candidate-once idempotency key is not
    # sufficient Authority evidence.
    original_evaluate_pending = planning._evaluate_pending_if_required
    pending_candidates: list[Any] = []
    search_branch_ordinal = 0

    def leave_evaluation_pending(
        _self: StoryPlanningGenerationApplication, **values: object
    ) -> object:
        nonlocal search_branch_ordinal
        search_branch_ordinal += 1
        if search_branch_ordinal <= successful_search_branches_before_crash:
            return original_evaluate_pending(**values)
        advanced = values["advanced"]
        pending_candidates.append(advanced)
        return advanced

    planning._evaluate_pending_if_required = MethodType(
        leave_evaluation_pending, planning
    )
    opening_idempotency_key = f"{project_id}:open-book"
    base_generation_command = StoryPlanningGenerationCommand(
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
        actor_id=principal.principal_id,
        generator_operation_name="book_plan.generate",
        logical_key="book:main",
        input_versions={
            role: generic[role] for role in GENERATOR_INPUT_ROLES["book_plan.generate"]
        },
        idempotency_key=(f"{opening_idempotency_key}:book_plan.generate:book:main"),
        trace_id=f"trace:{project_id}:open-book",
        correlation_id=f"correlation:{project_id}",
    )
    search_request = NarrativeSearchRequest(
        generation=base_generation_command,
        planning_horizon={"level": "BOOK", "stability": "HIGH", "reach": "DISTANT"},
        desired_transformation={
            "foundation_version": generic["book_design"],
            "goal": "establish a sustainable Book narrative architecture",
        },
        hard_constraints=(
            "preserve the approved Creative Foundation",
            "protect reader promise and ending direction",
            "do not convert future intent into accepted reality",
        ),
        accepted_through_chapter=0,
        parent_state_asset_version_id=generic["initial_story_state"],
    )
    try:
        narrative_search.explore(
            search_request,
            principal=principal,
            activate_selected=True,
        )
    except KernelError as exc:
        if exc.code != "NARRATIVE_SEARCH_CANDIDATE_NOT_QUALIFIED":
            raise
    else:
        raise AssertionError("pending NarrativeSearch branch unexpectedly qualified")
    finally:
        planning._evaluate_pending_if_required = original_evaluate_pending
    if len(pending_candidates) != 1:
        raise AssertionError("fixture did not freeze one pending search branch")
    candidate = pending_candidates[0]
    pending_branch_ordinal = successful_search_branches_before_crash + 1
    pending_branch_key = f"future-{pending_branch_ordinal}"
    generation = planning.require_generation(candidate.generation_operation_id)
    search_id = str(generation["narrative_search_id"])
    generation_command = replace(
        base_generation_command,
        idempotency_key=(
            f"{base_generation_command.idempotency_key}:"
            f"narrative-search:{pending_branch_key}"
        ),
        narrative_search_id=search_id,
        narrative_search_branch_key=pending_branch_key,
        narrative_search_parent_state_asset_version_id=(
            search_request.parent_state_asset_version_id
        ),
        narrative_search_accepted_through_chapter=0,
        narrative_search_strategy_directive=(
            DEFAULT_SEARCH_DIRECTIVES[pending_branch_ordinal - 1]
        ),
        narrative_search_planning_horizon=search_request.planning_horizon,
        narrative_search_desired_transformation=(search_request.desired_transformation),
        narrative_search_hard_constraints=search_request.hard_constraints,
        auto_approve_low_risk=False,
    )
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
        evaluator_execution_class=evaluator_execution_class,
        evaluation=(scripted_qualification("book_plan.generate") if scripted else None),
        idempotency_key=f"{generation_command.idempotency_key}:semantic-evaluation",
        trace_id=generation_command.trace_id,
        correlation_id=generation_command.correlation_id,
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
    opening_run_id, runtime_job_id = _seed_legacy_monolithic_opening(
        opening=opening,
        request=request,
    )
    runtime_jobs = RuntimeJobAuthority(DATABASE_URL)
    outer_claim = opening.claim_next_legacy_execution(
        worker_id="book-opening-process-that-disappears",
        lease_seconds=30,
        project_id=project_id,
        expected_opening_run_id=opening_run_id,
        expected_runtime_job_id=runtime_job_id,
    )
    assert outer_claim is not None

    def crash_inside_opening(*_args: object, **_kwargs: object) -> object:
        return planning.evaluate_candidate(
            evaluation_command,
            principal=evaluator,
            transition_principal=principal,
        )

    with ExitStack() as stack:
        stack.enter_context(
            patch.object(opening, "_open_frozen", side_effect=crash_inside_opening)
        )
        stack.enter_context(
            patch.object(
                RuntimeJobAuthority,
                "heartbeat",
                autospec=True,
                side_effect=lambda _authority, claim, lease_seconds: {
                    "runtime_job_id": claim.runtime_job_id,
                    "lease_seconds": lease_seconds,
                },
            )
        )
        if scripted:
            stack.enter_context(
                patch.object(
                    planning.semantic_evaluation.registry.item.handler,
                    "execute",
                    side_effect=SimulatedBookOpeningProcessLoss(
                        "scripted evaluator process disappeared"
                    ),
                )
            )
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
            WHERE lease_id=%s AND status='HELD'
            """,
            [evaluation_lease_id],
        )
        uow.commit()

    if terminalize_evaluation:
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
                reason="process disappeared before durable semantic convergence",
                expected_version=2,
                idempotency_key=f"cancel:{evaluation_operation_id}",
                trace_id=generation_command.trace_id,
                correlation_id=generation_command.correlation_id,
            ),
        )
        assert cancellation["status"] == "CANCELLATION_REQUESTED"
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT EXISTS(
                    SELECT 1 FROM authority_external_effect
                    WHERE operation_id=%s AND project_id=%s
                )
                """,
                [evaluation_operation_id, project_id],
            )
            has_external_effect = bool(uow.cursor.fetchone()[0])
        cancellation_resolution = (
            "external_state_unknown" if has_external_effect else "no_external_effect"
        )
        resolved = resolve_cancellation(
            DATABASE_URL,
            operation_id=evaluation_operation_id,
            project_id=project_id,
            expected_version=3,
            resolution=cancellation_resolution,
            actor_id="book-opening-recovery-regression",
            reason="legacy path classified the interrupted semantic execution",
            trace_id=generation_command.trace_id,
            correlation_id=generation_command.correlation_id,
        )
        assert resolved["status"] == (
            "RECONCILIATION_REQUIRED" if has_external_effect else "CANCELLED"
        )

    return LegacyBookOpeningOrphan(
        opening=opening,
        planning=planning,
        principal=principal,
        evaluator=evaluator,
        opening_run_id=opening_run_id,
        runtime_job_id=runtime_job_id,
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
