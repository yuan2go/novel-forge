from __future__ import annotations


MIGRATION_ID = "20260804_0056_database_runtime_governance"
DOWN_REVISION = "20260804_0055_legacy_native_conversion"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = (
    "Re-run the additive worker projection columns and CREATE INDEX IF NOT EXISTS "
    "statements; no domain authority row is rewritten."
)

UPGRADE_STATEMENTS = [
    """
    ALTER TABLE authority_worker_health_projection
        DROP CONSTRAINT authority_worker_health_status_check,
        ADD CONSTRAINT authority_worker_health_status_check CHECK (
            status IN ('STARTING','READY','BUSY','DEGRADED','DRAINING','FATAL','STOPPED')
        ),
        ADD COLUMN runtime_group TEXT NOT NULL DEFAULT '',
        ADD COLUMN active_attempts INTEGER NOT NULL DEFAULT 0,
        ADD COLUMN completed_count BIGINT NOT NULL DEFAULT 0,
        ADD COLUMN failed_count BIGINT NOT NULL DEFAULT 0,
        ADD COLUMN database_status TEXT NOT NULL DEFAULT 'UNKNOWN',
        ADD COLUMN drain_status TEXT NOT NULL DEFAULT 'ACCEPTING',
        ADD CONSTRAINT authority_worker_health_active_attempts_nonnegative
            CHECK (active_attempts >= 0),
        ADD CONSTRAINT authority_worker_health_completed_nonnegative
            CHECK (completed_count >= 0),
        ADD CONSTRAINT authority_worker_health_failed_nonnegative
            CHECK (failed_count >= 0),
        ADD CONSTRAINT authority_worker_health_database_status_check
            CHECK (database_status IN ('READY','DEGRADED','UNAVAILABLE','UNKNOWN')),
        ADD CONSTRAINT authority_worker_health_drain_status_check
            CHECK (drain_status IN ('ACCEPTING','DRAINING','DRAINED'))
    """,
    """
    CREATE INDEX IF NOT EXISTS authority_operation_worker_poll_idx
    ON authority_operation(definition_name, status, created_at, operation_id)
    WHERE status IN ('READY', 'FAILED_RETRYABLE', 'EXECUTING')
    """,
    """
    CREATE INDEX IF NOT EXISTS authority_book_production_worker_poll_idx
    ON authority_book_production(state, updated_at, book_run_id)
    WHERE state IN (
        'CHAPTER_SUBMITTED', 'CHAPTER_RUNNING', 'CHAPTER_WAITING_RETRY',
        'CHAPTER_COMPLETED', 'READER_OUTCOME_PENDING', 'CHECKPOINT_PENDING'
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS authority_external_effect_ready_poll_idx
    ON authority_external_effect(status, created_at, external_effect_id)
    WHERE status IN ('READY', 'FAILED_RETRYABLE', 'RECONCILIATION_REQUIRED')
    """,
]

DOWNGRADE_STATEMENTS: list[str] = []
