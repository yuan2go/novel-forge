from __future__ import annotations

MIGRATION_ID = "20260628_0002_query_and_release_indexes"
DOWN_REVISION: str | None = "20260625_0001_initial_industrial_schema"

UPGRADE_STATEMENTS = [
    "CREATE INDEX IF NOT EXISTS idx_nf_assets_project_type ON nf_assets(project_id, asset_type, indexed_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_nf_assets_workspace_type ON nf_assets(workspace_path, asset_type, indexed_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_nf_assets_updated ON nf_assets(updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_nf_task_statuses_indexed ON nf_task_statuses(indexed_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_nf_task_statuses_run_status ON nf_task_statuses(run_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_nf_projects_updated ON nf_projects(updated_at)",
]

DOWNGRADE_STATEMENTS = [
    "DROP INDEX IF EXISTS idx_nf_projects_updated",
    "DROP INDEX IF EXISTS idx_nf_task_statuses_run_status",
    "DROP INDEX IF EXISTS idx_nf_task_statuses_indexed",
    "DROP INDEX IF EXISTS idx_nf_assets_updated",
    "DROP INDEX IF EXISTS idx_nf_assets_workspace_type",
    "DROP INDEX IF EXISTS idx_nf_assets_project_type",
]
