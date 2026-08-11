from __future__ import annotations


MIGRATION_ID = "20260811_0080_source_snapshot_governance_identity"
DOWN_REVISION = "20260811_0079_source_import_scope_closure"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "repair the frozen rights payload before retrying the migration"


UPGRADE_STATEMENTS = [
    """
    ALTER TABLE authority_source_repository_snapshot
      ADD COLUMN governance_policy_hash TEXT
    """,
    """
    UPDATE authority_source_repository_snapshot AS snapshot
    SET governance_policy_hash =
        'sha256:' || encode(
          digest(
            convert_to(
              COALESCE(version.content->'rights', '{}'::jsonb)::text,
              'UTF8'
            ),
            'sha256'
          ),
          'hex'
        )
    FROM authority_asset_version AS version
    WHERE version.asset_version_id=snapshot.asset_version_id
      AND snapshot.governance_policy_hash IS NULL
    """,
    """
    ALTER TABLE authority_source_repository_snapshot
      ALTER COLUMN governance_policy_hash SET NOT NULL,
      ADD CONSTRAINT authority_source_repository_snapshot_governance_hash_check
        CHECK (governance_policy_hash ~ '^sha256:[0-9a-f]{64}$'),
      DROP CONSTRAINT
        authority_source_repository_s_project_id_repository_identit_key,
      ADD CONSTRAINT authority_source_repository_snapshot_identity_key
        UNIQUE(
          project_id, repository_identity, resolved_commit_sha,
          import_policy_hash, governance_policy_hash
        )
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []
