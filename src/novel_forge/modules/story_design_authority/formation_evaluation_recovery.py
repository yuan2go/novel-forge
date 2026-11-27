from __future__ import annotations

from copy import deepcopy
from typing import Any

from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.runtime import OperationTransitionCommand, transition_operation_in_uow
from novel_forge.modules.command_kernel.service import admit_command_in_uow


PREFLIGHT_FAILURE_CODES = frozenset({
    "NARRATIVE_EVALUATION_DEPENDENCY_DRIFT",
    "NARRATIVE_EVALUATION_PROVIDER_CONTEXT_INVALID",
    "NARRATIVE_EVALUATION_PROVIDER_CONTEXT_BUDGET_EXCEEDED",
})


def require_live_formation(uow, *, formation_run_id: str, project_id: str, book_id: str, frozen_input_digest: str) -> None:
    uow.cursor.execute("""
        SELECT EXISTS (
            SELECT 1 FROM authority_story_formation_run f
            JOIN authority_runtime_job job ON job.project_id=f.project_id
              AND job.subject_kind='STORY_FORMATION_RUN' AND job.subject_id=f.formation_run_id
              AND job.job_kind='STORY_FORMATION_ADVANCE' AND job.runtime_group='story_formation'
              AND job.status IN ('RUNNING','CHECKPOINTED')
              AND job.input_snapshot->>'formation_run_id'=f.formation_run_id
              AND job.input_snapshot->>'observed_stage'=f.current_stage
              AND job.input_snapshot->>'observed_version'=f.version::text
              AND job.input_snapshot->>'frozen_input_digest'=f.frozen_input_digest
            JOIN authority_runtime_job_attempt attempt ON attempt.runtime_job_id=job.runtime_job_id
              AND attempt.attempt_id=job.current_attempt_id AND attempt.worker_id=job.claimed_by
              AND attempt.fencing_token=job.current_fencing_token AND attempt.status=job.status
            JOIN authority_runtime_job_lease lease ON lease.runtime_job_id=job.runtime_job_id
              AND lease.attempt_id=attempt.attempt_id AND lease.lease_id=attempt.lease_id
              AND lease.worker_id=attempt.worker_id AND lease.fencing_token=attempt.fencing_token
              AND lease.status='HELD' AND lease.lease_expires_at>clock_timestamp()
            WHERE f.formation_run_id=%s AND f.project_id=%s AND f.book_id=%s
              AND f.frozen_input_digest=%s AND f.lifecycle='RUNNING' AND f.current_stage='BOOK_DESIGN'
        )
    """, [formation_run_id, project_id, book_id, frozen_input_digest])
    if not uow.cursor.fetchone()[0]:
        raise KernelError("NARRATIVE_EVALUATION_FORMATION_GATE_CLOSED", "Evaluation continuation requires the original Formation's live frozen stage and worker fence")


def try_admit_formation_continuation(application, uow, *, command, admission_command, current) -> dict[str, Any] | None:
    if current["operation_status"] != "FAILED_FINAL" or command.generator_operation_name != "book_design.propose":
        return None
    payload = current["command_payload"]["payload"]
    if payload.get("opening_execution_binding") or current["recovery_intent_id"]:
        return None
    if current["operation_actor_id"] != command.actor_id:
        raise KernelError("NARRATIVE_EVALUATION_RECOVERY_EVALUATOR_DRIFT", "Formation recovery must retain the trusted evaluator")
    uow.cursor.execute("""
        SELECT attempt.attempt_id,COALESCE(attempt.result->>'error_code',attempt.error->>'error_code'),
               operation.definition_snapshot->>'commit_sha',attempt.finished_at
        FROM authority_attempt attempt JOIN authority_operation operation USING(operation_id)
        WHERE attempt.operation_id=%s ORDER BY attempt.attempt_number DESC LIMIT 1
    """, [current["operation_id"]])
    failure = uow.cursor.fetchone()
    if failure is None or failure[1] not in PREFLIGHT_FAILURE_CODES:
        return None
    uow.cursor.execute("SELECT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=%s)", [current["operation_id"]])
    if uow.cursor.fetchone()[0]:
        raise KernelError("NARRATIVE_EVALUATION_EXTERNAL_EFFECT_RECONCILIATION_REQUIRED", "Formation preflight continuation requires proven absence of any Provider Effect")
    uow.cursor.execute("""
        SELECT f.formation_run_id,f.frozen_input_digest,f.version,resume.operation_id
        FROM authority_story_formation_run f
        JOIN authority_operation proposal ON proposal.operation_id=%s AND proposal.project_id=f.project_id
          AND proposal.workspace_id=f.workspace_id AND proposal.status='SUCCEEDED'
          AND proposal.definition_name='book_design.propose'
          AND proposal.command_payload->>'book_id'=f.book_id
          AND proposal.idempotency_key=f.formation_run_id||':book-design:propose'
        JOIN authority_operation resume ON resume.project_id=f.project_id AND resume.workspace_id=f.workspace_id
          AND resume.definition_name='story.formation.resume' AND resume.status='SUCCEEDED'
          AND resume.idempotency_key=f.formation_run_id||':resume:'||(f.version-1)::text
          AND resume.command_payload->>'formation_run_id'=f.formation_run_id
          AND resume.command_payload->>'book_id'=f.book_id
          AND resume.command_payload->>'expected_version'=(f.version-1)::text
          AND resume.causation_operation_id=f.root_operation_id AND resume.updated_at>%s
        WHERE f.project_id=%s AND f.workspace_id=%s AND f.book_id=%s
          AND f.lifecycle='RUNNING' AND f.current_stage='BOOK_DESIGN'
    """, [command.generation_operation_id, failure[3], command.project_id, command.workspace_id, command.book_id])
    formation = uow.cursor.fetchone()
    if formation is None:
        return None
    generation = int(current["generation"]) + 1
    if generation > 3:
        raise KernelError("NARRATIVE_EVALUATION_FORMATION_RECOVERY_EXHAUSTED", "Formation preflight recovery permits at most two successors")
    require_live_formation(uow, formation_run_id=formation[0], project_id=command.project_id, book_id=command.book_id, frozen_input_digest=formation[1])
    application._require_candidate_in_uow(uow, command)
    from .evaluation_runtime import _stable_id

    successor = deepcopy(admission_command)
    successor.update(
        logical_key=f"{command.candidate_asset_version_id}:formation-recovery:{generation}",
        idempotency_key=f"{current['idempotency_key']}:formation-recovery:{generation}",
        causation_id=current["operation_id"], causation_operation_id=current["operation_id"],
        input=deepcopy(current["command_payload"]),
        input_assets=[{"asset_version_id": item["asset_version_id"], "content_hash": item["content_hash"]} for item in current["input_asset_snapshot"]],
    )
    admitted = admit_command_in_uow(uow, successor, context=application._admission_context(command.actor_id))
    if admitted["replayed"]:
        raise KernelError("NARRATIVE_EVALUATION_REPLACEMENT_IDEMPOTENCY_CONFLICT", "Continuation Operation exists without its exact generation head")
    operation = application._operation_for_lineage_in_uow(uow, operation_id=str(admitted["operation_id"]), project_id=command.project_id, lock=True)
    execution_id = _stable_id("narrative-evaluation-execution", command.project_id, command.candidate_asset_version_id, generation)
    recovery_id = _stable_id("narrative-formation-recovery", current["operation_id"])
    uow.cursor.execute("""
        INSERT INTO authority_narrative_formation_recovery (
            recovery_id,project_id,workspace_id,book_id,formation_run_id,frozen_input_digest,formation_version,
            resume_operation_id,source_operation_id,successor_operation_id,candidate_asset_version_id,
            candidate_content_hash,successor_generation,evidence
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, [recovery_id,command.project_id,command.workspace_id,command.book_id,*formation,
          current["operation_id"],operation["operation_id"],command.candidate_asset_version_id,
          command.candidate_content_hash,generation,Jsonb({"source_attempt_id":failure[0],"error_code":failure[1],
          "source_release_sha":failure[2],"target_release_sha":application.commit_sha,
          "external_effect_disposition":"PROVEN_NO_EFFECT","source_status":"FAILED_FINAL"})])
    uow.cursor.execute("""
        INSERT INTO authority_narrative_evaluation_execution (
            evaluation_execution_id,project_id,book_id,candidate_asset_version_id,candidate_content_hash,generation,
            predecessor_execution_id,predecessor_generation,predecessor_operation_id,formation_recovery_ref,
            operation_id,idempotency_scope,idempotency_key,concurrency_key,lifecycle
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'ADMITTED')
    """, [execution_id,command.project_id,command.book_id,command.candidate_asset_version_id,command.candidate_content_hash,
          generation,current["evaluation_execution_id"],current["generation"],current["operation_id"],recovery_id,
          operation["operation_id"],operation["idempotency_scope"],operation["idempotency_key"],operation["concurrency_key"]])
    uow.cursor.execute("""
        UPDATE authority_narrative_evaluation_execution_head SET current_execution_id=%s,current_generation=%s,
            version=version+1,updated_at=transaction_timestamp()
        WHERE project_id=%s AND candidate_asset_version_id=%s AND current_execution_id=%s
          AND current_generation=%s AND version=%s
    """, [execution_id,generation,command.project_id,command.candidate_asset_version_id,current["evaluation_execution_id"],current["generation"],current["head_version"]])
    if uow.cursor.rowcount != 1:
        raise KernelError("NARRATIVE_EVALUATION_REPLACEMENT_STALE", "Formation continuation head CAS failed")
    transition_operation_in_uow(uow, OperationTransitionCommand(
        operation_id=str(operation["operation_id"]),project_id=command.project_id,
        expected_version=int(operation["version"]),expected_status="ADMITTED",target_status="READY",
        actor_id=command.actor_id,reason="Live resumed Formation authorized exact preflight continuation",
        trace_id=command.trace_id,correlation_id=command.correlation_id,causation_id=str(formation[3]),
    ))
    return {"operation_id":str(operation["operation_id"]),"operation_actor_id":command.actor_id,
            "evaluation_execution_id":execution_id,"generation":generation,"replayed":False}


def assert_formation_continuation_gate(uow, *, operation_id: str, project_id: str, recovery_id: str) -> None:
    uow.cursor.execute("SELECT authority_narrative_formation_gate_is_open(%s,%s,%s)", [operation_id,project_id,recovery_id])
    if not uow.cursor.fetchone()[0]:
        raise KernelError("NARRATIVE_EVALUATION_FORMATION_GATE_CLOSED", "Formation continuation requires exact recovery lineage and the original live worker fence")
