from __future__ import annotations

MIGRATION_ID = "20260801_0049_source_transform_fk_indexes"
DOWN_REVISION = "20260801_0048_source_transform_authority"


UPGRADE_STATEMENTS = [
    """
    CREATE INDEX authority_source_transform_workspace_idx
    ON authority_source_transform(workspace_id, created_at DESC)
    """,
    """
    CREATE INDEX authority_source_chunk_project_idx
    ON authority_source_chunk(project_id, created_at DESC)
    """,
    """
    CREATE INDEX authority_source_chunk_workspace_idx
    ON authority_source_chunk(workspace_id, created_at DESC)
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []
