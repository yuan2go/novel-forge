from __future__ import annotations

from .v20261019_0231_prepared_main_handoff import GUARD_STATEMENT as PREVIOUS_GUARD

MIGRATION_ID = '20261019_0232_first_isolated_preparation_custody'
DOWN_REVISION = '20261019_0231_prepared_main_handoff'
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = 'Append first-isolation preparation custody and stopped generic-successor bridging; retain original UNKNOWN, usage, receipts and submission-right revocation.'

MEMBER_STOPPED = """CREATE FUNCTION authority_first_preparation_member_stopped(identity TEXT, actor TEXT)
RETURNS BOOLEAN LANGUAGE SQL STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM authority_operation op WHERE op.operation_id=identity AND op.actor_id=actor
 AND NOT EXISTS(SELECT 1 FROM authority_lease_acquisition l JOIN authority_attempt a USING(attempt_id) WHERE a.operation_id=identity AND l.status='HELD')
 AND NOT EXISTS(SELECT 1 FROM authority_worker_cancel_signal WHERE operation_id=identity AND acknowledged_at IS NULL)
 AND EXISTS(SELECT 1 FROM authority_attempt WHERE operation_id=identity)
 AND (
  (op.status='FAILED_FINAL' AND EXISTS(SELECT 1 FROM authority_generation_isolation i WHERE i.operation_id=identity
    AND i.proof->>'contract_version'='pure-generation-isolation.v1' AND i.proof->>'business_commit_right'='REVOKED'
    AND i.proof->>'activation_right'='REVOKED' AND i.proof->>'actor_id'=actor)
   AND NOT EXISTS(SELECT 1 FROM authority_attempt WHERE operation_id=identity AND status<>'CANCELLED')
   AND NOT EXISTS(SELECT 1 FROM authority_cancellation_command WHERE operation_id=identity))
  OR (op.status='RECONCILIATION_REQUIRED'
   AND NOT EXISTS(SELECT 1 FROM authority_attempt WHERE operation_id=identity AND status<>'CANCELLED')
   AND EXISTS(SELECT 1 FROM authority_cancellation_command WHERE operation_id=identity AND actor_id=actor)
   AND NOT EXISTS(SELECT 1 FROM authority_cancellation_command WHERE operation_id=identity AND actor_id<>actor)
   AND EXISTS(SELECT 1 FROM authority_worker_cancel_signal WHERE operation_id=identity AND status='ACKNOWLEDGED' AND acknowledged_at IS NOT NULL))
  OR (op.status IN ('FAILED_FINAL','FAILED_RETRYABLE')
   AND NOT EXISTS(SELECT 1 FROM authority_attempt WHERE operation_id=identity AND status NOT IN ('FAILED_FINAL','FAILED_RETRYABLE'))
   AND NOT EXISTS(SELECT 1 FROM authority_cancellation_command WHERE operation_id=identity)
   AND NOT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=identity)
   AND NOT EXISTS(SELECT 1 FROM authority_budget_reservation WHERE operation_id=identity)
   AND EXISTS(SELECT 1 FROM authority_attempt a WHERE a.operation_id=identity
     AND a.attempt_number=(SELECT max(attempt_number) FROM authority_attempt WHERE operation_id=identity)
     AND ((a.result->>'error_code'='PROGRAMMING_BUG' AND a.result->>'error_message'='canceling statement due to statement timeout')
       OR (a.result->>'error_code'='PLANNING_ROUTING_LINEAGE_DEPTH_EXCEEDED' AND a.result->>'error_message'='PLANNING_ROUTING_LINEAGE_DEPTH_EXCEEDED: Planning repair routing lineage exceeds its bounded depth')))))
 AND NOT EXISTS(SELECT 1 FROM authority_external_effect e LEFT JOIN authority_budget_reservation b USING(external_effect_id)
  WHERE e.operation_id=identity AND NOT COALESCE(e.effect_type='model.invoke'
   AND e.request_payload->>'stage' IN ('context_compress','context_fidelity','world_candidates.generate','world_candidates.evaluate',
    'world_candidates.actor_0','world_candidates.actor_1','world_candidates.actor_2')
   AND ((e.status='SUCCEEDED' AND b.status='SETTLED' AND EXISTS(
      SELECT 1 FROM authority_external_effect_dispatch d JOIN authority_external_receipt receipt USING(dispatch_id)
      WHERE d.external_effect_id=e.external_effect_id AND d.status='SUCCEEDED' AND receipt.status='VERIFIED'))
    OR (authority_generation_isolated(e.external_effect_id) AND e.status IN ('UNKNOWN','RECONCILIATION_REQUIRED','FAILED_RETRYABLE'))
    OR (op.status='RECONCILIATION_REQUIRED' AND e.status='FAILED_RETRYABLE' AND b.status='RELEASED'
      AND e.request_payload->>'stage' IN ('context_compress','context_fidelity')
      AND e.last_error='{"message":"RUNTIME_DISPATCH_PAUSED: Planning preparation waits at the native Book pause checkpoint","error_code":"RUNTIME_DISPATCH_PAUSED","error_type":"KernelError","request_sent":false,"failure_phase":"pre_send_assertion","dispatch_pause_contract":"runtime-dispatch-control.v1","authorization_denial_permanent":false}'::jsonb
      AND (SELECT count(*) FROM authority_external_effect_dispatch WHERE external_effect_id=e.external_effect_id)=1
      AND EXISTS(SELECT 1 FROM authority_external_effect_dispatch d WHERE d.external_effect_id=e.external_effect_id
        AND d.status='FAILED_RETRYABLE' AND d.evidence=e.last_error
        AND NOT EXISTS(SELECT 1 FROM authority_external_receipt WHERE dispatch_id=d.dispatch_id)
        AND NOT EXISTS(SELECT 1 FROM authority_effect_dispatch_lease WHERE dispatch_id=d.dispatch_id AND status='HELD'))
      AND NOT EXISTS(SELECT 1 FROM authority_asset_version v JOIN authority_asset a USING(asset_id)
        WHERE a.project_id=e.project_id AND a.asset_type='execution_recovery_session'
        AND v.content#>>'{record,request,external_effect_id}'=e.external_effect_id))),false)))
$$"""

PERMITTED = """CREATE FUNCTION authority_first_isolated_preparation_permitted(runtime_id TEXT, child_id TEXT, generation JSONB)
RETURNS BOOLEAN LANGUAGE SQL STABLE AS $$
SELECT EXISTS(SELECT 1 FROM authority_story_planning_runtime_continuation r
 JOIN authority_operation registration ON registration.operation_id=r.registered_by_operation_id
 JOIN authority_operation source ON source.operation_id=r.source_operation_id
 JOIN authority_operation child ON child.operation_id=child_id
 JOIN authority_story_planning_generation prior ON prior.operation_id=source.operation_id
 JOIN authority_operation anchor ON anchor.operation_id=r.target_runtime#>>'{preparation_handoff,source_operation_id}'
 JOIN authority_attempt_capability_pack_snapshot snapshot ON snapshot.operation_id=anchor.operation_id
  AND snapshot.attempt_id=r.target_runtime#>>'{preparation_handoff,source_attempt_id}'
 JOIN authority_asset_version context ON context.asset_version_id=r.target_runtime#>>'{preparation_handoff,context_asset_version_id}'
  AND context.content_hash=r.target_runtime#>>'{preparation_handoff,context_content_hash}'
 JOIN authority_asset context_owner ON context_owner.asset_id=context.asset_id
 JOIN authority_book_production book ON book.book_run_id=r.source_command#>>'{arc_working_set,working_manuscript,book_run_id}'
 JOIN authority_story_formation_run formation ON formation.formation_run_id=r.decision_evidence->>'formation_run_id'
 WHERE r.continuation_id=runtime_id AND r.successor_operation_id=child_id
 AND registration.status='SUCCEEDED' AND registration.definition_name='story_planning.runtime_continuation.register'
 AND registration.definition_version='11.0.0' AND registration.actor_id=source.actor_id
 AND source.definition_name='story_planning.generate' AND source.definition_version='1.21.0'
 AND source.project_id=r.project_id AND source.workspace_id=r.workspace_id
 AND child.definition_name=source.definition_name AND child.definition_version=source.definition_version
 AND child.project_id=r.project_id AND child.workspace_id=r.workspace_id AND child.actor_id=source.actor_id
 AND child.causation_operation_id=source.operation_id
 AND child.definition_snapshot->>'commit_sha'=r.target_release_sha
 AND source.definition_snapshot->>'commit_sha'=r.source_release_sha
 AND r.chain_depth=COALESCE((SELECT chain_depth FROM authority_story_planning_runtime_continuation WHERE successor_operation_id=source.operation_id),0)+1
 AND r.source_command=source.command_payload->'payload' AND r.successor_command=child.command_payload->'payload'
 AND (r.successor_command-'runtime_continuation_id'-'idempotency_key')=(r.source_command-'runtime_continuation_id'-'idempotency_key')
 AND generation->>'book_id'=r.book_id AND prior.book_id=r.book_id
 AND generation->>'generator_operation_name'=prior.generator_operation_name
 AND prior.generator_operation_name IN ('chapter_plan.generate','chapter_group_plan.generate')
 AND generation->>'logical_key'=prior.logical_key AND generation->>'planning_scope'=prior.planning_scope
 AND generation->'input_snapshot'=prior.input_snapshot AND generation->>'input_snapshot_hash'=prior.input_snapshot_hash
 AND (generation->>'repair_number')::integer=prior.repair_number
 AND generation->>'repair_of_candidate_id' IS NOT DISTINCT FROM prior.repair_of_candidate_id
 AND generation->>'repair_reason' IS NOT DISTINCT FROM prior.repair_reason
 AND generation->>'narrative_search_id' IS NOT DISTINCT FROM prior.narrative_search_id
 AND generation->>'narrative_search_branch_key' IS NOT DISTINCT FROM prior.narrative_search_branch_key
 AND generation->>'candidate_asset_version_id' IS NULL AND prior.candidate_asset_version_id IS NULL
 AND r.target_runtime#>>'{preparation_handoff,contract_version}'='planning-first-isolated-preparation-handoff.v1'
 AND r.target_runtime#>>'{preparation_handoff,custody_source_operation_id}'=source.operation_id
 AND r.target_runtime->>'model_provider'=r.target_runtime#>>'{preparation_handoff,original_route,model_provider}'
 AND r.target_runtime->>'model_id'=r.target_runtime#>>'{preparation_handoff,original_route,model_id}'
 AND r.target_runtime->>'model_backend_id'=r.target_runtime#>>'{preparation_handoff,original_route,backend_id}'
 AND r.target_runtime->>'reasoning_effort'=r.target_runtime#>>'{preparation_handoff,original_route,reasoning_effort}'
 AND (NOT (r.target_runtime#>'{preparation_handoff,original_route}') ? 'auth_profile_ref'
  OR r.target_runtime->>'auth_profile_ref'=r.target_runtime#>>'{preparation_handoff,original_route,auth_profile_ref}')
 AND r.target_runtime#>'{preparation_handoff,main_dispatch_count}'='0'::jsonb
 AND r.target_runtime#>>'{preparation_handoff,source_submission_rights}'='REVOKED_OR_TERMINALLY_RELEASED'
 AND r.target_runtime#>'{preparation_handoff,original_pack_snapshot}'=snapshot.snapshot_payload
 AND r.target_runtime#>>'{preparation_handoff,original_pack_snapshot_id}'=snapshot.snapshot_id
 AND r.target_runtime#>>'{preparation_handoff,original_pack_snapshot_hash}'=snapshot.snapshot_hash
 AND r.target_runtime#>>'{preparation_handoff,preparation_source_boundary,pack_snapshot_hash}'=snapshot.snapshot_hash
 AND r.target_runtime#>'{preparation_handoff,preparation_source_boundary,sources}'=jsonb_build_array(jsonb_build_object('asset_version_id',context.asset_version_id,'content_hash',context.content_hash))
 AND r.target_runtime#>'{planning_capacity,allocated_task_tokens}'=r.target_runtime#>'{planning_capacity,prior_task_tokens}'
 AND r.target_runtime#>'{planning_capacity,allocated_task_tokens}'=(snapshot.snapshot_payload->>'context_policy_payload_json')::jsonb->'planning_task_token_budget'
 AND r.target_runtime#>>'{planning_capacity,context_revalidation,contract_version}'='same-capacity-isolated-preparation.v1'
 AND r.target_runtime#>>'{planning_capacity,context_revalidation,context_asset_version_id}'=context.asset_version_id
 AND r.target_runtime#>>'{planning_capacity,context_revalidation,context_content_hash}'=context.content_hash
 AND context_owner.project_id=r.project_id AND context_owner.asset_type='context_bundle'
 AND context.content->'arc_working_set'=r.source_command->'arc_working_set'
 AND book.project_id=r.project_id AND book.workspace_id=r.workspace_id AND book.book_id=r.book_id
 AND book.state IN ('READY','PAUSED') AND book.active_chapter_request_id IS NULL
 AND (r.source_command#>>'{arc_working_set,working_manuscript,target_chapter}')::integer=book.current_chapter+1
 AND (r.source_command#>>'{arc_working_set,working_manuscript,accepted_through_chapter}')::integer=book.accepted_through_chapter
 AND r.target_runtime#>>'{preparation_handoff,input_snapshot_id}'=book.input_snapshot_id
 AND formation.project_id=r.project_id AND formation.workspace_id=r.workspace_id AND formation.book_id=r.book_id
 AND formation.frozen_stage_inputs#>>'{generation_policy,auto_authorization,authorized_by_principal_id}'=registration.actor_id
 AND NOT EXISTS(SELECT 1 FROM authority_story_creation_cancellation WHERE formation_run_id=formation.formation_run_id)
 AND NOT EXISTS(SELECT 1 FROM authority_cancellation_command WHERE operation_id=book.root_operation_id)
 AND (WITH RECURSIVE ancestors AS (
   SELECT source.operation_id identity UNION
   SELECT p.source_operation_id FROM authority_story_planning_runtime_continuation p JOIN ancestors a ON p.successor_operation_id=a.identity
    WHERE p.project_id=r.project_id AND p.book_id=r.book_id)
  SELECT count(*)=jsonb_array_length(r.target_runtime#>'{preparation_handoff,stopped_ancestry}')
   AND bool_and(authority_first_preparation_member_stopped(a.identity,source.actor_id))
   AND bool_or(a.identity=anchor.operation_id)
   AND bool_and(((o.command_payload->'payload')-'runtime_continuation_id'-'idempotency_key')=(r.source_command-'runtime_continuation_id'-'idempotency_key'))
   AND bool_and(o.project_id=r.project_id AND o.workspace_id=r.workspace_id AND g.book_id=r.book_id AND g.candidate_asset_version_id IS NULL
     AND g.input_snapshot=prior.input_snapshot AND g.input_snapshot_hash=prior.input_snapshot_hash)
   AND bool_and(r.target_runtime#>'{preparation_handoff,stopped_ancestry}' @> jsonb_build_array(jsonb_build_object('operation_id',a.identity)))
  FROM ancestors a JOIN authority_operation o ON o.operation_id=a.identity JOIN authority_story_planning_generation g ON g.operation_id=a.identity)
 AND NOT EXISTS(SELECT 1 FROM authority_story_planning_runtime_continuation WHERE successor_operation_id=anchor.operation_id)
 AND EXISTS(SELECT 1 FROM authority_generation_isolation WHERE operation_id=anchor.operation_id)
 AND jsonb_array_length(r.target_runtime#>'{preparation_handoff,retained_preparation}')>0
 AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(r.target_runtime#>'{preparation_handoff,retained_preparation}') retained
   LEFT JOIN authority_external_effect e ON e.external_effect_id=retained->>'external_effect_id' AND e.operation_id=retained->>'operation_id'
   LEFT JOIN authority_budget_reservation b ON b.external_effect_id=e.external_effect_id
   WHERE NOT COALESCE(e.project_id=r.project_id AND e.status='SUCCEEDED' AND b.status='SETTLED'
    AND e.effect_type='model.invoke' AND e.request_hash=retained->>'request_hash'
    AND e.request_payload->>'stage'=retained->>'stage' AND e.request_payload->>'stage' IN ('context_compress','context_fidelity')
    AND e.request_payload#>'{input,context_compression_task,frozen_input_boundary}'=r.target_runtime#>'{preparation_handoff,preparation_source_boundary}'
    AND e.request_payload#>>'{input,context_compression_task,task,source_projection_hash}'=r.target_runtime#>>'{preparation_handoff,preparation_source_projection_hash}'
    AND r.target_runtime#>'{preparation_handoff,stopped_ancestry}' @> jsonb_build_array(jsonb_build_object('operation_id',e.operation_id)),false))
 AND EXISTS(SELECT 1 FROM authority_operation_output_asset output JOIN authority_asset_version receipt USING(asset_version_id)
   JOIN authority_asset asset ON asset.asset_id=receipt.asset_id WHERE output.operation_id=registration.operation_id
   AND output.role='primary' AND asset.project_id=r.project_id AND asset.asset_type='planning_runtime_continuation'
   AND output.content_hash=receipt.content_hash AND receipt.content->'target_runtime'=r.target_runtime
   AND receipt.content->>'source_operation_id'=source.operation_id)
) $$"""

_ANCHOR = 'AND NOT authority_prepared_main_handoff_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))'
assert PREVIOUS_GUARD.count(_ANCHOR) == 1
GUARD_STATEMENT = PREVIOUS_GUARD.replace(_ANCHOR, _ANCHOR + '\n               AND NOT authority_first_isolated_preparation_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))')
UPGRADE_STATEMENTS = [MEMBER_STOPPED, PERMITTED, GUARD_STATEMENT]
DOWNGRADE_STATEMENTS: list[str] = []
