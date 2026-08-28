from __future__ import annotations


MIGRATION_ID = "20260828_0102_book_opening_recovery_closure"
DOWN_REVISION = "20260826_0101_quality_qualification"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = (
    "preserve every terminal Operation, Attempt, Lease, RuntimeJob and Book "
    "Opening row; correct malformed legacy semantic-evaluation lineage through "
    "a later Authority reconciliation rather than rewriting execution history"
)


PREFLIGHT_STATEMENTS = [
    """
    SELECT 'semantic_evaluation_candidate_identity_missing', COUNT(*)
    FROM authority_operation
    WHERE definition_name='story_design.semantic_evaluate'
      AND (
          NULLIF(command_payload->'payload'->>'candidate_asset_version_id','')
              IS NULL
          OR NULLIF(command_payload->'payload'->>'candidate_content_hash','')
              IS NULL
          OR NULLIF(command_payload->'payload'->>'book_id','') IS NULL
      )
    """,
    """
    SELECT 'semantic_evaluation_candidate_identity_duplicate', COUNT(*)
    FROM (
        SELECT project_id,
               command_payload->'payload'->>'candidate_asset_version_id'
                   AS candidate_asset_version_id
        FROM authority_operation
        WHERE definition_name='story_design.semantic_evaluate'
        GROUP BY project_id,
                 command_payload->'payload'->>'candidate_asset_version_id'
        HAVING COUNT(*) > 1
    ) AS duplicate
    """,
    """
    SELECT 'semantic_evaluation_candidate_evidence_invalid', COUNT(*)
    FROM authority_operation AS operation
    LEFT JOIN authority_asset_version AS version
      ON version.asset_version_id=
         operation.command_payload->'payload'->>'candidate_asset_version_id'
    LEFT JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
    LEFT JOIN authority_book AS book
      ON book.project_id=operation.project_id
     AND book.book_id=operation.command_payload->'payload'->>'book_id'
    WHERE operation.definition_name='story_design.semantic_evaluate'
      AND (
          version.asset_version_id IS NULL
          OR asset.project_id IS DISTINCT FROM operation.project_id
          OR version.content_hash IS DISTINCT FROM
             operation.command_payload->'payload'->>'candidate_content_hash'
          OR book.book_id IS NULL
    )
    """,
    """
    SELECT 'runtime_job_active_claim_identity_invalid', COUNT(*)
    FROM authority_runtime_job AS job
    LEFT JOIN authority_runtime_job_attempt AS attempt
      ON attempt.runtime_job_id=job.runtime_job_id
     AND attempt.attempt_id=job.current_attempt_id
     AND attempt.fencing_token=job.current_fencing_token
    LEFT JOIN authority_runtime_job_lease AS lease
      ON lease.runtime_job_id=attempt.runtime_job_id
     AND lease.attempt_id=attempt.attempt_id
     AND lease.lease_id=attempt.lease_id
     AND lease.worker_id=attempt.worker_id
     AND lease.fencing_token=attempt.fencing_token
    WHERE job.status IN ('CLAIMED','RUNNING','CHECKPOINTED')
      AND (
          job.current_attempt_id IS NULL
          OR job.current_fencing_token <= 0
          OR NULLIF(job.claimed_by,'') IS NULL
          OR attempt.attempt_id IS NULL
          OR attempt.attempt_number IS DISTINCT FROM job.attempt_count
          OR attempt.status IS DISTINCT FROM job.status
          OR attempt.worker_id IS DISTINCT FROM job.claimed_by
          OR lease.lease_id IS NULL
          OR lease.status IS DISTINCT FROM 'HELD'
      )
    """,
]


UPGRADE_STATEMENTS = [
    """
    ALTER TABLE authority_runtime_job
    ADD COLUMN lease_loss_policy TEXT NOT NULL DEFAULT 'SAME_JOB_TAKEOVER',
    ADD CONSTRAINT authority_runtime_job_lease_loss_policy_check CHECK (
        lease_loss_policy IN (
            'SAME_JOB_TAKEOVER',
            'AUTHORITY_CONVERGENCE_REQUIRED'
        )
    )
    """,
    """
    UPDATE authority_runtime_job
    SET lease_loss_policy='AUTHORITY_CONVERGENCE_REQUIRED'
    WHERE job_kind='BOOK_OPENING_EXECUTE'
      AND runtime_group='book_opening'
      AND subject_kind='BOOK_OPENING_RUN'
    """,
    """
    ALTER TABLE authority_runtime_job
    ADD CONSTRAINT authority_book_opening_runtime_policy_check CHECK (
        NOT (
            job_kind='BOOK_OPENING_EXECUTE'
            AND runtime_group='book_opening'
            AND subject_kind='BOOK_OPENING_RUN'
        )
        OR lease_loss_policy='AUTHORITY_CONVERGENCE_REQUIRED'
    ) NOT VALID
    """,
    """
    CREATE OR REPLACE FUNCTION authority_book_opening_runtime_policy_guard()
    RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.job_kind='BOOK_OPENING_EXECUTE'
           AND NEW.runtime_group='book_opening'
           AND NEW.subject_kind='BOOK_OPENING_RUN' THEN
            IF TG_OP='INSERT' THEN
                -- Rolling old writers omit both fields and receive the former
                -- generic defaults.  Normalize only this exact operational
                -- contract before the NOT VALID check constrains the new row.
                NEW.lease_loss_policy='AUTHORITY_CONVERGENCE_REQUIRED';
                NEW.max_attempts=1;
            ELSIF (
                NEW.lease_loss_policy IS DISTINCT FROM
                    'AUTHORITY_CONVERGENCE_REQUIRED'
                OR NEW.max_attempts IS DISTINCT FROM 1
            ) AND NOT (
                OLD.job_kind='BOOK_OPENING_EXECUTE'
                AND OLD.runtime_group='book_opening'
                AND OLD.subject_kind='BOOK_OPENING_RUN'
                AND OLD.lease_loss_policy='AUTHORITY_CONVERGENCE_REQUIRED'
                AND OLD.max_attempts<>1
                AND NEW.lease_loss_policy IS NOT DISTINCT FROM
                    OLD.lease_loss_policy
                AND NEW.max_attempts IS NOT DISTINCT FROM OLD.max_attempts
            ) THEN
                RAISE EXCEPTION 'BOOK_OPENING_RUNTIME_POLICY_INVALID:%',
                    NEW.runtime_job_id
                    USING ERRCODE='check_violation';
            END IF;
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE TRIGGER authority_book_opening_runtime_policy_guard
    BEFORE INSERT OR UPDATE ON authority_runtime_job
    FOR EACH ROW EXECUTE FUNCTION authority_book_opening_runtime_policy_guard()
    """,
    """
    CREATE OR REPLACE FUNCTION authority_runtime_job_attempt_no_takeover_guard()
    RETURNS TRIGGER LANGUAGE plpgsql AS $$
    DECLARE
        runtime_policy TEXT;
        prior_attempt_exists BOOLEAN;
    BEGIN
        -- Lock RuntimeJob first, matching every claim path.  This serializes
        -- concurrent first-attempt inserts before checking append-only lineage.
        SELECT lease_loss_policy INTO runtime_policy
        FROM authority_runtime_job
        WHERE runtime_job_id=NEW.runtime_job_id
        FOR UPDATE;
        IF NOT FOUND THEN
            RETURN NEW;
        END IF;
        IF runtime_policy='AUTHORITY_CONVERGENCE_REQUIRED' THEN
            SELECT EXISTS (
                SELECT 1 FROM authority_runtime_job_attempt
                WHERE runtime_job_id=NEW.runtime_job_id
            ) INTO prior_attempt_exists;
            IF NEW.attempt_number IS DISTINCT FROM 1 OR prior_attempt_exists THEN
                RAISE EXCEPTION
                    'RUNTIME_JOB_AUTHORITY_ATTEMPT_REPLACEMENT_FORBIDDEN:%',
                    NEW.runtime_job_id
                    USING ERRCODE='check_violation';
            END IF;
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE TRIGGER authority_runtime_job_attempt_no_takeover_guard
    BEFORE INSERT ON authority_runtime_job_attempt
    FOR EACH ROW
    EXECUTE FUNCTION authority_runtime_job_attempt_no_takeover_guard()
    """,
    """
    ALTER TABLE authority_book_opening_run
    ADD COLUMN execution_contract_version TEXT NOT NULL
        DEFAULT 'legacy-unbound',
    ADD COLUMN current_execution_id TEXT,
    ADD COLUMN current_execution_generation BIGINT,
    ADD COLUMN current_checkpoint_id TEXT,
    ADD COLUMN current_checkpoint_sequence BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN current_checkpoint_hash TEXT NOT NULL DEFAULT '',
    ADD COLUMN recovery_state TEXT NOT NULL
        DEFAULT 'LEGACY_RECONCILIATION_REQUIRED',
    ADD CONSTRAINT authority_book_opening_execution_pointer_shape_check CHECK (
        (current_execution_id IS NULL
         AND current_execution_generation IS NULL)
        OR
        (current_execution_id IS NOT NULL
         AND current_execution_generation > 0)
    ),
    ADD CONSTRAINT authority_book_opening_checkpoint_pointer_shape_check CHECK (
        (current_checkpoint_id IS NULL
         AND current_checkpoint_sequence=0
         AND current_checkpoint_hash='')
        OR
        (current_checkpoint_id IS NOT NULL
         AND current_checkpoint_sequence > 0
         AND current_checkpoint_hash ~ '^sha256:[0-9a-f]{64}$')
    ),
    ADD CONSTRAINT authority_book_opening_recovery_state_check CHECK (
        recovery_state IN (
            'READY',
            'EXECUTION_LOSS_PENDING',
            'RECOVERY_REQUIRED',
            'RECOVERY_ASSESSED',
            'RECOVERY_ADMITTED',
            'LEGACY_RECONCILIATION_REQUIRED'
        )
    )
    """,
    """
    CREATE TABLE authority_book_opening_execution (
        opening_execution_id TEXT PRIMARY KEY,
        opening_run_id TEXT NOT NULL
            REFERENCES authority_book_opening_run(opening_run_id),
        generation BIGINT NOT NULL,
        predecessor_execution_id TEXT,
        predecessor_generation BIGINT,
        recovery_intent_id TEXT UNIQUE,
        runtime_job_id TEXT UNIQUE
            REFERENCES authority_runtime_job(runtime_job_id),
        current_attempt_id TEXT,
        current_lease_id TEXT,
        current_worker_id TEXT,
        current_fencing_token BIGINT,
        lifecycle TEXT NOT NULL,
        frozen_request_digest TEXT NOT NULL,
        input_snapshot_hash TEXT NOT NULL,
        policy_snapshot_hash TEXT NOT NULL,
        authority_contract_hash TEXT NOT NULL,
        terminal_reason JSONB NOT NULL DEFAULT '{}'::jsonb,
        version BIGINT NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        started_at TIMESTAMPTZ,
        terminal_at TIMESTAMPTZ,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(opening_run_id, generation),
        UNIQUE(opening_run_id, opening_execution_id, generation),
        FOREIGN KEY(
            opening_run_id,
            predecessor_execution_id,
            predecessor_generation
        ) REFERENCES authority_book_opening_execution(
            opening_run_id,
            opening_execution_id,
            generation
        ) DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY(
            runtime_job_id,
            current_attempt_id,
            current_lease_id,
            current_worker_id,
            current_fencing_token
        ) REFERENCES authority_runtime_job_attempt(
            runtime_job_id,
            attempt_id,
            lease_id,
            worker_id,
            fencing_token
        ) DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY(
            runtime_job_id,
            current_attempt_id,
            current_lease_id,
            current_worker_id,
            current_fencing_token
        ) REFERENCES authority_runtime_job_lease(
            runtime_job_id,
            attempt_id,
            lease_id,
            worker_id,
            fencing_token
        ) DEFERRABLE INITIALLY DEFERRED,
        CHECK (generation > 0),
        CHECK (
            (generation=1
             AND predecessor_execution_id IS NULL
             AND predecessor_generation IS NULL
             AND recovery_intent_id IS NULL)
            OR
            (generation>1
             AND predecessor_execution_id IS NOT NULL
             AND predecessor_generation=generation-1
             AND recovery_intent_id IS NOT NULL)
        ),
        CHECK (lifecycle IN (
            'SCHEDULED','BOUND','RUNNING','SUCCEEDED','FAILED','LOST','ABORTED'
        )),
        CHECK (
            (current_attempt_id IS NULL
             AND current_lease_id IS NULL
             AND current_worker_id IS NULL
             AND current_fencing_token IS NULL)
            OR
            (current_attempt_id IS NOT NULL
             AND current_lease_id IS NOT NULL
             AND NULLIF(current_worker_id,'') IS NOT NULL
             AND current_fencing_token > 0)
        ),
        CHECK (
            lifecycle NOT IN ('BOUND','RUNNING')
            OR current_attempt_id IS NOT NULL
        ),
        CHECK (
            lifecycle <> 'SCHEDULED'
            OR current_attempt_id IS NULL
        ),
        CHECK (
            runtime_job_id IS NOT NULL
            OR (
                generation=1
                AND lifecycle IN ('FAILED','ABORTED')
                AND current_attempt_id IS NULL
                AND current_lease_id IS NULL
                AND current_worker_id IS NULL
                AND current_fencing_token IS NULL
            )
        ),
        CHECK (frozen_request_digest ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (input_snapshot_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (policy_snapshot_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (authority_contract_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (jsonb_typeof(terminal_reason)='object'),
        CHECK (
            (lifecycle IN ('SUCCEEDED','FAILED','LOST','ABORTED')
             AND terminal_at IS NOT NULL)
            OR
            (lifecycle NOT IN ('SUCCEEDED','FAILED','LOST','ABORTED')
             AND terminal_at IS NULL)
        )
    )
    """,
    """
    CREATE INDEX authority_book_opening_execution_opening_fk_idx
    ON authority_book_opening_execution(opening_run_id)
    """,
    """
    CREATE INDEX authority_book_opening_execution_predecessor_fk_idx
    ON authority_book_opening_execution(
        opening_run_id, predecessor_execution_id, predecessor_generation
    ) WHERE predecessor_execution_id IS NOT NULL
    """,
    """
    CREATE INDEX authority_book_opening_execution_attempt_fk_idx
    ON authority_book_opening_execution(
        runtime_job_id, current_attempt_id, current_lease_id,
        current_worker_id, current_fencing_token
    ) WHERE current_attempt_id IS NOT NULL
    """,
    """
    CREATE TABLE authority_book_opening_semantic_checkpoint (
        checkpoint_id TEXT PRIMARY KEY,
        opening_run_id TEXT NOT NULL
            REFERENCES authority_book_opening_run(opening_run_id),
        opening_execution_id TEXT NOT NULL,
        execution_generation BIGINT NOT NULL,
        checkpoint_sequence BIGINT NOT NULL,
        semantic_work_key TEXT NOT NULL,
        owning_authority TEXT NOT NULL,
        evidence_type TEXT NOT NULL,
        evidence_id TEXT NOT NULL,
        evidence_version BIGINT NOT NULL,
        evidence_hash TEXT NOT NULL,
        frozen_request_digest TEXT NOT NULL,
        predecessor_checkpoint_id TEXT,
        predecessor_checkpoint_sequence BIGINT,
        predecessor_checkpoint_hash TEXT,
        checkpoint_hash TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(opening_run_id, checkpoint_sequence),
        UNIQUE(opening_run_id, semantic_work_key),
        UNIQUE(
            opening_run_id,
            checkpoint_id,
            checkpoint_sequence,
            checkpoint_hash
        ),
        UNIQUE(
            opening_run_id,
            semantic_work_key,
            owning_authority,
            evidence_type,
            evidence_id,
            evidence_version,
            evidence_hash
        ),
        FOREIGN KEY(
            opening_run_id,
            opening_execution_id,
            execution_generation
        ) REFERENCES authority_book_opening_execution(
            opening_run_id,
            opening_execution_id,
            generation
        ) DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY(
            opening_run_id,
            predecessor_checkpoint_id,
            predecessor_checkpoint_sequence,
            predecessor_checkpoint_hash
        ) REFERENCES authority_book_opening_semantic_checkpoint(
            opening_run_id,
            checkpoint_id,
            checkpoint_sequence,
            checkpoint_hash
        ) DEFERRABLE INITIALLY DEFERRED,
        CHECK (execution_generation > 0),
        CHECK (checkpoint_sequence > 0),
        CHECK (evidence_version >= 0),
        CHECK (NULLIF(semantic_work_key,'') IS NOT NULL),
        CHECK (NULLIF(owning_authority,'') IS NOT NULL),
        CHECK (NULLIF(evidence_type,'') IS NOT NULL),
        CHECK (NULLIF(evidence_id,'') IS NOT NULL),
        CHECK (evidence_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (frozen_request_digest ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (checkpoint_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (
            (checkpoint_sequence=1
             AND predecessor_checkpoint_id IS NULL
             AND predecessor_checkpoint_sequence IS NULL
             AND predecessor_checkpoint_hash IS NULL)
            OR
            (checkpoint_sequence>1
             AND predecessor_checkpoint_id IS NOT NULL
             AND predecessor_checkpoint_sequence=checkpoint_sequence-1
             AND predecessor_checkpoint_hash ~ '^sha256:[0-9a-f]{64}$')
        )
    )
    """,
    """
    CREATE INDEX authority_book_opening_checkpoint_execution_fk_idx
    ON authority_book_opening_semantic_checkpoint(
        opening_run_id, opening_execution_id, execution_generation
    )
    """,
    """
    CREATE INDEX authority_book_opening_checkpoint_predecessor_fk_idx
    ON authority_book_opening_semantic_checkpoint(
        opening_run_id, predecessor_checkpoint_id,
        predecessor_checkpoint_sequence, predecessor_checkpoint_hash
    ) WHERE predecessor_checkpoint_id IS NOT NULL
    """,
    """
    CREATE TABLE authority_book_opening_recovery_assessment (
        recovery_assessment_id TEXT PRIMARY KEY,
        assessment_kind TEXT NOT NULL,
        opening_run_id TEXT NOT NULL
            REFERENCES authority_book_opening_run(opening_run_id),
        opening_version BIGINT NOT NULL,
        opening_execution_id TEXT,
        execution_generation BIGINT,
        runtime_job_id TEXT,
        runtime_attempt_id TEXT,
        runtime_lease_id TEXT,
        runtime_worker_id TEXT,
        runtime_fencing_token BIGINT,
        checkpoint_id TEXT,
        checkpoint_sequence BIGINT NOT NULL DEFAULT 0,
        checkpoint_hash TEXT NOT NULL DEFAULT '',
        evaluation_head_digest TEXT NOT NULL,
        external_effect_digest TEXT NOT NULL,
        policy_config_digest TEXT NOT NULL,
        authority_version_digest TEXT NOT NULL,
        snapshot JSONB NOT NULL,
        snapshot_hash TEXT NOT NULL,
        disposition TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(opening_run_id, recovery_assessment_id),
        UNIQUE(opening_run_id, assessment_kind, idempotency_key),
        FOREIGN KEY(
            opening_run_id,
            opening_execution_id,
            execution_generation
        ) REFERENCES authority_book_opening_execution(
            opening_run_id,
            opening_execution_id,
            generation
        ) DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY(
            runtime_job_id,
            runtime_attempt_id,
            runtime_lease_id,
            runtime_worker_id,
            runtime_fencing_token
        ) REFERENCES authority_runtime_job_lease(
            runtime_job_id,
            attempt_id,
            lease_id,
            worker_id,
            fencing_token
        ) DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY(
            opening_run_id,
            checkpoint_id,
            checkpoint_sequence,
            checkpoint_hash
        ) REFERENCES authority_book_opening_semantic_checkpoint(
            opening_run_id,
            checkpoint_id,
            checkpoint_sequence,
            checkpoint_hash
        ) DEFERRABLE INITIALLY DEFERRED,
        CHECK (assessment_kind IN (
            'EXECUTION_LOSS','RECOVERY','CHECKPOINT_RECONCILIATION',
            'LEGACY_EXECUTION_RECONCILIATION'
        )),
        CHECK (opening_version >= 0),
        CHECK (
            (opening_execution_id IS NULL AND execution_generation IS NULL)
            OR
            (opening_execution_id IS NOT NULL AND execution_generation > 0)
        ),
        CHECK (
            (runtime_job_id IS NULL
             AND runtime_attempt_id IS NULL
             AND runtime_lease_id IS NULL
             AND runtime_worker_id IS NULL
             AND runtime_fencing_token IS NULL)
            OR
            (runtime_job_id IS NOT NULL
             AND runtime_attempt_id IS NOT NULL
             AND runtime_lease_id IS NOT NULL
             AND NULLIF(runtime_worker_id,'') IS NOT NULL
             AND runtime_fencing_token > 0)
        ),
        CHECK (
            (checkpoint_id IS NULL
             AND checkpoint_sequence=0
             AND checkpoint_hash='')
            OR
            (checkpoint_id IS NOT NULL
             AND checkpoint_sequence > 0
             AND checkpoint_hash ~ '^sha256:[0-9a-f]{64}$')
        ),
        CHECK (evaluation_head_digest ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (external_effect_digest ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (policy_config_digest ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (authority_version_digest ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (snapshot_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (jsonb_typeof(snapshot)='object'),
        CHECK (disposition IN (
            'PROVEN_NO_EFFECT',
            'PROVEN_SUCCESS',
            'PROVEN_TERMINAL_FAILURE',
            'UNKNOWN_AMBIGUOUS',
            'EXECUTION_LOST',
            'RECONCILIATION_REQUIRED'
        ))
    )
    """,
    """
    CREATE INDEX authority_book_opening_assessment_execution_fk_idx
    ON authority_book_opening_recovery_assessment(
        opening_run_id, opening_execution_id, execution_generation
    ) WHERE opening_execution_id IS NOT NULL
    """,
    """
    CREATE INDEX authority_book_opening_assessment_runtime_fk_idx
    ON authority_book_opening_recovery_assessment(
        runtime_job_id, runtime_attempt_id, runtime_lease_id,
        runtime_worker_id, runtime_fencing_token
    ) WHERE runtime_job_id IS NOT NULL
    """,
    """
    CREATE INDEX authority_book_opening_assessment_checkpoint_fk_idx
    ON authority_book_opening_recovery_assessment(
        opening_run_id, checkpoint_id, checkpoint_sequence, checkpoint_hash
    ) WHERE checkpoint_id IS NOT NULL
    """,
    """
    CREATE TABLE authority_book_opening_recovery_intent (
        recovery_intent_id TEXT PRIMARY KEY,
        opening_run_id TEXT NOT NULL
            REFERENCES authority_book_opening_run(opening_run_id),
        recovery_assessment_id TEXT NOT NULL UNIQUE,
        predecessor_execution_id TEXT NOT NULL,
        predecessor_generation BIGINT NOT NULL,
        successor_generation BIGINT NOT NULL,
        idempotency_key TEXT NOT NULL,
        intent_hash TEXT NOT NULL,
        authorized_by TEXT NOT NULL,
        authorization_reason TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(opening_run_id, recovery_intent_id),
        UNIQUE(opening_run_id, successor_generation),
        UNIQUE(opening_run_id, idempotency_key),
        FOREIGN KEY(opening_run_id, recovery_assessment_id)
            REFERENCES authority_book_opening_recovery_assessment(
                opening_run_id,
                recovery_assessment_id
            ) DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY(
            opening_run_id,
            predecessor_execution_id,
            predecessor_generation
        ) REFERENCES authority_book_opening_execution(
            opening_run_id,
            opening_execution_id,
            generation
        ) DEFERRABLE INITIALLY DEFERRED,
        CHECK (predecessor_generation > 0),
        CHECK (successor_generation=predecessor_generation+1),
        CHECK (intent_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (NULLIF(authorized_by,'') IS NOT NULL),
        CHECK (NULLIF(authorization_reason,'') IS NOT NULL)
    )
    """,
    """
    CREATE INDEX authority_book_opening_intent_opening_fk_idx
    ON authority_book_opening_recovery_intent(opening_run_id)
    """,
    """
    CREATE INDEX authority_book_opening_intent_assessment_fk_idx
    ON authority_book_opening_recovery_intent(
        opening_run_id, recovery_assessment_id
    )
    """,
    """
    CREATE INDEX authority_book_opening_intent_predecessor_fk_idx
    ON authority_book_opening_recovery_intent(
        opening_run_id, predecessor_execution_id, predecessor_generation
    )
    """,
    """
    ALTER TABLE authority_book_opening_execution
    ADD CONSTRAINT authority_book_opening_execution_recovery_intent_fk
    FOREIGN KEY(recovery_intent_id)
    REFERENCES authority_book_opening_recovery_intent(recovery_intent_id)
    DEFERRABLE INITIALLY DEFERRED
    """,
    """
    CREATE TABLE authority_book_opening_recovery_receipt (
        recovery_receipt_id TEXT PRIMARY KEY,
        receipt_kind TEXT NOT NULL,
        opening_run_id TEXT NOT NULL
            REFERENCES authority_book_opening_run(opening_run_id),
        recovery_assessment_id TEXT NOT NULL,
        recovery_intent_id TEXT,
        predecessor_execution_id TEXT NOT NULL,
        predecessor_generation BIGINT NOT NULL,
        successor_execution_id TEXT,
        successor_generation BIGINT,
        result JSONB NOT NULL,
        result_hash TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(opening_run_id, receipt_kind, idempotency_key),
        UNIQUE(recovery_intent_id),
        FOREIGN KEY(opening_run_id, recovery_assessment_id)
            REFERENCES authority_book_opening_recovery_assessment(
                opening_run_id,
                recovery_assessment_id
            ) DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY(opening_run_id, recovery_intent_id)
            REFERENCES authority_book_opening_recovery_intent(
                opening_run_id,
                recovery_intent_id
            ) DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY(
            opening_run_id,
            predecessor_execution_id,
            predecessor_generation
        ) REFERENCES authority_book_opening_execution(
            opening_run_id,
            opening_execution_id,
            generation
        ) DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY(
            opening_run_id,
            successor_execution_id,
            successor_generation
        ) REFERENCES authority_book_opening_execution(
            opening_run_id,
            opening_execution_id,
            generation
        ) DEFERRABLE INITIALLY DEFERRED,
        CHECK (receipt_kind IN (
            'EXECUTION_LOSS_CONVERGENCE',
            'RECOVERY_ADMISSION',
            'CHECKPOINT_RECONCILIATION',
            'LEGACY_EXECUTION_RECONCILIATION'
        )),
        CHECK (predecessor_generation > 0),
        CHECK (
            (receipt_kind='RECOVERY_ADMISSION'
             AND recovery_intent_id IS NOT NULL
             AND successor_execution_id IS NOT NULL
             AND successor_generation=predecessor_generation+1)
            OR
            (receipt_kind='EXECUTION_LOSS_CONVERGENCE'
             AND recovery_intent_id IS NULL
             AND successor_execution_id IS NULL
             AND successor_generation IS NULL)
            OR
            (receipt_kind='CHECKPOINT_RECONCILIATION'
             AND recovery_intent_id IS NULL
             AND successor_execution_id IS NULL
             AND successor_generation IS NULL)
            OR
            (receipt_kind='LEGACY_EXECUTION_RECONCILIATION'
             AND recovery_intent_id IS NULL
             AND successor_execution_id IS NULL
             AND successor_generation IS NULL)
        ),
        CHECK (jsonb_typeof(result)='object'),
        CHECK (result_hash ~ '^sha256:[0-9a-f]{64}$')
    )
    """,
    """
    CREATE INDEX authority_book_opening_receipt_opening_fk_idx
    ON authority_book_opening_recovery_receipt(opening_run_id)
    """,
    """
    CREATE INDEX authority_book_opening_receipt_assessment_fk_idx
    ON authority_book_opening_recovery_receipt(
        opening_run_id, recovery_assessment_id
    )
    """,
    """
    CREATE INDEX authority_book_opening_receipt_intent_fk_idx
    ON authority_book_opening_recovery_receipt(
        opening_run_id, recovery_intent_id
    )
    WHERE recovery_intent_id IS NOT NULL
    """,
    """
    CREATE INDEX authority_book_opening_receipt_predecessor_fk_idx
    ON authority_book_opening_recovery_receipt(
        opening_run_id, predecessor_execution_id, predecessor_generation
    )
    """,
    """
    CREATE INDEX authority_book_opening_receipt_successor_fk_idx
    ON authority_book_opening_recovery_receipt(
        opening_run_id, successor_execution_id, successor_generation
    ) WHERE successor_execution_id IS NOT NULL
    """,
    """
    CREATE OR REPLACE FUNCTION authority_assert_book_opening_recovery_fact(
        target_recovery_assessment_id TEXT
    ) RETURNS VOID LANGUAGE plpgsql AS $$
    DECLARE
        assessment RECORD;
        receipt RECORD;
        intent_binding RECORD;
        successor_binding RECORD;
        opening_binding RECORD;
        predecessor_binding RECORD;
        expected_assessment_kind TEXT;
        matching_receipts BIGINT;
    BEGIN
        SELECT recovery_assessment_id,assessment_kind,opening_run_id,
               opening_execution_id,execution_generation,disposition
        INTO assessment
        FROM authority_book_opening_recovery_assessment
        WHERE recovery_assessment_id=target_recovery_assessment_id;
        IF NOT FOUND THEN
            RETURN;
        END IF;

        FOR intent_binding IN
            SELECT *
            FROM authority_book_opening_recovery_intent
            WHERE recovery_assessment_id=assessment.recovery_assessment_id
        LOOP
            IF assessment.assessment_kind IS DISTINCT FROM 'RECOVERY'
               OR assessment.disposition NOT IN (
                   'PROVEN_NO_EFFECT','PROVEN_SUCCESS',
                   'PROVEN_TERMINAL_FAILURE'
               )
               OR assessment.opening_execution_id IS DISTINCT FROM
                  intent_binding.predecessor_execution_id
               OR assessment.execution_generation IS DISTINCT FROM
                  intent_binding.predecessor_generation THEN
                RAISE EXCEPTION
                    'BOOK_OPENING_RECOVERY_INTENT_ASSESSMENT_BINDING_INVALID:%',
                    intent_binding.recovery_intent_id
                    USING ERRCODE='check_violation';
            END IF;
            SELECT COUNT(*) INTO matching_receipts
            FROM authority_book_opening_recovery_receipt
            WHERE recovery_intent_id=intent_binding.recovery_intent_id
              AND recovery_assessment_id=assessment.recovery_assessment_id
              AND receipt_kind='RECOVERY_ADMISSION';
            IF matching_receipts IS DISTINCT FROM 1::BIGINT THEN
                RAISE EXCEPTION
                    'BOOK_OPENING_RECOVERY_INTENT_RECEIPT_REQUIRED:%',
                    intent_binding.recovery_intent_id
                    USING ERRCODE='check_violation';
            END IF;
        END LOOP;

        FOR receipt IN
            SELECT *
            FROM authority_book_opening_recovery_receipt
            WHERE recovery_assessment_id=
                  assessment.recovery_assessment_id
        LOOP
            expected_assessment_kind = CASE receipt.receipt_kind
                WHEN 'EXECUTION_LOSS_CONVERGENCE' THEN 'EXECUTION_LOSS'
                WHEN 'RECOVERY_ADMISSION' THEN 'RECOVERY'
                WHEN 'CHECKPOINT_RECONCILIATION' THEN
                    'CHECKPOINT_RECONCILIATION'
                WHEN 'LEGACY_EXECUTION_RECONCILIATION' THEN
                    'LEGACY_EXECUTION_RECONCILIATION'
            END;
            IF assessment.assessment_kind IS DISTINCT FROM
               expected_assessment_kind THEN
                RAISE EXCEPTION
                    'BOOK_OPENING_RECOVERY_RECEIPT_ASSESSMENT_KIND_INVALID:%',
                    receipt.recovery_receipt_id
                    USING ERRCODE='check_violation';
            END IF;
            IF assessment.opening_execution_id IS DISTINCT FROM
               receipt.predecessor_execution_id
               OR assessment.execution_generation IS DISTINCT FROM
                  receipt.predecessor_generation THEN
                RAISE EXCEPTION
                    'BOOK_OPENING_RECOVERY_RECEIPT_ASSESSMENT_BINDING_INVALID:%',
                    receipt.recovery_receipt_id
                    USING ERRCODE='check_violation';
            END IF;
            IF (receipt.receipt_kind='EXECUTION_LOSS_CONVERGENCE'
                AND assessment.disposition IS DISTINCT FROM 'EXECUTION_LOST')
               OR (receipt.receipt_kind IN (
                       'CHECKPOINT_RECONCILIATION',
                       'LEGACY_EXECUTION_RECONCILIATION'
                   ) AND assessment.disposition IS DISTINCT FROM
                       'RECONCILIATION_REQUIRED') THEN
                RAISE EXCEPTION
                    'BOOK_OPENING_RECOVERY_RECEIPT_DISPOSITION_INVALID:%',
                    receipt.recovery_receipt_id
                    USING ERRCODE='check_violation';
            END IF;

            SELECT lifecycle,current_execution_id,current_execution_generation
            INTO opening_binding
            FROM authority_book_opening_run
            WHERE opening_run_id=receipt.opening_run_id;
            SELECT lifecycle INTO predecessor_binding
            FROM authority_book_opening_execution
            WHERE opening_run_id=receipt.opening_run_id
              AND opening_execution_id=receipt.predecessor_execution_id
              AND generation=receipt.predecessor_generation;

            IF receipt.receipt_kind='RECOVERY_ADMISSION' THEN
                SELECT recovery_intent_id,opening_run_id,
                       recovery_assessment_id,predecessor_execution_id,
                       predecessor_generation,successor_generation
                INTO intent_binding
                FROM authority_book_opening_recovery_intent
                WHERE recovery_intent_id=receipt.recovery_intent_id
                  AND opening_run_id=receipt.opening_run_id;
                IF NOT FOUND
                   OR intent_binding.recovery_assessment_id IS DISTINCT FROM
                      receipt.recovery_assessment_id
                   OR intent_binding.predecessor_execution_id IS DISTINCT FROM
                      receipt.predecessor_execution_id
                   OR intent_binding.predecessor_generation IS DISTINCT FROM
                      receipt.predecessor_generation
                   OR intent_binding.successor_generation IS DISTINCT FROM
                      receipt.successor_generation THEN
                    RAISE EXCEPTION
                        'BOOK_OPENING_RECOVERY_RECEIPT_INTENT_BINDING_INVALID:%',
                        receipt.recovery_receipt_id
                        USING ERRCODE='check_violation';
                END IF;

                SELECT predecessor_execution_id,predecessor_generation,
                       recovery_intent_id
                INTO successor_binding
                FROM authority_book_opening_execution
                WHERE opening_run_id=receipt.opening_run_id
                  AND opening_execution_id=receipt.successor_execution_id
                  AND generation=receipt.successor_generation;
                IF NOT FOUND
                   OR successor_binding.predecessor_execution_id
                      IS DISTINCT FROM receipt.predecessor_execution_id
                   OR successor_binding.predecessor_generation
                      IS DISTINCT FROM receipt.predecessor_generation
                   OR successor_binding.recovery_intent_id IS DISTINCT FROM
                      receipt.recovery_intent_id THEN
                    RAISE EXCEPTION
                        'BOOK_OPENING_RECOVERY_RECEIPT_INTENT_BINDING_INVALID:%',
                        receipt.recovery_receipt_id
                        USING ERRCODE='check_violation';
                END IF;
                IF opening_binding.lifecycle IS DISTINCT FROM 'ADMITTED'
                   OR opening_binding.current_execution_id IS DISTINCT FROM
                      receipt.successor_execution_id
                   OR opening_binding.current_execution_generation IS DISTINCT FROM
                      receipt.successor_generation THEN
                    RAISE EXCEPTION
                        'BOOK_OPENING_RECOVERY_RECEIPT_OPENING_BINDING_INVALID:%',
                        receipt.recovery_receipt_id
                        USING ERRCODE='check_violation';
                END IF;
            ELSIF opening_binding.current_execution_id IS DISTINCT FROM
                  receipt.predecessor_execution_id
               OR opening_binding.current_execution_generation IS DISTINCT FROM
                  receipt.predecessor_generation
               OR (
                   receipt.receipt_kind='EXECUTION_LOSS_CONVERGENCE'
                   AND (
                       opening_binding.lifecycle IS DISTINCT FROM 'FAILED'
                       OR predecessor_binding.lifecycle IS DISTINCT FROM 'LOST'
                   )
               )
               OR (
                   receipt.receipt_kind='CHECKPOINT_RECONCILIATION'
                   AND (
                       opening_binding.lifecycle IS DISTINCT FROM 'FAILED'
                       OR predecessor_binding.lifecycle NOT IN ('FAILED','LOST')
                   )
               ) THEN
                RAISE EXCEPTION
                    'BOOK_OPENING_RECOVERY_RECEIPT_OPENING_BINDING_INVALID:%',
                    receipt.recovery_receipt_id
                    USING ERRCODE='check_violation';
            END IF;
        END LOOP;
    END;
    $$
    """,
    """
    CREATE OR REPLACE FUNCTION authority_book_opening_recovery_fact_guard()
    RETURNS TRIGGER LANGUAGE plpgsql AS $$
    DECLARE
        target_recovery_assessment_id TEXT;
    BEGIN
        IF TG_OP='DELETE' THEN
            target_recovery_assessment_id=OLD.recovery_assessment_id;
        ELSE
            target_recovery_assessment_id=NEW.recovery_assessment_id;
        END IF;
        PERFORM authority_assert_book_opening_recovery_fact(
            target_recovery_assessment_id
        );
        RETURN NULL;
    END;
    $$
    """,
    *[
        f"""
        CREATE CONSTRAINT TRIGGER {table}_relationship_guard
        AFTER INSERT OR UPDATE OR DELETE ON {table}
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION authority_book_opening_recovery_fact_guard()
        """
        for table in (
            "authority_book_opening_recovery_assessment",
            "authority_book_opening_recovery_intent",
            "authority_book_opening_recovery_receipt",
        )
    ],
    """
    ALTER TABLE authority_book_opening_run
    ADD CONSTRAINT authority_book_opening_current_execution_fk
    FOREIGN KEY(
        opening_run_id,
        current_execution_id,
        current_execution_generation
    ) REFERENCES authority_book_opening_execution(
        opening_run_id,
        opening_execution_id,
        generation
    ) DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT authority_book_opening_current_checkpoint_fk
    FOREIGN KEY(
        opening_run_id,
        current_checkpoint_id,
        current_checkpoint_sequence,
        current_checkpoint_hash
    ) REFERENCES authority_book_opening_semantic_checkpoint(
        opening_run_id,
        checkpoint_id,
        checkpoint_sequence,
        checkpoint_hash
    ) DEFERRABLE INITIALLY DEFERRED
    """,
    """
    CREATE INDEX authority_book_opening_current_execution_fk_idx
    ON authority_book_opening_run(
        opening_run_id, current_execution_id, current_execution_generation
    ) WHERE current_execution_id IS NOT NULL
    """,
    """
    CREATE INDEX authority_book_opening_current_checkpoint_fk_idx
    ON authority_book_opening_run(
        opening_run_id, current_checkpoint_id,
        current_checkpoint_sequence, current_checkpoint_hash
    ) WHERE current_checkpoint_id IS NOT NULL
    """,
    """
    CREATE TABLE authority_narrative_evaluation_execution (
        evaluation_execution_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        book_id TEXT NOT NULL,
        candidate_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        candidate_content_hash TEXT NOT NULL,
        generation BIGINT NOT NULL,
        predecessor_execution_id TEXT,
        predecessor_generation BIGINT,
        predecessor_operation_id TEXT REFERENCES authority_operation(operation_id),
        recovery_intent_id TEXT UNIQUE
            REFERENCES authority_book_opening_recovery_intent(
                recovery_intent_id
            ),
        operation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_operation(operation_id),
        idempotency_scope TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        concurrency_key TEXT NOT NULL,
        lifecycle TEXT NOT NULL,
        terminal_reason JSONB NOT NULL DEFAULT '{}'::jsonb,
        version BIGINT NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        started_at TIMESTAMPTZ,
        terminal_at TIMESTAMPTZ,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, candidate_asset_version_id, generation),
        UNIQUE(
            project_id,
            candidate_asset_version_id,
            evaluation_execution_id,
            generation
        ),
        UNIQUE(
            project_id,
            candidate_asset_version_id,
            evaluation_execution_id,
            generation,
            operation_id
        ),
        UNIQUE(project_id, idempotency_scope, idempotency_key),
        UNIQUE(project_id, concurrency_key),
        FOREIGN KEY(project_id, book_id)
            REFERENCES authority_book(project_id, book_id),
        FOREIGN KEY(
            project_id,
            candidate_asset_version_id,
            predecessor_execution_id,
            predecessor_generation,
            predecessor_operation_id
        ) REFERENCES authority_narrative_evaluation_execution(
            project_id,
            candidate_asset_version_id,
            evaluation_execution_id,
            generation,
            operation_id
        ) DEFERRABLE INITIALLY DEFERRED,
        CHECK (generation > 0),
        CHECK (
            (generation=1
             AND predecessor_execution_id IS NULL
             AND predecessor_generation IS NULL
             AND predecessor_operation_id IS NULL
             AND recovery_intent_id IS NULL)
            OR
            (generation>1
             AND predecessor_execution_id IS NOT NULL
             AND predecessor_generation=generation-1
             AND predecessor_operation_id IS NOT NULL
             AND recovery_intent_id IS NOT NULL)
        ),
        CHECK (candidate_content_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (lifecycle IN (
            'ADMITTED','RUNNING','SUCCEEDED','FAILED','CANCELLED',
            'DEAD_LETTER','RECONCILIATION_REQUIRED'
        )),
        CHECK (jsonb_typeof(terminal_reason)='object'),
        CHECK (
            (lifecycle IN (
                'SUCCEEDED','FAILED','CANCELLED','DEAD_LETTER'
             ) AND terminal_at IS NOT NULL)
            OR
            (lifecycle NOT IN (
                'SUCCEEDED','FAILED','CANCELLED','DEAD_LETTER'
             ) AND terminal_at IS NULL)
        )
    )
    """,
    """
    CREATE INDEX authority_narrative_evaluation_project_fk_idx
    ON authority_narrative_evaluation_execution(project_id)
    """,
    """
    CREATE INDEX authority_narrative_evaluation_book_fk_idx
    ON authority_narrative_evaluation_execution(project_id, book_id)
    """,
    """
    CREATE INDEX authority_narrative_evaluation_candidate_fk_idx
    ON authority_narrative_evaluation_execution(candidate_asset_version_id)
    """,
    """
    CREATE INDEX authority_narrative_evaluation_predecessor_fk_idx
    ON authority_narrative_evaluation_execution(
        project_id, candidate_asset_version_id,
        predecessor_execution_id, predecessor_generation,
        predecessor_operation_id
    ) WHERE predecessor_execution_id IS NOT NULL
    """,
    """
    CREATE INDEX authority_narrative_evaluation_predecessor_operation_fk_idx
    ON authority_narrative_evaluation_execution(predecessor_operation_id)
    WHERE predecessor_operation_id IS NOT NULL
    """,
    """
    CREATE INDEX authority_narrative_evaluation_intent_fk_idx
    ON authority_narrative_evaluation_execution(recovery_intent_id)
    WHERE recovery_intent_id IS NOT NULL
    """,
    """
    CREATE INDEX authority_narrative_evaluation_operation_fk_idx
    ON authority_narrative_evaluation_execution(operation_id)
    """,
    """
    CREATE TABLE authority_narrative_evaluation_execution_head (
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        candidate_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        current_execution_id TEXT NOT NULL,
        current_generation BIGINT NOT NULL,
        version BIGINT NOT NULL DEFAULT 0,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY(project_id, candidate_asset_version_id),
        FOREIGN KEY(
            project_id,
            candidate_asset_version_id,
            current_execution_id,
            current_generation
        ) REFERENCES authority_narrative_evaluation_execution(
            project_id,
            candidate_asset_version_id,
            evaluation_execution_id,
            generation
        ) DEFERRABLE INITIALLY DEFERRED,
        CHECK (current_generation > 0),
        CHECK (version >= 0)
    )
    """,
    """
    CREATE INDEX authority_narrative_evaluation_head_candidate_fk_idx
    ON authority_narrative_evaluation_execution_head(candidate_asset_version_id)
    """,
    """
    CREATE INDEX authority_narrative_evaluation_head_execution_fk_idx
    ON authority_narrative_evaluation_execution_head(
        project_id, candidate_asset_version_id,
        current_execution_id, current_generation
    )
    """,
    """
    INSERT INTO authority_narrative_evaluation_execution(
        evaluation_execution_id,
        project_id,
        book_id,
        candidate_asset_version_id,
        candidate_content_hash,
        generation,
        operation_id,
        idempotency_scope,
        idempotency_key,
        concurrency_key,
        lifecycle,
        terminal_reason,
        version,
        created_at,
        started_at,
        terminal_at,
        updated_at
    )
    SELECT
        'narrative-evaluation-execution:legacy:' || operation.operation_id,
        operation.project_id,
        operation.command_payload->'payload'->>'book_id',
        operation.command_payload->'payload'->>'candidate_asset_version_id',
        operation.command_payload->'payload'->>'candidate_content_hash',
        1,
        operation.operation_id,
        operation.idempotency_scope,
        operation.idempotency_key,
        operation.concurrency_key,
        CASE
            WHEN operation.status='SUCCEEDED' THEN 'SUCCEEDED'
            WHEN operation.status='CANCELLED' THEN 'CANCELLED'
            WHEN operation.status='DEAD_LETTER' THEN 'DEAD_LETTER'
            WHEN operation.status IN (
                'FAILED_FINAL','COMPENSATED','COMPENSATION_FAILED'
            ) THEN 'FAILED'
            WHEN operation.status='RECONCILIATION_REQUIRED'
                THEN 'RECONCILIATION_REQUIRED'
            WHEN operation.status IN (
                'EXECUTING','WAITING_CHILDREN','WAITING_EXTERNAL_RESULT',
                'WAITING_GATE','FAILED_RETRYABLE','CANCELLATION_REQUESTED',
                'COMPENSATION_REQUIRED','COMPENSATING'
            ) THEN 'RUNNING'
            ELSE 'ADMITTED'
        END,
        CASE
            WHEN operation.status IN (
                'SUCCEEDED','CANCELLED','DEAD_LETTER','FAILED_FINAL',
                'COMPENSATED','COMPENSATION_FAILED'
            ) THEN jsonb_build_object(
                'bootstrap','legacy_operation_terminal',
                'operation_status',operation.status
            )
            ELSE '{}'::jsonb
        END,
        0,
        operation.created_at,
        CASE
            WHEN operation.status IN (
                'EXECUTING','WAITING_CHILDREN','WAITING_EXTERNAL_RESULT',
                'WAITING_GATE','FAILED_RETRYABLE','CANCELLATION_REQUESTED',
                'COMPENSATION_REQUIRED','COMPENSATING','SUCCEEDED','CANCELLED',
                'DEAD_LETTER','FAILED_FINAL','COMPENSATED',
                'COMPENSATION_FAILED','RECONCILIATION_REQUIRED'
            ) THEN operation.updated_at
            ELSE NULL
        END,
        CASE
            WHEN operation.status IN (
                'SUCCEEDED','CANCELLED','DEAD_LETTER','FAILED_FINAL',
                'COMPENSATED','COMPENSATION_FAILED'
            ) THEN operation.updated_at
            ELSE NULL
        END,
        operation.updated_at
    FROM authority_operation AS operation
    WHERE operation.definition_name='story_design.semantic_evaluate'
    ORDER BY operation.project_id, operation.operation_id
    """,
    """
    INSERT INTO authority_narrative_evaluation_execution_head(
        project_id,
        candidate_asset_version_id,
        current_execution_id,
        current_generation,
        version,
        updated_at
    )
    SELECT
        project_id,
        candidate_asset_version_id,
        evaluation_execution_id,
        generation,
        0,
        updated_at
    FROM authority_narrative_evaluation_execution
    WHERE generation=1
    ORDER BY project_id, candidate_asset_version_id
    """,
    """
    CREATE OR REPLACE FUNCTION authority_book_opening_execution_guard()
    RETURNS TRIGGER LANGUAGE plpgsql AS $$
    DECLARE
        opening_project_id TEXT;
        runtime_project_id TEXT;
        runtime_job_kind TEXT;
        runtime_group_name TEXT;
        runtime_subject_kind TEXT;
        runtime_subject_id TEXT;
        runtime_lease_loss_policy TEXT;
    BEGIN
        IF TG_OP='DELETE' THEN
            RAISE EXCEPTION 'BOOK_OPENING_EXECUTION_HISTORY_IMMUTABLE'
                USING ERRCODE='check_violation';
        END IF;
        IF TG_OP='UPDATE' AND ROW(
            OLD.opening_execution_id,
            OLD.opening_run_id,
            OLD.generation,
            OLD.predecessor_execution_id,
            OLD.predecessor_generation,
            OLD.runtime_job_id,
            OLD.frozen_request_digest,
            OLD.input_snapshot_hash,
            OLD.policy_snapshot_hash,
            OLD.authority_contract_hash,
            OLD.created_at
        ) IS DISTINCT FROM ROW(
            NEW.opening_execution_id,
            NEW.opening_run_id,
            NEW.generation,
            NEW.predecessor_execution_id,
            NEW.predecessor_generation,
            NEW.runtime_job_id,
            NEW.frozen_request_digest,
            NEW.input_snapshot_hash,
            NEW.policy_snapshot_hash,
            NEW.authority_contract_hash,
            NEW.created_at
        ) THEN
            RAISE EXCEPTION 'BOOK_OPENING_EXECUTION_IDENTITY_IMMUTABLE'
                USING ERRCODE='check_violation';
        END IF;
        IF TG_OP='UPDATE'
           AND OLD.lifecycle IN ('SUCCEEDED','FAILED','LOST','ABORTED')
           AND ROW(OLD.*) IS DISTINCT FROM ROW(NEW.*) THEN
            RAISE EXCEPTION 'BOOK_OPENING_EXECUTION_TERMINAL_IMMUTABLE'
                USING ERRCODE='check_violation';
        END IF;

        SELECT project_id INTO opening_project_id
        FROM authority_book_opening_run
        WHERE opening_run_id=NEW.opening_run_id;
        IF NEW.runtime_job_id IS NULL THEN
            IF opening_project_id IS NULL
               OR NEW.generation IS DISTINCT FROM 1
               OR NEW.lifecycle NOT IN ('FAILED','ABORTED')
               OR NEW.current_attempt_id IS NOT NULL
               OR NEW.current_lease_id IS NOT NULL
               OR NEW.current_worker_id IS NOT NULL
               OR NEW.current_fencing_token IS NOT NULL THEN
                RAISE EXCEPTION 'BOOK_OPENING_RUNTIME_BINDING_INVALID'
                    USING ERRCODE='check_violation';
            END IF;
            RETURN NEW;
        END IF;
        SELECT project_id,job_kind,runtime_group,subject_kind,subject_id,
               lease_loss_policy
        INTO runtime_project_id,runtime_job_kind,runtime_group_name,
             runtime_subject_kind,runtime_subject_id,runtime_lease_loss_policy
        FROM authority_runtime_job
        WHERE runtime_job_id=NEW.runtime_job_id;
        IF opening_project_id IS NULL
           OR runtime_project_id IS DISTINCT FROM opening_project_id
           OR runtime_job_kind IS DISTINCT FROM 'BOOK_OPENING_EXECUTE'
           OR runtime_group_name IS DISTINCT FROM 'book_opening'
           OR runtime_subject_kind IS DISTINCT FROM 'BOOK_OPENING_RUN'
           OR runtime_subject_id IS DISTINCT FROM NEW.opening_run_id
           OR runtime_lease_loss_policy IS DISTINCT FROM
              'AUTHORITY_CONVERGENCE_REQUIRED' THEN
            RAISE EXCEPTION 'BOOK_OPENING_RUNTIME_BINDING_INVALID'
                USING ERRCODE='check_violation';
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE TRIGGER authority_book_opening_execution_guard
    BEFORE INSERT OR UPDATE OR DELETE
    ON authority_book_opening_execution
    FOR EACH ROW EXECUTE FUNCTION authority_book_opening_execution_guard()
    """,
    """
    CREATE OR REPLACE FUNCTION authority_assert_runtime_job_current_claim(
        target_runtime_job_id TEXT
    ) RETURNS VOID LANGUAGE plpgsql AS $$
    DECLARE
        claim RECORD;
    BEGIN
        SELECT
            job.status AS job_status,
            job.claimed_by AS job_claimed_by,
            job.current_attempt_id AS job_attempt_id,
            job.current_fencing_token AS job_fencing_token,
            job.attempt_count AS job_attempt_count,
            attempt.attempt_id AS exact_attempt_id,
            attempt.attempt_number AS attempt_number,
            attempt.status AS attempt_status,
            attempt.worker_id AS attempt_worker_id,
            attempt.lease_id AS attempt_lease_id,
            attempt.fencing_token AS attempt_fencing_token,
            lease.lease_id AS exact_lease_id,
            lease.status AS lease_status,
            lease.worker_id AS lease_worker_id,
            lease.fencing_token AS lease_fencing_token
        INTO claim
        FROM authority_runtime_job AS job
        LEFT JOIN authority_runtime_job_attempt AS attempt
          ON attempt.runtime_job_id=job.runtime_job_id
         AND attempt.attempt_id=job.current_attempt_id
         AND attempt.fencing_token=job.current_fencing_token
        LEFT JOIN authority_runtime_job_lease AS lease
          ON lease.runtime_job_id=attempt.runtime_job_id
         AND lease.attempt_id=attempt.attempt_id
         AND lease.lease_id=attempt.lease_id
         AND lease.worker_id=attempt.worker_id
         AND lease.fencing_token=attempt.fencing_token
        WHERE job.runtime_job_id=target_runtime_job_id;
        IF NOT FOUND THEN
            RETURN;
        END IF;
        IF claim.job_status IN ('CLAIMED','RUNNING','CHECKPOINTED')
           AND (
               claim.job_attempt_id IS NULL
               OR claim.job_fencing_token <= 0
               OR NULLIF(claim.job_claimed_by,'') IS NULL
               OR claim.exact_attempt_id IS NULL
               OR claim.attempt_number IS DISTINCT FROM claim.job_attempt_count
               OR claim.attempt_status IS DISTINCT FROM claim.job_status
               OR claim.attempt_worker_id IS DISTINCT FROM claim.job_claimed_by
               OR claim.attempt_fencing_token IS DISTINCT FROM
                  claim.job_fencing_token
               OR claim.exact_lease_id IS NULL
               OR claim.lease_status IS DISTINCT FROM 'HELD'
               OR claim.lease_worker_id IS DISTINCT FROM claim.job_claimed_by
               OR claim.lease_fencing_token IS DISTINCT FROM
                  claim.job_fencing_token
           ) THEN
            RAISE EXCEPTION
                'RUNTIME_JOB_CURRENT_CLAIM_IDENTITY_INVALID:%',
                target_runtime_job_id
                USING ERRCODE='check_violation';
        END IF;
    END;
    $$
    """,
    """
    CREATE OR REPLACE FUNCTION authority_runtime_job_current_claim_guard()
    RETURNS TRIGGER LANGUAGE plpgsql AS $$
    DECLARE
        target_runtime_job_id TEXT;
    BEGIN
        IF TG_OP='DELETE' THEN
            target_runtime_job_id=OLD.runtime_job_id;
        ELSE
            target_runtime_job_id=NEW.runtime_job_id;
        END IF;
        PERFORM authority_assert_runtime_job_current_claim(
            target_runtime_job_id
        );
        RETURN NULL;
    END;
    $$
    """,
    *[
        f"""
        CREATE CONSTRAINT TRIGGER {table}_current_claim_guard
        AFTER INSERT OR UPDATE OR DELETE ON {table}
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION authority_runtime_job_current_claim_guard()
        """
        for table in (
            "authority_runtime_job",
            "authority_runtime_job_attempt",
            "authority_runtime_job_lease",
        )
    ],
    """
    CREATE OR REPLACE FUNCTION authority_assert_book_opening_execution_binding(
        target_opening_execution_id TEXT
    ) RETURNS VOID LANGUAGE plpgsql AS $$
    DECLARE
        binding RECORD;
        exact_claim BOOLEAN;
    BEGIN
        SELECT
            execution.opening_execution_id,
            execution.opening_run_id,
            execution.generation AS execution_generation,
            execution.lifecycle AS execution_lifecycle,
            execution.recovery_intent_id,
            execution.frozen_request_digest AS execution_request_digest,
            execution.input_snapshot_hash,
            execution.runtime_job_id,
            execution.current_attempt_id AS execution_attempt_id,
            execution.current_lease_id AS execution_lease_id,
            execution.current_worker_id AS execution_worker_id,
            execution.current_fencing_token AS execution_fencing_token,
            opening.project_id AS opening_project_id,
            opening.frozen_request_digest AS opening_request_digest,
            opening.current_execution_id AS opening_current_execution_id,
            opening.current_execution_generation AS opening_current_generation,
            EXISTS (
                SELECT 1
                FROM authority_book_opening_recovery_receipt AS receipt
                WHERE receipt.receipt_kind='RECOVERY_ADMISSION'
                  AND receipt.opening_run_id=execution.opening_run_id
                  AND receipt.recovery_intent_id=execution.recovery_intent_id
                  AND receipt.successor_execution_id=
                      execution.opening_execution_id
                  AND receipt.successor_generation=execution.generation
            ) AS exact_recovery_admission,
            job.project_id AS job_project_id,
            job.job_kind,
            job.runtime_group,
            job.subject_kind,
            job.subject_id,
            job.input_hash AS job_input_hash,
            job.lease_loss_policy,
            job.status AS job_status,
            job.claimed_by AS job_claimed_by,
            job.current_attempt_id AS job_attempt_id,
            job.current_fencing_token AS job_fencing_token,
            attempt.attempt_id AS exact_attempt_id,
            attempt.status AS attempt_status,
            lease.lease_id AS exact_lease_id,
            lease.status AS lease_status
        INTO binding
        FROM authority_book_opening_execution AS execution
        JOIN authority_book_opening_run AS opening
          ON opening.opening_run_id=execution.opening_run_id
        LEFT JOIN authority_runtime_job AS job
          ON job.runtime_job_id=execution.runtime_job_id
        LEFT JOIN authority_runtime_job_attempt AS attempt
          ON attempt.runtime_job_id=execution.runtime_job_id
         AND attempt.attempt_id=execution.current_attempt_id
         AND attempt.lease_id=execution.current_lease_id
         AND attempt.worker_id=execution.current_worker_id
         AND attempt.fencing_token=execution.current_fencing_token
        LEFT JOIN authority_runtime_job_lease AS lease
          ON lease.runtime_job_id=execution.runtime_job_id
         AND lease.attempt_id=execution.current_attempt_id
         AND lease.lease_id=execution.current_lease_id
         AND lease.worker_id=execution.current_worker_id
         AND lease.fencing_token=execution.current_fencing_token
        WHERE execution.opening_execution_id=target_opening_execution_id;
        IF NOT FOUND THEN
            RETURN;
        END IF;
        IF binding.execution_request_digest IS DISTINCT FROM
           binding.opening_request_digest THEN
            RAISE EXCEPTION 'BOOK_OPENING_RELATIONAL_CLOSURE_INVALID:%',
                target_opening_execution_id
                USING ERRCODE='check_violation';
        END IF;
        IF binding.execution_generation>1
           AND (
               binding.recovery_intent_id IS NULL
               OR NOT binding.exact_recovery_admission
           ) THEN
            RAISE EXCEPTION 'BOOK_OPENING_RELATIONAL_CLOSURE_INVALID:%',
                target_opening_execution_id
                USING ERRCODE='check_violation';
        END IF;
        IF binding.execution_lifecycle IN ('SCHEDULED','BOUND','RUNNING')
           AND (
               binding.opening_current_execution_id IS DISTINCT FROM
                  binding.opening_execution_id
               OR binding.opening_current_generation IS DISTINCT FROM
                  binding.execution_generation
           ) THEN
            RAISE EXCEPTION 'BOOK_OPENING_RELATIONAL_CLOSURE_INVALID:%',
                target_opening_execution_id
                USING ERRCODE='check_violation';
        END IF;
        IF binding.runtime_job_id IS NULL THEN
            IF binding.execution_generation IS DISTINCT FROM 1
               OR binding.execution_lifecycle NOT IN ('FAILED','ABORTED')
               OR binding.execution_attempt_id IS NOT NULL
               OR binding.execution_lease_id IS NOT NULL
               OR binding.execution_worker_id IS NOT NULL
               OR binding.execution_fencing_token IS NOT NULL THEN
                RAISE EXCEPTION 'BOOK_OPENING_RELATIONAL_CLOSURE_INVALID:%',
                    target_opening_execution_id
                    USING ERRCODE='check_violation';
            END IF;
            RETURN;
        END IF;
        IF binding.job_project_id IS DISTINCT FROM binding.opening_project_id
           OR binding.job_kind IS DISTINCT FROM 'BOOK_OPENING_EXECUTE'
           OR binding.runtime_group IS DISTINCT FROM 'book_opening'
           OR binding.subject_kind IS DISTINCT FROM 'BOOK_OPENING_RUN'
           OR binding.subject_id IS DISTINCT FROM binding.opening_run_id
           OR binding.job_input_hash IS DISTINCT FROM binding.input_snapshot_hash
           OR binding.lease_loss_policy IS DISTINCT FROM
              'AUTHORITY_CONVERGENCE_REQUIRED' THEN
            RAISE EXCEPTION 'BOOK_OPENING_RELATIONAL_CLOSURE_INVALID:%',
                target_opening_execution_id
                USING ERRCODE='check_violation';
        END IF;

        PERFORM authority_assert_runtime_job_current_claim(
            binding.runtime_job_id
        );
        exact_claim = (
            binding.execution_attempt_id IS NOT NULL
            AND binding.exact_attempt_id IS NOT NULL
            AND binding.exact_lease_id IS NOT NULL
            AND binding.job_attempt_id IS NOT DISTINCT FROM
                binding.execution_attempt_id
            AND binding.job_fencing_token IS NOT DISTINCT FROM
                binding.execution_fencing_token
        );

        IF binding.execution_lifecycle='SCHEDULED' THEN
            IF binding.execution_attempt_id IS NOT NULL
               OR binding.job_status IS DISTINCT FROM 'READY'
               OR binding.job_attempt_id IS NOT NULL
               OR binding.job_fencing_token<>0
               OR binding.job_claimed_by<>'' THEN
                RAISE EXCEPTION 'BOOK_OPENING_RELATIONAL_CLOSURE_INVALID:%',
                    target_opening_execution_id
                    USING ERRCODE='check_violation';
            END IF;
        ELSIF binding.execution_lifecycle IN ('BOUND','RUNNING') THEN
            IF NOT exact_claim
               OR binding.job_status NOT IN ('CLAIMED','RUNNING','CHECKPOINTED')
               OR binding.job_claimed_by IS DISTINCT FROM
                  binding.execution_worker_id
               OR binding.attempt_status IS DISTINCT FROM binding.job_status
               OR binding.lease_status IS DISTINCT FROM 'HELD' THEN
                RAISE EXCEPTION 'BOOK_OPENING_RELATIONAL_CLOSURE_INVALID:%',
                    target_opening_execution_id
                    USING ERRCODE='check_violation';
            END IF;
        ELSIF binding.execution_lifecycle='SUCCEEDED' THEN
            IF NOT exact_claim
               OR binding.job_status IS DISTINCT FROM 'SUCCEEDED'
               OR binding.job_claimed_by<>''
               OR binding.attempt_status IS DISTINCT FROM 'SUCCEEDED'
               OR binding.lease_status IS DISTINCT FROM 'RELEASED' THEN
                RAISE EXCEPTION 'BOOK_OPENING_RELATIONAL_CLOSURE_INVALID:%',
                    target_opening_execution_id
                    USING ERRCODE='check_violation';
            END IF;
        ELSIF binding.execution_lifecycle='FAILED' THEN
            IF NOT exact_claim
               OR binding.job_status NOT IN ('FAILED','DEAD_LETTER')
               OR binding.job_claimed_by<>''
               OR binding.attempt_status IS DISTINCT FROM 'FAILED'
               OR binding.lease_status IS DISTINCT FROM 'RELEASED' THEN
                RAISE EXCEPTION 'BOOK_OPENING_RELATIONAL_CLOSURE_INVALID:%',
                    target_opening_execution_id
                    USING ERRCODE='check_violation';
            END IF;
        ELSIF binding.execution_lifecycle='LOST' THEN
            IF NOT exact_claim
               OR binding.job_status IS DISTINCT FROM 'FAILED'
               OR binding.job_claimed_by<>''
               OR binding.attempt_status IS DISTINCT FROM 'ABANDONED'
               OR binding.lease_status IS DISTINCT FROM 'EXPIRED' THEN
                RAISE EXCEPTION 'BOOK_OPENING_RELATIONAL_CLOSURE_INVALID:%',
                    target_opening_execution_id
                    USING ERRCODE='check_violation';
            END IF;
        ELSIF binding.execution_lifecycle='ABORTED' THEN
            IF binding.job_status IS DISTINCT FROM 'CANCELLED'
               OR binding.job_claimed_by<>''
               OR (
                   binding.execution_attempt_id IS NULL
                   AND (
                       binding.job_attempt_id IS NOT NULL
                       OR binding.job_fencing_token<>0
                   )
               )
               OR (
                   binding.execution_attempt_id IS NOT NULL
                   AND (
                       NOT exact_claim
                       OR binding.attempt_status IS DISTINCT FROM 'ABANDONED'
                       OR binding.lease_status IS DISTINCT FROM 'RELEASED'
                   )
               ) THEN
                RAISE EXCEPTION 'BOOK_OPENING_RELATIONAL_CLOSURE_INVALID:%',
                    target_opening_execution_id
                    USING ERRCODE='check_violation';
            END IF;
        END IF;
    END;
    $$
    """,
    """
    CREATE OR REPLACE FUNCTION authority_assert_book_opening_current_execution(
        target_opening_run_id TEXT
    ) RETURNS VOID LANGUAGE plpgsql AS $$
    DECLARE
        opening RECORD;
    BEGIN
        SELECT
            run.execution_contract_version,
            run.lifecycle AS opening_lifecycle,
            run.recovery_state,
            run.current_execution_id,
            run.current_execution_generation,
            execution.lifecycle AS execution_lifecycle
        INTO opening
        FROM authority_book_opening_run AS run
        LEFT JOIN authority_book_opening_execution AS execution
          ON execution.opening_run_id=run.opening_run_id
         AND execution.opening_execution_id=run.current_execution_id
         AND execution.generation=run.current_execution_generation
        WHERE run.opening_run_id=target_opening_run_id;
        IF NOT FOUND
           OR opening.execution_contract_version IS DISTINCT FROM
              'book-opening-execution-v2' THEN
            RETURN;
        END IF;
        IF opening.current_execution_id IS NULL
           OR opening.execution_lifecycle IS NULL
           OR opening.recovery_state='LEGACY_RECONCILIATION_REQUIRED'
           OR (
               opening.opening_lifecycle='ADMITTED'
               AND opening.execution_lifecycle NOT IN ('SCHEDULED','BOUND')
           )
           OR (
               opening.opening_lifecycle='RUNNING'
               AND opening.execution_lifecycle<>'RUNNING'
           )
           OR (
               opening.opening_lifecycle='COMPLETE'
               AND opening.execution_lifecycle<>'SUCCEEDED'
           )
           OR (
               opening.opening_lifecycle='FAILED'
               AND opening.execution_lifecycle NOT IN (
                   'FAILED','LOST','ABORTED'
               )
           )
           OR (
               opening.opening_lifecycle='ABORTED'
               AND opening.execution_lifecycle NOT IN (
                   'ABORTED','FAILED','LOST'
               )
           ) THEN
            RAISE EXCEPTION 'BOOK_OPENING_RELATIONAL_CLOSURE_INVALID:%',
                target_opening_run_id
                USING ERRCODE='check_violation';
        END IF;
        PERFORM authority_assert_book_opening_execution_binding(
            opening.current_execution_id
        );
    END;
    $$
    """,
    """
    CREATE OR REPLACE FUNCTION authority_book_opening_relational_closure_guard()
    RETURNS TRIGGER LANGUAGE plpgsql AS $$
    DECLARE
        target_opening_run_id TEXT;
        target_opening_execution_id TEXT;
        target_runtime_job_id TEXT;
        related RECORD;
    BEGIN
        IF TG_TABLE_NAME='authority_book_opening_run' THEN
            IF TG_OP='DELETE' THEN
                target_opening_run_id=OLD.opening_run_id;
            ELSE
                target_opening_run_id=NEW.opening_run_id;
            END IF;
        ELSIF TG_TABLE_NAME='authority_book_opening_execution' THEN
            IF TG_OP='DELETE' THEN
                target_opening_run_id=OLD.opening_run_id;
                target_opening_execution_id=OLD.opening_execution_id;
            ELSE
                target_opening_run_id=NEW.opening_run_id;
                target_opening_execution_id=NEW.opening_execution_id;
            END IF;
        ELSE
            IF TG_OP='DELETE' THEN
                target_runtime_job_id=OLD.runtime_job_id;
            ELSE
                target_runtime_job_id=NEW.runtime_job_id;
            END IF;
        END IF;

        IF target_opening_execution_id IS NOT NULL THEN
            PERFORM authority_assert_book_opening_execution_binding(
                target_opening_execution_id
            );
        END IF;
        IF target_opening_run_id IS NOT NULL THEN
            PERFORM authority_assert_book_opening_current_execution(
                target_opening_run_id
            );
        END IF;
        IF target_runtime_job_id IS NOT NULL THEN
            FOR related IN
                SELECT opening_execution_id,opening_run_id
                FROM authority_book_opening_execution
                WHERE runtime_job_id=target_runtime_job_id
            LOOP
                PERFORM authority_assert_book_opening_execution_binding(
                    related.opening_execution_id
                );
                PERFORM authority_assert_book_opening_current_execution(
                    related.opening_run_id
                );
            END LOOP;
        END IF;
        RETURN NULL;
    END;
    $$
    """,
    *[
        f"""
        CREATE CONSTRAINT TRIGGER {table}_relational_closure_guard
        AFTER INSERT OR UPDATE OR DELETE ON {table}
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION authority_book_opening_relational_closure_guard()
        """
        for table in (
            "authority_book_opening_run",
            "authority_book_opening_execution",
            "authority_runtime_job",
            "authority_runtime_job_attempt",
            "authority_runtime_job_lease",
        )
    ],
    """
    CREATE OR REPLACE FUNCTION authority_book_opening_head_monotonic_guard()
    RETURNS TRIGGER LANGUAGE plpgsql AS $$
    DECLARE
        successor RECORD;
        checkpoint RECORD;
    BEGIN
        IF ROW(OLD.current_execution_id,OLD.current_execution_generation)
           IS DISTINCT FROM
           ROW(NEW.current_execution_id,NEW.current_execution_generation) THEN
            IF OLD.current_execution_id IS NULL THEN
                IF NEW.current_execution_id IS NULL
                   OR NEW.current_execution_generation IS DISTINCT FROM 1 THEN
                    RAISE EXCEPTION 'BOOK_OPENING_EXECUTION_HEAD_NON_MONOTONIC:%',
                        OLD.opening_run_id USING ERRCODE='check_violation';
                END IF;
            ELSIF NEW.current_execution_generation IS DISTINCT FROM
                  OLD.current_execution_generation+1 THEN
                RAISE EXCEPTION 'BOOK_OPENING_EXECUTION_HEAD_NON_MONOTONIC:%',
                    OLD.opening_run_id USING ERRCODE='check_violation';
            ELSE
                SELECT predecessor_execution_id,predecessor_generation
                INTO successor
                FROM authority_book_opening_execution
                WHERE opening_run_id=NEW.opening_run_id
                  AND opening_execution_id=NEW.current_execution_id
                  AND generation=NEW.current_execution_generation;
                IF NOT FOUND
                   OR successor.predecessor_execution_id IS DISTINCT FROM
                      OLD.current_execution_id
                   OR successor.predecessor_generation IS DISTINCT FROM
                      OLD.current_execution_generation THEN
                    RAISE EXCEPTION 'BOOK_OPENING_EXECUTION_HEAD_NON_MONOTONIC:%',
                        OLD.opening_run_id USING ERRCODE='check_violation';
                END IF;
            END IF;
        END IF;

        IF ROW(OLD.current_checkpoint_id,OLD.current_checkpoint_sequence,
               OLD.current_checkpoint_hash) IS DISTINCT FROM
           ROW(NEW.current_checkpoint_id,NEW.current_checkpoint_sequence,
               NEW.current_checkpoint_hash) THEN
            IF OLD.current_checkpoint_sequence=0 THEN
                IF NEW.current_checkpoint_sequence IS DISTINCT FROM 1 THEN
                    RAISE EXCEPTION 'BOOK_OPENING_CHECKPOINT_HEAD_NON_MONOTONIC:%',
                        OLD.opening_run_id USING ERRCODE='check_violation';
                END IF;
            ELSIF NEW.current_checkpoint_sequence IS DISTINCT FROM
                  OLD.current_checkpoint_sequence+1 THEN
                RAISE EXCEPTION 'BOOK_OPENING_CHECKPOINT_HEAD_NON_MONOTONIC:%',
                    OLD.opening_run_id USING ERRCODE='check_violation';
            END IF;
            SELECT predecessor_checkpoint_id,predecessor_checkpoint_sequence,
                   predecessor_checkpoint_hash
            INTO checkpoint
            FROM authority_book_opening_semantic_checkpoint
            WHERE opening_run_id=NEW.opening_run_id
              AND checkpoint_id=NEW.current_checkpoint_id
              AND checkpoint_sequence=NEW.current_checkpoint_sequence
              AND checkpoint_hash=NEW.current_checkpoint_hash;
            IF NOT FOUND
               OR (
                   OLD.current_checkpoint_sequence=0
                   AND checkpoint.predecessor_checkpoint_id IS NOT NULL
               )
               OR (
                   OLD.current_checkpoint_sequence>0
                   AND (
                       checkpoint.predecessor_checkpoint_id IS DISTINCT FROM
                          OLD.current_checkpoint_id
                       OR checkpoint.predecessor_checkpoint_sequence IS DISTINCT FROM
                          OLD.current_checkpoint_sequence
                       OR checkpoint.predecessor_checkpoint_hash IS DISTINCT FROM
                          OLD.current_checkpoint_hash
                   )
               ) THEN
                RAISE EXCEPTION 'BOOK_OPENING_CHECKPOINT_HEAD_NON_MONOTONIC:%',
                    OLD.opening_run_id USING ERRCODE='check_violation';
            END IF;
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE TRIGGER authority_book_opening_run_head_monotonic
    BEFORE UPDATE OF current_execution_id,current_execution_generation,
                     current_checkpoint_id,current_checkpoint_sequence,
                     current_checkpoint_hash
    ON authority_book_opening_run
    FOR EACH ROW
    EXECUTE FUNCTION authority_book_opening_head_monotonic_guard()
    """,
    """
    CREATE OR REPLACE FUNCTION authority_assert_book_opening_checkpoint_binding(
        target_checkpoint_id TEXT
    ) RETURNS VOID LANGUAGE plpgsql AS $$
    DECLARE
        binding RECORD;
    BEGIN
        SELECT checkpoint.frozen_request_digest AS checkpoint_digest,
               execution.frozen_request_digest AS execution_digest,
               opening.frozen_request_digest AS opening_digest
        INTO binding
        FROM authority_book_opening_semantic_checkpoint AS checkpoint
        JOIN authority_book_opening_execution AS execution
          ON execution.opening_run_id=checkpoint.opening_run_id
         AND execution.opening_execution_id=checkpoint.opening_execution_id
         AND execution.generation=checkpoint.execution_generation
        JOIN authority_book_opening_run AS opening
          ON opening.opening_run_id=checkpoint.opening_run_id
        WHERE checkpoint.checkpoint_id=target_checkpoint_id;
        IF NOT FOUND THEN
            RETURN;
        END IF;
        IF binding.checkpoint_digest IS DISTINCT FROM binding.execution_digest
           OR binding.checkpoint_digest IS DISTINCT FROM binding.opening_digest THEN
            RAISE EXCEPTION 'BOOK_OPENING_CHECKPOINT_BINDING_INVALID:%',
                target_checkpoint_id USING ERRCODE='check_violation';
        END IF;
    END;
    $$
    """,
    """
    CREATE OR REPLACE FUNCTION authority_book_opening_checkpoint_binding_guard()
    RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        PERFORM authority_assert_book_opening_checkpoint_binding(
            CASE WHEN TG_OP='DELETE' THEN OLD.checkpoint_id ELSE NEW.checkpoint_id END
        );
        RETURN NULL;
    END;
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER authority_book_opening_checkpoint_binding_guard
    AFTER INSERT OR UPDATE OR DELETE
    ON authority_book_opening_semantic_checkpoint
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW
    EXECUTE FUNCTION authority_book_opening_checkpoint_binding_guard()
    """,
    """
    CREATE OR REPLACE FUNCTION authority_book_opening_frozen_input_guard()
    RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP='UPDATE' AND (
            OLD.frozen_request IS DISTINCT FROM NEW.frozen_request
            OR OLD.frozen_request_digest IS DISTINCT FROM
               NEW.frozen_request_digest
            OR OLD.project_id IS DISTINCT FROM NEW.project_id
            OR OLD.workspace_id IS DISTINCT FROM NEW.workspace_id
            OR OLD.book_id IS DISTINCT FROM NEW.book_id
            OR OLD.root_operation_id IS DISTINCT FROM NEW.root_operation_id
            OR OLD.stable_idempotency_key IS DISTINCT FROM
               NEW.stable_idempotency_key
            OR (
                OLD.execution_contract_version IS DISTINCT FROM
                    NEW.execution_contract_version
                AND NOT (
                    OLD.execution_contract_version='legacy-unbound'
                    AND NEW.execution_contract_version=
                        'book-opening-execution-v2'
                )
            )
        ) THEN
            RAISE EXCEPTION 'BOOK_OPENING_FROZEN_INPUT_IMMUTABLE:%',
                OLD.opening_run_id
                USING ERRCODE='check_violation';
        END IF;
        IF NEW.project_id IS DISTINCT FROM NEW.frozen_request->>'project_id'
           OR NEW.workspace_id IS DISTINCT FROM
              NEW.frozen_request->>'workspace_id'
           OR NEW.book_id IS DISTINCT FROM NEW.frozen_request->>'book_id'
           OR NEW.stable_idempotency_key IS DISTINCT FROM
              NEW.frozen_request->>'idempotency_key' THEN
            RAISE EXCEPTION 'BOOK_OPENING_FROZEN_SCOPE_INVALID:%',
                NEW.opening_run_id
                USING ERRCODE='check_violation';
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE TRIGGER authority_book_opening_run_frozen_input_immutable
    BEFORE UPDATE OF frozen_request,frozen_request_digest,project_id,
                     workspace_id,book_id,root_operation_id,
                     stable_idempotency_key,execution_contract_version
    ON authority_book_opening_run
    FOR EACH ROW
    EXECUTE FUNCTION authority_book_opening_frozen_input_guard()
    """,
    """
    CREATE TRIGGER authority_book_opening_run_frozen_scope_valid
    BEFORE INSERT ON authority_book_opening_run
    FOR EACH ROW
    EXECUTE FUNCTION authority_book_opening_frozen_input_guard()
    """,
    """
    CREATE OR REPLACE FUNCTION authority_book_opening_immutable_fact_guard()
    RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'BOOK_OPENING_RECOVERY_FACT_IMMUTABLE:%', TG_TABLE_NAME
            USING ERRCODE='check_violation';
    END;
    $$
    """,
    *[
        f"""
        CREATE TRIGGER {table}_immutable
        BEFORE UPDATE OR DELETE ON {table}
        FOR EACH ROW
        EXECUTE FUNCTION authority_book_opening_immutable_fact_guard()
        """
        for table in (
            "authority_book_opening_semantic_checkpoint",
            "authority_book_opening_recovery_assessment",
            "authority_book_opening_recovery_intent",
            "authority_book_opening_recovery_receipt",
        )
    ],
    """
    CREATE OR REPLACE FUNCTION authority_narrative_evaluation_execution_guard()
    RETURNS TRIGGER LANGUAGE plpgsql AS $$
    DECLARE
        operation_project_id TEXT;
        operation_idempotency_scope TEXT;
        operation_idempotency_key TEXT;
        operation_concurrency_key TEXT;
        candidate_project_id TEXT;
        authoritative_candidate_hash TEXT;
        intent_scope RECORD;
    BEGIN
        IF TG_OP='DELETE' THEN
            RAISE EXCEPTION 'NARRATIVE_EVALUATION_EXECUTION_HISTORY_IMMUTABLE'
                USING ERRCODE='check_violation';
        END IF;
        IF TG_OP='UPDATE' AND ROW(
            OLD.evaluation_execution_id,
            OLD.project_id,
            OLD.book_id,
            OLD.candidate_asset_version_id,
            OLD.candidate_content_hash,
            OLD.generation,
            OLD.predecessor_execution_id,
            OLD.predecessor_generation,
            OLD.predecessor_operation_id,
            OLD.recovery_intent_id,
            OLD.operation_id,
            OLD.idempotency_scope,
            OLD.idempotency_key,
            OLD.concurrency_key,
            OLD.created_at
        ) IS DISTINCT FROM ROW(
            NEW.evaluation_execution_id,
            NEW.project_id,
            NEW.book_id,
            NEW.candidate_asset_version_id,
            NEW.candidate_content_hash,
            NEW.generation,
            NEW.predecessor_execution_id,
            NEW.predecessor_generation,
            NEW.predecessor_operation_id,
            NEW.recovery_intent_id,
            NEW.operation_id,
            NEW.idempotency_scope,
            NEW.idempotency_key,
            NEW.concurrency_key,
            NEW.created_at
        ) THEN
            RAISE EXCEPTION 'NARRATIVE_EVALUATION_EXECUTION_IDENTITY_IMMUTABLE'
                USING ERRCODE='check_violation';
        END IF;
        IF TG_OP='UPDATE'
           AND OLD.lifecycle IN (
               'SUCCEEDED','FAILED','CANCELLED','DEAD_LETTER'
           )
           AND ROW(OLD.*) IS DISTINCT FROM ROW(NEW.*) THEN
            RAISE EXCEPTION 'NARRATIVE_EVALUATION_EXECUTION_TERMINAL_IMMUTABLE'
                USING ERRCODE='check_violation';
        END IF;

        SELECT project_id,idempotency_scope,idempotency_key,concurrency_key
        INTO operation_project_id,operation_idempotency_scope,
             operation_idempotency_key,operation_concurrency_key
        FROM authority_operation
        WHERE operation_id=NEW.operation_id
          AND definition_name='story_design.semantic_evaluate';
        SELECT asset.project_id,version.content_hash
        INTO candidate_project_id,authoritative_candidate_hash
        FROM authority_asset_version AS version
        JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
        WHERE version.asset_version_id=NEW.candidate_asset_version_id;
        IF operation_project_id IS DISTINCT FROM NEW.project_id
           OR operation_idempotency_scope IS DISTINCT FROM NEW.idempotency_scope
           OR operation_idempotency_key IS DISTINCT FROM NEW.idempotency_key
           OR operation_concurrency_key IS DISTINCT FROM NEW.concurrency_key
           OR candidate_project_id IS DISTINCT FROM NEW.project_id
           OR authoritative_candidate_hash IS DISTINCT FROM
              NEW.candidate_content_hash THEN
            RAISE EXCEPTION 'NARRATIVE_EVALUATION_EXECUTION_BINDING_INVALID'
                USING ERRCODE='check_violation';
        END IF;
        IF NEW.generation>1 THEN
            SELECT opening.project_id,opening.book_id,
                   assessment.assessment_kind,
                   assessment.snapshot->'semantic_evaluation'
                       AS semantic_evaluation
            INTO intent_scope
            FROM authority_book_opening_recovery_intent AS intent
            JOIN authority_book_opening_recovery_assessment AS assessment
              ON assessment.recovery_assessment_id=
                 intent.recovery_assessment_id
             AND assessment.opening_run_id=intent.opening_run_id
            JOIN authority_book_opening_run AS opening
              ON opening.opening_run_id=intent.opening_run_id
            WHERE intent.recovery_intent_id=NEW.recovery_intent_id;
            IF NOT FOUND
               OR intent_scope.project_id IS DISTINCT FROM NEW.project_id
               OR intent_scope.book_id IS DISTINCT FROM NEW.book_id
               OR intent_scope.assessment_kind IS DISTINCT FROM 'RECOVERY'
               OR intent_scope.semantic_evaluation->>'evaluation_execution_id'
                  IS DISTINCT FROM NEW.predecessor_execution_id
               OR intent_scope.semantic_evaluation->>'generation'
                  IS DISTINCT FROM NEW.predecessor_generation::TEXT
               OR intent_scope.semantic_evaluation->>'operation_id'
                  IS DISTINCT FROM NEW.predecessor_operation_id
               OR intent_scope.semantic_evaluation->>'candidate_asset_version_id'
                  IS DISTINCT FROM NEW.candidate_asset_version_id THEN
                RAISE EXCEPTION
                    'NARRATIVE_EVALUATION_RECOVERY_INTENT_BINDING_INVALID:%',
                    NEW.evaluation_execution_id
                    USING ERRCODE='check_violation';
            END IF;
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE TRIGGER authority_narrative_evaluation_execution_guard
    BEFORE INSERT OR UPDATE OR DELETE
    ON authority_narrative_evaluation_execution
    FOR EACH ROW
    EXECUTE FUNCTION authority_narrative_evaluation_execution_guard()
    """,
    """
    CREATE OR REPLACE FUNCTION authority_narrative_evaluation_head_guard()
    RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP='DELETE' THEN
            RAISE EXCEPTION 'NARRATIVE_EVALUATION_HEAD_DELETE_FORBIDDEN'
                USING ERRCODE='check_violation';
        END IF;
        IF ROW(OLD.project_id,OLD.candidate_asset_version_id)
           IS DISTINCT FROM
           ROW(NEW.project_id,NEW.candidate_asset_version_id) THEN
            RAISE EXCEPTION 'NARRATIVE_EVALUATION_HEAD_IDENTITY_IMMUTABLE'
                USING ERRCODE='check_violation';
        END IF;
        IF NEW.current_generation <> OLD.current_generation+1
           OR NEW.version <> OLD.version+1 THEN
            RAISE EXCEPTION 'NARRATIVE_EVALUATION_HEAD_CAS_INVALID'
                USING ERRCODE='check_violation';
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE TRIGGER authority_narrative_evaluation_head_guard
    BEFORE UPDATE OR DELETE
    ON authority_narrative_evaluation_execution_head
    FOR EACH ROW
    EXECUTE FUNCTION authority_narrative_evaluation_head_guard()
    """,
    """
    CREATE OR REPLACE FUNCTION authority_terminal_execution_history_guard()
    RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP='DELETE' THEN
            IF TG_TABLE_NAME='authority_operation'
               AND OLD.status IN (
                   'FAILED_FINAL','COMPENSATED','COMPENSATION_FAILED',
                   'SUCCEEDED','CANCELLED','DEAD_LETTER'
               ) THEN
                RAISE EXCEPTION 'TERMINAL_OPERATION_IMMUTABLE'
                    USING ERRCODE='check_violation';
            ELSIF TG_TABLE_NAME='authority_attempt'
               AND OLD.status IN (
                   'SUCCEEDED','FAILED_RETRYABLE','FAILED_FINAL','TIMED_OUT',
                   'LEASE_LOST','SUPERSEDED','LATE_RESULT_REJECTED','CANCELLED'
               ) THEN
                RAISE EXCEPTION 'TERMINAL_ATTEMPT_IMMUTABLE'
                    USING ERRCODE='check_violation';
            ELSIF TG_TABLE_NAME='authority_lease_acquisition'
               AND OLD.status IN ('RELEASED','EXPIRED') THEN
                RAISE EXCEPTION 'TERMINAL_LEASE_IMMUTABLE'
                    USING ERRCODE='check_violation';
            ELSIF TG_TABLE_NAME='authority_runtime_job'
               AND OLD.status IN (
                   'SUCCEEDED','FAILED','DEAD_LETTER','CANCELLED'
               ) THEN
                RAISE EXCEPTION 'TERMINAL_RUNTIME_JOB_IMMUTABLE'
                    USING ERRCODE='check_violation';
            ELSIF TG_TABLE_NAME='authority_runtime_job_attempt'
               AND OLD.status IN ('SUCCEEDED','FAILED','ABANDONED') THEN
                RAISE EXCEPTION 'TERMINAL_RUNTIME_ATTEMPT_IMMUTABLE'
                    USING ERRCODE='check_violation';
            ELSIF TG_TABLE_NAME='authority_runtime_job_lease'
               AND OLD.status IN ('RELEASED','EXPIRED','REVOKED') THEN
                RAISE EXCEPTION 'TERMINAL_RUNTIME_LEASE_IMMUTABLE'
                    USING ERRCODE='check_violation';
            END IF;
            RETURN OLD;
        END IF;

        IF TG_TABLE_NAME='authority_operation'
           AND OLD.status IN (
               'FAILED_FINAL','COMPENSATED','COMPENSATION_FAILED',
               'SUCCEEDED','CANCELLED','DEAD_LETTER'
           )
           AND ROW(OLD.*) IS DISTINCT FROM ROW(NEW.*) THEN
            RAISE EXCEPTION 'TERMINAL_OPERATION_IMMUTABLE'
                USING ERRCODE='check_violation';
        ELSIF TG_TABLE_NAME='authority_attempt'
           AND OLD.status IN (
               'SUCCEEDED','FAILED_RETRYABLE','FAILED_FINAL','TIMED_OUT',
               'LEASE_LOST','SUPERSEDED','LATE_RESULT_REJECTED','CANCELLED'
           )
           AND ROW(OLD.*) IS DISTINCT FROM ROW(NEW.*) THEN
            RAISE EXCEPTION 'TERMINAL_ATTEMPT_IMMUTABLE'
                USING ERRCODE='check_violation';
        ELSIF TG_TABLE_NAME='authority_lease_acquisition'
           AND OLD.status IN ('RELEASED','EXPIRED')
           AND ROW(OLD.*) IS DISTINCT FROM ROW(NEW.*) THEN
            RAISE EXCEPTION 'TERMINAL_LEASE_IMMUTABLE'
                USING ERRCODE='check_violation';
        ELSIF TG_TABLE_NAME='authority_runtime_job'
           AND OLD.status IN ('SUCCEEDED','FAILED','DEAD_LETTER','CANCELLED')
           AND ROW(OLD.*) IS DISTINCT FROM ROW(NEW.*) THEN
            RAISE EXCEPTION 'TERMINAL_RUNTIME_JOB_IMMUTABLE'
                USING ERRCODE='check_violation';
        ELSIF TG_TABLE_NAME='authority_runtime_job_attempt'
           AND OLD.status IN ('SUCCEEDED','FAILED','ABANDONED')
           AND ROW(OLD.*) IS DISTINCT FROM ROW(NEW.*) THEN
            RAISE EXCEPTION 'TERMINAL_RUNTIME_ATTEMPT_IMMUTABLE'
                USING ERRCODE='check_violation';
        ELSIF TG_TABLE_NAME='authority_runtime_job_lease'
           AND OLD.status IN ('RELEASED','EXPIRED','REVOKED')
           AND ROW(OLD.*) IS DISTINCT FROM ROW(NEW.*) THEN
            RAISE EXCEPTION 'TERMINAL_RUNTIME_LEASE_IMMUTABLE'
                USING ERRCODE='check_violation';
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    *[
        f"""
        CREATE TRIGGER {table}_terminal_immutable
        BEFORE UPDATE OR DELETE ON {table}
        FOR EACH ROW
        EXECUTE FUNCTION authority_terminal_execution_history_guard()
        """
        for table in (
            "authority_operation",
            "authority_attempt",
            "authority_lease_acquisition",
            "authority_runtime_job",
            "authority_runtime_job_attempt",
            "authority_runtime_job_lease",
        )
    ],
]


DOWNGRADE_STATEMENTS: list[str] = []
