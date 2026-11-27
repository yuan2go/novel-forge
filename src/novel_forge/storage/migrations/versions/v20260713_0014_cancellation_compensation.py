from __future__ import annotations

MIGRATION_ID = "20260713_0014_cancellation_compensation"
DOWN_REVISION = "20260713_0013_attempt_runtime"

UPGRADE_STATEMENTS = [
    """
    CREATE TABLE authority_cancellation_command (
        cancel_command_id TEXT PRIMARY KEY,
        operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        project_id TEXT NOT NULL,
        command_version INTEGER NOT NULL,
        actor_id TEXT NOT NULL,
        reason TEXT NOT NULL,
        expected_operation_version BIGINT NOT NULL,
        idempotency_key TEXT NOT NULL,
        request_digest TEXT NOT NULL,
        trace_id TEXT NOT NULL,
        correlation_id TEXT NOT NULL,
        causation_id TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (operation_id, idempotency_key),
        CHECK (command_version = 1)
    )
    """,
    """
    CREATE TABLE authority_worker_cancel_signal (
        signal_id TEXT PRIMARY KEY,
        operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        attempt_id TEXT NOT NULL REFERENCES authority_attempt(attempt_id),
        fencing_token BIGINT,
        status TEXT NOT NULL,
        payload JSONB NOT NULL,
        requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        acknowledged_at TIMESTAMPTZ,
        UNIQUE (attempt_id),
        CHECK (status IN ('REQUESTED', 'ACKNOWLEDGED'))
    )
    """,
    "CREATE INDEX authority_cancel_operation_idx ON authority_cancellation_command(operation_id, created_at DESC)",
    "CREATE INDEX authority_cancel_signal_operation_idx ON authority_worker_cancel_signal(operation_id, requested_at DESC)",
]

DOWNGRADE_STATEMENTS: list[str] = []
