from __future__ import annotations

MIGRATION_ID = "20260625_0001_initial_industrial_schema"
DOWN_REVISION: str | None = None

UPGRADE_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS nf_schema_migrations (
        migration_id TEXT PRIMARY KEY,
        applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS nf_assets (
        path TEXT PRIMARY KEY,
        category TEXT NOT NULL,
        asset_id TEXT NOT NULL,
        asset_type TEXT NOT NULL,
        title TEXT NOT NULL,
        source TEXT NOT NULL,
        project_id TEXT NOT NULL DEFAULT '',
        workspace_path TEXT NOT NULL DEFAULT '',
        tags TEXT[] NOT NULL DEFAULT '{}',
        version TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        payload JSONB NOT NULL,
        size_bytes BIGINT NOT NULL,
        mtime_ns BIGINT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        indexed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS nf_asset_versions (
        version_id BIGSERIAL PRIMARY KEY,
        path TEXT NOT NULL,
        asset_id TEXT NOT NULL,
        asset_type TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        payload JSONB NOT NULL,
        recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (path, content_hash)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS nf_task_statuses (
        status_asset_id TEXT PRIMARY KEY,
        path TEXT NOT NULL DEFAULT '',
        run_id TEXT NOT NULL,
        step TEXT NOT NULL,
        status TEXT NOT NULL,
        input_paths TEXT[] NOT NULL DEFAULT '{}',
        output_paths TEXT[] NOT NULL DEFAULT '{}',
        error_message TEXT NOT NULL DEFAULT '',
        payload JSONB NOT NULL,
        recorded_at TEXT NOT NULL,
        indexed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "ALTER TABLE nf_task_statuses ADD COLUMN IF NOT EXISTS path TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE nf_assets ADD COLUMN IF NOT EXISTS project_id TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE nf_assets ADD COLUMN IF NOT EXISTS workspace_path TEXT NOT NULL DEFAULT ''",
    """
    CREATE TABLE IF NOT EXISTS nf_projects (
        project_id TEXT PRIMARY KEY,
        workspace_asset_id TEXT NOT NULL,
        workspace_path TEXT NOT NULL UNIQUE,
        title TEXT NOT NULL,
        series_title TEXT NOT NULL DEFAULT '',
        book_number INTEGER,
        status TEXT NOT NULL DEFAULT 'active',
        config JSONB NOT NULL,
        payload JSONB NOT NULL,
        updated_at TEXT NOT NULL,
        indexed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_nf_assets_category ON nf_assets(category)",
    "CREATE INDEX IF NOT EXISTS idx_nf_assets_type ON nf_assets(asset_type)",
    "CREATE INDEX IF NOT EXISTS idx_nf_assets_project ON nf_assets(project_id, workspace_path)",
    "CREATE INDEX IF NOT EXISTS idx_nf_assets_tags ON nf_assets USING GIN(tags)",
    "CREATE INDEX IF NOT EXISTS idx_nf_asset_versions_asset_id ON nf_asset_versions(asset_id)",
    "CREATE INDEX IF NOT EXISTS idx_nf_task_statuses_run_step ON nf_task_statuses(run_id, step)",
    "CREATE INDEX IF NOT EXISTS idx_nf_task_statuses_status ON nf_task_statuses(status)",
    "CREATE INDEX IF NOT EXISTS idx_nf_projects_status ON nf_projects(status)",
    "CREATE INDEX IF NOT EXISTS idx_nf_projects_series ON nf_projects(series_title, book_number)",
]

DOWNGRADE_STATEMENTS = [
    "DROP INDEX IF EXISTS idx_nf_projects_series",
    "DROP INDEX IF EXISTS idx_nf_projects_status",
    "DROP INDEX IF EXISTS idx_nf_task_statuses_status",
    "DROP INDEX IF EXISTS idx_nf_task_statuses_run_step",
    "DROP INDEX IF EXISTS idx_nf_asset_versions_asset_id",
    "DROP INDEX IF EXISTS idx_nf_assets_tags",
    "DROP INDEX IF EXISTS idx_nf_assets_project",
    "DROP INDEX IF EXISTS idx_nf_assets_type",
    "DROP INDEX IF EXISTS idx_nf_assets_category",
    "DROP TABLE IF EXISTS nf_projects",
    "DROP TABLE IF EXISTS nf_task_statuses",
    "DROP TABLE IF EXISTS nf_asset_versions",
    "DROP TABLE IF EXISTS nf_assets",
    "DROP TABLE IF EXISTS nf_schema_migrations",
]
