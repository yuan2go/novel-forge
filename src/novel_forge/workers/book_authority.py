from __future__ import annotations

from novel_forge.workers.dispatch_pause import pause_worker_dispatch
from novel_forge.modules.command_kernel.dispatch_control import RuntimeDispatchPaused

import os
import signal
import time
from dataclasses import asdict
from typing import Callable, Any

from novel_forge.api.authority_dependencies import (
    build_book_production_composition,
    build_chapter_authority_application,
    build_content_authority_application,
    build_production_execution_composition,
    build_trusted_principal_resolver,
)
from novel_forge.modules.authority_security import Principal
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.book_authority import (
    BookProductionComposition,
    PostgresBookOpeningApplication,
    PostgresBookAuthorityScheduler,
)
from novel_forge.modules.book_authority.queries import PostgresBookProductionQuery
from novel_forge.modules.book_design_authority import StoryFormationApplication
from novel_forge.modules.book_design_authority.formation_generation import (
    FormationApprovalRequired,
)
from novel_forge.modules.command_kernel.worker_execution import (
    AuthorityWorkerExecutionBoundary,
    WorkerProgrammingError,
    WorkerSupervisor,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.lease_heartbeat import LeaseHeartbeatGuard
from novel_forge.modules.runtime_job import (
    BOOK_OPENING_LEGACY_JOB_KIND,
    BOOK_OPENING_LEGACY_RUNTIME_GROUP,
    BOOK_OPENING_WORKFLOW_JOB_KIND,
    BOOK_OPENING_WORKFLOW_RUNTIME_GROUP,
    RuntimeJobAuthority,
    RuntimeJobClaim,
    RuntimeJobSpec,
)
from novel_forge.storage.database_runtime import close_all_database_runtimes
from novel_forge.storage.worker_health import PostgresWorkerHealthObserver


def execute_creation_worker_claim(settings: IndustrialSettings, claim: RuntimeJobClaim) -> dict[str, object]:
    from novel_forge.modules.book_authority.creation_runtime import creation_runtime_environment, execute_creation_claim

    jobs = RuntimeJobAuthority(settings.database_url)
    execution = None
    try:
        binding = PostgresBookProductionQuery(settings.database_url).creation_executor_binding(
            project_id=claim.project_id, subject_id=claim.subject_id)
        values = creation_runtime_environment(claim.project_id,
            input_only_policy=binding.get("codex_input_only_policy") if binding else None)
        resolver = build_trusted_principal_resolver(env=values)
        operator = resolver.resolve_api_principal()
        if operator.principal_id != claim.input_snapshot["operator_id"]:
            raise KernelError("CREATION_EXECUTOR_BINDING_CONFLICT", "Configured operator differs from admitted creation")
        operator.require("book.authority.execute", claim.project_id)
        execution = build_production_execution_composition(settings, env=values)
        chapter = build_chapter_authority_application(settings, execution=execution, env=values)
        composition = build_book_production_composition(settings, principal=operator, execution=execution,
            chapter_application=chapter, env=values)
        content = build_content_authority_application(settings, env=values)
        return execute_creation_claim(jobs, claim, composition=composition, content=content, chapter=chapter,
            formation_worker=resolver.resolve_book_formation_worker_principal(claim.worker_id),
            book_worker=resolver.resolve_worker_principal(claim.worker_id))
    except Exception as error:
        if jobs.get(claim.runtime_job_id)["status"] == "CLAIMED":
            jobs.fail(claim, {"code": getattr(error, "code", type(error).__name__), "message": str(error)},
                      retry_delay_seconds=30, cause=error)
        raise
    finally:
        if execution is not None:
            execution.close()


def execute_book_phase_with_creation_scope(settings: IndustrialSettings, claim: RuntimeJobClaim,
        legacy: BookProductionComposition, execute: Callable[[BookProductionComposition], dict[str, Any]]) -> dict[str, Any]:
    from novel_forge.modules.book_authority.creation_runtime import creation_runtime_environment

    jobs = RuntimeJobAuthority(settings.database_url)
    execution = None
    try:
        binding = legacy.query.creation_executor_binding(
            project_id=claim.project_id, subject_id=claim.subject_id
        )
        if not binding:
            return execute(legacy)
        legacy.principal.require("book.authority.execute", claim.project_id)
        values = creation_runtime_environment(claim.project_id,
            input_only_policy=binding.get("codex_input_only_policy"))
        operator = build_trusted_principal_resolver(env=values).resolve_api_principal()
        if operator.principal_id != binding["operator_id"]:
            raise KernelError(
                "CREATION_EXECUTOR_BINDING_CONFLICT",
                "Configured operator differs from the original creation actor",
            )
        operator.require("book.authority.execute", claim.project_id)
        execution = build_production_execution_composition(settings, env=values)
        chapter = build_chapter_authority_application(settings, execution=execution, env=values)
        scoped = build_book_production_composition(
            settings,
            principal=operator,
            execution=execution,
            chapter_application=chapter,
            env=values,
        )
        return execute(scoped)
    except Exception as error:
        if jobs.get(claim.runtime_job_id)["status"] == "CLAIMED":
            jobs.fail(claim, {"code": getattr(error, "code", type(error).__name__), "message": str(error)},
                      retry_delay_seconds=30, cause=error)
        raise
    finally:
        if execution is not None:
            execution.close()


def schedule_book_coordination_jobs(
    query: PostgresBookProductionQuery,
    runtime_jobs: RuntimeJobAuthority,
    *,
    limit: int,
    book_run_id: str = "",
) -> tuple[dict[str, object], ...]:
    pending = query.coordination_candidates(
        book_run_id=book_run_id,
        limit=limit,
    )
    scheduled: list[dict[str, object]] = []
    for candidate in pending:
        scheduled.append(
            runtime_jobs.schedule(
                RuntimeJobSpec(
                    job_kind="BOOK_COORDINATION_TICK",
                    runtime_group="book",
                    subject_kind="BOOK_RUN",
                    subject_id=candidate.book_run_id,
                    project_id=candidate.project_id,
                    dedupe_key=(
                        f"{candidate.book_run_id}:tick:{candidate.next_tick_sequence}"
                    ),
                    input_snapshot={
                        "book_run_id": candidate.book_run_id,
                        "project_id": candidate.project_id,
                        "observed_state": candidate.state,
                        "observed_version": candidate.version,
                        "observed_updated_at": candidate.updated_at.isoformat(),
                        "tick_sequence": candidate.next_tick_sequence,
                        "coordination_dependencies": list(
                            candidate.dependency_snapshot
                        ),
                    },
                    max_attempts=5,
                )
            )
        )
    return tuple(scheduled)


def execute_book_coordination_claim(
    runtime_jobs: RuntimeJobAuthority,
    ticker: BookProductionComposition | PostgresBookAuthorityScheduler,
    claim: RuntimeJobClaim,
    *,
    lease_seconds: int = 30,
) -> dict[str, object]:
    if claim.job_kind != "BOOK_COORDINATION_TICK" or claim.subject_kind != "BOOK_RUN":
        raise RuntimeError("Book worker received a non-Book Runtime Job")
    runtime_jobs.start(claim)
    runtime_jobs.checkpoint(
        claim,
        {
            "stage": "BOOK_TICK_STARTED",
            "book_run_id": claim.subject_id,
            "observed_state": claim.input_snapshot.get("observed_state", ""),
            "observed_version": claim.input_snapshot.get("observed_version", -1),
        },
    )
    try:
        with LeaseHeartbeatGuard(
            lambda: runtime_jobs.heartbeat(
                claim,
                lease_seconds=lease_seconds,
            ),
            lease_seconds=lease_seconds,
            label=f"runtime-job:{claim.attempt_id}",
        ):
            tick = ticker.tick(claim.subject_id)
        tick_result = asdict(tick)
        runtime_jobs.checkpoint(
            claim,
            {
                "stage": "BOOK_TICK_APPLIED",
                "book_run_id": claim.subject_id,
                "action": tick.action,
                "state": tick.state,
                "operation_id": tick.operation_id,
            },
        )
        runtime_jobs.complete(claim, tick_result)
        return tick_result
    except Exception as exc:
        runtime_jobs.fail(
            claim,
            {
                "code": getattr(exc, "code", type(exc).__name__),
                "message": str(exc),
                "book_run_id": claim.subject_id,
            },
            retry_delay_seconds=30,
            cause=exc,
        )
        raise


def execute_book_projection_repair_claim(
    runtime_jobs: RuntimeJobAuthority,
    composition: BookProductionComposition,
    claim: RuntimeJobClaim,
    *,
    lease_seconds: int = 30,
    maximum_chapters: int = 4,
) -> dict[str, object]:

    if (
        claim.job_kind != "BOOK_PROJECTION_REPAIR"
        or claim.runtime_group != "book_repair"
        or claim.subject_kind != "BOOK_RUN"
    ):
        raise RuntimeError("Book repair worker received an invalid RuntimeJob")
    runtime_jobs.start(claim)
    runtime_jobs.checkpoint(
        claim,
        {
            "stage": "BOOK_PROJECTION_REPAIR_STARTED",
            "repair_id": claim.input_snapshot.get("repair_id", ""),
            "batch_start": claim.input_snapshot.get("batch_start", 1),
        },
    )
    handoff_committed = False
    try:
        with LeaseHeartbeatGuard(
            lambda: runtime_jobs.heartbeat(claim, lease_seconds=lease_seconds),
            lease_seconds=lease_seconds,
            label=f"runtime-job:{claim.attempt_id}",
        ):
            batch = composition.projection_repair.run_batch(
                claim,
                actor_id=composition.principal.principal_id,
                maximum_chapters=maximum_chapters,
            )
        result = asdict(batch)
        result["complete"] = batch.complete
        runtime_jobs.checkpoint(
            claim,
            {
                "stage": "BOOK_PROJECTION_REPAIR_BATCH_COMMITTED",
                **result,
            },
        )
        if batch.complete:
            runtime_jobs.complete(claim, result)
            return result
        continuation = RuntimeJobSpec(
            job_kind="BOOK_PROJECTION_REPAIR",
            runtime_group="book_repair",
            subject_kind="BOOK_RUN",
            subject_id=batch.book_run_id,
            project_id=claim.project_id,
            dedupe_key=(
                f"projection-repair:{batch.book_run_id}:chapter:{batch.next_chapter}"
            ),
            input_snapshot={
                "repair_id": batch.repair_id,
                "book_run_id": batch.book_run_id,
                "target_accepted_through_chapter": batch.target_chapter,
                "target_evidence_digest": claim.input_snapshot.get(
                    "target_evidence_digest", ""
                ),
                "batch_start": batch.next_chapter,
            },
            priority=20,
            max_attempts=10,
        )
        handoff = runtime_jobs.complete_and_schedule_continuation(
            claim, result, continuation
        )
        handoff_committed = True
        composition.projection_repair.link_continuation(
            repair_id=batch.repair_id,
            prior_runtime_job_id=claim.runtime_job_id,
            runtime_job_id=str(handoff["continuation_runtime_job_id"]),
        )
        return {**result, **handoff}
    except Exception as exc:
        if not handoff_committed:
            runtime_jobs.fail(
                claim,
                {
                    "code": exc.code if hasattr(exc, "code") else type(exc).__name__,
                    "message": str(exc),
                    "repair_id": claim.input_snapshot.get("repair_id", ""),
                },
                cause=exc,
            )
        raise


def execute_story_formation_claim(
    runtime_jobs: RuntimeJobAuthority,
    formation: StoryFormationApplication,
    principal: Principal,
    claim: RuntimeJobClaim,
    *,
    lease_seconds: int = 30,
) -> dict[str, object]:
    if (
        claim.job_kind != "STORY_FORMATION_ADVANCE"
        or claim.runtime_group != "story_formation"
        or claim.subject_kind != "STORY_FORMATION_RUN"
    ):
        raise RuntimeError("Book worker received an invalid Story Formation job")
    runtime_jobs.start(claim)
    current = formation.require(claim.subject_id)
    if current["lifecycle"] in {"FAILED", "WAITING_APPROVAL", "ABORTED"}:
        result = {"formation_run_id": claim.subject_id, "lifecycle": current["lifecycle"],
                  "current_stage": current["current_stage"], "version": current["version"],
                  "next_action": "FOLLOW_PERSISTED_OWNER_DECISION"}
        runtime_jobs.complete(claim, result)
        return result
    runtime_jobs.checkpoint(
        claim,
        {
            "stage": "STORY_FORMATION_ADVANCE_STARTED",
            "formation_run_id": claim.subject_id,
            "observed_stage": claim.input_snapshot.get("observed_stage", ""),
        },
    )
    business_committed = False
    try:
        with LeaseHeartbeatGuard(
            lambda: runtime_jobs.heartbeat(claim, lease_seconds=lease_seconds),
            lease_seconds=lease_seconds,
            label=f"runtime-job:{claim.attempt_id}",
        ):
            result = formation.advance_expected(
                claim.subject_id,
                expected_stage=str(claim.input_snapshot.get("observed_stage") or ""),
                expected_version=int(claim.input_snapshot.get("observed_version", -1)),
                principal=principal,
            )
        business_committed = True
        runtime_jobs.checkpoint(
            claim,
            {
                "stage": "STORY_FORMATION_ADVANCE_COMMITTED",
                "current_stage": result["current_stage"],
                "lifecycle": result["lifecycle"],
                "version": result["version"],
            },
        )
        runtime_jobs.complete(claim, result)
        return result
    except FormationApprovalRequired as approval:
        try:
            waiting = formation.wait_for_approval(
                claim.subject_id,
                expected_stage=str(
                    claim.input_snapshot.get("observed_stage") or ""
                ),
                expected_version=int(
                    claim.input_snapshot.get("observed_version", -1)
                ),
                authority=approval.authority,
                candidate_asset_version_id=approval.candidate_asset_version_id,
                candidate_content_hash=approval.candidate_content_hash,
                candidate_asset_version_ids=approval.candidate_asset_version_ids,
                runtime_attempt_id=claim.attempt_id,
                principal=principal,
                generation_failures=approval.generation_failures,
            )
        except Exception as exc:
            failure = {
                "code": getattr(exc, "code", type(exc).__name__),
                "message": str(exc),
                "formation_run_id": claim.subject_id,
                "approval_target": approval.candidate_asset_version_id,
            }
            if not isinstance(exc, RuntimeDispatchPaused):
                formation.record_failure(
                    claim.subject_id,
                    error=failure,
                    runtime_attempt_id=claim.attempt_id,
                )
            runtime_jobs.fail(claim, failure, cause=exc)
            raise
        business_committed = True
        runtime_jobs.checkpoint(
            claim,
            {
                "stage": "STORY_FORMATION_WAITING_APPROVAL",
                "current_stage": waiting["current_stage"],
                "lifecycle": waiting["lifecycle"],
                "version": waiting["version"],
                "candidate_asset_version_id": (
                    approval.candidate_asset_version_id
                ),
                "candidate_content_hash": approval.candidate_content_hash,
            },
        )
        runtime_jobs.complete(claim, waiting)
        return waiting
    except Exception as exc:
        failure = {
            "code": getattr(exc, "code", type(exc).__name__),
            "message": str(exc),
            "formation_run_id": claim.subject_id,
        }
        if not business_committed and not isinstance(exc, RuntimeDispatchPaused):
            formation.record_failure(
                claim.subject_id,
                error=failure,
                runtime_attempt_id=claim.attempt_id,
            )
        runtime_jobs.fail(
            claim,
            failure,
            cause=exc,
        )
        raise


def execute_book_opening_node_claim(
    runtime_jobs: RuntimeJobAuthority,
    opening: PostgresBookOpeningApplication,
    principal: Principal,
    claim: RuntimeJobClaim,
    *,
    lease_seconds: int = 30,
) -> dict[str, object]:
    if (
        claim.job_kind != BOOK_OPENING_WORKFLOW_JOB_KIND
        or claim.runtime_group != BOOK_OPENING_WORKFLOW_RUNTIME_GROUP
        or claim.subject_kind != "BOOK_OPENING_RUN"
        or str(claim.input_snapshot.get("workflow_contract_version") or "")
        != "book-opening-workflow-v1"
    ):
        raise RuntimeError(
            "Book workflow-v1 worker received an invalid RuntimeJob identity"
        )
    return _execute_book_opening_claim(
        runtime_jobs,
        opening,
        principal,
        claim,
        lease_seconds=lease_seconds,
    )


def _execute_book_opening_claim(
    runtime_jobs: RuntimeJobAuthority,
    opening: PostgresBookOpeningApplication,
    principal: Principal,
    claim: RuntimeJobClaim,
    *,
    lease_seconds: int,
) -> dict[str, object]:
    expected_version = int(claim.input_snapshot.get("observed_version", -1))
    result: dict[str, object] | None = None
    try:
        # INVARIANT: Opening.execute_run atomically moves RuntimeJob/Attempt and the
        # BookOpening execution chain to RUNNING before releasing any semantic
        # replacement.  A separate start/checkpoint transaction here would
        # recreate the orphan window this worker is meant to close.
        with LeaseHeartbeatGuard(
            lambda: runtime_jobs.heartbeat(claim, lease_seconds=lease_seconds),
            lease_seconds=lease_seconds,
            label=f"runtime-job:{claim.attempt_id}",
            probe=lambda: runtime_jobs.assert_live(claim),
            # INVARIANT: execute_run terminalizes the exact claim in its completion UoW.
            # Re-probing an already RELEASED lease on context exit would turn
            # every successful completion into a false response-loss path.
            probe_on_exit=False,
        ) as guard:
            result = opening.execute_run(
                claim.subject_id,
                expected_version=expected_version,
                runtime_claim=claim,
                principal=principal,
                execution_probe=guard.assert_healthy,
            )
        return result
    except Exception as exc:
        durable = opening.require(claim.subject_id)
        workflow_node_id = str(claim.input_snapshot.get("workflow_node_id") or "")
        if workflow_node_id:
            try:
                durable_result = opening.require_node_execution_result(
                    opening_run_id=claim.subject_id,
                    workflow_node_id=workflow_node_id,
                    opening_execution_id=str(
                        claim.input_snapshot.get("opening_execution_id") or ""
                    ),
                    execution_generation=int(
                        claim.input_snapshot.get("execution_generation") or 0
                    ),
                )
                if (
                    getattr(exc, "code", "") == "AUTHORITY_LEASE_HEARTBEAT_FAILED"
                    and result is not None
                    and {**result, "replayed": True} == durable_result
                ):
                    return result
                return durable_result
            except KernelError as durable_exc:
                if durable_exc.code != "BOOK_OPENING_NODE_RESULT_NOT_FOUND":
                    raise
        if str(durable["lifecycle"]) == "COMPLETE":
            # INVARIANT: The Authority completion UoW committed and only its response (or
            # a racing heartbeat response) was lost.  Return durable truth;
            # never rewrite the terminal execution or RuntimeJob history.
            return dict(durable["result"])
        failure = {
            "code": getattr(exc, "code", type(exc).__name__),
            "message": str(exc),
            "opening_run_id": claim.subject_id,
        }
        opening.record_failure(
            claim.subject_id,
            expected_version=expected_version,
            runtime_claim=claim,
            error=failure,
        )
        raise


def execute_legacy_book_opening_claim(
    runtime_jobs: RuntimeJobAuthority,
    opening: PostgresBookOpeningApplication,
    principal: Principal,
    claim: RuntimeJobClaim,
    *,
    lease_seconds: int = 30,
) -> dict[str, object]:

    if (
        claim.job_kind != BOOK_OPENING_LEGACY_JOB_KIND
        or claim.runtime_group != BOOK_OPENING_LEGACY_RUNTIME_GROUP
        or claim.subject_kind != "BOOK_OPENING_RUN"
        or str(claim.input_snapshot.get("workflow_contract_version") or "")
    ):
        raise RuntimeError("Legacy Book worker received a non-legacy RuntimeJob")
    return _execute_book_opening_claim(
        runtime_jobs,
        opening,
        principal,
        claim,
        lease_seconds=lease_seconds,
    )


def claim_next_book_opening_execution(
    opening: PostgresBookOpeningApplication,
    *,
    worker_id: str,
    lease_seconds: int,
) -> RuntimeJobClaim | None:

    claim = opening.claim_next_node_execution(
        worker_id=worker_id,
        lease_seconds=lease_seconds,
    )
    if claim is not None:
        return claim
    return opening.claim_next_legacy_execution(
        worker_id=worker_id,
        lease_seconds=lease_seconds,
    )


def execute_claimed_book_opening_execution(
    runtime_jobs: RuntimeJobAuthority,
    opening: PostgresBookOpeningApplication,
    principal: Principal,
    claim: RuntimeJobClaim,
    *,
    lease_seconds: int = 30,
) -> dict[str, object]:

    capability = (claim.job_kind, claim.runtime_group)
    if capability == (
        BOOK_OPENING_WORKFLOW_JOB_KIND,
        BOOK_OPENING_WORKFLOW_RUNTIME_GROUP,
    ):
        return execute_book_opening_node_claim(
            runtime_jobs,
            opening,
            principal,
            claim,
            lease_seconds=lease_seconds,
        )
    if capability == (
        BOOK_OPENING_LEGACY_JOB_KIND,
        BOOK_OPENING_LEGACY_RUNTIME_GROUP,
    ):
        return execute_legacy_book_opening_claim(
            runtime_jobs,
            opening,
            principal,
            claim,
            lease_seconds=lease_seconds,
        )
    raise RuntimeError("Book worker received an unsupported contract pair")


def execute_book_opening_claim(
    runtime_jobs: RuntimeJobAuthority,
    opening: PostgresBookOpeningApplication,
    principal: Principal,
    claim: RuntimeJobClaim,
    *,
    lease_seconds: int = 30,
) -> dict[str, object]:

    current_claim = claim
    for _ in range(5):
        if (current_claim.job_kind, current_claim.runtime_group) == (
            BOOK_OPENING_LEGACY_JOB_KIND,
            BOOK_OPENING_LEGACY_RUNTIME_GROUP,
        ):
            result = execute_legacy_book_opening_claim(
                runtime_jobs,
                opening,
                principal,
                current_claim,
                lease_seconds=lease_seconds,
            )
        else:
            result = execute_book_opening_node_claim(
                runtime_jobs,
                opening,
                principal,
                current_claim,
                lease_seconds=lease_seconds,
            )
        if "workflow_node_id" not in result:
            return result
        if str(result.get("lifecycle") or "") == "COMPLETE":
            final = result.get("book_opening_result")
            if not isinstance(final, dict):
                raise RuntimeError("completed Book Opening has no workflow result")
            # COMPATIBILITY: Compatibility callers require the v2 response keys; project them
            # without mutating the immutable PostgreSQL aggregate.
            compatible = dict(final)
            compatible["volume_plan_version"] = str(
                compatible.get("current_volume_plan_version") or ""
            )
            compatible["arc_plan_versions"] = list(
                compatible.get("current_relevant_arc_plan_versions") or ()
            )
            return compatible
        successor_runtime_job_id = str(result.get("successor_runtime_job_id") or "")
        if not successor_runtime_job_id:
            raise RuntimeError("Book Opening node has no exact successor RuntimeJob")
        current_claim = opening.claim_next_node_execution(
            worker_id=claim.worker_id,
            lease_seconds=lease_seconds,
            project_id=claim.project_id,
            expected_opening_run_id=claim.subject_id,
            expected_runtime_job_id=successor_runtime_job_id,
        )
        if (
            current_claim is None
            or current_claim.subject_id != claim.subject_id
            or current_claim.runtime_job_id != successor_runtime_job_id
        ):
            raise RuntimeError("Book Opening successor node was not claimable")
    raise RuntimeError("Book Opening workflow exceeded its fixed five-node graph")


def main() -> int:
    settings = IndustrialSettings.from_env()
    if settings.storage_authority != "postgresql" or not settings.database_url:
        raise RuntimeError("Book Authority worker requires PostgreSQL authority")
    worker_id = str(
        os.environ.get("NOVEL_FORGE_BOOK_AUTHORITY_WORKER_ID")
        or "book-authority-worker"
    ).strip()
    principal_resolver = build_trusted_principal_resolver()
    principal = principal_resolver.resolve_worker_principal(worker_id)
    formation_principal = (
        principal_resolver.resolve_book_formation_worker_principal(worker_id)
    )
    production_execution = build_production_execution_composition(settings)
    chapter = build_chapter_authority_application(
        settings, execution=production_execution
    )
    composition = build_book_production_composition(
        settings,
        principal=principal,
        execution=production_execution,
        chapter_application=chapter,
    )
    runtime_jobs = RuntimeJobAuthority(settings.database_url)
    poll_seconds = max(
        0.05, float(os.environ.get("NOVEL_FORGE_AUTHORITY_POLL_SECONDS") or "1")
    )
    batch_size = max(1, int(os.environ.get("NOVEL_FORGE_AUTHORITY_BATCH_SIZE") or "10"))
    lease_seconds = max(
        5, int(os.environ.get("NOVEL_FORGE_AUTHORITY_LEASE_SECONDS") or "30")
    )
    stopping = False
    boundary = AuthorityWorkerExecutionBoundary(worker_kind="book")
    supervisor = WorkerSupervisor(
        worker_kind="book",
        worker_id=worker_id,
        observer=PostgresWorkerHealthObserver(settings.database_url),
    )

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        while not stopping:
            if pause_worker_dispatch(supervisor, poll_seconds):
                continue
            from novel_forge.modules.book_authority.creation_runtime import schedule_creation_jobs

            schedule_creation_jobs(settings.database_url, limit=batch_size)
            creation_claim = runtime_jobs.claim(runtime_group="book_creation", worker_id=worker_id,
                lease_seconds=60, job_kinds=("BOOK_CREATION_ADVANCE",))
            if creation_claim is not None:
                supervisor.polled(idle=False)
                try:
                    failures = boundary.execute_batch((creation_claim,),
                        identity=lambda item: (item.project_id, item.runtime_job_id),
                        execute=lambda item: execute_creation_worker_claim(settings, item),
                        on_task_start=supervisor.operation_started,
                        on_task_finish=lambda operation_id, succeeded: supervisor.operation_finished(operation_id, succeeded=succeeded))
                    supervisor.batch_completed(failures)
                except WorkerProgrammingError as error:
                    supervisor.fatal(error)
                    return WorkerSupervisor.FATAL_EXIT_CODE
                continue
            if composition.formation is not None:
                composition.formation.schedule_candidates(limit=batch_size)
                formation_claim = runtime_jobs.claim(
                    runtime_group="story_formation",
                    worker_id=worker_id,
                    lease_seconds=lease_seconds,
                    job_kinds=("STORY_FORMATION_ADVANCE",),
                )
                if formation_claim is not None:
                    supervisor.polled(idle=False)
                    try:
                        failures = boundary.execute_batch(
                            (formation_claim,),
                            identity=lambda item: (
                                item.project_id,
                                item.runtime_job_id,
                            ),
                            execute=lambda item: execute_book_phase_with_creation_scope(settings, item, composition,
                                lambda scoped: execute_story_formation_claim(runtime_jobs, scoped.formation,
                                    formation_principal, item, lease_seconds=lease_seconds)),
                            on_task_start=supervisor.operation_started,
                            on_task_finish=lambda operation_id, succeeded: (
                                supervisor.operation_finished(
                                    operation_id, succeeded=succeeded
                                )
                            ),
                        )
                        supervisor.batch_completed(failures)
                    except WorkerProgrammingError as error:
                        supervisor.fatal(error)
                        return WorkerSupervisor.FATAL_EXIT_CODE
                    continue
            if composition.opening is not None:
                opening_claim = claim_next_book_opening_execution(
                    composition.opening,
                    worker_id=worker_id,
                    lease_seconds=lease_seconds,
                )
                if opening_claim is not None:
                    supervisor.polled(idle=False)
                    try:
                        failures = boundary.execute_batch(
                            (opening_claim,),
                            identity=lambda item: (
                                item.project_id,
                                item.runtime_job_id,
                            ),
                            execute=lambda item: execute_book_phase_with_creation_scope(settings, item, composition,
                                lambda scoped: execute_claimed_book_opening_execution(runtime_jobs, scoped.opening,
                                    scoped.principal, item, lease_seconds=lease_seconds)),
                            on_task_start=supervisor.operation_started,
                            on_task_finish=lambda operation_id, succeeded: (
                                supervisor.operation_finished(
                                    operation_id, succeeded=succeeded
                                )
                            ),
                        )
                        supervisor.batch_completed(failures)
                    except WorkerProgrammingError as error:
                        supervisor.fatal(error)
                        return WorkerSupervisor.FATAL_EXIT_CODE
                    continue
            repair_claim = runtime_jobs.claim(
                runtime_group="book_repair",
                worker_id=worker_id,
                lease_seconds=lease_seconds,
                job_kinds=("BOOK_PROJECTION_REPAIR",),
            )
            if repair_claim is not None:
                supervisor.polled(idle=False)
                try:
                    failures = boundary.execute_batch(
                        (repair_claim,),
                        identity=lambda item: (
                            item.project_id,
                            item.runtime_job_id,
                        ),
                        execute=lambda item: execute_book_phase_with_creation_scope(settings, item, composition,
                            lambda scoped: execute_book_projection_repair_claim(runtime_jobs, scoped,
                                item, lease_seconds=lease_seconds)),
                        on_task_start=supervisor.operation_started,
                        on_task_finish=lambda operation_id, succeeded: (
                            supervisor.operation_finished(
                                operation_id, succeeded=succeeded
                            )
                        ),
                    )
                    supervisor.batch_completed(failures)
                except WorkerProgrammingError as error:
                    supervisor.fatal(error)
                    return WorkerSupervisor.FATAL_EXIT_CODE
                continue
            schedule_book_coordination_jobs(
                composition.query,
                runtime_jobs,
                limit=batch_size,
            )
            claim = runtime_jobs.claim(
                runtime_group="book",
                worker_id=worker_id,
                lease_seconds=lease_seconds,
                job_kinds=("BOOK_COORDINATION_TICK",),
            )
            if claim is None:
                supervisor.polled(idle=True)
                time.sleep(poll_seconds)
                continue
            supervisor.polled(idle=False)
            # WHY: Claim only work that is about to execute. Pre-claiming a serial
            # batch allows later leases to expire before their heartbeat starts.
            batch = (claim,)
            try:
                failures = boundary.execute_batch(
                    batch,
                    identity=lambda item: (item.project_id, item.runtime_job_id),
                    execute=lambda item: execute_book_phase_with_creation_scope(settings, item, composition,
                        lambda scoped: execute_book_coordination_claim(runtime_jobs, scoped,
                            item, lease_seconds=lease_seconds)),
                    on_task_start=supervisor.operation_started,
                    on_task_finish=lambda operation_id, succeeded: (
                        supervisor.operation_finished(operation_id, succeeded=succeeded)
                    ),
                )
                supervisor.batch_completed(failures)
            except WorkerProgrammingError as error:
                supervisor.fatal(error)
                return WorkerSupervisor.FATAL_EXIT_CODE
        supervisor.draining()
        supervisor.stopped()
        return 0
    finally:
        production_execution.close()
        close_all_database_runtimes()


def cli() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    cli()


__all__ = [
    "claim_next_book_opening_execution",
    "cli",
    "execute_book_coordination_claim",
    "execute_claimed_book_opening_execution",
    "execute_legacy_book_opening_claim",
    "execute_book_opening_node_claim",
    "execute_book_projection_repair_claim",
    "execute_story_formation_claim",
    "main",
    "schedule_book_coordination_jobs",
]
