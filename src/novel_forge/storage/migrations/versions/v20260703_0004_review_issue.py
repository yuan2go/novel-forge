from __future__ import annotations

MIGRATION_ID = "20260703_0004_review_issue"
DOWN_REVISION: str | None = "20260702_0003_mkaos_p0"

UPGRADE_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS review_issues (
        id TEXT PRIMARY KEY,
        asset_id TEXT NOT NULL UNIQUE,
        project_id TEXT NOT NULL DEFAULT '',
        workspace_path TEXT NOT NULL DEFAULT '',
        target_asset_id TEXT NOT NULL DEFAULT '',
        target_asset_type TEXT NOT NULL DEFAULT '',
        target_asset_path TEXT NOT NULL DEFAULT '',
        issue_type TEXT NOT NULL,
        severity TEXT NOT NULL,
        blocking BOOLEAN NOT NULL DEFAULT FALSE,
        status TEXT NOT NULL DEFAULT 'open',
        source_system TEXT NOT NULL DEFAULT '',
        source_issue_id TEXT NOT NULL DEFAULT '',
        review_report_id TEXT NOT NULL DEFAULT '',
        review_report_path TEXT NOT NULL DEFAULT '',
        revision_task_id TEXT NOT NULL DEFAULT '',
        message TEXT NOT NULL DEFAULT '',
        fix_suggestion TEXT NOT NULL DEFAULT '',
        evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
        source_issue JSONB NOT NULL DEFAULT '{}'::jsonb,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_review_issues_project ON review_issues(project_id, workspace_path)",
    "CREATE INDEX IF NOT EXISTS idx_review_issues_target ON review_issues(target_asset_id, target_asset_type)",
    "CREATE INDEX IF NOT EXISTS idx_review_issues_blocking ON review_issues(blocking, status, severity)",
    "CREATE INDEX IF NOT EXISTS idx_review_issues_source ON review_issues(source_system, source_issue_id)",
]

DOWNGRADE_STATEMENTS: list[str] = []
