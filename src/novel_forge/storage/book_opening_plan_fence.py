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
    """INVARIANT: Authorize one active-plan mutation against the current Opening lease.

    The normal path proves the immutable PlanningGeneration binding is the
    current Runtime fence.  Recovery may retain that immutable predecessor
    binding, so its alternative path is the existing RecoveryAssessment-backed
    narrative replacement gate plus the exact current recovery RuntimeJob.
    Retained selected branches require immutable checkpoints and an unbroken
    RecoveryAdmission lineage, while the current Runtime lease remains mandatory.
    """
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
        recovery_authorized = _checkpoint_generation_authorized(
            cursor,
            project_id=project_id,
            book_id=book_id,
            generation_operation_id=generation_operation_id,
            candidate_asset_version_id=candidate_asset_version_id,
            original_binding=opening_binding,
            current_binding=required_binding,
        )
    if not direct_generation_authorized and not recovery_authorized:
        raise KernelError(
            "BOOK_OPENING_PLAN_MUTATION_NOT_AUTHORIZED",
            "Plan mutation is not bound to the live Opening or its recovery evidence",
        )


def _checkpoint_generation_authorized(
    cursor, *, project_id, book_id, generation_operation_id,
    candidate_asset_version_id, original_binding, current_binding,
):
    if (not original_binding
            or original_binding.get("opening_run_id") != current_binding["opening_run_id"]
            or original_binding.get("opening_execution_generation", 0)
            >= current_binding["opening_execution_generation"]):
        return False
    cursor.execute(
        """WITH RECURSIVE lineage AS (
          SELECT execution.* FROM authority_book_opening_execution execution
          WHERE execution.opening_run_id=%s AND execution.opening_execution_id=%s
            AND execution.generation=%s
          UNION ALL SELECT prior.* FROM authority_book_opening_execution prior
          JOIN lineage child ON child.opening_run_id=prior.opening_run_id
            AND child.predecessor_execution_id=prior.opening_execution_id
            AND child.predecessor_generation=prior.generation
          JOIN authority_book_opening_recovery_intent intent
            ON intent.recovery_intent_id=child.recovery_intent_id
            AND intent.opening_run_id=child.opening_run_id
            AND intent.predecessor_execution_id=prior.opening_execution_id
            AND intent.predecessor_generation=prior.generation
            AND intent.successor_generation=child.generation
          JOIN authority_book_opening_recovery_receipt receipt
            ON receipt.recovery_intent_id=intent.recovery_intent_id
            AND receipt.receipt_kind='RECOVERY_ADMISSION'
            AND receipt.successor_execution_id=child.opening_execution_id
        ) SELECT EXISTS(
          SELECT 1 FROM authority_book_opening_run opening
          JOIN authority_story_planning_generation generation
            ON generation.project_id=opening.project_id AND generation.book_id=opening.book_id
            AND generation.workspace_id=opening.workspace_id
          JOIN authority_operation operation ON operation.operation_id=generation.operation_id
            AND operation.status='SUCCEEDED'
          JOIN authority_story_narrative_search_candidate membership
            ON membership.generation_operation_id=generation.operation_id
            AND membership.candidate_asset_version_id=generation.candidate_asset_version_id
            AND membership.search_id=generation.narrative_search_id
            AND membership.branch_key=generation.narrative_search_branch_key
          JOIN authority_story_narrative_search search ON search.search_id=membership.search_id
            AND search.project_id=opening.project_id AND search.book_id=opening.book_id
            AND search.workspace_id=opening.workspace_id
          JOIN authority_story_narrative_search_decision decision ON decision.search_id=search.search_id
            AND decision.selected_candidate_asset_version_id=membership.candidate_asset_version_id
            AND search.selected_candidate_asset_version_id=membership.candidate_asset_version_id
          JOIN authority_book_opening_semantic_checkpoint checkpoint
            ON checkpoint.opening_run_id=opening.opening_run_id
            AND checkpoint.frozen_request_digest=opening.frozen_request_digest
            AND checkpoint.owning_authority='STORY_PLANNING'
            AND checkpoint.semantic_work_key='narrative-search-branch:'||search.search_id||':'||membership.branch_key
            AND checkpoint.checkpoint_sequence<=opening.current_checkpoint_sequence
          LEFT JOIN authority_story_narrative_branch_reconciliation_evidence reconciliation
            ON reconciliation.membership_id=membership.membership_id
            AND reconciliation.opening_run_id=opening.opening_run_id
          WHERE opening.opening_run_id=%s AND opening.project_id=%s AND opening.book_id=%s
            AND generation.operation_id=%s AND membership.candidate_asset_version_id=%s
            AND EXISTS(SELECT 1 FROM lineage WHERE opening_execution_id=%s AND generation=%s)
            AND EXISTS(SELECT 1 FROM lineage WHERE opening_execution_id=checkpoint.opening_execution_id
              AND generation=checkpoint.execution_generation)
            AND ((checkpoint.evidence_type='NARRATIVE_SEARCH_BRANCH'
              AND checkpoint.evidence_id=membership.membership_id
              AND checkpoint.evidence_hash=membership.branch_evidence_hash
              AND checkpoint.evidence_version=1)
              OR (checkpoint.evidence_type='NARRATIVE_SEARCH_BRANCH_RECONCILIATION'
                AND checkpoint.evidence_id=reconciliation.reconciliation_evidence_id
                AND checkpoint.evidence_hash=reconciliation.evidence_hash
                AND checkpoint.evidence_version=reconciliation.evidence_version)))""",
        [current_binding["opening_run_id"], current_binding["opening_execution_id"],
         current_binding["opening_execution_generation"], current_binding["opening_run_id"],
         project_id, book_id, generation_operation_id, candidate_asset_version_id,
         original_binding.get("opening_execution_id"), original_binding.get("opening_execution_generation")],
    )
    return bool(cursor.fetchone()[0])


__all__ = ["lock_and_assert_book_opening_plan_mutation"]
