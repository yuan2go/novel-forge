from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import os
from time import monotonic, sleep
from typing import Any, Callable

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.runtime_job import RuntimeJobAuthority, RuntimeJobSpec
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


class _RecoveryCheckpoint(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def resume_generation_pause(authority, *, book_run_id, principal):
    book = authority.require(book_run_id)
    if book["state"] != "PAUSED" or book.get("paused_reason") != "GENERATION_RECOVERY_EXHAUSTED":
        return False
    request = authority.require_chapter_request(book["active_chapter_request_id"])
    from novel_forge.modules.command_kernel.generation_policy import generation_graph
    with AuthorityUnitOfWork(authority.database_url) as uow:
        if not generation_graph(uow.cursor, request["chapter_root_operation_id"], book["project_id"]):
            return False
        uow.cursor.execute("""SELECT EXISTS(SELECT 1 FROM authority_saga_step_successor successor
            JOIN authority_operation replacement ON replacement.operation_id=successor.successor_operation_id
            JOIN authority_saga_step step ON step.operation_id=replacement.operation_id
            WHERE replacement.root_operation_id=%s AND replacement.project_id=%s
              AND replacement.status IN ('ADMITTED','READY','RUNNING','WAITING_EXTERNAL_RESULT')
              AND successor.policy_evidence->>'contract_version'='chapter-pure-generation-successor.v1')""",
            [request["chapter_root_operation_id"], book["project_id"]])
        runnable = bool(uow.cursor.fetchone()[0])
    if not runnable:
        return False
    authority.resume(book_run_id, reason="Original generation failure is isolated; resume the owned successor without a historical quota lock",
        principal=principal, expected_version=book["version"])
    return True


def drive_book(*, composition: Any, chapter: Any, book_run_id: str, worker: Any,
               maximum_ticks: int, deadline: float, continuation_live: Callable[[], bool] = lambda: True, execution_probe: Callable[[], object] = lambda: None, events: Callable[[dict[str, Any]], None] = lambda _: None) -> str:
    try:
        return _drive_book(composition=composition, chapter=chapter, book_run_id=book_run_id,
            worker=worker, maximum_ticks=maximum_ticks, deadline=deadline,
            continuation_live=continuation_live, execution_probe=execution_probe, events=events)
    except _RecoveryCheckpoint as checkpoint:
        return checkpoint.reason
    except KernelError as error:
        if error.code != "GENERATION_RECOVERY_EXHAUSTED":
            raise
        book = composition.authority.require(book_run_id)
        if book["state"] != "PAUSED" or book.get("paused_reason") != error.code:
            composition.authority.pause(book_run_id, reason=error.code, principal=composition.principal)
        events({"kind": "GENERATION_RECOVERY_STOPPED", "book_run_id": book_run_id,
            "reason_code": error.code, "failure": error.details, "recovery_state": "EXHAUSTED",
            "business_impact": "SAVED_MANUSCRIPT_RETAINED_NO_FURTHER_DISPATCH"})
        return error.code


def _drive_book(*, composition: Any, chapter: Any, book_run_id: str, worker: Any,
               maximum_ticks: int, deadline: float, continuation_live: Callable[[], bool] = lambda: True, execution_probe: Callable[[], object] = lambda: None, events: Callable[[dict[str, Any]], None] = lambda _: None) -> str:
    from novel_forge.workers.book_authority import schedule_book_coordination_jobs, execute_book_coordination_claim

    jobs = RuntimeJobAuthority(composition.authority.database_url)
    recovery_actions = 0
    stalled_failures = {}

    def repeated_failure(error: KernelError, root_id: str) -> bool:
        from novel_forge.modules.story_planning_runtime.domain import canonical_hash
        details = error.details or {}
        signature = canonical_hash({"root": root_id, "code": error.code,
            "cause": details.get("cause_code"), "stage": details.get("stage")})
        stalled_failures[signature] = stalled_failures.get(signature, 0) + 1
        if stalled_failures[signature] < 3:
            return False
        events({"kind": "GENERATION_NO_PROGRESS", "book_run_id": book_run_id,
            "operation_id": root_id, "failure": details, "scope": "CURRENT_DRIVE",
            "same_failure_observations": stalled_failures[signature]})
        return True

    def recover(action: Callable[[], bool]) -> bool:
        nonlocal recovery_actions
        execution_probe()
        if not continuation_live():
            composition.authority.cancel(book_run_id, reason="Original creation cancellation", principal=composition.principal)
            raise _RecoveryCheckpoint("CANCELLED")
        current = composition.authority.require(book_run_id)
        worker.require("book.authority.execute", current["project_id"])
        if current["state"] == "COMPLETED":
            raise _RecoveryCheckpoint("COMPLETED")
        if current["state"] in {"ABORTED", "CANCELLED"}:
            raise _RecoveryCheckpoint("CANCELLED")
        if monotonic() >= deadline or recovery_actions >= maximum_ticks:
            raise _RecoveryCheckpoint("YIELDED_CHECKPOINT")
        if composition.query.unresolved_chapter_effects(book_run_id=book_run_id):
            raise _RecoveryCheckpoint("WAIT_EXTERNAL_RECONCILIATION")
        changed = action()
        if changed:
            recovery_actions += 1
        return changed

    for _ in range(maximum_ticks):
        execution_probe()
        if not continuation_live():
            composition.authority.cancel(book_run_id, reason="Original creation cancellation", principal=composition.principal)
            return "CANCELLED"
        book = composition.authority.require(book_run_id)
        worker.require("book.authority.execute", book["project_id"])
        if book["state"] == "COMPLETED":
            return "COMPLETED"
        from .manuscript import author_first, writing_frontier
        if author_first(book) and writing_frontier(book) >= book["target_chapter_count"]:
            return "MANUSCRIPT_READY"
        if book["state"] in {"ABORTED", "CANCELLED"}:
            return "CANCELLED"
        if monotonic() >= deadline:
            return "YIELDED_CHECKPOINT"
        from novel_forge.modules.command_kernel.generation_isolation import recover_chapter_generations
        from novel_forge.modules.chapter_authority.context_transport_recovery import recover_unsent_context_transport, recover_optional_memory_transport
        recover_unsent_context_transport(composition.authority, book_run_id=book_run_id, principal=composition.principal)
        recover_optional_memory_transport(composition.authority, book_run_id=book_run_id, principal=composition.principal)
        from novel_forge.modules.chapter_authority.context_transport_recovery import recover_schema_transport
        recover(lambda: recover_schema_transport(composition.authority, book_run_id=book_run_id, principal=composition.principal))
        recover_chapter_generations(composition.authority, book_run_id=book_run_id, principal=composition.principal)
        if composition.query.unresolved_chapter_effects(book_run_id=book_run_id):
            return "WAIT_EXTERNAL_RECONCILIATION"
        from novel_forge.modules.story_planning_runtime.runtime_continuation import recover_world_disclosure_frontier
        recover(lambda: recover_world_disclosure_frontier(composition.planning,composition.authority.require(book_run_id),principal=composition.principal))
        resume_generation_pause(composition.authority, book_run_id=book_run_id, principal=composition.principal)
        from novel_forge.modules.chapter_authority.memo_recovery import recover_memo_references, recover_memo_completion, recover_intent_references
        recover(lambda: recover_intent_references(composition.authority, book_run_id=book_run_id, principal=composition.principal))
        recover(lambda: recover_memo_references(composition.authority, book_run_id=book_run_id, principal=composition.principal))
        recover(lambda: recover_memo_completion(composition.authority, book_run_id=book_run_id, principal=composition.principal))
        from novel_forge.modules.chapter_authority.scene_receipt_recovery import recover_scene_source_union
        recover(lambda: recover_scene_source_union(composition.authority, book_run_id=book_run_id, principal=composition.principal))
        if not author_first(book):
            from novel_forge.modules.chapter_authority.canon_contract_recovery import recover_canon_contract, recover_completed_canon_window
            recover(lambda: recover_canon_contract(composition.authority, book_run_id=book_run_id, principal=composition.principal))
            recover(lambda: recover_completed_canon_window(composition.authority, book_run_id=book_run_id, principal=composition.principal))
            from novel_forge.modules.chapter_authority.receipt_recovery import recover_known_draft_receipt
            recover(lambda: recover_known_draft_receipt(composition.authority, book_run_id=book_run_id, principal=composition.principal))
            from novel_forge.modules.chapter_authority.current_semantic_recovery import retire_semantic_frontier
            try:
                recover(lambda: retire_semantic_frontier(composition.authority, book_run_id=book_run_id, principal=composition.principal))
            except KernelError as error:
                if error.code == "CURRENT_SEMANTIC_REPAIR_CONTROL_EXHAUSTED":
                    return error.code
                raise
            from .retained_recovery import recover_retained_quality
            if recover(lambda: recover_retained_quality(composition.authority, book_run_id=book_run_id, principal=composition.principal)):
                events({"kind": "CHAPTER_RETAINED_GRAPH_CONTINUATION", "book_run_id": book_run_id})
            from novel_forge.modules.chapter_authority.derived_recovery import recover_derived_frontier
            while recover(lambda: recover_derived_frontier(composition.authority, book_run_id=book_run_id, principal=composition.principal)):
                events({'kind':'CHAPTER_DERIVED_REVALIDATION','book_run_id':book_run_id})
            from novel_forge.modules.chapter_authority.candidate_repair import recover_quality_frontier
            recover(lambda: recover_quality_frontier(composition.authority, book_run_id=book_run_id, principal=composition.principal))
            from novel_forge.modules.chapter_authority.candidate_repair import recover_support_frontier
            recover(lambda: recover_support_frontier(composition.authority, book_run_id=book_run_id, principal=composition.principal))
            from novel_forge.modules.chapter_authority.candidate_repair import recover_information_frontier
            recover(lambda: recover_information_frontier(composition.authority, book_run_id=book_run_id, principal=composition.principal))
            from novel_forge.modules.chapter_authority.candidate_repair import recover_review_frontier
            recover(lambda: recover_review_frontier(composition.authority, book_run_id=book_run_id, principal=composition.principal))
            from novel_forge.modules.chapter_authority.candidate_repair import recover_length_frontier
            recover(lambda: recover_length_frontier(composition.authority, book_run_id=book_run_id, principal=composition.principal))
            from novel_forge.modules.chapter_authority.candidate_repair import recover_length_retry_phase
            recover(lambda: recover_length_retry_phase(composition.authority, book_run_id=book_run_id, principal=composition.principal))
            from novel_forge.modules.chapter_authority.candidate_repair import recover_canon_capacity_frontier
            recover(lambda: recover_canon_capacity_frontier(composition.authority, book_run_id=book_run_id, principal=composition.principal))
            from novel_forge.modules.chapter_authority.candidate_repair import recover_canon_protocol_frontier
            recover(lambda: recover_canon_protocol_frontier(composition.authority, book_run_id=book_run_id, principal=composition.principal))
            from novel_forge.modules.chapter_authority.candidate_repair import recover_canon_schema_retry_phase
            recover(lambda: recover_canon_schema_retry_phase(composition.authority, book_run_id=book_run_id, principal=composition.principal))
            from novel_forge.modules.chapter_authority.contract_recovery import recover_realization_frontier
            recover(lambda: recover_realization_frontier(composition.authority, book_run_id=book_run_id, principal=composition.principal))
            from .execution_recovery_v2 import recover_timeout as recover_timeout_v2
            if recover(lambda: recover_timeout_v2(composition.authority, book_run_id=book_run_id, principal=composition.principal)):
                book = composition.authority.require(book_run_id)
            from .execution_recovery import recover_timeout
            if recover(lambda: recover_timeout(composition.authority, book_run_id=book_run_id, principal=composition.principal)):
                book = composition.authority.require(book_run_id)
            from novel_forge.modules.story_planning_runtime.stage_repairs import resume_rejected_book_plan
            if recover(lambda: resume_rejected_book_plan(composition, composition.authority.require(book_run_id), worker=worker, execution_probe=execution_probe)):
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
                execution_probe()
                if not continuation_live():
                    composition.authority.cancel(book_run_id, reason="Original creation cancellation", principal=composition.principal)
                    return "CANCELLED"
                if monotonic() >= deadline:
                    return "YIELDED_CHECKPOINT"
                try:
                    result = scheduler.tick(project_id=book["project_id"], root_operation_id=active)
                except KernelError as error:
                    events({"kind": "CHAPTER_CHECKPOINT", "operation_id": active, "reason_code": error.code, "failure": error.details})
                    if error.code.startswith("MODEL_EFFECT_OUTCOME_UNKNOWN") or error.code == "CONTENT_EXTERNAL_RECONCILIATION_REQUIRED":
                        from novel_forge.modules.command_kernel.generation_isolation import recover_chapter_generations
                        if recover_chapter_generations(composition.authority, book_run_id=book_run_id, principal=composition.principal):
                            if repeated_failure(error, active):
                                return "GENERATION_NO_PROGRESS"
                            continue
                    elif repeated_failure(error, active):
                        return "GENERATION_NO_PROGRESS"
                    if error.code == "CHAPTER_ATTEMPT_EXHAUSTED" and recover_unsent_context_transport(composition.authority, book_run_id=book_run_id, principal=composition.principal):
                        continue
                    if author_first(book):
                        return error.code
                    if recover(lambda: recover_derived_frontier(composition.authority, book_run_id=book_run_id, principal=composition.principal)):
                        while recover(lambda: recover_derived_frontier(composition.authority, book_run_id=book_run_id, principal=composition.principal)):
                            pass
                        continue
                    if error.code == "PROVIDER_ROUTING_BLOCKED" and recover(lambda: recover_canon_capacity_frontier(composition.authority, book_run_id=book_run_id, principal=composition.principal)):
                        continue
                    if error.code == "MODEL_EFFECT_RETRYABLE_PROCESS_EXIT_FAILURE" and recover(lambda: recover_canon_schema_retry_phase(composition.authority, book_run_id=book_run_id, principal=composition.principal)):
                        continue
                    if error.code in {"CHAPTER_LENGTH_REPAIR_INCOMPLETE", "OPERATION_BUSINESS_TIMEOUT"} and recover(lambda: recover_length_retry_phase(composition.authority, book_run_id=book_run_id, principal=composition.principal)):
                        events({"kind": "CHAPTER_LENGTH_RETRY_PHASE", "operation_id": active})
                        continue
                    if error.code in {"MODEL_EFFECT_RETRYABLE_PROCESS_EXIT_FAILURE", "CHAPTER_LENGTH_REPAIR_INCOMPLETE", "CANON_QUOTE_LOCALIZATION_INVALID"}:
                        from .member_retry import wait_settled_member_retry
                        if recover(lambda: wait_settled_member_retry(composition.authority, book_run_id=book_run_id, root_id=active, principal=composition.principal, deadline=deadline)):
                            events({"kind": "CHAPTER_MEMBER_RETRY_WAIT", "operation_id": active})
                            continue
                    if scheduler.has_ready_quality_work(project_id=book["project_id"], root_operation_id=active):
                        continue
                    return error.code
                events({"kind": "CHAPTER_TICK", "result": asdict(result)})
                if result.operation_status == "SUCCEEDED":
                    stalled_failures.clear()
                if result.recovery_mode.startswith(('derived_canon_','derived_quality_')) and result.operation_status=='SUCCEEDED':
                    while recover(lambda: recover_derived_frontier(composition.authority, book_run_id=book_run_id, principal=composition.principal)):
                        events({'kind':'CHAPTER_DERIVED_REVALIDATION','book_run_id':book_run_id})
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
                      deadline: float, creation_policy: dict[str, Any] | None = None, execution_probe: Callable[[], object] = lambda: None,
                      creation_job_id: str = "") -> dict[str, Any]:
    from novel_forge.workers.book_authority import execute_story_formation_claim, execute_book_opening_claim
    from .creation_inputs import prepare_creation_inputs
    from .opening import OpenBookProductionRequest, _OPENING_INPUT_ROLES

    formation = composition.formation
    if formation is None or composition.opening is None:
        raise KernelError("CREATION_RUNTIME_REQUIRED", "Native Formation and Opening must be configured")
    execution_probe()
    run = formation.require(formation_run_id)
    project, book = run["project_id"], run["book_id"]
    composition.principal.require("book.authority.execute", project)
    if reconcile_creation_cancellation(composition, formation_run_id):
        return {"formation_run_id": formation_run_id, "stop_reason": "CANCELLED"}
    frozen = formation.frozen_input(formation_run_id)
    policy = dict(frozen.generation_policy or {})
    profiles = policy.get("creation_input_policy") or creation_policy
    if profiles is None:
        raise KernelError("CREATION_PROFILES_REQUIRED", "Historical Formation requires its original creation policy")
    if run["lifecycle"] == "FAILED":
        capacity_registered = _recover_formation_capacity(composition, run, policy, execution_probe=execution_probe)
        reason = _formation_resume_blocker(composition, run, policy, capacity_registered=capacity_registered, creation_job_id=creation_job_id)
        if reason:
            return {"formation_run_id": formation_run_id, "stop_reason": reason, "checkpoint": run}
        formation.resume(formation_run_id, expected_version=run["version"], principal=composition.principal)
    if (run["lifecycle"] == "WAITING_APPROVAL"
            and policy.get("contract_version") in {"formation-generation.v5", "formation-generation.v7"}
            and run.get("recovery_instruction", {}).get("author_selection", {}).get("decision") == "APPROVE"):
        formation.resume(formation_run_id, expected_version=run["version"], principal=composition.principal)
    jobs = RuntimeJobAuthority(composition.authority.database_url)
    for _ in range(maximum_ticks):
        execution_probe()
        if reconcile_creation_cancellation(composition, formation_run_id):
            return {"formation_run_id": formation_run_id, "stop_reason": "CANCELLED"}
        run = formation.require(formation_run_id)
        if run["lifecycle"] == "READY":
            break
        if run["lifecycle"] not in {"ADMITTED", "RUNNING"}:
            return {"formation_run_id": formation_run_id, "stop_reason": run["lifecycle"], "checkpoint": run}
        if monotonic() >= deadline:
            return {"formation_run_id": formation_run_id, "stop_reason": "YIELDED_CHECKPOINT"}
        formation.schedule_candidates(limit=1, project_id=project, formation_run_id=formation_run_id)
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
            capacity_registered = _recover_formation_capacity(composition, checkpoint, policy, execution_probe=execution_probe)
            blocked = _formation_resume_blocker(composition, checkpoint, policy, capacity_registered=capacity_registered, creation_job_id=creation_job_id)
            if capacity_registered and not blocked:
                formation.resume(formation_run_id, expected_version=checkpoint["version"], principal=composition.principal)
                return {"formation_run_id": formation_run_id, "stop_reason": "YIELDED_CHECKPOINT",
                        "recovery_action": "CONTINUE_REGISTERED_NATIVE_CAPACITY_SUCCESSOR"}
            failure_code = str(getattr(error, "code", type(error).__name__))
            return {"formation_run_id": formation_run_id,
                    "stop_reason": blocked or ("FORMATION_CURRENT_FAILURE_REQUIRES_CORRECTION" if failure_code.startswith("MODEL_EFFECT_FINAL_") else "FORMATION_FAILED"),
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
        execution_probe()
        if opening is None:
            prepared = prepare_creation_inputs(composition=composition, content=content,
                formation_run_id=formation_run_id, policy=profiles)
            versions = prepared["versions"]
            portfolio = AuthorityAssetQuery(content.database_url).require(project_id=project,
                asset_version_id=versions["character_arc_portfolio"])
            from novel_forge.modules.hierarchical_planning.domain import character_planning_locator
            arc_keys = tuple(dict.fromkeys(("book:" + book,
                *(character_planning_locator(row["character_id"]) for row in portfolio.content["trajectories"]))))
            admitted = composition.open_book(OpenBookProductionRequest(project_id=project,
                workspace_id=run["workspace_id"], book_id=book, actor_id=composition.principal.principal_id,
                expected_book_version=prepared["book_version"], production_profile=versions["production_profile"],
                planning_input_versions={role: versions[role] for role in _OPENING_INPUT_ROLES},
                arc_logical_keys=arc_keys, idempotency_key=opening_key, trace_id="trace:" + opening_key,
                correlation_id=formation_run_id, initial_story_state_version=versions["story_state"],
                initial_canon_snapshot_version=versions["canon_snapshot"]))
            opening = (admitted.opening_run_id,)
        opened = composition.opening.require(opening[0])
        if opened["lifecycle"] == "ABORTED":
            return {"formation_run_id": formation_run_id, "opening_run_id": opening[0], "stop_reason": "CANCELLED"}
        with AuthorityUnitOfWork(composition.authority.database_url) as uow:
            uow.cursor.execute("SELECT lifecycle FROM authority_book_opening_execution WHERE opening_execution_id=%s", [opened["current_execution_id"]])
            execution_lifecycle = uow.cursor.fetchone()
        if opened["lifecycle"] in {"ADMITTED", "RUNNING"} and execution_lifecycle and execution_lifecycle[0] in {"BOUND", "RUNNING"}:
            loss_key = (
                opening[0]
                + ":execution-loss:"
                + str(opened["current_execution_generation"])
            )
            try:
                loss = composition.opening.recovery.assess_execution_loss(
                    opening[0],
                    idempotency_key=loss_key,
                    principal=composition.principal,
                )
            except KernelError as error:
                if error.code != "BOOK_OPENING_EXECUTION_STILL_VALID":
                    raise
            else:
                composition.opening.recovery.converge_execution_loss(
                    loss.recovery_assessment_id,
                    idempotency_key=loss_key + ":converge",
                    principal=composition.principal,
                    expected_opening_run_id=opening[0],
                )
                opened = composition.opening.require(opening[0])
        if opened["lifecycle"] == "ABORTED":
            return {
                "formation_run_id": formation_run_id,
                "opening_run_id": opening[0],
                "stop_reason": "CANCELLED",
            }
        if opened["lifecycle"] == "FAILED":
            from novel_forge.modules.command_kernel.generation_isolation import recover_book_generations
            try:
                if opened.get("failure", {}).get("code") == "PLANNING_RUNTIME_CONTINUATION_COMMAND_DRIFT":
                    _recover_pending_planning_deployment(composition, run, policy, execution_probe=execution_probe)
                recover_book_generations(composition.planning, project_id=project, book_id=book,
                    principal=composition.principal)
            except KernelError as error:
                return {"opening_run_id": opening[0], "stop_reason": error.code, "reason": error.message,
                    "failure": error.details, "checkpoint": opened}
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
                with AuthorityUnitOfWork(composition.authority.database_url) as uow:
                    uow.cursor.execute("SELECT COUNT(*) FROM authority_generation_isolation WHERE project_id=%s AND book_id=%s", [project, book])
                    recovery_revision = str(uow.cursor.fetchone()[0])
                recovery_key = opening[0] + ":creation-recovery:" + str(opened["version"]) + ":disposition:" + recovery_revision
                assessment = composition.opening.recovery.assess_recovery(opening[0],
                    idempotency_key=recovery_key, principal=composition.principal)
                composition.opening.recovery.recover(assessment.recovery_assessment_id,
                    idempotency_key=recovery_key + ":apply",
                    reason="continue exact native creation checkpoint", principal=composition.principal)
            except KernelError as error:
                return {"opening_run_id": opening[0], "stop_reason": error.code, "reason": error.message, "checkpoint": opened}
        for _ in range(maximum_ticks):
            execution_probe()
            if reconcile_creation_cancellation(composition, formation_run_id):
                return {"formation_run_id": formation_run_id, "stop_reason": "CANCELLED"}
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
                from novel_forge.modules.command_kernel.generation_isolation import recover_book_generations
                try:
                    if error.code == "PLANNING_RUNTIME_CONTINUATION_COMMAND_DRIFT":
                        _recover_pending_planning_deployment(composition, run, policy, execution_probe=execution_probe)
                        return {"opening_run_id":opening[0],"stop_reason":"YIELDED_CHECKPOINT",
                            "recovery_action":"CONTINUE_REVALIDATED_NATIVE_DEPLOYMENT",
                            "checkpoint":composition.opening.require(opening[0])}
                    if recover_book_generations(composition.planning, project_id=project, book_id=book,
                            principal=composition.principal):
                        return {"opening_run_id": opening[0], "stop_reason": "YIELDED_CHECKPOINT",
                            "recovery_action": "CONTINUE_REGISTERED_NATIVE_SUCCESSOR", "failure": error.details,
                            "checkpoint": composition.opening.require(opening[0])}
                except KernelError as recovery_error:
                    return {"opening_run_id": opening[0], "stop_reason": recovery_error.code,
                        "reason": recovery_error.message, "failure": recovery_error.details,
                        "checkpoint": composition.opening.require(opening[0])}
                return {"opening_run_id": opening[0], "stop_reason": error.code, "reason": error.message,
                        "failure": error.details,
                        "checkpoint": composition.opening.require(opening[0])}
        opened = composition.opening.require(opening[0])
        if opened["lifecycle"] != "COMPLETE":
            return {"opening_run_id": opening[0], "stop_reason": opened["lifecycle"], "checkpoint": opened}
        execution_probe()
        snapshot = composition.input_resolver.require(opened["result"]["input_snapshot_id"])
        design = AuthorityAssetQuery(content.database_url).require(project_id=project, asset_version_id=snapshot.book_design_version)
        from .creation_window import execution_stop_chapter
        stop_chapter = execution_stop_chapter(frozen.generation_policy or {}, target_chapters=int(design.content["target_chapters"]))
        started = composition.authority.start(resolved_book_command(snapshot,
            actor=composition.principal.principal_id, run_key=run_key, chapters=stop_chapter), principal=composition.principal)
        existing = (started.book_run_id,)
    stop = drive_book(composition=composition, chapter=chapter, book_run_id=existing[0], worker=book_worker,
        maximum_ticks=maximum_ticks, deadline=deadline,
        continuation_live=lambda: not creation_cancellation(composition.authority.database_url, formation_run_id), execution_probe=execution_probe)
    return {"formation_run_id": formation_run_id, "book_run_id": existing[0], "stop_reason": stop,
            "checkpoint": composition.authority.require(existing[0])}


def _recover_pending_planning_deployment(composition, run, policy, *, execution_probe):
    from novel_forge.modules.story_planning_runtime.runtime_continuation import require_binding
    from novel_forge.modules.story_planning_runtime.runtime_deployment import register

    auth = policy.get("auto_authorization", {})
    if auth.get("authorized_by_principal_id") != composition.principal.principal_id:
        raise KernelError("PLANNING_DEPLOYMENT_REVALIDATION_AUTHORIZATION_REQUIRED", "Require original Creator authorization")
    with AuthorityUnitOfWork(composition.authority.database_url) as uow:
        uow.cursor.execute("""SELECT continuation_id FROM authority_story_planning_runtime_continuation
            WHERE project_id=%s AND book_id=%s AND successor_operation_id IS NULL
              AND target_release_sha<>%s ORDER BY created_at""",
            [run["project_id"], run["book_id"], composition.planning.commit_sha])
        pending = uow.cursor.fetchall()
    for (identity,) in pending:
        if require_binding(composition.authority.database_url, identity)["target_release_sha"] == composition.planning.commit_sha:
            continue
        register(composition.planning, identity, project_id=run["project_id"], principal=composition.principal,
            authorization_ref=auth["authorization_ref"], reason="Preserve unstarted native task across actual Creator deployment; unchanged story inputs and contracts",
            execution_probe=execution_probe)


def creation_cancellation(database_url: str, formation_run_id: str) -> dict[str, str] | None:
    from novel_forge.storage.story_formation_repositories import StoryFormationRepository
    with AuthorityUnitOfWork(database_url) as uow:
        return StoryFormationRepository(uow.cursor).cancellation(formation_run_id)


def reconcile_creation_cancellation(composition: Any, formation_run_id: str) -> bool:
    intent = creation_cancellation(composition.authority.database_url, formation_run_id)
    if not intent:
        return False
    run = composition.formation.require(formation_run_id)
    with AuthorityUnitOfWork(composition.authority.database_url) as uow:
        uow.cursor.execute("SELECT book_run_id FROM authority_book_production WHERE project_id=%s AND stable_idempotency_key=%s", [run["project_id"], formation_run_id + ":production"])
        book = uow.cursor.fetchone()
        uow.cursor.execute("SELECT opening_run_id,lifecycle,version FROM authority_book_opening_run WHERE project_id=%s AND stable_idempotency_key=%s", [run["project_id"], formation_run_id + ":opening"])
        opening = uow.cursor.fetchone()
    if book:
        composition.authority.cancel(book[0], reason=intent["reason"], principal=composition.principal)
    elif opening and opening[1] not in {"COMPLETE", "ABORTED"}:
        composition.opening.abort(opening[0], expected_version=opening[2], principal=composition.principal)
    elif run["lifecycle"] not in {"READY", "ABORTED"}:
        composition.formation.abort(formation_run_id, expected_version=run["version"], principal=composition.principal)
    return True


def _recover_formation_capacity(composition: Any, run: dict[str, Any], policy: dict[str, Any], *, execution_probe: Callable[[], object]) -> bool:
    from novel_forge.modules.authority_security import PrincipalType
    from novel_forge.modules.story_planning_runtime.foundation_generation import FOUNDATION_GENERATORS

    authorization = policy.get("auto_authorization") or {}
    stage = run["current_stage"]
    generator = next((name for name, role in FOUNDATION_GENERATORS.items() if role.value == stage), None)
    if (run["lifecycle"] != "FAILED" or generator is None or stage == "CREATIVE_FOUNDATION"
            or run.get("failure", {}).get("code") not in {
                "PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED", "PLANNING_RUNTIME_CONTINUATION_OWNER_REQUIRED"}
            or composition.principal.principal_type is not PrincipalType.LOCAL_OPERATOR
            or policy.get("approval_mode") != "AUTO"
            or any(authorization.get(key) != value for key, value in {
                "formation_run_id": run["formation_run_id"], "project_id": run["project_id"],
                "book_id": run["book_id"], "authorized_by_principal_id": composition.principal.principal_id}.items())
            or run.get("recovery_instruction", {}).get("action") != "RESUME_WITH_SAME_FROZEN_INPUTS"):
        return False
    with AuthorityUnitOfWork(composition.authority.database_url) as uow:
        uow.cursor.execute("""SELECT operation.operation_id,operation.version
            FROM authority_story_planning_generation generation JOIN authority_operation operation USING(operation_id)
            JOIN LATERAL (SELECT result FROM authority_attempt WHERE operation_id=operation.operation_id
                ORDER BY attempt_number DESC LIMIT 1) attempt ON TRUE
            WHERE generation.project_id=%s AND generation.book_id=%s AND generation.generator_operation_name=%s
              AND generation.logical_key=%s AND generation.candidate_asset_version_id IS NULL
              AND operation.operation_id=(SELECT latest.operation_id FROM authority_story_planning_generation latest
                JOIN authority_operation latest_owner ON latest_owner.operation_id=latest.operation_id
                WHERE latest.project_id=generation.project_id AND latest.book_id=generation.book_id
                  AND latest.generator_operation_name=generation.generator_operation_name AND latest.logical_key=generation.logical_key
                ORDER BY latest_owner.created_at DESC,latest_owner.operation_id DESC LIMIT 1)
              AND operation.status IN ('FAILED_FINAL','DEAD_LETTER')
              AND attempt.result->>'error_code'='PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED'
              AND NOT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=operation.operation_id)
              AND NOT EXISTS(SELECT 1 FROM authority_lease_acquisition lease JOIN authority_attempt owner USING(attempt_id)
                WHERE owner.operation_id=operation.operation_id AND lease.status='HELD' AND lease.expires_at>NOW())
            ORDER BY operation.created_at DESC LIMIT 1""",
            [run["project_id"], run["book_id"], generator, f"{run['formation_run_id']}:{stage}:0"])
        source = uow.cursor.fetchone()
    if source is None:
        return False
    execution_probe()
    if creation_cancellation(composition.authority.database_url, run["formation_run_id"]):
        return False
    composition.planning.register_runtime_continuation(source[0], project_id=run["project_id"],
        principal=composition.principal, expected_source_version=source[1],
        decision_evidence={"authorization_ref": authorization["authorization_ref"],
            "reason": "Creator authorizes capacity correction of the exact unsent current Foundation stage; preserve frozen inputs"},
        trace_id="trace:formation-capacity:" + source[0], correlation_id=run["formation_run_id"])
    return True


def _formation_resume_blocker(composition: Any, run: dict[str, Any], policy: dict[str, Any], *, capacity_registered: bool = False,
                              creation_job_id: str = "") -> str:
    from novel_forge.modules.production_execution.execution_template import selected_book_template

    authorization = policy.get("auto_authorization") or {}
    if (policy.get("approval_mode") != "AUTO"
            or any(authorization.get(key) != value for key, value in {
                "formation_run_id": run["formation_run_id"], "project_id": run["project_id"],
                "book_id": run["book_id"], "authorized_by_principal_id": composition.principal.principal_id}.items())
            or run.get("recovery_instruction", {}).get("action") != "RESUME_WITH_SAME_FROZEN_INPUTS"):
        return "FORMATION_OWNER_RECOVERY_REQUIRED"
    failure_code = str(run.get("failure", {}).get("code") or "")
    if not capacity_registered and not failure_code.startswith(("MODEL_EFFECT_RETRYABLE_", "MODEL_EFFECT_FINAL_")) and failure_code not in {
        "RuntimeError", "EFFECT_REQUEST_TIMEOUT_BEFORE_SEND", "EFFECT_REQUEST_FAILED_RETRYABLE",
        "EFFECT_BUDGET_EXECUTION_ASSERTION_FAILED", "RESOURCE_ROUTE_RESELECT_REQUIRED"}:
        return "FORMATION_OWNER_RECOVERY_REQUIRED"
    with AuthorityUnitOfWork(composition.authority.database_url) as uow:
        from novel_forge.modules.command_kernel.budget_runtime import unresolved_cli_outcomes

        if unresolved_cli_outcomes(uow.cursor, run["project_id"], book_id=run["book_id"]):
            return "FORMATION_RECONCILIATION_OR_LEASE_REQUIRED"
        if selected_book_template(uow.cursor, project_id=run["project_id"], book_id=run["book_id"]) is None:
            return "FORMATION_OWNER_RECOVERY_REQUIRED"
        uow.cursor.execute("""SELECT EXISTS(SELECT 1 FROM authority_external_effect
            WHERE project_id=%s AND request_payload #>> '{_production_execution,book_id}'=%s
              AND NOT authority_generation_isolated(external_effect_id)
              AND (status IN ('DISPATCHING','UNKNOWN','RECONCILIATION_REQUIRED')
                   OR status='FAILED_FINAL' AND effect_type<>'model.invoke'))
            OR EXISTS(SELECT 1 FROM authority_runtime_job_lease lease
                JOIN authority_runtime_job job USING(runtime_job_id)
                WHERE job.subject_kind='STORY_FORMATION_RUN' AND job.subject_id=%s
                  AND job.runtime_job_id<>%s
                  AND lease.status='HELD' AND lease.lease_expires_at>NOW())""",
            [run["project_id"], run["book_id"], run["formation_run_id"], creation_job_id])
        if uow.cursor.fetchone()[0]:
            return "FORMATION_RECONCILIATION_OR_LEASE_REQUIRED"
    return ""


def creation_narrative_execution(policy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    version = policy.get("narrative_execution_contract")
    if version is None:
        return {"chapter": {}, "planning": {}}
    if version != "native-narrative-execution.v1":
        raise KernelError("CREATION_NARRATIVE_EXECUTION_INVALID", "Unknown frozen narrative execution contract")
    return {"chapter": {"pack_version_override": "3.0.3", "prose_skill_version": "prose-generation-v5",
                        "prompt_template_version": "v15"},
            "planning": {"event_first_planning": True}}


def creation_title(inputs: dict[str, Any]) -> tuple[str, bool]:
    generated = inputs.get("version") == "creation-request.v2" and "title" not in inputs
    if generated:
        return "Untitled — pending native Foundation", True
    title = inputs.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("Creation requires an author title or the generated-title request contract")
    return title, False


def creation_runtime_environment(project_id: str, values: dict[str, str] | None = None) -> dict[str, str]:
    result = dict(os.environ if values is None else values)
    scope = hashlib.sha256(project_id.encode()).hexdigest()[:24]
    result.setdefault("NOVEL_FORGE_CHAPTER_CAPABILITY_PACK_ID", "chapter_generation_pack.creative." + scope)
    result.setdefault("NOVEL_FORGE_PLANNING_CAPABILITY_PACK_ID", "story_planning_pack.creative." + scope)
    result.setdefault("NOVEL_FORGE_READER_OUTCOME_CAPABILITY_PACK_ID", "reader_outcome_pack.creative." + scope)
    result.setdefault("NOVEL_FORGE_COORDINATED_READER_CONTRACT", "reader-accepted-context.v3")
    return result


_CREATION_PROGRESS_COLUMNS = """run.current_stage,run.lifecycle,run.version,
            (SELECT count(*) FROM authority_external_effect effect WHERE effect.project_id=run.project_id
                AND effect.request_payload #>> '{_production_execution,book_id}'=run.book_id AND effect.status='SUCCEEDED'),
            (SELECT count(*) FROM authority_book_opening_node_receipt receipt
                JOIN authority_book_opening_run opening USING(opening_run_id)
                WHERE opening.project_id=run.project_id AND opening.stable_idempotency_key=run.formation_run_id || ':opening'),
            (SELECT COALESCE(jsonb_build_array(production.state,production.accepted_through_chapter,production.version),'[]'::jsonb)
                FROM authority_book_production production WHERE production.project_id=run.project_id
                  AND production.stable_idempotency_key=run.formation_run_id || ':production'),
            jsonb_build_object('cancel_requested',EXISTS(SELECT 1 FROM authority_story_creation_cancellation cancellation WHERE cancellation.formation_run_id=run.formation_run_id),
                'generation_recovery',jsonb_build_array(
                    (SELECT count(*) FROM authority_generation_isolation WHERE project_id=run.project_id AND book_id=run.book_id),
                    (SELECT count(*) FROM authority_story_planning_runtime_continuation WHERE project_id=run.project_id AND book_id=run.book_id)),
                'opening',(SELECT jsonb_build_array(opening.lifecycle,opening.version) FROM authority_book_opening_run opening
                    WHERE opening.project_id=run.project_id AND opening.stable_idempotency_key=run.formation_run_id || ':opening'),
                'chapter',(SELECT jsonb_build_array(operation.status,operation.version) FROM authority_book_production production
                    JOIN authority_book_chapter_request request ON request.chapter_request_id=production.active_chapter_request_id
                    JOIN authority_operation operation ON operation.operation_id=request.chapter_root_operation_id
                    WHERE production.project_id=run.project_id AND production.stable_idempotency_key=run.formation_run_id || ':production'))
"""


def creation_progress(database_url: str, *, project_id: str, formation_run_id: str) -> tuple[Any, ...]:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(f"SELECT {_CREATION_PROGRESS_COLUMNS} FROM authority_story_formation_run run WHERE run.formation_run_id=%s AND run.project_id=%s",
            [formation_run_id, project_id])
        row = uow.cursor.fetchone()
    if row is None:
        raise KernelError("CREATION_CHECKPOINT_NOT_FOUND", formation_run_id)
    return tuple(row)


def creation_wait_class(reason: str) -> str:
    if reason in {"COMPLETED", "MANUSCRIPT_READY"}:
        return "COMPLETED"
    if reason in {"CANCELLED", "ABORTED"}:
        return "CANCELLED"
    if reason in {"TASK_CONTEXT_MODEL_OUTPUT_CAPACITY_UNKNOWN", "TASK_CONTEXT_MODEL_CAPACITY_UNKNOWN"}:
        return "OWNER_RECOVERY_REQUIRED"
    if "RECONCILIATION" in reason or "UNKNOWN" in reason:
        return "RECONCILIATION_REQUIRED"
    if reason in {"YIELDED_CHECKPOINT", "WAITING_LEASE_OR_DEPENDENCY", "WAITING_OPENING_DEPENDENCY",
                  "WAITING_CHAPTER_DEPENDENCY", "FORMATION_FAILED"}:
        return "TECHNICAL_WAIT"
    if reason in {"WAITING_APPROVAL", "WAIT_PLAN_APPROVAL", "WAIT_REPLAN_APPROVAL", "WAIT_CONTROL_DECISION"}:
        return "AUTHOR_DECISION"
    return "OWNER_RECOVERY_REQUIRED"


def creation_material_progress(progress: Any) -> Any:
    # WHY: Retiring failures and appending recovery versions are evidence, not new usable work.
    if not isinstance(progress, (list, tuple)) or len(progress) != 7:
        return progress
    result = list(progress)
    result[2] = None
    if isinstance(result[5], (list, tuple)):
        result[5] = list(result[5])[:2]
    state = dict(result[6]) if isinstance(result[6], dict) else {}
    state.pop("generation_recovery", None)
    for key in ("chapter", "opening"):
        if isinstance(state.get(key), (list, tuple)):
            state[key] = list(state[key])[:1]
    result[6] = state
    return result


def creation_recovery_record(database_url: str, formation_run_id: str, reason: str, key: str) -> dict[str, Any] | None:
    dedupe = f"{formation_run_id}:creation:recover:{key or hashlib.sha256(reason.encode()).hexdigest()}"
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("SELECT runtime_job_id,status,input_snapshot FROM authority_runtime_job WHERE dedupe_key=%s AND job_kind='BOOK_CREATION_ADVANCE' AND subject_id=%s", [dedupe,formation_run_id])
        row = uow.cursor.fetchone()
    if not row:
        return None
    if row[2].get("owner_recovery_reason") != reason:
        raise KernelError("CREATION_RECOVERY_REQUEST_DRIFT", "Recovery key already binds a different reason")
    return {"runtime_job_id":row[0],"status":row[1],"deduplicated":True}


def schedule_creation_jobs(database_url: str, *, limit: int = 10, formation_run_id: str = "", recovery_reason: str = "", recovery_key: str = "") -> tuple[dict[str, Any], ...]:
    if limit <= 0:
        raise ValueError("creation scheduling limit must be positive")
    if recovery_reason and not formation_run_id:
        raise ValueError("Explicit recovery must name the original creation")
    jobs = RuntimeJobAuthority(database_url)
    with AuthorityUnitOfWork(database_url) as uow:
        recovery_dedupe = f"{formation_run_id}:creation:recover:{recovery_key or hashlib.sha256(recovery_reason.encode()).hexdigest()}" if recovery_reason else ""
        if recovery_dedupe:
            uow.cursor.execute("SELECT runtime_job_id,status,input_snapshot FROM authority_runtime_job WHERE dedupe_key=%s AND job_kind='BOOK_CREATION_ADVANCE' AND subject_id=%s", [recovery_dedupe,formation_run_id])
            recovered = uow.cursor.fetchone()
            if recovered:
                if recovered[2].get("owner_recovery_reason") != recovery_reason:
                    raise KernelError("CREATION_RECOVERY_REQUEST_DRIFT", "Recovery key already binds a different reason")
                return ({"runtime_job_id":recovered[0],"status":recovered[1],"deduplicated":True},)
        uow.cursor.execute(f"""SELECT run.formation_run_id,run.project_id,run.frozen_input_digest,
                run.frozen_stage_inputs #>> '{{generation_policy,auto_authorization,authorized_by_principal_id}}',
                latest.input_snapshot,latest.result,latest.status
            FROM authority_story_formation_run run
            LEFT JOIN LATERAL (
                SELECT job.input_snapshot,receipt.result,job.status FROM authority_runtime_job job
                LEFT JOIN LATERAL (SELECT result FROM authority_runtime_job_result
                    WHERE runtime_job_id=job.runtime_job_id ORDER BY created_at DESC,result_id DESC LIMIT 1) receipt ON TRUE
                WHERE job.job_kind='BOOK_CREATION_ADVANCE' AND job.subject_id=run.formation_run_id
                  AND job.project_id=run.project_id ORDER BY job.created_at DESC,job.runtime_job_id DESC LIMIT 1
            ) latest ON TRUE
            WHERE run.frozen_stage_inputs #>> '{{generation_policy,contract_version}}' IN ('formation-generation.v5','formation-generation.v7')
              AND run.lifecycle<>'ABORTED' AND (%s='' OR run.formation_run_id=%s)
              AND COALESCE(latest.status,'')<>'CANCELLED'
              AND COALESCE(latest.result->>'wait_class','') NOT IN ('COMPLETED','CANCELLED')
              AND (%s OR COALESCE(latest.status,'')<>'DEAD_LETTER' OR latest.input_snapshot->'progress' IS DISTINCT FROM jsonb_build_array({_CREATION_PROGRESS_COLUMNS}))
              AND (%s OR latest.result IS NULL OR latest.result->'progress' IS DISTINCT FROM jsonb_build_array({_CREATION_PROGRESS_COLUMNS}))
              AND NOT EXISTS (SELECT 1 FROM authority_runtime_job job WHERE job.job_kind='BOOK_CREATION_ADVANCE'
                AND job.project_id=run.project_id AND job.subject_id=run.formation_run_id
                AND job.status IN ('READY','RETRY_WAIT','CLAIMED','RUNNING','CHECKPOINTED'))
            ORDER BY run.updated_at,run.formation_run_id LIMIT %s FOR UPDATE OF run SKIP LOCKED""", [formation_run_id, formation_run_id, bool(recovery_reason), bool(recovery_reason), limit])
        candidates = tuple(uow.cursor.fetchall())
        scheduled = []
        for identity, project, digest, actor, previous, result, status in candidates:
            progress = list(creation_progress(database_url, project_id=project, formation_run_id=identity))
            if status == "CANCELLED" or (not recovery_reason and status == "DEAD_LETTER" and progress == (previous or {}).get("progress")):
                continue
            if result and (result.get("wait_class") in {"COMPLETED", "CANCELLED"}
                           or not recovery_reason and result.get("progress") == progress):
                continue
            sequence = int((previous or {}).get("sequence", -1)) + 1
            scheduled.append(jobs.schedule_in_uow(uow, RuntimeJobSpec(job_kind="BOOK_CREATION_ADVANCE", runtime_group="book_creation",
                subject_kind="STORY_FORMATION_RUN", subject_id=identity, project_id=project,
                dedupe_key=recovery_dedupe or f"{identity}:creation:{sequence}", input_snapshot={"contract_version": "creation-coordination.v1",
                    "formation_run_id": identity, "frozen_input_digest": digest, "operator_id": actor,
                    "sequence": sequence, "stagnant_windows": 0, "progress": progress,
                    **({"owner_recovery_reason": recovery_reason} if recovery_reason else {})}, max_attempts=3)))
        uow.commit()
    return tuple(scheduled)


def execute_creation_claim(jobs: RuntimeJobAuthority, claim: Any, *, composition: Any, content: Any,
                           chapter: Any, formation_worker: Any, book_worker: Any,
                           maximum_ticks: int = 20, work_window_seconds: int = 30) -> dict[str, Any]:
    from novel_forge.modules.command_kernel.lease_heartbeat import LeaseHeartbeatGuard

    if (claim.job_kind, claim.runtime_group, claim.subject_kind) != (
            "BOOK_CREATION_ADVANCE", "book_creation", "STORY_FORMATION_RUN"):
        raise ValueError("Creation worker requires its governed Formation envelope")
    jobs.start(claim)
    handed_off = False
    try:
        run = composition.formation.require(claim.subject_id)
        if (run["project_id"] != claim.project_id or run["frozen_input_digest"] != claim.input_snapshot["frozen_input_digest"]
                or composition.principal.principal_id != claim.input_snapshot["operator_id"]):
            raise KernelError("CREATION_EXECUTOR_BINDING_CONFLICT", "Configured operator or frozen Formation changed")
        composition.principal.require("book.authority.execute", claim.project_id)
        with LeaseHeartbeatGuard(lambda: jobs.heartbeat(claim, lease_seconds=60), lease_seconds=60,
                                 label=f"creation:{claim.attempt_id}"):
            try:
                result = continue_creation(composition=composition, content=content, chapter=chapter,
                    formation_run_id=claim.subject_id, formation_worker=formation_worker, book_worker=book_worker,
                    maximum_ticks=maximum_ticks, deadline=monotonic() + work_window_seconds, execution_probe=lambda: jobs.assert_live(claim),
                    creation_job_id=claim.runtime_job_id)
            except KernelError as error:
                if error.code not in {"PLANNING_RESULT_REPAIR_BOUND_EXCEEDED", "PLANNING_REPAIR_BOUND_EXCEEDED"}:
                    raise
                result = {"formation_run_id": claim.subject_id, "stop_reason": error.code,
                    "failure": {"code": error.code, "message": str(error)},
                    "recovery_instruction": "Inspect retained failed proposals and exact diagnostics. A new author decision or approved future input change must resolve the cause; repeating recovery cannot expand the repair allowance."}
        progress = list(creation_progress(jobs.database_url, project_id=claim.project_id, formation_run_id=claim.subject_id))
        stagnant = int(claim.input_snapshot.get("stagnant_windows", 0)) + 1 if creation_material_progress(progress) == creation_material_progress(claim.input_snapshot.get("progress")) else 0
        reason = result["stop_reason"]
        waiting = creation_wait_class(reason)
        receipt = {key: value for key, value in result.items() if key != "checkpoint"}
        receipt.update(stop_reason=reason, wait_class=waiting, progress=progress,
                       executor="book-authority-worker", next_action="INSPECT_OWNER_EVIDENCE",
                       checkpoint_ref=claim.subject_id)
        if waiting in {"TECHNICAL_WAIT", "RECONCILIATION_REQUIRED"}:
            delay = min(300, 5 * 2 ** min(stagnant, 6))
            sequence = int(claim.input_snapshot["sequence"]) + 1
            receipt.update(next_action="RECONCILE_SAME_IDENTITIES" if waiting == "RECONCILIATION_REQUIRED" else "RESUME_SAME_FROZEN_INPUTS",
                           retry_after_seconds=delay)
            next_job = RuntimeJobSpec(job_kind=claim.job_kind, runtime_group=claim.runtime_group,
                subject_kind=claim.subject_kind, subject_id=claim.subject_id, project_id=claim.project_id,
                dedupe_key=f"{claim.subject_id}:creation:{sequence}",
                input_snapshot={**claim.input_snapshot, "sequence": sequence, "progress": progress, "stagnant_windows": stagnant},
                available_at=datetime.now(timezone.utc) + timedelta(seconds=delay), max_attempts=3)
            handoff = jobs.complete_and_schedule_continuation(claim, receipt, next_job)
            handed_off = True
            return {**receipt, **handoff}
        jobs.complete(claim, receipt)
        handed_off = True
        return receipt
    except Exception as error:
        if not handed_off and jobs.get(claim.runtime_job_id)["status"] == "SUCCEEDED":
            with AuthorityUnitOfWork(jobs.database_url) as uow:
                uow.cursor.execute("SELECT result FROM authority_runtime_job_result WHERE runtime_job_id=%s AND attempt_id=%s", [claim.runtime_job_id, claim.attempt_id])
                committed = uow.cursor.fetchone()
            if committed:
                return committed[0]
        if not handed_off:
            jobs.fail(claim, {"code": getattr(error, "code", type(error).__name__), "message": str(error),
                             "formation_run_id": claim.subject_id}, retry_delay_seconds=30, cause=error)
        raise


def creation_status(database_url: str, *, project_id: str, formation_run_id: str, principal: Any) -> dict[str, Any]:
    from novel_forge.storage.story_formation_repositories import StoryFormationRepository

    principal.require("book.authority.query", project_id)
    with AuthorityUnitOfWork(database_url) as uow:
        run = StoryFormationRepository(uow.cursor).require(formation_run_id)
        if run["project_id"] != project_id:
            raise PermissionError("Formation is outside the requested Project")
        uow.cursor.execute("""SELECT job.runtime_job_id,job.status,job.available_at,job.last_error,receipt.result
            FROM authority_runtime_job job LEFT JOIN LATERAL (SELECT result FROM authority_runtime_job_result
                WHERE runtime_job_id=job.runtime_job_id ORDER BY created_at DESC,result_id DESC LIMIT 1) receipt ON TRUE
            WHERE job.job_kind='BOOK_CREATION_ADVANCE' AND job.subject_id=%s AND job.project_id=%s
            ORDER BY job.created_at DESC,job.runtime_job_id DESC LIMIT 1""", [formation_run_id, project_id])
        latest = uow.cursor.fetchone()
        cancellation = StoryFormationRepository(uow.cursor).cancellation(formation_run_id)
        uow.cursor.execute("SELECT book_run_id,state,accepted_through_chapter,target_chapter_count,version,current_chapter FROM authority_book_production WHERE project_id=%s AND stable_idempotency_key=%s", [project_id, formation_run_id + ":production"])
        production_row = uow.cursor.fetchone()
        production = dict(zip(("book_run_id", "state", "accepted_chapters", "target_chapters", "version", "saved_chapters"), production_row, strict=True)) if production_row else None
        from novel_forge.modules.command_kernel.budget_runtime import unresolved_cli_outcomes
        formation_unresolved = unresolved_cli_outcomes(uow.cursor, project_id, book_id=run["book_id"]) if not production else []
        candidates = []
        candidate_ids = run["recovery_instruction"].get("candidate_asset_version_ids") or StoryFormationRepository(uow.cursor).approval_wait(formation_run_id, "CREATIVE_SEARCH").get("candidate_asset_version_ids", [])
        for ordinal, identity in enumerate(candidate_ids, 1):
            asset = AuthorityAssetQuery(database_url).require(project_id=project_id, asset_version_id=identity)
            uow.cursor.execute("SELECT schema_version FROM authority_asset_version WHERE asset_version_id=%s", [identity])
            schema_version = uow.cursor.fetchone()[0]
            candidates.append({"number": ordinal, "asset_version_id": identity, "content_hash": asset.content_hash,
                "schema_version": schema_version, "content": asset.content})
    state = "INTERNAL_ACCEPTANCE_COMPLETE" if production and production["state"] == "COMPLETED" else "CANCELLATION_REQUESTED" if cancellation else "AUTHOR_DECISION" if run["lifecycle"] == "WAITING_APPROVAL" else "PRODUCING"
    if latest and latest[1] == "DEAD_LETTER" and state == "PRODUCING":
        state = "OWNER_RECOVERY_REQUIRED"
    if latest and latest[1] == "SUCCEEDED" and state == "PRODUCING":
        state = str((latest[4] or {}).get("wait_class") or state)
        if state == "COMPLETED":
            state = "INTERNAL_ACCEPTANCE_COMPLETE" if production and production["state"] == "COMPLETED" else "MANUSCRIPT_READY" if production and production["saved_chapters"] >= production["target_chapters"] else "OWNER_RECOVERY_REQUIRED"
    from .queries import PostgresBookProductionQuery

    unresolved = PostgresBookProductionQuery(database_url).unresolved_chapter_effects(book_run_id=production["book_run_id"]) if production else formation_unresolved
    if unresolved:
        state = "RECONCILIATION_REQUIRED"
    return {
        "formation_run_id": formation_run_id,
        "production": production,
        "author_state": state,
        "unresolved_external_effects": unresolved,
        "next_action": "RECONCILE_ORIGINAL_EXTERNAL_EFFECTS"
        if state == "RECONCILIATION_REQUIRED"
        else "RECOVER_ORIGINAL_CREATION_AFTER_RESOLVING_RETAINED_FAILURE"
        if state == "OWNER_RECOVERY_REQUIRED"
        else "WAIT_FOR_NATIVE_EXECUTOR"
        if state == "PRODUCING"
        else state,
        "responsible_party": "RUNTIME_OWNER"
        if state in {"OWNER_RECOVERY_REQUIRED", "RECONCILIATION_REQUIRED"}
        else "AUTHOR"
        if state == "AUTHOR_DECISION"
        else "BOOK_AUTHORITY_WORKER",
        "delivery": {
            "required_action": "READ_EDIT_OR_EXPORT_CURRENT_MANUSCRIPT",
            "export_status": "AVAILABLE_FOR_SAVED_PROSE",
            "query_url": f"/product/editor/manuscripts?project_id={project_id}&book_run_id={production['book_run_id']}" if production else "",
            "literary_quality": "NOT_PROVEN",
        },
        "formation_lifecycle": run["lifecycle"],
        "stage": run["current_stage"],
        "version": run["version"],
        "cancellation": cancellation,
        "candidates": candidates,
        "failure": run["failure"] or ((latest[4] or {}).get("failure", {}) if latest else {}),
        "recovery_instruction": run["recovery_instruction"] or ((latest[4] or {}).get("recovery_instruction", {}) if latest else {}),
        "coordination": dict(
            zip(
                ("runtime_job_id", "status", "next_attempt_at", "error", "result"),
                latest,
            )
        )
        if latest
        else None,
        "progress": list(
            creation_progress(
                database_url, project_id=project_id, formation_run_id=formation_run_id
            )
        ),
    }


def execute_creation_command(settings: Any, args: Any, *, request_input: dict[str, Any] | None = None, brief_source: tuple[str, str] | None = None) -> dict[str, Any]:
    from copy import deepcopy
    from dataclasses import replace
    import json
    from types import SimpleNamespace
    from novel_forge.api.authority_dependencies import (authority_release_identity, build_trusted_principal_resolver,
        build_content_authority_application, build_production_execution_composition,
        build_chapter_authority_application, build_book_production_composition)
    from novel_forge.modules.book_design_authority.formation_domain import StoryFormationInput, deterministic_story_formation_run_id
    from novel_forge.modules.book_design_authority.formation import StartStoryFormationCommand
    from novel_forge.modules.book_design_authority.query import BookDesignAuthorityQuery
    from novel_forge.modules.content_authority.application import ContentOperationRequest
    from novel_forge.modules.production_execution.execution_template import selected_book_template
    from novel_forge.modules.capability_packs.validation_deployment import (
        install_chapter_validation_pack, install_longform_validation_pack, register_validation_runtime_definitions)
    from novel_forge.modules.capability_packs.longform_profiles import build_story_planning_pack_profile
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork

    if args.maximum_ticks <= 0 or args.work_window_seconds <= 0:
        raise ValueError("Creative creation requires a positive execution window")
    args = SimpleNamespace(**vars(args))
    explicit_creation_policy = args.creation_policy_file is not None
    if args.creation_policy_file is None:
        args.creation_policy_file = args.repository_root / "config/execution_templates/creation_inputs.json"
    if args.action == "start" and args.idempotency_key:
        args.idempotency_key = f"creation:{args.project_id}:{args.book_id}:{args.idempotency_key}"
    runtime_values = creation_runtime_environment(args.project_id)
    settings = replace(settings, root=args.repository_root.resolve())
    resolver = build_trusted_principal_resolver()
    principal = resolver.resolve_api_principal()
    principal.require("book.authority.execute", args.project_id)
    if args.action == "status":
        return creation_status(settings.database_url, project_id=args.project_id,
                               formation_run_id=args.formation_run_id, principal=principal)
    build_id, sha = authority_release_identity()
    content = build_content_authority_application(settings)
    formation_id = args.formation_run_id
    existing_formation = None
    if args.action == "start":
        if (request_input is None and not args.input_file) or not all((args.workspace_id, args.book_id, args.idempotency_key)):
            raise ValueError("Start requires current work input, exact Book scope and stable idempotency key")
        inputs = deepcopy(request_input) if request_input is not None else json.loads(args.input_file.read_text())
        required = {"version", "brief", "target_chapters", "language_contract"}
        if not required <= set(inputs) or set(inputs) - required - {"title", "chapter_length", "creative_candidates", "author_creative_foundation", "comparison_policy", "input_selection", "execution_window"} or inputs["version"] not in {"creation-request.v1", "creation-request.v2"}:
            raise ValueError("Creation input must declare current brief, scope and language")
        inputs["title"], generated_title = creation_title(inputs)
        if (not isinstance(inputs["target_chapters"], int) or isinstance(inputs["target_chapters"], bool)
                or not 1 <= inputs["target_chapters"] <= 10000 or not isinstance(inputs["brief"], dict)
                or not isinstance(inputs["title"], str) or not inputs["title"].strip()
                or not isinstance(inputs["language_contract"], dict)
                or not isinstance(inputs["language_contract"].get("required_language"), str)
                or not inputs["language_contract"]["required_language"].strip()):
            raise ValueError("Creation requires a typed current work request")
        from .creation_window import validate_execution_window
        execution_window = validate_execution_window(inputs.get("execution_window"), target_chapters=inputs["target_chapters"])
        from novel_forge.modules.creative.input_selection import validate_input_selection, require_input_scope, brief_input_assets
        selection = validate_input_selection(inputs.get("input_selection") or {
            "contract_version": "creative-input-selection.v1", "book_id": args.book_id,
            "source_kind": "CURRENT_AUTHOR_INPUT", "purpose": "WORK_PRODUCTION",
            "intent_ref": args.idempotency_key})
        if selection["book_id"] != args.book_id:
            raise ValueError("CREATION_INPUT_BOOK_MISMATCH")
        saved_selection = inputs["brief"].pop("creative_input_selection", None) if brief_source else None
        if saved_selection:
            require_input_scope({"creative_input_selection": saved_selection}, project_id=args.project_id,
                workspace_id=args.workspace_id, book_id=args.book_id)
            selection = validate_input_selection({key: value for key, value in saved_selection.items()
                if key not in {"project_id", "workspace_id", "selected_by_actor_id", "selection_operation_id"}})
            if inputs.get("input_selection") and inputs["input_selection"] != selection:
                raise ValueError("CREATION_INPUT_SELECTION_DRIFT")
        author_direction = inputs.get("author_creative_foundation")
        automatic_comparison = args.creative_selection == "AUTO_COMPARISON" and not author_direction
        from novel_forge.modules.story_planning_runtime.narrative_search import CREATIVE_INTELLIGENCE_DIMENSIONS, validate_search_selection_policy
        comparison_policy = validate_search_selection_policy(inputs.get("comparison_policy") or {
            "contract_version": "narrative-search-comparison.v2",
            "dimension_weights": {dimension: 1 for dimension in CREATIVE_INTELLIGENCE_DIMENSIONS},
            "uncertainty_margin": 0.05, "tie_break": "STABLE_ID"}) if automatic_comparison else None
        if inputs.get("comparison_policy") and not automatic_comparison:
            raise ValueError("Comparison policy requires automatic direction comparison")
        candidate_count = 1 if author_direction else inputs.get("creative_candidates", 2)
        if not isinstance(candidate_count, int) or isinstance(candidate_count, bool) or not (1 if author_direction else 2) <= candidate_count <= 4:
            raise ValueError("Creative direction comparison requires two to four bounded alternatives")
        from novel_forge.modules.creative.domain import validate_creative_brief
        if brief_source and "project_id" in inputs["brief"]:
            if inputs["brief"]["project_id"] != args.project_id:
                raise ValueError("CREATION_BRIEF_SOURCE_DRIFT")
            inputs["brief"].pop("project_id")
        inputs["brief"] = validate_creative_brief(inputs["brief"])
        replay_identity = deterministic_story_formation_run_id(project_id=args.project_id, book_id=args.book_id,
            stable_idempotency_key=args.idempotency_key)
        with AuthorityUnitOfWork(settings.database_url) as uow:
            uow.cursor.execute("SELECT workspace_id,frozen_stage_inputs FROM authority_story_formation_run WHERE formation_run_id=%s AND project_id=%s", [replay_identity,args.project_id])
            replay = uow.cursor.fetchone()
        if replay:
            original = StoryFormationInput.from_mapping(replay[1])
            policy = original.generation_policy or {}
            original_brief = AuthorityAssetQuery(settings.database_url).require(project_id=args.project_id, asset_version_id=original.creative_brief_asset_version_id)
            profile = policy.get("creation_input_policy", {}).get("profiles", {}).get("production_profile", {}).get("content", {})
            original_selection = original_brief.content.get("creative_input_selection")
            if original_selection and any(original_selection.get(key) != value for key, value in selection.items()):
                raise ValueError("CREATION_INPUT_SELECTION_DRIFT")
            if (replay[0] != args.workspace_id or {"project_id":args.project_id, **inputs["brief"]} != {key: value for key, value in original_brief.content.items() if key != "creative_input_selection"}
                    or any(inputs[field] != policy.get(field) for field in ("title", "target_chapters"))
                    or inputs["language_contract"] != profile.get("language_contract")
                    or execution_window != profile.get("execution_window")
                    or candidate_count != policy.get("creative_candidates")
                    or author_direction != policy.get("author_creative_foundation")
                    or automatic_comparison != (policy.get("creative_selection") == "AUTO_COMPARISON")
                    or comparison_policy != policy.get("selection_policy")
                    or "chapter_length" in inputs and inputs["chapter_length"] != profile.get("chapter_length")
                    or brief_source and brief_source != (original.creative_brief_asset_version_id, original.creative_brief_content_hash)):
                raise ValueError("CREATION_FROZEN_INPUT_DRIFT")
            args.action, args.formation_run_id = "continue", replay_identity
            return execute_creation_command(settings, args)
        profiles = deepcopy(json.loads(args.creation_policy_file.read_text()))
        from novel_forge.modules.production_execution.codex_model_catalog import parse_codex_model_catalog
        catalog = parse_codex_model_catalog(os.environ.get("NOVEL_FORGE_CODEX_ROUTER_MODELS", ""))
        windows = [model["context_limit"] - model["output_limit"] for model in catalog if model["role"] == "PRIMARY"]
        if not windows or max(windows) <= 0:
            raise ValueError("CREATION_CONTEXT_WINDOW_REQUIRED")
        profile_content = profiles["profiles"]["production_profile"]["content"]
        if generated_title:
            profile_content["title_generation_contract"] = "generated-book-title.v1"
        if execution_window is not None:
            profile_content["execution_window"] = execution_window
        template_config = json.loads(args.execution_template_file.read_text())
        if template_config.get("author_workflow"):
            from .manuscript import AUTHOR_WORKFLOW
            if template_config["author_workflow"] != AUTHOR_WORKFLOW:
                raise ValueError("AUTHOR_WORKFLOW_INVALID")
            profile_content["author_workflow"] = dict(AUTHOR_WORKFLOW)
        profile_content.setdefault("chapter_context_policy", {"version": "book-chapter-context.v1",
            "draft_profile": "draft-context-profile-v4", "draft_token_budget": max(windows), "quality_token_budget": max(windows)})
        profile_content.setdefault("world_production_policy", {"version": "world-production-policy.v4",
            "max_provider_stages": 2, "context_token_budget": min(512000, max(windows))})
        profiles["profiles"]["production_profile"]["content"].update(
            target_chapter_count=inputs["target_chapters"], language_contract=inputs["language_contract"])
        if "chapter_length" in inputs:
            length = inputs["chapter_length"]
            if (not isinstance(length, dict) or set(length) != {"minimum", "maximum"}
                    or any(not isinstance(value, int) or isinstance(value, bool) for value in length.values())
                    or not 1 <= length["minimum"] <= length["maximum"] <= 100000):
                raise ValueError("CREATION_CHAPTER_LENGTH_INVALID")
            for fact in profiles["profiles"]["platform_profile"]["content"]["structured_facts"]:
                if fact["key"] == "platform_rules":
                    fact["value"]["chapter_length"] = dict(length)
            profiles["profiles"]["production_profile"]["content"]["chapter_length"] = dict(length)
        formation_id = deterministic_story_formation_run_id(project_id=args.project_id, book_id=args.book_id,
            stable_idempotency_key=args.idempotency_key)
        from novel_forge.modules.production_execution.execution_template import selected_template
        from novel_forge.modules.production_execution.routing_runtime import PostgresRoutingRegistry
        selected = selected_template(PostgresRoutingRegistry(settings.database_url).policy(args.project_id).get("policy", {}), args.book_id)
        if selected and selected["mode"] != "CREATIVE_VALIDATION":
            raise ValueError("CREATION_REQUIRES_EXPLICIT_VALIDATION_TEMPLATE")
        with AuthorityUnitOfWork(settings.database_url) as uow:
            uow.cursor.execute("SELECT formation_run_id FROM authority_story_formation_run WHERE project_id=%s AND book_id=%s AND formation_run_id<>%s", [args.project_id, args.book_id, formation_id])
            if uow.cursor.fetchone():
                raise ValueError("CREATION_ALREADY_ADMITTED_USE_ORIGINAL_FORMATION")
        ensure_creation_scope(settings, args, principal=principal, title=inputs["title"], build_id=build_id, sha=sha)
        from novel_forge.modules.book_design_authority.application import BookDesignAuthorityApplication, BookDesignAuthorityCommand
        query = BookDesignAuthorityQuery(settings.database_url)
        try:
            book = query.require_book(project_id=args.project_id, book_id=args.book_id)
        except KernelError as error:
            if error.code != "BOOK_NOT_FOUND":
                raise
            native = BookDesignAuthorityApplication(settings.database_url, application_build_id=build_id, commit_sha=sha)
            native.execute(BookDesignAuthorityCommand(definition_name="book.create", project_id=args.project_id,
                workspace_id=args.workspace_id, book_id=args.book_id, actor_id=principal.principal_id,
                service_identity="native-creation", idempotency_key=args.idempotency_key + ":book",
                trace_id="trace:" + args.idempotency_key, correlation_id=formation_id,
                payload={"schema_version": "book-authority.v1", "title": inputs["title"],
                    "production_profile": profiles["profiles"]["production_profile"]["content"],
                    "runtime_policy": {"execution_mode": "CREATIVE_VALIDATION", "template_source": str(args.execution_template_file)},
                    "release_identity": sha}), principal=principal)
            book = query.require_book(project_id=args.project_id, book_id=args.book_id)
        if book["workspace_id"] != args.workspace_id:
            raise ValueError("Creation Book is outside the current workspace")
        if brief_source:
            brief = AuthorityAssetQuery(settings.database_url).require(project_id=args.project_id, asset_version_id=brief_source[0])
            if brief.asset_type != "creative_brief" or brief.content_hash != brief_source[1] or {key: value for key, value in brief.content.items() if key != "creative_input_selection"} != {"project_id":args.project_id, **inputs["brief"]}:
                raise KernelError("CREATION_BRIEF_SOURCE_DRIFT", "Creation must bind the exact saved author brief")
        else:
            brief = content.execute(ContentOperationRequest(definition_name="creative.brief.create", project_id=args.project_id,
                workspace_id=args.workspace_id, actor_id=principal.principal_id, trace_id="trace:" + args.idempotency_key,
                correlation_id=formation_id, idempotency_key=args.idempotency_key + ":brief",
                input_assets=brief_input_assets(inputs["brief"], selection),
                payload={"brief": inputs["brief"], "input_selection": selection}), principal=principal)
        frozen = StoryFormationInput(creative_brief_asset_version_id=brief.asset_version_id,
            creative_brief_content_hash=brief.content_hash, generation_policy={
                "contract_version": "formation-generation.v7" if automatic_comparison else "formation-generation.v5" if args.creative_selection == "AUTHOR_COMPARISON" or author_direction else "formation-generation.v4",
                **({"creative_selection": "AUTHOR_DIRECTION" if author_direction else "AUTO_COMPARISON" if automatic_comparison else "AUTHOR_COMPARISON"} if args.creative_selection in {"AUTHOR_COMPARISON", "AUTO_COMPARISON"} or author_direction else {}),
                **({"selection_policy": comparison_policy, "strategy_directives": [
                    "Explore the author's central promise through a coherent causal direction with room for later development",
                    "Explore a distinct direction through character motivations and relationships while respecting the author's constraints",
                    "Explore a distinct situation or observation suited to the author's intended length and reader experience",
                    "Explore a distinct pacing and information structure preserving the author's intended tone and future writability",
                ][:candidate_count]} if automatic_comparison else {}),
                **({"author_creative_foundation": author_direction} if author_direction else {}),
                "approval_mode": "AUTO", "creative_candidates": candidate_count,
                "target_chapters": inputs["target_chapters"], "title": inputs["title"], "creation_input_policy": profiles,
                "auto_authorization": {"contract_version": "formation-auto-authorization.v1", "policy_version": "formation-auto-policy.v1",
                    "authorization_ref": "creation:" + args.idempotency_key, "authorized_by_principal_id": principal.principal_id,
                    "project_id": args.project_id, "workspace_id": args.workspace_id, "book_id": args.book_id,
                    "formation_run_id": formation_id, "allowed_actions": ["book_design.candidate.activate",
                        "book_design.candidate.decide", "story_planning.candidate.activate", "story_planning.candidate.approve"]}})
        with AuthorityUnitOfWork(settings.database_url) as uow:
            uow.cursor.execute("SELECT frozen_input_digest,expected_book_version FROM authority_story_formation_run WHERE formation_run_id=%s AND project_id=%s", [formation_id, args.project_id])
            existing_formation = uow.cursor.fetchone()
            if existing_formation and existing_formation[0] != frozen.digest:
                raise ValueError("CREATION_FROZEN_INPUT_DRIFT")
            admission = selected_book_template(uow.cursor, project_id=args.project_id, book_id=args.book_id, allow_literary_required=True)
        if admission is None:
            from novel_forge.modules.authority_handler_runtime.policy_commands import configure_execution_template
            configure_execution_template(settings, SimpleNamespace(project_id=args.project_id,
                workspace_id=args.workspace_id, book_id=args.book_id, policy_version="creation:" + formation_id,
                idempotency_key=args.idempotency_key + ":execution-template", template_file=args.execution_template_file))
        repository_root = args.repository_root.resolve()
        hashes = register_validation_runtime_definitions(settings.database_url, application_build_id=build_id, commit_sha=sha)
        if existing_formation is None:
            narrative = creation_narrative_execution(profiles)
            install_chapter_validation_pack(settings.database_url, repository_root=repository_root,
            project_id=args.project_id, workspace_id=args.workspace_id, book_id=args.book_id,
            application_build_id=build_id, commit_sha=sha, compiler=principal, approver=principal, agent_admin=principal,
            pack_id_override=runtime_values["NOVEL_FORGE_CHAPTER_CAPABILITY_PACK_ID"], runtime_environment=settings.environment,
            **narrative["chapter"])
            profile = build_story_planning_pack_profile(repository_root, operation_definition_hash=hashes["planning"],
            pack_id=runtime_values["NOVEL_FORGE_PLANNING_CAPABILITY_PACK_ID"], **narrative["planning"])
            install_longform_validation_pack(settings.database_url, profile=profile, pack_version=str(profile.manifest["identity"]["version"]), agent_generation=1,
            expected_activation_version=0, project_id=args.project_id, workspace_id=args.workspace_id, book_id=args.book_id,
            application_build_id=build_id, commit_sha=sha, compiler=principal, approver=principal, agent_admin=principal,
            agent_domain="story_planning", agent_scope_type="BOOK", runtime_environment=settings.environment)
    elif not formation_id:
        raise ValueError("Continue requires the original Formation identity")
    execution = build_production_execution_composition(settings, env=runtime_values)
    try:
        chapter = build_chapter_authority_application(settings, execution=execution, env=runtime_values)
        composition = build_book_production_composition(settings, principal=principal, execution=execution, chapter_application=chapter, env=runtime_values)
        if args.action == "start":
            composition.formation.admit(StartStoryFormationCommand(project_id=args.project_id, workspace_id=args.workspace_id,
                book_id=args.book_id, actor_id=principal.principal_id, expected_book_version=existing_formation[1] if existing_formation else book["version"],
                stable_idempotency_key=args.idempotency_key, trace_id="trace:" + args.idempotency_key,
                correlation_id=formation_id, frozen_input=frozen), principal=principal)
        run = composition.formation.require(formation_id)
        if run["project_id"] != args.project_id:
            raise PermissionError("Formation is outside authorized project")
        from novel_forge.modules.book_authority.creation_runtime import creation_cancellation, reconcile_creation_cancellation
        if args.action != "cancel" and creation_cancellation(settings.database_url, formation_id):
            reconcile_creation_cancellation(composition, formation_id)
            return {"stop_reason": "CANCELLED", **creation_status(settings.database_url,
                project_id=args.project_id, formation_run_id=formation_id, principal=principal)}
        if args.action == "cancel":
            composition.formation.cancel_continuation(formation_id, principal=principal,
                reason=args.reason, idempotency_key=args.idempotency_key)
            from novel_forge.modules.book_authority.creation_runtime import reconcile_creation_cancellation
            reconcile_creation_cancellation(composition, formation_id)
            schedule_creation_jobs(settings.database_url, limit=1, formation_run_id=formation_id)
            return {"stop_reason": "CANCELLED", **creation_status(settings.database_url,
                project_id=args.project_id, formation_run_id=formation_id, principal=principal)}
        from .reader_pack import ensure_creation_reader_pack

        ensure_creation_reader_pack(settings, SimpleNamespace(project_id=run["project_id"],
            workspace_id=run["workspace_id"], book_id=run["book_id"],
            repository_root=args.repository_root), principal=principal, build_id=build_id, sha=sha,
            pack_id=runtime_values["NOVEL_FORGE_READER_OUTCOME_CAPABILITY_PACK_ID"])
        if args.action == "recover":
            if not args.reason.strip():
                raise ValueError("Recovery requires a reason describing the resolved blocker")
            recovered = creation_recovery_record(settings.database_url, formation_id, args.reason, args.idempotency_key)
            if recovered:
                return {"stop_reason":"WORKER_OWNS_CONTINUATION", "scheduled":[recovered],
                    **creation_status(settings.database_url, project_id=args.project_id, formation_run_id=formation_id, principal=principal)}
            from novel_forge.modules.command_kernel.generation_isolation import recover_book_generations

            with AuthorityUnitOfWork(settings.database_url) as uow:
                uow.cursor.execute("""SELECT DISTINCT o.actor_id FROM authority_story_planning_generation g
                    JOIN authority_operation o USING(operation_id) WHERE g.project_id=%s AND g.book_id=%s""",
                    [run["project_id"], run["book_id"]])
                source_actors = [row[0] for row in uow.cursor.fetchall()]
            for source_actor in source_actors:
                recover_book_generations(composition.planning, project_id=run["project_id"],
                    book_id=run["book_id"], principal=principal, source_actor_id=source_actor)
            if run["lifecycle"] == "FAILED":
                composition.formation.resume(formation_id, expected_version=run["version"], principal=principal)
        if args.action == "choose":
            if args.candidate_number is not None:
                choices = creation_status(settings.database_url, project_id=args.project_id, formation_run_id=formation_id, principal=principal)["candidates"]
                selected = next((candidate for candidate in choices if candidate["number"] == args.candidate_number), None)
                if not selected:
                    raise ValueError("Candidate number is outside the current frozen alternatives")
                args.candidate_version, args.candidate_hash = selected["asset_version_id"], selected["content_hash"]
            if not all((args.candidate_version, args.candidate_hash, args.reason.strip(), args.idempotency_key)):
                raise ValueError("Choose requires the exact candidate/hash, comparison reason and stable decision key")
            with AuthorityUnitOfWork(settings.database_url) as uow:
                uow.cursor.execute("""SELECT command_payload FROM authority_operation
                    WHERE idempotency_scope='book:story-formation' AND idempotency_key=ANY(%s)
                      AND command_payload->>'formation_run_id'=%s ORDER BY created_at LIMIT 1""",
                    [[args.idempotency_key, f"{formation_id}:author-decision:{args.idempotency_key}"],formation_id])
                previous_decision = uow.cursor.fetchone()
            decision_version = previous_decision[0]["expected_version"] if previous_decision else run["version"]
            composition.formation.author_decision(formation_id, expected_version=decision_version,
                candidate_asset_version_id=args.candidate_version, candidate_content_hash=args.candidate_hash,
                decision="APPROVE", reason=args.reason, idempotency_key=args.idempotency_key, principal=principal)
        if (composition.formation.frozen_input(formation_id).generation_policy or {}).get("contract_version") in {"formation-generation.v5", "formation-generation.v7"}:
            from uuid import uuid4
            continuation_reason = args.reason if args.action == "recover" else "Authorized ordinary continue rechecks the current frozen inputs" if args.action == "continue" else ""
            continuation_key = args.idempotency_key if args.action == "recover" else "continue:" + (args.idempotency_key or str(uuid4())) if args.action == "continue" else ""
            scheduled = schedule_creation_jobs(settings.database_url, limit=1, formation_run_id=formation_id,
                recovery_reason=continuation_reason, recovery_key=continuation_key)
            if not args.foreground:
                return {"formation_run_id": formation_id, "stop_reason": "WORKER_OWNS_CONTINUATION",
                        "scheduled": list(scheduled), **creation_status(settings.database_url,
                            project_id=args.project_id, formation_run_id=formation_id, principal=principal)}
        progress, stagnant = None, 0
        while True:
            result = continue_creation(composition=composition, content=content, chapter=chapter, formation_run_id=formation_id,
                formation_worker=resolver.resolve_book_formation_worker_principal("creation-formation"),
                book_worker=resolver.resolve_worker_principal("creation-book"), maximum_ticks=args.maximum_ticks,
                deadline=monotonic() + args.work_window_seconds,
                creation_policy=json.loads(args.creation_policy_file.read_text()) if args.action == "continue" and explicit_creation_policy else None)
            if result["stop_reason"] != "YIELDED_CHECKPOINT" or args.yield_after_window:
                return {"formation_run_id": formation_id, **result}
            current = creation_material_progress(creation_progress(settings.database_url, project_id=args.project_id, formation_run_id=formation_id))
            stagnant = stagnant + 1 if current == progress else 0
            progress = current
            sleep(min(5, stagnant + 1))
    finally:
        execution.close()


def ensure_creation_scope(settings: Any, args: Any, *, principal: Any, title: str, build_id: str, sha: str) -> None:
    from novel_forge.modules.command_kernel.errors import KernelError
    from novel_forge.modules.project_authority.application import ProjectAuthorityApplication, ProjectAuthorityCommand
    from novel_forge.modules.project_authority.query import ProjectAuthorityQuery
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork

    application = ProjectAuthorityApplication(settings.database_url, application_build_id=build_id, commit_sha=sha)
    query = ProjectAuthorityQuery(settings.database_url)
    try:
        project = query.require_project(args.project_id)
    except KernelError as error:
        if error.code != "PROJECT_NOT_FOUND":
            raise
        application.execute(ProjectAuthorityCommand(definition_name="project_lifecycle.create", project_id=args.project_id,
            workspace_id=args.workspace_id, actor_id=principal.principal_id, idempotency_key=args.project_id + ":" + args.idempotency_key + ":project",
            trace_id="trace:" + args.idempotency_key, correlation_id=args.book_id, payload={"title": title}), principal=principal)
        project = query.require_project(args.project_id)
    if project["status"] != "ACTIVE":
        raise KernelError("PROJECT_LIFECYCLE_CONFLICT", "Creation requires an active authorized project")
    with AuthorityUnitOfWork(settings.database_url) as uow:
        uow.cursor.execute("SELECT project_id,book_id,status FROM authority_workspace WHERE workspace_id=%s", [args.workspace_id])
        workspace = uow.cursor.fetchone()
    if workspace is None:
        application.execute(ProjectAuthorityCommand(definition_name="project_workspace.create", project_id=args.project_id,
            workspace_id=project["workspace_id"], actor_id=principal.principal_id, idempotency_key=args.idempotency_key + ":workspace",
            trace_id="trace:" + args.idempotency_key, correlation_id=args.book_id,
            expected_version=project["version"], expected_current_asset_version_id=project["asset_version_id"],
            payload={"workspace_id": args.workspace_id}), principal=principal)
    elif workspace[0] != args.project_id or workspace[1] not in (None, "", args.book_id) or workspace[2] != "ACTIVE":
        raise KernelError("CREATION_WORKSPACE_SCOPE_CONFLICT", args.workspace_id)
