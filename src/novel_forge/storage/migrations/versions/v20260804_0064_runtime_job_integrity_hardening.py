from __future__ import annotations


MIGRATION_ID = "20260804_0064_runtime_job_integrity_hardening"
DOWN_REVISION = "20260804_0063_worker_fleet_operational_governance"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = (
    "Restore the pre-0064 backup for full rollback. For an in-place repair, "
    "drain Runtime Job workers, preserve immutable events and terminal results, "
    "repair cross-table execution identities, then recreate the composite "
    "constraints before workers resume."
)


PREFLIGHT_STATEMENTS = [
    "SELECT 'missing_runtime_job', "
    "CASE WHEN to_regclass('authority_runtime_job') IS NULL THEN 1 ELSE 0 END",
    "SELECT 'missing_runtime_job_attempt', "
    "CASE WHEN to_regclass('authority_runtime_job_attempt') IS NULL THEN 1 ELSE 0 END",
]


UPGRADE_STATEMENTS = [
    """
    UPDATE authority_migration_run
    SET status='IMPORT_RUNNING', updated_at=NOW()
    WHERE status='ARCHIVAL_RECONCILED'
      AND run_completion_level='NONE'
    """,
    """
    ALTER TABLE authority_runtime_job_attempt
    ADD CONSTRAINT authority_runtime_job_attempt_execution_identity_unique
    UNIQUE(runtime_job_id, attempt_id, fencing_token)
    """,
    """
    ALTER TABLE authority_runtime_job
    ADD CONSTRAINT authority_runtime_job_current_execution_fk
    FOREIGN KEY(runtime_job_id, current_attempt_id, current_fencing_token)
    REFERENCES authority_runtime_job_attempt(
        runtime_job_id, attempt_id, fencing_token
    )
    DEFERRABLE INITIALLY DEFERRED
    """,
    """
    ALTER TABLE authority_runtime_job_lease
    ADD CONSTRAINT authority_runtime_job_lease_execution_fk
    FOREIGN KEY(runtime_job_id, attempt_id, fencing_token)
    REFERENCES authority_runtime_job_attempt(
        runtime_job_id, attempt_id, fencing_token
    )
    DEFERRABLE INITIALLY DEFERRED
    """,
    """
    ALTER TABLE authority_runtime_job_checkpoint
    ADD CONSTRAINT authority_runtime_job_checkpoint_execution_fk
    FOREIGN KEY(runtime_job_id, attempt_id, fencing_token)
    REFERENCES authority_runtime_job_attempt(
        runtime_job_id, attempt_id, fencing_token
    )
    DEFERRABLE INITIALLY DEFERRED
    """,
    """
    ALTER TABLE authority_runtime_job_result
    ADD CONSTRAINT authority_runtime_job_result_execution_fk
    FOREIGN KEY(runtime_job_id, attempt_id, fencing_token)
    REFERENCES authority_runtime_job_attempt(
        runtime_job_id, attempt_id, fencing_token
    )
    DEFERRABLE INITIALLY DEFERRED
    """,
    """
    ALTER TABLE authority_runtime_job_event
    ADD CONSTRAINT authority_runtime_job_event_execution_fk
    FOREIGN KEY(runtime_job_id, attempt_id, fencing_token)
    REFERENCES authority_runtime_job_attempt(
        runtime_job_id, attempt_id, fencing_token
    )
    DEFERRABLE INITIALLY DEFERRED
    """,
    """
    CREATE INDEX authority_runtime_job_current_execution_fk_idx
    ON authority_runtime_job(
        runtime_job_id, current_attempt_id, current_fencing_token
    )
    """,
    """
    CREATE INDEX authority_runtime_job_lease_execution_fk_idx
    ON authority_runtime_job_lease(runtime_job_id, attempt_id, fencing_token)
    """,
    """
    CREATE INDEX authority_runtime_job_checkpoint_execution_fk_idx
    ON authority_runtime_job_checkpoint(runtime_job_id, attempt_id, fencing_token)
    """,
    """
    CREATE INDEX authority_runtime_job_result_execution_fk_idx
    ON authority_runtime_job_result(runtime_job_id, attempt_id, fencing_token)
    """,
    """
    CREATE INDEX authority_runtime_job_event_execution_fk_idx
    ON authority_runtime_job_event(runtime_job_id, attempt_id, fencing_token)
    WHERE attempt_id IS NOT NULL
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []
