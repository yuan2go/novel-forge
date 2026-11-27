from __future__ import annotations

MIGRATION_ID = "20260713_0013_attempt_runtime"
DOWN_REVISION = "20260713_0012_admission_contract"

UPGRADE_STATEMENTS = [
    "ALTER TABLE authority_attempt ADD COLUMN max_attempts INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE authority_attempt ADD COLUMN queued_at TIMESTAMPTZ",
    "ALTER TABLE authority_attempt ADD COLUMN checkpoint JSONB NOT NULL DEFAULT '{}'::jsonb",
    "ALTER TABLE authority_attempt ADD COLUMN checkpointed_at TIMESTAMPTZ",
    "ALTER TABLE authority_attempt ADD COLUMN result_submitted_at TIMESTAMPTZ",
    "ALTER TABLE authority_attempt ADD CONSTRAINT authority_attempt_max_attempts_positive CHECK (max_attempts > 0)",
    """
    CREATE TABLE authority_late_result_evidence (
        evidence_id TEXT PRIMARY KEY,
        attempt_id TEXT NOT NULL REFERENCES authority_attempt(attempt_id),
        operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        project_id TEXT NOT NULL,
        command_type TEXT NOT NULL,
        worker_id TEXT NOT NULL,
        presented_fencing_token BIGINT NOT NULL,
        current_fencing_token BIGINT,
        payload JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX authority_late_result_attempt_idx ON authority_late_result_evidence(attempt_id, created_at DESC)",
    "CREATE INDEX authority_late_result_operation_idx ON authority_late_result_evidence(operation_id, created_at DESC)",
]

DOWNGRADE_STATEMENTS: list[str] = []
