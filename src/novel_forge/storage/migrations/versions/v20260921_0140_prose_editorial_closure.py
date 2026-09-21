from __future__ import annotations

MIGRATION_ID = "20260921_0140_prose_editorial_closure"
DOWN_REVISION = "20260920_0139_narrative_reference_sampling"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = "append review and editorial events; retain frozen prose manifests and prior signatures"

UPGRADE_STATEMENTS = [
    """CREATE TABLE authority_book_prose_review_run (
        run_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        workspace_id TEXT NOT NULL REFERENCES authority_workspace(workspace_id),
        book_run_id TEXT NOT NULL REFERENCES authority_book_production(book_run_id),
        manifest_digest TEXT NOT NULL,
        manifest JSONB NOT NULL,
        exact_release_sha TEXT NOT NULL CHECK (exact_release_sha ~ '^[0-9a-f]{40}$'),
        created_by_operation_id TEXT NOT NULL UNIQUE REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(book_run_id, manifest_digest, exact_release_sha)
    )""",
    """CREATE TABLE authority_book_prose_review_event (
        event_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES authority_book_prose_review_run(run_id),
        event_version BIGINT NOT NULL CHECK (event_version > 0),
        kind TEXT NOT NULL CHECK (kind IN ('WINDOW_ADMITTED','WINDOW_REUSED','FINDING_DISPOSITION','PAUSED','RESUMED')),
        content JSONB NOT NULL,
        created_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(run_id, event_version)
    )""",
    """CREATE TABLE authority_book_editorial_event (
        event_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        workspace_id TEXT NOT NULL REFERENCES authority_workspace(workspace_id),
        book_run_id TEXT NOT NULL REFERENCES authority_book_production(book_run_id),
        event_version BIGINT NOT NULL CHECK (event_version > 0),
        kind TEXT NOT NULL CHECK (kind IN ('POLICY','SIGNATURE','REVOCATION')),
        content JSONB NOT NULL,
        actor_id TEXT NOT NULL,
        authentication_source TEXT NOT NULL,
        created_by_operation_id TEXT NOT NULL UNIQUE REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(book_run_id, event_version)
    )""",
    """CREATE FUNCTION authority_prose_editorial_scope_guard() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_TABLE_NAME='authority_book_prose_review_event' THEN
            IF NOT EXISTS (SELECT 1 FROM authority_book_prose_review_run r
                JOIN authority_operation o ON o.project_id=r.project_id AND o.workspace_id=r.workspace_id
                WHERE r.run_id=NEW.run_id AND o.operation_id=NEW.created_by_operation_id)
            THEN RAISE EXCEPTION 'review event scope mismatch'; END IF;
        ELSE
            IF NOT EXISTS (SELECT 1 FROM authority_book_production b
                JOIN authority_operation o ON o.project_id=b.project_id AND o.workspace_id=b.workspace_id
                WHERE b.book_run_id=NEW.book_run_id AND b.project_id=NEW.project_id
                AND b.workspace_id=NEW.workspace_id AND o.operation_id=NEW.created_by_operation_id)
            THEN RAISE EXCEPTION 'editorial scope mismatch'; END IF;
        END IF;
        RETURN NEW;
    END $$""",
    *[
        statement
        for table in (
            "authority_book_prose_review_run",
            "authority_book_prose_review_event",
            "authority_book_editorial_event",
        )
        for statement in (
            f"CREATE TRIGGER {table}_scope BEFORE INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION authority_prose_editorial_scope_guard()",
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION authority_book_completion_immutable_guard()",
        )
    ],
    "ALTER TABLE authority_book_completion_decision DROP CONSTRAINT authority_book_completion_decision_outcome_check",
    "ALTER TABLE authority_book_completion_decision DROP CONSTRAINT authority_book_completion_decision_check",
    "ALTER TABLE authority_book_completion_decision ADD CHECK (outcome IN ('BLOCKED','REJECTED','ACCEPTED'))",
    "ALTER TABLE authority_book_completion_decision ADD CHECK ((requested_decision='REJECTED' AND outcome='REJECTED') OR (requested_decision='ACCEPTED' AND outcome IN ('BLOCKED','ACCEPTED')))",
]
DOWNGRADE_STATEMENTS: list[str] = []
