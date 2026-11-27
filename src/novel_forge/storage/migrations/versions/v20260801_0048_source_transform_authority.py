from __future__ import annotations

MIGRATION_ID = "20260801_0048_source_transform_authority"
DOWN_REVISION = "20260801_0047_candidate_asset_lifecycle"


UPGRADE_STATEMENTS = [
    """
    CREATE TABLE authority_source_transform (
        source_transform_id TEXT PRIMARY KEY REFERENCES authority_asset(asset_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        workspace_id TEXT NOT NULL REFERENCES authority_workspace(workspace_id),
        source_document_id TEXT NOT NULL
            REFERENCES authority_source_document(source_document_id),
        source_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        asset_version_id TEXT NOT NULL UNIQUE
            REFERENCES authority_asset_version(asset_version_id),
        created_by_operation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_operation(operation_id),
        normalization_version TEXT NOT NULL,
        chunking_version TEXT NOT NULL,
        chunking_policy_hash TEXT NOT NULL,
        manifest_hash TEXT NOT NULL,
        chunk_count INTEGER NOT NULL,
        total_chunk_bytes BIGINT NOT NULL,
        status TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(source_asset_version_id, chunking_policy_hash, manifest_hash),
        CHECK (chunk_count > 0),
        CHECK (total_chunk_bytes > 0),
        CHECK (status IN ('ACTIVE', 'SUPERSEDED', 'ROLLED_BACK'))
    )
    """,
    """
    CREATE UNIQUE INDEX authority_source_transform_one_active_idx
    ON authority_source_transform(source_document_id)
    WHERE status = 'ACTIVE'
    """,
    """
    CREATE INDEX authority_source_transform_project_idx
    ON authority_source_transform(project_id, created_at DESC)
    """,
    """
    CREATE INDEX authority_source_transform_source_version_idx
    ON authority_source_transform(source_asset_version_id, created_at DESC)
    """,
    """
    CREATE TABLE authority_source_chunk (
        source_chunk_id TEXT PRIMARY KEY REFERENCES authority_asset(asset_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        workspace_id TEXT NOT NULL REFERENCES authority_workspace(workspace_id),
        source_transform_id TEXT NOT NULL
            REFERENCES authority_source_transform(source_transform_id),
        source_document_id TEXT NOT NULL
            REFERENCES authority_source_document(source_document_id),
        asset_version_id TEXT NOT NULL UNIQUE
            REFERENCES authority_asset_version(asset_version_id),
        blob_id TEXT NOT NULL UNIQUE REFERENCES authority_blob(blob_id),
        chunk_index INTEGER NOT NULL,
        content_hash TEXT NOT NULL,
        byte_size BIGINT NOT NULL,
        character_count INTEGER NOT NULL,
        token_count INTEGER NOT NULL,
        source_byte_start BIGINT NOT NULL,
        source_byte_end BIGINT NOT NULL,
        created_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(source_transform_id, chunk_index),
        CHECK (chunk_index >= 0),
        CHECK (byte_size > 0),
        CHECK (character_count > 0),
        CHECK (token_count > 0),
        CHECK (source_byte_start >= 0),
        CHECK (source_byte_end > source_byte_start)
    )
    """,
    """
    CREATE INDEX authority_source_chunk_source_idx
    ON authority_source_chunk(source_document_id, created_at DESC)
    """,
    """
    CREATE INDEX authority_source_chunk_transform_idx
    ON authority_source_chunk(source_transform_id, chunk_index)
    """,
    """
    CREATE INDEX authority_source_chunk_operation_idx
    ON authority_source_chunk(created_by_operation_id)
    """,
]


# Forward-only: source Blob references and immutable AssetVersions require the
# backup/restore and object reconciliation runbook rather than destructive down SQL.
DOWNGRADE_STATEMENTS: list[str] = []
