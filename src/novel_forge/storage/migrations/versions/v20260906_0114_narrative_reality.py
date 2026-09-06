from __future__ import annotations

MIGRATION_ID = "20260906_0114_narrative_reality"
DOWN_REVISION = "20260905_0113_policy_completion_fk_indexes"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = "rebuild missing derived Reality revisions from committed acceptance; never rewrite accepted sources"

UPGRADE_STATEMENTS = [
    """
    CREATE FUNCTION authority_reality_digest(parts text[]) RETURNS text
    LANGUAGE sql IMMUTABLE STRICT AS $$
        SELECT 'sha256:' || encode(sha256(convert_to(
            string_agg(octet_length(part)::text || ':' || part, '' ORDER BY ordinal),
            'UTF8')), 'hex')
        FROM unnest(parts) WITH ORDINALITY AS items(part, ordinal)
    $$
    """,
    """
    CREATE TABLE authority_narrative_reality_revision (
        revision_id text PRIMARY KEY,
        project_id text NOT NULL,
        book_id text NOT NULL,
        book_run_id text NOT NULL REFERENCES authority_book_production(book_run_id),
        chapter_number integer NOT NULL CHECK (chapter_number > 0),
        acceptance_id text NOT NULL UNIQUE REFERENCES authority_book_chapter_acceptance(acceptance_id),
        outcome_version_id text NOT NULL REFERENCES authority_asset_version(asset_version_id),
        state_version_id text NOT NULL REFERENCES authority_asset_version(asset_version_id),
        canon_version_id text NOT NULL REFERENCES authority_asset_version(asset_version_id),
        projection_set_id text NOT NULL UNIQUE REFERENCES authority_book_narrative_projection_set(projection_set_id),
        source_digest text NOT NULL,
        parent_revision_id text REFERENCES authority_narrative_reality_revision(revision_id),
        UNIQUE (book_run_id, chapter_number),
        CHECK ((chapter_number = 1) = (parent_revision_id IS NULL))
    )
    """,
    "CREATE INDEX authority_reality_scope_idx ON authority_narrative_reality_revision(project_id, book_id, chapter_number)",
    "CREATE INDEX authority_reality_outcome_idx ON authority_narrative_reality_revision(outcome_version_id)",
    "CREATE INDEX authority_reality_state_idx ON authority_narrative_reality_revision(state_version_id)",
    "CREATE INDEX authority_reality_canon_idx ON authority_narrative_reality_revision(canon_version_id)",
    "CREATE INDEX authority_reality_parent_idx ON authority_narrative_reality_revision(parent_revision_id)",
    """
    CREATE FUNCTION authority_reality_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE source record; parent record; expected_digest text; expected_id text;
    BEGIN
        IF TG_OP <> 'INSERT' THEN
            RAISE EXCEPTION 'Narrative Reality revisions are immutable' USING ERRCODE='23514';
        END IF;
        SELECT a.*, b.book_id, p.projection_hash,
               o.content_hash AS outcome_hash, s.content_hash AS state_hash,
               c.content_hash AS canon_hash
        INTO source
        FROM authority_book_chapter_acceptance a
        JOIN authority_book_production b ON b.book_run_id=a.book_run_id
        JOIN authority_book_narrative_projection_set p ON p.projection_set_id=a.longform_projection_set_id
        JOIN authority_asset_version o ON o.asset_version_id=a.chapter_outcome_asset_version_id
        JOIN authority_asset_version s ON s.asset_version_id=a.story_state_asset_version_id
        JOIN authority_asset_version c ON c.asset_version_id=a.canon_snapshot_asset_version_id
        WHERE a.acceptance_id=NEW.acceptance_id AND a.status='COMMITTED' AND p.status='COMPLETE';
        IF NOT FOUND OR (NEW.project_id, NEW.book_id, NEW.book_run_id, NEW.chapter_number,
            NEW.outcome_version_id, NEW.state_version_id, NEW.canon_version_id, NEW.projection_set_id)
            IS DISTINCT FROM (source.project_id, source.book_id, source.book_run_id, source.chapter_number,
            source.chapter_outcome_asset_version_id, source.story_state_asset_version_id,
            source.canon_snapshot_asset_version_id, source.longform_projection_set_id) THEN
            RAISE EXCEPTION 'Reality requires exact committed acceptance sources' USING ERRCODE='23514';
        END IF;
        IF NEW.chapter_number > 1 THEN
            SELECT * INTO parent FROM authority_narrative_reality_revision
            WHERE revision_id=NEW.parent_revision_id;
            IF NOT FOUND OR (parent.book_run_id, parent.project_id, parent.book_id, parent.chapter_number)
                IS DISTINCT FROM (NEW.book_run_id, NEW.project_id, NEW.book_id, NEW.chapter_number-1) THEN
                RAISE EXCEPTION 'Reality parent must be the immediately preceding accepted frontier' USING ERRCODE='23514';
            END IF;
        END IF;
        expected_digest := authority_reality_digest(ARRAY[source.canon_hash, source.outcome_hash, source.projection_hash, source.state_hash]);
        expected_id := 'reality:' || authority_reality_digest(ARRAY['narrative-reality.v1',
            NEW.project_id, NEW.book_id, NEW.book_run_id, NEW.chapter_number::text,
            NEW.acceptance_id, NEW.outcome_version_id, NEW.state_version_id,
            NEW.canon_version_id, NEW.projection_set_id, expected_digest, COALESCE(NEW.parent_revision_id, '')]);
        IF NEW.source_digest <> expected_digest OR NEW.revision_id <> expected_id THEN
            RAISE EXCEPTION 'Reality identity must bind exact source hashes and parent' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
    END $$
    """,
    "CREATE TRIGGER authority_reality_immutable BEFORE INSERT OR UPDATE OR DELETE ON authority_narrative_reality_revision FOR EACH ROW EXECUTE FUNCTION authority_reality_guard()",
    """
    CREATE FUNCTION authority_project_reality(source_acceptance_id text) RETURNS text LANGUAGE plpgsql AS $$
    DECLARE source record; parent_id text; digest text; identity text;
    BEGIN
        SELECT a.*, b.book_id, p.projection_hash,
               o.content_hash AS outcome_hash, s.content_hash AS state_hash, c.content_hash AS canon_hash
        INTO source FROM authority_book_chapter_acceptance a
        JOIN authority_book_production b ON b.book_run_id=a.book_run_id
        JOIN authority_book_narrative_projection_set p ON p.projection_set_id=a.longform_projection_set_id
        JOIN authority_asset_version o ON o.asset_version_id=a.chapter_outcome_asset_version_id
        JOIN authority_asset_version s ON s.asset_version_id=a.story_state_asset_version_id
        JOIN authority_asset_version c ON c.asset_version_id=a.canon_snapshot_asset_version_id
        WHERE a.acceptance_id=source_acceptance_id AND a.status='COMMITTED' AND p.status='COMPLETE';
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Reality source is not committed and complete' USING ERRCODE='23514';
        END IF;
        SELECT revision_id INTO parent_id FROM authority_narrative_reality_revision
        WHERE book_run_id=source.book_run_id AND chapter_number=source.chapter_number-1;
        digest := authority_reality_digest(ARRAY[source.canon_hash, source.outcome_hash, source.projection_hash, source.state_hash]);
        identity := 'reality:' || authority_reality_digest(ARRAY['narrative-reality.v1',
            source.project_id, source.book_id, source.book_run_id, source.chapter_number::text,
            source.acceptance_id, source.chapter_outcome_asset_version_id,
            source.story_state_asset_version_id, source.canon_snapshot_asset_version_id,
            source.longform_projection_set_id, digest, COALESCE(parent_id, '')]);
        INSERT INTO authority_narrative_reality_revision VALUES (
            identity, source.project_id, source.book_id, source.book_run_id, source.chapter_number,
            source.acceptance_id, source.chapter_outcome_asset_version_id, source.story_state_asset_version_id,
            source.canon_snapshot_asset_version_id, source.longform_projection_set_id, digest, parent_id
        ) ON CONFLICT (revision_id) DO NOTHING;
        RETURN identity;
    END $$
    """,
    """
    DO $$ DECLARE accepted record; BEGIN
        FOR accepted IN SELECT a.acceptance_id FROM authority_book_chapter_acceptance a
            JOIN authority_book_narrative_projection_set p ON p.projection_set_id=a.longform_projection_set_id
            WHERE a.status='COMMITTED' AND p.status='COMPLETE' ORDER BY a.book_run_id, a.chapter_number
        LOOP PERFORM authority_project_reality(accepted.acceptance_id); END LOOP;
    END $$
    """,
]
