from __future__ import annotations


MIGRATION_ID = "20260812_0084_development_gap_final_convergence"
DOWN_REVISION = "20260812_0083_narrative_runtime_convergence"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = (
    "rebuild the derived projections from immutable Authority assets, Operations, "
    "Attempts, ExternalEffects, Capability snapshots, and PlanChange records"
)


UPGRADE_STATEMENTS = [
    "DROP INDEX IF EXISTS authority_runtime_job_active_subject_idx",
    "DROP INDEX IF EXISTS authority_runtime_job_dedupe_idx",
    """
    CREATE UNIQUE INDEX authority_runtime_job_dedupe_idx
    ON authority_runtime_job(project_id, runtime_group, job_kind, dedupe_key)
    """,
    """
    CREATE UNIQUE INDEX authority_runtime_job_active_subject_idx
    ON authority_runtime_job(
      project_id, runtime_group, job_kind, subject_kind, subject_id
    )
    WHERE status IN ('READY','CLAIMED','RUNNING','CHECKPOINTED','RETRY_WAIT')
    """,
    """
    CREATE TABLE authority_book_replan_reevaluation (
        reevaluation_id TEXT PRIMARY KEY,
        replan_id TEXT NOT NULL REFERENCES authority_book_replan(replan_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        source_recap_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        deviation_report_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        evaluation_operation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_operation(operation_id),
        gate_result TEXT NOT NULL,
        resolution TEXT NOT NULL,
        remaining_issue_types JSONB NOT NULL,
        evidence_refs JSONB NOT NULL,
        stable_idempotency_key TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, replan_id, stable_idempotency_key),
        CHECK (gate_result IN ('PASSED','FAILED')),
        CHECK (resolution IN ('RESOLVED','ESCALATED')),
        CHECK (jsonb_typeof(remaining_issue_types)='array'),
        CHECK (jsonb_typeof(evidence_refs)='array'),
        CHECK (
          (gate_result='PASSED' AND resolution='RESOLVED'
           AND jsonb_array_length(remaining_issue_types)=0)
          OR
          (gate_result='FAILED' AND resolution='ESCALATED'
           AND jsonb_array_length(remaining_issue_types)>0)
        )
    )
    """,
    """
    CREATE INDEX authority_book_replan_reevaluation_query_idx
    ON authority_book_replan_reevaluation(
      project_id, replan_id, created_at DESC
    )
    """,
    """
    CREATE INDEX authority_book_replan_reevaluation_recap_idx
    ON authority_book_replan_reevaluation(source_recap_asset_version_id)
    """,
    """
    CREATE INDEX authority_book_replan_reevaluation_deviation_idx
    ON authority_book_replan_reevaluation(deviation_report_asset_version_id)
    """,
    "DROP VIEW IF EXISTS authority_corrective_action_lineage_projection",
    "DROP VIEW IF EXISTS authority_mkaos_runtime_usage_projection",
    "DROP VIEW IF EXISTS authority_mkaos_runtime_selection_projection",
    "DROP VIEW IF EXISTS authority_context_runtime_usage_projection",
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
      AND context_version.content->>'context_contract_version'=
          'authority-context-bundle-v5'
      AND context_version.content->'context_manifest'->>'contract_version'=
          'narrative-context-manifest-v1'
    """,
    """
    CREATE VIEW authority_mkaos_runtime_selection_projection AS
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
      AND context_version.content->>'context_contract_version'=
          'authority-context-bundle-v5'
      AND context_version.content->'context_manifest'->>'contract_version'=
          'narrative-context-manifest-v1'
    """,
    """
    CREATE VIEW authority_mkaos_runtime_usage_projection AS
    SELECT DISTINCT
           selection.project_id,
           selection.book_id,
           selection.context_bundle_asset_version_id,
           selection.context_build_operation_id,
           consumer.operation_id AS consumer_operation_id,
           consumer.definition_name AS consumer_definition_name,
           effect.request_payload->'_production_execution'->>'attempt_id'
             AS attempt_id,
           effect.external_effect_id,
           effect.provider,
           effect.model_id,
           effect.provider_request_id,
           effect.capability AS capability_id,
           snapshot.snapshot_id AS capability_pack_snapshot_id,
           snapshot.pack_id AS capability_pack_id,
           snapshot.pack_version AS capability_pack_version,
           result.asset_version_id AS result_asset_version_id,
           result_asset.asset_type AS result_asset_type,
           selection.target_capability_id,
           selection.narrative_position,
           consumer.trace_id,
           selection.knowledge_pack_id,
           selection.knowledge_pack_asset_version_id,
           selection.knowledge_card_asset_version_id,
           selection.usage_role,
           selection.frozen_weight,
           selection.inclusion_reason,
           selection.narrative_function,
           effect.created_at AS consumed_at
    FROM authority_mkaos_runtime_selection_projection AS selection
    JOIN authority_operation AS consumer
      ON consumer.project_id=selection.project_id
     AND consumer.status='SUCCEEDED'
     AND EXISTS (
       SELECT 1
       FROM jsonb_array_elements(consumer.input_asset_snapshot) AS input(value)
       WHERE input.value->>'asset_version_id'=
             selection.context_bundle_asset_version_id
     )
    JOIN authority_external_effect AS effect
      ON effect.operation_id=consumer.operation_id
     AND effect.project_id=consumer.project_id
     AND effect.effect_type='model.invoke'
     AND effect.status='SUCCEEDED'
     AND EXISTS (
       SELECT 1
       FROM jsonb_array_elements(
         COALESCE(
           effect.request_payload->'_production_execution'->'input_artifacts',
           '[]'::jsonb
         )
       ) AS input(value)
       WHERE input.value->>'artifact_type'='context_bundle'
         AND input.value->>'asset_version_id'=
             selection.context_bundle_asset_version_id
     )
    LEFT JOIN authority_attempt_capability_pack_snapshot AS snapshot
      ON snapshot.operation_id=consumer.operation_id
     AND snapshot.attempt_id=
         effect.request_payload->'_production_execution'->>'attempt_id'
    JOIN authority_operation_output_asset AS result
      ON result.operation_id=consumer.operation_id
     AND result.role='primary'
    JOIN authority_asset AS result_asset
      ON result_asset.asset_id=result.asset_id
     AND result_asset.project_id=selection.project_id
    """,
    """
    CREATE VIEW authority_corrective_action_lineage_projection AS
    WITH review_issue AS (
      SELECT operation.project_id,
             operation.operation_id AS source_operation_id,
             version.asset_version_id AS source_asset_version_id,
             issue.value AS issue,
             version.created_at
      FROM authority_operation AS operation
      JOIN authority_operation_output_asset AS output
        ON output.operation_id=operation.operation_id
       AND output.output_key='chapter.review'
      JOIN authority_asset_version AS version
        ON version.asset_version_id=output.asset_version_id
      CROSS JOIN LATERAL jsonb_array_elements(
        COALESCE(version.content->'issues','[]'::jsonb)
      ) AS issue(value)
      WHERE operation.status='SUCCEEDED'
    ), review_flow AS (
      SELECT issue.*,
             revision.operation_id AS execution_operation_id,
             revision.attempt_id AS execution_attempt_id,
             revision.result_asset_version_id,
             evaluation.operation_id AS evaluation_operation_id,
             evaluation.asset_version_id AS evaluation_asset_version_id,
             evaluation.lineage
      FROM review_issue AS issue
      LEFT JOIN LATERAL (
        SELECT operation.operation_id, attempt.attempt_id,
               output.asset_version_id AS result_asset_version_id
        FROM authority_operation AS operation
        JOIN authority_operation_output_asset AS output
          ON output.operation_id=operation.operation_id
         AND output.output_key='chapter.revision'
        LEFT JOIN LATERAL (
          SELECT attempt.attempt_id
          FROM authority_attempt AS attempt
          WHERE attempt.operation_id=operation.operation_id
            AND attempt.status='SUCCEEDED'
          ORDER BY attempt.attempt_number DESC LIMIT 1
        ) AS attempt ON TRUE
        WHERE operation.project_id=issue.project_id
          AND operation.status='SUCCEEDED'
          AND EXISTS (
            SELECT 1
            FROM jsonb_array_elements(operation.input_asset_snapshot) AS input(value)
            WHERE input.value->>'asset_version_id'=issue.source_asset_version_id
          )
        ORDER BY operation.created_at DESC LIMIT 1
      ) AS revision ON TRUE
      LEFT JOIN LATERAL (
        SELECT operation.operation_id, output.asset_version_id,
               lineage.value AS lineage
        FROM authority_operation AS operation
        JOIN authority_operation_output_asset AS output
          ON output.operation_id=operation.operation_id
         AND output.output_key='chapter.rereview'
        JOIN authority_asset_version AS version
          ON version.asset_version_id=output.asset_version_id
        CROSS JOIN LATERAL jsonb_array_elements(
          COALESCE(version.content->'issue_lineage','[]'::jsonb)
        ) AS lineage(value)
        WHERE revision.operation_id IS NOT NULL
          AND operation.project_id=issue.project_id
          AND operation.status='SUCCEEDED'
          AND lineage.value->>'review_issue_id'=
              issue.issue->>'review_issue_id'
          AND EXISTS (
            SELECT 1
            FROM jsonb_array_elements(operation.input_asset_snapshot) AS input(value)
            WHERE input.value->>'asset_version_id'=issue.source_asset_version_id
          )
          AND EXISTS (
            SELECT 1
            FROM jsonb_array_elements(operation.input_asset_snapshot) AS input(value)
            WHERE input.value->>'asset_version_id'=
                  revision.result_asset_version_id
          )
        ORDER BY operation.created_at DESC LIMIT 1
      ) AS evaluation ON TRUE
    ), quality_issue AS (
      SELECT operation.project_id,
             operation.operation_id AS source_operation_id,
             version.asset_version_id AS source_asset_version_id,
             version.content AS issue,
             version.created_at
      FROM authority_operation AS operation
      JOIN authority_operation_output_asset AS output
        ON output.operation_id=operation.operation_id
       AND output.role='required_action'
      JOIN authority_asset AS asset ON asset.asset_id=output.asset_id
       AND asset.asset_type='revision_task'
      JOIN authority_asset_version AS version
        ON version.asset_version_id=output.asset_version_id
      WHERE operation.status='SUCCEEDED'
    ), reader_issue AS (
      SELECT operation.project_id,
             operation.operation_id AS source_operation_id,
             version.asset_version_id AS source_asset_version_id,
             issue.value,
             candidate.asset_version_id AS action_asset_version_id,
             version.created_at
      FROM authority_operation AS operation
      JOIN authority_operation_output_asset AS output
        ON output.operation_id=operation.operation_id
       AND output.output_key='reader_outcome.issue_set'
      JOIN authority_asset_version AS version
        ON version.asset_version_id=output.asset_version_id
      CROSS JOIN LATERAL jsonb_array_elements(
        COALESCE(version.content->'issues','[]'::jsonb)
      ) AS issue(value)
      LEFT JOIN authority_operation_output_asset AS candidate
        ON candidate.operation_id=operation.operation_id
       AND candidate.output_key='reader_outcome.plan_adjustment_candidate'
      WHERE operation.status='SUCCEEDED'
    ), longform_issue AS (
      SELECT operation.project_id,
             operation.operation_id AS source_operation_id,
             version.asset_version_id AS source_asset_version_id,
             issue.value,
             COALESCE(replan_request.asset_version_id,
                      adjustment.asset_version_id) AS action_asset_version_id,
             replan.replan_id,
             replan.created_by_operation_id,
             replan.replacement_candidate_asset_version_id,
             replan.status AS replan_status,
             plan_change.activation_operation_id,
             reevaluation.evaluation_operation_id,
             reevaluation.deviation_report_asset_version_id
               AS evaluation_asset_version_id,
             reevaluation.gate_result,
             reevaluation.resolution,
             version.created_at
      FROM authority_operation AS operation
      JOIN authority_operation_output_asset AS output
        ON output.operation_id=operation.operation_id
       AND output.output_key='longform.recap.deviation_report'
      JOIN authority_asset_version AS version
        ON version.asset_version_id=output.asset_version_id
      CROSS JOIN LATERAL jsonb_array_elements(
        COALESCE(version.content->'deviations','[]'::jsonb)
      ) AS issue(value)
      LEFT JOIN authority_operation_output_asset AS replan_request
        ON replan_request.operation_id=operation.operation_id
       AND replan_request.output_key='longform.recap.replan_request'
      LEFT JOIN authority_operation_output_asset AS adjustment
        ON adjustment.operation_id=operation.operation_id
       AND adjustment.output_key='longform.recap.adjustment_proposal'
      LEFT JOIN authority_book_replan AS replan
        ON replan.replan_request_asset_version_id=replan_request.asset_version_id
      LEFT JOIN authority_plan_change_proposal AS plan_change
        ON plan_change.proposal_id=replan.plan_change_proposal_id
      LEFT JOIN LATERAL (
        SELECT item.evaluation_operation_id,
               item.deviation_report_asset_version_id,
               item.gate_result, item.resolution
        FROM authority_book_replan_reevaluation AS item
        WHERE item.replan_id=replan.replan_id
          AND item.project_id=operation.project_id
        ORDER BY item.created_at DESC LIMIT 1
      ) AS reevaluation ON TRUE
      WHERE operation.status='SUCCEEDED'
    )
    SELECT flow.issue->>'review_issue_id' AS issue_id,
           flow.project_id, flow.source_operation_id,
           flow.source_asset_version_id,
           flow.issue->>'code' AS issue_type,
           UPPER(flow.issue->>'severity') AS severity,
           jsonb_build_array(flow.issue->'evidence_locator') AS evidence_refs,
           'corrective-action:' || (flow.issue->>'review_issue_id') AS action_id,
           'LOCAL_REVISION'::TEXT AS action_type,
           jsonb_build_object(
             'target_asset_version_id',flow.issue->>'target_asset_version_id'
           ) AS target_scope,
           'ChapterRevisionAuthority'::TEXT AS required_authority,
           'chapter.rereview'::TEXT AS reevaluation_gate,
           NULL::TEXT AS action_asset_version_id,
           flow.execution_operation_id, flow.execution_attempt_id,
           CASE WHEN flow.result_asset_version_id IS NULL THEN '[]'::jsonb
             ELSE jsonb_build_array(flow.result_asset_version_id) END
             AS result_asset_version_ids,
           flow.evaluation_operation_id,
           flow.evaluation_asset_version_id,
           CASE WHEN flow.evaluation_operation_id IS NULL THEN 'NOT_OBSERVED'
             WHEN flow.lineage->>'to_status'='RESOLVED' THEN 'PASSED'
             ELSE 'FAILED' END AS gate_result,
           CASE WHEN flow.evaluation_operation_id IS NULL THEN NULL
             WHEN flow.lineage->>'to_status'='RESOLVED' THEN 'RESOLVED'
             ELSE 'ESCALATED' END AS resolution,
           CASE WHEN flow.execution_operation_id IS NULL THEN 'ADMITTED'
             WHEN flow.evaluation_operation_id IS NULL THEN 'REEVALUATION_PENDING'
             WHEN flow.lineage->>'to_status'='RESOLVED' THEN 'RESOLVED'
             ELSE 'ESCALATED' END AS status,
           flow.created_at
    FROM review_flow AS flow
    UNION ALL
    SELECT 'corrective-issue:quality:' || md5(
             issue.project_id || ':' || issue.source_asset_version_id
           ),
           issue.project_id, issue.source_operation_id,
           issue.source_asset_version_id,
           COALESCE(issue.issue->>'observation',
                    issue.issue->'issue'->>'code','QUALITY_ISSUE'),
           UPPER(COALESCE(issue.issue->'issue'->>'severity','MAJOR')),
           COALESCE(issue.issue->'evidence_asset_version_ids','[]'::jsonb),
           'corrective-action:quality:' || md5(
             issue.project_id || ':' || issue.source_asset_version_id
           ),
           COALESCE(issue.issue->>'action_type','LOCAL_REVISION'),
           COALESCE(issue.issue->'target_scope','{}'::jsonb),
           issue.issue->>'required_authority',
           issue.issue->>'reevaluation_gate',
           issue.source_asset_version_id,
           execution.operation_id, execution.attempt_id,
           CASE WHEN execution.result_asset_version_id IS NULL THEN '[]'::jsonb
             ELSE jsonb_build_array(execution.result_asset_version_id) END,
           evaluation.operation_id, evaluation.asset_version_id,
           CASE WHEN evaluation.operation_id IS NULL THEN 'NOT_OBSERVED'
             WHEN evaluation.action_still_required THEN 'FAILED'
             ELSE 'PASSED' END,
           CASE WHEN evaluation.operation_id IS NULL THEN NULL
             WHEN evaluation.action_still_required THEN 'ESCALATED'
             ELSE 'RESOLVED' END,
           CASE WHEN execution.operation_id IS NULL THEN 'ADMITTED'
             WHEN evaluation.operation_id IS NULL THEN 'REEVALUATION_PENDING'
             WHEN evaluation.action_still_required THEN 'ESCALATED'
             ELSE 'RESOLVED' END,
           issue.created_at
    FROM quality_issue AS issue
    LEFT JOIN LATERAL (
      SELECT operation.operation_id, attempt.attempt_id,
             output.asset_version_id AS result_asset_version_id
      FROM authority_operation AS operation
      JOIN authority_operation_output_asset AS output
        ON output.operation_id=operation.operation_id
       AND output.output_key='chapter.revision'
      LEFT JOIN LATERAL (
        SELECT attempt.attempt_id FROM authority_attempt AS attempt
        WHERE attempt.operation_id=operation.operation_id
          AND attempt.status='SUCCEEDED'
        ORDER BY attempt.attempt_number DESC LIMIT 1
      ) AS attempt ON TRUE
      WHERE operation.project_id=issue.project_id
        AND operation.status='SUCCEEDED'
        AND EXISTS (
          SELECT 1 FROM jsonb_array_elements(operation.input_asset_snapshot) input(value)
          WHERE input.value->>'asset_version_id'=issue.source_asset_version_id
        )
      ORDER BY operation.created_at DESC LIMIT 1
    ) AS execution ON TRUE
    LEFT JOIN LATERAL (
      SELECT operation.operation_id, output.asset_version_id,
             EXISTS (
               SELECT 1
               FROM jsonb_array_elements(
                 COALESCE(version.content->'required_actions','[]'::jsonb)
               ) action(value)
               WHERE COALESCE(action.value->>'observation',
                              action.value->'issue'->>'code')=
                     COALESCE(issue.issue->>'observation',
                              issue.issue->'issue'->>'code')
             ) AS action_still_required
      FROM authority_operation AS operation
      JOIN authority_operation_output_asset AS output
        ON output.operation_id=operation.operation_id
       AND output.output_key='chapter.quality'
      JOIN authority_asset_version AS version
        ON version.asset_version_id=output.asset_version_id
      WHERE execution.operation_id IS NOT NULL
        AND operation.project_id=issue.project_id
        AND operation.status='SUCCEEDED'
        AND EXISTS (
          SELECT 1 FROM jsonb_array_elements(operation.input_asset_snapshot) input(value)
          WHERE input.value->>'asset_version_id'=issue.source_asset_version_id
        )
        AND EXISTS (
          SELECT 1 FROM jsonb_array_elements(operation.input_asset_snapshot) input(value)
          WHERE input.value->>'asset_version_id'=execution.result_asset_version_id
        )
      ORDER BY operation.created_at DESC LIMIT 1
    ) AS evaluation ON TRUE
    UNION ALL
    SELECT 'corrective-issue:reader:' || md5(
             issue.project_id || ':' || issue.source_asset_version_id || ':' ||
             COALESCE(issue.value->>'code','READER_ISSUE')
           ),
           issue.project_id, issue.source_operation_id,
           issue.source_asset_version_id,
           COALESCE(issue.value->>'code','READER_ISSUE'),
           UPPER(COALESCE(issue.value->>'severity','MAJOR')),
           COALESCE(issue.value->'evidence','[]'::jsonb),
           'corrective-action:reader:' || md5(
             issue.project_id || ':' || issue.source_asset_version_id || ':' ||
             COALESCE(issue.value->>'code','READER_ISSUE')
           ),
           'FUTURE_PLAN_ADJUSTMENT',
           jsonb_build_object('mutation_scope','FUTURE_ONLY'),
           'PlanChangeAuthority', 'longform.recap',
           issue.action_asset_version_id,
           NULL::TEXT, NULL::TEXT, '[]'::jsonb,
           NULL::TEXT, NULL::TEXT, 'NOT_OBSERVED', NULL::TEXT,
           CASE WHEN issue.action_asset_version_id IS NULL THEN 'OPEN'
                ELSE 'ADMITTED' END,
           issue.created_at
    FROM reader_issue AS issue
    UNION ALL
    SELECT 'corrective-issue:longform:' || md5(
             issue.project_id || ':' || issue.source_asset_version_id || ':' ||
             COALESCE(issue.value->>'type','LONGFORM_DEVIATION')
           ),
           issue.project_id, issue.source_operation_id,
           issue.source_asset_version_id,
           COALESCE(issue.value->>'type','LONGFORM_DEVIATION'),
           UPPER(COALESCE(issue.value->>'severity','MAJOR')),
           jsonb_build_array(issue.value->'evidence'),
           'corrective-action:longform:' || md5(
             issue.project_id || ':' || issue.source_asset_version_id || ':' ||
             COALESCE(issue.value->>'type','LONGFORM_DEVIATION')
           ),
           CASE WHEN issue.replan_id IS NULL THEN 'PLAN_ADJUSTMENT'
                ELSE 'GOVERNED_REPLAN' END,
           jsonb_build_object('future_only',TRUE),
           'PlanChangeAuthority', 'longform.recap',
           issue.action_asset_version_id,
           COALESCE(issue.activation_operation_id,
                    issue.created_by_operation_id),
           NULL::TEXT,
           CASE WHEN issue.replacement_candidate_asset_version_id IS NULL
                THEN '[]'::jsonb
                ELSE jsonb_build_array(
                  issue.replacement_candidate_asset_version_id
                ) END,
           issue.evaluation_operation_id,
           issue.evaluation_asset_version_id,
           COALESCE(
             issue.gate_result,
             CASE WHEN issue.replan_status='RESUMED' THEN 'NOT_OBSERVED'
                  ELSE 'NOT_AVAILABLE' END
           ),
           issue.resolution,
           CASE WHEN issue.replan_id IS NULL THEN 'ADMITTED'
                WHEN issue.replan_status IN ('FAILED','REJECTED') THEN 'FAILED'
                WHEN issue.resolution IS NOT NULL THEN issue.resolution
                WHEN issue.replan_status='RESUMED' THEN 'REEVALUATION_PENDING'
                WHEN issue.activation_operation_id IS NOT NULL THEN 'APPLIED'
                ELSE 'IN_PROGRESS' END,
           issue.created_at
    FROM longform_issue AS issue
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []
