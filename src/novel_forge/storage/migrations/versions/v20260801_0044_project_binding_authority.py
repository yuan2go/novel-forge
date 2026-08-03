from __future__ import annotations

MIGRATION_ID = "20260801_0044_project_binding_authority"
DOWN_REVISION = "20260801_0043_project_workspace_and_legacy_migration_authority"


UPGRADE_STATEMENTS = [
    """
    ALTER TABLE authority_project_binding
    ADD COLUMN binding_asset_version_id TEXT NOT NULL UNIQUE
        REFERENCES authority_asset_version(asset_version_id)
    """,
    """
    CREATE INDEX authority_project_binding_asset_version_fk_idx
    ON authority_project_binding(binding_asset_version_id)
    """,
]


# Forward-only: Project binding decisions are immutable audit evidence. Restore
# follows the Authority backup/rehearsal runbook instead of deleting decisions.
DOWNGRADE_STATEMENTS: list[str] = []
