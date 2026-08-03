from __future__ import annotations

MIGRATION_ID = "20260801_0046_source_document_authority"
DOWN_REVISION = "20260801_0045_task_recovery_authority"


UPGRADE_STATEMENTS = [
    """
    CREATE TABLE authority_source_document (
        source_document_id TEXT PRIMARY KEY REFERENCES authority_asset(asset_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        workspace_id TEXT NOT NULL REFERENCES authority_workspace(workspace_id),
        asset_version_id TEXT NOT NULL UNIQUE
            REFERENCES authority_asset_version(asset_version_id),
        blob_id TEXT NOT NULL REFERENCES authority_blob(blob_id),
        source_content_hash TEXT NOT NULL,
        source_size BIGINT NOT NULL,
        media_type TEXT NOT NULL,
        title TEXT NOT NULL,
        source_kind TEXT NOT NULL,
        source_uri TEXT NOT NULL DEFAULT '',
        rights_authorization TEXT NOT NULL,
        license_name TEXT NOT NULL DEFAULT '',
        copyright_boundary TEXT NOT NULL DEFAULT '',
        governance_status TEXT NOT NULL,
        created_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, source_content_hash),
        CHECK (source_size >= 0),
        CHECK (media_type ~ '^[a-z0-9.+-]+/[a-z0-9.+-]+$'),
        CHECK (rights_authorization IN (
            'owned', 'licensed', 'public_domain', 'permission_granted',
            'test_fixture', 'unknown', 'forbidden', 'pirated',
            'infringing', 'private'
        )),
        CHECK (governance_status IN (
            'ELIGIBLE', 'NEEDS_REVIEW', 'QUARANTINED', 'INELIGIBLE'
        ))
    )
    """,
    """
    CREATE INDEX authority_source_document_project_status_idx
    ON authority_source_document(project_id, governance_status, created_at DESC)
    """,
    """
    CREATE INDEX authority_source_document_workspace_idx
    ON authority_source_document(workspace_id, created_at DESC)
    """,
    """
    CREATE INDEX authority_source_document_blob_idx
    ON authority_source_document(blob_id)
    """,
    """
    CREATE INDEX authority_source_document_operation_idx
    ON authority_source_document(created_by_operation_id)
    """,
]


# Forward-only governance evidence. Restore follows the Authority backup and
# immutable-object reconciliation procedure.
DOWNGRADE_STATEMENTS: list[str] = []
