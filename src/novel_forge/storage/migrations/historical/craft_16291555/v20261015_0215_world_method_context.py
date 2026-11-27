from __future__ import annotations

from .v20261014_0214_book_query_recovery import UPGRADE_STATEMENTS as PREVIOUS

MIGRATION_ID = "20261015_0215_world_method_context"
DOWN_REVISION = "20261014_0214_book_query_recovery"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Retain the exact zero-send protected World Context failure and its two immutable outputs under an explicit versioned method projection."

_SQL = """CREATE FUNCTION authority_unsent_world_context_continuation_permitted(runtime_id TEXT, child_id TEXT, generation JSONB)
RETURNS BOOLEAN LANGUAGE SQL STABLE AS $$
SELECT EXISTS(SELECT 1 FROM authority_story_planning_runtime_continuation r
 JOIN authority_operation registered ON registered.operation_id=r.registered_by_operation_id
 JOIN authority_operation source ON source.operation_id=r.source_operation_id
 JOIN authority_operation child ON child.operation_id=child_id
 JOIN authority_story_planning_runtime_continuation previous ON previous.continuation_id=source.command_payload#>>'{payload,runtime_continuation_id}'
   AND previous.successor_operation_id=source.operation_id AND previous.project_id=r.project_id AND previous.workspace_id=r.workspace_id AND previous.book_id=r.book_id
 JOIN authority_story_planning_generation prior ON prior.operation_id=source.operation_id
 JOIN authority_attempt attempt ON attempt.operation_id=source.operation_id
   AND attempt.attempt_number=(SELECT max(attempt_number) FROM authority_attempt WHERE operation_id=source.operation_id)
 JOIN LATERAL regexp_match(attempt.result->>'error_message', '^PROTECTED_CONTEXT_BUDGET_EXCEEDED: (.+) exceeds TOTAL_CONTEXT_LIMIT; requires=([0-9]+), available=([0-9]+), used=([0-9]+), total=([0-9]+)$') signature(parts) ON TRUE
 JOIN authority_attempt_capability_pack_snapshot pack ON pack.attempt_id=attempt.attempt_id AND pack.operation_id=source.operation_id
 JOIN authority_story_formation_run formation ON formation.formation_run_id=r.decision_evidence->>'formation_run_id'
 JOIN authority_operation_output_asset context_output ON context_output.operation_id=source.operation_id AND context_output.output_key='planning.context_bundle'
 JOIN authority_asset_version context ON context.asset_version_id=context_output.asset_version_id AND context.content_hash=context_output.content_hash
 JOIN authority_asset context_owner ON context_owner.asset_id=context.asset_id AND context_owner.project_id=r.project_id AND context_owner.asset_type='context_bundle'
 JOIN authority_operation_output_asset world_output ON world_output.operation_id=source.operation_id
   AND world_output.output_key=r.target_runtime#>>'{planning_capacity,context_revalidation,world_source_output_key}'
 JOIN authority_asset_version world ON world.asset_version_id=world_output.asset_version_id AND world.content_hash=world_output.content_hash
 JOIN authority_asset world_owner ON world_owner.asset_id=world.asset_id AND world_owner.project_id=r.project_id AND world_owner.asset_type='world_preparation_source'
 WHERE r.continuation_id=runtime_id AND r.successor_operation_id=child_id AND r.chain_depth>0
 AND source.status='FAILED_FINAL' AND source.definition_name='story_planning.generate'
 AND attempt.status='FAILED_FINAL' AND attempt.result->>'error_code'='PROGRAMMING_BUG'
 AND attempt.result->>'failure_class'='programming_bug'
 AND signature.parts[1]=world.asset_version_id AND signature.parts[2]::numeric>signature.parts[3]::numeric
 AND world_output.output_key LIKE 'production_execution.contract.world_preparation_source.%'
 AND r.target_runtime#>'{planning_capacity,context_revalidation,source_failure}'=attempt.result
 AND r.target_runtime#>>'{planning_capacity,context_revalidation,contract_version}'='world-method-scope-projection.v1'
 AND r.target_runtime#>>'{planning_capacity,context_revalidation,source_operation_id}'=source.operation_id
 AND r.target_runtime#>>'{planning_capacity,context_revalidation,source_operation_status}'='FAILED_FINAL'
 AND r.target_runtime#>>'{planning_capacity,context_revalidation,context_asset_version_id}'=context.asset_version_id
 AND r.target_runtime#>>'{planning_capacity,context_revalidation,context_content_hash}'=context.content_hash
 AND r.target_runtime#>>'{planning_capacity,context_revalidation,world_source_asset_version_id}'=world.asset_version_id
 AND r.target_runtime#>>'{planning_capacity,context_revalidation,world_source_content_hash}'=world.content_hash
 AND r.target_runtime#>>'{planning_capacity,context_revalidation,prior_runtime_continuation_id}'=previous.continuation_id
 AND NOT EXISTS(SELECT 1 FROM (VALUES ('model_provider'),('model_id'),('reasoning_effort'),('runtime_class'),('model_backend_id'),('cost_accounting_basis')) identity(key)
   WHERE r.target_runtime->identity.key IS DISTINCT FROM previous.target_runtime->identity.key)
 AND (r.target_runtime->'account' #- '{entitlement,authorization_ref}')=(previous.target_runtime->'account' #- '{entitlement,authorization_ref}')
 AND context.content->>'world_method_scope_projection_version' IS NULL
 AND context.content->>'project_id'=r.project_id AND context.content->>'workspace_id'=r.workspace_id AND context.content->>'book_id'=r.book_id
 AND context.content->>'planning_scope'='CHAPTER'
 AND context.content#>>'{knowledge_access_policy,craft_candidate_review_version}'='explicit-allowlist-craft-review.v1'
 AND context.content#>>'{knowledge_access_policy,usage_scope}'='EXPERIMENTAL_VALIDATION'
 AND context.content#>>'{knowledge_access_policy,mode}'='ALLOW_ONLY'
 AND jsonb_array_length(context.content#>'{narrative_intelligence,selected}')>0
 AND world.content#>'{contract,request}'=r.source_command->'world_preparation_request'
 AND world.content#>'{contract,fact_mutation_allowed}'='false'::jsonb
 AND world.content#>>'{contract,reality,project_id}'=r.project_id AND world.content#>>'{contract,reality,book_id}'=r.book_id
 AND registered.status='SUCCEEDED' AND registered.definition_name='story_planning.runtime_continuation.register'
 AND formation.project_id=r.project_id AND formation.workspace_id=r.workspace_id AND formation.book_id=r.book_id
 AND formation.frozen_stage_inputs#>>'{generation_policy,auto_authorization,authorized_by_principal_id}'=registered.actor_id
 AND NOT EXISTS(SELECT 1 FROM authority_story_creation_cancellation WHERE formation_run_id=formation.formation_run_id)
 AND r.source_command->>'execution_contract_version'='1.21.0'
 AND r.source_command=source.command_payload->'payload' AND r.successor_command=child.command_payload->'payload'
 AND (r.successor_command-'runtime_continuation_id'-'idempotency_key')=(r.source_command-'runtime_continuation_id'-'idempotency_key')
 AND child.causation_operation_id=source.operation_id AND child.actor_id=source.actor_id
 AND child.project_id=r.project_id AND child.workspace_id=r.workspace_id
 AND source.project_id=r.project_id AND source.workspace_id=r.workspace_id
 AND prior.project_id=r.project_id AND prior.workspace_id=r.workspace_id AND prior.book_id=r.book_id
 AND generation->>'project_id'=r.project_id AND generation->>'workspace_id'=r.workspace_id AND generation->>'book_id'=r.book_id
 AND generation->>'generator_operation_name'='chapter_plan.generate' AND generation->>'generator_operation_name'=prior.generator_operation_name
 AND generation->>'logical_key'=prior.logical_key AND generation->>'planning_scope'=prior.planning_scope
 AND generation->'input_snapshot'=prior.input_snapshot AND generation->>'input_snapshot_hash'=prior.input_snapshot_hash
 AND generation->>'repair_number'=prior.repair_number::text
 AND generation->>'repair_of_operation_id' IS NOT DISTINCT FROM prior.repair_of_operation_id
 AND generation->>'repair_result_asset_version_id' IS NOT DISTINCT FROM prior.repair_result_asset_version_id
 AND generation->>'narrative_search_id' IS NOT DISTINCT FROM prior.narrative_search_id
 AND generation->>'narrative_search_branch_key' IS NOT DISTINCT FROM prior.narrative_search_branch_key
 AND generation->>'candidate_asset_version_id' IS NULL AND prior.candidate_asset_version_id IS NULL
 AND NOT EXISTS(SELECT 1 FROM (VALUES ('prompt_bundle_hash'),('route_policy_hash'),('context_policy_hash'),('skill_bundle_hash'),('tool_policy_hash')) identity(key)
   WHERE pack.snapshot_payload->identity.key IS DISTINCT FROM r.target_runtime->'pack_snapshot'->identity.key)
 AND r.target_runtime#>'{planning_capacity,external_intents_at_source}'='0'::jsonb
 AND NOT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=source.operation_id)
 AND NOT EXISTS(SELECT 1 FROM authority_budget_reservation WHERE operation_id=source.operation_id)
 AND (SELECT count(*) FROM authority_operation_output_asset WHERE operation_id=source.operation_id)=2
 AND NOT EXISTS(SELECT 1 FROM authority_operation_output_asset WHERE operation_id=source.operation_id
   AND asset_version_id NOT IN (context.asset_version_id,world.asset_version_id))
 AND NOT EXISTS(SELECT 1 FROM authority_attempt WHERE operation_id=source.operation_id AND status IN ('CLAIMED','EXECUTING','WAITING_EXTERNAL_RESULT','LEASED','RUNNING','CHECKPOINTED','RESULT_SUBMITTED'))
 AND NOT EXISTS(SELECT 1 FROM authority_lease_acquisition lease JOIN authority_attempt attempt USING(attempt_id) WHERE attempt.operation_id=source.operation_id AND lease.status='HELD')
 AND NOT EXISTS(SELECT 1 FROM authority_worker_cancel_signal WHERE operation_id=source.operation_id AND acknowledged_at IS NULL)
 AND NOT EXISTS(SELECT 1 FROM authority_book_production WHERE project_id=r.project_id AND book_id=r.book_id AND state IN ('ABORTED','CANCELLED','COMPLETED'))
) $$"""
_GUARD = 'AND NOT authority_book_unsent_query_continuation_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))'
assert PREVIOUS[1].count(_GUARD) == 1
UPGRADE_STATEMENTS = [_SQL, PREVIOUS[1].replace(_GUARD,
    _GUARD + '\n               AND NOT authority_unsent_world_context_continuation_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))')]
DOWNGRADE_STATEMENTS: list[str] = []
