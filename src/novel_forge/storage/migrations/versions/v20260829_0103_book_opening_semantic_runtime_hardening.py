from __future__ import annotations


MIGRATION_ID = "20260829_0103_book_opening_semantic_runtime_hardening"
DOWN_REVISION = "20260828_0102_book_opening_recovery_closure"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = (
    "preserve every historical Planning membership, Budget reservation, "
    "RecoveryAssessment, Operation, Attempt and ExternalEffect row; converge "
    "legacy-unbound evidence through the owning Authority reconciliation path"
)


PREFLIGHT_STATEMENTS = [
    """
    SELECT 'narrative_search_membership_generation_mismatch', COUNT(*)
    FROM authority_story_narrative_search_candidate AS membership
    LEFT JOIN authority_story_planning_generation AS generation
      ON generation.operation_id=membership.generation_operation_id
     AND generation.narrative_search_id=membership.search_id
     AND generation.narrative_search_branch_key=membership.branch_key
     AND generation.candidate_asset_version_id=
         membership.candidate_asset_version_id
    WHERE generation.generation_id IS NULL
    """,
    """
    SELECT 'narrative_search_membership_generation_duplicate', COUNT(*)
    FROM (
        SELECT operation_id,narrative_search_id,
               narrative_search_branch_key,candidate_asset_version_id
        FROM authority_story_planning_generation
        WHERE narrative_search_id IS NOT NULL
          AND narrative_search_branch_key IS NOT NULL
          AND candidate_asset_version_id IS NOT NULL
        GROUP BY operation_id,narrative_search_id,
                 narrative_search_branch_key,candidate_asset_version_id
        HAVING COUNT(*)>1
    ) AS duplicate
    """,
    """
    SELECT 'active_semantic_evaluation_lineage_missing', COUNT(*)
    FROM authority_operation AS operation
    LEFT JOIN authority_narrative_evaluation_execution AS evaluation
      ON evaluation.operation_id=operation.operation_id
     AND evaluation.project_id=operation.project_id
    WHERE operation.definition_name='story_design.semantic_evaluate'
      AND operation.status NOT IN (
          'SUCCEEDED','FAILED_FINAL','CANCELLED','DEAD_LETTER',
          'COMPENSATED','COMPENSATION_FAILED'
      )
      AND evaluation.evaluation_execution_id IS NULL
    """,
    """
    SELECT 'active_replacement_runtime_binding_missing', COUNT(*)
    FROM authority_book_opening_execution AS execution
    JOIN authority_book_opening_run AS opening
      ON opening.opening_run_id=execution.opening_run_id
    LEFT JOIN authority_runtime_job AS job
      ON job.runtime_job_id=execution.runtime_job_id
    LEFT JOIN authority_book_opening_recovery_intent AS intent
      ON intent.recovery_intent_id=execution.recovery_intent_id
     AND intent.opening_run_id=execution.opening_run_id
     AND intent.successor_generation=execution.generation
    LEFT JOIN authority_book_opening_recovery_assessment AS assessment
      ON assessment.recovery_assessment_id=intent.recovery_assessment_id
     AND assessment.opening_run_id=intent.opening_run_id
     AND assessment.assessment_kind='RECOVERY'
    LEFT JOIN authority_book_opening_recovery_receipt AS receipt
      ON receipt.receipt_kind='RECOVERY_ADMISSION'
     AND receipt.opening_run_id=execution.opening_run_id
     AND receipt.recovery_assessment_id=assessment.recovery_assessment_id
     AND receipt.recovery_intent_id=intent.recovery_intent_id
     AND receipt.predecessor_execution_id=intent.predecessor_execution_id
     AND receipt.predecessor_generation=intent.predecessor_generation
     AND receipt.successor_execution_id=execution.opening_execution_id
     AND receipt.successor_generation=execution.generation
    WHERE execution.lifecycle IN ('SCHEDULED','BOUND','RUNNING')
      AND execution.generation>1
      AND (
          opening.execution_contract_version='book-opening-execution-v2'
          AND opening.current_execution_id=execution.opening_execution_id
          AND opening.current_execution_generation=execution.generation
          AND opening.frozen_request_digest=execution.frozen_request_digest
          AND (
              (execution.lifecycle IN ('SCHEDULED','BOUND')
               AND opening.lifecycle='ADMITTED')
              OR
              (execution.lifecycle='RUNNING'
               AND opening.lifecycle='RUNNING'
               AND opening.recovery_state='READY')
          )
          AND intent.recovery_intent_id=execution.recovery_intent_id
          AND intent.predecessor_execution_id=
              execution.predecessor_execution_id
          AND intent.predecessor_generation=execution.predecessor_generation
          AND assessment.recovery_assessment_id=intent.recovery_assessment_id
          AND assessment.disposition NOT IN (
              'UNKNOWN_AMBIGUOUS','RECONCILIATION_REQUIRED'
          )
          AND assessment.opening_execution_id=
              intent.predecessor_execution_id
          AND assessment.execution_generation=intent.predecessor_generation
          AND assessment.snapshot->'opening'->>'opening_run_id'=
              opening.opening_run_id
          AND assessment.snapshot->'opening'->>'current_execution_id'=
              intent.predecessor_execution_id
          AND assessment.snapshot->'opening'->>
              'current_execution_generation'=
              intent.predecessor_generation::text
          AND receipt.recovery_intent_id=intent.recovery_intent_id
          AND receipt.result->>'opening_run_id'=opening.opening_run_id
          AND receipt.result->>'recovery_intent_id'=intent.recovery_intent_id
          AND receipt.result->>'opening_execution_id'=
              execution.opening_execution_id
          AND receipt.result->>'execution_generation'=
              execution.generation::text
          AND receipt.result->>'runtime_job_id'=job.runtime_job_id
          AND job.project_id=opening.project_id
          AND job.job_kind='BOOK_OPENING_EXECUTE'
          AND job.runtime_group='book_opening'
          AND job.subject_kind='BOOK_OPENING_RUN'
          AND job.subject_id=opening.opening_run_id
          AND job.input_hash=execution.input_snapshot_hash
          AND job.lease_loss_policy='AUTHORITY_CONVERGENCE_REQUIRED'
          AND job.max_attempts=1
          AND job.input_snapshot->>'opening_run_id'=opening.opening_run_id
          AND job.input_snapshot->>'opening_execution_id'=
              execution.opening_execution_id
          AND job.input_snapshot->>'execution_generation'=
              execution.generation::text
          AND job.input_snapshot->>'frozen_request_digest'=
              opening.frozen_request_digest
          AND job.input_snapshot->>'recovery_intent_id'=
              intent.recovery_intent_id
          AND (
              (execution.lifecycle='SCHEDULED'
               AND job.status='READY'
               AND job.current_attempt_id IS NULL
               AND execution.current_attempt_id IS NULL)
              OR EXISTS (
                  SELECT 1
                  FROM authority_runtime_job_attempt AS runtime_attempt
                  JOIN authority_runtime_job_lease AS runtime_lease
                    ON runtime_lease.runtime_job_id=job.runtime_job_id
                   AND runtime_lease.attempt_id=runtime_attempt.attempt_id
                   AND runtime_lease.lease_id=runtime_attempt.lease_id
                   AND runtime_lease.worker_id=runtime_attempt.worker_id
                   AND runtime_lease.fencing_token=
                       runtime_attempt.fencing_token
                   AND runtime_lease.status='HELD'
                   AND runtime_lease.lease_expires_at>clock_timestamp()
                  WHERE execution.lifecycle IN ('BOUND','RUNNING')
                    AND runtime_attempt.runtime_job_id=job.runtime_job_id
                    AND runtime_attempt.attempt_id=job.current_attempt_id
                    AND runtime_attempt.attempt_number=job.attempt_count
                    AND runtime_attempt.lease_id=execution.current_lease_id
                    AND runtime_attempt.worker_id=job.claimed_by
                    AND runtime_attempt.fencing_token=
                        job.current_fencing_token
                    AND runtime_attempt.attempt_id=
                        execution.current_attempt_id
                    AND runtime_attempt.worker_id=
                        execution.current_worker_id
                    AND runtime_attempt.fencing_token=
                        execution.current_fencing_token
                    AND (
                        (execution.lifecycle='BOUND'
                         AND job.status='CLAIMED'
                         AND runtime_attempt.status='CLAIMED')
                        OR
                        (execution.lifecycle='RUNNING'
                         AND job.status IN ('RUNNING','CHECKPOINTED')
                         AND runtime_attempt.status=job.status)
                    )
              )
          )
          AND (
              (
                  job.input_snapshot->>'semantic_execution_mode'='NONE'
                  AND COALESCE(
                      job.input_snapshot->>
                          'semantic_evaluation_operation_id',''
                  )=''
                  AND COALESCE(
                      job.input_snapshot->>
                          'semantic_evaluation_execution_id',''
                  )=''
                  AND COALESCE(
                      job.input_snapshot->>
                          'semantic_evaluation_generation','0'
                  )='0'
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
              ) OR EXISTS (
              SELECT 1
              FROM authority_narrative_evaluation_execution AS evaluation
              JOIN authority_narrative_evaluation_execution_head AS head
                ON head.project_id=evaluation.project_id
               AND head.candidate_asset_version_id=
                   evaluation.candidate_asset_version_id
               AND head.current_execution_id=
                   evaluation.evaluation_execution_id
               AND head.current_generation=evaluation.generation
              JOIN authority_operation AS evaluation_operation
                ON evaluation_operation.operation_id=evaluation.operation_id
               AND evaluation_operation.project_id=evaluation.project_id
               AND evaluation_operation.definition_name=
                   'story_design.semantic_evaluate'
              JOIN authority_operation AS generation_operation
                ON generation_operation.operation_id=
                   evaluation_operation.command_payload->'payload'->>
                       'generation_operation_id'
               AND generation_operation.project_id=evaluation.project_id
               AND (
                   generation_operation.definition_name=
                       evaluation_operation.command_payload->'payload'->>
                           'generator_operation_name'
                   OR (
                       generation_operation.definition_name=
                           'story_planning.generate'
                       AND generation_operation.command_payload->'payload'->>
                           'generator_operation_name'=
                           evaluation_operation.command_payload->'payload'->>
                               'generator_operation_name'
                   )
               )
               AND COALESCE(
                   generation_operation.command_payload->'payload'->>'book_id',
                   generation_operation.command_payload->>'book_id'
               )=evaluation.book_id
               AND (
                   (evaluation.generation=1
                    AND evaluation_operation.causation_operation_id=
                        generation_operation.operation_id)
                   OR
                   (evaluation.generation>1
                   AND evaluation_operation.causation_operation_id=
                        evaluation.predecessor_operation_id)
               )
              JOIN authority_operation_output_asset AS generation_output
                ON generation_output.operation_id=
                   generation_operation.operation_id
               AND generation_output.asset_version_id=
                   evaluation.candidate_asset_version_id
               AND generation_output.content_hash=
                   evaluation.candidate_content_hash
              WHERE evaluation.operation_id=
                        job.input_snapshot->>
                            'semantic_evaluation_operation_id'
                AND evaluation.evaluation_execution_id=
                        job.input_snapshot->>
                            'semantic_evaluation_execution_id'
                AND evaluation.generation::text=
                        job.input_snapshot->>
                            'semantic_evaluation_generation'
                AND evaluation.project_id=job.project_id
                AND evaluation.book_id=opening.book_id
                AND evaluation_operation.command_payload->'payload'->>'book_id'=
                    evaluation.book_id
                AND evaluation_operation.command_payload->'payload'->>
                    'candidate_asset_version_id'=
                    evaluation.candidate_asset_version_id
                AND evaluation_operation.command_payload->'payload'->>
                    'candidate_content_hash'=evaluation.candidate_content_hash
                AND COALESCE(
                    evaluation_operation.command_payload->'payload'->
                        'opening_execution_binding',
                    '{}'::jsonb
                )=COALESCE(
                    generation_operation.command_payload->'payload'->
                        'opening_execution_binding',
                    generation_operation.command_payload->
                        'opening_execution_binding',
                    '{}'::jsonb
                )
                AND (
                    (
                        job.input_snapshot->>'semantic_execution_mode'=
                            'NEW_REPLACEMENT'
                        AND evaluation.generation>1
                        AND evaluation.recovery_intent_id=
                            execution.recovery_intent_id
                        AND job.input_snapshot->>
                            'replacement_evaluation_operation_id'=
                            evaluation.operation_id
                        AND assessment.snapshot->'semantic_evaluation'->>
                            'operation_id'=
                            evaluation.predecessor_operation_id
                        AND assessment.snapshot->'semantic_evaluation'->>
                            'evaluation_execution_id'=
                            evaluation.predecessor_execution_id
                        AND assessment.snapshot->'semantic_evaluation'->>
                            'generation'=
                            evaluation.predecessor_generation::text
                        AND assessment.snapshot->'semantic_evaluation'->>
                            'candidate_asset_version_id'=
                            evaluation.candidate_asset_version_id
                        AND assessment.snapshot->'semantic_evaluation'->>
                            'candidate_content_hash'=
                            evaluation.candidate_content_hash
                        AND receipt.result->>
                            'replacement_evaluation_operation_id'=
                            evaluation.operation_id
                        AND receipt.result->>
                            'replacement_evaluation_execution_id'=
                            evaluation.evaluation_execution_id
                    ) OR (
                        job.input_snapshot->>'semantic_execution_mode'=
                            'RESUME_CURRENT'
                        AND COALESCE(
                            job.input_snapshot->>
                                'replacement_evaluation_operation_id',''
                        )=''
                        AND assessment.snapshot->'semantic_evaluation'->>
                            'operation_id'=evaluation.operation_id
                        AND assessment.snapshot->'semantic_evaluation'->>
                            'evaluation_execution_id'=
                            evaluation.evaluation_execution_id
                        AND assessment.snapshot->'semantic_evaluation'->>
                            'generation'=evaluation.generation::text
                        AND assessment.snapshot->'semantic_evaluation'->>
                            'candidate_asset_version_id'=
                            evaluation.candidate_asset_version_id
                        AND assessment.snapshot->'semantic_evaluation'->>
                            'candidate_content_hash'=
                            evaluation.candidate_content_hash
                        AND COALESCE(
                            receipt.result->>
                                'replacement_evaluation_operation_id',''
                        )=''
                        AND COALESCE(
                            receipt.result->>
                                'replacement_evaluation_execution_id',''
                        )=''
                    )
                )
          )
      )) IS NOT TRUE
    """,
    """
    SELECT 'active_replacement_operation_outer_gate_closed', COUNT(*)
    FROM authority_operation AS operation
    JOIN authority_narrative_evaluation_execution AS evaluation
      ON evaluation.operation_id=operation.operation_id
     AND evaluation.project_id=operation.project_id
     AND evaluation.generation>1
    WHERE operation.definition_name='story_design.semantic_evaluate'
      AND operation.status IN ('READY','EXECUTING')
      AND NOT EXISTS (
          SELECT 1
          FROM authority_book_opening_run AS opening
          JOIN authority_book_opening_execution AS execution
            ON execution.opening_run_id=opening.opening_run_id
           AND execution.opening_execution_id=opening.current_execution_id
           AND execution.generation=opening.current_execution_generation
           AND execution.lifecycle='RUNNING'
          JOIN authority_runtime_job AS job
            ON job.runtime_job_id=execution.runtime_job_id
           AND job.project_id=opening.project_id
           AND job.status IN ('RUNNING','CHECKPOINTED')
           AND job.input_snapshot->>'semantic_evaluation_operation_id'=
               evaluation.operation_id
           AND job.input_snapshot->>'semantic_evaluation_execution_id'=
               evaluation.evaluation_execution_id
           AND job.input_snapshot->>'semantic_evaluation_generation'=
               evaluation.generation::text
          JOIN authority_runtime_job_attempt AS attempt
            ON attempt.runtime_job_id=job.runtime_job_id
           AND attempt.attempt_id=job.current_attempt_id
           AND attempt.status=job.status
           AND attempt.worker_id=job.claimed_by
           AND attempt.fencing_token=job.current_fencing_token
          JOIN authority_runtime_job_lease AS lease
            ON lease.runtime_job_id=job.runtime_job_id
           AND lease.attempt_id=attempt.attempt_id
           AND lease.lease_id=attempt.lease_id
           AND lease.worker_id=attempt.worker_id
           AND lease.fencing_token=attempt.fencing_token
           AND lease.status='HELD'
           AND lease.lease_expires_at>clock_timestamp()
          WHERE opening.project_id=evaluation.project_id
            AND opening.book_id=evaluation.book_id
            AND opening.lifecycle='RUNNING'
            AND opening.recovery_state='READY'
            AND execution.current_attempt_id=attempt.attempt_id
            AND execution.current_lease_id=lease.lease_id
            AND execution.current_worker_id=attempt.worker_id
            AND execution.current_fencing_token=attempt.fencing_token
      )
    """,
    """
    SELECT 'held_replacement_dispatch_outer_gate_closed', COUNT(*)
    FROM authority_effect_dispatch_lease AS dispatch_lease
    JOIN authority_external_effect_dispatch AS dispatch
      ON dispatch.dispatch_id=dispatch_lease.dispatch_id
    JOIN authority_external_effect AS effect
      ON effect.external_effect_id=dispatch.external_effect_id
    JOIN authority_operation AS operation
      ON operation.operation_id=effect.operation_id
     AND operation.project_id=effect.project_id
     AND operation.definition_name='story_design.semantic_evaluate'
    JOIN authority_narrative_evaluation_execution AS evaluation
      ON evaluation.operation_id=operation.operation_id
     AND evaluation.project_id=operation.project_id
     AND evaluation.generation>1
    WHERE dispatch_lease.status='HELD'
      AND NOT EXISTS (
          SELECT 1
          FROM authority_book_opening_run AS opening
          JOIN authority_book_opening_execution AS execution
            ON execution.opening_run_id=opening.opening_run_id
           AND execution.opening_execution_id=opening.current_execution_id
           AND execution.generation=opening.current_execution_generation
           AND execution.lifecycle='RUNNING'
          JOIN authority_runtime_job AS job
            ON job.runtime_job_id=execution.runtime_job_id
           AND job.project_id=opening.project_id
           AND job.status IN ('RUNNING','CHECKPOINTED')
           AND job.input_snapshot->>'semantic_evaluation_operation_id'=
               evaluation.operation_id
           AND job.input_snapshot->>'semantic_evaluation_execution_id'=
               evaluation.evaluation_execution_id
           AND job.input_snapshot->>'semantic_evaluation_generation'=
               evaluation.generation::text
          JOIN authority_runtime_job_attempt AS attempt
            ON attempt.runtime_job_id=job.runtime_job_id
           AND attempt.attempt_id=job.current_attempt_id
           AND attempt.status=job.status
           AND attempt.worker_id=job.claimed_by
           AND attempt.fencing_token=job.current_fencing_token
          JOIN authority_runtime_job_lease AS lease
            ON lease.runtime_job_id=job.runtime_job_id
           AND lease.attempt_id=attempt.attempt_id
           AND lease.lease_id=attempt.lease_id
           AND lease.worker_id=attempt.worker_id
           AND lease.fencing_token=attempt.fencing_token
           AND lease.status='HELD'
           AND lease.lease_expires_at>clock_timestamp()
          WHERE opening.project_id=evaluation.project_id
            AND opening.book_id=evaluation.book_id
            AND opening.lifecycle='RUNNING'
            AND opening.recovery_state='READY'
            AND execution.current_attempt_id=attempt.attempt_id
            AND execution.current_lease_id=lease.lease_id
            AND execution.current_worker_id=attempt.worker_id
            AND execution.current_fencing_token=attempt.fencing_token
      )
    """,
]


UPGRADE_STATEMENTS = [
    # A future-N branch becomes durable evidence only when its exact generation
    # identity, membership projection and outer semantic checkpoint can commit
    # together.  Historical rows remain explicit legacy evidence and must be
    # reconciled through Book Opening Authority; the migration does not invent
    # hashes for facts that were never atomically observed.
    """
    ALTER TABLE authority_story_narrative_search_candidate
    ADD COLUMN branch_evidence_contract_version TEXT NOT NULL
        DEFAULT 'legacy-unbound',
    ADD COLUMN branch_evidence_hash TEXT NOT NULL DEFAULT '',
    ADD CONSTRAINT authority_story_narrative_branch_evidence_shape_check CHECK (
        (
            branch_evidence_contract_version='legacy-unbound'
            AND branch_evidence_hash=''
        ) OR (
            branch_evidence_contract_version=
                'narrative-search-branch-evidence.v1'
            AND branch_evidence_hash ~ '^sha256:[0-9a-f]{64}$'
        )
    )
    """,
    """
    ALTER TABLE authority_story_planning_generation
    ADD CONSTRAINT authority_story_planning_generation_search_identity
    UNIQUE (
        operation_id,narrative_search_id,narrative_search_branch_key,
        candidate_asset_version_id
    )
    """,
    """
    ALTER TABLE authority_story_narrative_search_candidate
    ADD CONSTRAINT authority_story_narrative_membership_generation_fk
    FOREIGN KEY (
        generation_operation_id,search_id,branch_key,
        candidate_asset_version_id
    ) REFERENCES authority_story_planning_generation (
        operation_id,narrative_search_id,narrative_search_branch_key,
        candidate_asset_version_id
    ) DEFERRABLE INITIALLY DEFERRED
    """,
    """
    CREATE INDEX authority_story_narrative_membership_generation_identity_idx
    ON authority_story_narrative_search_candidate(
        generation_operation_id,search_id,branch_key,
        candidate_asset_version_id
    )
    """,
    """
    CREATE OR REPLACE FUNCTION
        novel_forge_story_planning_generation_identity_guard()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF ROW(
            OLD.generation_id, OLD.operation_id, OLD.project_id,
            OLD.workspace_id, OLD.book_id, OLD.generator_operation_name,
            OLD.planning_scope, OLD.logical_key, OLD.parent_version_id,
            OLD.input_snapshot, OLD.input_snapshot_hash,
            OLD.repair_of_candidate_id, OLD.repair_reason, OLD.repair_number,
            OLD.narrative_search_id, OLD.narrative_search_branch_key,
            OLD.created_at
        ) IS DISTINCT FROM ROW(
            NEW.generation_id, NEW.operation_id, NEW.project_id,
            NEW.workspace_id, NEW.book_id, NEW.generator_operation_name,
            NEW.planning_scope, NEW.logical_key, NEW.parent_version_id,
            NEW.input_snapshot, NEW.input_snapshot_hash,
            NEW.repair_of_candidate_id, NEW.repair_reason, NEW.repair_number,
            NEW.narrative_search_id, NEW.narrative_search_branch_key,
            NEW.created_at
        ) THEN
            RAISE EXCEPTION 'STORY_PLANNING_GENERATION_IDENTITY_IMMUTABLE'
                USING ERRCODE='check_violation';
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE OR REPLACE FUNCTION
        authority_story_narrative_membership_identity_guard()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP='DELETE' OR ROW(
            OLD.membership_id,OLD.search_id,OLD.branch_key,
            OLD.candidate_asset_version_id,OLD.generation_operation_id,
            OLD.projection,OLD.projection_hash,OLD.strategy_fingerprint,
            OLD.comparison_score,OLD.qualification_hash,
            OLD.branch_evidence_contract_version,OLD.branch_evidence_hash,
            OLD.created_at
        ) IS DISTINCT FROM ROW(
            NEW.membership_id,NEW.search_id,NEW.branch_key,
            NEW.candidate_asset_version_id,NEW.generation_operation_id,
            NEW.projection,NEW.projection_hash,NEW.strategy_fingerprint,
            NEW.comparison_score,NEW.qualification_hash,
            NEW.branch_evidence_contract_version,NEW.branch_evidence_hash,
            NEW.created_at
        ) THEN
            RAISE EXCEPTION
                'NARRATIVE_SEARCH_MEMBERSHIP_IDENTITY_IMMUTABLE:%',
                OLD.membership_id USING ERRCODE='check_violation';
        END IF;
        IF OLD.status IN ('SELECTED','REJECTED')
           AND NEW.status IS DISTINCT FROM OLD.status THEN
            RAISE EXCEPTION
                'NARRATIVE_SEARCH_MEMBERSHIP_TERMINAL_IMMUTABLE:%',
                OLD.membership_id USING ERRCODE='check_violation';
        END IF;
        IF OLD.status='ELIGIBLE'
           AND NEW.status NOT IN ('ELIGIBLE','SELECTED','REJECTED') THEN
            RAISE EXCEPTION
                'NARRATIVE_SEARCH_MEMBERSHIP_TRANSITION_INVALID:%',
                OLD.membership_id USING ERRCODE='check_violation';
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE TRIGGER authority_story_narrative_membership_identity_immutable
    BEFORE UPDATE OR DELETE ON authority_story_narrative_search_candidate
    FOR EACH ROW EXECUTE FUNCTION
        authority_story_narrative_membership_identity_guard()
    """,
    """
    CREATE OR REPLACE FUNCTION
        authority_story_narrative_membership_evidence_guard()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.branch_evidence_contract_version<>
               'narrative-search-branch-evidence.v1'
           OR NEW.branch_evidence_hash !~ '^sha256:[0-9a-f]{64}$' THEN
            RAISE EXCEPTION 'NARRATIVE_SEARCH_BRANCH_EVIDENCE_INVALID:%',
                NEW.membership_id USING ERRCODE='check_violation';
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE TRIGGER authority_story_narrative_membership_evidence_required
    BEFORE INSERT ON authority_story_narrative_search_candidate
    FOR EACH ROW EXECUTE FUNCTION
        authority_story_narrative_membership_evidence_guard()
    """,
    """
    CREATE OR REPLACE FUNCTION authority_story_narrative_search_identity_guard()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF ROW(
            OLD.search_id,OLD.project_id,OLD.workspace_id,OLD.book_id,
            OLD.book_run_id,OLD.generator_operation_name,OLD.planning_scope,
            OLD.logical_key,OLD.parent_version_id,
            OLD.parent_state_asset_version_id,OLD.parent_state_content_hash,
            OLD.accepted_through_chapter,OLD.planning_horizon,
            OLD.desired_transformation,OLD.hard_constraints,
            OLD.input_snapshot_hash,OLD.strategy_directives,
            OLD.candidate_target,OLD.stable_idempotency_key,OLD.created_at
        ) IS DISTINCT FROM ROW(
            NEW.search_id,NEW.project_id,NEW.workspace_id,NEW.book_id,
            NEW.book_run_id,NEW.generator_operation_name,NEW.planning_scope,
            NEW.logical_key,NEW.parent_version_id,
            NEW.parent_state_asset_version_id,NEW.parent_state_content_hash,
            NEW.accepted_through_chapter,NEW.planning_horizon,
            NEW.desired_transformation,NEW.hard_constraints,
            NEW.input_snapshot_hash,NEW.strategy_directives,
            NEW.candidate_target,NEW.stable_idempotency_key,NEW.created_at
        ) THEN
            RAISE EXCEPTION 'NARRATIVE_SEARCH_IDENTITY_IMMUTABLE:%',
                OLD.search_id USING ERRCODE='check_violation';
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE TRIGGER authority_story_narrative_search_identity_immutable
    BEFORE UPDATE ON authority_story_narrative_search
    FOR EACH ROW EXECUTE FUNCTION authority_story_narrative_search_identity_guard()
    """,

    # A legacy membership is immutable historical evidence.  Reconciliation
    # therefore appends a Planning-owned sidecar whose exact source facts were
    # re-read under the Book Opening live execution fence.  The Book Authority
    # assessment/receipt below bind that inner artifact to the outer checkpoint
    # in the same transaction; none of these rows authorizes Provider work.
    """
    ALTER TABLE authority_story_narrative_search_candidate
    ADD CONSTRAINT authority_story_narrative_membership_reconciliation_identity
    UNIQUE (
        membership_id,search_id,branch_key,candidate_asset_version_id,
        generation_operation_id,branch_evidence_contract_version
    )
    """,
    """
    CREATE TABLE authority_story_narrative_branch_reconciliation_evidence (
        reconciliation_evidence_id TEXT PRIMARY KEY,
        membership_id TEXT NOT NULL,
        search_id TEXT NOT NULL,
        branch_key TEXT NOT NULL,
        candidate_asset_version_id TEXT NOT NULL,
        generation_operation_id TEXT NOT NULL,
        source_branch_evidence_contract_version TEXT NOT NULL,
        opening_run_id TEXT NOT NULL
            REFERENCES authority_book_opening_run(opening_run_id),
        opening_execution_id TEXT NOT NULL,
        execution_generation BIGINT NOT NULL,
        generation_input_snapshot_hash TEXT NOT NULL,
        candidate_content_hash TEXT NOT NULL,
        projection_hash TEXT NOT NULL,
        strategy_fingerprint TEXT NOT NULL,
        qualification_hash TEXT NOT NULL,
        qualification_receipt_set_hash TEXT NOT NULL,
        reconciled_branch_evidence_hash TEXT NOT NULL,
        reconciliation_contract_version TEXT NOT NULL,
        evidence_version BIGINT NOT NULL,
        evidence_payload JSONB NOT NULL,
        evidence_hash TEXT NOT NULL,
        stable_idempotency_key TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(membership_id),
        UNIQUE(stable_idempotency_key),
        UNIQUE(reconciliation_evidence_id,membership_id),
        UNIQUE(reconciliation_evidence_id,membership_id,opening_run_id),
        UNIQUE(
            reconciliation_evidence_id,membership_id,opening_run_id,
            opening_execution_id,execution_generation
        ),
        UNIQUE(reconciliation_evidence_id,evidence_version,evidence_hash),
        FOREIGN KEY (
            membership_id,search_id,branch_key,candidate_asset_version_id,
            generation_operation_id,source_branch_evidence_contract_version
        ) REFERENCES authority_story_narrative_search_candidate (
            membership_id,search_id,branch_key,candidate_asset_version_id,
            generation_operation_id,branch_evidence_contract_version
        ) DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY (
            opening_run_id,opening_execution_id,execution_generation
        ) REFERENCES authority_book_opening_execution (
            opening_run_id,opening_execution_id,generation
        ) DEFERRABLE INITIALLY DEFERRED,
        CHECK (source_branch_evidence_contract_version='legacy-unbound'),
        CHECK (
            reconciliation_contract_version=
                'narrative-search-branch-reconciliation.v1'
        ),
        CHECK (evidence_version=1),
        CHECK (execution_generation>0),
        CHECK (generation_input_snapshot_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (candidate_content_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (projection_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (qualification_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (qualification_receipt_set_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (reconciled_branch_evidence_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (evidence_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (jsonb_typeof(evidence_payload)='object'),
        CHECK (NULLIF(stable_idempotency_key,'') IS NOT NULL)
    )
    """,
    """
    CREATE INDEX authority_story_narrative_branch_reconciliation_source_idx
    ON authority_story_narrative_branch_reconciliation_evidence(
        membership_id,search_id,branch_key,candidate_asset_version_id,
        generation_operation_id,source_branch_evidence_contract_version
    )
    """,
    """
    CREATE INDEX authority_story_narrative_branch_reconciliation_execution_idx
    ON authority_story_narrative_branch_reconciliation_evidence(
        opening_run_id,opening_execution_id,execution_generation
    )
    """,
    """
    CREATE TRIGGER authority_story_narrative_branch_reconciliation_immutable
    BEFORE UPDATE OR DELETE
    ON authority_story_narrative_branch_reconciliation_evidence
    FOR EACH ROW EXECUTE FUNCTION novel_forge_reject_immutable_mutation()
    """,
    """
    CREATE TABLE authority_book_opening_branch_reconciliation_assessment (
        branch_reconciliation_assessment_id TEXT PRIMARY KEY,
        opening_run_id TEXT NOT NULL
            REFERENCES authority_book_opening_run(opening_run_id),
        opening_execution_id TEXT NOT NULL,
        execution_generation BIGINT NOT NULL,
        runtime_job_id TEXT NOT NULL,
        runtime_attempt_id TEXT NOT NULL,
        runtime_lease_id TEXT NOT NULL,
        runtime_worker_id TEXT NOT NULL,
        runtime_fencing_token BIGINT NOT NULL,
        membership_id TEXT NOT NULL,
        reconciliation_evidence_id TEXT NOT NULL,
        semantic_work_key TEXT NOT NULL,
        predecessor_checkpoint_id TEXT,
        predecessor_checkpoint_sequence BIGINT NOT NULL,
        predecessor_checkpoint_hash TEXT NOT NULL,
        assessment_contract_version TEXT NOT NULL,
        assessment_snapshot JSONB NOT NULL,
        assessment_hash TEXT NOT NULL,
        reconciliation_intent_hash TEXT NOT NULL,
        outcome TEXT NOT NULL,
        stable_idempotency_key TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(opening_run_id,membership_id),
        UNIQUE(opening_run_id,reconciliation_evidence_id),
        UNIQUE(opening_run_id,stable_idempotency_key),
        UNIQUE(branch_reconciliation_assessment_id,reconciliation_evidence_id),
        FOREIGN KEY (
            opening_run_id,opening_execution_id,execution_generation
        ) REFERENCES authority_book_opening_execution (
            opening_run_id,opening_execution_id,generation
        ) DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY (
            runtime_job_id,runtime_attempt_id,runtime_lease_id,
            runtime_worker_id,runtime_fencing_token
        ) REFERENCES authority_runtime_job_lease (
            runtime_job_id,attempt_id,lease_id,worker_id,fencing_token
        ) DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY (
            reconciliation_evidence_id,membership_id,opening_run_id,
            opening_execution_id,execution_generation
        )
        REFERENCES authority_story_narrative_branch_reconciliation_evidence (
            reconciliation_evidence_id,membership_id,opening_run_id,
            opening_execution_id,execution_generation
        ) DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY (
            opening_run_id,predecessor_checkpoint_id,
            predecessor_checkpoint_sequence,predecessor_checkpoint_hash
        ) REFERENCES authority_book_opening_semantic_checkpoint (
            opening_run_id,checkpoint_id,checkpoint_sequence,checkpoint_hash
        ) DEFERRABLE INITIALLY DEFERRED,
        CHECK (execution_generation>0),
        CHECK (runtime_fencing_token>0),
        CHECK (NULLIF(runtime_worker_id,'') IS NOT NULL),
        CHECK (NULLIF(semantic_work_key,'') IS NOT NULL),
        CHECK (
            (predecessor_checkpoint_id IS NULL
             AND predecessor_checkpoint_sequence=0
             AND predecessor_checkpoint_hash='')
            OR
            (predecessor_checkpoint_id IS NOT NULL
             AND predecessor_checkpoint_sequence>0
             AND predecessor_checkpoint_hash ~ '^sha256:[0-9a-f]{64}$')
        ),
        CHECK (
            assessment_contract_version=
                'book-opening-branch-reconciliation-assessment.v1'
        ),
        CHECK (jsonb_typeof(assessment_snapshot)='object'),
        CHECK (assessment_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (reconciliation_intent_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (outcome='RECONCILABLE'),
        CHECK (NULLIF(stable_idempotency_key,'') IS NOT NULL)
    )
    """,
    """
    CREATE INDEX authority_book_opening_branch_reconciliation_execution_idx
    ON authority_book_opening_branch_reconciliation_assessment(
        opening_run_id,opening_execution_id,execution_generation
    )
    """,
    """
    CREATE INDEX authority_book_opening_branch_reconciliation_runtime_idx
    ON authority_book_opening_branch_reconciliation_assessment(
        runtime_job_id,runtime_attempt_id,runtime_lease_id,
        runtime_worker_id,runtime_fencing_token
    )
    """,
    """
    CREATE INDEX authority_book_opening_branch_reconciliation_checkpoint_idx
    ON authority_book_opening_branch_reconciliation_assessment(
        opening_run_id,predecessor_checkpoint_id,
        predecessor_checkpoint_sequence,predecessor_checkpoint_hash
    ) WHERE predecessor_checkpoint_id IS NOT NULL
    """,
    """
    CREATE TRIGGER
        authority_book_opening_branch_reconciliation_assessment_immutable
    BEFORE UPDATE OR DELETE
    ON authority_book_opening_branch_reconciliation_assessment
    FOR EACH ROW EXECUTE FUNCTION novel_forge_reject_immutable_mutation()
    """,
    """
    CREATE TABLE authority_book_opening_branch_reconciliation_receipt (
        branch_reconciliation_receipt_id TEXT PRIMARY KEY,
        branch_reconciliation_assessment_id TEXT NOT NULL,
        opening_run_id TEXT NOT NULL,
        membership_id TEXT NOT NULL,
        reconciliation_evidence_id TEXT NOT NULL,
        checkpoint_id TEXT NOT NULL,
        checkpoint_sequence BIGINT NOT NULL,
        checkpoint_hash TEXT NOT NULL,
        result JSONB NOT NULL,
        result_hash TEXT NOT NULL,
        stable_idempotency_key TEXT NOT NULL,
        event_id TEXT NOT NULL UNIQUE REFERENCES state_event(event_id),
        audit_id TEXT NOT NULL UNIQUE REFERENCES audit_log(audit_id),
        outbox_id TEXT NOT NULL UNIQUE REFERENCES outbox_event(outbox_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(branch_reconciliation_assessment_id),
        UNIQUE(opening_run_id,membership_id),
        UNIQUE(opening_run_id,reconciliation_evidence_id),
        UNIQUE(opening_run_id,stable_idempotency_key),
        FOREIGN KEY (
            branch_reconciliation_assessment_id,reconciliation_evidence_id
        ) REFERENCES authority_book_opening_branch_reconciliation_assessment (
            branch_reconciliation_assessment_id,reconciliation_evidence_id
        ) DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY (
            opening_run_id,checkpoint_id,checkpoint_sequence,checkpoint_hash
        ) REFERENCES authority_book_opening_semantic_checkpoint (
            opening_run_id,checkpoint_id,checkpoint_sequence,checkpoint_hash
        ) DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY (
            reconciliation_evidence_id,membership_id,opening_run_id
        )
        REFERENCES authority_story_narrative_branch_reconciliation_evidence (
            reconciliation_evidence_id,membership_id,opening_run_id
        ) DEFERRABLE INITIALLY DEFERRED,
        CHECK (checkpoint_sequence>0),
        CHECK (checkpoint_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (jsonb_typeof(result)='object'),
        CHECK (result_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (NULLIF(stable_idempotency_key,'') IS NOT NULL)
    )
    """,
    """
    CREATE INDEX authority_book_opening_branch_reconciliation_receipt_checkpoint_idx
    ON authority_book_opening_branch_reconciliation_receipt(
        opening_run_id,checkpoint_id,checkpoint_sequence,checkpoint_hash
    )
    """,
    """
    CREATE TRIGGER authority_book_opening_branch_reconciliation_receipt_immutable
    BEFORE UPDATE OR DELETE
    ON authority_book_opening_branch_reconciliation_receipt
    FOR EACH ROW EXECUTE FUNCTION novel_forge_reject_immutable_mutation()
    """,

    # Provider budgets become persistent Command Kernel Authority.  Existing
    # reservations/openings are deliberately unbound rather than guessed from
    # process environment.  A later Authority command may reconcile them.
    """
    CREATE TABLE authority_provider_budget_scope (
        budget_scope_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        owner_kind TEXT NOT NULL,
        owner_id TEXT NOT NULL,
        currency TEXT NOT NULL,
        policy_contract_version TEXT NOT NULL,
        policy_snapshot JSONB NOT NULL,
        policy_hash TEXT NOT NULL,
        budget_timezone TEXT NOT NULL,
        started_at TIMESTAMPTZ NOT NULL,
        deadline_at TIMESTAMPTZ NOT NULL,
        revision BIGINT NOT NULL DEFAULT 1,
        created_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        stable_idempotency_key TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id,owner_kind,owner_id),
        UNIQUE(project_id,stable_idempotency_key),
        UNIQUE(budget_scope_id,revision),
        CHECK (owner_kind IN ('BOOK_OPENING')),
        CHECK (NULLIF(owner_id,'') IS NOT NULL),
        CHECK (NULLIF(currency,'') IS NOT NULL),
        CHECK (jsonb_typeof(policy_snapshot)='object'),
        CHECK (policy_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (revision = 1),
        CHECK (deadline_at > started_at),
        CHECK (COALESCE(policy_snapshot->>'execution_mode','') IN (
            'PROVIDER_ALLOWED','PROJECTION_ONLY'
        ))
    )
    """,
    """
    CREATE INDEX authority_provider_budget_scope_owner_idx
    ON authority_provider_budget_scope(project_id,owner_kind,owner_id,revision)
    """,
    """
    CREATE TRIGGER authority_provider_budget_scope_immutable
    BEFORE UPDATE OR DELETE ON authority_provider_budget_scope
    FOR EACH ROW EXECUTE FUNCTION novel_forge_reject_immutable_mutation()
    """,
    """
    ALTER TABLE authority_book_opening_run
    ADD COLUMN budget_scope_id TEXT
        REFERENCES authority_provider_budget_scope(budget_scope_id),
    ADD COLUMN budget_scope_revision BIGINT,
    ADD COLUMN budget_contract_state TEXT NOT NULL
        DEFAULT 'LEGACY_BUDGET_RECONCILIATION_REQUIRED',
    ADD CONSTRAINT authority_book_opening_budget_binding_shape_check CHECK (
        (
            budget_contract_state=
                'LEGACY_BUDGET_RECONCILIATION_REQUIRED'
            AND budget_scope_id IS NULL
            AND budget_scope_revision IS NULL
        ) OR (
            budget_contract_state IN ('BOUND','RECONCILIATION_REQUIRED')
            AND budget_scope_id IS NOT NULL
            AND budget_scope_revision > 0
        )
    ),
    ADD CONSTRAINT authority_book_opening_budget_scope_revision_fk
        FOREIGN KEY(budget_scope_id,budget_scope_revision)
        REFERENCES authority_provider_budget_scope(budget_scope_id,revision)
        DEFERRABLE INITIALLY DEFERRED
    """,
    """
    CREATE INDEX authority_book_opening_budget_scope_fk_idx
    ON authority_book_opening_run(budget_scope_id,budget_scope_revision)
    WHERE budget_scope_id IS NOT NULL
    """,
    """
    CREATE OR REPLACE FUNCTION authority_book_opening_budget_binding_guard()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF OLD.budget_scope_id IS NOT NULL
           AND ROW(OLD.budget_scope_id,OLD.budget_scope_revision)
               IS DISTINCT FROM
               ROW(NEW.budget_scope_id,NEW.budget_scope_revision) THEN
            RAISE EXCEPTION 'BOOK_OPENING_BUDGET_BINDING_IMMUTABLE:%',
                OLD.opening_run_id USING ERRCODE='check_violation';
        END IF;
        IF OLD.budget_contract_state='BOUND'
           AND NEW.budget_contract_state IS DISTINCT FROM 'BOUND' THEN
            RAISE EXCEPTION 'BOOK_OPENING_BUDGET_BINDING_IMMUTABLE:%',
                OLD.opening_run_id USING ERRCODE='check_violation';
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE TRIGGER authority_book_opening_budget_binding_immutable
    BEFORE UPDATE OF budget_scope_id,budget_scope_revision,budget_contract_state
    ON authority_book_opening_run
    FOR EACH ROW EXECUTE FUNCTION authority_book_opening_budget_binding_guard()
    """,
    """
    ALTER TABLE authority_budget_reservation
    ADD COLUMN budget_scope_id TEXT
        REFERENCES authority_provider_budget_scope(budget_scope_id),
    ADD COLUMN budget_scope_revision BIGINT,
    ADD COLUMN version BIGINT NOT NULL DEFAULT 0,
    ADD CONSTRAINT authority_budget_reservation_scope_shape_check CHECK (
        (budget_scope_id IS NULL AND budget_scope_revision IS NULL)
        OR (budget_scope_id IS NOT NULL AND budget_scope_revision > 0)
    ),
    ADD CONSTRAINT authority_budget_reservation_version_check CHECK (version >= 0),
    ADD CONSTRAINT authority_budget_reservation_scope_identity
        UNIQUE(reservation_id,budget_scope_id,budget_scope_revision),
    ADD CONSTRAINT authority_budget_reservation_scope_revision_fk
        FOREIGN KEY(budget_scope_id,budget_scope_revision)
        REFERENCES authority_provider_budget_scope(budget_scope_id,revision)
        DEFERRABLE INITIALLY DEFERRED
    """,
    """
    CREATE INDEX authority_budget_reservation_scope_idx
    ON authority_budget_reservation(
        budget_scope_id,budget_scope_revision,status,created_at
    ) WHERE budget_scope_id IS NOT NULL
    """,
    """
    CREATE OR REPLACE FUNCTION authority_budget_reservation_version_guard()
    RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE
        lifecycle_changed BOOLEAN;
    BEGIN
        IF TG_OP='DELETE' THEN
            RAISE EXCEPTION 'BUDGET_RESERVATION_HISTORY_IMMUTABLE:%',
                OLD.reservation_id USING ERRCODE='check_violation';
        END IF;
        IF ROW(
            OLD.reservation_id,OLD.operation_id,OLD.external_effect_id,
            OLD.project_id,OLD.stable_idempotency_key,OLD.provider,
            OLD.chapter,OLD.currency,OLD.estimated_amount,
            OLD.reserved_amount,OLD.estimated_tokens,OLD.caps,
            OLD.budget_timezone,OLD.budget_scope_id,
            OLD.budget_scope_revision,OLD.created_at
        ) IS DISTINCT FROM ROW(
            NEW.reservation_id,NEW.operation_id,NEW.external_effect_id,
            NEW.project_id,NEW.stable_idempotency_key,NEW.provider,
            NEW.chapter,NEW.currency,NEW.estimated_amount,
            NEW.reserved_amount,NEW.estimated_tokens,NEW.caps,
            NEW.budget_timezone,NEW.budget_scope_id,
            NEW.budget_scope_revision,NEW.created_at
        ) THEN
            RAISE EXCEPTION 'BUDGET_RESERVATION_IDENTITY_IMMUTABLE:%',
                OLD.reservation_id USING ERRCODE='check_violation';
        END IF;

        lifecycle_changed = ROW(
            OLD.settled_amount,OLD.actual_tokens,OLD.status,OLD.evidence,
            OLD.updated_at,OLD.settled_at,OLD.budget_breach
        ) IS DISTINCT FROM ROW(
            NEW.settled_amount,NEW.actual_tokens,NEW.status,NEW.evidence,
            NEW.updated_at,NEW.settled_at,NEW.budget_breach
        );

        IF OLD.status IN ('SETTLED','RELEASED','REJECTED')
           AND lifecycle_changed THEN
            RAISE EXCEPTION 'BUDGET_RESERVATION_TERMINAL_IMMUTABLE:%',
                OLD.reservation_id USING ERRCODE='check_violation';
        END IF;

        IF NEW.status IS DISTINCT FROM OLD.status
           AND NOT (
               (OLD.status='RESERVED' AND NEW.status IN (
                   'HELD_UNKNOWN','SETTLED','RELEASED','REJECTED'
               ))
               OR (OLD.status='HELD_UNKNOWN' AND NEW.status='SETTLED')
           ) THEN
            RAISE EXCEPTION 'BUDGET_RESERVATION_TRANSITION_INVALID:%:%->%',
                OLD.reservation_id,OLD.status,NEW.status
                USING ERRCODE='check_violation';
        END IF;

        IF lifecycle_changed
           AND NEW.version IS DISTINCT FROM OLD.version+1 THEN
            RAISE EXCEPTION 'BUDGET_RESERVATION_VERSION_NON_MONOTONIC:%',
                OLD.reservation_id USING ERRCODE='check_violation';
        ELSIF NOT lifecycle_changed
              AND NEW.version IS DISTINCT FROM OLD.version THEN
            RAISE EXCEPTION 'BUDGET_RESERVATION_VERSION_WITHOUT_CHANGE:%',
                OLD.reservation_id USING ERRCODE='check_violation';
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE TRIGGER authority_budget_reservation_version_monotonic
    BEFORE UPDATE OR DELETE ON authority_budget_reservation
    FOR EACH ROW EXECUTE FUNCTION authority_budget_reservation_version_guard()
    """,
    """
    CREATE TRIGGER authority_operation_cost_evidence_immutable
    BEFORE UPDATE OR DELETE ON authority_operation_cost_evidence
    FOR EACH ROW EXECUTE FUNCTION novel_forge_reject_immutable_mutation()
    """,
    """
    CREATE TABLE authority_budget_evidence_link (
        budget_evidence_link_id TEXT PRIMARY KEY,
        budget_scope_id TEXT NOT NULL
            REFERENCES authority_provider_budget_scope(budget_scope_id),
        budget_scope_revision BIGINT NOT NULL,
        reservation_id TEXT NOT NULL
            REFERENCES authority_budget_reservation(reservation_id),
        evidence_kind TEXT NOT NULL,
        evidence_id TEXT NOT NULL,
        evidence_version BIGINT NOT NULL,
        evidence_hash TEXT NOT NULL,
        stable_idempotency_key TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(budget_scope_id,stable_idempotency_key),
        UNIQUE(
            budget_scope_id,reservation_id,evidence_kind,
            evidence_id,evidence_version
        ),
        FOREIGN KEY(budget_scope_id,budget_scope_revision)
            REFERENCES authority_provider_budget_scope(budget_scope_id,revision)
            DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY(reservation_id,budget_scope_id,budget_scope_revision)
            REFERENCES authority_budget_reservation(
                reservation_id,budget_scope_id,budget_scope_revision
            ) DEFERRABLE INITIALLY DEFERRED,
        CHECK (budget_scope_revision > 0),
        CHECK (evidence_kind IN (
            'OPERATION_COST','COST_LEDGER','MODEL_CALL'
        )),
        CHECK (NULLIF(evidence_id,'') IS NOT NULL),
        CHECK (evidence_version >= 0),
        CHECK (evidence_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (NULLIF(stable_idempotency_key,'') IS NOT NULL)
    )
    """,
    """
    CREATE INDEX authority_budget_evidence_scope_idx
    ON authority_budget_evidence_link(
        budget_scope_id,budget_scope_revision,created_at
    )
    """,
    """
    CREATE TRIGGER authority_budget_evidence_link_immutable
    BEFORE UPDATE OR DELETE ON authority_budget_evidence_link
    FOR EACH ROW EXECUTE FUNCTION novel_forge_reject_immutable_mutation()
    """,
    """
    CREATE TABLE authority_book_opening_budget_reconciliation_receipt (
        budget_reconciliation_receipt_id TEXT PRIMARY KEY,
        opening_run_id TEXT NOT NULL
            REFERENCES authority_book_opening_run(opening_run_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        budget_scope_id TEXT NOT NULL,
        budget_scope_revision BIGINT NOT NULL,
        command_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        expected_opening_version BIGINT NOT NULL,
        frozen_request_digest TEXT NOT NULL,
        contract_snapshot JSONB NOT NULL,
        contract_hash TEXT NOT NULL,
        intent_hash TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        authorized_by TEXT NOT NULL,
        authorization_reason TEXT NOT NULL,
        result JSONB NOT NULL,
        result_hash TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(opening_run_id),
        UNIQUE(command_operation_id),
        UNIQUE(opening_run_id,intent_hash),
        UNIQUE(opening_run_id,idempotency_key),
        FOREIGN KEY(budget_scope_id,budget_scope_revision)
            REFERENCES authority_provider_budget_scope(budget_scope_id,revision)
            DEFERRABLE INITIALLY DEFERRED,
        CHECK (budget_scope_revision=1),
        CHECK (expected_opening_version>=0),
        CHECK (frozen_request_digest ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (jsonb_typeof(contract_snapshot)='object'),
        CHECK (contract_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (intent_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (NULLIF(idempotency_key,'') IS NOT NULL),
        CHECK (NULLIF(authorized_by,'') IS NOT NULL),
        CHECK (NULLIF(authorization_reason,'') IS NOT NULL),
        CHECK (jsonb_typeof(result)='object'),
        CHECK (result_hash ~ '^sha256:[0-9a-f]{64}$')
    )
    """,
    """
    CREATE INDEX authority_book_opening_budget_reconciliation_project_idx
    ON authority_book_opening_budget_reconciliation_receipt(
        project_id,created_at
    )
    """,
    """
    CREATE TRIGGER
        authority_book_opening_budget_reconciliation_receipt_immutable
    BEFORE UPDATE OR DELETE
    ON authority_book_opening_budget_reconciliation_receipt
    FOR EACH ROW EXECUTE FUNCTION novel_forge_reject_immutable_mutation()
    """,
    """
    CREATE TABLE authority_book_opening_legacy_budget_reservation_attribution (
        legacy_budget_attribution_id TEXT PRIMARY KEY,
        budget_reconciliation_receipt_id TEXT NOT NULL
            REFERENCES authority_book_opening_budget_reconciliation_receipt(
                budget_reconciliation_receipt_id
            ),
        opening_run_id TEXT NOT NULL
            REFERENCES authority_book_opening_run(opening_run_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        budget_scope_id TEXT NOT NULL,
        budget_scope_revision BIGINT NOT NULL,
        reservation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_budget_reservation(reservation_id),
        operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        external_effect_id TEXT NOT NULL
            REFERENCES authority_external_effect(external_effect_id),
        reservation_version BIGINT NOT NULL,
        reservation_status TEXT NOT NULL,
        reservation_snapshot JSONB NOT NULL,
        reservation_snapshot_hash TEXT NOT NULL,
        cost_evidence_id TEXT,
        cost_evidence_version BIGINT,
        cost_evidence_hash TEXT,
        attributed_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(budget_reconciliation_receipt_id,reservation_id),
        FOREIGN KEY(budget_scope_id,budget_scope_revision)
            REFERENCES authority_provider_budget_scope(budget_scope_id,revision)
            DEFERRABLE INITIALLY DEFERRED,
        CHECK (budget_scope_revision=1),
        CHECK (reservation_version>=0),
        CHECK (reservation_status IN ('SETTLED','RELEASED','REJECTED')),
        CHECK (jsonb_typeof(reservation_snapshot)='object'),
        CHECK (reservation_snapshot_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (
            (reservation_status='SETTLED'
             AND NULLIF(cost_evidence_id,'') IS NOT NULL
             AND cost_evidence_version=0
             AND cost_evidence_hash ~ '^sha256:[0-9a-f]{64}$')
            OR
            (reservation_status<>'SETTLED'
             AND cost_evidence_id IS NULL
             AND cost_evidence_version IS NULL
             AND cost_evidence_hash IS NULL)
        )
    )
    """,
    """
    CREATE INDEX authority_book_opening_legacy_budget_attribution_scope_idx
    ON authority_book_opening_legacy_budget_reservation_attribution(
        budget_scope_id,budget_scope_revision,opening_run_id
    )
    """,
    """
    CREATE TRIGGER authority_book_opening_legacy_budget_attribution_immutable
    BEFORE UPDATE OR DELETE
    ON authority_book_opening_legacy_budget_reservation_attribution
    FOR EACH ROW EXECUTE FUNCTION novel_forge_reject_immutable_mutation()
    """,
    """
    CREATE TABLE authority_book_opening_budget_operation_binding (
        operation_budget_binding_id TEXT PRIMARY KEY,
        operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        opening_run_id TEXT NOT NULL
            REFERENCES authority_book_opening_run(opening_run_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        budget_scope_id TEXT NOT NULL,
        budget_scope_revision BIGINT NOT NULL,
        opening_execution_id TEXT NOT NULL,
        opening_execution_generation BIGINT NOT NULL,
        runtime_job_id TEXT NOT NULL,
        runtime_attempt_id TEXT NOT NULL,
        runtime_lease_id TEXT NOT NULL,
        runtime_worker_id TEXT NOT NULL,
        runtime_fencing_token BIGINT NOT NULL,
        binding_source TEXT NOT NULL,
        bound_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(
            operation_id,opening_execution_id,opening_execution_generation,
            runtime_attempt_id,runtime_fencing_token
        ),
        UNIQUE(operation_budget_binding_id,operation_id),
        FOREIGN KEY(budget_scope_id,budget_scope_revision)
            REFERENCES authority_provider_budget_scope(budget_scope_id,revision)
            DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY(
            opening_run_id,opening_execution_id,opening_execution_generation
        ) REFERENCES authority_book_opening_execution(
            opening_run_id,opening_execution_id,generation
        ) DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY(
            runtime_job_id,runtime_attempt_id,runtime_lease_id,
            runtime_worker_id,runtime_fencing_token
        ) REFERENCES authority_runtime_job_lease(
            runtime_job_id,attempt_id,lease_id,worker_id,fencing_token
        ) DEFERRABLE INITIALLY DEFERRED,
        CHECK (budget_scope_revision=1),
        CHECK (opening_execution_generation>0),
        CHECK (runtime_fencing_token>0),
        CHECK (binding_source IN (
            'EXPLICIT_OPENING_CONTEXT','CAUSATION_LINEAGE',
            'LEGACY_RECONCILIATION'
        ))
    )
    """,
    """
    CREATE INDEX authority_book_opening_budget_operation_owner_idx
    ON authority_book_opening_budget_operation_binding(
        opening_run_id,budget_scope_id,budget_scope_revision,
        opening_execution_generation
    )
    """,
    """
    CREATE TRIGGER authority_book_opening_budget_operation_binding_immutable
    BEFORE UPDATE OR DELETE
    ON authority_book_opening_budget_operation_binding
    FOR EACH ROW EXECUTE FUNCTION novel_forge_reject_immutable_mutation()
    """,
    """
    CREATE TABLE authority_book_opening_budget_effect_binding (
        budget_effect_binding_id TEXT PRIMARY KEY,
        external_effect_id TEXT NOT NULL
            REFERENCES authority_external_effect(external_effect_id),
        operation_budget_binding_id TEXT NOT NULL,
        operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        opening_run_id TEXT NOT NULL
            REFERENCES authority_book_opening_run(opening_run_id),
        budget_scope_id TEXT NOT NULL,
        budget_scope_revision BIGINT NOT NULL,
        reservation_id TEXT NOT NULL UNIQUE,
        reservation_version BIGINT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(external_effect_id,reservation_id),
        FOREIGN KEY(operation_budget_binding_id,operation_id)
            REFERENCES authority_book_opening_budget_operation_binding(
                operation_budget_binding_id,operation_id
            ) DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY(reservation_id,budget_scope_id,budget_scope_revision)
            REFERENCES authority_budget_reservation(
                reservation_id,budget_scope_id,budget_scope_revision
            ) DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY(budget_scope_id,budget_scope_revision)
            REFERENCES authority_provider_budget_scope(budget_scope_id,revision)
            DEFERRABLE INITIALLY DEFERRED,
        CHECK (budget_scope_revision=1),
        CHECK (reservation_version>=0)
    )
    """,
    """
    CREATE INDEX authority_book_opening_budget_effect_owner_idx
    ON authority_book_opening_budget_effect_binding(
        opening_run_id,operation_id,budget_scope_id,budget_scope_revision,
        external_effect_id
    )
    """,
    """
    CREATE TRIGGER authority_book_opening_budget_effect_binding_immutable
    BEFORE UPDATE OR DELETE
    ON authority_book_opening_budget_effect_binding
    FOR EACH ROW EXECUTE FUNCTION novel_forge_reject_immutable_mutation()
    """,
    """
    ALTER TABLE authority_book_opening_recovery_assessment
    ADD COLUMN assessment_contract_version TEXT NOT NULL
        DEFAULT 'book-opening-recovery-assessment.v1',
    ADD COLUMN budget_scope_id TEXT
        REFERENCES authority_provider_budget_scope(budget_scope_id),
    ADD COLUMN budget_scope_revision BIGINT,
    ADD COLUMN budget_policy_hash TEXT,
    ADD COLUMN budget_snapshot_digest TEXT,
    ADD COLUMN budget_outcome TEXT,
    ADD CONSTRAINT BOOK_OPENING_RECOVERY_ASSESSMENT_V2_BUDGET_INVALID CHECK (
        (
            assessment_contract_version=
                'book-opening-recovery-assessment.v1'
            AND budget_scope_id IS NULL
            AND budget_scope_revision IS NULL
            AND budget_policy_hash IS NULL
            AND budget_snapshot_digest IS NULL
            AND budget_outcome IS NULL
        ) OR (
            assessment_contract_version=
                'book-opening-recovery-assessment.v2'
            AND budget_scope_id IS NOT NULL
            AND budget_scope_revision > 0
            AND budget_policy_hash ~ '^sha256:[0-9a-f]{64}$'
            AND budget_snapshot_digest ~ '^sha256:[0-9a-f]{64}$'
            AND budget_outcome IN (
                'NOT_REQUIRED','ELIGIBLE','EXHAUSTED',
                'RECONCILIATION_REQUIRED'
            )
        )
    ),
    ADD CONSTRAINT authority_book_opening_assessment_budget_scope_revision_fk
        FOREIGN KEY(budget_scope_id,budget_scope_revision)
        REFERENCES authority_provider_budget_scope(budget_scope_id,revision)
        DEFERRABLE INITIALLY DEFERRED
    """,
    """
    CREATE INDEX authority_book_opening_assessment_budget_scope_idx
    ON authority_book_opening_recovery_assessment(
        budget_scope_id,budget_scope_revision,created_at
    ) WHERE budget_scope_id IS NOT NULL
    """,

    """
    ALTER TABLE authority_runtime_job
    ADD CONSTRAINT authority_book_opening_semantic_binding_shape_check CHECK (
        NOT (
            job_kind='BOOK_OPENING_EXECUTE'
            AND runtime_group='book_opening'
            AND subject_kind='BOOK_OPENING_RUN'
        ) OR (
            (
                NOT (input_snapshot ? 'semantic_execution_mode')
                AND input_snapshot->>'execution_generation'='1'
                AND COALESCE(input_snapshot->>'recovery_intent_id','')=''
                AND COALESCE(
                    input_snapshot->>'replacement_evaluation_operation_id',''
                )=''
            ) OR (
            input_snapshot ? 'semantic_evaluation_operation_id'
            AND input_snapshot ? 'semantic_evaluation_execution_id'
            AND input_snapshot ? 'semantic_evaluation_generation'
            AND input_snapshot ? 'semantic_execution_mode'
            AND input_snapshot->>'semantic_execution_mode' IN (
                'NONE','NEW_REPLACEMENT','RESUME_CURRENT'
            )
            AND (
                (
                    input_snapshot->>'semantic_execution_mode'='NONE'
                    AND input_snapshot->>'semantic_evaluation_operation_id'=''
                    AND input_snapshot->>'semantic_evaluation_execution_id'=''
                    AND input_snapshot->>'semantic_evaluation_generation'='0'
                ) OR (
                    input_snapshot->>'semantic_execution_mode' IN (
                        'NEW_REPLACEMENT','RESUME_CURRENT'
                    )
                    AND NULLIF(
                        input_snapshot->>'semantic_evaluation_operation_id',''
                    ) IS NOT NULL
                    AND NULLIF(
                        input_snapshot->>'semantic_evaluation_execution_id',''
                    ) IS NOT NULL
                    AND input_snapshot->>'semantic_evaluation_generation'
                        ~ '^[1-9][0-9]*$'
                )
            )
            )
        )
    ) NOT VALID
    """,

    """
    CREATE INDEX authority_runtime_job_semantic_evaluation_binding_idx
    ON authority_runtime_job(
        project_id,
        (input_snapshot->>'semantic_evaluation_operation_id'),
        (input_snapshot->>'semantic_evaluation_execution_id'),
        (input_snapshot->>'semantic_evaluation_generation'),
        (input_snapshot->>'semantic_execution_mode')
    ) WHERE job_kind='BOOK_OPENING_EXECUTE'
      AND runtime_group='book_opening'
      AND subject_kind='BOOK_OPENING_RUN'
      AND input_snapshot ? 'semantic_execution_mode'
    """,

    # Semantic execution has no independent switch. The derived gate is true
    # only for an ordinary generation-one Evaluation, its exact original
    # Opening fence, or one exact current NEW/RESUME recovery execution.
    """
    CREATE OR REPLACE FUNCTION authority_narrative_replacement_gate_is_open(
        p_operation_id TEXT,
        p_project_id TEXT
    ) RETURNS BOOLEAN LANGUAGE plpgsql VOLATILE AS $$
    DECLARE
        evaluation RECORD;
        opening_binding JSONB;
        recovery_bound BOOLEAN;
        recovery_open BOOLEAN;
    BEGIN
        IF NULLIF(p_operation_id,'') IS NULL
           OR NULLIF(p_project_id,'') IS NULL THEN
            RETURN FALSE;
        END IF;
        SELECT
            execution.evaluation_execution_id,
            execution.generation,
            execution.project_id,
            execution.book_id,
            execution.candidate_asset_version_id,
            execution.candidate_content_hash,
            execution.recovery_intent_id,
            execution.predecessor_execution_id,
            execution.predecessor_generation,
            execution.predecessor_operation_id,
            operation.command_payload->'payload'->>'generation_operation_id'
                AS generation_operation_id,
            COALESCE(
                generation_operation.command_payload->'payload'->
                    'opening_execution_binding',
                generation_operation.command_payload->
                    'opening_execution_binding'
            ) AS opening_execution_binding,
            head.current_execution_id=execution.evaluation_execution_id
                AND head.current_generation=execution.generation AS head_current,
            operation.command_payload->'payload'->>'book_id'=
                execution.book_id
                AND operation.command_payload->'payload'->>
                    'candidate_asset_version_id'=
                    execution.candidate_asset_version_id
                AND operation.command_payload->'payload'->>
                    'candidate_content_hash'=execution.candidate_content_hash
                AND COALESCE(
                    operation.command_payload->'payload'->
                        'opening_execution_binding',
                    '{}'::jsonb
                )=COALESCE(
                    generation_operation.command_payload->'payload'->
                        'opening_execution_binding',
                    generation_operation.command_payload->
                        'opening_execution_binding',
                    '{}'::jsonb
                )
                AS operation_identity_current,
            generation_operation.project_id=execution.project_id
                AND generation_operation.status IN ('WAITING_GATE','SUCCEEDED')
                AND generation_output.operation_id=
                    generation_operation.operation_id
                AND generation_output.asset_version_id=
                    execution.candidate_asset_version_id
                AND generation_output.content_hash=
                    execution.candidate_content_hash
                AND (
                    (
                        (
                            generation_operation.definition_name=
                                operation.command_payload->'payload'->>
                                    'generator_operation_name'
                            OR (
                                generation_operation.definition_name=
                                    'story_planning.generate'
                                AND generation_operation.command_payload->
                                    'payload'->>'generator_operation_name'=
                                    operation.command_payload->'payload'->>
                                        'generator_operation_name'
                            )
                        )
                        AND COALESCE(
                            generation_operation.command_payload->'payload'->>
                                'book_id',
                            generation_operation.command_payload->>'book_id'
                        )=execution.book_id
                    ) OR (
                        generation_operation.status='SUCCEEDED'
                        AND generation_operation.definition_name=CASE
                            operation.command_payload->'payload'->>
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
                        AND generation_asset.project_id=execution.project_id
                        AND generation_asset.asset_type=CASE
                            operation.command_payload->'payload'->>
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
                            execution.candidate_content_hash
                        AND generation_version.content->>'project_id'=
                            execution.project_id
                        AND generation_version.content->>
                            'generator_operation_name'=
                            operation.command_payload->'payload'->>
                                'generator_operation_name'
                        AND generation_version.content->>'operator_authored'=
                            'true'
                        AND generation_version.content->>'provider_generated'=
                            'false'
                        AND design_state.source_kind='OPERATOR_AUTHORED'
                        AND design_state.generator_operation_name=
                            operation.command_payload->'payload'->>
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
                        execution.generation=1
                        AND operation.causation_operation_id=
                            generation_operation.operation_id
                    ) OR (
                        execution.generation>1
                        AND operation.causation_operation_id=
                            execution.predecessor_operation_id
                    )
                ) AS generation_identity_current
        INTO evaluation
        FROM authority_narrative_evaluation_execution AS execution
        JOIN authority_operation AS operation
          ON operation.operation_id=execution.operation_id
         AND operation.project_id=execution.project_id
         AND operation.definition_name='story_design.semantic_evaluate'
        LEFT JOIN authority_operation AS generation_operation
          ON generation_operation.operation_id=
             operation.command_payload->'payload'->>'generation_operation_id'
         AND generation_operation.project_id=execution.project_id
        LEFT JOIN authority_operation_output_asset AS generation_output
          ON generation_output.operation_id=generation_operation.operation_id
         AND generation_output.asset_version_id=
             execution.candidate_asset_version_id
         AND generation_output.content_hash=execution.candidate_content_hash
        LEFT JOIN authority_asset_version AS generation_version
          ON generation_version.asset_version_id=
             generation_output.asset_version_id
        LEFT JOIN authority_asset AS generation_asset
          ON generation_asset.asset_id=generation_version.asset_id
        LEFT JOIN authority_story_design_version_state AS design_state
          ON design_state.project_id=execution.project_id
         AND design_state.asset_version_id=
             execution.candidate_asset_version_id
        LEFT JOIN authority_narrative_evaluation_execution_head AS head
          ON head.project_id=execution.project_id
         AND head.candidate_asset_version_id=
             execution.candidate_asset_version_id
        WHERE execution.operation_id=p_operation_id
          AND execution.project_id=p_project_id;
        IF NOT FOUND
           OR evaluation.generation<=0
           OR NULLIF(evaluation.evaluation_execution_id,'') IS NULL
           OR NULLIF(evaluation.book_id,'') IS NULL
           OR NULLIF(evaluation.candidate_asset_version_id,'') IS NULL
           OR NULLIF(evaluation.candidate_content_hash,'') IS NULL
           OR NULLIF(evaluation.generation_operation_id,'') IS NULL
           OR evaluation.head_current IS DISTINCT FROM TRUE
           OR evaluation.operation_identity_current IS DISTINCT FROM TRUE
           OR evaluation.generation_identity_current IS DISTINCT FROM TRUE
           OR (
               evaluation.generation=1
               AND (
                   evaluation.predecessor_execution_id IS NOT NULL
                   OR evaluation.predecessor_generation IS NOT NULL
                   OR evaluation.predecessor_operation_id IS NOT NULL
                   OR evaluation.recovery_intent_id IS NOT NULL
               )
           )
           OR (
               evaluation.generation>1
               AND (
                   NULLIF(evaluation.predecessor_execution_id,'') IS NULL
                   OR evaluation.predecessor_generation IS DISTINCT FROM
                      evaluation.generation-1
                   OR NULLIF(evaluation.predecessor_operation_id,'') IS NULL
                   OR NULLIF(evaluation.recovery_intent_id,'') IS NULL
               )
           ) THEN
            RETURN FALSE;
        END IF;

        SELECT EXISTS (
            SELECT 1
            FROM authority_runtime_job AS job
            WHERE job.project_id=evaluation.project_id
              AND job.job_kind='BOOK_OPENING_EXECUTE'
              AND job.runtime_group='book_opening'
              AND job.subject_kind='BOOK_OPENING_RUN'
              AND job.input_snapshot->>'semantic_evaluation_operation_id'=
                  p_operation_id
              AND job.input_snapshot->>'semantic_evaluation_execution_id'=
                  evaluation.evaluation_execution_id
              AND job.input_snapshot->>'semantic_evaluation_generation'=
                  evaluation.generation::text
              AND job.input_snapshot->>'semantic_execution_mode' IN (
                  'NEW_REPLACEMENT','RESUME_CURRENT'
              )
        ) INTO recovery_bound;

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
            JOIN authority_book_opening_recovery_intent AS intent
              ON intent.recovery_intent_id=
                 opening_execution.recovery_intent_id
             AND intent.opening_run_id=opening.opening_run_id
             AND intent.successor_generation=opening_execution.generation
            JOIN authority_book_opening_recovery_assessment AS assessment
              ON assessment.recovery_assessment_id=intent.recovery_assessment_id
             AND assessment.opening_run_id=opening.opening_run_id
             AND assessment.assessment_kind='RECOVERY'
             AND assessment.disposition NOT IN (
                 'UNKNOWN_AMBIGUOUS','RECONCILIATION_REQUIRED'
             )
             AND assessment.opening_execution_id=
                 intent.predecessor_execution_id
             AND assessment.execution_generation=
                 intent.predecessor_generation
             AND assessment.snapshot->'opening'->>'opening_run_id'=
                 opening.opening_run_id
             AND assessment.snapshot->'opening'->>'current_execution_id'=
                 intent.predecessor_execution_id
             AND assessment.snapshot->'opening'->>
                 'current_execution_generation'=
                 intent.predecessor_generation::text
             AND assessment.snapshot->'execution'->>'opening_execution_id'=
                 intent.predecessor_execution_id
             AND assessment.snapshot->'execution'->>'generation'=
                 intent.predecessor_generation::text
            JOIN authority_book_opening_recovery_receipt AS receipt
              ON receipt.receipt_kind='RECOVERY_ADMISSION'
             AND receipt.opening_run_id=opening.opening_run_id
             AND receipt.recovery_assessment_id=
                 assessment.recovery_assessment_id
             AND receipt.recovery_intent_id=intent.recovery_intent_id
             AND receipt.predecessor_execution_id=
                 intent.predecessor_execution_id
             AND receipt.predecessor_generation=intent.predecessor_generation
             AND receipt.successor_execution_id=
                 opening_execution.opening_execution_id
             AND receipt.successor_generation=opening_execution.generation
            JOIN authority_runtime_job AS job
              ON job.runtime_job_id=opening_execution.runtime_job_id
             AND job.project_id=opening.project_id
             AND job.job_kind='BOOK_OPENING_EXECUTE'
             AND job.runtime_group='book_opening'
             AND job.subject_kind='BOOK_OPENING_RUN'
             AND job.subject_id=opening.opening_run_id
             AND job.input_hash=opening_execution.input_snapshot_hash
             AND job.lease_loss_policy='AUTHORITY_CONVERGENCE_REQUIRED'
             AND job.max_attempts=1
             AND job.status IN ('RUNNING','CHECKPOINTED')
             AND job.current_attempt_id IS NOT NULL
             AND job.current_fencing_token>0
             AND NULLIF(job.claimed_by,'') IS NOT NULL
             AND job.input_snapshot->>'opening_run_id'=
                 opening.opening_run_id
             AND job.input_snapshot->>'opening_execution_id'=
                 opening_execution.opening_execution_id
             AND job.input_snapshot->>'execution_generation'=
                 opening_execution.generation::text
             AND job.input_snapshot->>'frozen_request_digest'=
                 opening.frozen_request_digest
             AND job.input_snapshot->>'recovery_intent_id'=
                 intent.recovery_intent_id
             AND job.input_snapshot->>'semantic_evaluation_operation_id'=
                 p_operation_id
             AND job.input_snapshot->>'semantic_evaluation_execution_id'=
                 evaluation.evaluation_execution_id
             AND job.input_snapshot->>'semantic_evaluation_generation'=
                 evaluation.generation::text
             AND receipt.result->>'recovery_intent_id'=
                 intent.recovery_intent_id
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
            WHERE opening.project_id=evaluation.project_id
              AND opening.book_id=evaluation.book_id
              AND opening.execution_contract_version=
                  'book-opening-execution-v2'
              AND opening.lifecycle='RUNNING'
              AND opening.recovery_state='READY'
              AND opening_execution.current_attempt_id=attempt.attempt_id
              AND opening_execution.current_lease_id=lease.lease_id
              AND opening_execution.current_worker_id=attempt.worker_id
              AND opening_execution.current_fencing_token=
                  attempt.fencing_token
              AND opening_execution.predecessor_execution_id=
                  intent.predecessor_execution_id
              AND opening_execution.predecessor_generation=
                  intent.predecessor_generation
              AND (
                  (
                      job.input_snapshot->>'semantic_execution_mode'=
                          'NEW_REPLACEMENT'
                      AND evaluation.generation>1
                      AND intent.recovery_intent_id=
                          evaluation.recovery_intent_id
                      AND job.input_snapshot->>
                          'replacement_evaluation_operation_id'=
                          p_operation_id
                      AND receipt.result->>
                          'replacement_evaluation_operation_id'=
                          p_operation_id
                      AND receipt.result->>
                          'replacement_evaluation_execution_id'=
                          evaluation.evaluation_execution_id
                      AND assessment.snapshot->'semantic_evaluation'->>
                          'operation_id'=
                          evaluation.predecessor_operation_id
                      AND assessment.snapshot->'semantic_evaluation'->>
                          'evaluation_execution_id'=
                          evaluation.predecessor_execution_id
                      AND assessment.snapshot->'semantic_evaluation'->>
                          'generation'=
                          evaluation.predecessor_generation::text
                      AND assessment.snapshot->'semantic_evaluation'->>
                          'candidate_asset_version_id'=
                          evaluation.candidate_asset_version_id
                      AND assessment.snapshot->'semantic_evaluation'->>
                          'candidate_content_hash'=
                          evaluation.candidate_content_hash
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
                          'operation_id'=p_operation_id
                      AND assessment.snapshot->'semantic_evaluation'->>
                          'evaluation_execution_id'=
                          evaluation.evaluation_execution_id
                      AND assessment.snapshot->'semantic_evaluation'->>
                          'generation'=evaluation.generation::text
                      AND assessment.snapshot->'semantic_evaluation'->>
                          'candidate_asset_version_id'=
                          evaluation.candidate_asset_version_id
                      AND assessment.snapshot->'semantic_evaluation'->>
                          'candidate_content_hash'=
                          evaluation.candidate_content_hash
                  )
              )
        ) INTO recovery_open;
        IF evaluation.generation>1 OR recovery_bound THEN
            RETURN recovery_open;
        END IF;

        opening_binding := evaluation.opening_execution_binding;
        IF opening_binding IS NULL OR opening_binding='{}'::JSONB THEN
            RETURN TRUE;
        END IF;
        IF jsonb_typeof(opening_binding) IS DISTINCT FROM 'object' THEN
            RETURN FALSE;
        END IF;
        IF (SELECT COUNT(*) FROM jsonb_object_keys(opening_binding))<>8
           OR NOT opening_binding ?& ARRAY[
               'opening_run_id','opening_execution_id',
               'opening_execution_generation','runtime_job_id',
               'runtime_attempt_id','runtime_lease_id','runtime_worker_id',
               'runtime_fencing_token'
           ] THEN
            RETURN FALSE;
        END IF;
        RETURN EXISTS (
            SELECT 1
            FROM authority_book_opening_run AS opening
            JOIN authority_book_opening_execution AS opening_execution
              ON opening_execution.opening_run_id=opening.opening_run_id
             AND opening_execution.opening_execution_id=
                 opening_binding->>'opening_execution_id'
             AND opening_execution.generation::text=
                 opening_binding->>'opening_execution_generation'
             AND opening_execution.runtime_job_id=
                 opening_binding->>'runtime_job_id'
             AND opening_execution.current_attempt_id=
                 opening_binding->>'runtime_attempt_id'
             AND opening_execution.current_lease_id=
                 opening_binding->>'runtime_lease_id'
             AND opening_execution.current_worker_id=
                 opening_binding->>'runtime_worker_id'
             AND opening_execution.current_fencing_token::text=
                 opening_binding->>'runtime_fencing_token'
             AND opening_execution.lifecycle='RUNNING'
             AND opening_execution.frozen_request_digest=
                 opening.frozen_request_digest
            JOIN authority_runtime_job AS job
              ON job.runtime_job_id=opening_execution.runtime_job_id
             AND job.project_id=opening.project_id
             AND job.job_kind='BOOK_OPENING_EXECUTE'
             AND job.runtime_group='book_opening'
             AND job.subject_kind='BOOK_OPENING_RUN'
             AND job.subject_id=opening.opening_run_id
             AND job.input_hash=opening_execution.input_snapshot_hash
             AND job.lease_loss_policy='AUTHORITY_CONVERGENCE_REQUIRED'
             AND job.max_attempts=1
             AND job.status IN ('RUNNING','CHECKPOINTED')
             AND job.current_attempt_id=
                 opening_binding->>'runtime_attempt_id'
             AND job.current_fencing_token::text=
                 opening_binding->>'runtime_fencing_token'
             AND job.claimed_by=opening_binding->>'runtime_worker_id'
             AND job.input_snapshot->>'opening_run_id'=
                 opening.opening_run_id
             AND job.input_snapshot->>'opening_execution_id'=
                 opening_execution.opening_execution_id
             AND job.input_snapshot->>'execution_generation'=
                 opening_execution.generation::text
            JOIN authority_runtime_job_attempt AS attempt
              ON attempt.runtime_job_id=job.runtime_job_id
             AND attempt.attempt_id=job.current_attempt_id
             AND attempt.attempt_number=job.attempt_count
             AND attempt.lease_id=opening_binding->>'runtime_lease_id'
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
            WHERE opening.opening_run_id=opening_binding->>'opening_run_id'
              AND opening.project_id=evaluation.project_id
              AND opening.book_id=evaluation.book_id
              AND opening.execution_contract_version=
                  'book-opening-execution-v2'
              AND opening.lifecycle='RUNNING'
              AND opening.recovery_state='READY'
              AND opening.current_execution_id=
                  opening_execution.opening_execution_id
              AND opening.current_execution_generation=
                  opening_execution.generation
        );
    END;
    $$
    """,
    """
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1
            FROM authority_operation AS operation
            WHERE operation.definition_name='story_design.semantic_evaluate'
              AND operation.status IN ('READY','EXECUTING')
              AND NOT authority_narrative_replacement_gate_is_open(
                  operation.operation_id,operation.project_id
              )
        ) OR EXISTS (
            SELECT 1
            FROM authority_narrative_evaluation_execution AS evaluation
            WHERE evaluation.lifecycle='RUNNING'
              AND NOT authority_narrative_replacement_gate_is_open(
                  evaluation.operation_id,evaluation.project_id
              )
        ) OR EXISTS (
            SELECT 1
            FROM authority_attempt AS attempt
            JOIN authority_operation AS operation
              ON operation.operation_id=attempt.operation_id
             AND operation.definition_name=
                 'story_design.semantic_evaluate'
            WHERE attempt.status IN (
                'CREATED','QUEUED','LEASED','RUNNING','CHECKPOINTED',
                'RESULT_SUBMITTED'
            )
              AND NOT authority_narrative_replacement_gate_is_open(
                  operation.operation_id,operation.project_id
              )
        ) OR EXISTS (
            SELECT 1
            FROM authority_external_effect AS effect
            JOIN authority_operation AS operation
              ON operation.operation_id=effect.operation_id
             AND operation.definition_name=
                 'story_design.semantic_evaluate'
            WHERE effect.status IN ('READY','DISPATCHING')
              AND NOT authority_narrative_replacement_gate_is_open(
                  operation.operation_id,operation.project_id
              )
        ) OR EXISTS (
            SELECT 1
            FROM authority_effect_dispatch_lease AS effect_lease
            JOIN authority_external_effect_dispatch AS dispatch
              ON dispatch.dispatch_id=effect_lease.dispatch_id
            JOIN authority_external_effect AS effect
              ON effect.external_effect_id=dispatch.external_effect_id
            JOIN authority_operation AS operation
              ON operation.operation_id=effect.operation_id
             AND operation.definition_name=
                 'story_design.semantic_evaluate'
            WHERE effect_lease.status='HELD'
              AND NOT authority_narrative_replacement_gate_is_open(
                  operation.operation_id,operation.project_id
              )
        ) THEN
            RAISE EXCEPTION
                'NARRATIVE_EVALUATION_ACTIVE_EXECUTION_GATE_INVALID'
                USING ERRCODE='check_violation';
        END IF;
    END;
    $$
    """,
    """
    CREATE OR REPLACE FUNCTION
        authority_narrative_replacement_operation_gate_guard()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.definition_name='story_design.semantic_evaluate'
           AND NEW.status IN ('READY','EXECUTING')
           AND NOT authority_narrative_replacement_gate_is_open(
               NEW.operation_id,NEW.project_id
           ) THEN
            RAISE EXCEPTION
                'NARRATIVE_EVALUATION_REPLACEMENT_EXECUTION_GATE_CLOSED:%',
                NEW.operation_id USING ERRCODE='check_violation';
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE TRIGGER authority_narrative_replacement_operation_gate
    BEFORE INSERT OR UPDATE ON authority_operation
    FOR EACH ROW EXECUTE FUNCTION
        authority_narrative_replacement_operation_gate_guard()
    """,
    """
    CREATE OR REPLACE FUNCTION
        authority_narrative_replacement_evaluation_gate_guard()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.lifecycle='RUNNING'
           AND NOT authority_narrative_replacement_gate_is_open(
               NEW.operation_id,NEW.project_id
           ) THEN
            RAISE EXCEPTION
                'NARRATIVE_EVALUATION_REPLACEMENT_EXECUTION_GATE_CLOSED:%',
                NEW.operation_id USING ERRCODE='check_violation';
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE TRIGGER authority_narrative_replacement_evaluation_gate
    BEFORE INSERT OR UPDATE
    ON authority_narrative_evaluation_execution
    FOR EACH ROW EXECUTE FUNCTION
        authority_narrative_replacement_evaluation_gate_guard()
    """,
    """
    CREATE OR REPLACE FUNCTION
        authority_narrative_replacement_attempt_gate_guard()
    RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE
        operation_project_id TEXT;
        operation_definition_name TEXT;
    BEGIN
        IF NEW.status NOT IN (
            'CREATED','QUEUED','LEASED','RUNNING','CHECKPOINTED',
            'RESULT_SUBMITTED'
        ) THEN
            RETURN NEW;
        END IF;
        SELECT operation.project_id,operation.definition_name
        INTO operation_project_id,operation_definition_name
        FROM authority_operation AS operation
        WHERE operation.operation_id=NEW.operation_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION
                'NARRATIVE_EVALUATION_OPERATION_LINEAGE_MISSING:%',
                NEW.operation_id USING ERRCODE='check_violation';
        END IF;
        IF operation_definition_name='story_design.semantic_evaluate'
           AND NOT authority_narrative_replacement_gate_is_open(
               NEW.operation_id,operation_project_id
           ) THEN
            RAISE EXCEPTION
                'NARRATIVE_EVALUATION_REPLACEMENT_EXECUTION_GATE_CLOSED:%',
                NEW.operation_id USING ERRCODE='check_violation';
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE TRIGGER authority_narrative_replacement_attempt_gate
    BEFORE INSERT OR UPDATE OF status ON authority_attempt
    FOR EACH ROW EXECUTE FUNCTION
        authority_narrative_replacement_attempt_gate_guard()
    """,
    """
    CREATE OR REPLACE FUNCTION
        authority_narrative_replacement_effect_gate_guard()
    RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE
        operation_project_id TEXT;
        operation_definition_name TEXT;
    BEGIN
        IF NEW.status NOT IN ('READY','DISPATCHING') THEN
            RETURN NEW;
        END IF;
        SELECT operation.project_id,operation.definition_name
        INTO operation_project_id,operation_definition_name
        FROM authority_operation AS operation
        WHERE operation.operation_id=NEW.operation_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION
                'NARRATIVE_EVALUATION_OPERATION_LINEAGE_MISSING:%',
                NEW.operation_id USING ERRCODE='check_violation';
        END IF;
        IF operation_definition_name='story_design.semantic_evaluate'
           AND NOT authority_narrative_replacement_gate_is_open(
               NEW.operation_id,operation_project_id
           ) THEN
            RAISE EXCEPTION
                'NARRATIVE_EVALUATION_REPLACEMENT_EXECUTION_GATE_CLOSED:%',
                NEW.operation_id USING ERRCODE='check_violation';
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE TRIGGER authority_narrative_replacement_effect_gate
    BEFORE INSERT OR UPDATE ON authority_external_effect
    FOR EACH ROW EXECUTE FUNCTION
        authority_narrative_replacement_effect_gate_guard()
    """,
    """
    CREATE OR REPLACE FUNCTION
        authority_narrative_replacement_dispatch_gate_guard()
    RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE
        effect_operation_id TEXT;
        operation_project_id TEXT;
        operation_definition_name TEXT;
    BEGIN
        IF NEW.status<>'HELD' THEN
            RETURN NEW;
        END IF;
        SELECT effect.operation_id,operation.project_id,
               operation.definition_name
        INTO effect_operation_id,operation_project_id,
             operation_definition_name
        FROM authority_external_effect_dispatch AS dispatch
        JOIN authority_external_effect AS effect
          ON effect.external_effect_id=dispatch.external_effect_id
        JOIN authority_operation AS operation
          ON operation.operation_id=effect.operation_id
        WHERE dispatch.dispatch_id=NEW.dispatch_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION
                'NARRATIVE_EVALUATION_DISPATCH_LINEAGE_MISSING:%',
                NEW.dispatch_id USING ERRCODE='check_violation';
        END IF;
        IF operation_definition_name='story_design.semantic_evaluate'
           AND NOT authority_narrative_replacement_gate_is_open(
               effect_operation_id,operation_project_id
           ) THEN
            RAISE EXCEPTION
                'NARRATIVE_EVALUATION_REPLACEMENT_EXECUTION_GATE_CLOSED:%',
                effect_operation_id USING ERRCODE='check_violation';
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE TRIGGER authority_narrative_replacement_dispatch_gate
    BEFORE INSERT OR UPDATE ON authority_effect_dispatch_lease
    FOR EACH ROW EXECUTE FUNCTION
        authority_narrative_replacement_dispatch_gate_guard()
    """,
    """
    CREATE INDEX authority_bo_branch_assess_evidence_fk_idx
    ON authority_book_opening_branch_reconciliation_assessment(
        reconciliation_evidence_id,membership_id,opening_run_id,
        opening_execution_id,execution_generation
    )
    """,
    """
    CREATE INDEX authority_bo_branch_receipt_evidence_fk_idx
    ON authority_book_opening_branch_reconciliation_receipt(
        reconciliation_evidence_id,membership_id,opening_run_id
    )
    """,
    """
    CREATE INDEX authority_bo_branch_receipt_assess_fk_idx
    ON authority_book_opening_branch_reconciliation_receipt(
        branch_reconciliation_assessment_id,reconciliation_evidence_id
    )
    """,
    """
    CREATE INDEX authority_bo_budget_effect_operation_fk_idx
    ON authority_book_opening_budget_effect_binding(
        operation_budget_binding_id,operation_id
    )
    """,
    """
    CREATE INDEX authority_bo_budget_effect_reservation_fk_idx
    ON authority_book_opening_budget_effect_binding(
        reservation_id,budget_scope_id,budget_scope_revision
    )
    """,
    """
    CREATE INDEX authority_bo_budget_op_opening_fk_idx
    ON authority_book_opening_budget_operation_binding(
        opening_run_id,opening_execution_id,opening_execution_generation
    )
    """,
    """
    CREATE INDEX authority_bo_budget_op_bound_by_fk_idx
    ON authority_book_opening_budget_operation_binding(bound_by_operation_id)
    """,
    """
    CREATE INDEX authority_bo_budget_op_project_fk_idx
    ON authority_book_opening_budget_operation_binding(project_id)
    """,
    """
    CREATE INDEX authority_bo_budget_op_runtime_fk_idx
    ON authority_book_opening_budget_operation_binding(
        runtime_job_id,runtime_attempt_id,runtime_lease_id,
        runtime_worker_id,runtime_fencing_token
    )
    """,
    """
    CREATE INDEX authority_bo_budget_receipt_scope_fk_idx
    ON authority_book_opening_budget_reconciliation_receipt(
        budget_scope_id,budget_scope_revision
    )
    """,
    """
    CREATE INDEX authority_bo_legacy_budget_actor_fk_idx
    ON authority_book_opening_legacy_budget_reservation_attribution(
        attributed_by_operation_id
    )
    """,
    """
    CREATE INDEX authority_bo_legacy_budget_effect_fk_idx
    ON authority_book_opening_legacy_budget_reservation_attribution(
        external_effect_id
    )
    """,
    """
    CREATE INDEX authority_bo_legacy_budget_operation_fk_idx
    ON authority_book_opening_legacy_budget_reservation_attribution(operation_id)
    """,
    """
    CREATE INDEX authority_bo_legacy_budget_project_fk_idx
    ON authority_book_opening_legacy_budget_reservation_attribution(project_id)
    """,
    """
    CREATE INDEX authority_budget_evidence_reservation_fk_idx
    ON authority_budget_evidence_link(
        reservation_id,budget_scope_id,budget_scope_revision
    )
    """,
    """
    CREATE INDEX authority_provider_budget_created_by_fk_idx
    ON authority_provider_budget_scope(created_by_operation_id)
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []
