from __future__ import annotations


MIGRATION_ID = "20260905_0112_realization_execution_policy"
DOWN_REVISION = "20260905_0111_whole_book_completion"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = (
    "retain positive ordered realization ranges; bind execution caps per Book run"
)


UPGRADE_STATEMENTS = [
    """
    DO $$
    DECLARE range_constraint TEXT;
    BEGIN
        SELECT conname INTO STRICT range_constraint FROM pg_constraint
        WHERE conrelid='authority_narrative_realization'::regclass
          AND contype='c'
          AND pg_get_constraintdef(oid) LIKE '%chapter_end - chapter_start%';
        EXECUTE format(
            'ALTER TABLE authority_narrative_realization DROP CONSTRAINT %I',
            range_constraint
        );
    END;
    $$
    """,
]


def upgrade(connection) -> None:
    with connection.cursor() as cursor:
        for statement in UPGRADE_STATEMENTS:
            cursor.execute(statement)
