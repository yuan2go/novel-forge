from __future__ import annotations

MIGRATION_ID = "20261009_0186_generation_capacity_inheritance"
DOWN_REVISION = "20261009_0185_pure_generation_isolation"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Retain prior task capacity through the native isolated generation successor without changing original history."

UPGRADE_STATEMENTS = [
    """CREATE OR REPLACE FUNCTION authority_generation_continuation_permitted(runtime_id TEXT, child_id TEXT, generation JSONB)
 RETURNS BOOLEAN LANGUAGE SQL STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM authority_story_planning_runtime_continuation r
 JOIN authority_operation registered ON registered.operation_id=r.registered_by_operation_id
 JOIN authority_operation source ON source.operation_id=r.source_operation_id
 JOIN authority_operation child ON child.operation_id=child_id
 JOIN authority_story_planning_generation prior ON prior.operation_id=source.operation_id
 JOIN authority_generation_isolation i ON i.operation_id=source.operation_id OR (
   r.decision_evidence->>'capacity_inheritance'='generation-capacity-inheritance.v1'
   AND NOT EXISTS(SELECT 1 FROM authority_external_effect e WHERE e.operation_id=source.operation_id)
   AND NOT EXISTS(SELECT 1 FROM authority_budget_reservation b WHERE b.operation_id=source.operation_id)
   AND EXISTS(SELECT 1 FROM authority_story_planning_runtime_continuation link
      JOIN authority_operation original ON original.operation_id=link.source_operation_id
      JOIN authority_story_planning_runtime_continuation capacity ON capacity.continuation_id=original.command_payload#>>'{payload,runtime_continuation_id}'
      WHERE link.source_operation_id=i.operation_id AND link.successor_operation_id=source.operation_id
      AND link.target_runtime#>>'{generation_isolation,external_effect_id}'=i.external_effect_id
      AND r.chain_depth=link.chain_depth+1 AND r.chain_depth<=3
      AND source.status='FAILED_FINAL'
      AND r.target_runtime#>>'{planning_capacity,allocated_task_tokens}'=capacity.target_runtime#>>'{planning_capacity,allocated_task_tokens}'
      AND r.target_runtime#>'{planning_capacity,allocated_task_tokens}' IS NOT NULL))
 WHERE r.continuation_id=runtime_id AND r.successor_operation_id=child_id
 AND registered.status='SUCCEEDED' AND registered.definition_name='story_planning.runtime_continuation.register'
 AND authority_generation_isolated(i.external_effect_id)
 AND r.source_command=source.command_payload->'payload' AND r.successor_command=child.command_payload->'payload'
 AND (r.successor_command-'runtime_continuation_id'-'idempotency_key'-'opening_execution_binding')=(r.source_command-'runtime_continuation_id'-'idempotency_key'-'opening_execution_binding')
 AND child.causation_operation_id=source.operation_id AND child.project_id=i.project_id AND child.workspace_id=i.workspace_id
 AND child.actor_id=source.actor_id AND r.book_id=i.book_id AND generation->>'book_id'=i.book_id
 AND generation->>'generator_operation_name'=prior.generator_operation_name
 AND generation->>'logical_key'=prior.logical_key AND generation->>'planning_scope'=prior.planning_scope
 AND generation->'input_snapshot'=prior.input_snapshot AND generation->>'input_snapshot_hash'=prior.input_snapshot_hash
 AND (generation->>'repair_number')::int=prior.repair_number
 AND generation->>'narrative_search_id' IS NOT DISTINCT FROM prior.narrative_search_id
 AND generation->>'narrative_search_branch_key' IS NOT DISTINCT FROM prior.narrative_search_branch_key
 AND generation->>'candidate_asset_version_id' IS NULL
 AND r.target_runtime#>>'{generation_isolation,external_effect_id}'=i.external_effect_id
 AND (r.decision_evidence->>'authorization_ref'=i.proof->>'authorization_ref' OR r.decision_evidence->>'capacity_inheritance'='generation-capacity-inheritance.v1')) $$""",
    """ALTER TABLE authority_story_planning_runtime_continuation DROP CONSTRAINT authority_story_planning_runtime_continuation_chain_depth_check""",
    """ALTER TABLE authority_story_planning_runtime_continuation ADD CONSTRAINT authority_story_planning_runtime_continuation_chain_depth_check CHECK ((((chain_depth >= 1) AND (chain_depth <= 2)) OR ((chain_depth = 3) AND ((COALESCE((decision_evidence ->> 'projection_revalidation'::text), ''::text) = 'world-direction-projection.v1'::text) OR (((decision_evidence ->> 'changed_contract'::text) = 'planning-host-source-selectors.v2'::text) AND ((target_runtime #>> '{planning_reference_contract,contract_version}'::text[]) = 'planning-reference-contract-successor.v2'::text)))) OR ((chain_depth = 4) AND ((decision_evidence ->> 'planning_host_revalidation'::text) = 'planning-arc-scope-revalidation.v2'::text) AND ((decision_evidence -> 'provider_dispatch_authorized'::text) = 'false'::jsonb) AND ((target_runtime #>> '{planning_host_revalidation,contract_version}'::text[]) = 'planning-arc-scope-revalidation.v2'::text))) OR (chain_depth=3 AND decision_evidence->>'capacity_inheritance'='generation-capacity-inheritance.v1' AND target_runtime#>>'{generation_isolation,contract_version}'='pure-generation-isolation.v1'))""",
]

DOWNGRADE_STATEMENTS: list[str] = []
