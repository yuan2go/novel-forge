from __future__ import annotations


MIGRATION_ID = "20260804_0067_activated_migration_archival_binding"
DOWN_REVISION = "20260804_0066_runtime_job_attempt_lease_existence"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = (
    "Restore the pre-0067 backup for full rollback. For an in-place repair, "
    "recover the immutable archival AssetVersion from each activation-bound "
    "Migration Validation, backfill the three archival evidence fields, and "
    "revalidate every activated DOMAIN_NATIVE item before release verification."
)


PREFLIGHT_STATEMENTS = [
    """
    WITH missing AS (
        SELECT item.*,
               COALESCE(
                   NULLIF(item.evidence#>>'{reconciliation,target_content_hash}', ''),
                   NULLIF(item.evidence->>'target_content_hash', '')
               ) AS archival_hash
        FROM authority_legacy_migration_item AS item
        WHERE item.status='ACTIVATED'
          AND item.target_materialization_level='DOMAIN_NATIVE'
          AND NULLIF(
              item.evidence->>'archival_target_asset_version_id', ''
          ) IS NULL
    ), candidates AS (
        SELECT missing.migration_item_id,
               validation.target_asset_version_id AS asset_version_id,
               1 AS priority
        FROM missing
        JOIN authority_legacy_migration_validation AS validation
          ON validation.migration_validation_id=
             missing.evidence->>'migration_validation_id'
         AND validation.migration_item_id=missing.migration_item_id
         AND validation.migration_run_id=missing.migration_run_id
        JOIN authority_asset_version AS version
          ON version.asset_version_id=validation.target_asset_version_id
         AND version.content_hash=missing.archival_hash
        JOIN authority_asset AS asset
          ON asset.asset_id=version.asset_id
         AND asset.project_id=missing.project_id
        UNION ALL
        SELECT missing.migration_item_id, output.asset_version_id, 2 AS priority
        FROM missing
        JOIN authority_operation_output_asset AS output
          ON output.operation_id=missing.operation_id
         AND output.content_hash=missing.archival_hash
        JOIN authority_asset AS asset
          ON asset.asset_id=output.asset_id
         AND asset.project_id=missing.project_id
        UNION ALL
        SELECT missing.migration_item_id, version.asset_version_id, 3 AS priority
        FROM missing
        JOIN authority_asset_version AS version
          ON version.asset_version_id=missing.target_asset_version_id
         AND version.content_hash=missing.archival_hash
        JOIN authority_asset AS asset
          ON asset.asset_id=version.asset_id
         AND asset.project_id=missing.project_id
    ), candidate_counts AS (
        SELECT migration_item_id, priority,
               COUNT(DISTINCT asset_version_id) AS candidate_count
        FROM candidates
        GROUP BY migration_item_id, priority
    ), preferred AS (
        SELECT DISTINCT ON (migration_item_id)
               migration_item_id, priority, candidate_count
        FROM candidate_counts
        ORDER BY migration_item_id, priority
    )
    SELECT 'activated_domain_item_without_unique_archival_binding', COUNT(*)
    FROM missing
    LEFT JOIN preferred
      ON preferred.migration_item_id=missing.migration_item_id
    WHERE missing.archival_hash IS NULL
       OR preferred.migration_item_id IS NULL
       OR preferred.candidate_count <> 1
    """,
]


UPGRADE_STATEMENTS = [
    """
    WITH missing AS (
        SELECT item.migration_item_id, item.migration_run_id,
               item.project_id, item.operation_id,
               item.target_asset_version_id, item.evidence,
               COALESCE(
                   NULLIF(item.evidence#>>'{reconciliation,target_content_hash}', ''),
                   NULLIF(item.evidence->>'target_content_hash', '')
               ) AS archival_hash
        FROM authority_legacy_migration_item AS item
        WHERE item.status='ACTIVATED'
          AND item.target_materialization_level='DOMAIN_NATIVE'
          AND NULLIF(
              item.evidence->>'archival_target_asset_version_id', ''
          ) IS NULL
    ), candidates AS (
        SELECT missing.migration_item_id, validation.target_asset_id AS asset_id,
               validation.target_asset_version_id AS asset_version_id,
               version.content_hash, 1 AS priority
        FROM missing
        JOIN authority_legacy_migration_validation AS validation
          ON validation.migration_validation_id=
             missing.evidence->>'migration_validation_id'
         AND validation.migration_item_id=missing.migration_item_id
         AND validation.migration_run_id=missing.migration_run_id
        JOIN authority_asset_version AS version
          ON version.asset_version_id=validation.target_asset_version_id
         AND version.content_hash=missing.archival_hash
        JOIN authority_asset AS asset
          ON asset.asset_id=version.asset_id
         AND asset.project_id=missing.project_id
        UNION ALL
        SELECT missing.migration_item_id, output.asset_id,
               output.asset_version_id, output.content_hash, 2 AS priority
        FROM missing
        JOIN authority_operation_output_asset AS output
          ON output.operation_id=missing.operation_id
         AND output.content_hash=missing.archival_hash
        JOIN authority_asset AS asset
          ON asset.asset_id=output.asset_id
         AND asset.project_id=missing.project_id
        UNION ALL
        SELECT missing.migration_item_id, version.asset_id,
               version.asset_version_id, version.content_hash, 3 AS priority
        FROM missing
        JOIN authority_asset_version AS version
          ON version.asset_version_id=missing.target_asset_version_id
         AND version.content_hash=missing.archival_hash
        JOIN authority_asset AS asset
          ON asset.asset_id=version.asset_id
         AND asset.project_id=missing.project_id
    ), candidate_counts AS (
        SELECT migration_item_id, priority,
               COUNT(DISTINCT asset_version_id) AS candidate_count
        FROM candidates
        GROUP BY migration_item_id, priority
    ), preferred AS (
        SELECT DISTINCT ON (migration_item_id)
               migration_item_id, priority, candidate_count
        FROM candidate_counts
        ORDER BY migration_item_id, priority
    ), recovered AS (
        SELECT DISTINCT ON (migration_item_id)
               candidates.migration_item_id, candidates.asset_id,
               candidates.asset_version_id, candidates.content_hash
        FROM candidates
        JOIN preferred
          ON preferred.migration_item_id=candidates.migration_item_id
         AND preferred.priority=candidates.priority
         AND preferred.candidate_count=1
        ORDER BY candidates.migration_item_id,
                 candidates.priority, candidates.asset_version_id
    )
    UPDATE authority_legacy_migration_item AS item
    SET evidence=item.evidence || jsonb_build_object(
            'archival_target_asset_id', recovered.asset_id,
            'archival_target_asset_version_id', recovered.asset_version_id,
            'archival_target_content_hash', recovered.content_hash,
            'archival_binding_recovered_by_migration',
                '20260804_0067_activated_migration_archival_binding'
        ),
        updated_at=NOW()
    FROM recovered
    WHERE recovered.migration_item_id=item.migration_item_id
    """,
    """
    ALTER TABLE authority_legacy_migration_item
    ADD CONSTRAINT authority_migration_item_archival_binding_check
    CHECK (
        status <> 'ACTIVATED'
        OR target_materialization_level <> 'DOMAIN_NATIVE'
        OR (
            NULLIF(evidence->>'archival_target_asset_id', '') IS NOT NULL
            AND NULLIF(evidence->>'archival_target_asset_version_id', '') IS NOT NULL
            AND NULLIF(evidence->>'archival_target_content_hash', '') IS NOT NULL
        )
    )
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []
