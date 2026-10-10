from __future__ import annotations

MIGRATION_ID = '20261010_0196_recovery_reference_indexes'
DOWN_REVISION = "20261009_0195_prose_review_generation_isolation"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Index recovery and source-market foreign-key references without changing historical facts or admission rules."

UPGRADE_STATEMENTS = [
    'CREATE INDEX authority_child_delegation_delivery_operation_idx ON authority_child_delegation (delivered_by_operation_id)',
    'CREATE INDEX authority_generation_isolation_operation_idx ON authority_generation_isolation (operation_id)',
    'CREATE INDEX authority_generation_isolation_materialization_idx ON authority_generation_isolation (materialization_asset_version_id)',
    'CREATE INDEX authority_source_market_definition_previous_idx ON authority_source_market_definition (project_id,previous_definition_id)',
    'CREATE INDEX authority_source_market_edition_book_source_idx ON authority_source_market_edition_link (project_id,source_id,book_source_id)',
    'CREATE INDEX authority_source_market_metadata_book_source_idx ON authority_source_market_metadata (project_id,source_id,book_source_id)',
]
DOWNGRADE_STATEMENTS: list[str] = []
