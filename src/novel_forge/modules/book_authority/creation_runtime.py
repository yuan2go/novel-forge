from __future__ import annotations

from dataclasses import asdict
from time import monotonic
from typing import Any, Callable

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.runtime_job import RuntimeJobAuthority
from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .production import StartBookProductionCommand


def resolved_book_command(snapshot: Any, *, actor: str, run_key: str, chapters: int) -> StartBookProductionCommand:
    return StartBookProductionCommand(
        project_id=snapshot.project_id, workspace_id=snapshot.workspace_id, book_id=snapshot.book_id,
        actor_id=actor, trace_id=f"trace:{run_key}", correlation_id=run_key, stable_idempotency_key=run_key,
        book_design_version=snapshot.book_design_version, book_plan_version=snapshot.book_plan_version,
        production_profile_version=snapshot.production_profile_version,
        longform_context_versions={"volume_plan_version": snapshot.current_volume_plan_version,
            "arc_plan_versions": list(snapshot.current_relevant_arc_plan_versions),
            **{key: getattr(snapshot, key) for key in (
                "character_state_version", "foreshadowing_state_version", "quality_trend_version",
                "reward_ledger_version", "promise_ledger_version", "reader_segment_version",
                "reader_contract_version", "platform_profile_version")}},
        target_chapter_count=chapters, input_mode="RESOLVED_AUTHORITY_INPUT", input_snapshot_id=snapshot.snapshot_id,
    )


def drive_book(*, composition: Any, chapter: Any, book_run_id: str, worker: Any,
               maximum_ticks: int, deadline: float, events: Callable[[dict[str, Any]], None] = lambda _: None) -> str:
    from novel_forge.workers.book_authority import schedule_book_coordination_jobs, execute_book_coordination_claim

    jobs = RuntimeJobAuthority(composition.authority.database_url)
    for _ in range(maximum_ticks):
        book = composition.authority.require(book_run_id)
        worker.require("book.authority.execute", book["project_id"])
        if book["state"] == "COMPLETED":
            return "COMPLETED"
        if monotonic() >= deadline:
            return "YIELDED_CHECKPOINT"
        from .execution_recovery import recover_timeout
        if recover_timeout(composition.authority, book_run_id=book_run_id, principal=composition.principal):
            book = composition.authority.require(book_run_id)
        from novel_forge.modules.story_planning_runtime.stage_repairs import resume_rejected_book_plan
        if resume_rejected_book_plan(composition,book,worker=worker):
            book=composition.authority.require(book_run_id)
        schedule_book_coordination_jobs(composition.query, jobs, limit=1, book_run_id=book_run_id)
        claim = jobs.claim(runtime_group="book", worker_id=worker.principal_id, lease_seconds=30,
            job_kinds=("BOOK_COORDINATION_TICK",), subject_kind="BOOK_RUN", subject_id=book_run_id)
        if claim is None:
            return "WAITING_LEASE_OR_DEPENDENCY"
        tick = execute_book_coordination_claim(jobs, composition, claim)
        events({"kind": "BOOK_TICK", "result": tick})
        progress = composition.query.progress(book_run_id=book_run_id)
        active = str(tick.get("operation_id") or "") if tick["action"] == "DISPATCH_CHAPTER" else progress.active_operation_id
        if active and progress.active_operation_status not in {"SUCCEEDED", "FAILED_TERMINAL", "CANCELLED"}:
            scheduler = chapter.scheduler(principal=worker)
            for _ in range(80):
                if monotonic() >= deadline:
                    return "YIELDED_CHECKPOINT"
                try:
                    result = scheduler.tick(project_id=book["project_id"], root_operation_id=active)
                except KernelError as error:
                    events({"kind": "CHAPTER_CHECKPOINT", "operation_id": active, "reason_code": error.code})
                    if scheduler.has_ready_quality_work(project_id=book["project_id"], root_operation_id=active):
                        continue
                    return error.code
                events({"kind": "CHAPTER_TICK", "result": asdict(result)})
                if result.saga_status == "SUCCEEDED":
                    break
                if result.operation_status in {"WAITING_RETRY", "UNKNOWN", "FAILED_FINAL", "FAILED_TERMINAL"}:
                    if scheduler.has_ready_quality_work(project_id=book["project_id"], root_operation_id=active):
                        continue
                    return "WAITING_CHAPTER_DEPENDENCY"
        elif tick["action"].startswith(("BLOCK", "WAIT", "APPROVAL", "REQUEST_REPLAN")):
            return str(tick["action"])
    return "YIELDED_CHECKPOINT"


def continue_creation(*, composition: Any, content: Any, chapter: Any, formation_run_id: str,
                      formation_worker: Any, book_worker: Any, maximum_ticks: int,
                      deadline: float, creation_policy: dict[str, Any] | None = None) -> dict[str, Any]:
    from novel_forge.workers.book_authority import execute_story_formation_claim, execute_book_opening_claim
    from .creation_inputs import prepare_creation_inputs
    from .opening import OpenBookProductionRequest, _OPENING_INPUT_ROLES

    formation = composition.formation
    if formation is None or composition.opening is None:
        raise KernelError("CREATION_RUNTIME_REQUIRED", "Native Formation and Opening must be configured")
    run = formation.require(formation_run_id)
    project, book = run["project_id"], run["book_id"]
    composition.principal.require("book.authority.execute", project)
    frozen = formation.frozen_input(formation_run_id)
    policy = dict(frozen.generation_policy or {})
    profiles = policy.get("creation_input_policy") or creation_policy
    if profiles is None:
        raise KernelError("CREATION_PROFILES_REQUIRED", "Historical Formation requires its original creation policy")
    if run["lifecycle"] == "FAILED":
        reason = _formation_resume_blocker(composition, run, policy)
        if reason:
            return {"formation_run_id": formation_run_id, "stop_reason": reason, "checkpoint": run}
        formation.resume(formation_run_id, expected_version=run["version"], principal=composition.principal)
    jobs = RuntimeJobAuthority(composition.authority.database_url)
    for _ in range(maximum_ticks):
        run = formation.require(formation_run_id)
        if run["lifecycle"] == "READY":
            break
        if run["lifecycle"] not in {"ADMITTED", "RUNNING"}:
            return {"formation_run_id": formation_run_id, "stop_reason": run["lifecycle"], "checkpoint": run}
        if monotonic() >= deadline:
            return {"formation_run_id": formation_run_id, "stop_reason": "YIELDED_CHECKPOINT"}
        formation.schedule_candidates(limit=100)
        claim = jobs.claim(runtime_group="story_formation", worker_id=formation_worker.principal_id,
            lease_seconds=60, job_kinds=("STORY_FORMATION_ADVANCE",),
            subject_kind="STORY_FORMATION_RUN", subject_id=formation_run_id)
        if claim is None:
            return {"formation_run_id": formation_run_id, "stop_reason": "WAITING_LEASE_OR_DEPENDENCY"}
        try:
            execute_story_formation_claim(jobs, formation, formation_worker, claim, lease_seconds=60)
        except Exception as error:
            checkpoint = formation.require(formation_run_id)
            if checkpoint["lifecycle"] != "FAILED":
                raise
            return {"formation_run_id": formation_run_id, "stop_reason": "FORMATION_FAILED",
                    "reason_code": str(getattr(error, "code", type(error).__name__)), "checkpoint": checkpoint}
    if formation.require(formation_run_id)["lifecycle"] != "READY":
        return {"formation_run_id": formation_run_id, "stop_reason": "YIELDED_CHECKPOINT"}
    run_key, opening_key = formation_run_id + ":production", formation_run_id + ":opening"
    with AuthorityUnitOfWork(composition.authority.database_url) as uow:
        uow.cursor.execute("SELECT book_run_id FROM authority_book_production WHERE project_id=%s AND stable_idempotency_key=%s", [project, run_key])
        existing = uow.cursor.fetchone()
        uow.cursor.execute("SELECT opening_run_id FROM authority_book_opening_run WHERE project_id=%s AND stable_idempotency_key=%s", [project, opening_key])
        opening = uow.cursor.fetchone()
    if existing is None:
        if opening is None:
            prepared = prepare_creation_inputs(composition=composition, content=content,
                formation_run_id=formation_run_id, policy=profiles)
            versions = prepared["versions"]
            portfolio = AuthorityAssetQuery(content.database_url).require(project_id=project,
                asset_version_id=versions["character_arc_portfolio"])
            arc_keys = tuple(dict.fromkeys(("book:" + book,
                *("character:" + row["character_id"] for row in portfolio.content["trajectories"]))))
            admitted = composition.open_book(OpenBookProductionRequest(project_id=project,
                workspace_id=run["workspace_id"], book_id=book, actor_id=composition.principal.principal_id,
                expected_book_version=prepared["book_version"], production_profile=versions["production_profile"],
                planning_input_versions={role: versions[role] for role in _OPENING_INPUT_ROLES},
                arc_logical_keys=arc_keys, idempotency_key=opening_key, trace_id="trace:" + opening_key,
                correlation_id=formation_run_id, initial_story_state_version=versions["story_state"],
                initial_canon_snapshot_version=versions["canon_snapshot"]))
            opening = (admitted.opening_run_id,)
        opened = composition.opening.require(opening[0])
        with AuthorityUnitOfWork(composition.authority.database_url) as uow:
            uow.cursor.execute("SELECT policy_snapshot FROM authority_provider_budget_scope WHERE budget_scope_id=%s", [opened["budget_scope_id"]])
            scope_policy = uow.cursor.fetchone()
        if (opened["lifecycle"] != "COMPLETE" and scope_policy
                and scope_policy[0].get("resource_control_version") != "billing-channel-resources.v1"
                and composition.opening.provider_budget_policy.get("resource_control_version") == "billing-channel-resources.v1"):
            from .resource_succession import adopt_resource_policy
            try:
                adopt_resource_policy(composition.opening, opening_run_id=opening[0], principal=composition.principal,
                    expected_version=opened["version"], idempotency_key=opening[0] + ":resource-successor")
            except KernelError as error:
                return {"opening_run_id": opening[0], "stop_reason": error.code, "reason": error.message, "checkpoint": opened}
        if opened["lifecycle"] == "FAILED":
            try:
                assessment = composition.opening.recovery.assess_recovery(opening[0],
                    idempotency_key=opening[0] + ":creation-recovery:" + str(opened["version"]), principal=composition.principal)
                composition.opening.recovery.recover(assessment.recovery_assessment_id,
                    idempotency_key=opening[0] + ":creation-recover:" + str(opened["version"]),
                    reason="continue exact native creation checkpoint", principal=composition.principal)
            except KernelError as error:
                return {"opening_run_id": opening[0], "stop_reason": error.code, "reason": error.message, "checkpoint": opened}
        for _ in range(maximum_ticks):
            opened = composition.opening.require(opening[0])
            if opened["lifecycle"] == "COMPLETE":
                break
            if monotonic() >= deadline:
                return {"formation_run_id": formation_run_id, "opening_run_id": opening[0], "stop_reason": "YIELDED_CHECKPOINT"}
            claim = composition.opening.claim_next_execution(worker_id=book_worker.principal_id,
                lease_seconds=60, project_id=project, expected_opening_run_id=opening[0])
            if claim is None or claim.subject_id != opening[0]:
                return {"opening_run_id": opening[0], "stop_reason": "WAITING_OPENING_DEPENDENCY"}
            try:
                execute_book_opening_claim(jobs, composition.opening, composition.principal, claim, lease_seconds=60)
            except KernelError as error:
                return {"opening_run_id": opening[0], "stop_reason": error.code, "reason": error.message,
                        "checkpoint": composition.opening.require(opening[0])}
        opened = composition.opening.require(opening[0])
        if opened["lifecycle"] != "COMPLETE":
            return {"opening_run_id": opening[0], "stop_reason": opened["lifecycle"], "checkpoint": opened}
        snapshot = composition.input_resolver.require(opened["result"]["input_snapshot_id"])
        design = AuthorityAssetQuery(content.database_url).require(project_id=project, asset_version_id=snapshot.book_design_version)
        started = composition.authority.start(resolved_book_command(snapshot,
            actor=composition.principal.principal_id, run_key=run_key, chapters=int(design.content["target_chapters"])), principal=composition.principal)
        existing = (started.book_run_id,)
    stop = drive_book(composition=composition, chapter=chapter, book_run_id=existing[0], worker=book_worker,
        maximum_ticks=maximum_ticks, deadline=deadline)
    return {"formation_run_id": formation_run_id, "book_run_id": existing[0], "stop_reason": stop,
            "checkpoint": composition.authority.require(existing[0])}


def _formation_resume_blocker(composition: Any, run: dict[str, Any], policy: dict[str, Any]) -> str:
    from novel_forge.modules.production_execution.execution_template import selected_book_template

    authorization = policy.get("auto_authorization") or {}
    if (policy.get("approval_mode") != "AUTO"
            or any(authorization.get(key) != value for key, value in {
                "formation_run_id": run["formation_run_id"], "project_id": run["project_id"],
                "book_id": run["book_id"], "authorized_by_principal_id": composition.principal.principal_id}.items())
            or run.get("recovery_instruction", {}).get("action") != "RESUME_WITH_SAME_FROZEN_INPUTS"):
        return "FORMATION_OWNER_RECOVERY_REQUIRED"
    if run.get("failure", {}).get("code") not in {
        "RuntimeError", "EFFECT_REQUEST_TIMEOUT_BEFORE_SEND", "EFFECT_REQUEST_FAILED_RETRYABLE",
        "EFFECT_BUDGET_EXECUTION_ASSERTION_FAILED", "RESOURCE_ROUTE_RESELECT_REQUIRED"}:
        return "FORMATION_OWNER_RECOVERY_REQUIRED"
    with AuthorityUnitOfWork(composition.authority.database_url) as uow:
        if selected_book_template(uow.cursor, project_id=run["project_id"], book_id=run["book_id"]) is None:
            return "FORMATION_OWNER_RECOVERY_REQUIRED"
        uow.cursor.execute("""SELECT count(*) FROM authority_runtime_job_attempt attempt
            JOIN authority_runtime_job job USING(runtime_job_id)
            WHERE job.subject_kind='STORY_FORMATION_RUN' AND job.subject_id=%s
              AND job.project_id=%s AND job.input_snapshot->>'observed_stage'=%s
              AND attempt.status IN ('FAILED','ABANDONED')""",
            [run["formation_run_id"], run["project_id"], run["current_stage"]])
        if int(uow.cursor.fetchone()[0]) >= 3:
            return "FORMATION_NO_PROGRESS_LIMIT"
        uow.cursor.execute("""SELECT EXISTS(SELECT 1 FROM authority_external_effect
            WHERE project_id=%s AND request_payload #>> '{_production_execution,book_id}'=%s
              AND status IN ('DISPATCHING','UNKNOWN','RECONCILIATION_REQUIRED','FAILED_FINAL'))
            OR EXISTS(SELECT 1 FROM authority_runtime_job_lease lease
                JOIN authority_runtime_job job USING(runtime_job_id)
                WHERE job.subject_kind='STORY_FORMATION_RUN' AND job.subject_id=%s
                  AND lease.status='HELD' AND lease.lease_expires_at>NOW())""",
            [run["project_id"], run["book_id"], run["formation_run_id"]])
        if uow.cursor.fetchone()[0]:
            return "FORMATION_RECONCILIATION_OR_LEASE_REQUIRED"
    return ""
