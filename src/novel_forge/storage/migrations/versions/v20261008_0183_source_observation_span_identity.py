from __future__ import annotations

MIGRATION_ID = "20261008_0183_source_observation_span_identity"
DOWN_REVISION = "20261008_0182_source_market_observations"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Retain every original observation and span; append a correction to evidence identity."

UPGRADE_STATEMENTS = [
    """
    DO $$ DECLARE existing TEXT; BEGIN
        SELECT conname INTO STRICT existing FROM pg_constraint
        WHERE conrelid='authority_source_deconstruction_observation_input'::regclass
          AND contype='u'
          AND pg_get_constraintdef(oid)=
              'UNIQUE (observation_asset_version_id, input_asset_version_id, role)';
        EXECUTE format(
            'ALTER TABLE authority_source_deconstruction_observation_input DROP CONSTRAINT %I',
            existing
        );
    END $$
    """,
    """
    CREATE UNIQUE INDEX authority_source_observation_span_identity_idx
    ON authority_source_deconstruction_observation_input(
        observation_asset_version_id,input_asset_version_id,role,evidence_span_id
    ) WHERE role='SOURCE_CHUNK_EVIDENCE'
    """,
    """
    CREATE UNIQUE INDEX authority_source_observation_asset_identity_idx
    ON authority_source_deconstruction_observation_input(
        observation_asset_version_id,input_asset_version_id,role
    ) WHERE role<>'SOURCE_CHUNK_EVIDENCE'
    """,
]
