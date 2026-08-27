"""Bounded PostgreSQL Book Authority coordinator worker."""

from __future__ import annotations

import os
import signal
import time
from dataclasses import asdict

from novel_forge.api.authority_dependencies import (
    build_book_production_composition,
    build_chapter_authority_application,
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
from novel_forge.modules.command_kernel.worker_execution import (
    AuthorityWorkerExecutionBoundary,
    WorkerProgrammingError,
    WorkerSupervisor,
)
from novel_forge.modules.command_kernel.lease_heartbeat import LeaseHeartbeatGuard
from novel_forge.modules.runtime_job import (
    RuntimeJobAuthority,
    RuntimeJobClaim,
    RuntimeJobSpec,
)
from novel_forge.storage.database_runtime import close_all_database_runtimes
from novel_forge.storage.worker_health import PostgresWorkerHealthObserver


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
                "code": type(exc).__name__,
                "message": str(exc),
                "book_run_id": claim.subject_id,
            },
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
    """Execute one bounded repair envelope and atomically hand off continuation."""

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
                    "code": exc.code
                    if hasattr(exc, "code")
                    else type(exc).__name__,
                    "message": str(exc),
                    "repair_id": claim.input_snapshot.get("repair_id", ""),
                },
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
                expected_version=int(
                    claim.input_snapshot.get("observed_version", -1)
                ),
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
    except Exception as exc:
        failure = {
            "code": getattr(exc, "code", type(exc).__name__),
            "message": str(exc),
            "formation_run_id": claim.subject_id,
        }
        if not business_committed:
            formation.record_failure(
                claim.subject_id,
                error=failure,
                runtime_attempt_id=claim.attempt_id,
            )
        runtime_jobs.fail(
            claim,
            failure,
        )
        raise


def execute_book_opening_claim(
    runtime_jobs: RuntimeJobAuthority,
    opening: PostgresBookOpeningApplication,
    principal: Principal,
    claim: RuntimeJobClaim,
    *,
    lease_seconds: int = 30,
) -> dict[str, object]:
    if (
        claim.job_kind != "BOOK_OPENING_EXECUTE"
        or claim.runtime_group != "book_opening"
        or claim.subject_kind != "BOOK_OPENING_RUN"
    ):
        raise RuntimeError("Book worker received an invalid Book opening job")
    runtime_jobs.start(claim)
    expected_version = int(claim.input_snapshot.get("observed_version", -1))
    runtime_jobs.checkpoint(
        claim,
        {
            "stage": "BOOK_OPENING_STARTED",
            "opening_run_id": claim.subject_id,
            "observed_version": expected_version,
        },
    )
    business_committed = False
    try:
        with LeaseHeartbeatGuard(
            lambda: runtime_jobs.heartbeat(claim, lease_seconds=lease_seconds),
            lease_seconds=lease_seconds,
            label=f"runtime-job:{claim.attempt_id}",
        ):
            result = opening.execute_run(
                claim.subject_id,
                expected_version=expected_version,
                principal=principal,
            )
        business_committed = True
        runtime_jobs.checkpoint(
            claim,
            {
                "stage": "BOOK_OPENING_COMMITTED",
                "opening_run_id": claim.subject_id,
                "input_snapshot_id": result["input_snapshot_id"],
            },
        )
        runtime_jobs.complete(claim, result)
        return result
    except Exception as exc:
        failure = {
            "code": getattr(exc, "code", type(exc).__name__),
            "message": str(exc),
            "opening_run_id": claim.subject_id,
        }
        if not business_committed:
            opening.record_failure(
                claim.subject_id,
                expected_version=expected_version,
                error=failure,
            )
        runtime_jobs.fail(claim, failure)
        raise


def main() -> int:
    settings = IndustrialSettings.from_env()
    if settings.storage_authority != "postgresql" or not settings.database_url:
        raise RuntimeError("Book Authority worker requires PostgreSQL authority")
    worker_id = str(
        os.environ.get("NOVEL_FORGE_BOOK_AUTHORITY_WORKER_ID")
        or "book-authority-worker"
    ).strip()
    principal = build_trusted_principal_resolver().resolve_worker_principal(worker_id)
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
                            execute=lambda item: execute_story_formation_claim(
                                runtime_jobs,
                                composition.formation,
                                principal,
                                item,
                                lease_seconds=lease_seconds,
                            ),
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
                opening_claim = runtime_jobs.claim(
                    runtime_group="book_opening",
                    worker_id=worker_id,
                    lease_seconds=lease_seconds,
                    job_kinds=("BOOK_OPENING_EXECUTE",),
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
                            execute=lambda item: execute_book_opening_claim(
                                runtime_jobs,
                                composition.opening,
                                principal,
                                item,
                                lease_seconds=lease_seconds,
                            ),
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
                        execute=lambda item: execute_book_projection_repair_claim(
                            runtime_jobs,
                            composition,
                            item,
                            lease_seconds=lease_seconds,
                        ),
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
            # Claim only work that is about to execute. Pre-claiming a serial
            # batch allows later leases to expire before their heartbeat starts.
            batch = (claim,)
            try:
                failures = boundary.execute_batch(
                    batch,
                    identity=lambda item: (item.project_id, item.runtime_job_id),
                    execute=lambda item: execute_book_coordination_claim(
                        runtime_jobs,
                        composition,
                        item,
                        lease_seconds=lease_seconds,
                    ),
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
    "cli",
    "execute_book_coordination_claim",
    "execute_book_projection_repair_claim",
    "execute_story_formation_claim",
    "main",
    "schedule_book_coordination_jobs",
]
