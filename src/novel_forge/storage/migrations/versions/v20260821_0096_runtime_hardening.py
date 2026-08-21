from __future__ import annotations


MIGRATION_ID = "20260821_0096_runtime_hardening"
DOWN_REVISION = "20260821_0095_post_merge_correctness_repair"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = (
    "Preserve accepted narrative truth. Reconcile Arc follow-up terminal states, "
    "unknown embedding effects, frozen Agent execution, and semantic retrieval "
    "through their existing Authorities and durable runtime records."
)


UPGRADE_STATEMENTS = [
    """
    ALTER TABLE authority_arc_checkpoint_followup
    DROP CONSTRAINT authority_arc_checkpoint_followup_status_check
    """,
    """
    ALTER TABLE authority_arc_checkpoint_followup
    ADD CONSTRAINT authority_arc_checkpoint_followup_status_check CHECK (
        status IN (
            'READY','RUNNING','PROPOSED','WAITING_APPROVAL','COMPLETED',
            'FAILED_RETRYABLE','FAILED_FINAL','DEAD_LETTER','CANCELLED',
            'RECONCILIATION_REQUIRED','MANUAL_INTERVENTION'
        )
    )
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []


__all__ = [
    "BACKUP_REQUIRED",
    "DOWN_REVISION",
    "FORWARD_FIX",
    "FORWARD_ONLY",
    "MIGRATION_ID",
    "UPGRADE_STATEMENTS",
]
