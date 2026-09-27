from __future__ import annotations

MIGRATION_ID = "20260927_0145_edition_execution_windows"
DOWN_REVISION = "20260927_0144_book_editions"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "retain frozen edition and execution windows; append a corrected run-scoped decision"

UPGRADE_STATEMENTS = [
    """DO $$ DECLARE existing record; BEGIN
      FOR existing IN SELECT conname FROM pg_constraint
        WHERE conrelid='authority_chapter_group_production'::regclass
          AND pg_get_constraintdef(oid)='UNIQUE (project_id, group_plan_version_id)' LOOP
        EXECUTE format('ALTER TABLE authority_chapter_group_production DROP CONSTRAINT %I', existing.conname);
      END LOOP;
    END $$""",
    "ALTER TABLE authority_chapter_group_production ADD CONSTRAINT authority_chapter_group_run_plan_unique UNIQUE(book_run_id,group_plan_version_id)",
    "DROP INDEX chapter_group_one_active_per_book_idx",
    "CREATE UNIQUE INDEX chapter_group_one_active_per_run_idx ON authority_chapter_group_production(book_run_id) WHERE state IN ('PREPARING','READY','CHAPTER_RUNNING','CLOSURE_PENDING','PAUSED')",
]
DOWNGRADE_STATEMENTS: list[str] = []
