"""INVARIANT: Canonical Book Opening fence for active Story Plan mutation."""

from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError


def lock_and_assert_book_opening_plan_mutation(
    cursor: Any,
    *,
    project_id: str,
    book_id: str,
    generation_operation_id: str,
    candidate_asset_version_id: str,
) -> None:

    cursor.execute(
        """
        SELECT book_id
        FROM authority_book
        WHERE project_id=%s AND book_id=%s
        FOR UPDATE
        """,
        [project_id, book_id],
    )
    if cursor.fetchone() is None:
        raise KernelError(
            "BOOK_NOT_FOUND",
            "Planning activation requires its exact Book Authority owner",
        )
    cursor.execute(
        """
        SELECT
            COALESCE(
                operation.command_payload->'payload'->'opening_execution_binding',
                operation.command_payload->'opening_execution_binding'
            ),
            evaluation.operation_id,evaluation.generation,
            evaluation.recovery_intent_id,
            EXISTS (
                SELECT 1
                FROM authority_runtime_job AS recovery_job
                WHERE recovery_job.project_id=generation.project_id
                  AND (
                      (
                          recovery_job.job_kind='BOOK_OPENING_EXECUTE'
                          AND recovery_job.runtime_group='book_opening'
                      ) OR (
                          recovery_job.job_kind=
                              'BOOK_OPENING_WORKFLOW_NODE_EXECUTE'
                          AND recovery_job.runtime_group=
                              'book_opening_workflow_v1'
                      )
                  )
                  AND recovery_job.subject_kind='BOOK_OPENING_RUN'
                  AND recovery_job.input_snapshot->>
                      'semantic_evaluation_operation_id'=evaluation.operation_id
                  AND recovery_job.input_snapshot->>
                      'semantic_execution_mode' IN (
                          'NEW_REPLACEMENT','RESUME_CURRENT'
                      )
            ) AS recovery_bound
        FROM authority_story_planning_generation AS generation
        JOIN authority_story_planning_candidate AS candidate
          ON candidate.generation_id=generation.generation_id
         AND candidate.project_id=generation.project_id
         AND candidate.book_id=generation.book_id
        JOIN authority_operation AS operation
          ON operation.operation_id=generation.operation_id
         AND operation.project_id=generation.project_id
         AND operation.definition_name='story_planning.generate'
        LEFT JOIN authority_narrative_evaluation_execution_head AS head
          ON head.project_id=generation.project_id
         AND head.candidate_asset_version_id=
             candidate.candidate_asset_version_id
        LEFT JOIN authority_narrative_evaluation_execution AS evaluation
          ON evaluation.project_id=head.project_id
         AND evaluation.candidate_asset_version_id=
             head.candidate_asset_version_id
         AND evaluation.evaluation_execution_id=head.current_execution_id
         AND evaluation.generation=head.current_generation
        WHERE generation.operation_id=%s
          AND generation.project_id=%s
          AND generation.book_id=%s
          AND candidate.candidate_asset_version_id=%s
        """,
        [
            generation_operation_id,
            project_id,
            book_id,
            candidate_asset_version_id,
        ],
    )
    generation = cursor.fetchone()
    opening_binding = (
        dict(generation[0])
        if generation is not None and isinstance(generation[0], dict)
        else {}
    )
    evaluation_operation_id = str(generation[1] or "") if generation else ""
    recovery_lineage_bound = bool(
        generation
        and (
            int(generation[2] or 0) > 1
            or str(generation[3] or "")
            or bool(generation[4])
        )
    )

    cursor.execute(
        """
        SELECT opening_run_id
        FROM authority_book_opening_run
        WHERE project_id=%s AND book_id=%s
          AND lifecycle IN ('ADMITTED','RUNNING','FAILED')
        FOR UPDATE
        """,
        [project_id, book_id],
    )
    active_openings = tuple(str(row[0]) for row in cursor.fetchall())
    if not active_openings:
        if opening_binding or recovery_lineage_bound:
            raise KernelError(
                "BOOK_OPENING_PLAN_MUTATION_NOT_AUTHORIZED",
                "Stale Book Opening generation cannot mutate Plans after its owner terminated",
            )
        return
    if len(active_openings) != 1:
        raise KernelError(
            "BOOK_OPENING_ACTIVE_WORKFLOW_CONFLICT",
            "Planning mutation found multiple active Book Openings",
        )
    if generation is None:
        raise KernelError(
            "BOOK_OPENING_PLAN_MUTATION_NOT_AUTHORIZED",
            "Active Book Opening plan mutation has no exact PlanningGeneration lineage",
        )
    recovery_gate_open = False
    if evaluation_operation_id:
        cursor.execute(
            "SELECT authority_narrative_replacement_gate_is_open(%s,%s)",
            [evaluation_operation_id, project_id],
        )
        recovery_gate_open = bool(cursor.fetchone()[0])

    cursor.execute(
        """
        SELECT
            opening.opening_run_id,
            execution.opening_execution_id,execution.generation,
            job.runtime_job_id,attempt.attempt_id,lease.lease_id,
            attempt.worker_id,attempt.fencing_token,
            COALESCE(job.input_snapshot->>'semantic_evaluation_operation_id',''),
            COALESCE(job.input_snapshot->>'semantic_execution_mode','NONE')
        FROM authority_book_opening_run AS opening
        JOIN authority_book_opening_execution AS execution
          ON execution.opening_run_id=opening.opening_run_id
         AND execution.opening_execution_id=opening.current_execution_id
         AND execution.generation=opening.current_execution_generation
        JOIN authority_runtime_job AS job
          ON job.runtime_job_id=execution.runtime_job_id
         AND (
             (
                 opening.workflow_contract_version='book-opening-workflow-v1'
                 AND opening.execution_contract_version=
                     'book-opening-execution-v3'
                 AND job.job_kind='BOOK_OPENING_WORKFLOW_NODE_EXECUTE'
                 AND job.runtime_group='book_opening_workflow_v1'
             ) OR (
                 opening.workflow_contract_version='legacy-monolithic-v2'
                 AND opening.execution_contract_version=
                     'book-opening-execution-v2'
                 AND job.job_kind='BOOK_OPENING_EXECUTE'
                 AND job.runtime_group='book_opening'
             )
         )
         AND job.current_attempt_id=execution.current_attempt_id
         AND job.current_fencing_token=execution.current_fencing_token
         AND job.claimed_by=execution.current_worker_id
        JOIN authority_runtime_job_attempt AS attempt
          ON attempt.runtime_job_id=job.runtime_job_id
         AND attempt.attempt_id=job.current_attempt_id
         AND attempt.lease_id=execution.current_lease_id
         AND attempt.worker_id=job.claimed_by
         AND attempt.fencing_token=job.current_fencing_token
        JOIN authority_runtime_job_lease AS lease
          ON lease.runtime_job_id=job.runtime_job_id
         AND lease.attempt_id=attempt.attempt_id
         AND lease.lease_id=attempt.lease_id
         AND lease.worker_id=attempt.worker_id
         AND lease.fencing_token=attempt.fencing_token
        WHERE opening.opening_run_id=%s
          AND opening.project_id=%s AND opening.book_id=%s
          AND opening.lifecycle='RUNNING'
          AND execution.lifecycle='RUNNING'
          AND job.status='RUNNING' AND attempt.status='RUNNING'
          AND lease.status='HELD'
          AND lease.lease_expires_at>clock_timestamp()
        FOR UPDATE OF opening,execution,job,attempt,lease
        """,
        [active_openings[0], project_id, book_id],
    )
    live = cursor.fetchone()
    if live is None:
        raise KernelError(
            "BOOK_OPENING_PLAN_MUTATION_NOT_AUTHORIZED",
            "Planning mutation has no exact live Book Opening Runtime fence",
        )
    required_binding = {
        "opening_run_id": str(live[0]),
        "opening_execution_id": str(live[1]),
        "opening_execution_generation": int(live[2]),
        "runtime_job_id": str(live[3]),
        "runtime_attempt_id": str(live[4]),
        "runtime_lease_id": str(live[5]),
        "runtime_worker_id": str(live[6]),
        "runtime_fencing_token": int(live[7]),
    }
    direct_generation_authorized = opening_binding == required_binding
    recovery_authorized = (
        recovery_gate_open
        and evaluation_operation_id == str(live[8])
        and str(live[9]) in {"NEW_REPLACEMENT", "RESUME_CURRENT"}
    )
    if not direct_generation_authorized and not recovery_authorized:
        raise KernelError(
            "BOOK_OPENING_PLAN_MUTATION_NOT_AUTHORIZED",
            "Plan mutation is not bound to the live Opening or its recovery evidence",
        )


__all__ = ["lock_and_assert_book_opening_plan_mutation"]
