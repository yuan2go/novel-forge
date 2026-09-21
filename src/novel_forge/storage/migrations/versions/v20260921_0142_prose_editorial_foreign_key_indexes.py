from __future__ import annotations


MIGRATION_ID = "20260921_0142_prose_editorial_foreign_key_indexes"
DOWN_REVISION = "20260921_0141_author_chapter_replacement"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = "retain prose review and editorial foreign keys; append their supporting indexes"


UPGRADE_STATEMENTS = [
    "CREATE INDEX IF NOT EXISTS authority_book_editorial_event_project_idx ON authority_book_editorial_event(project_id)",
    "CREATE INDEX IF NOT EXISTS authority_book_editorial_event_workspace_idx ON authority_book_editorial_event(workspace_id)",
    "CREATE INDEX IF NOT EXISTS authority_book_prose_review_run_project_idx ON authority_book_prose_review_run(project_id)",
    "CREATE INDEX IF NOT EXISTS authority_book_prose_review_run_workspace_idx ON authority_book_prose_review_run(workspace_id)",
    "CREATE INDEX IF NOT EXISTS authority_book_prose_review_event_operation_idx ON authority_book_prose_review_event(created_by_operation_id)",
]
