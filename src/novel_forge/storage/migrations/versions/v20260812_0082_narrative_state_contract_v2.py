from __future__ import annotations


MIGRATION_ID = "20260812_0082_narrative_state_contract_v2"
DOWN_REVISION = "20260811_0081_source_intelligence_router"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = (
    "repair invalid immutable ChapterOutcome lineage through Book Authority, then "
    "rebuild the derived Narrative State v2 projection from committed acceptances"
)


UPGRADE_STATEMENTS = [
    "DROP VIEW authority_temporal_state_event_projection",
    """
    ALTER TABLE authority_story_state_reducer_application
      ADD COLUMN event_id TEXT,
      ADD COLUMN state_kind TEXT,
      ADD COLUMN entity_key TEXT,
      ADD COLUMN reducer_semantics TEXT,
      ADD COLUMN accepted_chapter INTEGER
    """,
    """
    UPDATE authority_story_state_reducer_application AS application
    SET event_id=application.idempotency_key,
        state_kind=application.output_state_type,
        entity_key=application.reducer_key,
        reducer_semantics='LEGACY_V1_RECORDED_APPLICATION',
        accepted_chapter=COALESCE(
          NULLIF(outcome.content->>'chapter_number', '')::integer,
          application.current_state_version
        )
    FROM authority_asset_version AS outcome
    WHERE outcome.asset_version_id=application.chapter_outcome_asset_version_id
    """,
    """
    ALTER TABLE authority_story_state_reducer_application
      ALTER COLUMN event_id SET NOT NULL,
      ALTER COLUMN state_kind SET NOT NULL,
      ALTER COLUMN entity_key SET NOT NULL,
      ALTER COLUMN reducer_semantics SET NOT NULL,
      ALTER COLUMN accepted_chapter SET NOT NULL,
      ADD CONSTRAINT authority_story_reducer_event_id_check CHECK (
        event_id<>''
      ),
      ADD CONSTRAINT authority_story_reducer_state_kind_check CHECK (
        state_kind<>''
      ),
      ADD CONSTRAINT authority_story_reducer_entity_key_check CHECK (
        entity_key<>''
      ),
      ADD CONSTRAINT authority_story_reducer_accepted_chapter_check CHECK (
        accepted_chapter>0
      )
    """,
    """
    DO $$
    DECLARE target_constraint TEXT;
    BEGIN
      SELECT constraint_name INTO target_constraint
      FROM information_schema.table_constraints
      WHERE table_schema=current_schema()
        AND table_name='authority_story_state_reducer_application'
        AND constraint_type='UNIQUE'
        AND constraint_name IN (
          SELECT conname
          FROM pg_constraint
          WHERE conrelid='authority_story_state_reducer_application'::regclass
            AND pg_get_constraintdef(oid) LIKE
              'UNIQUE (project_id, chapter_outcome_asset_version_id, reducer_key)%'
        )
      LIMIT 1;
      IF target_constraint IS NOT NULL THEN
        EXECUTE format(
          'ALTER TABLE authority_story_state_reducer_application DROP CONSTRAINT %I',
          target_constraint
        );
      END IF;
    END $$
    """,
    """
    CREATE UNIQUE INDEX authority_story_reducer_event_identity_idx
    ON authority_story_state_reducer_application(project_id, event_id)
    """,
    """
    CREATE INDEX authority_story_reducer_entity_replay_idx
    ON authority_story_state_reducer_application(
      project_id, state_kind, entity_key, accepted_chapter
    )
    """,
    """
    CREATE VIEW authority_narrative_state_event_projection AS
    SELECT acceptance.project_id,
           production.book_id,
           acceptance.book_run_id,
           acceptance.acceptance_id,
           acceptance.acceptance_operation_id,
           acceptance_operation.trace_id,
           acceptance.chapter_number AS accepted_chapter,
           acceptance.chapter_outcome_asset_version_id,
           event.payload AS event_payload,
           event.event_ordinal,
           acceptance.created_at AS recorded_at
    FROM authority_book_chapter_acceptance AS acceptance
    JOIN authority_book_production AS production
      ON production.book_run_id=acceptance.book_run_id
     AND production.project_id=acceptance.project_id
    JOIN authority_operation AS acceptance_operation
      ON acceptance_operation.operation_id=acceptance.acceptance_operation_id
     AND acceptance_operation.project_id=acceptance.project_id
     AND acceptance_operation.status='SUCCEEDED'
    JOIN authority_asset_version AS outcome_version
      ON outcome_version.asset_version_id=
         acceptance.chapter_outcome_asset_version_id
     AND outcome_version.lifecycle IN ('ACTIVE', 'SUPERSEDED')
     AND outcome_version.eligibility='ELIGIBLE'
     AND outcome_version.governance='CLEAR'
    JOIN authority_asset AS outcome_asset
      ON outcome_asset.asset_id=outcome_version.asset_id
     AND outcome_asset.project_id=acceptance.project_id
     AND outcome_asset.asset_type='chapter_outcome'
    CROSS JOIN LATERAL jsonb_array_elements(
      outcome_version.content->'state_events'
    ) WITH ORDINALITY AS event(payload, event_ordinal)
    WHERE acceptance.status='COMMITTED'
      AND outcome_version.content->>'contract_version'='chapter-outcome-v2'
      AND outcome_version.content->>'project_id'=acceptance.project_id
      AND outcome_version.content->>'book_id'=production.book_id
      AND (outcome_version.content->>'chapter_number')::integer=
          acceptance.chapter_number
      AND event.payload->>'contract_version'='narrative-state-event-v2'
      AND event.payload->>'layer'='STATE_EVENT'
      AND event.payload->'scope'->>'project_id'=acceptance.project_id
      AND event.payload->'scope'->>'book_id'=production.book_id
      AND (event.payload->'coordinate'->>'source_chapter')::integer=
          acceptance.chapter_number
      AND (event.payload->'coordinate'->>'effective_from_chapter')::integer
          <= acceptance.chapter_number
    """,
    """
    CREATE VIEW authority_narrative_current_state_projection AS
    SELECT DISTINCT ON (acceptance.project_id, production.book_id)
           acceptance.project_id,
           production.book_id,
           acceptance.book_run_id,
           acceptance.acceptance_id,
           acceptance.chapter_number AS accepted_through_chapter,
           acceptance.chapter_outcome_asset_version_id,
           acceptance.story_state_asset_version_id,
           story.content AS story_state,
           acceptance.canon_snapshot_asset_version_id,
           canon.content AS canon_state,
           acceptance.created_at AS recorded_at
    FROM authority_book_chapter_acceptance AS acceptance
    JOIN authority_book_production AS production
      ON production.book_run_id=acceptance.book_run_id
     AND production.project_id=acceptance.project_id
    JOIN authority_operation AS acceptance_operation
      ON acceptance_operation.operation_id=acceptance.acceptance_operation_id
     AND acceptance_operation.project_id=acceptance.project_id
     AND acceptance_operation.status='SUCCEEDED'
    JOIN authority_asset_version AS story
      ON story.asset_version_id=acceptance.story_state_asset_version_id
     AND story.lifecycle IN ('ACTIVE', 'SUPERSEDED')
     AND story.eligibility='ELIGIBLE'
     AND story.governance='CLEAR'
    JOIN authority_asset AS story_asset
      ON story_asset.asset_id=story.asset_id
     AND story_asset.project_id=acceptance.project_id
     AND story_asset.asset_type='story_state_snapshot'
    JOIN authority_asset_version AS canon
      ON canon.asset_version_id=acceptance.canon_snapshot_asset_version_id
     AND canon.lifecycle IN ('ACTIVE', 'SUPERSEDED')
     AND canon.eligibility='ELIGIBLE'
     AND canon.governance='CLEAR'
    JOIN authority_asset AS canon_asset
      ON canon_asset.asset_id=canon.asset_id
     AND canon_asset.project_id=acceptance.project_id
     AND canon_asset.asset_type='canon_snapshot'
    WHERE acceptance.status='COMMITTED'
      AND story.content->>'contract_version'='story-state-snapshot-v2'
      AND canon.content->>'contract_version'='canon-snapshot-v2'
      AND story.content->>'project_id'=acceptance.project_id
      AND story.content->>'book_id'=production.book_id
      AND canon.content->>'project_id'=acceptance.project_id
      AND canon.content->>'book_id'=production.book_id
      AND (story.content->>'accepted_through_chapter')::integer=
          acceptance.chapter_number
      AND (canon.content->>'accepted_through_chapter')::integer=
          acceptance.chapter_number
    ORDER BY acceptance.project_id, production.book_id,
             acceptance.chapter_number DESC, acceptance.created_at DESC
    """,
    """
    CREATE VIEW authority_narrative_state_rebuild_source AS
    SELECT acceptance.project_id,
           production.book_id,
           acceptance.book_run_id,
           acceptance.acceptance_id,
           acceptance.chapter_number AS accepted_chapter,
           acceptance.chapter_outcome_asset_version_id,
           acceptance.story_state_asset_version_id,
           outcome.content AS chapter_outcome,
           acceptance.created_at AS recorded_at
    FROM authority_book_chapter_acceptance AS acceptance
    JOIN authority_book_production AS production
      ON production.book_run_id=acceptance.book_run_id
     AND production.project_id=acceptance.project_id
    JOIN authority_operation AS acceptance_operation
      ON acceptance_operation.operation_id=acceptance.acceptance_operation_id
     AND acceptance_operation.project_id=acceptance.project_id
     AND acceptance_operation.status='SUCCEEDED'
    JOIN authority_asset_version AS outcome
      ON outcome.asset_version_id=acceptance.chapter_outcome_asset_version_id
     AND outcome.lifecycle IN ('ACTIVE', 'SUPERSEDED')
     AND outcome.eligibility='ELIGIBLE'
     AND outcome.governance='CLEAR'
    JOIN authority_asset AS outcome_asset
      ON outcome_asset.asset_id=outcome.asset_id
     AND outcome_asset.project_id=acceptance.project_id
     AND outcome_asset.asset_type='chapter_outcome'
    WHERE acceptance.status='COMMITTED'
      AND outcome.content->>'contract_version' IN (
        'chapter-outcome-v1', 'chapter-outcome-v2'
      )
      AND outcome.content->>'project_id'=acceptance.project_id
      AND outcome.content->>'book_id'=production.book_id
      AND (outcome.content->>'chapter_number')::integer=
          acceptance.chapter_number
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []
