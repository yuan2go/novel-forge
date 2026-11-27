from __future__ import annotations

MIGRATION_ID = '20261005_0149_zero_increment_chapter_outcome'
DOWN_REVISION = "20260928_0148_author_supervised_design"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Retain v1-v3 accepted history; append a successor view repair if needed."
UPGRADE_STATEMENTS = [
    """
    CREATE OR REPLACE VIEW authority_narrative_state_event_projection AS
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
      AND outcome_version.content->>'contract_version' IN (
          'chapter-outcome-v2', 'chapter-outcome-v3', 'chapter-outcome-v4'
      )
      AND outcome_version.content->>'project_id'=acceptance.project_id
      AND outcome_version.content->>'book_id'=production.book_id
      AND (outcome_version.content->>'chapter_number')::integer=
          acceptance.chapter_number
      AND event.payload->>'contract_version' IN (
          'narrative-state-event-v2', 'narrative-state-event-v3'
      )
      AND event.payload->>'layer'='STATE_EVENT'
    """,
    """
    CREATE OR REPLACE VIEW authority_narrative_state_rebuild_source AS
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
        'chapter-outcome-v1', 'chapter-outcome-v2', 'chapter-outcome-v3', 'chapter-outcome-v4'
      )
      AND outcome.content->>'project_id'=acceptance.project_id
      AND outcome.content->>'book_id'=production.book_id
      AND (outcome.content->>'chapter_number')::integer=
          acceptance.chapter_number
    """,
]
DOWNGRADE_STATEMENTS: list[str] = []
