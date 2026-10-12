from __future__ import annotations

from .v20261011_0199_plan_change_capacity import UPGRADE_STATEMENTS as PREVIOUS

MIGRATION_ID = '20261012_0202_prepared_planning_continuation'
DOWN_REVISION = '20261012_0201_working_revision_generation_isolation'
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = 'Retain exact verified World preparation while correcting an unsent Planning request; preserve usage, source identities and stopped history.'

_WORLD = """CREATE FUNCTION authority_prepared_world_source_safe(source_id TEXT, runtime JSONB)
RETURNS BOOLEAN LANGUAGE SQL STABLE AS $$
SELECT EXISTS(SELECT 1 FROM authority_operation source
 JOIN authority_operation origin ON origin.operation_id=runtime#>>'{planning_capacity,retained_world_action,source_operation_id}'
 JOIN authority_asset_version action ON action.asset_version_id=runtime#>>'{planning_capacity,retained_world_action,world_action,asset_version_id}'
 JOIN authority_asset owner ON owner.asset_id=action.asset_id
 WHERE source.operation_id=source_id AND source.status IN ('FAILED_FINAL','DEAD_LETTER')
 AND source.definition_name='story_planning.generate'
 AND owner.project_id=source.project_id AND owner.asset_type='narrative_governance_action'
 AND action.content_hash=runtime#>>'{planning_capacity,retained_world_action,world_action,content_hash}'
 AND origin.status IN ('FAILED_FINAL','DEAD_LETTER','SUCCEEDED') AND origin.project_id=source.project_id
 AND origin.actor_id=source.actor_id AND origin.workspace_id=source.workspace_id
 AND origin.command_payload#>>'{payload,book_id}'=source.command_payload#>>'{payload,book_id}'
 AND (origin.operation_id=source_id OR EXISTS(SELECT 1 FROM authority_story_planning_runtime_continuation prior
   JOIN authority_operation registration ON registration.operation_id=prior.registered_by_operation_id
   WHERE prior.continuation_id=source.command_payload#>>'{payload,runtime_continuation_id}'
   AND prior.successor_operation_id=source_id AND prior.successor_command=source.command_payload->'payload'
   AND prior.project_id=source.project_id AND prior.book_id=source.command_payload#>>'{payload,book_id}'
   AND registration.status='SUCCEEDED' AND registration.definition_name='story_planning.runtime_continuation.register'
   AND (prior.target_runtime#>'{planning_capacity,retained_world_action}'=runtime#>'{planning_capacity,retained_world_action}'
     OR (prior.target_runtime#>>'{provider_schema_correction,source_operation_id}'=origin.operation_id
       AND prior.target_runtime#>'{provider_schema_correction,world_action}'=runtime#>'{planning_capacity,retained_world_action,world_action}'))))
 AND action.content#>>'{contract,project_id}'=source.project_id
 AND action.content#>>'{contract,book_id}'=source.command_payload#>>'{payload,book_id}'
 AND action.content#>>'{contract,actor_id}'=source.actor_id
 AND action.content#>'{contract,fact_mutation_allowed}'='false'::jsonb
 AND action.content#>>'{contract,world_plan,disposition}' IN ('ELIGIBLE','DEFER')
 AND (SELECT count(*) FROM authority_external_effect WHERE operation_id=origin.operation_id)=2
 AND (origin.operation_id=source_id OR NOT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=source_id))
 AND 2=(SELECT count(*) FROM (VALUES ('generation','world_candidates.generate'),('evaluation','world_candidates.evaluate')) stage(key,name)
   JOIN authority_asset_version output ON output.asset_version_id=action.content#>>ARRAY['contract',stage.key,'asset_version_id']
   JOIN authority_asset asset ON asset.asset_id=output.asset_id AND asset.project_id=source.project_id
   JOIN authority_external_effect effect ON effect.external_effect_id=output.content#>>'{contract,evidence,external_receipt_ref}'
     AND effect.operation_id=origin.operation_id AND effect.project_id=source.project_id
     AND effect.effect_type='model.invoke' AND effect.status='SUCCEEDED'
     AND effect.request_payload->>'stage'=stage.name
   JOIN authority_asset_version materialization ON materialization.asset_version_id=effect.request_payload#>>'{_production_execution,capability_runtime,materialization_asset_version_id}'
     AND materialization.content_hash=effect.request_payload#>>'{_production_execution,capability_runtime,materialization_content_hash}'
   JOIN authority_asset materialization_owner ON materialization_owner.asset_id=materialization.asset_id
     AND materialization_owner.project_id=source.project_id
   WHERE action.content#>ARRAY['contract',stage.key]=runtime#>ARRAY['planning_capacity','retained_world_action','world_action',stage.key]
     AND output.content_hash=action.content#>>ARRAY['contract',stage.key,'content_hash']
     AND output.content#>'{contract,source}'=action.content#>'{contract,source}'
     AND action.content#>'{contract,source}'=runtime#>'{planning_capacity,retained_world_action,world_action,source}'
     AND materialization.content#>>'{contract,tool_permissions,default}'='DENY'
     AND materialization.content#>'{contract,tool_permissions,allowed}'='["model.provider.invoke"]'::jsonb
     AND NOT authority_generation_isolated(effect.external_effect_id)
     AND EXISTS(SELECT 1 FROM authority_external_effect_dispatch dispatch
       JOIN authority_external_receipt receipt USING(dispatch_id)
       WHERE dispatch.external_effect_id=effect.external_effect_id AND dispatch.status='SUCCEEDED'
       AND receipt.status='VERIFIED' AND receipt.payload->'evidence'=dispatch.evidence
       AND receipt.payload#>'{evidence,result}'=output.content#>'{contract,output}'))
 AND NOT EXISTS(SELECT 1 FROM authority_budget_reservation budget WHERE budget.operation_id=source_id
   AND (budget.external_effect_id IS NULL OR NOT EXISTS(SELECT 1 FROM authority_external_effect effect
       WHERE effect.operation_id=source_id AND effect.external_effect_id=budget.external_effect_id)))
 AND NOT EXISTS(SELECT 1 FROM authority_lease_acquisition lease JOIN authority_attempt attempt USING(attempt_id)
   WHERE attempt.operation_id IN (source_id,origin.operation_id) AND lease.status='HELD')) $$"""

_NO_CALL = """AND NOT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=source.operation_id)
      AND NOT EXISTS(SELECT 1 FROM authority_budget_reservation WHERE operation_id=source.operation_id)"""
assert PREVIOUS[0].count(_NO_CALL) == 1
UPGRADE_STATEMENTS = [_WORLD, PREVIOUS[0].replace('r.chain_depth BETWEEN 1 AND 2', 'r.chain_depth>0').replace(
    "AND r.target_runtime #> '{planning_capacity,external_intents_at_source}'='0'::jsonb",
    """AND (r.target_runtime #> '{planning_capacity,external_intents_at_source}'='0'::jsonb OR authority_prepared_world_source_safe(source.operation_id,r.target_runtime))
      AND (r.target_runtime#>'{planning_capacity,retained_world_action}' IS NULL OR authority_prepared_world_source_safe(source.operation_id,r.target_runtime))""",
).replace(_NO_CALL, """AND ((NOT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=source.operation_id)
      AND NOT EXISTS(SELECT 1 FROM authority_budget_reservation WHERE operation_id=source.operation_id))
      OR authority_prepared_world_source_safe(source.operation_id,r.target_runtime))""").replace(
    "-'CONTEXT_CAPACITY_EXCEEDED'-'BUDGET_HARD_LIMIT'", "-'CONTEXT_CAPACITY_EXCEEDED'-'BUDGET_HARD_LIMIT'-'PROVIDER_MODEL_CAPACITY_UNAVAILABLE'")]
DOWNGRADE_STATEMENTS: list[str] = []
