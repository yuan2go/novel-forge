from __future__ import annotations

MIGRATION_ID = "20261006_0163_failed_step_successor"
DOWN_REVISION = "20261006_0162_stage_repair_policy"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "append failed-step successor evidence; preserve terminal Operations, Attempts and successful siblings"
UPGRADE_STATEMENTS = [
    """CREATE TABLE authority_saga_step_successor (
        successor_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        saga_id TEXT NOT NULL REFERENCES authority_saga(saga_id),
        predecessor_operation_id TEXT NOT NULL UNIQUE REFERENCES authority_operation(operation_id),
        successor_operation_id TEXT NOT NULL UNIQUE REFERENCES authority_operation(operation_id),
        actor_id TEXT NOT NULL,
        contract_version TEXT NOT NULL CHECK (contract_version='kernel-failed-step-successor.v1'),
        request_digest TEXT NOT NULL,
        source_step_snapshot JSONB NOT NULL,
        source_failure_snapshot JSONB NOT NULL,
        policy_evidence JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CHECK (predecessor_operation_id<>successor_operation_id)
    )""",
]
DOWNGRADE_STATEMENTS: list[str] = []
