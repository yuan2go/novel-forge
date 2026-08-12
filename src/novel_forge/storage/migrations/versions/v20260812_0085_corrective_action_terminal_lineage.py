from __future__ import annotations


MIGRATION_ID = "20260812_0085_corrective_action_terminal_lineage"
DOWN_REVISION = "20260812_0084_development_gap_final_convergence"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = (
    "the v84 projection is retained as a migration-only base; terminal Quality "
    "correction state is derived from immutable Operation, Attempt, and Asset facts"
)


UPGRADE_STATEMENTS = [
    """
    ALTER VIEW authority_corrective_action_lineage_projection
    RENAME TO authority_corrective_action_lineage_projection_v84_base
    """,
    """
    COMMENT ON VIEW authority_corrective_action_lineage_projection_v84_base IS
    'MIGRATION_ONLY base projection retained for the 0085 terminal-state wrapper'
    """,
    """
    CREATE VIEW authority_corrective_action_lineage_projection AS
    SELECT base.issue_id, base.project_id, base.source_operation_id,
           base.source_asset_version_id, base.issue_type, base.severity,
           base.evidence_refs, base.action_id, base.action_type,
           base.target_scope, base.required_authority, base.reevaluation_gate,
           base.action_asset_version_id,
           COALESCE(base.execution_operation_id, correction.operation_id)
             AS execution_operation_id,
           COALESCE(base.execution_attempt_id, correction.attempt_id)
             AS execution_attempt_id,
           base.result_asset_version_ids, base.evaluation_operation_id,
           base.evaluation_asset_version_id,
           CASE
             WHEN action_version.lifecycle='SUPERSEDED' THEN 'NOT_APPLICABLE'
             WHEN correction.status IN ('FAILED_FINAL','DEAD_LETTER','CANCELLED')
               THEN 'NOT_AVAILABLE'
             ELSE base.gate_result
           END AS gate_result,
           CASE
             WHEN action_version.lifecycle='SUPERSEDED' THEN 'SUPERSEDED'
             WHEN correction.status IN ('FAILED_FINAL','DEAD_LETTER') THEN 'FAILED'
             WHEN correction.status='CANCELLED' THEN 'CANCELLED'
             ELSE base.resolution
           END AS resolution,
           CASE
             WHEN action_version.lifecycle='SUPERSEDED' THEN 'SUPERSEDED'
             WHEN correction.status IN ('FAILED_FINAL','DEAD_LETTER') THEN 'FAILED'
             WHEN correction.status='CANCELLED' THEN 'CANCELLED'
             WHEN base.status<>'ADMITTED' THEN base.status
             WHEN correction.status IN (
               'ADMITTED','READY','EXECUTING','WAITING_EXTERNAL_RESULT',
               'RECONCILIATION_REQUIRED','CANCELLATION_REQUESTED',
               'FAILED_RETRYABLE'
             ) THEN 'IN_PROGRESS'
             WHEN correction.status='SUCCEEDED' THEN 'REEVALUATION_PENDING'
             ELSE base.status
           END AS status,
           base.created_at
    FROM authority_corrective_action_lineage_projection_v84_base AS base
    LEFT JOIN authority_asset_version AS action_version
      ON action_version.asset_version_id=base.action_asset_version_id
    LEFT JOIN LATERAL (
      SELECT operation.operation_id, operation.status, attempt.attempt_id
      FROM authority_operation AS operation
      LEFT JOIN LATERAL (
        SELECT item.attempt_id
        FROM authority_attempt AS item
        WHERE item.operation_id=operation.operation_id
        ORDER BY item.attempt_number DESC
        LIMIT 1
      ) AS attempt ON TRUE
      WHERE base.issue_id LIKE 'corrective-issue:quality:%'
        AND operation.project_id=base.project_id
        AND operation.definition_name='chapter.revision.apply'
        AND EXISTS (
          SELECT 1
          FROM jsonb_array_elements(operation.input_asset_snapshot) AS input(value)
          WHERE input.value->>'asset_version_id'=base.source_asset_version_id
        )
      ORDER BY operation.created_at DESC, operation.operation_id DESC
      LIMIT 1
    ) AS correction ON TRUE
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []
