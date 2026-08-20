from __future__ import annotations


MIGRATION_ID = "20260820_0093_book_liveness_critical_path_closure"
DOWN_REVISION = "20260814_0092_longform_correctness_closure"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = (
    "Restore the pre-0093 backup to recover dropped redundant pointer columns. "
    "For forward repair, reconstruct any projection from the durable follow-up "
    "operation link and normalize legacy sidecar-blocking Book states."
)


UPGRADE_STATEMENTS = [
    """
    UPDATE authority_book_production AS book
    SET state='READY', version=version+1, updated_at=NOW()
    WHERE book.state='COMPLETED'
      AND EXISTS (
          SELECT 1
          FROM authority_chapter_group_production AS group_run
          WHERE group_run.book_run_id=book.book_run_id
            AND group_run.state='CLOSURE_PENDING'
      )
    """,
    """
    UPDATE authority_book_production
    SET state='READY',
        active_chapter_request_id=NULL,
        active_child_delegation_id=NULL,
        active_chapter_number=NULL,
        active_plan_version_id=NULL,
        version=version+1,
        updated_at=NOW()
    WHERE state IN (
        'CANON_COMMITTED', 'READER_OUTCOME_PENDING',
        'FOLLOWUP_PENDING', 'CHECKPOINT_PENDING'
    )
      AND active_chapter_request_id IS NULL
      AND accepted_through_chapter > 0
      AND EXISTS (
          SELECT 1
          FROM authority_book_chapter_acceptance AS acceptance
          WHERE acceptance.book_run_id=authority_book_production.book_run_id
            AND acceptance.chapter_number=
                authority_book_production.accepted_through_chapter
            AND acceptance.status='COMMITTED'
      )
    """,
    "DROP INDEX authority_book_production_reader_operation_fk_idx",
    "DROP INDEX authority_book_production_recap_operation_fk_idx",
    """
    ALTER TABLE authority_book_production
    DROP COLUMN last_reader_outcome_operation_id,
    DROP COLUMN last_recap_operation_id
    """,
    """
    CREATE INDEX authority_book_acceptance_followup_admission_idx
    ON authority_book_chapter_acceptance(
        status, chapter_number, created_at, book_run_id, chapter_request_id
    )
    """,
    """
    CREATE INDEX authority_book_followup_backlog_idx
    ON authority_book_followup_operation(
        book_run_id, chapter_request_id, followup_type, operation_id
    )
    """,
    """
    CREATE INDEX authority_book_followup_runtime_job_progress_idx
    ON authority_runtime_job(
        project_id, (input_snapshot->>'book_run_id'), status, available_at
    )
    WHERE runtime_group='book_followup'
      AND job_kind='BOOK_FOLLOWUP_ADMISSION'
    """,
]


def upgrade(connection) -> None:
    with connection.cursor() as cursor:
        for statement in UPGRADE_STATEMENTS:
            cursor.execute(statement)


__all__ = [
    "BACKUP_REQUIRED",
    "DOWN_REVISION",
    "FORWARD_FIX",
    "FORWARD_ONLY",
    "MIGRATION_ID",
    "UPGRADE_STATEMENTS",
    "upgrade",
]
