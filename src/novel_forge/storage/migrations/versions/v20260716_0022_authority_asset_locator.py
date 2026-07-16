from __future__ import annotations

MIGRATION_ID = "20260716_0022_authority_asset_locator"
DOWN_REVISION = "20260716_0021_saga_coordination"

UPGRADE_STATEMENTS = [
    "ALTER TABLE authority_asset ADD CONSTRAINT authority_asset_project_identity_unique UNIQUE (project_id, asset_id)",
    "ALTER TABLE authority_asset_version ADD CONSTRAINT authority_asset_version_asset_identity_unique UNIQUE (asset_id, asset_version_id)",
    """
    CREATE TABLE authority_asset_locator (
        project_id TEXT NOT NULL,
        logical_ref TEXT NOT NULL,
        category TEXT NOT NULL,
        asset_id TEXT NOT NULL,
        current_asset_version_id TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (project_id, logical_ref),
        UNIQUE (project_id, asset_id),
        FOREIGN KEY (project_id, asset_id)
            REFERENCES authority_asset(project_id, asset_id),
        FOREIGN KEY (asset_id, current_asset_version_id)
            REFERENCES authority_asset_version(asset_id, asset_version_id),
        CHECK (logical_ref <> '' AND logical_ref !~ '(^/|(^|/)\\.\\.?(/|$))'),
        CHECK (category <> '')
    )
    """,
    "CREATE INDEX authority_asset_locator_asset_id_idx ON authority_asset_locator(asset_id)",
    "CREATE INDEX authority_asset_locator_current_version_idx ON authority_asset_locator(current_asset_version_id)",
    "CREATE INDEX authority_asset_locator_asset_version_idx ON authority_asset_locator(asset_id, current_asset_version_id)",
    "CREATE INDEX authority_asset_locator_project_category_updated_idx ON authority_asset_locator(project_id, category, updated_at DESC, logical_ref)",
]

DOWNGRADE_STATEMENTS: list[str] = []
