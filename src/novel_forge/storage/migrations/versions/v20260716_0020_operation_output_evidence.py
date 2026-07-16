from __future__ import annotations

MIGRATION_ID = "20260716_0020_operation_output_evidence"
DOWN_REVISION = "20260716_0019_external_effect_protocol"

UPGRADE_STATEMENTS = [
    """
    CREATE TABLE authority_operation_output_asset (
        operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        asset_id TEXT NOT NULL REFERENCES authority_asset(asset_id),
        asset_version_id TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        output_key TEXT NOT NULL,
        role TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY(operation_id, output_key, role, asset_version_id),
        CHECK (output_key <> ''),
        CHECK (role <> ''),
        CHECK (content_hash <> '')
    )
    """,
    "CREATE INDEX authority_operation_output_asset_version_idx ON authority_operation_output_asset(asset_version_id, operation_id)",
    "CREATE INDEX authority_operation_output_asset_asset_idx ON authority_operation_output_asset(asset_id, operation_id)",
    "CREATE INDEX authority_operation_output_asset_key_idx ON authority_operation_output_asset(operation_id, output_key, role)",
]

DOWNGRADE_STATEMENTS: list[str] = []
