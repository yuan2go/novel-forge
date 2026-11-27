from __future__ import annotations


MIGRATION_ID = "20260804_0057_hot_query_governance"
DOWN_REVISION = "20260804_0056_database_runtime_governance"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = (
    "Re-run the additive CREATE INDEX IF NOT EXISTS statement. The index contains "
    "no business authority state and can be rebuilt online during maintenance."
)

UPGRADE_STATEMENTS = [
    """
    CREATE INDEX IF NOT EXISTS authority_outbox_worker_claim_idx
    ON outbox_event(available_at, created_at, outbox_id)
    WHERE LOWER(status) IN ('pending', 'queued', 'failed')
    """,
]

DOWNGRADE_STATEMENTS: list[str] = []
