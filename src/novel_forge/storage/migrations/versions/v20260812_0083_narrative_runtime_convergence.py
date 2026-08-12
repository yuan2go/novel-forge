from __future__ import annotations


MIGRATION_ID = "20260812_0083_narrative_runtime_convergence"
DOWN_REVISION = "20260812_0082_narrative_state_contract_v2"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = (
    "rebuild derived Context and MKAOS runtime usage projections from immutable "
    "Authority operations; preserve Replan evidence in a new governed request"
)


UPGRADE_STATEMENTS = [
    """
    ALTER TABLE authority_book_replan
      ADD COLUMN impact_scope JSONB NOT NULL DEFAULT '{}'::jsonb,
      ADD COLUMN preserved_invariants JSONB NOT NULL DEFAULT '[]'::jsonb,
      ADD COLUMN decision_evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
      ADD CONSTRAINT authority_book_replan_impact_scope_object_check
        CHECK (jsonb_typeof(impact_scope)='object'),
      ADD CONSTRAINT authority_book_replan_invariants_array_check
        CHECK (jsonb_typeof(preserved_invariants)='array'),
      ADD CONSTRAINT authority_book_replan_decision_evidence_array_check
        CHECK (jsonb_typeof(decision_evidence)='array')
    """,
    """
    CREATE VIEW authority_context_runtime_usage_projection AS
    SELECT context_asset.project_id,
           COALESCE(context_version.content->>'book_id', '') AS book_id,
           context_version.asset_version_id AS context_bundle_asset_version_id,
           context_output.operation_id AS context_build_operation_id,
           context_operation.trace_id,
           context_version.content->'context_manifest'->'task'
             ->>'target_capability_id' AS target_capability_id,
           context_version.content->'context_manifest'->'task'
             ->>'created_by_operation_id' AS manifest_operation_id,
           context_version.content->'context_manifest'->'narrative_position'
             AS narrative_position,
           context_version.content->'context_manifest'->'authority_state_boundary'
             AS authority_state_boundary,
           selected.value->>'asset_version_id' AS selected_asset_version_id,
           selected.value->>'asset_type' AS selected_asset_type,
           selected.value->>'inclusion_reason' AS inclusion_reason,
           selected.value->>'narrative_function' AS narrative_function,
           selected.value->>'allowed_use' AS allowed_use,
           consumer.operation_id AS consumer_operation_id,
           consumer.definition_name AS consumer_definition_name,
           consumer.status AS consumer_status,
           result.asset_version_id AS result_asset_version_id,
           result_asset.asset_type AS result_asset_type,
           context_operation.created_at AS context_built_at,
           consumer.updated_at AS consumed_at
    FROM authority_operation_output_asset AS context_output
    JOIN authority_operation AS context_operation
      ON context_operation.operation_id=context_output.operation_id
     AND context_operation.status='SUCCEEDED'
    JOIN authority_asset_version AS context_version
      ON context_version.asset_version_id=context_output.asset_version_id
     AND context_version.lifecycle IN ('ACTIVE','SUPERSEDED')
     AND context_version.eligibility='ELIGIBLE'
     AND context_version.governance='CLEAR'
    JOIN authority_asset AS context_asset
      ON context_asset.asset_id=context_version.asset_id
     AND context_asset.asset_type='context_bundle'
    CROSS JOIN LATERAL jsonb_array_elements(
      context_version.content->'context_manifest'->'selected_inputs'
    ) AS selected(value)
    JOIN authority_asset_version AS selected_version
      ON selected_version.asset_version_id=selected.value->>'asset_version_id'
     AND selected_version.lifecycle IN ('ACTIVE','SUPERSEDED')
     AND selected_version.eligibility='ELIGIBLE'
     AND selected_version.governance='CLEAR'
    JOIN authority_asset AS selected_asset
      ON selected_asset.asset_id=selected_version.asset_id
     AND selected_asset.project_id=context_asset.project_id
    JOIN authority_operation AS consumer
      ON consumer.project_id=context_asset.project_id
     AND consumer.status='SUCCEEDED'
     AND EXISTS (
       SELECT 1
       FROM jsonb_array_elements(consumer.input_asset_snapshot) AS input(value)
       WHERE input.value->>'asset_version_id'=context_version.asset_version_id
     )
    LEFT JOIN authority_operation_output_asset AS result
      ON result.operation_id=consumer.operation_id
     AND result.role='primary'
    LEFT JOIN authority_asset AS result_asset
      ON result_asset.asset_id=result.asset_id
     AND result_asset.project_id=context_asset.project_id
    WHERE context_output.output_key='chapter.context'
      AND context_version.content->>'context_contract_version'=
          'authority-context-bundle-v5'
      AND context_version.content->'context_manifest'->>'contract_version'=
          'narrative-context-manifest-v1'
    """,
    """
    CREATE VIEW authority_mkaos_runtime_usage_projection AS
    SELECT usage.project_id,
           usage.book_id,
           usage.context_bundle_asset_version_id,
           usage.context_build_operation_id,
           usage.consumer_operation_id,
           usage.consumer_definition_name,
           usage.result_asset_version_id,
           usage.result_asset_type,
           usage.target_capability_id,
           usage.narrative_position,
           usage.trace_id,
           pack.knowledge_pack_id,
           pack.asset_version_id AS knowledge_pack_asset_version_id,
           item.knowledge_card_asset_version_id,
           item.usage_role,
           item.frozen_weight,
           usage.inclusion_reason,
           usage.narrative_function,
           usage.consumed_at
    FROM authority_context_runtime_usage_projection AS usage
    JOIN authority_mkaos_knowledge_pack AS pack
      ON pack.asset_version_id=usage.selected_asset_version_id
     AND pack.project_id=usage.project_id
     AND pack.status IN ('ACTIVE','SUPERSEDED')
    JOIN authority_mkaos_knowledge_pack_item AS item
      ON item.knowledge_pack_id=pack.knowledge_pack_id
     AND item.knowledge_pack_asset_version_id=pack.asset_version_id
    WHERE usage.selected_asset_type='knowledge_pack'
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []
