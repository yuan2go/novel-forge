from __future__ import annotations


MIGRATION_ID = "20260804_0066_runtime_job_attempt_lease_existence"
DOWN_REVISION = "20260804_0065_runtime_job_lease_identity"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = (
    "Restore the pre-0066 backup for full rollback. For an in-place repair, "
    "drain Runtime Job workers, reconstruct each orphan Attempt Lease from "
    "immutable claim events, then recreate the deferred reverse constraint."
)


PREFLIGHT_STATEMENTS = [
    """
    SELECT 'runtime_job_attempt_without_exact_lease', COUNT(*)
    FROM authority_runtime_job_attempt AS attempt
    LEFT JOIN authority_runtime_job_lease AS lease
      ON lease.runtime_job_id=attempt.runtime_job_id
     AND lease.attempt_id=attempt.attempt_id
     AND lease.lease_id=attempt.lease_id
     AND lease.worker_id=attempt.worker_id
     AND lease.fencing_token=attempt.fencing_token
    WHERE lease.lease_id IS NULL
    """,
]


UPGRADE_STATEMENTS = [
    """
    ALTER TABLE authority_runtime_job_lease
    ADD CONSTRAINT authority_runtime_job_lease_attempt_identity_unique
    UNIQUE(runtime_job_id, attempt_id, lease_id, worker_id, fencing_token)
    """,
    """
    ALTER TABLE authority_runtime_job_attempt
    ADD CONSTRAINT authority_runtime_job_attempt_exact_lease_fk
    FOREIGN KEY(runtime_job_id, attempt_id, lease_id, worker_id, fencing_token)
    REFERENCES authority_runtime_job_lease(
        runtime_job_id, attempt_id, lease_id, worker_id, fencing_token
    )
    DEFERRABLE INITIALLY DEFERRED
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []
