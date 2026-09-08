from __future__ import annotations


MIGRATION_ID = "20260909_0124_corpus_fk_indexes"
DOWN_REVISION = "20260908_0123_source_analysis_dimensions"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = "retain Corpus foreign keys; append missing supporting indexes"


UPGRADE_STATEMENTS = [
    "CREATE INDEX IF NOT EXISTS authority_corpus_source_workspace_idx ON authority_corpus_source(workspace_id)",
    "CREATE INDEX IF NOT EXISTS authority_corpus_rights_previous_scope_idx ON authority_corpus_rights(project_id,source_id,previous_rights_id) WHERE previous_rights_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS authority_corpus_snapshot_rights_scope_idx ON authority_corpus_snapshot(project_id,source_id,rights_id)",
    "CREATE INDEX IF NOT EXISTS authority_corpus_snapshot_previous_scope_idx ON authority_corpus_snapshot(project_id,source_id,previous_snapshot_id) WHERE previous_snapshot_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS authority_corpus_edition_snapshot_scope_idx ON authority_corpus_edition(project_id,source_id,snapshot_id)",
    "CREATE INDEX IF NOT EXISTS authority_corpus_edition_book_scope_idx ON authority_corpus_edition(project_id,source_id,book_source_id)",
    "CREATE INDEX IF NOT EXISTS authority_corpus_membership_admission_idx ON authority_corpus_membership(project_id,edition_id,purpose,decision_id,decision)",
    "CREATE INDEX IF NOT EXISTS authority_corpus_retirement_source_scope_idx ON authority_corpus_retirement(project_id,source_id)",
]
