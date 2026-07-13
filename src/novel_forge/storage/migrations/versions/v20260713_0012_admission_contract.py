from __future__ import annotations

MIGRATION_ID = "20260713_0012_admission_contract"
DOWN_REVISION = "20260713_0011_effect_inbox_invariants"

UPGRADE_STATEMENTS = [
    "ALTER TABLE authority_operation_definition ADD COLUMN definition_hash TEXT NOT NULL DEFAULT 'legacy-unregistered'",
    "ALTER TABLE authority_operation_definition ADD COLUMN handler_key TEXT NOT NULL DEFAULT 'legacy.unregistered'",
    "ALTER TABLE authority_operation_definition ADD COLUMN handler_contract_version TEXT NOT NULL DEFAULT '0.0.0-legacy'",
    "ALTER TABLE authority_operation_definition ADD COLUMN application_build_id TEXT NOT NULL DEFAULT 'legacy-unknown'",
    "ALTER TABLE authority_operation_definition ADD COLUMN commit_sha TEXT NOT NULL DEFAULT 'legacy-unknown'",
    "ALTER TABLE authority_operation_definition ADD COLUMN execution_mode TEXT NOT NULL DEFAULT 'transactional'",
    "ALTER TABLE authority_operation_definition ADD COLUMN permissions JSONB NOT NULL DEFAULT '[]'::jsonb",
    "ALTER TABLE authority_operation_definition ADD COLUMN approval_policy JSONB NOT NULL DEFAULT '{}'::jsonb",
    "ALTER TABLE authority_operation_definition ADD COLUMN idempotency_scope TEXT NOT NULL DEFAULT 'project:operation'",
    "ALTER TABLE authority_operation_definition ADD COLUMN concurrency_key_template TEXT NOT NULL DEFAULT 'project:{project_id}:legacy'",
    "ALTER TABLE authority_operation_definition ADD COLUMN retry_policy JSONB NOT NULL DEFAULT '{}'::jsonb",
    "ALTER TABLE authority_operation_definition ADD COLUMN timeout_policy JSONB NOT NULL DEFAULT '{}'::jsonb",
    "ALTER TABLE authority_operation_definition ADD COLUMN cancellation_policy JSONB NOT NULL DEFAULT '{}'::jsonb",
    "ALTER TABLE authority_operation_definition ADD COLUMN compensation_policy JSONB NOT NULL DEFAULT '{}'::jsonb",
    "ALTER TABLE authority_operation_definition ADD COLUMN irreversible_effect_policy JSONB NOT NULL DEFAULT '{}'::jsonb",
    "ALTER TABLE authority_operation_definition ADD COLUMN external_capabilities JSONB NOT NULL DEFAULT '[]'::jsonb",
    """
    ALTER TABLE authority_operation_definition
    ADD CONSTRAINT authority_definition_execution_mode_check
    CHECK (execution_mode IN ('transactional', 'worker', 'external', 'saga'))
    """,
    """
    ALTER TABLE authority_operation_definition
    ADD CONSTRAINT authority_definition_permissions_array_check
    CHECK (jsonb_typeof(permissions) = 'array')
    """,
    """
    ALTER TABLE authority_operation_definition
    ADD CONSTRAINT authority_definition_external_capabilities_array_check
    CHECK (jsonb_typeof(external_capabilities) = 'array')
    """,
    "ALTER TABLE authority_operation ADD COLUMN actor_id TEXT NOT NULL DEFAULT 'legacy-unknown'",
    "ALTER TABLE authority_operation ADD COLUMN workspace_id TEXT NOT NULL DEFAULT 'legacy-unknown'",
    "ALTER TABLE authority_operation ADD COLUMN concurrency_key TEXT NOT NULL DEFAULT 'legacy-unknown'",
    "ALTER TABLE authority_operation ADD COLUMN trace_id TEXT NOT NULL DEFAULT 'legacy-unknown'",
    "ALTER TABLE authority_operation ADD COLUMN span_id TEXT NOT NULL DEFAULT 'legacy-unknown'",
    "ALTER TABLE authority_operation ADD COLUMN correlation_id TEXT NOT NULL DEFAULT 'legacy-unknown'",
    "ALTER TABLE authority_operation ADD COLUMN causation_id TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE authority_operation ADD COLUMN command_payload JSONB NOT NULL DEFAULT '{}'::jsonb",
    "ALTER TABLE authority_operation ADD COLUMN approval_requirement_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb",
    "ALTER TABLE authority_operation ADD COLUMN input_asset_snapshot JSONB NOT NULL DEFAULT '[]'::jsonb",
    """
    ALTER TABLE authority_operation
    ADD CONSTRAINT authority_operation_input_assets_array_check
    CHECK (jsonb_typeof(input_asset_snapshot) = 'array')
    """,
    """
    CREATE TABLE authority_idempotency_record (
        idempotency_scope TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        request_digest TEXT NOT NULL,
        operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (idempotency_scope, idempotency_key),
        UNIQUE (operation_id)
    )
    """,
    "CREATE INDEX authority_operation_workspace_idx ON authority_operation(project_id, workspace_id, created_at DESC)",
    "CREATE INDEX authority_operation_concurrency_idx ON authority_operation(project_id, concurrency_key, status)",
]

DOWNGRADE_STATEMENTS: list[str] = []
