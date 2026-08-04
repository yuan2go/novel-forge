from __future__ import annotations


MIGRATION_ID = "20260804_0059_migration_validation_authority"
DOWN_REVISION = "20260804_0058_authority_cutover_release_qualification"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = (
    "Restore the pre-0059 backup for a full rollback. For an in-place repair, "
    "retain immutable migration items and decisions, recreate the additive "
    "validation aggregate, and rerun server-side validation before approval."
)


PREFLIGHT_STATEMENTS = [
    """
    SELECT 'missing_legacy_migration_item',
           CASE WHEN to_regclass('authority_legacy_migration_item') IS NULL
                THEN 1 ELSE 0 END
    """,
    """
    SELECT 'missing_legacy_migration_decision',
           CASE WHEN to_regclass('authority_legacy_migration_decision') IS NULL
                THEN 1 ELSE 0 END
    """,
]


UPGRADE_STATEMENTS = [
    """
    CREATE TABLE authority_legacy_migration_validation (
        migration_validation_id TEXT PRIMARY KEY,
        migration_run_id TEXT NOT NULL
            REFERENCES authority_migration_run(migration_run_id),
        migration_item_id TEXT NOT NULL
            REFERENCES authority_legacy_migration_item(migration_item_id),
        validation_version BIGINT NOT NULL,
        item_version BIGINT NOT NULL,
        source_hash TEXT NOT NULL,
        target_asset_id TEXT NOT NULL
            REFERENCES authority_asset(asset_id),
        target_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        target_materialization_level TEXT NOT NULL,
        domain_adapter TEXT NOT NULL,
        validator_name TEXT NOT NULL,
        validator_version TEXT NOT NULL,
        validator_implementation_hash TEXT NOT NULL,
        input_hash TEXT NOT NULL,
        result_hash TEXT NOT NULL,
        reference_snapshot_hash TEXT NOT NULL,
        dependency_projection_hash TEXT NOT NULL,
        status TEXT NOT NULL,
        evidence JSONB NOT NULL,
        validated_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        validated_by_actor_id TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(migration_item_id, validation_version),
        UNIQUE(migration_item_id, item_version, validator_implementation_hash),
        CHECK (validation_version > 0 AND item_version >= 0),
        CHECK (source_hash LIKE 'sha256:%'),
        CHECK (validator_name <> '' AND validator_version <> ''),
        CHECK (validator_implementation_hash LIKE 'sha256:%'),
        CHECK (input_hash LIKE 'sha256:%' AND result_hash LIKE 'sha256:%'),
        CHECK (reference_snapshot_hash LIKE 'sha256:%'),
        CHECK (dependency_projection_hash LIKE 'sha256:%'),
        CHECK (target_materialization_level IN ('ARCHIVAL_NATIVE','DOMAIN_NATIVE')),
        CHECK (domain_adapter <> '' AND validated_by_actor_id <> ''),
        CHECK (status IN ('PASS','FAIL','STALE','REVOKED'))
    )
    """,
    """
    CREATE INDEX authority_legacy_migration_validation_run_fk_idx
    ON authority_legacy_migration_validation(migration_run_id)
    """,
    """
    CREATE INDEX authority_legacy_migration_validation_item_latest_idx
    ON authority_legacy_migration_validation(
        migration_item_id, validation_version DESC, created_at DESC
    ) WHERE status='PASS'
    """,
    """
    CREATE INDEX authority_legacy_migration_validation_target_asset_fk_idx
    ON authority_legacy_migration_validation(target_asset_id)
    """,
    """
    CREATE INDEX authority_legacy_migration_validation_target_version_fk_idx
    ON authority_legacy_migration_validation(target_asset_version_id)
    """,
    """
    CREATE INDEX authority_legacy_migration_validation_operation_fk_idx
    ON authority_legacy_migration_validation(validated_by_operation_id)
    """,
    """
    ALTER TABLE authority_legacy_migration_decision
        ADD COLUMN migration_validation_id TEXT
            REFERENCES authority_legacy_migration_validation(migration_validation_id),
        ADD COLUMN validation_result_hash TEXT NOT NULL DEFAULT ''
    """,
    """
    ALTER TABLE authority_legacy_migration_decision
        ADD CONSTRAINT authority_legacy_migration_decision_validation_binding_check
        CHECK (
            decision <> 'APPROVE'
            OR (
                migration_validation_id IS NOT NULL
                AND validation_result_hash LIKE 'sha256:%'
            )
        ) NOT VALID
    """,
    """
    CREATE INDEX authority_legacy_migration_decision_validation_fk_idx
    ON authority_legacy_migration_decision(migration_validation_id)
    WHERE migration_validation_id IS NOT NULL
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []
