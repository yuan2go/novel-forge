from __future__ import annotations

MIGRATION_ID = "20260906_0117_world_causal_event_locators"
DOWN_REVISION = "20260906_0116_book_control_policy"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = "rebuild derived world event identities from immutable accepted outcomes; never alter accepted payloads"

UPGRADE_STATEMENTS = [
    "ALTER TABLE authority_reality_event_index ADD COLUMN state_kind text, ADD COLUMN entity_key text, ADD COLUMN batch_local_id text, ADD COLUMN fact_origin_kind text",
    "DROP TRIGGER authority_reality_event_immutable ON authority_reality_event_index",
    """
    UPDATE authority_reality_event_index i SET
        state_kind=v.content->'state_events'->i.event_ordinal->>'state_kind',
        entity_key=v.content->'state_events'->i.event_ordinal->'identity'->>'entity_key',
        batch_local_id=v.content->'state_events'->i.event_ordinal->'mutation'->'payload'->'causal_batch'->>'local_id',
        fact_origin_kind=v.content->'state_events'->i.event_ordinal->'mutation'->'payload'->'fact_origin'->>'kind'
    FROM authority_narrative_reality_revision r
    JOIN authority_asset_version v ON v.asset_version_id=r.outcome_version_id
    WHERE r.revision_id=i.revision_id
    """,
    "ALTER TABLE authority_reality_event_index ALTER COLUMN state_kind SET NOT NULL, ALTER COLUMN entity_key SET NOT NULL",
    "CREATE TRIGGER authority_reality_event_immutable BEFORE INSERT OR UPDATE OR DELETE ON authority_reality_event_index FOR EACH ROW EXECUTE FUNCTION authority_reality_event_guard()",
    """
    CREATE FUNCTION authority_reality_causal_locator_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE source jsonb;
    BEGIN
        SELECT v.content->'state_events'->NEW.event_ordinal INTO source
        FROM authority_narrative_reality_revision r
        JOIN authority_asset_version v ON v.asset_version_id=r.outcome_version_id
        WHERE r.revision_id=NEW.revision_id;
        IF NOT FOUND OR source IS NULL OR
            (NEW.state_kind, NEW.entity_key, NEW.batch_local_id, NEW.fact_origin_kind)
            IS DISTINCT FROM (source->>'state_kind', source->'identity'->>'entity_key',
                source->'mutation'->'payload'->'causal_batch'->>'local_id',
                source->'mutation'->'payload'->'fact_origin'->>'kind') THEN
            RAISE EXCEPTION 'Causal locator must project its exact accepted event' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
    END $$
    """,
    "CREATE TRIGGER authority_reality_causal_locator_exact BEFORE INSERT ON authority_reality_event_index FOR EACH ROW EXECUTE FUNCTION authority_reality_causal_locator_guard()",
    "CREATE UNIQUE INDEX authority_reality_batch_local_idx ON authority_reality_event_index(revision_id, batch_local_id) WHERE batch_local_id IS NOT NULL",
    "CREATE INDEX authority_reality_entity_clock_idx ON authority_reality_event_index(book_run_id, state_kind, entity_key, timeline_id, end_ordinal DESC, accepted_chapter) WHERE world_tick AND timeline_id IS NOT NULL",
    """
    CREATE OR REPLACE FUNCTION authority_index_reality_events(target_revision_id text) RETURNS void LANGUAGE sql AS $$
        INSERT INTO authority_reality_event_index (
            book_run_id, event_id, revision_id, event_ordinal, accepted_chapter,
            world_tick, timeline_id, end_ordinal, state_kind, entity_key,
            batch_local_id, fact_origin_kind
        )
        SELECT r.book_run_id, event->>'event_id', r.revision_id, ordinal::integer-1, r.chapter_number,
            event->'mutation'->'payload' ? 'world_transition',
            CASE WHEN event->'story_time'->>'precision' <> 'UNSPECIFIED' THEN event->'story_time'->>'timeline_id' END,
            CASE WHEN event->'story_time'->>'precision' <> 'UNSPECIFIED' THEN (event->'story_time'->>'end_ordinal')::bigint END,
            event->>'state_kind', event->'identity'->>'entity_key',
            event->'mutation'->'payload'->'causal_batch'->>'local_id',
            event->'mutation'->'payload'->'fact_origin'->>'kind'
        FROM authority_narrative_reality_revision r
        JOIN authority_asset_version v ON v.asset_version_id=r.outcome_version_id
        CROSS JOIN LATERAL jsonb_array_elements(v.content->'state_events') WITH ORDINALITY AS events(event, ordinal)
        WHERE r.revision_id=target_revision_id
        ON CONFLICT (revision_id, event_ordinal) DO NOTHING
    $$
    """,
]
