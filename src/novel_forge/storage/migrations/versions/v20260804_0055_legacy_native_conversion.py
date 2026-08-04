from __future__ import annotations

MIGRATION_ID = "20260804_0055_legacy_native_conversion"
DOWN_REVISION = "20260804_0054_scope_foreign_key_indexes"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = (
    "restore the pre-0055 database backup and replay the frozen snapshot; "
    "native AssetVersions are immutable and remain traceable by migration item"
)

UPGRADE_STATEMENTS = [
    """
    ALTER TABLE authority_legacy_migration_item
    DROP CONSTRAINT authority_legacy_migration_it_migration_run_id_stable_busin_key
    """,
    """
    ALTER TABLE authority_migration_run
        ADD COLUMN phase TEXT NOT NULL DEFAULT 'SCAN',
        ADD COLUMN reconciliation JSONB NOT NULL DEFAULT '{}'::jsonb,
        ADD COLUMN checkpoint_hash TEXT NOT NULL DEFAULT '',
        ADD CONSTRAINT authority_migration_run_phase_check CHECK (phase IN (
            'SCAN', 'CLASSIFY', 'IMPORT_CANDIDATE', 'SEMANTIC_CONVERT',
            'VALIDATE', 'QUALIFY', 'ACTIVATE', 'QUARANTINE', 'RECONCILE'
        ))
    """,
    """
    ALTER TABLE authority_legacy_migration_item
        ADD COLUMN source_asset_type TEXT NOT NULL DEFAULT 'unknown',
        ADD COLUMN target_asset_type TEXT NOT NULL DEFAULT '',
        ADD COLUMN codec_name TEXT NOT NULL DEFAULT '',
        ADD COLUMN codec_version TEXT NOT NULL DEFAULT '',
        ADD COLUMN phase TEXT NOT NULL DEFAULT 'SCAN',
        ADD COLUMN target_content_hash TEXT NOT NULL DEFAULT '',
        ADD COLUMN reference_count INTEGER NOT NULL DEFAULT 0,
        ADD COLUMN reconciliation JSONB NOT NULL DEFAULT '{}'::jsonb,
        ADD CONSTRAINT authority_legacy_migration_item_reference_count_check
            CHECK (reference_count >= 0),
        ADD CONSTRAINT authority_legacy_migration_item_phase_check CHECK (phase IN (
            'SCAN', 'CLASSIFY', 'IMPORT_CANDIDATE', 'SEMANTIC_CONVERT',
            'VALIDATE', 'QUALIFY', 'ACTIVATE', 'QUARANTINE', 'RECONCILE'
        ))
    """,
    """
    ALTER TABLE authority_legacy_migration_item
        DROP CONSTRAINT authority_legacy_migration_item_status_check,
        ADD CONSTRAINT authority_legacy_migration_item_status_check CHECK (status IN (
            'DISCOVERED', 'VALIDATED', 'IMPORTED', 'QUALIFIED', 'ACTIVATED',
            'NEEDS_REVIEW', 'QUARANTINED', 'INELIGIBLE',
            'SKIPPED_DUPLICATE', 'FAILED'
        )),
        DROP CONSTRAINT authority_legacy_migration_item_decision_check,
        ADD CONSTRAINT authority_legacy_migration_item_decision_check CHECK (decision IN (
            'PENDING', 'IMPORT', 'MIGRATE_NATIVE', 'REBUILD',
            'DISCARD_REBUILDABLE', 'QUARANTINE', 'REJECT'
        ))
    """,
    """
    ALTER TABLE authority_data_quarantine
        ADD COLUMN source_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        ADD COLUMN object_reference JSONB NOT NULL DEFAULT '{}'::jsonb,
        ADD COLUMN source_size_bytes BIGINT NOT NULL DEFAULT 0,
        ADD CONSTRAINT authority_data_quarantine_source_size_check
            CHECK (source_size_bytes >= 0)
    """,
    """
    CREATE INDEX authority_legacy_migration_item_phase_resume_idx
    ON authority_legacy_migration_item(
        migration_run_id, phase, status, updated_at, migration_item_id
    )
    """,
    """
    CREATE INDEX authority_legacy_migration_item_business_identity_idx
    ON authority_legacy_migration_item(
        project_id, target_asset_type, stable_business_key, source_hash
    ) WHERE target_asset_version_id IS NOT NULL
    """,
    """
    CREATE INDEX authority_legacy_migration_item_source_type_idx
    ON authority_legacy_migration_item(source_asset_type, status, updated_at DESC)
    """,
]

DOWNGRADE_STATEMENTS: list[str] = []
