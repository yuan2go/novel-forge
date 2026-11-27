from __future__ import annotations

MIGRATION_ID = "20260801_0045_task_recovery_authority"
DOWN_REVISION = "20260801_0044_project_binding_authority"


UPGRADE_STATEMENTS = [
    """
    CREATE TABLE authority_outbox_recovery_command (
        recovery_command_id TEXT PRIMARY KEY,
        outbox_id TEXT NOT NULL REFERENCES outbox_event(outbox_id),
        replacement_outbox_id TEXT NOT NULL UNIQUE REFERENCES outbox_event(outbox_id),
        project_id TEXT NOT NULL,
        actor_id TEXT NOT NULL,
        expected_attempt_count INTEGER NOT NULL,
        idempotency_key TEXT NOT NULL,
        request_digest TEXT NOT NULL,
        reason TEXT NOT NULL,
        recovery_action TEXT NOT NULL,
        trace_id TEXT NOT NULL,
        correlation_id TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, outbox_id, idempotency_key),
        CHECK (expected_attempt_count >= 0),
        CHECK (recovery_action = 'REQUEUE_NEW_GENERATION')
    )
    """,
    """
    CREATE INDEX authority_outbox_recovery_query_idx
    ON authority_outbox_recovery_command(project_id, outbox_id, created_at DESC)
    """,
]


# Forward-only audit evidence. Restore uses the Authority backup/rehearsal
# procedure; recovery commands must never be erased by an application rollback.
DOWNGRADE_STATEMENTS: list[str] = []
