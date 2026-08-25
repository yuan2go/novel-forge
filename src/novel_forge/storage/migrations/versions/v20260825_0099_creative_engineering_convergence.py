from __future__ import annotations


MIGRATION_ID = "20260825_0099_creative_engineering_convergence"
DOWN_REVISION = "20260825_0098_narrative_evolution_engine"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = (
    "repair governed Context, authoring projection, or Skill activation evidence "
    "with a later forward migration; accepted narrative evidence remains immutable"
)


UPGRADE_STATEMENTS = [
    """
    UPDATE authority_operation_definition
       SET enabled=FALSE
     WHERE name IN (
       'agent.chapter_binding.register',
       'agent.chapter_binding.activate',
       'agent.candidate.execute'
     )
        OR (name='agent.session.execute' AND definition_version='2.0.0')
    """,
    """
    ALTER TABLE authority_agent_transcript_event
      DROP CONSTRAINT IF EXISTS
        authority_agent_transcript_event_event_type_check
    """,
    """
    ALTER TABLE authority_agent_transcript_event
      ADD CONSTRAINT authority_agent_transcript_event_event_type_check
      CHECK (
        event_type IN (
          'REQUEST_STARTED','SKILL_ACTIVATED','MODEL_MESSAGE',
          'TOOL_REQUESTED','TOOL_OBSERVED','AUTHORITY_COMMAND_SUBMITTED',
          'REQUEST_COMMITTED','REQUEST_FAILED','CHECKPOINT','SESSION_STOPPED'
        )
      )
    """,
    """
    CREATE INDEX authority_narrative_retrieval_authoring_projection_idx
      ON authority_narrative_retrieval_document(
        project_id,
        book_id,
        (metadata->>'authoring_projection_kind'),
        accepted_from_chapter DESC
      )
      WHERE metadata ? 'authoring_projection_kind'
    """,
    """
    CREATE OR REPLACE VIEW authority_context_runtime_usage_projection AS
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
    JOIN authority_asset AS context_asset
      ON context_asset.asset_id=context_version.asset_id
     AND context_asset.asset_type='context_bundle'
    CROSS JOIN LATERAL jsonb_array_elements(
      COALESCE(
        context_version.content->'context_manifest'->'selected_inputs',
        '[]'::jsonb
      )
    ) AS selected(value)
    JOIN authority_asset_version AS selected_version
      ON selected_version.asset_version_id=selected.value->>'asset_version_id'
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
      AND context_version.content->>'context_contract_version' IN (
          'authority-context-bundle-v5', 'authority-context-bundle-v6',
          'authority-context-bundle-v7'
      )
      AND context_version.content->'context_manifest'->>'contract_version' IN (
          'narrative-context-manifest-v1', 'narrative-context-manifest-v2',
          'narrative-context-manifest-v3'
      )
    """,
    """
    CREATE OR REPLACE VIEW authority_mkaos_runtime_selection_projection AS
    SELECT context_asset.project_id,
           COALESCE(context_version.content->>'book_id', '') AS book_id,
           context_version.asset_version_id AS context_bundle_asset_version_id,
           context_output.operation_id AS context_build_operation_id,
           context_operation.trace_id,
           context_version.content->'context_manifest'->'task'
             ->>'target_capability_id' AS target_capability_id,
           context_version.content->'context_manifest'->'narrative_position'
             AS narrative_position,
           pack.knowledge_pack_id,
           pack.asset_version_id AS knowledge_pack_asset_version_id,
           item.knowledge_card_asset_version_id,
           item.usage_role,
           item.frozen_weight,
           selected.value->>'inclusion_reason' AS inclusion_reason,
           selected.value->>'narrative_function' AS narrative_function,
           context_operation.created_at AS selected_at
    FROM authority_operation_output_asset AS context_output
    JOIN authority_operation AS context_operation
      ON context_operation.operation_id=context_output.operation_id
     AND context_operation.status='SUCCEEDED'
    JOIN authority_asset_version AS context_version
      ON context_version.asset_version_id=context_output.asset_version_id
    JOIN authority_asset AS context_asset
      ON context_asset.asset_id=context_version.asset_id
     AND context_asset.asset_type='context_bundle'
    CROSS JOIN LATERAL jsonb_array_elements(
      COALESCE(
        context_version.content->'context_manifest'->'selected_inputs',
        '[]'::jsonb
      )
    ) AS selected(value)
    JOIN authority_mkaos_knowledge_pack AS pack
      ON pack.asset_version_id=selected.value->>'asset_version_id'
     AND pack.project_id=context_asset.project_id
    JOIN authority_mkaos_knowledge_pack_item AS item
      ON item.knowledge_pack_id=pack.knowledge_pack_id
     AND item.knowledge_pack_asset_version_id=pack.asset_version_id
    WHERE context_output.output_key='chapter.context'
      AND selected.value->>'asset_type'='knowledge_pack'
      AND context_version.content->>'context_contract_version' IN (
          'authority-context-bundle-v5', 'authority-context-bundle-v6',
          'authority-context-bundle-v7'
      )
      AND context_version.content->'context_manifest'->>'contract_version' IN (
          'narrative-context-manifest-v1', 'narrative-context-manifest-v2',
          'narrative-context-manifest-v3'
      )
    """,
]


def upgrade(connection) -> None:
    with connection.cursor() as cursor:
        for statement in UPGRADE_STATEMENTS:
            cursor.execute(statement)


__all__ = [
    "BACKUP_REQUIRED",
    "DOWN_REVISION",
    "FORWARD_FIX",
    "FORWARD_ONLY",
    "MIGRATION_ID",
    "UPGRADE_STATEMENTS",
    "upgrade",
]
