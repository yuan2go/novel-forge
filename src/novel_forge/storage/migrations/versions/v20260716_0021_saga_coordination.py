from __future__ import annotations

MIGRATION_ID = "20260716_0021_saga_coordination"
DOWN_REVISION = "20260716_0020_operation_output_evidence"

UPGRADE_STATEMENTS = [
    "ALTER TABLE authority_saga ADD COLUMN coordinator_owner TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE authority_saga ADD COLUMN coordinator_lease_id TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE authority_saga ADD COLUMN coordinator_fencing_token BIGINT NOT NULL DEFAULT 0",
    "ALTER TABLE authority_saga ADD COLUMN coordinator_expires_at TIMESTAMPTZ",
    "ALTER TABLE authority_saga ADD COLUMN coordinator_heartbeat_at TIMESTAMPTZ",
    "ALTER TABLE authority_saga ADD COLUMN forward_recovery_attempts INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE authority_saga ADD CONSTRAINT authority_saga_fencing_token_check CHECK (coordinator_fencing_token >= 0)",
    "ALTER TABLE authority_saga ADD CONSTRAINT authority_saga_forward_recovery_attempts_check CHECK (forward_recovery_attempts >= 0)",
    "ALTER TABLE authority_saga_step ADD COLUMN compensation_operation_id TEXT REFERENCES authority_operation(operation_id)",
    "CREATE UNIQUE INDEX authority_saga_compensation_operation_unique ON authority_saga_step(compensation_operation_id) WHERE compensation_operation_id IS NOT NULL",
]

DOWNGRADE_STATEMENTS: list[str] = []
