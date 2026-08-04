from __future__ import annotations


MIGRATION_ID = "20260804_0054_scope_foreign_key_indexes"
DOWN_REVISION = "20260804_0053_d0_provider_qualification_authority"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = (
    "Re-run CREATE INDEX IF NOT EXISTS for any invalid or missing scope index; "
    "do not remove the underlying foreign key."
)
PREFLIGHT_STATEMENTS: list[str] = []


UPGRADE_STATEMENTS = [
    "CREATE INDEX IF NOT EXISTS authority_asset_activation_book_scope_idx ON authority_asset_activation(project_id, book_id)",
    "CREATE INDEX IF NOT EXISTS authority_asset_decision_book_scope_idx ON authority_asset_decision(project_id, book_id)",
    "CREATE INDEX IF NOT EXISTS authority_asset_dependency_book_scope_idx ON authority_asset_dependency(project_id, book_id)",
    "CREATE INDEX IF NOT EXISTS authority_asset_evidence_book_scope_idx ON authority_asset_evidence(project_id, book_id)",
    "CREATE INDEX IF NOT EXISTS authority_asset_supersession_book_scope_idx ON authority_asset_supersession(project_id, book_id)",
    "CREATE INDEX IF NOT EXISTS authority_book_design_candidate_scope_idx ON authority_book_design_candidate(project_id, book_id, workspace_id)",
    "CREATE INDEX IF NOT EXISTS authority_d0_run_report_asset_idx ON authority_d0_qualification_run(report_asset_version_id)",
    "CREATE INDEX IF NOT EXISTS authority_d0_run_workspace_idx ON authority_d0_qualification_run(workspace_id)",
]


DOWNGRADE_STATEMENTS: list[str] = []
