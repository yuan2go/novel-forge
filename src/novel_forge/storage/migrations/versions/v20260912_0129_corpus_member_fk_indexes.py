from __future__ import annotations


MIGRATION_ID = "20260912_0129_corpus_member_fk_indexes"
DOWN_REVISION = "20260910_0128_corpus_operations"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = "retain Corpus member scope foreign keys; append their composite supporting indexes"


UPGRADE_STATEMENTS = [
    "CREATE INDEX IF NOT EXISTS corpus_work_member_revision_scope_idx ON authority_corpus_work_member(revision_id,project_id)",
    "CREATE INDEX IF NOT EXISTS corpus_work_member_processing_scope_idx ON authority_corpus_work_member(processing_id,project_id,edition_id)",
    "CREATE INDEX IF NOT EXISTS corpus_curated_member_revision_scope_idx ON authority_corpus_curated_member(revision_id,project_id)",
    "CREATE INDEX IF NOT EXISTS corpus_curated_member_processing_scope_idx ON authority_corpus_curated_member(processing_id,project_id,edition_id)",
]
