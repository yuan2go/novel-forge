from __future__ import annotations

MIGRATION_ID = "20260927_0146_edition_prefix_inheritance"
DOWN_REVISION = "20260927_0145_edition_execution_windows"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "retain immutable prefix proof and append a corrected edition; never rewrite accepted sources"

UPGRADE_STATEMENTS = [
    """CREATE TABLE authority_book_edition_prefix (
 book_run_id TEXT PRIMARY KEY REFERENCES authority_book_production(book_run_id),
 revision_id TEXT NOT NULL REFERENCES authority_book_edition_revision(revision_id),
 source_book_run_id TEXT NOT NULL REFERENCES authority_book_production(book_run_id),
 through_chapter INTEGER NOT NULL CHECK(through_chapter>0),
 source_acceptance_id TEXT NOT NULL REFERENCES authority_book_chapter_acceptance(acceptance_id),
 content JSONB NOT NULL,
 created_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
 CHECK(book_run_id<>source_book_run_id)
)""",
    """CREATE FUNCTION authority_book_source_run(target_run text, target_chapter integer) RETURNS text
LANGUAGE sql STABLE AS $$
 WITH RECURSIVE lineage(run_id,depth) AS (
   SELECT target_run,0
   UNION ALL
   SELECT prefix.source_book_run_id,lineage.depth+1 FROM lineage
   JOIN authority_book_edition_prefix prefix ON prefix.book_run_id=lineage.run_id
   WHERE target_chapter<=prefix.through_chapter AND lineage.depth<64
 ) SELECT run_id FROM lineage ORDER BY depth DESC LIMIT 1
$$""",
    """CREATE FUNCTION authority_book_acceptance_lineage(target_run text)
RETURNS SETOF authority_book_chapter_acceptance LANGUAGE sql STABLE AS $$
 WITH RECURSIVE lineage(run_id,ceiling,depth) AS (
   SELECT target_run,2147483647,0
   UNION ALL
   SELECT prefix.source_book_run_id,LEAST(lineage.ceiling,prefix.through_chapter),lineage.depth+1
   FROM lineage JOIN authority_book_edition_prefix prefix ON prefix.book_run_id=lineage.run_id
   WHERE lineage.depth<64
 ) SELECT accepted.* FROM lineage
 JOIN authority_book_chapter_acceptance accepted ON accepted.book_run_id=lineage.run_id
 LEFT JOIN authority_book_edition_prefix inherited ON inherited.book_run_id=lineage.run_id
 WHERE accepted.status='COMMITTED' AND accepted.chapter_number<=lineage.ceiling
   AND accepted.chapter_number>COALESCE(inherited.through_chapter,0)
$$""",
    """CREATE FUNCTION authority_edition_prefix_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE target record; source record; bound record; frontier record;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Edition prefix inheritance is immutable' USING ERRCODE='23514'; END IF;
 SELECT * INTO target FROM authority_book_production WHERE book_run_id=NEW.book_run_id;
 SELECT * INTO source FROM authority_book_production WHERE book_run_id=NEW.source_book_run_id;
 SELECT * INTO bound FROM authority_book_edition_run WHERE book_run_id=NEW.book_run_id;
 SELECT a.*, p.status AS projection_status INTO frontier
 FROM authority_book_acceptance_lineage(NEW.source_book_run_id) a
 JOIN authority_book_narrative_projection_set p ON p.projection_set_id=a.longform_projection_set_id
 WHERE a.acceptance_id=NEW.source_acceptance_id AND a.chapter_number=NEW.through_chapter;
 IF target.book_id IS DISTINCT FROM source.book_id OR target.project_id IS DISTINCT FROM source.project_id
    OR target.workspace_id IS DISTINCT FROM source.workspace_id
    OR bound.revision_id IS DISTINCT FROM NEW.revision_id OR bound.role<>'VALIDATION'
    OR target.accepted_through_chapter<>0 OR target.active_chapter_request_id IS NOT NULL
    OR source.accepted_through_chapter<NEW.through_chapter OR frontier.projection_status IS DISTINCT FROM 'COMPLETE'
    OR NEW.content->>'contract_version' IS DISTINCT FROM 'book-edition-prefix-inheritance.v1'
    OR (NEW.content->>'through_chapter')::integer IS DISTINCT FROM NEW.through_chapter
    OR jsonb_array_length(NEW.content->'accepted_sources') IS DISTINCT FROM NEW.through_chapter
    OR EXISTS(SELECT 1 FROM authority_book_edition_prefix p WHERE p.book_run_id=NEW.source_book_run_id
              AND authority_book_source_run(p.book_run_id,1)=NEW.book_run_id)
 THEN RAISE EXCEPTION 'Prefix inheritance requires exact same-Book committed sources and an empty bound target' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$""",
    """CREATE TRIGGER authority_edition_prefix_immutable BEFORE INSERT OR UPDATE OR DELETE ON authority_book_edition_prefix FOR EACH ROW EXECUTE FUNCTION authority_edition_prefix_guard()""",
    """CREATE INDEX authority_edition_prefix_revision_id_idx ON authority_book_edition_prefix(revision_id)""",
    """CREATE INDEX authority_edition_prefix_source_book_run_id_idx ON authority_book_edition_prefix(source_book_run_id)""",
    """CREATE INDEX authority_edition_prefix_source_acceptance_id_idx ON authority_book_edition_prefix(source_acceptance_id)""",
    """CREATE INDEX authority_edition_prefix_created_by_operation_id_idx ON authority_book_edition_prefix(created_by_operation_id)""",
    """
    CREATE OR REPLACE FUNCTION authority_reality_guard() RETURNS trigger LANGUAGE plpgsql AS $$
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
                IS DISTINCT FROM (authority_book_source_run(NEW.book_run_id, NEW.chapter_number-1), NEW.project_id, NEW.book_id, NEW.chapter_number-1) THEN
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
    """
    CREATE OR REPLACE FUNCTION authority_project_reality(source_acceptance_id text) RETURNS text LANGUAGE plpgsql AS $$
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
        WHERE book_run_id=authority_book_source_run(source.book_run_id, source.chapter_number-1) AND chapter_number=source.chapter_number-1;
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
]
DOWNGRADE_STATEMENTS: list[str] = []
