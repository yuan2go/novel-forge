from __future__ import annotations

from .v20261009_0189_unsent_context_successor import UPGRADE_STATEMENTS as CONTEXT_STATEMENTS

MIGRATION_ID = '20261009_0191_provider_schema_successor'
DOWN_REVISION = '20261009_0190_group_window_successor'
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = 'Admit equivalent corrected Provider Schema successors with exact task identities and retained completed stages.'

UPGRADE_STATEMENTS = [
    """CREATE FUNCTION authority_schema_continuation_permitted(runtime_id TEXT, child_id TEXT, task_generation JSONB)
    RETURNS BOOLEAN LANGUAGE SQL STABLE AS $$
    SELECT EXISTS(SELECT 1 FROM authority_story_planning_runtime_continuation r
      JOIN authority_operation source ON source.operation_id=r.source_operation_id
      JOIN authority_story_planning_generation prior ON prior.operation_id=source.operation_id
      JOIN authority_operation registered ON registered.operation_id=r.registered_by_operation_id
      JOIN authority_operation child ON child.operation_id=child_id
      JOIN authority_operation_output_asset output ON output.operation_id=source.operation_id
        AND output.asset_version_id=r.target_runtime #>> '{provider_schema_correction,model_call_log_asset_version_id}'
      JOIN authority_asset_version evidence ON evidence.asset_version_id=output.asset_version_id
      JOIN authority_external_effect effect ON effect.external_effect_id=r.target_runtime #>> '{provider_schema_correction,external_effect_id}'
      JOIN authority_external_effect_dispatch dispatch USING(external_effect_id)
      JOIN authority_story_formation_run formation ON formation.formation_run_id=r.decision_evidence->>'formation_run_id'
      WHERE r.continuation_id=runtime_id AND r.successor_operation_id=child_id
      AND source.status='FAILED_FINAL' AND source.definition_name='story_planning.generate'
      AND registered.status='SUCCEEDED' AND registered.definition_name='story_planning.runtime_continuation.register'
      AND formation.project_id=r.project_id AND formation.workspace_id=r.workspace_id AND formation.book_id=r.book_id
      AND formation.frozen_stage_inputs #>> '{generation_policy,auto_authorization,authorized_by_principal_id}'=registered.actor_id
      AND NOT EXISTS(SELECT 1 FROM authority_story_creation_cancellation WHERE formation_run_id=formation.formation_run_id)
      AND r.source_command=source.command_payload->'payload' AND r.successor_command=child.command_payload->'payload'
      AND (r.successor_command-'runtime_continuation_id'-'idempotency_key'-'opening_execution_binding')=
          (r.source_command-'runtime_continuation_id'-'idempotency_key'-'opening_execution_binding')
      AND child.causation_operation_id=source.operation_id AND child.actor_id=source.actor_id AND registered.actor_id=source.actor_id
      AND child.project_id=r.project_id AND child.workspace_id=r.workspace_id
      AND source.project_id=r.project_id AND source.workspace_id=r.workspace_id
      AND task_generation->>'book_id'=r.book_id AND task_generation->>'generator_operation_name'=prior.generator_operation_name
      AND task_generation->>'logical_key'=prior.logical_key AND task_generation->>'planning_scope'=prior.planning_scope
      AND task_generation->'input_snapshot'=prior.input_snapshot AND task_generation->>'input_snapshot_hash'=prior.input_snapshot_hash
      AND (task_generation->>'repair_number')::int=prior.repair_number
      AND task_generation->>'narrative_search_id' IS NOT DISTINCT FROM prior.narrative_search_id
      AND task_generation->>'narrative_search_branch_key' IS NOT DISTINCT FROM prior.narrative_search_branch_key
      AND task_generation->>'candidate_asset_version_id' IS NULL AND prior.candidate_asset_version_id IS NULL
      AND effect.operation_id=source.operation_id AND effect.project_id=r.project_id
      AND effect.effect_type='model.invoke' AND effect.status='FAILED_FINAL' AND dispatch.status='FAILED_FINAL'
      AND dispatch.evidence->'production_execution'=evidence.content->'production_execution'
      AND evidence.content_hash=r.target_runtime #>> '{provider_schema_correction,model_call_log_content_hash}'
      AND evidence.content->>'stage'=prior.generator_operation_name
      AND evidence.content #>> '{production_execution,process_evidence,failure_code}'='PROVIDER_SCHEMA_REJECTED'
      AND evidence.content #>> '{production_execution,process_evidence,provider_schema_contract,equivalent_projection}'='codex-nullable-shared-types.v2'
      AND r.target_runtime #>> '{provider_schema_correction,wire_correction,contract_version}'='codex-nullable-shared-types.v3'
      AND r.target_runtime #>> '{provider_schema_correction,wire_correction,reversible_equivalence}'='EXACT'
      AND r.target_runtime #>> '{provider_schema_correction,wire_correction,canonical_hash}'=
          evidence.content #>> '{production_execution,process_evidence,provider_schema_contract,canonical_hash}'
      AND r.target_runtime #>> '{provider_schema_correction,wire_correction,previous_wire_hash}'=
          evidence.content #>> '{production_execution,process_evidence,provider_schema_contract,provider_hash}'
      AND r.target_runtime #>> '{provider_schema_correction,wire_correction,corrected_wire_hash}' <>
          r.target_runtime #>> '{provider_schema_correction,wire_correction,previous_wire_hash}'
      AND NOT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=source.operation_id
        AND (effect_type<>'model.invoke' OR status NOT IN ('SUCCEEDED','FAILED_FINAL')))
      AND NOT EXISTS(SELECT 1 FROM authority_lease_acquisition lease JOIN authority_attempt attempt USING(attempt_id)
        WHERE attempt.operation_id=source.operation_id AND lease.status='HELD')
    ) $$""",
    CONTEXT_STATEMENTS[1].replace(
        'AND NOT authority_unsent_context_continuation_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))',
        'AND NOT authority_unsent_context_continuation_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))\n               AND NOT authority_schema_continuation_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))',
    ),
]
DOWNGRADE_STATEMENTS: list[str] = []
