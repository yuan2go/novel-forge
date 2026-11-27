from __future__ import annotations


MIGRATION_ID = "20260814_0091_canonical_longform_runtime_completion"
DOWN_REVISION = "20260814_0090_progressive_replan_scopes"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = (
    "Bind Narrative Qualification to an independent evaluation Operation/Attempt "
    "and expose canonical planning/runtime projections without a parallel Authority"
)


UPGRADE_STATEMENTS = [
    """
    ALTER TABLE authority_story_planning_generation
    DROP CONSTRAINT authority_story_planning_generation_status_check,
    ADD CONSTRAINT authority_story_planning_generation_status_check
    CHECK (status IN (
        'ADMITTED', 'EXECUTING', 'CANDIDATE_MATERIALIZED',
        'STRUCTURALLY_VALID', 'EVALUATION_PENDING',
        'SEMANTICALLY_VALID', 'QUALIFIED', 'APPROVAL_PENDING',
        'APPROVED', 'ACTIVE', 'REPAIR_REQUIRED', 'REJECTED'
    ))
    """,
    """
    ALTER TABLE authority_book_design_candidate
    DROP CONSTRAINT authority_book_design_candidate_status_check,
    ADD CONSTRAINT authority_book_design_candidate_status_check
    CHECK (status IN (
        'EVALUATION_PENDING', 'VALIDATED', 'APPROVED', 'REJECTED',
        'ACTIVE', 'SUPERSEDED'
    ))
    """,
    """
    ALTER TABLE authority_book_production_input_snapshot
    ADD COLUMN volume_portfolio_plan_versions JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN narrative_chapter_cursor INTEGER NOT NULL DEFAULT 1,
    ADD CONSTRAINT authority_book_production_volume_portfolio_check
    CHECK (jsonb_typeof(volume_portfolio_plan_versions)='array'),
    ADD CONSTRAINT authority_book_production_chapter_cursor_check
    CHECK (narrative_chapter_cursor > 0)
    """,
    """
    ALTER TABLE authority_narrative_design_qualification
    ADD COLUMN generation_operation_id TEXT
        REFERENCES authority_operation(operation_id),
    ADD COLUMN evaluation_operation_id TEXT
        REFERENCES authority_operation(operation_id),
    ADD COLUMN evaluation_attempt_id TEXT
        REFERENCES authority_attempt(attempt_id),
    ADD COLUMN evaluation_asset_version_id TEXT
        REFERENCES authority_asset_version(asset_version_id),
    ADD COLUMN evaluation_evidence_hash TEXT,
    ADD COLUMN trust_boundary TEXT NOT NULL DEFAULT 'LEGACY_COUPLED'
    """,
    """
    ALTER TABLE authority_narrative_design_qualification
    ADD CONSTRAINT authority_narrative_design_qualification_trust_check
    CHECK (trust_boundary IN ('LEGACY_COUPLED', 'INDEPENDENT')),
    ADD CONSTRAINT authority_narrative_design_qualification_independent_check
    CHECK (
        trust_boundary <> 'INDEPENDENT'
        OR (
            generation_operation_id IS NOT NULL
            AND evaluation_operation_id IS NOT NULL
            AND evaluation_attempt_id IS NOT NULL
            AND evaluation_asset_version_id IS NOT NULL
            AND evaluation_evidence_hash LIKE 'sha256:%'
            AND source_operation_id=evaluation_operation_id
            AND generation_operation_id<>evaluation_operation_id
        )
    )
    """,
    """
    CREATE INDEX authority_narrative_design_qualification_evaluation_idx
    ON authority_narrative_design_qualification(
        evaluation_operation_id, evaluation_attempt_id,
        evaluation_asset_version_id
    )
    """,
    """
    CREATE INDEX authority_narrative_design_qualification_generation_idx
    ON authority_narrative_design_qualification(
        generation_operation_id, asset_version_id, design_layer
    )
    """,
    """
    CREATE OR REPLACE VIEW authority_current_narrative_design_qualification AS
    SELECT qualification.qualification_id,
           qualification.project_id,
           qualification.book_id,
           qualification.asset_version_id,
           qualification.source_operation_id,
           qualification.design_layer,
           qualification.profile_id,
           qualification.profile_version,
           qualification.profile_hash,
           qualification.capability_id,
           qualification.skill_ref,
           qualification.evaluator_execution_class,
           qualification.qualification_status,
           qualification.evaluation,
           qualification.evaluation_hash,
           qualification.qualification_hash,
           CASE
             WHEN book.current_book_design_asset_version_id=
                  qualification.asset_version_id THEN 'CURRENT'
             WHEN active.binding_id IS NOT NULL AND binding.freshness='CURRENT'
                  THEN 'CURRENT'
             ELSE 'HISTORICAL'
           END AS freshness,
           qualification.generation_operation_id,
           qualification.evaluation_operation_id,
           qualification.evaluation_attempt_id,
           qualification.evaluation_asset_version_id,
           qualification.evaluation_evidence_hash,
           qualification.trust_boundary
    FROM authority_narrative_design_qualification AS qualification
    LEFT JOIN authority_book AS book
      ON book.project_id=qualification.project_id
     AND book.book_id=qualification.book_id
    LEFT JOIN story_plan_binding AS binding
      ON binding.project_id=qualification.project_id
     AND binding.book_id=qualification.book_id
     AND binding.asset_version_id=qualification.asset_version_id
    LEFT JOIN active_story_plan_version AS active
      ON active.binding_id=binding.binding_id
    WHERE qualification.qualification_status='PASS'
      AND qualification.trust_boundary='INDEPENDENT'
    """,
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
      AND outcome_version.content->>'contract_version'='chapter-outcome-v2'
      AND outcome_version.content->>'project_id'=acceptance.project_id
      AND outcome_version.content->>'book_id'=production.book_id
      AND (outcome_version.content->>'chapter_number')::integer=
          acceptance.chapter_number
      AND event.payload->>'contract_version' IN (
          'narrative-state-event-v2', 'narrative-state-event-v3'
      )
      AND event.payload->>'layer'='STATE_EVENT'
      AND event.payload->'scope'->>'project_id'=acceptance.project_id
      AND event.payload->'scope'->>'book_id'=production.book_id
      AND (event.payload->'coordinate'->>'source_chapter')::integer=
          acceptance.chapter_number
      AND (event.payload->'coordinate'->>'effective_from_chapter')::integer
          <= acceptance.chapter_number
    """,
    """
    CREATE VIEW authority_volume_portfolio_projection AS
    SELECT binding.project_id,
           binding.book_id,
           binding.logical_key AS volume_logical_key,
           binding.asset_version_id AS volume_plan_version_id,
           version.content_hash AS volume_plan_content_hash,
           version.content->'chapter_range' AS chapter_range,
           version.content->>'planning_horizon' AS planning_horizon,
           version.content->>'realization_level' AS realization_level,
           version.content->'commitment_contract' AS commitment_contract,
           EXISTS (
               SELECT 1
               FROM authority_book_production_input_snapshot AS snapshot
               WHERE snapshot.project_id=binding.project_id
                 AND snapshot.book_id=binding.book_id
                 AND snapshot.current_volume_plan_version=
                     binding.asset_version_id
                 AND snapshot.created_at=(
                     SELECT MAX(latest.created_at)
                     FROM authority_book_production_input_snapshot AS latest
                     WHERE latest.project_id=binding.project_id
                       AND latest.book_id=binding.book_id
                 )
           ) AS runtime_current_volume,
           COALESCE((
               SELECT snapshot.narrative_chapter_cursor
               FROM authority_book_production_input_snapshot AS snapshot
               WHERE snapshot.project_id=binding.project_id
                 AND snapshot.book_id=binding.book_id
                 AND snapshot.current_volume_plan_version=binding.asset_version_id
               ORDER BY snapshot.created_at DESC
               LIMIT 1
           ), 0) AS runtime_chapter_cursor,
           binding.execution_scope,
           binding.freshness
    FROM active_story_plan_version AS active
    JOIN story_plan_binding AS binding
      ON binding.binding_id=active.binding_id
    JOIN authority_asset_version AS version
      ON version.asset_version_id=binding.asset_version_id
    WHERE binding.contract_type='VOLUME'
      AND binding.freshness='CURRENT'
    """,
    """
    CREATE VIEW authority_canonical_planning_projection AS
    SELECT binding.project_id,
           binding.book_id,
           binding.contract_type,
           binding.logical_key,
           binding.asset_version_id,
           binding.parent_version_id,
           binding.execution_scope,
           binding.freshness,
           version.content->>'planning_horizon' AS planning_horizon,
           version.content->>'realization_level' AS realization_level,
           version.content->'commitment_contract' AS commitment_contract,
           version.content->'world_realization' AS world_realization,
           version.content->'character_realization' AS character_realization,
           version.content->'narrative_load_budget' AS narrative_load_budget
    FROM active_story_plan_version AS active
    JOIN story_plan_binding AS binding ON binding.binding_id=active.binding_id
    JOIN authority_asset_version AS version
      ON version.asset_version_id=binding.asset_version_id
    WHERE binding.freshness IN ('CURRENT', 'IMPACTED')
    """,
    """
    CREATE VIEW authority_multiscale_quality_projection AS
    SELECT asset.project_id,
           version.asset_version_id AS quality_report_asset_version_id,
           version.content->>'book_id' AS book_id,
           (version.content->>'accepted_through_chapter')::INTEGER
               AS accepted_through_chapter,
           version.content->>'observation_status' AS observation_status,
           version.content->'scope_reports' AS scope_reports,
           version.content->'window_reports' AS window_reports,
           version.content->'source_acceptance_ids' AS source_acceptance_ids,
           version.content->'source_accepted_asset_version_ids'
               AS source_accepted_asset_version_ids,
           version.created_at
    FROM authority_asset AS asset
    JOIN authority_asset_version AS version ON version.asset_id=asset.asset_id
    WHERE asset.asset_type='multiscale_narrative_quality_report'
      AND version.lifecycle IN ('ACTIVE', 'SUPERSEDED')
      AND version.governance='CLEAR'
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []
