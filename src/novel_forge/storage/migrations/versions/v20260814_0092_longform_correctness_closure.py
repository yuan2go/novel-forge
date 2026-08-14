from __future__ import annotations


MIGRATION_ID = "20260814_0092_longform_correctness_closure"
DOWN_REVISION = "20260814_0091_canonical_longform_runtime_completion"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = (
    "Separate the global Arc portfolio from cursor projection, bind real semantic "
    "evaluation Provider receipts, and expose inherited Narrative Load Policy lineage"
)


UPGRADE_STATEMENTS = [
    """
    ALTER TABLE authority_book_production_input_snapshot
    ADD COLUMN arc_portfolio_plan_versions JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN current_relevant_arc_plan_versions JSONB NOT NULL DEFAULT '[]'::jsonb
    """,
    """
    UPDATE authority_book_production_input_snapshot
    SET arc_portfolio_plan_versions=active_arc_plan_versions,
        current_relevant_arc_plan_versions=active_arc_plan_versions
    WHERE arc_portfolio_plan_versions='[]'::jsonb
      AND current_relevant_arc_plan_versions='[]'::jsonb
    """,
    """
    ALTER TABLE authority_book_production_input_snapshot
    ADD CONSTRAINT authority_book_production_arc_portfolio_check
        CHECK (
            jsonb_typeof(arc_portfolio_plan_versions)='array'
            AND jsonb_array_length(arc_portfolio_plan_versions)>0
        ),
    ADD CONSTRAINT authority_book_production_relevant_arc_projection_check
        CHECK (
            jsonb_typeof(current_relevant_arc_plan_versions)='array'
            AND jsonb_array_length(current_relevant_arc_plan_versions)>0
        ),
    ADD CONSTRAINT authority_book_production_arc_projection_subset_check
        CHECK (arc_portfolio_plan_versions @> current_relevant_arc_plan_versions),
    ADD CONSTRAINT authority_book_production_arc_projection_alias_check
        CHECK (active_arc_plan_versions=current_relevant_arc_plan_versions)
    """,
    """
    CREATE INDEX authority_book_production_arc_portfolio_gin_idx
    ON authority_book_production_input_snapshot
    USING GIN (arc_portfolio_plan_versions jsonb_path_ops)
    """,
    """
    CREATE INDEX authority_book_production_current_relevant_arc_gin_idx
    ON authority_book_production_input_snapshot
    USING GIN (current_relevant_arc_plan_versions jsonb_path_ops)
    """,
    """
    ALTER TABLE authority_narrative_design_qualification
    ADD COLUMN provider_model_call_asset_version_id TEXT
        REFERENCES authority_asset_version(asset_version_id),
    ADD COLUMN provider_model_call_content_hash TEXT,
    ADD COLUMN provider_evidence_hash TEXT,
    ADD COLUMN provider_result_hash TEXT,
    ADD COLUMN provider_route_snapshot_id TEXT
    """,
    """
    ALTER TABLE authority_narrative_design_qualification
    DISABLE TRIGGER authority_narrative_design_qualification_immutable
    """,
    """
    UPDATE authority_narrative_design_qualification
    SET trust_boundary='LEGACY_COUPLED'
    WHERE evaluator_execution_class='MODEL_PROVIDER'
      AND trust_boundary='INDEPENDENT'
    """,
    """
    ALTER TABLE authority_narrative_design_qualification
    ENABLE TRIGGER authority_narrative_design_qualification_immutable
    """,
    """
    ALTER TABLE authority_narrative_design_qualification
    ADD CONSTRAINT authority_narrative_design_provider_lineage_check
    CHECK (
        evaluator_execution_class <> 'MODEL_PROVIDER'
        OR trust_boundary <> 'INDEPENDENT'
        OR (
            provider_model_call_asset_version_id IS NOT NULL
            AND provider_model_call_content_hash IS NOT NULL
            AND provider_model_call_content_hash ~ '^sha256:[0-9a-f]{64}$'
            AND provider_evidence_hash IS NOT NULL
            AND provider_evidence_hash ~ '^sha256:[0-9a-f]{64}$'
            AND provider_result_hash IS NOT NULL
            AND provider_result_hash ~ '^sha256:[0-9a-f]{64}$'
            AND provider_route_snapshot_id IS NOT NULL
            AND provider_route_snapshot_id <> ''
        )
    )
    """,
    """
    CREATE INDEX authority_narrative_design_provider_receipt_idx
    ON authority_narrative_design_qualification(
        provider_model_call_asset_version_id,
        provider_route_snapshot_id,
        provider_result_hash
    )
    WHERE evaluator_execution_class='MODEL_PROVIDER'
      AND trust_boundary='INDEPENDENT'
    """,
    """
    CREATE OR REPLACE FUNCTION authority_validate_narrative_provider_lineage()
    RETURNS TRIGGER AS $$
    DECLARE
        model_call_content JSONB;
        model_call_content_hash TEXT;
        model_call_asset_type TEXT;
        model_call_project_id TEXT;
        evaluation_asset_content JSONB;
        evaluation_asset_content_hash TEXT;
        evaluation_asset_type TEXT;
        evaluation_asset_project_id TEXT;
    BEGIN
        IF NEW.evaluator_execution_class <> 'MODEL_PROVIDER'
           OR NEW.trust_boundary <> 'INDEPENDENT' THEN
            RETURN NEW;
        END IF;

        SELECT version.content, version.content_hash, asset.asset_type, asset.project_id
        INTO model_call_content, model_call_content_hash,
             model_call_asset_type, model_call_project_id
        FROM authority_asset_version AS version
        JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
        WHERE version.asset_version_id=NEW.provider_model_call_asset_version_id;

        SELECT version.content, version.content_hash,
               asset.asset_type, asset.project_id
        INTO evaluation_asset_content, evaluation_asset_content_hash,
             evaluation_asset_type, evaluation_asset_project_id
        FROM authority_asset_version AS version
        JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
        WHERE version.asset_version_id=NEW.evaluation_asset_version_id;

        IF NOT FOUND
           OR model_call_asset_type IS DISTINCT FROM 'model_call_log'
           OR model_call_project_id IS DISTINCT FROM NEW.project_id
           OR model_call_content_hash IS DISTINCT FROM
              NEW.provider_model_call_content_hash
           OR model_call_content->>'operation_id' IS DISTINCT FROM
              NEW.evaluation_operation_id
           OR model_call_content->>'attempt_id' IS DISTINCT FROM
              NEW.evaluation_attempt_id
           OR model_call_content->>'stage' IS DISTINCT FROM
              'narrative_semantic_evaluation'
           OR model_call_content#>>'{target_lineage,target_asset_version_id}'
              IS DISTINCT FROM NEW.asset_version_id
           OR model_call_content#>>'{target_lineage,target_content_hash}'
              IS DISTINCT FROM NEW.candidate_content_hash
           OR model_call_content#>>'{target_lineage,generation_operation_id}'
              IS DISTINCT FROM NEW.generation_operation_id
           OR model_call_content#>>'{provider_evidence,real_model_call}'
              IS DISTINCT FROM 'true'
           OR model_call_content#>>'{provider_evidence,production_execution,execution_handle,transport}'
              IS DISTINCT FROM 'REMOTE_PROVIDER_API'
           OR model_call_content#>>'{provider_evidence,production_execution,route_snapshot,route_snapshot_id}'
              IS DISTINCT FROM NEW.provider_route_snapshot_id
           OR authority_sha256_jsonb(model_call_content->'provider_evidence')
              IS DISTINCT FROM NEW.provider_evidence_hash
           OR authority_sha256_jsonb(model_call_content#>'{provider_evidence,result}')
              IS DISTINCT FROM NEW.provider_result_hash
           OR evaluation_asset_type IS DISTINCT FROM
              'narrative_design_evaluation'
           OR evaluation_asset_project_id IS DISTINCT FROM NEW.project_id
           OR evaluation_asset_content#>>'{candidate_asset_version_id}'
              IS DISTINCT FROM NEW.asset_version_id
           OR evaluation_asset_content#>>'{candidate_content_hash}'
              IS DISTINCT FROM NEW.candidate_content_hash
           OR evaluation_asset_content#>>'{generation_operation_id}'
              IS DISTINCT FROM NEW.generation_operation_id
           OR evaluation_asset_content#>>'{evaluation_operation_id}'
              IS DISTINCT FROM NEW.evaluation_operation_id
           OR evaluation_asset_content#>>'{evaluation_attempt_id}'
              IS DISTINCT FROM NEW.evaluation_attempt_id
           OR evaluation_asset_content#>>'{evaluator_execution_class}'
              IS DISTINCT FROM NEW.evaluator_execution_class
           OR evaluation_asset_content#>>'{evaluation_evidence_hash}'
              IS DISTINCT FROM NEW.evaluation_evidence_hash
           OR evaluation_asset_content#>>'{qualification,qualification_hash}'
              IS DISTINCT FROM NEW.qualification_hash
           OR evaluation_asset_content#>'{evaluation}'
              IS DISTINCT FROM model_call_content#>'{provider_evidence,result}'
           OR evaluation_asset_content#>>'{provider_execution,provider_evidence_hash}'
              IS DISTINCT FROM NEW.provider_evidence_hash
           OR evaluation_asset_content#>>'{provider_execution,provider_result_hash}'
              IS DISTINCT FROM NEW.provider_result_hash
           OR evaluation_asset_content#>>'{provider_execution,route_snapshot_id}'
              IS DISTINCT FROM NEW.provider_route_snapshot_id
           OR authority_sha256_jsonb(NEW.evaluation)
              IS DISTINCT FROM NEW.evaluation_hash
           OR NEW.evaluation->>'layer' IS DISTINCT FROM NEW.design_layer
           OR NEW.evaluation->>'profile_id' IS DISTINCT FROM NEW.profile_id
           OR NEW.evaluation->>'profile_version' IS DISTINCT FROM
              NEW.profile_version
           OR NEW.evaluation->>'profile_hash' IS DISTINCT FROM NEW.profile_hash
           OR NEW.evaluation->>'capability_id' IS DISTINCT FROM NEW.capability_id
           OR NEW.evaluation->>'skill_ref' IS DISTINCT FROM NEW.skill_ref
           OR NOT EXISTS (
                SELECT 1
                FROM jsonb_array_elements(
                    evaluation_asset_content#>'{evaluation,evaluations}'
                ) AS item(value)
                WHERE item.value=NEW.evaluation
           )
           OR NOT EXISTS (
                SELECT 1
                FROM jsonb_array_elements(
                    evaluation_asset_content#>'{qualification,receipts}'
                ) AS receipt(value)
                WHERE receipt.value->>'layer'=NEW.design_layer
                  AND receipt.value->>'status'=NEW.qualification_status
                  AND receipt.value->>'profile_id'=NEW.profile_id
                  AND receipt.value->>'profile_version'=NEW.profile_version
                  AND receipt.value->>'profile_hash'=NEW.profile_hash
                  AND receipt.value->>'evaluation_hash'=NEW.evaluation_hash
                  AND receipt.value->'evidence'=NEW.evaluation
           )
        THEN
            RAISE EXCEPTION
                'Narrative qualification Provider lineage does not match exact ModelCallLog';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE TRIGGER authority_narrative_design_provider_lineage_guard
    BEFORE INSERT ON authority_narrative_design_qualification
    FOR EACH ROW EXECUTE FUNCTION authority_validate_narrative_provider_lineage()
    """,
    """
    CREATE OR REPLACE FUNCTION authority_validate_book_arc_projection()
    RETURNS TRIGGER AS $$
    BEGIN
        IF EXISTS (
            SELECT value
            FROM jsonb_array_elements_text(NEW.arc_portfolio_plan_versions)
                 AS item(value)
            GROUP BY value HAVING COUNT(*)>1
        ) OR EXISTS (
            SELECT value
            FROM jsonb_array_elements_text(
                NEW.current_relevant_arc_plan_versions
            ) AS item(value)
            GROUP BY value HAVING COUNT(*)>1
        ) OR EXISTS (
            SELECT 1
            FROM jsonb_array_elements_text(NEW.arc_portfolio_plan_versions)
                 AS item(asset_version_id)
            LEFT JOIN story_plan_binding AS binding
              ON binding.project_id=NEW.project_id
             AND binding.book_id=NEW.book_id
             AND binding.asset_version_id=item.asset_version_id
             AND binding.contract_type='ARC'
             AND binding.freshness='CURRENT'
            LEFT JOIN authority_asset_version AS version
              ON version.asset_version_id=item.asset_version_id
            WHERE binding.binding_id IS NULL
               OR version.asset_version_id IS NULL
               OR jsonb_typeof(version.content->'cross_volume_scope')<>'array'
               OR jsonb_array_length(version.content->'cross_volume_scope')=0
               OR NOT NEW.volume_portfolio_plan_versions @>
                    (version.content->'cross_volume_scope')
        ) OR EXISTS (
            SELECT 1
            FROM jsonb_array_elements_text(NEW.volume_portfolio_plan_versions)
                 AS item(asset_version_id)
            WHERE NOT EXISTS (
                SELECT 1
                FROM story_plan_binding AS binding
                WHERE binding.project_id=NEW.project_id
                  AND binding.book_id=NEW.book_id
                  AND binding.asset_version_id=item.asset_version_id
                  AND binding.contract_type='VOLUME'
                  AND binding.freshness='CURRENT'
            )
        ) OR EXISTS (
            SELECT 1
            FROM jsonb_array_elements_text(
                NEW.current_relevant_arc_plan_versions
            ) AS item(asset_version_id)
            JOIN authority_asset_version AS version
              ON version.asset_version_id=item.asset_version_id
            WHERE NOT (version.content->'cross_volume_scope') @>
                to_jsonb(ARRAY[NEW.current_volume_plan_version])
        ) THEN
            RAISE EXCEPTION 'BOOK_INPUT_ARC_PROJECTION_INVALID'
                USING ERRCODE='check_violation';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE TRIGGER authority_book_arc_projection_guard
    BEFORE INSERT ON authority_book_production_input_snapshot
    FOR EACH ROW EXECUTE FUNCTION authority_validate_book_arc_projection()
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
           qualification.trust_boundary,
           qualification.provider_model_call_asset_version_id,
           qualification.provider_model_call_content_hash,
           qualification.provider_evidence_hash,
           qualification.provider_result_hash,
           qualification.provider_route_snapshot_id
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
    DROP VIEW authority_canonical_planning_projection
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
           version.content->'constraint_envelope'->'narrative_load_policy'
               AS narrative_load_policy,
           version.content->'constraint_envelope'->'narrative_load_policy_lineage'
               AS narrative_load_policy_lineage,
           version.content->'constraint_envelope'->'narrative_load_projection'
               AS narrative_load_projection
    FROM active_story_plan_version AS active
    JOIN story_plan_binding AS binding ON binding.binding_id=active.binding_id
    JOIN authority_asset_version AS version
      ON version.asset_version_id=binding.asset_version_id
    WHERE binding.freshness IN ('CURRENT', 'IMPACTED')
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []
