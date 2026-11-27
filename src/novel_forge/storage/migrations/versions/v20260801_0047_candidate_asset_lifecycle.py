from __future__ import annotations

MIGRATION_ID = "20260801_0047_candidate_asset_lifecycle"
DOWN_REVISION = "20260801_0046_source_document_authority"


UPGRADE_STATEMENTS = [
    """
    ALTER TABLE authority_asset_version
    DROP CONSTRAINT authority_asset_version_lifecycle_check
    """,
    """
    ALTER TABLE authority_asset_version
    ADD CONSTRAINT authority_asset_version_lifecycle_check
    CHECK (lifecycle IN (
        'DRAFT', 'CANDIDATE', 'IMPORTED', 'ACTIVE',
        'SUPERSEDED', 'RETIRED', 'DELETED'
    ))
    """,
    """
    CREATE INDEX IF NOT EXISTS authority_source_document_operation_idx
    ON authority_source_document(created_by_operation_id)
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []
