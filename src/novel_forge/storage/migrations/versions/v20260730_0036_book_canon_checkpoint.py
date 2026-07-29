from __future__ import annotations

MIGRATION_ID = "20260730_0036_book_canon_checkpoint"
DOWN_REVISION = "20260730_0035_book_child_delegation"

UPGRADE_STATEMENTS = [
    """
    ALTER TABLE authority_book_production
    ADD COLUMN active_canon_snapshot_version_id TEXT
        REFERENCES authority_asset_version(asset_version_id)
    """,
    """
    CREATE INDEX authority_book_canon_snapshot_fk_idx
    ON authority_book_production(active_canon_snapshot_version_id)
    """,
    """
    ALTER TABLE authority_book_chapter_acceptance
    ADD COLUMN canon_snapshot_asset_version_id TEXT
        REFERENCES authority_asset_version(asset_version_id)
    """,
    """
    UPDATE authority_book_chapter_acceptance AS acceptance
    SET canon_snapshot_asset_version_id=state.asset_version_id
    FROM (
        SELECT DISTINCT ON (delegation.delegation_id)
               delegation.delegation_id,
               binding.asset_version_id
        FROM authority_child_delegation AS delegation
        JOIN authority_operation AS operation
          ON operation.root_operation_id=delegation.child_root_operation_id
         AND operation.project_id=delegation.project_id
        JOIN authority_operation_output_asset AS binding
          ON binding.operation_id=operation.operation_id
         AND binding.role='state_snapshot'
        JOIN authority_asset AS asset
          ON asset.asset_id=binding.asset_id
         AND asset.asset_type='canon_snapshot'
        ORDER BY delegation.delegation_id, binding.created_at DESC
    ) AS state
    WHERE state.delegation_id=acceptance.delegation_id
    """,
    """
    ALTER TABLE authority_book_chapter_acceptance
    ALTER COLUMN canon_snapshot_asset_version_id SET NOT NULL
    """,
    """
    CREATE UNIQUE INDEX authority_book_acceptance_canon_snapshot_idx
    ON authority_book_chapter_acceptance(canon_snapshot_asset_version_id)
    """,
]

# Authority acceptance and state checkpoints are append-only. Repair is
# roll-forward so historical lineage is never destructively removed.
DOWNGRADE_STATEMENTS: list[str] = []
