from __future__ import annotations

MIGRATION_ID = "20260906_0115_reality_event_index"
DOWN_REVISION = "20260906_0114_narrative_reality"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = "rebuild derived event locators from immutable accepted outcomes"

UPGRADE_STATEMENTS = [
    """
    CREATE TABLE authority_reality_event_index (
        book_run_id text NOT NULL REFERENCES authority_book_production(book_run_id),
        event_id text NOT NULL,
        revision_id text NOT NULL REFERENCES authority_narrative_reality_revision(revision_id),
        event_ordinal integer NOT NULL CHECK (event_ordinal >= 0),
        accepted_chapter integer NOT NULL CHECK (accepted_chapter > 0),
        world_tick boolean NOT NULL,
        timeline_id text,
        end_ordinal bigint,
        PRIMARY KEY (book_run_id, event_id),
        UNIQUE (revision_id, event_ordinal)
    )
    """,
    "CREATE INDEX authority_reality_event_clock_idx ON authority_reality_event_index(book_run_id, timeline_id, end_ordinal DESC, accepted_chapter) WHERE world_tick",
    "CREATE INDEX authority_reality_event_frontier_idx ON authority_reality_event_index(book_run_id, accepted_chapter, event_ordinal)",
    """
    CREATE FUNCTION authority_reality_event_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE source jsonb; chapter integer; owner text;
    BEGIN
        IF TG_OP <> 'INSERT' THEN
            RAISE EXCEPTION 'Accepted Reality event locators are immutable' USING ERRCODE='23514';
        END IF;
        SELECT v.content->'state_events'->NEW.event_ordinal, r.chapter_number, r.book_run_id
        INTO source, chapter, owner
        FROM authority_narrative_reality_revision r
        JOIN authority_asset_version v ON v.asset_version_id=r.outcome_version_id
        WHERE r.revision_id=NEW.revision_id;
        IF NOT FOUND OR source IS NULL OR
            (NEW.book_run_id, NEW.event_id, NEW.accepted_chapter, NEW.world_tick, NEW.timeline_id, NEW.end_ordinal)
            IS DISTINCT FROM (owner, source->>'event_id', chapter, source->'mutation'->'payload' ? 'world_transition',
                CASE WHEN source->'story_time'->>'precision' <> 'UNSPECIFIED' THEN source->'story_time'->>'timeline_id' END,
                CASE WHEN source->'story_time'->>'precision' <> 'UNSPECIFIED' THEN (source->'story_time'->>'end_ordinal')::bigint END) THEN
            RAISE EXCEPTION 'Reality event locator must resolve its exact accepted source' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
    END $$
    """,
    "CREATE TRIGGER authority_reality_event_immutable BEFORE INSERT OR UPDATE OR DELETE ON authority_reality_event_index FOR EACH ROW EXECUTE FUNCTION authority_reality_event_guard()",
    """
    CREATE FUNCTION authority_index_reality_events(target_revision_id text) RETURNS void LANGUAGE sql AS $$
        INSERT INTO authority_reality_event_index
        SELECT r.book_run_id, event->>'event_id', r.revision_id, ordinal::integer-1, r.chapter_number,
            event->'mutation'->'payload' ? 'world_transition',
            CASE WHEN event->'story_time'->>'precision' <> 'UNSPECIFIED' THEN event->'story_time'->>'timeline_id' END,
            CASE WHEN event->'story_time'->>'precision' <> 'UNSPECIFIED' THEN (event->'story_time'->>'end_ordinal')::bigint END
        FROM authority_narrative_reality_revision r
        JOIN authority_asset_version v ON v.asset_version_id=r.outcome_version_id
        CROSS JOIN LATERAL jsonb_array_elements(v.content->'state_events') WITH ORDINALITY AS events(event, ordinal)
        WHERE r.revision_id=target_revision_id
        ON CONFLICT (revision_id, event_ordinal) DO NOTHING
    $$
    """,
    """
    CREATE FUNCTION authority_reality_event_after_insert() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        PERFORM authority_index_reality_events(NEW.revision_id);
        RETURN NEW;
    END $$
    """,
    "CREATE TRIGGER authority_reality_event_projection AFTER INSERT ON authority_narrative_reality_revision FOR EACH ROW EXECUTE FUNCTION authority_reality_event_after_insert()",
    """
    DO $$ DECLARE r record; BEGIN
        FOR r IN SELECT revision_id FROM authority_narrative_reality_revision ORDER BY book_run_id, chapter_number
        LOOP PERFORM authority_index_reality_events(r.revision_id); END LOOP;
    END $$
    """,
]
