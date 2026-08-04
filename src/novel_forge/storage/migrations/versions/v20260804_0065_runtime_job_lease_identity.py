from __future__ import annotations


MIGRATION_ID = "20260804_0065_runtime_job_lease_identity"
DOWN_REVISION = "20260804_0064_runtime_job_integrity_hardening"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = (
    "Restore the pre-0065 backup for full rollback. For an in-place repair, "
    "drain Runtime Job workers, reconcile Attempt and Lease identity from "
    "immutable Runtime Job events, then recreate the composite constraint."
)


PREFLIGHT_STATEMENTS = [
    """
    SELECT 'runtime_job_attempt_lease_identity_mismatch', COUNT(*)
    FROM authority_runtime_job_attempt AS attempt
    JOIN authority_runtime_job_lease AS lease
      ON lease.attempt_id=attempt.attempt_id
    WHERE lease.runtime_job_id<>attempt.runtime_job_id
       OR lease.lease_id<>attempt.lease_id
       OR lease.worker_id<>attempt.worker_id
       OR lease.fencing_token<>attempt.fencing_token
    """,
]


UPGRADE_STATEMENTS = [
    """
    ALTER TABLE authority_runtime_job_attempt
    ADD CONSTRAINT authority_runtime_job_attempt_lease_identity_unique
    UNIQUE(runtime_job_id, attempt_id, lease_id, worker_id, fencing_token)
    """,
    """
    ALTER TABLE authority_runtime_job_lease
    ADD CONSTRAINT authority_runtime_job_lease_attempt_identity_fk
    FOREIGN KEY(runtime_job_id, attempt_id, lease_id, worker_id, fencing_token)
    REFERENCES authority_runtime_job_attempt(
        runtime_job_id, attempt_id, lease_id, worker_id, fencing_token
    )
    DEFERRABLE INITIALLY DEFERRED
    """,
    """
    CREATE INDEX authority_runtime_job_lease_attempt_identity_fk_idx
    ON authority_runtime_job_lease(
        runtime_job_id, attempt_id, lease_id, worker_id, fencing_token
    )
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []
