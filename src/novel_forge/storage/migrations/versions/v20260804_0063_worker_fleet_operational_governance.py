from __future__ import annotations


MIGRATION_ID = "20260804_0063_worker_fleet_operational_governance"
DOWN_REVISION = "20260804_0062_runtime_job_execution_plane"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = (
    "Restore the pre-0063 backup for full rollback. For forward repair, drain "
    "workers, expire active Outbox executions, recreate rebuildable health and "
    "metrics projections, and retain delivery receipts and execution history."
)


PREFLIGHT_STATEMENTS = [
    "SELECT 'missing_worker_health', "
    "CASE WHEN to_regclass('authority_worker_health_projection') IS NULL THEN 1 ELSE 0 END",
    "SELECT 'missing_outbox', "
    "CASE WHEN to_regclass('outbox_event') IS NULL THEN 1 ELSE 0 END",
]


UPGRADE_STATEMENTS = [
    """
    CREATE INDEX authority_book_runtime_job_schedule_idx
    ON authority_book_production(state, updated_at, book_run_id)
    WHERE state IN (
        'CHAPTER_SUBMITTED','CHAPTER_RUNNING','CHAPTER_WAITING_RETRY',
        'CHAPTER_COMPLETED','READER_OUTCOME_PENDING','CHECKPOINT_PENDING',
        'READY','COMPLETED'
    )
    """,
    """
    CREATE INDEX authority_runtime_job_active_recovery_idx
    ON authority_runtime_job(runtime_group, status, current_attempt_id)
    WHERE status IN ('CLAIMED','RUNNING','CHECKPOINTED')
    """,
    """
    ALTER TABLE authority_worker_health_projection
        ADD COLUMN active_runtime_job_id TEXT NOT NULL DEFAULT '',
        ADD COLUMN fencing_token BIGINT NOT NULL DEFAULT 0,
        ADD COLUMN completed_runtime_job_count BIGINT NOT NULL DEFAULT 0,
        ADD COLUMN failed_runtime_job_count BIGINT NOT NULL DEFAULT 0,
        ADD COLUMN last_database_success_at TIMESTAMPTZ,
        ADD COLUMN last_database_failure_at TIMESTAMPTZ,
        ADD CONSTRAINT authority_worker_health_fencing_nonnegative CHECK (
            fencing_token >= 0
        ),
        ADD CONSTRAINT authority_worker_health_completed_runtime_nonnegative CHECK (
            completed_runtime_job_count >= 0
        ),
        ADD CONSTRAINT authority_worker_health_failed_runtime_nonnegative CHECK (
            failed_runtime_job_count >= 0
        )
    """,
    """
    CREATE INDEX authority_worker_health_active_runtime_job_idx
    ON authority_worker_health_projection(active_runtime_job_id)
    WHERE active_runtime_job_id <> ''
    """,
    """
    CREATE TABLE authority_outbox_delivery_execution (
        outbox_delivery_execution_id TEXT PRIMARY KEY,
        outbox_id TEXT NOT NULL REFERENCES outbox_event(outbox_id),
        event_id TEXT NOT NULL REFERENCES state_event(event_id),
        worker_id TEXT NOT NULL,
        lease_id TEXT NOT NULL UNIQUE,
        fencing_token BIGINT NOT NULL,
        status TEXT NOT NULL,
        checkpoint_sequence INTEGER NOT NULL DEFAULT 0,
        checkpoint JSONB NOT NULL DEFAULT '{}'::jsonb,
        checkpoint_hash TEXT NOT NULL DEFAULT '',
        result_hash TEXT NOT NULL DEFAULT '',
        error JSONB NOT NULL DEFAULT '{}'::jsonb,
        started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        lease_expires_at TIMESTAMPTZ NOT NULL,
        completed_at TIMESTAMPTZ,
        CONSTRAINT authority_outbox_delivery_execution_identity_unique
            UNIQUE(outbox_id, fencing_token),
        CONSTRAINT authority_outbox_delivery_execution_status_check CHECK (
            status IN ('CLAIMED','RUNNING','CHECKPOINTED','SUCCEEDED','FAILED','ABANDONED','DEAD_LETTER')
        ),
        CONSTRAINT authority_outbox_delivery_execution_fence_check CHECK (
            fencing_token > 0 AND checkpoint_sequence >= 0
        )
    )
    """,
    """
    CREATE INDEX authority_outbox_delivery_execution_event_fk_idx
    ON authority_outbox_delivery_execution(event_id)
    """,
    """
    CREATE INDEX authority_outbox_delivery_execution_worker_idx
    ON authority_outbox_delivery_execution(worker_id, status, started_at DESC)
    """,
    """
    CREATE INDEX authority_outbox_delivery_execution_lease_expiry_idx
    ON authority_outbox_delivery_execution(status, lease_expires_at)
    WHERE status IN ('CLAIMED','RUNNING','CHECKPOINTED')
    """,
    """
    CREATE TABLE authority_worker_operational_metrics_projection (
        worker_id TEXT NOT NULL,
        worker_kind TEXT NOT NULL,
        runtime_group TEXT NOT NULL,
        database_identity_fingerprint TEXT NOT NULL,
        database_role TEXT NOT NULL,
        service TEXT NOT NULL,
        pool_config_fingerprint TEXT NOT NULL,
        pool_size BIGINT NOT NULL DEFAULT 0,
        pool_in_use BIGINT NOT NULL DEFAULT 0,
        pool_waiting BIGINT NOT NULL DEFAULT 0,
        transaction_count BIGINT NOT NULL DEFAULT 0,
        rollback_count BIGINT NOT NULL DEFAULT 0,
        retry_count BIGINT NOT NULL DEFAULT 0,
        timeout_count BIGINT NOT NULL DEFAULT 0,
        deadlock_count BIGINT NOT NULL DEFAULT 0,
        serialization_failure_count BIGINT NOT NULL DEFAULT 0,
        long_transaction_count BIGINT NOT NULL DEFAULT 0,
        runtime_job_backlog BIGINT NOT NULL DEFAULT 0,
        outbox_backlog BIGINT NOT NULL DEFAULT 0,
        unknown_effect_backlog BIGINT NOT NULL DEFAULT 0,
        stale_worker_count BIGINT NOT NULL DEFAULT 0,
        recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY(worker_id, worker_kind),
        CONSTRAINT authority_worker_operational_metrics_nonnegative CHECK (
            pool_size >= 0 AND pool_in_use >= 0 AND pool_waiting >= 0
            AND transaction_count >= 0 AND rollback_count >= 0
            AND retry_count >= 0 AND timeout_count >= 0
            AND deadlock_count >= 0 AND serialization_failure_count >= 0
            AND long_transaction_count >= 0 AND runtime_job_backlog >= 0
            AND outbox_backlog >= 0 AND unknown_effect_backlog >= 0
            AND stale_worker_count >= 0
        )
    )
    """,
    """
    CREATE INDEX authority_worker_operational_metrics_fleet_idx
    ON authority_worker_operational_metrics_projection(
        runtime_group, recorded_at DESC
    )
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []
