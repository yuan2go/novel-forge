from __future__ import annotations

MIGRATION_ID = "20261016_0221_working_scope_fk_indexes"
DOWN_REVISION = "20261015_0220_chapter_prior_audit_convergence"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = "Append supporting indexes for retained working receipts and scoped Story Design versions without changing their facts or guards."

UPGRADE_STATEMENTS = [
    "CREATE INDEX IF NOT EXISTS authority_retained_working_operation_idx ON authority_book_retained_working_continuation(created_by_operation_id)",
    "CREATE INDEX IF NOT EXISTS authority_story_design_active_scoped_source_idx ON authority_story_design_active_version(project_id,asset_version_id,scope_key,scope_layer)",
]
DOWNGRADE_STATEMENTS: list[str] = []
