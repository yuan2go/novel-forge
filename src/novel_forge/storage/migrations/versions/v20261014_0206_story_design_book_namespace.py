from __future__ import annotations

MIGRATION_ID = "20261014_0206_story_design_book_namespace"
DOWN_REVISION = "20261014_0205_source_observation_generation_isolation"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Bind Story Design current projections to proven Book and design-layer identities; restore wrongly superseded states only through scoped owner reconciliation."

UPGRADE_STATEMENTS = [
    """CREATE FUNCTION authority_story_design_book_scope(p_project TEXT, p_asset TEXT) RETURNS TEXT
    LANGUAGE plpgsql AS $$
    DECLARE scopes TEXT[]; resolved TEXT;
    BEGIN
      SELECT array_agg(DISTINCT scope.book_id) INTO scopes FROM (
        SELECT generation.book_id FROM authority_story_planning_candidate candidate
        JOIN authority_story_planning_generation generation USING(generation_id,project_id,book_id)
        WHERE candidate.project_id=p_project AND candidate.candidate_asset_version_id=p_asset
        UNION ALL
        SELECT binding.book_id FROM story_plan_binding binding
        WHERE binding.project_id=p_project AND binding.asset_version_id=p_asset
        UNION ALL
        SELECT book_id FROM authority_book WHERE project_id=p_project AND current_book_design_asset_version_id=p_asset
        UNION ALL
        SELECT NULLIF(version.content->>'book_id','') FROM authority_asset_version version
        JOIN authority_asset asset USING(asset_id)
        WHERE asset.project_id=p_project AND version.asset_version_id=p_asset
      ) scope WHERE scope.book_id IS NOT NULL;
      IF cardinality(scopes)>1 THEN RAISE EXCEPTION 'Story Design Book lineage is ambiguous'; END IF;
      resolved := scopes[1];
      IF resolved IS NOT NULL AND NOT EXISTS(SELECT 1 FROM authority_book
        WHERE project_id=p_project AND book_id=resolved) THEN
        RAISE EXCEPTION 'Story Design Book lineage has no owning Book';
      END IF;
      RETURN resolved;
    END $$""",
    "ALTER TABLE authority_story_design_version_state ADD COLUMN book_id TEXT",
    "UPDATE authority_story_design_version_state SET book_id=authority_story_design_book_scope(project_id,asset_version_id)",
    """ALTER TABLE authority_story_design_version_state
       ADD CONSTRAINT story_design_book_scope_fk FOREIGN KEY(project_id,book_id) REFERENCES authority_book(project_id,book_id),
       ADD COLUMN scope_key TEXT GENERATED ALWAYS AS (CASE WHEN book_id IS NULL THEN 'LEGACY_UNBOUND' ELSE 'BOOK:'||book_id END) STORED,
       ADD COLUMN scope_layer TEXT GENERATED ALWAYS AS (CASE WHEN book_id IS NULL THEN 'LEGACY_UNBOUND' ELSE design_scope END) STORED""",
    "ALTER TABLE authority_story_design_version_state ADD CONSTRAINT story_design_scoped_version_unique UNIQUE(project_id,asset_version_id,scope_key,scope_layer)",
    "CREATE INDEX story_design_book_layer_idx ON authority_story_design_version_state(project_id,book_id,design_scope,logical_key)",
    """CREATE FUNCTION authority_story_design_scope_binding() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    DECLARE resolved TEXT;
    BEGIN
      IF TG_OP='INSERT' THEN
        resolved := authority_story_design_book_scope(NEW.project_id,NEW.asset_version_id);
        IF NEW.book_id IS NOT NULL AND NEW.book_id IS DISTINCT FROM resolved THEN
          RAISE EXCEPTION 'Story Design Book scope differs from immutable lineage';
        END IF;
        NEW.book_id := resolved;
      ELSIF NEW.book_id IS DISTINCT FROM OLD.book_id OR NEW.design_scope IS DISTINCT FROM OLD.design_scope THEN
        RAISE EXCEPTION 'Story Design Book and design-layer scope are immutable';
      END IF;
      RETURN NEW;
    END $$""",
    "CREATE TRIGGER story_design_scope_binding BEFORE INSERT OR UPDATE ON authority_story_design_version_state FOR EACH ROW EXECUTE FUNCTION authority_story_design_scope_binding()",
    """ALTER TABLE authority_story_design_active_version ADD COLUMN book_id TEXT,
       ADD COLUMN scope_key TEXT GENERATED ALWAYS AS (CASE WHEN book_id IS NULL THEN 'LEGACY_UNBOUND' ELSE 'BOOK:'||book_id END) STORED,
       ADD COLUMN scope_layer TEXT NOT NULL DEFAULT 'LEGACY_UNBOUND'""",
    """UPDATE authority_story_design_active_version active SET book_id=state.book_id,scope_layer=state.scope_layer
       FROM authority_story_design_version_state state WHERE state.project_id=active.project_id AND state.asset_version_id=active.asset_version_id""",
    """ALTER TABLE authority_story_design_active_version DROP CONSTRAINT authority_story_design_active_version_pkey,
       ADD PRIMARY KEY(project_id,scope_key,scope_layer,logical_key),
       ADD CONSTRAINT story_design_active_scoped_version_fk FOREIGN KEY(project_id,asset_version_id,scope_key,scope_layer)
         REFERENCES authority_story_design_version_state(project_id,asset_version_id,scope_key,scope_layer)""",
    "ALTER TABLE authority_story_design_transition DROP CONSTRAINT authority_story_design_transition_transition_type_check",
    """ALTER TABLE authority_story_design_transition ADD CONSTRAINT authority_story_design_transition_transition_type_check
       CHECK(transition_type IN ('ENROLL','MATERIALIZE','STRUCTURAL_VALIDATE','SEMANTIC_VALIDATE','QUALIFY','SUBMIT_APPROVAL','APPROVE','ACTIVATE','REJECT','RECONCILE_SCOPE'))""",
]

DOWNGRADE_STATEMENTS: list[str] = []
