from __future__ import annotations


MIGRATION_ID = "20260905_0111_whole_book_completion"
DOWN_REVISION = "20260905_0110_chapter_mission_scene_contract"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = "append a new completion case and decision; never rewrite accepted Chapter history or terminal completion evidence"


UPGRADE_STATEMENTS = [
    """
    CREATE TABLE authority_book_completion_case (
        case_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        workspace_id TEXT NOT NULL REFERENCES authority_workspace(workspace_id),
        book_id TEXT NOT NULL,
        book_run_id TEXT NOT NULL REFERENCES authority_book_production(book_run_id),
        case_version BIGINT NOT NULL CHECK (case_version > 0),
        exact_release_sha TEXT NOT NULL CHECK (exact_release_sha ~ '^[0-9a-f]{40}$'),
        source_digest TEXT NOT NULL CHECK (source_digest ~ '^sha256:[0-9a-f]{64}$'),
        accepted_through INTEGER NOT NULL CHECK (accepted_through >= 0),
        status TEXT NOT NULL CHECK (status IN ('READY_FOR_EDITORIAL','NEEDS_REMEDIATION')),
        assessment JSONB NOT NULL CHECK (assessment->>'schema_version'='book-completion-case.v1'),
        source_snapshot JSONB NOT NULL CHECK (jsonb_typeof(source_snapshot)='object'),
        created_by_operation_id TEXT NOT NULL UNIQUE REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        FOREIGN KEY(project_id, book_id) REFERENCES authority_book(project_id, book_id),
        UNIQUE(book_run_id, case_version),
        UNIQUE(case_id, source_digest)
    )
    """,
    """
    CREATE TABLE authority_book_completion_source (
        case_id TEXT NOT NULL REFERENCES authority_book_completion_case(case_id),
        chapter_number INTEGER NOT NULL CHECK (chapter_number > 0),
        acceptance_id TEXT NOT NULL REFERENCES authority_book_chapter_acceptance(acceptance_id),
        projection_set_id TEXT REFERENCES authority_book_narrative_projection_set(projection_set_id),
        outcome_version_id TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        story_state_version_id TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        canon_version_id TEXT REFERENCES authority_asset_version(asset_version_id),
        source_record JSONB NOT NULL CHECK (jsonb_typeof(source_record)='object'),
        PRIMARY KEY(case_id, chapter_number),
        UNIQUE(case_id, acceptance_id)
    )
    """,
    """
    CREATE TABLE authority_book_completion_decision (
        decision_id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL UNIQUE REFERENCES authority_book_completion_case(case_id),
        book_run_id TEXT NOT NULL REFERENCES authority_book_production(book_run_id),
        decision_version BIGINT NOT NULL CHECK (decision_version > 0),
        source_digest TEXT NOT NULL,
        requested_decision TEXT NOT NULL CHECK (requested_decision IN ('ACCEPTED','REJECTED')),
        outcome TEXT NOT NULL CHECK (outcome IN ('BLOCKED','REJECTED')),
        decision JSONB NOT NULL CHECK (decision->>'schema_version'='book-completion-decision.v1'),
        quality_campaign_id TEXT REFERENCES authority_quality_qualification_campaign(campaign_id),
        quality_decision_id TEXT REFERENCES authority_quality_qualification_decision(decision_id),
        closure_evidence_id TEXT REFERENCES authority_quality_qualification_evidence(evidence_id),
        created_by_operation_id TEXT NOT NULL UNIQUE REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        FOREIGN KEY(case_id, source_digest) REFERENCES authority_book_completion_case(case_id, source_digest),
        UNIQUE(book_run_id, decision_version),
        CHECK ((requested_decision='REJECTED' AND outcome='REJECTED') OR
               (requested_decision='ACCEPTED' AND outcome='BLOCKED'))
    )
    """,
    """
    CREATE FUNCTION authority_book_completion_scope_guard() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_TABLE_NAME='authority_book_completion_case' THEN
            IF NOT EXISTS (
                SELECT 1 FROM authority_book_production AS book
                JOIN authority_operation AS operation
                  ON operation.operation_id=NEW.created_by_operation_id
                 AND operation.project_id=book.project_id
                 AND operation.workspace_id=book.workspace_id
                WHERE book.book_run_id=NEW.book_run_id AND book.project_id=NEW.project_id
                  AND book.workspace_id=NEW.workspace_id AND book.book_id=NEW.book_id
            ) THEN RAISE EXCEPTION 'completion case scope mismatch'; END IF;
        ELSIF TG_TABLE_NAME='authority_book_completion_source' THEN
            IF NOT EXISTS (
                SELECT 1 FROM authority_book_completion_case AS completion
                JOIN authority_book_chapter_acceptance AS accepted
                  ON accepted.book_run_id=completion.book_run_id
                 AND accepted.project_id=completion.project_id
                WHERE completion.case_id=NEW.case_id AND accepted.acceptance_id=NEW.acceptance_id
                  AND accepted.chapter_number=NEW.chapter_number
                  AND accepted.chapter_outcome_asset_version_id=NEW.outcome_version_id
                  AND accepted.story_state_asset_version_id=NEW.story_state_version_id
                  AND accepted.canon_snapshot_asset_version_id IS NOT DISTINCT FROM NEW.canon_version_id
                  AND accepted.longform_projection_set_id IS NOT DISTINCT FROM NEW.projection_set_id
            ) THEN RAISE EXCEPTION 'completion accepted source mismatch'; END IF;
        ELSE
            IF NOT EXISTS (
                SELECT 1 FROM authority_book_completion_case AS completion
                JOIN authority_operation AS operation
                  ON operation.operation_id=NEW.created_by_operation_id
                 AND operation.project_id=completion.project_id
                 AND operation.workspace_id=completion.workspace_id
                WHERE completion.case_id=NEW.case_id AND completion.book_run_id=NEW.book_run_id
                  AND completion.source_digest=NEW.source_digest
            ) THEN RAISE EXCEPTION 'completion decision scope mismatch'; END IF;
        END IF;
        RETURN NEW;
    END
    $$
    """,
    """
    CREATE FUNCTION authority_book_completion_immutable_guard() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'completion evidence is immutable; append a new case or decision';
    END
    $$
    """,
    *[
        statement
        for table in (
            "authority_book_completion_case",
            "authority_book_completion_source",
            "authority_book_completion_decision",
        )
        for statement in (
            f"CREATE TRIGGER {table}_scope BEFORE INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION authority_book_completion_scope_guard()",
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION authority_book_completion_immutable_guard()",
        )
    ],
    "CREATE INDEX authority_completion_case_scope_idx ON authority_book_completion_case(project_id,book_id,case_version DESC)",
    "CREATE INDEX authority_completion_source_acceptance_idx ON authority_book_completion_source(acceptance_id)",
    "CREATE INDEX authority_completion_source_projection_idx ON authority_book_completion_source(projection_set_id)",
    "CREATE INDEX authority_completion_decision_campaign_idx ON authority_book_completion_decision(quality_campaign_id)",
]


DOWNGRADE_STATEMENTS: list[str] = []
