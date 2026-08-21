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
    ALTER TABLE authority_agent_harness_session
    ADD COLUMN execution_contract JSONB NOT NULL DEFAULT '{}'::jsonb
    """,
    """
    ALTER TABLE authority_agent_harness_session
    ADD COLUMN execution_contract_hash TEXT NOT NULL DEFAULT '' CHECK (
        execution_contract_hash = '' OR
        execution_contract_hash ~ '^sha256:[0-9a-f]{64}$'
    )
    """,
    """
    ALTER TABLE authority_agent_harness_session
    ADD CONSTRAINT authority_agent_harness_execution_contract_identity_check
    CHECK (
        (execution_contract = '{}'::jsonb AND execution_contract_hash = '') OR
        (execution_contract <> '{}'::jsonb AND execution_contract_hash <> '')
    )
    """,
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
    """
    ALTER TABLE authority_retrieval_embedding_projection
    DROP CONSTRAINT authority_retrieval_embedding_projection_status_check
    """,
    """
    UPDATE authority_retrieval_embedding_projection
    SET status='FAILED_FINAL', version=version+1, updated_at=NOW(),
        evidence=evidence || '{"migration":"FAILED_TERMINAL_TO_FAILED_FINAL"}'::jsonb
    WHERE status='FAILED_TERMINAL'
    """,
    """
    ALTER TABLE authority_retrieval_embedding_projection
    ADD CONSTRAINT authority_retrieval_embedding_projection_status_check CHECK (
        status IN (
            'PENDING','RUNNING','READY','FAILED_RETRYABLE','FAILED_FINAL',
            'DEAD_LETTER','CANCELLED','RECONCILIATION_REQUIRED'
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
