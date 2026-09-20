from __future__ import annotations

MIGRATION_ID = "20260920_0138_narrative_craft_origin"
DOWN_REVISION = "20260920_0137_opening_delete_fence"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = "Preserve Source execution requirements while admitting explicitly governed repository original Craft candidates."

UPGRADE_STATEMENTS = [
    """
    ALTER TABLE authority_mkaos_knowledge_candidate
      ALTER COLUMN execution_asset_version_id DROP NOT NULL,
      ADD COLUMN origin_kind TEXT NOT NULL DEFAULT 'SOURCE_ABSTRACTION',
      ADD COLUMN craft_mechanism_id TEXT,
      ADD COLUMN craft_mechanism_version INTEGER,
      ADD COLUMN craft_mechanism_hash TEXT,
      ADD CONSTRAINT authority_mkaos_candidate_origin_ck CHECK (
        (origin_kind = 'SOURCE_ABSTRACTION' AND execution_asset_version_id IS NOT NULL)
        OR (origin_kind = 'REPOSITORY_ORIGINAL' AND execution_asset_version_id IS NULL
            AND craft_mechanism_id IS NOT NULL)
      ),
      ADD CONSTRAINT authority_mkaos_candidate_craft_identity_ck CHECK (
        (craft_mechanism_id IS NULL AND craft_mechanism_version IS NULL AND craft_mechanism_hash IS NULL)
        OR (craft_mechanism_id IS NOT NULL AND craft_mechanism_id ~ '^[a-z][a-z0-9-]{2,79}$'
            AND craft_mechanism_version IS NOT NULL
            AND craft_mechanism_hash IS NOT NULL AND craft_mechanism_version > 0
            AND craft_mechanism_hash ~ '^sha256:[0-9a-f]{64}$')
      )
    """,
    """
    CREATE UNIQUE INDEX authority_mkaos_candidate_craft_version_idx
      ON authority_mkaos_knowledge_candidate(project_id, craft_mechanism_id, craft_mechanism_version)
      WHERE craft_mechanism_id IS NOT NULL
    """,
]
