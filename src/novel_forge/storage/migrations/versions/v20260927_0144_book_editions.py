from __future__ import annotations

MIGRATION_ID = "20260927_0144_book_editions"
DOWN_REVISION = "20260927_0143_runtime_dispatch_control"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "retain edition revisions and switch events; append a corrected revision and controlled selection"

UPGRADE_STATEMENTS = [
    """CREATE TABLE authority_book_edition (
        edition_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        workspace_id TEXT NOT NULL REFERENCES authority_workspace(workspace_id),
        book_id TEXT NOT NULL REFERENCES authority_book(book_id),
        source_book_run_id TEXT NOT NULL REFERENCES authority_book_production(book_run_id),
        version BIGINT NOT NULL CHECK(version > 0),
        current_revision_id TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        created_by_operation_id TEXT NOT NULL UNIQUE REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    """CREATE TABLE authority_book_edition_revision (
        revision_id TEXT PRIMARY KEY REFERENCES authority_asset_version(asset_version_id),
        edition_id TEXT NOT NULL REFERENCES authority_book_edition(edition_id) DEFERRABLE INITIALLY DEFERRED,
        revision_number BIGINT NOT NULL CHECK(revision_number > 0),
        predecessor_revision_id TEXT REFERENCES authority_book_edition_revision(revision_id),
        base_revision_id TEXT REFERENCES authority_book_edition_revision(revision_id),
        manifest_digest TEXT NOT NULL,
        created_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(edition_id, revision_number)
    )""",
    """CREATE TABLE authority_book_edition_head (
        book_id TEXT PRIMARY KEY REFERENCES authority_book(book_id),
        selected_revision_id TEXT NOT NULL REFERENCES authority_book_edition_revision(revision_id),
        version BIGINT NOT NULL CHECK(version > 0),
        updated_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id)
    )""",
    """CREATE TABLE authority_book_edition_event (
        event_id TEXT PRIMARY KEY,
        revision_id TEXT NOT NULL REFERENCES authority_book_edition_revision(revision_id),
        event_kind TEXT NOT NULL CHECK(event_kind IN ('CREATED','SAVED','VALIDATION_BOUND','VALIDATED','REJECTED','SELECTED','SOURCE_INVALIDATED')),
        content JSONB NOT NULL,
        created_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    """CREATE TABLE authority_book_edition_run (
        book_run_id TEXT PRIMARY KEY REFERENCES authority_book_production(book_run_id),
        revision_id TEXT NOT NULL UNIQUE REFERENCES authority_book_edition_revision(revision_id),
        role TEXT NOT NULL CHECK(role IN ('SOURCE','VALIDATION')),
        created_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id)
    )""",
    *[f"CREATE INDEX {table}_{column}_idx ON {table}({column})" for table, column in (
        ("authority_book_edition", "project_id"), ("authority_book_edition", "workspace_id"),
        ("authority_book_edition", "book_id"), ("authority_book_edition", "source_book_run_id"),
        ("authority_book_edition", "current_revision_id"),
        ("authority_book_edition_revision", "predecessor_revision_id"),
        ("authority_book_edition_revision", "base_revision_id"),
        ("authority_book_edition_revision", "created_by_operation_id"),
        ("authority_book_edition_head", "selected_revision_id"), ("authority_book_edition_head", "updated_by_operation_id"),
        ("authority_book_edition_event", "revision_id"), ("authority_book_edition_event", "created_by_operation_id"),
        ("authority_book_edition_run", "revision_id"), ("authority_book_edition_run", "created_by_operation_id"),
    )],
    *[f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION authority_book_completion_immutable_guard()"
      for table in ("authority_book_edition_revision", "authority_book_edition_event", "authority_book_edition_run")],
    """CREATE FUNCTION authority_book_edition_scope_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM authority_book_production b JOIN authority_operation o
            ON o.operation_id=NEW.created_by_operation_id AND o.project_id=b.project_id AND o.workspace_id=b.workspace_id
            WHERE b.book_run_id=NEW.source_book_run_id AND b.project_id=NEW.project_id
            AND b.workspace_id=NEW.workspace_id AND b.book_id=NEW.book_id)
        THEN RAISE EXCEPTION 'Book edition scope mismatch'; END IF;
        RETURN NEW;
    END $$""",
    "CREATE TRIGGER authority_book_edition_scope BEFORE INSERT OR UPDATE ON authority_book_edition FOR EACH ROW EXECUTE FUNCTION authority_book_edition_scope_guard()",
]


_PROJECTION_COMPONENTS = (
    "authority_arc_progress_v2", "authority_arc_actual_state", "authority_arc_checkpoint_v2",
    "authority_arc_outcome_v2", "authority_narrative_obligation_state",
)
UPGRADE_STATEMENTS.extend([
    *[f"ALTER TABLE {table} ADD COLUMN book_run_id TEXT REFERENCES authority_book_production(book_run_id)" for table in _PROJECTION_COMPONENTS],
    *[f"UPDATE {table} component SET book_run_id=projection.book_run_id FROM authority_book_narrative_projection_set projection WHERE component.projection_set_id=projection.projection_set_id" for table in _PROJECTION_COMPONENTS],
    *[f"ALTER TABLE {table} ALTER COLUMN book_run_id SET NOT NULL" for table in _PROJECTION_COMPONENTS],
    """DO $$ DECLARE item record; existing record; BEGIN
      FOR item IN SELECT * FROM (VALUES
        ('authority_book_narrative_projection_set', 'UNIQUE (project_id, book_id, chapter_number)'),
        ('authority_arc_progress_v2', 'UNIQUE (project_id, book_id, arc_plan_version_id, chapter_number)'),
        ('authority_arc_actual_state', 'PRIMARY KEY (project_id, book_id, arc_plan_version_id)'),
        ('authority_arc_checkpoint_v2', 'UNIQUE (project_id, book_id, arc_plan_version_id, accepted_through_chapter)'),
        ('authority_arc_outcome_v2', 'UNIQUE (project_id, book_id, arc_plan_version_id)'),
        ('authority_narrative_obligation_state', 'PRIMARY KEY (project_id, book_id, obligation_id)')
      ) scopes(table_name, old_definition) LOOP
        FOR existing IN SELECT conname FROM pg_constraint WHERE conrelid=item.table_name::regclass
          AND pg_get_constraintdef(oid)=item.old_definition LOOP
          EXECUTE format('ALTER TABLE %I DROP CONSTRAINT %I', item.table_name, existing.conname);
        END LOOP;
      END LOOP;
    END $$""",
    "ALTER TABLE authority_book_narrative_projection_set ADD CONSTRAINT authority_book_projection_run_chapter_unique UNIQUE(book_run_id,chapter_number)",
    "ALTER TABLE authority_arc_progress_v2 ADD CONSTRAINT authority_arc_progress_run_unique UNIQUE(book_run_id,arc_plan_version_id,chapter_number)",
    "ALTER TABLE authority_arc_actual_state ADD PRIMARY KEY(book_run_id,arc_plan_version_id)",
    "ALTER TABLE authority_arc_checkpoint_v2 ADD CONSTRAINT authority_arc_checkpoint_run_unique UNIQUE(book_run_id,arc_plan_version_id,accepted_through_chapter)",
    "ALTER TABLE authority_arc_outcome_v2 ADD CONSTRAINT authority_arc_outcome_run_unique UNIQUE(book_run_id,arc_plan_version_id)",
    "ALTER TABLE authority_narrative_obligation_state ADD PRIMARY KEY(book_run_id,obligation_id)",
    """CREATE FUNCTION authority_longform_projection_run_scope_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE source authority_book_narrative_projection_set%ROWTYPE;
    BEGIN
      SELECT * INTO source FROM authority_book_narrative_projection_set WHERE projection_set_id=NEW.projection_set_id;
      IF NOT FOUND THEN RAISE EXCEPTION 'Longform projection source missing'; END IF;
      IF NEW.book_run_id IS NULL THEN NEW.book_run_id := source.book_run_id; END IF;
      IF (NEW.project_id,NEW.book_id,NEW.book_run_id,NEW.acceptance_operation_id)
         IS DISTINCT FROM (source.project_id,source.book_id,source.book_run_id,source.acceptance_operation_id)
      THEN RAISE EXCEPTION 'Longform projection run scope mismatch'; END IF;
      IF TG_OP='UPDATE' AND (OLD.project_id,OLD.book_id,OLD.book_run_id)
         IS DISTINCT FROM (NEW.project_id,NEW.book_id,NEW.book_run_id)
      THEN RAISE EXCEPTION 'Longform projection cannot change manuscript run'; END IF;
      RETURN NEW;
    END $$""",
    *[f"CREATE TRIGGER {table}_run_scope BEFORE INSERT OR UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION authority_longform_projection_run_scope_guard()" for table in _PROJECTION_COMPONENTS],
])

DOWNGRADE_STATEMENTS: list[str] = []
