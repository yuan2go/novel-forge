from __future__ import annotations


MIGRATION_ID = "20260804_0061_structured_migration_references"
DOWN_REVISION = "20260804_0060_migration_completion_semantics"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = (
    "Restore the pre-0061 backup for a full rollback. For an in-place repair, "
    "retain resolved reference targets, rebuild structured contracts from the "
    "frozen snapshot, and quarantine any edge whose type or hash no longer matches."
)


PREFLIGHT_STATEMENTS = [
    """
    SELECT 'missing_migration_reference',
           CASE WHEN to_regclass('authority_legacy_migration_reference') IS NULL
                THEN 1 ELSE 0 END
    """,
]


UPGRADE_STATEMENTS = [
    """
    ALTER TABLE authority_legacy_migration_reference
        ADD COLUMN expected_source_type TEXT NOT NULL DEFAULT '',
        ADD COLUMN expected_target_asset_type TEXT NOT NULL DEFAULT '',
        ADD COLUMN expected_content_hash TEXT NOT NULL DEFAULT '',
        ADD COLUMN cardinality TEXT NOT NULL DEFAULT 'MANY',
        ADD COLUMN compatibility_evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
        ADD CONSTRAINT authority_legacy_migration_reference_expected_hash_check
            CHECK (
                expected_content_hash=''
                OR expected_content_hash LIKE 'sha256:%'
            ),
        ADD CONSTRAINT authority_legacy_migration_reference_cardinality_check
            CHECK (cardinality IN ('ONE','MANY'))
    """,
    """
    UPDATE authority_legacy_migration_reference
    SET relation_type='RELATED_ASSET',
        compatibility_evidence=jsonb_build_object(
            'input_format','LEGACY_STRING_V1',
            'normalized_relation_type','RELATED_ASSET',
            'legacy_string_compatibility',TRUE
        )
    WHERE relation_type='LEGACY_REFERENCE'
    """,
    """
    ALTER TABLE authority_legacy_migration_reference
        ADD CONSTRAINT authority_legacy_migration_reference_relation_type_check
            CHECK (relation_type IN (
                'BOOK_DESIGN_OF_BOOK','PARENT_PLAN','ARC_OVERLAY',
                'KNOWLEDGE_PACK_ITEM','KNOWLEDGE_PACK_TARGET','SOURCE_EVIDENCE',
                'CANON_DEPENDENCY','CONTEXT_INPUT','RELATED_ASSET',
                'OPTIONAL_REFERENCE'
            ))
    """,
    """
    CREATE UNIQUE INDEX authority_legacy_migration_reference_one_cardinality_idx
    ON authority_legacy_migration_reference(source_item_id, relation_type)
    WHERE cardinality='ONE'
    """,
    """
    CREATE INDEX authority_legacy_migration_reference_dependency_graph_idx
    ON authority_legacy_migration_reference(
        migration_run_id, source_item_id, target_item_id, relation_type
    ) WHERE resolution_status='RESOLVED'
    """,
    """
    CREATE INDEX authority_legacy_migration_reference_expected_type_idx
    ON authority_legacy_migration_reference(
        migration_run_id, expected_source_type, expected_target_asset_type,
        resolution_status
    )
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []
