"""INVARIANT: a Book-bound evaluation must revalidate the exact live Opening execution and lease immediately before Provider dispatch."""

from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


_OPENING_BINDING_FIELDS = frozenset(
    {
        "opening_run_id",
        "opening_execution_id",
        "opening_execution_generation",
        "runtime_job_id",
        "runtime_attempt_id",
        "runtime_lease_id",
        "runtime_worker_id",
        "runtime_fencing_token",
    }
)


def _assert_live_generation_one_opening(
    uow: AuthorityUnitOfWork,
    *,
    project_id: str,
    book_id: str,
    opening_binding: dict[str, Any],
) -> None:

    if set(opening_binding) != _OPENING_BINDING_FIELDS:
        raise KernelError(
            "NARRATIVE_EVALUATION_OPENING_BINDING_INVALID",
            "generation-one semantic Evaluation has an incomplete Opening binding",
        )
    try:
        execution_generation = int(opening_binding["opening_execution_generation"])
        fencing_token = int(opening_binding["runtime_fencing_token"])
    except (TypeError, ValueError) as exc:
        raise KernelError(
            "NARRATIVE_EVALUATION_OPENING_BINDING_INVALID",
            "generation-one semantic Evaluation has an invalid Opening fence",
        ) from exc
    required_text = tuple(
        str(opening_binding[field] or "").strip()
        for field in _OPENING_BINDING_FIELDS
        if field not in {"opening_execution_generation", "runtime_fencing_token"}
    )
    if execution_generation <= 0 or fencing_token <= 0 or not all(required_text):
        raise KernelError(
            "NARRATIVE_EVALUATION_OPENING_BINDING_INVALID",
            "generation-one semantic Evaluation has an invalid Opening identity",
        )
    uow.cursor.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM authority_book_opening_run AS opening
            JOIN authority_book_opening_execution AS opening_execution
              ON opening_execution.opening_run_id=opening.opening_run_id
             AND opening_execution.opening_execution_id=%s
             AND opening_execution.generation=%s
             AND opening_execution.runtime_job_id=%s
             AND opening_execution.current_attempt_id=%s
             AND opening_execution.current_lease_id=%s
             AND opening_execution.current_worker_id=%s
             AND opening_execution.current_fencing_token=%s
             AND opening_execution.lifecycle='RUNNING'
             AND opening_execution.frozen_request_digest=
                 opening.frozen_request_digest
            JOIN authority_runtime_job AS job
              ON job.runtime_job_id=opening_execution.runtime_job_id
             AND job.project_id=opening.project_id
             AND (
                 (
                     opening.workflow_contract_version=
                         'book-opening-workflow-v1'
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
             AND job.subject_kind='BOOK_OPENING_RUN'
             AND job.subject_id=opening.opening_run_id
             AND job.input_hash=opening_execution.input_snapshot_hash
             AND job.lease_loss_policy='AUTHORITY_CONVERGENCE_REQUIRED'
             AND job.max_attempts=1
             AND job.status IN ('RUNNING','CHECKPOINTED')
             AND job.current_attempt_id=%s
             AND job.current_fencing_token=%s
             AND job.claimed_by=%s
             AND job.input_snapshot->>'opening_run_id'=
                 opening.opening_run_id
             AND job.input_snapshot->>'opening_execution_id'=
                 opening_execution.opening_execution_id
             AND job.input_snapshot->>'execution_generation'=
                 opening_execution.generation::text
            JOIN authority_runtime_job_attempt AS attempt
              ON attempt.runtime_job_id=job.runtime_job_id
             AND attempt.attempt_id=job.current_attempt_id
             AND attempt.lease_id=%s
             AND attempt.worker_id=job.claimed_by
             AND attempt.fencing_token=job.current_fencing_token
             AND attempt.status=job.status
            JOIN authority_runtime_job_lease AS lease
              ON lease.runtime_job_id=job.runtime_job_id
             AND lease.attempt_id=attempt.attempt_id
             AND lease.lease_id=attempt.lease_id
             AND lease.worker_id=attempt.worker_id
             AND lease.fencing_token=attempt.fencing_token
             AND lease.status='HELD'
             AND lease.lease_expires_at>clock_timestamp()
            WHERE opening.opening_run_id=%s
              AND opening.project_id=%s
              AND opening.book_id=%s
              AND opening.lifecycle='RUNNING'
              AND opening.recovery_state='READY'
              AND opening.current_execution_id=
                  opening_execution.opening_execution_id
              AND opening.current_execution_generation=
                  opening_execution.generation
        )
        """,
        [
            str(opening_binding["opening_execution_id"]),
            execution_generation,
            str(opening_binding["runtime_job_id"]),
            str(opening_binding["runtime_attempt_id"]),
            str(opening_binding["runtime_lease_id"]),
            str(opening_binding["runtime_worker_id"]),
            fencing_token,
            str(opening_binding["runtime_attempt_id"]),
            fencing_token,
            str(opening_binding["runtime_worker_id"]),
            str(opening_binding["runtime_lease_id"]),
            str(opening_binding["opening_run_id"]),
            project_id,
            book_id,
        ],
    )
    row = uow.cursor.fetchone()
    if row is None or not bool(row[0]):
        raise KernelError(
            "NARRATIVE_EVALUATION_BOOK_OPENING_EXECUTION_GATE_CLOSED",
            "generation-one semantic Evaluation lost its exact Book Opening execution fence",
        )


def _assert_live_replacement_opening(
    uow: AuthorityUnitOfWork,
    *,
    operation_id: str,
    project_id: str,
    book_id: str,
    evaluation_execution_id: str,
    generation: int,
    evaluation_recovery_intent_id: str,
    candidate_asset_version_id: str,
    candidate_content_hash: str,
    predecessor_execution_id: str,
    predecessor_generation: int,
    predecessor_operation_id: str,
    closed_code: str = "NARRATIVE_EVALUATION_REPLACEMENT_EXECUTION_GATE_CLOSED",
) -> None:

    uow.cursor.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM authority_book_opening_run AS opening
            JOIN authority_book_opening_execution AS opening_execution
              ON opening_execution.opening_run_id=opening.opening_run_id
             AND opening_execution.opening_execution_id=
                 opening.current_execution_id
             AND opening_execution.generation=
                 opening.current_execution_generation
             AND opening_execution.lifecycle='RUNNING'
             AND opening_execution.frozen_request_digest=
                 opening.frozen_request_digest
             AND opening_execution.recovery_intent_id IS NOT NULL
            JOIN authority_book_opening_recovery_intent AS recovery_intent
              ON recovery_intent.recovery_intent_id=
                 opening_execution.recovery_intent_id
             AND recovery_intent.opening_run_id=opening.opening_run_id
             AND recovery_intent.successor_generation=
                 opening_execution.generation
            JOIN authority_book_opening_recovery_assessment AS assessment
              ON assessment.recovery_assessment_id=
                 recovery_intent.recovery_assessment_id
             AND assessment.opening_run_id=opening.opening_run_id
             AND assessment.assessment_kind='RECOVERY'
             AND assessment.disposition NOT IN (
                 'UNKNOWN_AMBIGUOUS','RECONCILIATION_REQUIRED'
             )
             AND assessment.opening_execution_id=
                 recovery_intent.predecessor_execution_id
             AND assessment.execution_generation=
                 recovery_intent.predecessor_generation
             AND assessment.snapshot->'opening'->>'opening_run_id'=
                 opening.opening_run_id
             AND assessment.snapshot->'opening'->>'current_execution_id'=
                 recovery_intent.predecessor_execution_id
             AND assessment.snapshot->'opening'->>
                 'current_execution_generation'=
                 recovery_intent.predecessor_generation::text
             AND assessment.snapshot->'execution'->>'opening_execution_id'=
                 recovery_intent.predecessor_execution_id
             AND assessment.snapshot->'execution'->>'generation'=
                 recovery_intent.predecessor_generation::text
            JOIN authority_book_opening_recovery_receipt AS receipt
              ON receipt.receipt_kind='RECOVERY_ADMISSION'
             AND receipt.opening_run_id=opening.opening_run_id
             AND receipt.recovery_assessment_id=
                 assessment.recovery_assessment_id
             AND receipt.recovery_intent_id=
                 recovery_intent.recovery_intent_id
             AND receipt.predecessor_execution_id=
                 recovery_intent.predecessor_execution_id
             AND receipt.predecessor_generation=
                 recovery_intent.predecessor_generation
             AND receipt.successor_execution_id=
                 opening_execution.opening_execution_id
             AND receipt.successor_generation=opening_execution.generation
            JOIN authority_runtime_job AS job
              ON job.runtime_job_id=opening_execution.runtime_job_id
             AND job.project_id=opening.project_id
             AND (
                 (
                     opening.workflow_contract_version=
                         'book-opening-workflow-v1'
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
             AND job.subject_kind='BOOK_OPENING_RUN'
             AND job.subject_id=opening.opening_run_id
             AND job.input_hash=opening_execution.input_snapshot_hash
             AND job.lease_loss_policy='AUTHORITY_CONVERGENCE_REQUIRED'
             AND job.max_attempts=1
             AND job.status IN ('RUNNING','CHECKPOINTED')
             AND job.current_attempt_id IS NOT NULL
             AND job.current_fencing_token>0
             AND job.claimed_by<>''
             AND job.input_snapshot->>'opening_run_id'=
                 opening.opening_run_id
             AND job.input_snapshot->>'opening_execution_id'=
                 opening_execution.opening_execution_id
             AND job.input_snapshot->>'execution_generation'=
                 opening_execution.generation::text
             AND job.input_snapshot->>'frozen_request_digest'=
                 opening.frozen_request_digest
             AND job.input_snapshot->>'recovery_intent_id'=
                 recovery_intent.recovery_intent_id
             AND job.input_snapshot->>'semantic_evaluation_operation_id'=%s
             AND job.input_snapshot->>'semantic_evaluation_execution_id'=%s
             AND job.input_snapshot->>'semantic_evaluation_generation'=%s
             AND job.input_snapshot->>'semantic_execution_mode' IN (
                 'NEW_REPLACEMENT','RESUME_CURRENT'
             )
             AND receipt.result->>'recovery_intent_id'=
                 recovery_intent.recovery_intent_id
             AND receipt.result->>'opening_execution_id'=
                 opening_execution.opening_execution_id
             AND receipt.result->>'execution_generation'=
                 opening_execution.generation::text
             AND receipt.result->>'runtime_job_id'=job.runtime_job_id
             AND receipt.result->>'opening_run_id'=opening.opening_run_id
            JOIN authority_runtime_job_attempt AS attempt
              ON attempt.runtime_job_id=job.runtime_job_id
             AND attempt.attempt_id=job.current_attempt_id
             AND attempt.attempt_number=job.attempt_count
             AND attempt.lease_id=opening_execution.current_lease_id
             AND attempt.worker_id=job.claimed_by
             AND attempt.fencing_token=job.current_fencing_token
             AND attempt.status=job.status
            JOIN authority_runtime_job_lease AS lease
              ON lease.runtime_job_id=job.runtime_job_id
             AND lease.attempt_id=attempt.attempt_id
             AND lease.lease_id=attempt.lease_id
             AND lease.worker_id=attempt.worker_id
             AND lease.fencing_token=attempt.fencing_token
             AND lease.status='HELD'
             AND lease.lease_expires_at>clock_timestamp()
            WHERE opening.project_id=%s
              AND opening.book_id=%s
              AND opening.lifecycle='RUNNING'
              AND opening.recovery_state='READY'
              AND opening_execution.current_attempt_id=attempt.attempt_id
              AND opening_execution.current_worker_id=attempt.worker_id
              AND opening_execution.current_fencing_token=
                  attempt.fencing_token
              AND opening_execution.predecessor_execution_id=
                  recovery_intent.predecessor_execution_id
              AND opening_execution.predecessor_generation=
                  recovery_intent.predecessor_generation
              AND (
                  (
                      job.input_snapshot->>'semantic_execution_mode'=
                          'NEW_REPLACEMENT'
                      AND recovery_intent.recovery_intent_id=%s
                      AND job.input_snapshot->>
                          'replacement_evaluation_operation_id'=%s
                      AND receipt.result->>
                          'replacement_evaluation_operation_id'=%s
                      AND receipt.result->>
                          'replacement_evaluation_execution_id'=%s
                      AND %s>1
                      AND assessment.snapshot->'semantic_evaluation'->>
                          'operation_id'=%s
                      AND assessment.snapshot->'semantic_evaluation'->>
                          'evaluation_execution_id'=%s
                      AND assessment.snapshot->'semantic_evaluation'->>
                          'generation'=%s
                      AND assessment.snapshot->'semantic_evaluation'->>
                          'candidate_asset_version_id'=%s
                      AND assessment.snapshot->'semantic_evaluation'->>
                          'candidate_content_hash'=%s
                  ) OR (
                      job.input_snapshot->>'semantic_execution_mode'=
                          'RESUME_CURRENT'
                      AND COALESCE(
                          job.input_snapshot->>
                              'replacement_evaluation_operation_id',''
                      )=''
                      AND COALESCE(
                          receipt.result->>
                              'replacement_evaluation_operation_id',''
                      )=''
                      AND COALESCE(
                          receipt.result->>
                              'replacement_evaluation_execution_id',''
                      )=''
                      AND assessment.snapshot->'semantic_evaluation'->>
                          'operation_id'=%s
                      AND assessment.snapshot->'semantic_evaluation'->>
                          'evaluation_execution_id'=%s
                      AND assessment.snapshot->'semantic_evaluation'->>
                          'generation'=%s
                      AND assessment.snapshot->'semantic_evaluation'->>
                          'candidate_asset_version_id'=%s
                      AND assessment.snapshot->'semantic_evaluation'->>
                          'candidate_content_hash'=%s
                  )
              )
        )
        """,
        [
            operation_id,
            evaluation_execution_id,
            str(generation),
            project_id,
            book_id,
            evaluation_recovery_intent_id,
            operation_id,
            operation_id,
            evaluation_execution_id,
            generation,
            predecessor_operation_id,
            predecessor_execution_id,
            str(predecessor_generation),
            candidate_asset_version_id,
            candidate_content_hash,
            operation_id,
            evaluation_execution_id,
            str(generation),
            candidate_asset_version_id,
            candidate_content_hash,
        ],
    )
    row = uow.cursor.fetchone()
    if row is None or not bool(row[0]):
        raise KernelError(
            closed_code,
            "semantic Evaluation has no exact live recovery execution gate",
        )


def _is_recovery_bound(
    uow: AuthorityUnitOfWork,
    *,
    operation_id: str,
    project_id: str,
    evaluation_execution_id: str,
    generation: int,
) -> bool:

    # Deliberately do not join through the outer lineage here.  Any durable
    # RuntimeJob that claims this exact semantic execution as NEW/RESUME makes
    # the ordinary generation-one path unavailable.  Broken outer lineage must
    # therefore reach the full gate and fail closed instead of disappearing
    # from this probe through an inner join.
    uow.cursor.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM authority_runtime_job AS job
            WHERE job.project_id=%s
              AND (
                  (
                      job.job_kind='BOOK_OPENING_EXECUTE'
                      AND job.runtime_group='book_opening'
                  ) OR (
                      job.job_kind='BOOK_OPENING_WORKFLOW_NODE_EXECUTE'
                      AND job.runtime_group='book_opening_workflow_v1'
                  )
              )
              AND job.subject_kind='BOOK_OPENING_RUN'
              AND job.input_snapshot->>'semantic_evaluation_operation_id'=%s
              AND job.input_snapshot->>'semantic_evaluation_execution_id'=%s
              AND job.input_snapshot->>'semantic_evaluation_generation'=%s
              AND job.input_snapshot->>'semantic_execution_mode' IN (
                  'NEW_REPLACEMENT','RESUME_CURRENT'
              )
        )
        """,
        [
            project_id,
            operation_id,
            evaluation_execution_id,
            str(generation),
        ],
    )
    row = uow.cursor.fetchone()
    return row is not None and bool(row[0])


def assert_narrative_replacement_execution_gate_in_uow(
    uow: AuthorityUnitOfWork,
    *,
    operation_id: str,
    project_id: str,
) -> dict[str, Any]:

    if not operation_id.strip() or not project_id.strip():
        raise KernelError(
            "NARRATIVE_EVALUATION_REPLACEMENT_GATE_IDENTITY_INVALID",
            "semantic replacement gate requires Operation and Project identity",
        )
    uow.cursor.execute(
        """
        SELECT evaluation.generation,evaluation.recovery_intent_id,
               evaluation.evaluation_execution_id,evaluation.book_id,
               head.current_execution_id=evaluation.evaluation_execution_id
                   AND head.current_generation=evaluation.generation,
               evaluation_operation.command_payload->'payload'->>
                   'generation_operation_id',
               generation_operation.project_id,
               COALESCE(
                   generation_operation.command_payload->'payload'->
                       'opening_execution_binding',
                   generation_operation.command_payload->
                       'opening_execution_binding'
               ),
               evaluation.candidate_asset_version_id,
               evaluation.candidate_content_hash,
               evaluation.predecessor_execution_id,
               evaluation.predecessor_generation,
               evaluation.predecessor_operation_id,
               evaluation_operation.command_payload->'payload'->>'book_id'=
                   evaluation.book_id
                   AND evaluation_operation.command_payload->'payload'->>
                       'candidate_asset_version_id'=
                       evaluation.candidate_asset_version_id
                   AND evaluation_operation.command_payload->'payload'->>
                       'candidate_content_hash'=evaluation.candidate_content_hash,
               COALESCE(
                   evaluation_operation.command_payload->'payload'->
                       'opening_execution_binding',
                   '{}'::jsonb
               )=COALESCE(
                   generation_operation.command_payload->'payload'->
                       'opening_execution_binding',
                   generation_operation.command_payload->
                       'opening_execution_binding',
                   '{}'::jsonb
               ),
               generation_operation.status IN ('WAITING_GATE','SUCCEEDED')
                   AND generation_output.operation_id=
                       generation_operation.operation_id
                   AND generation_output.asset_version_id=
                       evaluation.candidate_asset_version_id
                   AND generation_output.content_hash=
                       evaluation.candidate_content_hash
                   AND (
                       (
                           (
                               generation_operation.definition_name=
                                   evaluation_operation.command_payload->
                                       'payload'->>'generator_operation_name'
                               OR (
                                   generation_operation.definition_name=
                                       'story_planning.generate'
                                   AND generation_operation.command_payload->
                                       'payload'->>'generator_operation_name'=
                                       evaluation_operation.command_payload->
                                           'payload'->>
                                           'generator_operation_name'
                               )
                           )
                           AND COALESCE(
                               generation_operation.command_payload->'payload'->>
                                   'book_id',
                               generation_operation.command_payload->>'book_id'
                           )=evaluation.book_id
                       ) OR (
                           generation_operation.status='SUCCEEDED'
                           AND generation_operation.definition_name=CASE
                               evaluation_operation.command_payload->'payload'->>
                                   'generator_operation_name'
                               WHEN 'creative.candidates.generate' THEN
                                   'story_design.creative_foundation.author'
                               WHEN 'theme.candidates.generate' THEN
                                   'story_design.theme_contract.author'
                               WHEN 'ending.intent.generate' THEN
                                   'story_design.ending_intent.author'
                               WHEN 'reader.promise.generate' THEN
                                   'story_design.reader_promise.author'
                               WHEN 'world.design.generate' THEN
                                   'story_design.world_bible.author'
                               WHEN 'character.cast.generate' THEN
                                   'story_design.character_cast.author'
                               ELSE NULL
                           END
                           AND generation_asset.project_id=evaluation.project_id
                           AND generation_asset.asset_type=CASE
                               evaluation_operation.command_payload->'payload'->>
                                   'generator_operation_name'
                               WHEN 'creative.candidates.generate' THEN
                                   'creative_foundation'
                               WHEN 'theme.candidates.generate' THEN
                                   'theme_contract'
                               WHEN 'ending.intent.generate' THEN
                                   'ending_intent'
                               WHEN 'reader.promise.generate' THEN
                                   'reader_promise'
                               WHEN 'world.design.generate' THEN
                                   'world_bible'
                               WHEN 'character.cast.generate' THEN
                                   'character_cast'
                               ELSE NULL
                           END
                           AND generation_version.content_hash=
                               evaluation.candidate_content_hash
                           AND generation_version.content->>'project_id'=
                               evaluation.project_id
                           AND generation_version.content->>
                               'generator_operation_name'=
                               evaluation_operation.command_payload->'payload'->>
                                   'generator_operation_name'
                           AND generation_version.content->>'operator_authored'=
                               'true'
                           AND generation_version.content->>'provider_generated'=
                               'false'
                           AND design_state.source_kind='OPERATOR_AUTHORED'
                           AND design_state.generator_operation_name=
                               evaluation_operation.command_payload->'payload'->>
                                   'generator_operation_name'
                           AND design_state.lifecycle='MATERIALIZED'
                           AND design_state.qualification='STRUCTURALLY_VALID'
                           AND design_state.execution_evidence->>'operation_id'=
                               generation_operation.operation_id
                           AND design_state.execution_evidence->>
                               'authoring_operation_id'=
                               generation_operation.operation_id
                           AND design_state.execution_evidence->>
                               'operator_authored'='true'
                           AND design_state.execution_evidence->>
                               'provider_generated'='false'
                       )
                   )
                   AND (
                       (
                           evaluation.generation=1
                           AND evaluation_operation.causation_operation_id=
                               generation_operation.operation_id
                       ) OR (
                           evaluation.generation>1
                           AND evaluation_operation.causation_operation_id=
                               evaluation.predecessor_operation_id
                       )
                   )
        FROM authority_narrative_evaluation_execution AS evaluation
        JOIN authority_operation AS evaluation_operation
          ON evaluation_operation.operation_id=evaluation.operation_id
         AND evaluation_operation.project_id=evaluation.project_id
         AND evaluation_operation.definition_name=
             'story_design.semantic_evaluate'
        LEFT JOIN authority_operation AS generation_operation
          ON generation_operation.operation_id=
             evaluation_operation.command_payload->'payload'->>
                 'generation_operation_id'
         AND generation_operation.project_id=evaluation.project_id
        LEFT JOIN authority_operation_output_asset AS generation_output
          ON generation_output.operation_id=generation_operation.operation_id
         AND generation_output.asset_version_id=
             evaluation.candidate_asset_version_id
         AND generation_output.content_hash=evaluation.candidate_content_hash
        LEFT JOIN authority_asset_version AS generation_version
          ON generation_version.asset_version_id=
             generation_output.asset_version_id
        LEFT JOIN authority_asset AS generation_asset
          ON generation_asset.asset_id=generation_version.asset_id
        LEFT JOIN authority_story_design_version_state AS design_state
          ON design_state.project_id=evaluation.project_id
         AND design_state.asset_version_id=
             evaluation.candidate_asset_version_id
        LEFT JOIN authority_narrative_evaluation_execution_head AS head
          ON head.project_id=evaluation.project_id
         AND head.candidate_asset_version_id=
             evaluation.candidate_asset_version_id
        WHERE evaluation.operation_id=%s AND evaluation.project_id=%s
        """,
        [operation_id, project_id],
    )
    row = uow.cursor.fetchone()
    if row is None:
        raise KernelError(
            "NARRATIVE_EVALUATION_EXECUTION_NOT_FOUND",
            "semantic Evaluation Operation has no execution lineage",
        )
    generation = int(row[0])
    recovery_intent_id = str(row[1] or "")
    evaluation_execution_id = str(row[2] or "")
    book_id = str(row[3] or "")
    generation_operation_id = str(row[5] or "")
    generation_operation_project_id = str(row[6] or "")
    raw_opening_binding = row[7]
    candidate_asset_version_id = str(row[8] or "")
    candidate_content_hash = str(row[9] or "")
    predecessor_execution_id = str(row[10] or "")
    predecessor_generation = int(row[11] or 0)
    predecessor_operation_id = str(row[12] or "")
    if raw_opening_binding is None:
        opening_binding: dict[str, Any] = {}
    elif isinstance(raw_opening_binding, dict):
        opening_binding = dict(raw_opening_binding)
    else:
        raise KernelError(
            "NARRATIVE_EVALUATION_OPENING_BINDING_INVALID",
            "semantic Evaluation generation carries a malformed Opening binding",
        )
    if (
        generation <= 0
        or not evaluation_execution_id
        or not book_id
        or not bool(row[4])
        or not generation_operation_id
        or generation_operation_project_id != project_id
        or not candidate_asset_version_id
        or not candidate_content_hash
        or not bool(row[13])
        or not bool(row[14])
        or not bool(row[15])
        or (generation > 1 and not recovery_intent_id)
        or (
            generation == 1
            and (
                recovery_intent_id
                or predecessor_execution_id
                or predecessor_generation
                or predecessor_operation_id
            )
        )
        or (
            generation > 1
            and (
                not predecessor_execution_id
                or predecessor_generation != generation - 1
                or not predecessor_operation_id
            )
        )
    ):
        raise KernelError(
            "NARRATIVE_EVALUATION_REPLACEMENT_GATE_IDENTITY_INVALID",
            "semantic replacement gate requires complete generation lineage",
        )
    if generation == 1:
        if opening_binding:
            try:
                _assert_live_generation_one_opening(
                    uow,
                    project_id=project_id,
                    book_id=book_id,
                    opening_binding=opening_binding,
                )
            except KernelError as exc:
                if (
                    exc.code
                    != "NARRATIVE_EVALUATION_BOOK_OPENING_EXECUTION_GATE_CLOSED"
                ):
                    raise
                # A failed original Opening may formally recover by resuming
                # the still-current generation-one Evaluation.  In that case
                # the immutable Planning binding names history while the new
                # RuntimeJob and its RecoveryAssessment own current liveness.
                _assert_live_replacement_opening(
                    uow,
                    operation_id=operation_id,
                    project_id=project_id,
                    book_id=book_id,
                    evaluation_execution_id=evaluation_execution_id,
                    generation=generation,
                    evaluation_recovery_intent_id="",
                    candidate_asset_version_id=candidate_asset_version_id,
                    candidate_content_hash=candidate_content_hash,
                    predecessor_execution_id=predecessor_execution_id,
                    predecessor_generation=predecessor_generation,
                    predecessor_operation_id=predecessor_operation_id,
                    closed_code=(
                        "NARRATIVE_EVALUATION_BOOK_OPENING_EXECUTION_GATE_CLOSED"
                    ),
                )
        elif _is_recovery_bound(
            uow,
            operation_id=operation_id,
            project_id=project_id,
            evaluation_execution_id=evaluation_execution_id,
            generation=generation,
        ):
            _assert_live_replacement_opening(
                uow,
                operation_id=operation_id,
                project_id=project_id,
                book_id=book_id,
                evaluation_execution_id=evaluation_execution_id,
                generation=generation,
                evaluation_recovery_intent_id="",
                candidate_asset_version_id=candidate_asset_version_id,
                candidate_content_hash=candidate_content_hash,
                predecessor_execution_id=predecessor_execution_id,
                predecessor_generation=predecessor_generation,
                predecessor_operation_id=predecessor_operation_id,
                closed_code=("NARRATIVE_EVALUATION_BOOK_OPENING_EXECUTION_GATE_CLOSED"),
            )
        return {
            "operation_id": operation_id,
            "project_id": project_id,
            "generation": generation,
            "replacement": False,
            "gate_open": True,
        }
    _assert_live_replacement_opening(
        uow,
        operation_id=operation_id,
        project_id=project_id,
        book_id=book_id,
        evaluation_execution_id=evaluation_execution_id,
        generation=generation,
        evaluation_recovery_intent_id=recovery_intent_id,
        candidate_asset_version_id=candidate_asset_version_id,
        candidate_content_hash=candidate_content_hash,
        predecessor_execution_id=predecessor_execution_id,
        predecessor_generation=predecessor_generation,
        predecessor_operation_id=predecessor_operation_id,
    )
    return {
        "operation_id": operation_id,
        "project_id": project_id,
        "generation": generation,
        "replacement": True,
        "gate_open": True,
    }


def assert_narrative_replacement_execution_gate(
    database_url: str,
    *,
    operation_id: str,
    project_id: str,
) -> dict[str, Any]:
    with AuthorityUnitOfWork(database_url) as uow:
        return assert_narrative_replacement_execution_gate_in_uow(
            uow,
            operation_id=operation_id,
            project_id=project_id,
        )


__all__ = [
    "assert_narrative_replacement_execution_gate",
    "assert_narrative_replacement_execution_gate_in_uow",
]
