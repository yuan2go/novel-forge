from __future__ import annotations


MIGRATION_ID = "20260812_0086_corrective_generation_terminal_lineage"
DOWN_REVISION = "20260812_0085_corrective_action_terminal_lineage"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = (
    "terminal Quality correction state is derived across the bounded correction "
    "generation, including independent rereview and downstream evaluation operations"
)


UPGRADE_STATEMENTS = [
    """
    ALTER VIEW authority_corrective_action_lineage_projection
    RENAME TO authority_corrective_action_lineage_projection_v85_base
    """,
    """
    COMMENT ON VIEW authority_corrective_action_lineage_projection_v85_base IS
    'MIGRATION_ONLY base projection retained for the 0086 correction-generation wrapper'
    """,
    """
    CREATE VIEW authority_corrective_action_lineage_projection AS
    SELECT base.issue_id, base.project_id, base.source_operation_id,
           base.source_asset_version_id, base.issue_type, base.severity,
           base.evidence_refs, base.action_id, base.action_type,
           base.target_scope, base.required_authority, base.reevaluation_gate,
           base.action_asset_version_id, base.execution_operation_id,
           base.execution_attempt_id, base.result_asset_version_ids,
           CASE
             WHEN base.evaluation_operation_id IS NOT NULL
               THEN base.evaluation_operation_id
             WHEN terminal.definition_name<>'chapter.revision.apply'
               THEN terminal.operation_id
             ELSE NULL
           END AS evaluation_operation_id,
           base.evaluation_asset_version_id,
           CASE
             WHEN base.status='SUPERSEDED' THEN base.gate_result
             WHEN terminal.status IN ('FAILED_FINAL','DEAD_LETTER','CANCELLED')
               THEN 'NOT_AVAILABLE'
             ELSE base.gate_result
           END AS gate_result,
           CASE
             WHEN base.status='SUPERSEDED' THEN base.resolution
             WHEN terminal.status IN ('FAILED_FINAL','DEAD_LETTER') THEN 'FAILED'
             WHEN terminal.status='CANCELLED' THEN 'CANCELLED'
             ELSE base.resolution
           END AS resolution,
           CASE
             WHEN base.status='SUPERSEDED' THEN base.status
             WHEN terminal.status IN ('FAILED_FINAL','DEAD_LETTER') THEN 'FAILED'
             WHEN terminal.status='CANCELLED' THEN 'CANCELLED'
             ELSE base.status
           END AS status,
           base.created_at
    FROM authority_corrective_action_lineage_projection_v85_base AS base
    LEFT JOIN LATERAL (
      SELECT operation.root_operation_id,
             substring(
               operation.idempotency_key
               FROM ':quality-correction:([0-9]+)$'
             ) AS generation
      FROM authority_operation AS operation
      WHERE base.issue_id LIKE 'corrective-issue:quality:%'
        AND operation.project_id=base.project_id
        AND operation.definition_name='chapter.revision.apply'
        AND operation.idempotency_key ~ ':quality-correction:[0-9]+$'
        AND EXISTS (
          SELECT 1
          FROM jsonb_array_elements(operation.input_asset_snapshot) AS input(value)
          WHERE input.value->>'asset_version_id'=base.source_asset_version_id
        )
      ORDER BY operation.created_at DESC, operation.operation_id DESC
      LIMIT 1
    ) AS correction ON TRUE
    LEFT JOIN LATERAL (
      SELECT operation.operation_id, operation.definition_name, operation.status
      FROM authority_operation AS operation
      WHERE correction.root_operation_id IS NOT NULL
        AND operation.project_id=base.project_id
        AND operation.root_operation_id=correction.root_operation_id
        AND substring(
              operation.idempotency_key
              FROM ':quality-correction:([0-9]+)$'
            )=correction.generation
        AND operation.definition_name IN (
          'chapter.revision.apply', 'chapter.revision.review',
          'chapter.canon.extract', 'chapter.canon.propose_changes',
          'chapter.canon.update', 'chapter.quality.structural.evaluate',
          'chapter.quality.commercial.evaluate',
          'chapter.quality.source_originality.evaluate',
          'chapter.quality.longform.evaluate',
          'chapter.quality.platform.evaluate', 'chapter.quality.evaluate'
        )
        AND operation.status IN ('FAILED_FINAL','DEAD_LETTER','CANCELLED')
      ORDER BY operation.updated_at DESC, operation.operation_id DESC
      LIMIT 1
    ) AS terminal ON TRUE
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []
