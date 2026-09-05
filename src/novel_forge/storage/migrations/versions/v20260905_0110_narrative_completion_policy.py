from __future__ import annotations


MIGRATION_ID = "20260905_0110_narrative_completion_policy"
DOWN_REVISION = "20260905_0109_chapter_window_execution_policy"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = "append new Book completion cases; never rewrite accepted history or existing completion evidence"


UPGRADE_STATEMENTS = [
    """
    CREATE TABLE authority_book_completion_case (
        completion_case_id TEXT PRIMARY KEY,
        book_run_id TEXT NOT NULL REFERENCES authority_book_production(book_run_id),
        project_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        acceptance_id TEXT NOT NULL REFERENCES authority_book_chapter_acceptance(acceptance_id),
        projection_set_id TEXT NOT NULL REFERENCES authority_book_narrative_projection_set(projection_set_id),
        chapter_number INTEGER NOT NULL CHECK (chapter_number > 0),
        operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        contract_version TEXT NOT NULL CHECK (contract_version='whole-book-completion-v1'),
        content_hash TEXT NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
        decision TEXT NOT NULL CHECK (decision='BLOCKED'),
        report JSONB NOT NULL CHECK (
            report ?& ARRAY['contract_version','decision','owner','whole_book_accepted','accepted_actual_mutation_allowed','blockers','snapshot']
            AND report->>'contract_version'='whole-book-completion-v1'
            AND report->>'decision'=decision
            AND report->>'owner'='BookAuthority'
            AND report->'whole_book_accepted'='false'::jsonb
            AND report->'accepted_actual_mutation_allowed'='false'::jsonb
            AND jsonb_array_length(report->'blockers') > 0
        ),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(book_run_id, acceptance_id, content_hash)
    )
    """,
    """
    CREATE FUNCTION authority_book_completion_case_guard()
    RETURNS TRIGGER AS $$
    BEGIN
        IF TG_OP <> 'INSERT' THEN
            RAISE EXCEPTION 'Book completion cases are immutable'
                USING ERRCODE='23514', CONSTRAINT='authority_book_completion_immutable';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM authority_book_production AS book
            JOIN authority_book_chapter_acceptance AS acceptance
              ON acceptance.book_run_id=book.book_run_id
             AND acceptance.acceptance_id=NEW.acceptance_id
             AND acceptance.project_id=NEW.project_id
             AND acceptance.chapter_number=NEW.chapter_number
             AND acceptance.status='COMMITTED'
            JOIN authority_book_narrative_projection_set AS projection
              ON projection.projection_set_id=NEW.projection_set_id
             AND projection.acceptance_id=acceptance.acceptance_id
             AND projection.status='COMPLETE'
            JOIN authority_operation AS operation
              ON operation.operation_id=NEW.operation_id
             AND operation.project_id=NEW.project_id
             AND operation.definition_name='book.authority.mutate'
            WHERE book.book_run_id=NEW.book_run_id
              AND book.project_id=NEW.project_id AND book.book_id=NEW.book_id
              AND book.target_chapter_count=NEW.chapter_number
              AND book.accepted_through_chapter=NEW.chapter_number
              AND book.active_longform_projection_set_id=NEW.projection_set_id
              AND NEW.report->'snapshot'->>'book_run_id'=NEW.book_run_id
              AND NEW.report->'snapshot'->>'project_id'=NEW.project_id
              AND NEW.report->'snapshot'->>'book_id'=NEW.book_id
              AND (NEW.report->'snapshot'->>'target_chapter_count')::integer=NEW.chapter_number
              AND NEW.report->'snapshot'->>'book_design_version'=book.book_design_version
              AND NEW.report->'snapshot'->>'book_plan_version'=book.book_plan_version
              AND (NEW.report->'snapshot'->'accepted_boundary'->>'chapter_number')::integer=NEW.chapter_number
              AND NEW.report->'snapshot'->'accepted_boundary'->>'chapter_outcome_asset_version_id'=projection.chapter_outcome_asset_version_id
              AND NEW.report->'snapshot'->'accepted_boundary'->>'story_state_asset_version_id'=projection.story_state_asset_version_id
              AND NEW.report->'snapshot'->'accepted_boundary'->>'canon_snapshot_asset_version_id'=projection.canon_snapshot_asset_version_id
              AND NEW.report->'snapshot'->'accepted_boundary'->>'projection_hash'=projection.projection_hash
              AND NEW.report->'snapshot'->'accepted_boundary'->>'acceptance_id'=NEW.acceptance_id
              AND NEW.report->'snapshot'->'accepted_boundary'->>'projection_set_id'=NEW.projection_set_id
              AND NEW.report->'snapshot'->'arc_state'=projection.arc_state
              AND NEW.report->'snapshot'->'obligation_state'=projection.obligation_state
              AND NEW.report->'snapshot'->'chapter_gate_evidence'=acceptance.evidence
        ) THEN
            RAISE EXCEPTION 'Book completion scope differs from the terminal accepted boundary'
                USING ERRCODE='23514', CONSTRAINT='authority_book_completion_scope';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE TRIGGER authority_book_completion_case_guard_trigger
    BEFORE INSERT OR UPDATE OR DELETE ON authority_book_completion_case
    FOR EACH ROW EXECUTE FUNCTION authority_book_completion_case_guard()
    """,
    "CREATE INDEX authority_book_completion_book_idx ON authority_book_completion_case(book_run_id, created_at DESC)",
    "CREATE INDEX authority_book_completion_acceptance_idx ON authority_book_completion_case(acceptance_id)",
    "CREATE INDEX authority_book_completion_projection_idx ON authority_book_completion_case(projection_set_id)",
    "CREATE INDEX authority_book_completion_operation_idx ON authority_book_completion_case(operation_id)",
]

DOWNGRADE_STATEMENTS: list[str] = []
