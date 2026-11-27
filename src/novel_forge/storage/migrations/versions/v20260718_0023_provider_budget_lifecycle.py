from __future__ import annotations

MIGRATION_ID = "20260718_0023_provider_budget_lifecycle"
DOWN_REVISION = "20260716_0022_authority_asset_locator"

UPGRADE_STATEMENTS = [
    "ALTER TABLE authority_external_effect ADD COLUMN provider_request_id TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE authority_external_effect ADD COLUMN model_id TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE authority_external_effect ADD COLUMN request_deadline_at TIMESTAMPTZ",
    "ALTER TABLE authority_external_effect ADD COLUMN last_provider_heartbeat_at TIMESTAMPTZ",
    "ALTER TABLE authority_external_effect ADD COLUMN reconciliation_mode TEXT NOT NULL DEFAULT 'query'",
    "ALTER TABLE authority_external_effect ADD COLUMN manual_resolution_required BOOLEAN NOT NULL DEFAULT FALSE",
    """
    ALTER TABLE authority_external_effect
    ADD CONSTRAINT authority_effect_reconciliation_mode_check
    CHECK (reconciliation_mode IN ('query', 'callback', 'unsupported'))
    """,
    "CREATE INDEX authority_effect_provider_request_idx ON authority_external_effect(project_id, provider, provider_request_id) WHERE provider_request_id <> ''",
    "CREATE INDEX authority_effect_reconciliation_ready_idx ON authority_external_effect(project_id, status, reconciliation_mode) WHERE status IN ('UNKNOWN', 'RECONCILIATION_REQUIRED')",
    """
    CREATE TABLE authority_budget_reservation (
        reservation_id TEXT PRIMARY KEY,
        operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        external_effect_id TEXT REFERENCES authority_external_effect(external_effect_id),
        project_id TEXT NOT NULL,
        stable_idempotency_key TEXT NOT NULL,
        provider TEXT NOT NULL,
        chapter INTEGER,
        currency TEXT NOT NULL,
        estimated_amount NUMERIC(20, 8) NOT NULL,
        reserved_amount NUMERIC(20, 8) NOT NULL,
        settled_amount NUMERIC(20, 8) NOT NULL DEFAULT 0,
        estimated_tokens BIGINT NOT NULL DEFAULT 0,
        actual_tokens BIGINT NOT NULL DEFAULT 0,
        status TEXT NOT NULL,
        caps JSONB NOT NULL DEFAULT '{}'::jsonb,
        evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        settled_at TIMESTAMPTZ,
        UNIQUE(project_id, stable_idempotency_key),
        CHECK (estimated_amount >= 0 AND reserved_amount >= 0 AND settled_amount >= 0),
        CHECK (estimated_tokens >= 0 AND actual_tokens >= 0),
        CHECK (chapter IS NULL OR chapter > 0),
        CHECK (status IN ('RESERVED', 'HELD_UNKNOWN', 'SETTLED', 'RELEASED', 'REJECTED'))
    )
    """,
    "CREATE INDEX authority_budget_project_status_idx ON authority_budget_reservation(project_id, status, created_at)",
    "CREATE INDEX authority_budget_operation_idx ON authority_budget_reservation(operation_id, status)",
    "CREATE INDEX authority_budget_effect_idx ON authority_budget_reservation(external_effect_id) WHERE external_effect_id IS NOT NULL",
    "CREATE INDEX authority_budget_provider_day_idx ON authority_budget_reservation(project_id, provider, created_at)",
]

DOWNGRADE_STATEMENTS: list[str] = []
