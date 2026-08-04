from __future__ import annotations


MIGRATION_ID = "20260804_0060_migration_completion_semantics"
DOWN_REVISION = "20260804_0059_migration_validation_authority"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = (
    "Restore the pre-0060 backup for a full rollback. For an in-place repair, "
    "retain immutable migration evidence and rebuild the additive archival, "
    "domain, validation-scope, and run-completion projections from source rows."
)


PREFLIGHT_STATEMENTS = [
    """
    SELECT 'missing_migration_run',
           CASE WHEN to_regclass('authority_migration_run') IS NULL
                THEN 1 ELSE 0 END
    """,
    """
    SELECT 'missing_migration_item',
           CASE WHEN to_regclass('authority_legacy_migration_item') IS NULL
                THEN 1 ELSE 0 END
    """,
]


UPGRADE_STATEMENTS = [
    """
    ALTER TABLE authority_migration_run
        DROP CONSTRAINT authority_migration_run_status_check
    """,
    """
    ALTER TABLE authority_migration_run
        ADD COLUMN run_completion_level TEXT NOT NULL DEFAULT 'NONE',
        ADD COLUMN required_verification_level TEXT NOT NULL DEFAULT 'ARCHIVAL_NATIVE',
        ADD CONSTRAINT authority_migration_run_completion_level_check CHECK (
            run_completion_level IN (
                'NONE','ARCHIVAL_RECONCILED','DOMAIN_RECONCILED','RELEASE_READY'
            )
        ),
        ADD CONSTRAINT authority_migration_run_verification_level_check CHECK (
            required_verification_level IN (
                'ARCHIVAL_NATIVE','DOMAIN_NATIVE','RELEASE_READY'
            )
        )
    """,
    """
    UPDATE authority_migration_run
    SET status = CASE status
        WHEN 'RUNNING' THEN 'IMPORT_RUNNING'
        WHEN 'FAILED' THEN 'FAILED'
        WHEN 'CANCELLED' THEN 'CANCELLED'
        WHEN 'QUARANTINED' THEN 'QUARANTINED'
        ELSE 'ARCHIVAL_RECONCILED'
    END,
    run_completion_level = CASE
        WHEN status IN ('SUCCEEDED','VALIDATING') THEN 'ARCHIVAL_RECONCILED'
        ELSE 'NONE'
    END
    """,
    """
    ALTER TABLE authority_migration_run
        ADD CONSTRAINT authority_migration_run_status_check CHECK (status IN (
            'IMPORT_RUNNING','ARCHIVAL_RECONCILED','DOMAIN_REVIEW_PENDING',
            'DOMAIN_ACTIVATION_PARTIAL','DOMAIN_RECONCILED','QUARANTINED',
            'FAILED','CANCELLED'
        ))
    """,
    """
    ALTER TABLE authority_legacy_migration_item
        ADD COLUMN materialization_stage TEXT NOT NULL DEFAULT 'ARCHIVAL',
        ADD COLUMN archival_state TEXT NOT NULL DEFAULT 'DISCOVERED',
        ADD COLUMN domain_state TEXT NOT NULL DEFAULT 'DOMAIN_NOT_APPLICABLE',
        ADD COLUMN validation_scope TEXT NOT NULL DEFAULT 'ARCHIVAL',
        ADD CONSTRAINT authority_legacy_migration_item_stage_check CHECK (
            materialization_stage IN ('ARCHIVAL','DOMAIN')
        ),
        ADD CONSTRAINT authority_legacy_migration_item_archival_state_check CHECK (
            archival_state IN (
                'DISCOVERED','CLASSIFIED','ARCHIVAL_IMPORTED','ARCHIVAL_VALIDATED',
                'REFERENCES_PENDING','REFERENCES_RESOLVED','ARCHIVAL_RECONCILED'
            )
        ),
        ADD CONSTRAINT authority_legacy_migration_item_domain_state_check CHECK (
            domain_state IN (
                'DOMAIN_NOT_APPLICABLE','DOMAIN_VALIDATION_PENDING',
                'DOMAIN_VALIDATED','DOMAIN_VALIDATION_FAILED',
                'DOMAIN_DECISION_PENDING','DOMAIN_APPROVED','DOMAIN_REJECTED',
                'DOMAIN_ACTIVATION_PENDING','DOMAIN_ACTIVATED',
                'DOMAIN_RECONCILED','DOMAIN_RECONCILIATION_FAILED'
            )
        ),
        ADD CONSTRAINT authority_legacy_migration_item_validation_scope_check CHECK (
            validation_scope IN ('ARCHIVAL','DOMAIN')
        )
    """,
    """
    UPDATE authority_legacy_migration_item
    SET materialization_stage = CASE
            WHEN materialization_level='DOMAIN_NATIVE' THEN 'DOMAIN'
            ELSE 'ARCHIVAL'
        END,
        archival_state = CASE
            WHEN reference_count > 0 AND reference_state='UNRESOLVED'
                THEN 'REFERENCES_PENDING'
            WHEN reference_count > 0 AND reference_state='RESOLVED'
                THEN 'REFERENCES_RESOLVED'
            WHEN target_asset_version_id IS NOT NULL
                THEN 'ARCHIVAL_VALIDATED'
            WHEN phase IN ('CLASSIFY','IMPORT_CANDIDATE') THEN 'CLASSIFIED'
            ELSE 'DISCOVERED'
        END,
        domain_state = CASE
            WHEN target_materialization_level <> 'DOMAIN_NATIVE'
                THEN 'DOMAIN_NOT_APPLICABLE'
            WHEN status='ACTIVATED' THEN 'DOMAIN_ACTIVATED'
            WHEN status='QUALIFIED' THEN 'DOMAIN_ACTIVATION_PENDING'
            WHEN status='INELIGIBLE' THEN 'DOMAIN_REJECTED'
            ELSE 'DOMAIN_VALIDATION_PENDING'
        END,
        validation_scope = CASE
            WHEN target_materialization_level='DOMAIN_NATIVE' THEN 'DOMAIN'
            ELSE 'ARCHIVAL'
        END
    """,
    """
    CREATE INDEX authority_migration_run_completion_query_idx
    ON authority_migration_run(
        status, run_completion_level, updated_at DESC, migration_run_id
    )
    """,
    """
    CREATE INDEX authority_legacy_migration_item_domain_resume_idx
    ON authority_legacy_migration_item(
        migration_run_id, domain_state, item_version, updated_at, migration_item_id
    ) WHERE domain_state NOT IN ('DOMAIN_NOT_APPLICABLE','DOMAIN_RECONCILED')
    """,
    """
    CREATE INDEX authority_legacy_migration_item_archival_resume_idx
    ON authority_legacy_migration_item(
        migration_run_id, archival_state, updated_at, migration_item_id
    ) WHERE archival_state <> 'ARCHIVAL_RECONCILED'
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []
