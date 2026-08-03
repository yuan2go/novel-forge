from __future__ import annotations

MIGRATION_ID = "20260804_0052_asset_schema_and_scope_integrity"
DOWN_REVISION = "20260803_0051_book_design_authority_slice"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = (
    "Create corrected Project/Workspace/Book and explicit legacy AssetVersion scope "
    "records, then rerun 0052; never delete or cross-relabel authoritative rows."
)


PREFLIGHT_STATEMENTS = [
    """
    SELECT 'invalid_asset_schema_version', COUNT(*)
    FROM authority_asset_version
    WHERE schema_version IS NULL
       OR schema_version !~ '^[a-z0-9][a-z0-9._-]*\\.v[0-9]+$'
    UNION ALL
    SELECT 'book_workspace_scope_mismatch', COUNT(*)
    FROM authority_book AS book
    LEFT JOIN authority_workspace AS workspace
      ON workspace.workspace_id = book.workspace_id
    WHERE workspace.workspace_id IS NULL OR workspace.project_id <> book.project_id
    UNION ALL
    SELECT 'book_asset_scope_mismatch', COUNT(*)
    FROM authority_book AS book
    JOIN authority_asset_version AS version
      ON version.asset_version_id IN (
          book.current_book_asset_version_id,
          book.current_book_design_asset_version_id
      )
    JOIN authority_asset AS asset ON asset.asset_id = version.asset_id
    WHERE asset.project_id <> book.project_id
    UNION ALL
    SELECT 'book_design_candidate_scope_mismatch', COUNT(*)
    FROM authority_book_design_candidate AS candidate
    LEFT JOIN authority_book AS book ON book.book_id = candidate.book_id
    LEFT JOIN authority_asset_version AS version
      ON version.asset_version_id = candidate.asset_version_id
    LEFT JOIN authority_asset AS asset ON asset.asset_id = version.asset_id
    WHERE book.book_id IS NULL
       OR (book.project_id, book.workspace_id) <>
          (candidate.project_id, candidate.workspace_id)
       OR asset.project_id <> candidate.project_id
       OR asset.asset_id <> candidate.asset_id
    UNION ALL
    SELECT 'scoped_asset_relation_mismatch', COUNT(*)
    FROM (
        SELECT dependency.project_id, dependency.book_id,
               dependency.source_asset_version_id AS asset_version_id
        FROM authority_asset_dependency AS dependency
        UNION ALL
        SELECT project_id, book_id, target_asset_version_id
        FROM authority_asset_dependency
        UNION ALL
        SELECT project_id, book_id, asset_version_id
        FROM authority_asset_decision
        UNION ALL
        SELECT project_id, book_id, asset_version_id
        FROM authority_asset_activation
        UNION ALL
        SELECT project_id, book_id, previous_asset_version_id
        FROM authority_asset_supersession
        UNION ALL
        SELECT project_id, book_id, successor_asset_version_id
        FROM authority_asset_supersession
        UNION ALL
        SELECT project_id, book_id, asset_version_id
        FROM authority_asset_evidence
    ) AS relation
    LEFT JOIN authority_book AS book ON book.book_id = relation.book_id
    LEFT JOIN authority_asset_version AS version
      ON version.asset_version_id = relation.asset_version_id
    LEFT JOIN authority_asset AS asset ON asset.asset_id = version.asset_id
    WHERE book.book_id IS NULL
       OR book.project_id <> relation.project_id
       OR asset.project_id <> relation.project_id
    UNION ALL
    SELECT 'planning_scope_orphan', COUNT(*)
    FROM story_plan_binding AS binding
    LEFT JOIN authority_project AS project
      ON project.project_id = binding.project_id
    LEFT JOIN authority_book AS book
      ON book.project_id = binding.project_id AND book.book_id = binding.book_id
    LEFT JOIN authority_asset_version AS version
      ON version.asset_version_id = binding.asset_version_id
    LEFT JOIN authority_asset AS asset ON asset.asset_id = version.asset_id
    WHERE project.project_id IS NULL
       OR book.book_id IS NULL
       OR asset.project_id <> binding.project_id
    UNION ALL
    SELECT 'active_plan_scope_mismatch', COUNT(*)
    FROM active_story_plan_version AS active
    LEFT JOIN story_plan_binding AS binding
      ON binding.binding_id = active.binding_id
    WHERE binding.binding_id IS NULL
       OR (binding.project_id, binding.book_id, binding.asset_version_id) <>
          (active.project_id, active.book_id, active.asset_version_id)
    UNION ALL
    SELECT 'planning_dependency_scope_mismatch', COUNT(*)
    FROM asset_dependency_edge AS edge
    LEFT JOIN authority_book AS book
      ON book.project_id = edge.project_id AND book.book_id = edge.book_id
    LEFT JOIN authority_asset_version AS source_version
      ON source_version.asset_version_id = edge.source_asset_version_id
    LEFT JOIN authority_asset AS source_asset
      ON source_asset.asset_id = source_version.asset_id
    LEFT JOIN authority_asset_version AS dependent_version
      ON dependent_version.asset_version_id = edge.dependent_asset_version_id
    LEFT JOIN authority_asset AS dependent_asset
      ON dependent_asset.asset_id = dependent_version.asset_id
    WHERE book.book_id IS NULL
       OR source_asset.project_id <> edge.project_id
       OR dependent_asset.project_id <> edge.project_id
    """,
]


UPGRADE_STATEMENTS = [
    # The 0051 default was only a transition aid. Existing rows are explicitly
    # classified before all future writes become mandatory at the command API.
    "UPDATE authority_asset_version SET schema_version = 'legacy-unversioned.v1' WHERE schema_version IS NULL OR schema_version = ''",
    "ALTER TABLE authority_asset_version ALTER COLUMN schema_version DROP DEFAULT",
    "ALTER TABLE authority_asset_version VALIDATE CONSTRAINT authority_asset_version_schema_version_check",
    "ALTER TABLE authority_book ADD CONSTRAINT authority_book_project_identity_unique UNIQUE (project_id, book_id)",
    """
    CREATE OR REPLACE FUNCTION authority_require_asset_version_project(
        expected_project_id TEXT,
        expected_asset_version_id TEXT
    ) RETURNS VOID
    LANGUAGE plpgsql
    AS $$
    DECLARE actual_project_id TEXT;
    BEGIN
        IF expected_asset_version_id IS NULL OR expected_asset_version_id = '' THEN
            RETURN;
        END IF;
        SELECT asset.project_id INTO actual_project_id
        FROM authority_asset_version AS version
        JOIN authority_asset AS asset ON asset.asset_id = version.asset_id
        WHERE version.asset_version_id = expected_asset_version_id;
        IF actual_project_id IS NULL OR actual_project_id <> expected_project_id THEN
            RAISE EXCEPTION 'AssetVersion belongs to another Project or is missing'
                USING ERRCODE = '23514',
                      CONSTRAINT = 'authority_asset_version_project_scope_check';
        END IF;
    END;
    $$
    """,
    """
    CREATE OR REPLACE FUNCTION authority_require_operation_project(
        expected_project_id TEXT,
        expected_operation_id TEXT
    ) RETURNS VOID
    LANGUAGE plpgsql
    AS $$
    DECLARE actual_project_id TEXT;
    BEGIN
        IF expected_operation_id IS NULL OR expected_operation_id = '' THEN
            RETURN;
        END IF;
        SELECT project_id INTO actual_project_id
        FROM authority_operation WHERE operation_id = expected_operation_id;
        IF actual_project_id IS NULL OR actual_project_id <> expected_project_id THEN
            RAISE EXCEPTION 'Operation belongs to another Project or is missing'
                USING ERRCODE = '23514',
                      CONSTRAINT = 'authority_operation_project_scope_check';
        END IF;
    END;
    $$
    """,
    """
    CREATE OR REPLACE FUNCTION authority_validate_book_scope()
    RETURNS TRIGGER
    LANGUAGE plpgsql
    AS $$
    DECLARE workspace_project_id TEXT;
    BEGIN
        SELECT project_id INTO workspace_project_id
        FROM authority_workspace WHERE workspace_id = NEW.workspace_id;
        IF workspace_project_id IS NULL OR workspace_project_id <> NEW.project_id THEN
            RAISE EXCEPTION 'Book Workspace does not belong to Project'
                USING ERRCODE = '23514', CONSTRAINT = 'authority_book_workspace_project_check';
        END IF;
        PERFORM authority_require_asset_version_project(NEW.project_id, NEW.current_book_asset_version_id);
        PERFORM authority_require_asset_version_project(NEW.project_id, NEW.current_book_design_asset_version_id);
        PERFORM authority_require_operation_project(NEW.project_id, NEW.created_by_operation_id);
        PERFORM authority_require_operation_project(NEW.project_id, NEW.last_operation_id);
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER authority_book_scope_guard
    AFTER INSERT OR UPDATE ON authority_book
    DEFERRABLE INITIALLY IMMEDIATE
    FOR EACH ROW EXECUTE FUNCTION authority_validate_book_scope()
    """,
    """
    CREATE OR REPLACE FUNCTION authority_validate_scoped_asset_relation()
    RETURNS TRIGGER
    LANGUAGE plpgsql
    AS $$
    DECLARE payload JSONB := to_jsonb(NEW);
    DECLARE book_project_id TEXT;
    DECLARE book_workspace_id TEXT;
    DECLARE field_name TEXT;
    DECLARE asset_fields TEXT[];
    DECLARE operation_fields TEXT[];
    DECLARE version_asset_id TEXT;
    BEGIN
        SELECT project_id, workspace_id INTO book_project_id, book_workspace_id
        FROM authority_book WHERE book_id = payload->>'book_id';
        IF book_project_id IS NULL OR book_project_id <> payload->>'project_id' THEN
            RAISE EXCEPTION 'relationship Book does not belong to Project'
                USING ERRCODE = '23514', CONSTRAINT = 'authority_relation_book_project_check';
        END IF;
        IF payload ? 'workspace_id' AND book_workspace_id <> payload->>'workspace_id' THEN
            RAISE EXCEPTION 'relationship Workspace does not belong to Book'
                USING ERRCODE = '23514', CONSTRAINT = 'authority_relation_book_workspace_check';
        END IF;
        asset_fields := CASE TG_TABLE_NAME
            WHEN 'authority_book_design_candidate' THEN ARRAY['asset_version_id']
            WHEN 'authority_asset_dependency' THEN ARRAY['source_asset_version_id', 'target_asset_version_id']
            WHEN 'authority_asset_decision' THEN ARRAY['asset_version_id']
            WHEN 'authority_asset_activation' THEN ARRAY['asset_version_id']
            WHEN 'authority_asset_supersession' THEN ARRAY['previous_asset_version_id', 'successor_asset_version_id']
            WHEN 'authority_asset_evidence' THEN ARRAY['asset_version_id']
            ELSE ARRAY[]::TEXT[]
        END;
        FOREACH field_name IN ARRAY asset_fields LOOP
            PERFORM authority_require_asset_version_project(payload->>'project_id', payload->>field_name);
        END LOOP;
        IF payload ? 'asset_id' AND payload ? 'asset_version_id' THEN
            SELECT asset_id INTO version_asset_id
            FROM authority_asset_version
            WHERE asset_version_id = payload->>'asset_version_id';
            IF version_asset_id IS NULL OR version_asset_id <> payload->>'asset_id' THEN
                RAISE EXCEPTION 'AssetVersion does not belong to declared Asset'
                    USING ERRCODE = '23514', CONSTRAINT = 'authority_relation_asset_identity_check';
            END IF;
        END IF;
        IF TG_TABLE_NAME = 'authority_asset_activation' THEN
            PERFORM 1 FROM authority_asset_decision
            WHERE decision_id = payload->>'decision_id'
              AND project_id = payload->>'project_id'
              AND book_id = payload->>'book_id'
              AND asset_version_id = payload->>'asset_version_id';
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Activation Decision does not match Asset scope'
                    USING ERRCODE = '23514', CONSTRAINT = 'authority_activation_decision_scope_check';
            END IF;
        END IF;
        operation_fields := ARRAY[
            'created_by_operation_id', 'last_operation_id',
            'decided_by_operation_id', 'activated_by_operation_id',
            'superseded_by_operation_id'
        ];
        FOREACH field_name IN ARRAY operation_fields LOOP
            IF payload ? field_name THEN
                PERFORM authority_require_operation_project(payload->>'project_id', payload->>field_name);
            END IF;
        END LOOP;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER authority_book_design_candidate_scope_guard
    AFTER INSERT OR UPDATE ON authority_book_design_candidate
    DEFERRABLE INITIALLY IMMEDIATE
    FOR EACH ROW EXECUTE FUNCTION authority_validate_scoped_asset_relation()
    """,
    """
    CREATE CONSTRAINT TRIGGER authority_asset_dependency_scope_guard
    AFTER INSERT OR UPDATE ON authority_asset_dependency
    DEFERRABLE INITIALLY IMMEDIATE
    FOR EACH ROW EXECUTE FUNCTION authority_validate_scoped_asset_relation()
    """,
    """
    CREATE CONSTRAINT TRIGGER authority_asset_decision_scope_guard
    AFTER INSERT OR UPDATE ON authority_asset_decision
    DEFERRABLE INITIALLY IMMEDIATE
    FOR EACH ROW EXECUTE FUNCTION authority_validate_scoped_asset_relation()
    """,
    """
    CREATE CONSTRAINT TRIGGER authority_asset_activation_scope_guard
    AFTER INSERT OR UPDATE ON authority_asset_activation
    DEFERRABLE INITIALLY IMMEDIATE
    FOR EACH ROW EXECUTE FUNCTION authority_validate_scoped_asset_relation()
    """,
    """
    CREATE CONSTRAINT TRIGGER authority_asset_supersession_scope_guard
    AFTER INSERT OR UPDATE ON authority_asset_supersession
    DEFERRABLE INITIALLY IMMEDIATE
    FOR EACH ROW EXECUTE FUNCTION authority_validate_scoped_asset_relation()
    """,
    """
    CREATE CONSTRAINT TRIGGER authority_asset_evidence_scope_guard
    AFTER INSERT OR UPDATE ON authority_asset_evidence
    DEFERRABLE INITIALLY IMMEDIATE
    FOR EACH ROW EXECUTE FUNCTION authority_validate_scoped_asset_relation()
    """,
    "ALTER TABLE authority_book_design_candidate ADD CONSTRAINT authority_book_design_candidate_book_scope_fk FOREIGN KEY (project_id, workspace_id, book_id) REFERENCES authority_book(project_id, workspace_id, book_id) DEFERRABLE INITIALLY IMMEDIATE",
    "ALTER TABLE authority_asset_dependency ADD CONSTRAINT authority_asset_dependency_book_scope_fk FOREIGN KEY (project_id, book_id) REFERENCES authority_book(project_id, book_id) DEFERRABLE INITIALLY IMMEDIATE",
    "ALTER TABLE authority_asset_decision ADD CONSTRAINT authority_asset_decision_book_scope_fk FOREIGN KEY (project_id, book_id) REFERENCES authority_book(project_id, book_id) DEFERRABLE INITIALLY IMMEDIATE",
    "ALTER TABLE authority_asset_activation ADD CONSTRAINT authority_asset_activation_book_scope_fk FOREIGN KEY (project_id, book_id) REFERENCES authority_book(project_id, book_id) DEFERRABLE INITIALLY IMMEDIATE",
    "ALTER TABLE authority_asset_supersession ADD CONSTRAINT authority_asset_supersession_book_scope_fk FOREIGN KEY (project_id, book_id) REFERENCES authority_book(project_id, book_id) DEFERRABLE INITIALLY IMMEDIATE",
    "ALTER TABLE authority_asset_evidence ADD CONSTRAINT authority_asset_evidence_book_scope_fk FOREIGN KEY (project_id, book_id) REFERENCES authority_book(project_id, book_id) DEFERRABLE INITIALLY IMMEDIATE",
    "ALTER TABLE story_plan_binding ADD CONSTRAINT story_plan_binding_project_fk FOREIGN KEY (project_id) REFERENCES authority_project(project_id) DEFERRABLE INITIALLY IMMEDIATE",
    "ALTER TABLE story_plan_binding ADD CONSTRAINT story_plan_binding_book_scope_fk FOREIGN KEY (project_id, book_id) REFERENCES authority_book(project_id, book_id) DEFERRABLE INITIALLY IMMEDIATE",
    "ALTER TABLE story_plan_binding ADD CONSTRAINT story_plan_binding_scope_identity_unique UNIQUE (project_id, book_id, binding_id)",
    "ALTER TABLE active_story_plan_version ADD CONSTRAINT active_story_plan_binding_scope_fk FOREIGN KEY (project_id, book_id, binding_id) REFERENCES story_plan_binding(project_id, book_id, binding_id) DEFERRABLE INITIALLY IMMEDIATE",
    "ALTER TABLE asset_dependency_edge ADD CONSTRAINT asset_dependency_edge_book_scope_fk FOREIGN KEY (project_id, book_id) REFERENCES authority_book(project_id, book_id) DEFERRABLE INITIALLY IMMEDIATE",
    "ALTER TABLE story_plan_hierarchy ADD CONSTRAINT story_plan_hierarchy_book_scope_fk FOREIGN KEY (project_id, book_id) REFERENCES authority_book(project_id, book_id) DEFERRABLE INITIALLY IMMEDIATE",
    "ALTER TABLE story_plan_hierarchy ADD CONSTRAINT story_plan_hierarchy_parent_scope_fk FOREIGN KEY (project_id, book_id, parent_binding_id) REFERENCES story_plan_binding(project_id, book_id, binding_id) DEFERRABLE INITIALLY IMMEDIATE",
    "ALTER TABLE story_plan_hierarchy ADD CONSTRAINT story_plan_hierarchy_child_scope_fk FOREIGN KEY (project_id, book_id, child_binding_id) REFERENCES story_plan_binding(project_id, book_id, binding_id) DEFERRABLE INITIALLY IMMEDIATE",
    "ALTER TABLE planning_horizon ADD CONSTRAINT planning_horizon_book_scope_fk FOREIGN KEY (project_id, book_id) REFERENCES authority_book(project_id, book_id) DEFERRABLE INITIALLY IMMEDIATE",
    "ALTER TABLE story_production_cursor ADD CONSTRAINT story_production_cursor_book_scope_fk FOREIGN KEY (project_id, book_id) REFERENCES authority_book(project_id, book_id) DEFERRABLE INITIALLY IMMEDIATE",
    """
    CREATE OR REPLACE FUNCTION authority_validate_planning_scope()
    RETURNS TRIGGER
    LANGUAGE plpgsql
    AS $$
    DECLARE payload JSONB := to_jsonb(NEW);
    DECLARE book_project_id TEXT;
    DECLARE field_name TEXT;
    DECLARE asset_fields TEXT[];
    DECLARE operation_fields TEXT[];
    DECLARE binding_project_id TEXT;
    DECLARE binding_book_id TEXT;
    DECLARE binding_asset_version_id TEXT;
    BEGIN
        SELECT project_id INTO book_project_id
        FROM authority_book WHERE book_id = payload->>'book_id';
        IF book_project_id IS NULL OR book_project_id <> payload->>'project_id' THEN
            RAISE EXCEPTION 'Planning Book does not belong to Project'
                USING ERRCODE = '23514', CONSTRAINT = 'planning_book_project_scope_check';
        END IF;
        asset_fields := CASE TG_TABLE_NAME
            WHEN 'story_plan_binding' THEN ARRAY['asset_version_id', 'parent_version_id']
            WHEN 'active_story_plan_version' THEN ARRAY['asset_version_id']
            WHEN 'asset_dependency_edge' THEN ARRAY['source_asset_version_id', 'dependent_asset_version_id']
            ELSE ARRAY[]::TEXT[]
        END;
        FOREACH field_name IN ARRAY asset_fields LOOP
            PERFORM authority_require_asset_version_project(payload->>'project_id', payload->>field_name);
        END LOOP;
        operation_fields := ARRAY[
            'created_by_operation_id', 'activated_by_operation_id',
            'updated_by_operation_id'
        ];
        FOREACH field_name IN ARRAY operation_fields LOOP
            IF payload ? field_name THEN
                PERFORM authority_require_operation_project(
                    payload->>'project_id', payload->>field_name
                );
            END IF;
        END LOOP;
        IF TG_TABLE_NAME = 'active_story_plan_version' THEN
            SELECT project_id, book_id, asset_version_id
            INTO binding_project_id, binding_book_id, binding_asset_version_id
            FROM story_plan_binding WHERE binding_id = payload->>'binding_id';
            IF binding_project_id IS NULL
               OR (binding_project_id, binding_book_id, binding_asset_version_id) <>
                  (payload->>'project_id', payload->>'book_id', payload->>'asset_version_id') THEN
                RAISE EXCEPTION 'Active Plan does not match its Binding scope'
                    USING ERRCODE = '23514', CONSTRAINT = 'active_story_plan_binding_scope_check';
            END IF;
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER story_plan_binding_asset_scope_guard
    AFTER INSERT OR UPDATE ON story_plan_binding
    DEFERRABLE INITIALLY IMMEDIATE
    FOR EACH ROW EXECUTE FUNCTION authority_validate_planning_scope()
    """,
    """
    CREATE CONSTRAINT TRIGGER active_story_plan_asset_scope_guard
    AFTER INSERT OR UPDATE ON active_story_plan_version
    DEFERRABLE INITIALLY IMMEDIATE
    FOR EACH ROW EXECUTE FUNCTION authority_validate_planning_scope()
    """,
    """
    CREATE CONSTRAINT TRIGGER asset_dependency_edge_scope_guard
    AFTER INSERT OR UPDATE ON asset_dependency_edge
    DEFERRABLE INITIALLY IMMEDIATE
    FOR EACH ROW EXECUTE FUNCTION authority_validate_planning_scope()
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []
