from __future__ import annotations

MIGRATION_ID = "20261008_0181_author_manuscript_delivery"
DOWN_REVISION = "20261007_0180_foundation_direction_search"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Preserve accepted facts, frozen requests, manuscript versions and cost evidence; append a forward correction."

UPGRADE_STATEMENTS = [
    """DO $$ DECLARE item RECORD; BEGIN
        FOR item IN SELECT conname FROM pg_constraint
            WHERE conrelid='authority_capability_pack_validation_admission'::regclass
              AND contype='c' AND pg_get_constraintdef(oid) LIKE '%allowed_environments%'
        LOOP EXECUTE format('ALTER TABLE authority_capability_pack_validation_admission DROP CONSTRAINT %I',item.conname); END LOOP;
        ALTER TABLE authority_capability_pack_validation_admission ADD CONSTRAINT author_pack_runtime_scope CHECK (
            admission_scope->'allowed_environments'='["validation"]'::jsonb OR (
                jsonb_array_length(admission_scope->'allowed_environments')=1
                AND admission_scope->'allowed_environments'=admission_scope->'allowed_runtime_profiles'
                AND admission_scope#>>'{allowed_environments,0}' IN ('development','test','production')
                AND jsonb_path_exists(policy_snapshot, '$.policy.execution_templates[*] ? (@.version == "creative-execution-template.v12" && @.author_workflow.mode == "AUTHOR_FIRST" && @.author_workflow.deep_review == false)')));
    END $$""",
    "ALTER TABLE authority_child_delegation ADD COLUMN delivered_by_operation_id TEXT REFERENCES authority_operation(operation_id)",
    "DROP INDEX authority_child_delegation_one_active_owner_idx",
    """CREATE UNIQUE INDEX authority_child_delegation_one_active_owner_idx ON authority_child_delegation(owner_id)
        WHERE superseded_at IS NULL AND delivered_by_operation_id IS NULL
          AND status IN ('DISPATCHED','RUNNING','WAITING_RETRY','SUCCEEDED','CANCELLATION_REQUESTED','UNKNOWN')""",
    """CREATE TABLE authority_book_manuscript_delivery (
        book_run_id TEXT NOT NULL REFERENCES authority_book_production(book_run_id),
        chapter_request_id TEXT NOT NULL UNIQUE REFERENCES authority_book_chapter_request(chapter_request_id),
        chapter_number INTEGER NOT NULL CHECK(chapter_number>0),
        source_asset_version_id TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        source_content_hash TEXT NOT NULL,
        context_snapshot JSONB NOT NULL CHECK(context_snapshot->>'version'='working-manuscript-context.v1'),
        created_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY(book_run_id,chapter_number)
    )""",
    "CREATE INDEX authority_book_manuscript_source_idx ON authority_book_manuscript_delivery(source_asset_version_id)",
    "CREATE INDEX authority_book_manuscript_operation_idx ON authority_book_manuscript_delivery(created_by_operation_id)",
    """CREATE FUNCTION authority_book_manuscript_delivery_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Manuscript delivery evidence is immutable'; END IF;
        IF NOT EXISTS(SELECT 1 FROM authority_book_production b
            JOIN authority_book_chapter_request r ON r.book_run_id=b.book_run_id
            JOIN authority_asset_version v ON v.asset_version_id=NEW.source_asset_version_id
            JOIN authority_asset a ON a.asset_id=v.asset_id AND a.project_id=b.project_id
            JOIN authority_operation_output_asset o ON o.asset_version_id=v.asset_version_id
            JOIN authority_operation p ON p.operation_id=o.operation_id AND p.root_operation_id=r.chapter_root_operation_id
            JOIN authority_operation root ON root.operation_id=r.chapter_root_operation_id
            JOIN authority_operation writer ON writer.operation_id=NEW.created_by_operation_id
            WHERE b.book_run_id=NEW.book_run_id AND r.chapter_request_id=NEW.chapter_request_id
              AND r.chapter_number=NEW.chapter_number AND b.active_chapter_request_id=r.chapter_request_id
              AND b.current_chapter=NEW.chapter_number-1 AND a.asset_type='draft_chapter'
              AND v.content_hash=NEW.source_content_hash AND v.governance='CLEAR' AND v.eligibility='ELIGIBLE'
              AND p.status='SUCCEEDED' AND p.definition_name='chapter.draft.generate'
              AND o.output_key='chapter.draft' AND root.definition_version='3.10.0-author-first.v1'
              AND writer.project_id=b.project_id AND writer.workspace_id=b.workspace_id
              AND writer.definition_name='book.authority.mutate'
              AND writer.command_payload #>> '{payload,action}'='manuscript_deliver'
              AND NEW.context_snapshot->>'book_run_id'=b.book_run_id
              AND NEW.context_snapshot->>'project_id'=b.project_id) THEN
            RAISE EXCEPTION 'Manuscript delivery requires exact owned successful prose';
        END IF;
        RETURN NEW;
    END $$""",
    """CREATE TRIGGER authority_book_manuscript_delivery_guard BEFORE INSERT OR UPDATE OR DELETE
        ON authority_book_manuscript_delivery FOR EACH ROW EXECUTE FUNCTION authority_book_manuscript_delivery_guard()""",
    """CREATE FUNCTION authority_child_manuscript_delivery_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF OLD.delivered_by_operation_id IS NOT NULL AND NEW.delivered_by_operation_id IS DISTINCT FROM OLD.delivered_by_operation_id THEN
            RAISE EXCEPTION 'Manuscript closure cannot rewrite delivery identity';
        END IF;
        IF NEW.delivered_by_operation_id IS NOT NULL AND NOT EXISTS(
            SELECT 1 FROM authority_book_manuscript_delivery d JOIN authority_operation root ON root.operation_id=NEW.child_root_operation_id
            WHERE d.chapter_request_id=NEW.chapter_request_id AND d.book_run_id=NEW.owner_id
              AND d.created_by_operation_id=NEW.delivered_by_operation_id AND root.status='SUCCEEDED'
              AND NEW.status='SUCCEEDED') THEN RAISE EXCEPTION 'Delegation delivery requires its exact saved manuscript'; END IF;
        RETURN NEW;
    END $$""",
    """CREATE TRIGGER authority_child_manuscript_delivery_guard BEFORE UPDATE ON authority_child_delegation
        FOR EACH ROW EXECUTE FUNCTION authority_child_manuscript_delivery_guard()""",
]
DOWNGRADE_STATEMENTS: list[str] = []
