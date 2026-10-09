from __future__ import annotations

from .v20261009_0185_pure_generation_isolation import UPGRADE_STATEMENTS as ISOLATION_STATEMENTS

MIGRATION_ID = "20261009_0189_unsent_context_successor"
DOWN_REVISION = "20261009_0188_saved_result_admission"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Bind audited typed VolumePlan Context successors to proven unsent requests while retaining failed Attempts."

UPGRADE_STATEMENTS = [
    """CREATE FUNCTION authority_unsent_context_continuation_permitted(runtime_id TEXT, child_id TEXT, generation JSONB)
    RETURNS BOOLEAN LANGUAGE SQL STABLE AS $$
    SELECT EXISTS(SELECT 1 FROM authority_story_planning_runtime_continuation r
      JOIN authority_operation registered ON registered.operation_id=r.registered_by_operation_id
      JOIN authority_operation source ON source.operation_id=r.source_operation_id
      JOIN authority_operation child ON child.operation_id=child_id
      JOIN authority_story_planning_generation prior ON prior.operation_id=source.operation_id
      JOIN authority_operation_output_asset context_output ON context_output.operation_id=source.operation_id
        AND context_output.output_key='planning.context_bundle'
      JOIN authority_asset_version context ON context.asset_version_id=context_output.asset_version_id
      JOIN authority_story_formation_run formation ON formation.formation_run_id=r.decision_evidence->>'formation_run_id'
      WHERE r.continuation_id=runtime_id AND r.successor_operation_id=child_id AND r.chain_depth BETWEEN 1 AND 2
      AND source.status='FAILED_FINAL' AND source.definition_name='story_planning.generate'
      AND registered.status='SUCCEEDED' AND registered.definition_name='story_planning.runtime_continuation.register'
      AND formation.project_id=r.project_id AND formation.book_id=r.book_id AND formation.workspace_id=r.workspace_id
      AND formation.frozen_stage_inputs #>> '{generation_policy,auto_authorization,authorized_by_principal_id}'=registered.actor_id
      AND NOT EXISTS(SELECT 1 FROM authority_story_creation_cancellation WHERE formation_run_id=formation.formation_run_id)
      AND r.source_command=source.command_payload->'payload' AND r.successor_command=child.command_payload->'payload'
      AND (r.successor_command-'runtime_continuation_id'-'idempotency_key'-'opening_execution_binding')=
          (r.source_command-'runtime_continuation_id'-'idempotency_key'-'opening_execution_binding')
      AND r.target_runtime #>> '{planning_capacity,context_revalidation,contract_version}'='typed-volume-context-projection.v1'
      AND r.target_runtime #>> '{planning_capacity,context_revalidation,context_asset_version_id}'=context.asset_version_id
      AND r.target_runtime #>> '{planning_capacity,context_revalidation,context_content_hash}'=context.content_hash
      AND r.target_runtime #> '{planning_capacity,external_intents_at_source}'='0'::jsonb
      AND child.causation_operation_id=source.operation_id AND child.project_id=r.project_id AND child.workspace_id=r.workspace_id
      AND child.actor_id=source.actor_id AND source.project_id=r.project_id AND source.workspace_id=r.workspace_id
      AND generation->>'book_id'=r.book_id AND generation->>'generator_operation_name'='arc_plan.generate'
      AND generation->>'generator_operation_name'=prior.generator_operation_name
      AND generation->>'logical_key'=prior.logical_key AND generation->>'planning_scope'=prior.planning_scope
      AND generation->'input_snapshot'=prior.input_snapshot AND generation->>'input_snapshot_hash'=prior.input_snapshot_hash
      AND (generation->>'repair_number')::int=prior.repair_number
      AND generation->>'narrative_search_id' IS NOT DISTINCT FROM prior.narrative_search_id
      AND generation->>'narrative_search_branch_key' IS NOT DISTINCT FROM prior.narrative_search_branch_key
      AND generation->>'candidate_asset_version_id' IS NULL
      AND NOT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=source.operation_id)
      AND NOT EXISTS(SELECT 1 FROM authority_budget_reservation WHERE operation_id=source.operation_id)
      AND NOT EXISTS(SELECT 1 FROM authority_lease_acquisition lease JOIN authority_attempt attempt USING(attempt_id)
        WHERE attempt.operation_id=source.operation_id AND lease.status='HELD')
      AND EXISTS(SELECT 1 FROM authority_attempt attempt WHERE attempt.operation_id=source.operation_id
        AND attempt.attempt_number=(SELECT max(attempt_number) FROM authority_attempt WHERE operation_id=source.operation_id)
        AND attempt.status IN ('FAILED_RETRYABLE','FAILED_FINAL')
        AND COALESCE(attempt.error->>'error_code',attempt.result->>'error_code')='PROVIDER_ROUTING_BLOCKED')
      AND EXISTS(SELECT 1 FROM authority_operation_output_asset output
        JOIN authority_asset_version version USING(asset_version_id) JOIN authority_asset asset ON asset.asset_id=version.asset_id
        WHERE output.operation_id=source.operation_id AND asset.asset_type='routing_decision'
        AND version.content->>'decision_id'=r.target_runtime #>> '{planning_capacity,context_revalidation,blocked_decision_id}'
        AND version.content->>'status'='BLOCKED' AND version.content #>> '{task,operation_id}'=source.operation_id
        AND version.content #>> '{task,project_id}'=r.project_id AND version.content #>> '{task,work_id}'=r.book_id
        AND jsonb_array_length(version.content->'candidates')>0
        AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(version.content->'candidates') candidate
          WHERE NOT (candidate->'rejected_reasons' ? 'CONTEXT_CAPACITY_EXCEEDED')
            OR (candidate->'rejected_reasons')-'CONTEXT_CAPACITY_EXCEEDED'-'BUDGET_HARD_LIMIT'<>'[]'::jsonb))
    ) $$""",
    next(statement for statement in ISOLATION_STATEMENTS if "CREATE OR REPLACE FUNCTION authority_planning_result_repair_guard()" in statement).replace(
        "AND NOT authority_generation_continuation_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))",
        "AND NOT authority_generation_continuation_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))\n               AND NOT authority_unsent_context_continuation_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))",
    ),
]
DOWNGRADE_STATEMENTS: list[str] = []
