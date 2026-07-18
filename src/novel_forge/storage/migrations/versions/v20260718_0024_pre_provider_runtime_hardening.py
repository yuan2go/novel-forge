from __future__ import annotations

MIGRATION_ID = "20260718_0024_pre_provider_runtime_hardening"
DOWN_REVISION = "20260718_0023_provider_budget_lifecycle"

UPGRADE_STATEMENTS = [
    "ALTER TABLE authority_operation ADD COLUMN business_deadline_at TIMESTAMPTZ",
    "ALTER TABLE authority_attempt ADD COLUMN business_deadline_at TIMESTAMPTZ",
    "ALTER TABLE authority_saga ADD COLUMN root_deadline_at TIMESTAMPTZ",
    "ALTER TABLE authority_external_effect ADD COLUMN request_timeout_seconds INTEGER",
    "ALTER TABLE authority_budget_reservation ADD COLUMN budget_timezone TEXT NOT NULL DEFAULT 'UTC'",
    "ALTER TABLE authority_budget_reservation ADD COLUMN budget_breach BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE authority_budget_reservation ADD CONSTRAINT authority_budget_timezone_nonempty CHECK (budget_timezone <> '')",
    "ALTER TABLE authority_external_effect ADD CONSTRAINT authority_effect_request_timeout_positive CHECK (request_timeout_seconds IS NULL OR request_timeout_seconds > 0)",
    "ALTER TABLE authority_effect_reconciliation_evidence DROP CONSTRAINT authority_effect_reconciliation_evidence_outcome_check",
    "ALTER TABLE authority_effect_reconciliation_evidence ADD CONSTRAINT authority_effect_reconciliation_evidence_outcome_check CHECK (outcome IN ('success','not_found','ambiguous','failed_final','cancelled'))",
    "CREATE INDEX authority_operation_deadline_idx ON authority_operation(business_deadline_at, status) WHERE business_deadline_at IS NOT NULL",
    "CREATE INDEX authority_attempt_deadline_idx ON authority_attempt(business_deadline_at, status) WHERE business_deadline_at IS NOT NULL",
    "CREATE INDEX authority_saga_deadline_idx ON authority_saga(root_deadline_at, status) WHERE root_deadline_at IS NOT NULL",
    """
    CREATE TABLE authority_recovery_command (
        recovery_command_id TEXT PRIMARY KEY,
        operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        project_id TEXT NOT NULL,
        actor_id TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        request_digest TEXT NOT NULL,
        expected_version BIGINT NOT NULL,
        reason TEXT NOT NULL,
        recovery_action TEXT NOT NULL,
        trace_id TEXT NOT NULL,
        correlation_id TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, operation_id, idempotency_key),
        CHECK (expected_version >= 0),
        CHECK (recovery_action IN (
            'READY_FOR_RETRY', 'LEASE_TAKEOVER_VISIBLE',
            'RECONCILIATION_DISPATCHED', 'GATE_RESUMED', 'ALREADY_COMPLETE'
        ))
    )
    """,
    "CREATE INDEX authority_recovery_operation_idx ON authority_recovery_command(project_id, operation_id, created_at DESC)",
    """
    CREATE TABLE authority_effect_manual_resolution (
        manual_resolution_id TEXT PRIMARY KEY,
        external_effect_id TEXT NOT NULL REFERENCES authority_external_effect(external_effect_id),
        operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        project_id TEXT NOT NULL,
        actor_id TEXT NOT NULL,
        decision TEXT NOT NULL,
        reason TEXT NOT NULL,
        evidence JSONB NOT NULL,
        idempotency_key TEXT NOT NULL,
        request_digest TEXT NOT NULL,
        trace_id TEXT NOT NULL,
        correlation_id TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, external_effect_id, idempotency_key),
        CHECK (decision IN (
            'MARK_SUCCEEDED','MARK_NOT_FOUND','MARK_FAILED_FINAL',
            'MARK_CANCELLED','RETRY_WITH_NEW_GENERATION'
        ))
    )
    """,
    "CREATE INDEX authority_effect_manual_resolution_idx ON authority_effect_manual_resolution(project_id, external_effect_id, created_at DESC)",
    "CREATE INDEX authority_effect_manual_resolution_operation_idx ON authority_effect_manual_resolution(operation_id)",
]

DOWNGRADE_STATEMENTS: list[str] = []
