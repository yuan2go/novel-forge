from __future__ import annotations

MIGRATION_ID = "20260718_0028_provider_adapter_v2"
DOWN_REVISION = "20260718_0027_canon_approval_operation"

UPGRADE_STATEMENTS = [
    "ALTER TABLE authority_external_effect ADD COLUMN provider_capability_profile JSONB NOT NULL DEFAULT '{}'::jsonb",
    "ALTER TABLE authority_external_effect ADD COLUMN provider_control_level TEXT NOT NULL DEFAULT 'LEGACY_UNCONTROLLED'",
    "ALTER TABLE authority_external_effect ADD COLUMN provider_idempotency_mode TEXT NOT NULL DEFAULT 'unsupported'",
    "ALTER TABLE authority_external_effect ADD COLUMN provider_query_mode TEXT NOT NULL DEFAULT 'unsupported'",
    "ALTER TABLE authority_external_effect ADD COLUMN provider_cancel_mode TEXT NOT NULL DEFAULT 'unsupported'",
    "ALTER TABLE authority_external_effect ADD COLUMN provider_callback_mode TEXT NOT NULL DEFAULT 'unsupported'",
    "ALTER TABLE authority_external_effect ADD CONSTRAINT authority_effect_provider_control_level_check CHECK (provider_control_level IN ('V2_CONTROLLED','FIXTURE_CONTROLLED','LEGACY_UNCONTROLLED'))",
    "ALTER TABLE authority_external_effect ADD CONSTRAINT authority_effect_provider_idempotency_mode_check CHECK (provider_idempotency_mode IN ('provider','unsupported'))",
    "ALTER TABLE authority_external_effect ADD CONSTRAINT authority_effect_provider_query_mode_check CHECK (provider_query_mode IN ('query','unsupported'))",
    "ALTER TABLE authority_external_effect ADD CONSTRAINT authority_effect_provider_cancel_mode_check CHECK (provider_cancel_mode IN ('cancel','unsupported'))",
    "ALTER TABLE authority_external_effect ADD CONSTRAINT authority_effect_provider_callback_mode_check CHECK (provider_callback_mode IN ('callback','unsupported'))",
    "CREATE INDEX authority_effect_provider_control_idx ON authority_external_effect(project_id, provider_control_level, status)",
]

DOWNGRADE_STATEMENTS: list[str] = []
