from __future__ import annotations


MIGRATION_ID = "20260804_0062_runtime_job_execution_plane"
DOWN_REVISION = "20260804_0061_structured_migration_references"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = (
    "Restore the pre-0062 backup for full rollback. For an in-place repair, "
    "drain Runtime Job workers, preserve terminal jobs and events, expire held "
    "leases, then rebuild attempts and projections from immutable events."
)


PREFLIGHT_STATEMENTS = [
    "SELECT 'runtime_job_name_collision', "
    "CASE WHEN to_regclass('authority_runtime_job') IS NULL THEN 0 ELSE 1 END",
]


UPGRADE_STATEMENTS = [
    """
    CREATE TABLE authority_runtime_job (
        runtime_job_id TEXT PRIMARY KEY,
        job_kind TEXT NOT NULL,
        runtime_group TEXT NOT NULL,
        subject_kind TEXT NOT NULL,
        subject_id TEXT NOT NULL,
        project_id TEXT NOT NULL DEFAULT '',
        dedupe_key TEXT NOT NULL,
        input_snapshot JSONB NOT NULL,
        input_hash TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'READY',
        priority INTEGER NOT NULL DEFAULT 100,
        available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        attempt_count INTEGER NOT NULL DEFAULT 0,
        max_attempts INTEGER NOT NULL DEFAULT 5,
        claimed_by TEXT NOT NULL DEFAULT '',
        current_attempt_id TEXT,
        current_fencing_token BIGINT NOT NULL DEFAULT 0,
        result_hash TEXT NOT NULL DEFAULT '',
        last_error JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        completed_at TIMESTAMPTZ,
        CONSTRAINT authority_runtime_job_status_check CHECK (
            status IN (
                'READY','CLAIMED','RUNNING','CHECKPOINTED','RETRY_WAIT',
                'SUCCEEDED','FAILED','DEAD_LETTER','CANCELLED'
            )
        ),
        CONSTRAINT authority_runtime_job_attempt_bounds_check CHECK (
            attempt_count >= 0 AND max_attempts > 0
            AND attempt_count <= max_attempts
        ),
        CONSTRAINT authority_runtime_job_priority_check CHECK (priority >= 0),
        CONSTRAINT authority_runtime_job_input_hash_check CHECK (
            input_hash LIKE 'sha256:%'
        )
    )
    """,
    """
    CREATE TABLE authority_runtime_job_attempt (
        attempt_id TEXT PRIMARY KEY,
        runtime_job_id TEXT NOT NULL REFERENCES authority_runtime_job(runtime_job_id),
        attempt_number INTEGER NOT NULL,
        worker_id TEXT NOT NULL,
        status TEXT NOT NULL,
        lease_id TEXT NOT NULL,
        fencing_token BIGINT NOT NULL,
        lease_expires_at TIMESTAMPTZ NOT NULL,
        heartbeat_at TIMESTAMPTZ NOT NULL,
        checkpoint JSONB NOT NULL DEFAULT '{}'::jsonb,
        checkpoint_hash TEXT NOT NULL DEFAULT '',
        checkpoint_sequence INTEGER NOT NULL DEFAULT 0,
        result_hash TEXT NOT NULL DEFAULT '',
        error JSONB NOT NULL DEFAULT '{}'::jsonb,
        started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        completed_at TIMESTAMPTZ,
        CONSTRAINT authority_runtime_job_attempt_unique
            UNIQUE(runtime_job_id, attempt_number),
        CONSTRAINT authority_runtime_job_attempt_status_check CHECK (
            status IN (
                'CLAIMED','RUNNING','CHECKPOINTED','SUCCEEDED','FAILED','ABANDONED'
            )
        ),
        CONSTRAINT authority_runtime_job_attempt_number_check CHECK (
            attempt_number > 0 AND fencing_token > 0
        )
    )
    """,
    """
    ALTER TABLE authority_runtime_job
    ADD CONSTRAINT authority_runtime_job_current_attempt_fk
    FOREIGN KEY (current_attempt_id)
    REFERENCES authority_runtime_job_attempt(attempt_id)
    DEFERRABLE INITIALLY DEFERRED
    """,
    """
    CREATE TABLE authority_runtime_job_lease (
        lease_id TEXT PRIMARY KEY,
        runtime_job_id TEXT NOT NULL REFERENCES authority_runtime_job(runtime_job_id),
        attempt_id TEXT NOT NULL UNIQUE
            REFERENCES authority_runtime_job_attempt(attempt_id),
        worker_id TEXT NOT NULL,
        fencing_token BIGINT NOT NULL,
        lease_expires_at TIMESTAMPTZ NOT NULL,
        heartbeat_at TIMESTAMPTZ NOT NULL,
        status TEXT NOT NULL,
        released_at TIMESTAMPTZ,
        release_reason TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT authority_runtime_job_lease_status_check CHECK (
            status IN ('HELD','RELEASED','EXPIRED','REVOKED')
        ),
        CONSTRAINT authority_runtime_job_lease_fence_check CHECK (
            fencing_token > 0
        )
    )
    """,
    """
    CREATE TABLE authority_runtime_job_checkpoint (
        checkpoint_id TEXT PRIMARY KEY,
        runtime_job_id TEXT NOT NULL REFERENCES authority_runtime_job(runtime_job_id),
        attempt_id TEXT NOT NULL REFERENCES authority_runtime_job_attempt(attempt_id),
        checkpoint_sequence INTEGER NOT NULL,
        fencing_token BIGINT NOT NULL,
        checkpoint JSONB NOT NULL,
        checkpoint_hash TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT authority_runtime_job_checkpoint_unique
            UNIQUE(attempt_id, checkpoint_sequence),
        CONSTRAINT authority_runtime_job_checkpoint_sequence_check CHECK (
            checkpoint_sequence > 0 AND fencing_token > 0
        ),
        CONSTRAINT authority_runtime_job_checkpoint_hash_check CHECK (
            checkpoint_hash LIKE 'sha256:%'
        )
    )
    """,
    """
    CREATE TABLE authority_runtime_job_result (
        result_id TEXT PRIMARY KEY,
        runtime_job_id TEXT NOT NULL REFERENCES authority_runtime_job(runtime_job_id),
        attempt_id TEXT NOT NULL UNIQUE
            REFERENCES authority_runtime_job_attempt(attempt_id),
        fencing_token BIGINT NOT NULL,
        status TEXT NOT NULL,
        result JSONB NOT NULL,
        result_hash TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT authority_runtime_job_result_status_check CHECK (
            status IN ('SUCCEEDED','FAILED')
        ),
        CONSTRAINT authority_runtime_job_result_fence_check CHECK (
            fencing_token > 0
        ),
        CONSTRAINT authority_runtime_job_result_hash_check CHECK (
            result_hash LIKE 'sha256:%'
        )
    )
    """,
    """
    CREATE TABLE authority_runtime_job_event (
        runtime_job_event_id TEXT PRIMARY KEY,
        runtime_job_id TEXT NOT NULL REFERENCES authority_runtime_job(runtime_job_id),
        attempt_id TEXT REFERENCES authority_runtime_job_attempt(attempt_id),
        sequence_number BIGINT NOT NULL,
        event_type TEXT NOT NULL,
        worker_id TEXT NOT NULL DEFAULT '',
        fencing_token BIGINT NOT NULL DEFAULT 0,
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT authority_runtime_job_event_sequence_unique
            UNIQUE(runtime_job_id, sequence_number),
        CONSTRAINT authority_runtime_job_event_sequence_check CHECK (
            sequence_number > 0 AND fencing_token >= 0
        )
    )
    """,
    """
    CREATE UNIQUE INDEX authority_runtime_job_dedupe_idx
    ON authority_runtime_job(runtime_group, job_kind, dedupe_key)
    """,
    """
    CREATE UNIQUE INDEX authority_runtime_job_active_subject_idx
    ON authority_runtime_job(runtime_group, job_kind, subject_kind, subject_id)
    WHERE status IN ('READY','CLAIMED','RUNNING','CHECKPOINTED','RETRY_WAIT')
    """,
    """
    CREATE INDEX authority_runtime_job_claim_idx
    ON authority_runtime_job(runtime_group, priority, available_at, created_at)
    WHERE status IN ('READY','RETRY_WAIT')
    """,
    """
    CREATE INDEX authority_runtime_job_current_attempt_idx
    ON authority_runtime_job(current_attempt_id)
    WHERE current_attempt_id IS NOT NULL
    """,
    """
    CREATE INDEX authority_runtime_job_active_lease_idx
    ON authority_runtime_job_lease(status, lease_expires_at, runtime_job_id)
    """,
    """
    CREATE UNIQUE INDEX authority_runtime_job_one_held_lease_idx
    ON authority_runtime_job_lease(runtime_job_id)
    WHERE status='HELD'
    """,
    """
    CREATE INDEX authority_runtime_job_attempt_job_idx
    ON authority_runtime_job_attempt(runtime_job_id, status, attempt_number DESC)
    """,
    """
    CREATE INDEX authority_runtime_job_checkpoint_job_idx
    ON authority_runtime_job_checkpoint(runtime_job_id, created_at DESC)
    """,
    """
    CREATE INDEX authority_runtime_job_result_job_idx
    ON authority_runtime_job_result(runtime_job_id, created_at DESC)
    """,
    """
    CREATE INDEX authority_runtime_job_event_attempt_idx
    ON authority_runtime_job_event(attempt_id)
    WHERE attempt_id IS NOT NULL
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []
