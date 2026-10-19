from __future__ import annotations

from .v20261015_0220_chapter_prior_audit_convergence import GUARD_STATEMENT as PREVIOUS_GUARD

MIGRATION_ID = "20261018_0223_working_plan_input_continuation"
DOWN_REVISION = "20261016_0222_planning_host_frozen_definition"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Permit the exact zero-preparation current working Planning input-scope continuation; retain all original failures and prior recovery guards."

PERMITTED = """CREATE FUNCTION authority_working_plan_input_continuation_permitted(runtime_id TEXT, child_id TEXT, generation JSONB)
RETURNS BOOLEAN LANGUAGE SQL STABLE AS $$
SELECT EXISTS(SELECT 1 FROM authority_story_planning_runtime_continuation r
 JOIN authority_operation registration ON registration.operation_id=r.registered_by_operation_id
 JOIN authority_operation source ON source.operation_id=r.source_operation_id
 JOIN authority_operation child ON child.operation_id=child_id
 JOIN authority_story_planning_generation prior ON prior.operation_id=source.operation_id
 JOIN authority_attempt attempt ON attempt.operation_id=source.operation_id
 JOIN authority_book_production book ON book.book_run_id=r.source_command#>>'{arc_working_set,working_manuscript,book_run_id}'
 JOIN authority_story_formation_run formation ON formation.formation_run_id=r.decision_evidence->>'formation_run_id'
 JOIN authority_asset_version change ON change.asset_version_id=r.source_command#>>'{change_evidence_version_ids,0}'
 JOIN authority_asset change_asset ON change_asset.asset_id=change.asset_id
 JOIN authority_operation_output_asset change_output ON change_output.asset_version_id=change.asset_version_id AND change_output.role='primary'
 JOIN authority_operation author ON author.operation_id=change_output.operation_id
 JOIN active_story_plan_version active ON active.project_id=r.project_id AND active.book_id=r.book_id
 JOIN story_plan_binding binding ON binding.binding_id=active.binding_id AND binding.asset_version_id=change.content->>'target_plan_version_id'
 JOIN authority_asset_version plan ON plan.asset_version_id=binding.asset_version_id
 JOIN authority_story_planning_candidate candidate ON candidate.candidate_asset_version_id=plan.asset_version_id
 JOIN authority_story_planning_generation reference ON reference.generation_id=candidate.generation_id
 JOIN authority_operation reference_operation ON reference_operation.operation_id=reference.operation_id
 JOIN authority_external_effect effect ON effect.operation_id=reference.operation_id
   AND effect.external_effect_id=r.decision_evidence#>>'{reference_route,external_effect_id}'
 JOIN authority_attempt_capability_pack_snapshot pack ON pack.operation_id=reference.operation_id
   AND pack.snapshot_id=r.decision_evidence#>>'{source_input_scope_failure,reference_pack_snapshot_id}'
   AND pack.snapshot_hash=r.decision_evidence#>>'{source_input_scope_failure,reference_pack_snapshot_hash}'
 WHERE r.continuation_id=runtime_id AND r.successor_operation_id=child_id AND r.chain_depth=1
 AND registration.status='SUCCEEDED' AND registration.definition_name='story_planning.runtime_continuation.register'
 AND registration.definition_version='1.0.0' AND registration.project_id=r.project_id AND registration.workspace_id=r.workspace_id
 AND source.status='FAILED_FINAL' AND source.definition_name='story_planning.generate' AND source.definition_version='1.21.0'
 AND source.project_id=r.project_id AND source.workspace_id=r.workspace_id
 AND source.definition_snapshot->>'commit_sha'=r.source_release_sha AND r.source_release_sha<>r.target_release_sha
 AND child.definition_name=source.definition_name AND child.definition_version=source.definition_version
 AND child.definition_snapshot->>'commit_sha'=r.target_release_sha
 AND child.project_id=r.project_id AND child.workspace_id=r.workspace_id AND child.actor_id=source.actor_id
 AND child.causation_operation_id=source.operation_id
 AND attempt.status='FAILED_FINAL' AND (SELECT count(*) FROM authority_attempt WHERE operation_id=source.operation_id)=1
 AND attempt.result->>'error_code'='MANUSCRIPT_CONTEXT_INVALID'
 AND attempt.result->>'error_message'='MANUSCRIPT_CONTEXT_INVALID: Only the selected preceding writing history can be read'
 AND r.decision_evidence->>'recovery_kind'='planning-unsent-working-input-scope.v1'
 AND r.decision_evidence#>>'{source_input_scope_failure,contract_version}'='planning-unsent-working-input-scope.v1'
 AND r.decision_evidence#>>'{source_input_scope_failure,source_operation_id}'=source.operation_id
 AND r.decision_evidence#>>'{source_input_scope_failure,source_attempt_id}'=attempt.attempt_id
 AND r.decision_evidence#>'{source_input_scope_failure,source_failure}'=attempt.result
 AND r.decision_evidence#>'{source_input_scope_failure,source_pack_snapshot}'='null'::jsonb
 AND r.decision_evidence#>>'{source_input_scope_failure,source_provider_dispatch_count}'='0'
 AND r.decision_evidence->>'route_reference_scope'='TARGET_PLAN_COMPLETED_CALL_NOT_FAILED_SOURCE'
 AND r.source_command=source.command_payload->'payload' AND r.successor_command=child.command_payload->'payload'
 AND (r.successor_command-'runtime_continuation_id'-'idempotency_key')=(r.source_command-'runtime_continuation_id'-'idempotency_key')
 AND r.source_command->>'execution_contract_version'='1.21.0'
 AND COALESCE(r.source_command->>'runtime_continuation_id','')='' AND prior.repair_number=0
 AND jsonb_array_length(r.source_command->'change_evidence_version_ids')=1
 AND change_asset.asset_type='replan_request' AND change_asset.project_id=r.project_id
 AND change.lifecycle='ACTIVE' AND change.eligibility='ELIGIBLE' AND change.governance='CLEAR'
 AND change.content->>'contract_version'='operator-planning-change-request.v1'
 AND change.content->>'authority_boundary'='FUTURE_PLAN_PROPOSAL_ONLY'
 AND change.content->>'book_id'=r.book_id AND change.content->>'accepted_through_chapter'=book.accepted_through_chapter::text
 AND author.definition_name='planning.change_request.author' AND author.status='SUCCEEDED'
 AND author.actor_id=source.actor_id AND author.project_id=r.project_id AND author.workspace_id=r.workspace_id
 AND EXISTS(SELECT 1 FROM jsonb_array_elements(source.input_asset_snapshot) input
   WHERE input->>'asset_version_id'=change.asset_version_id AND input->>'content_hash'=change.content_hash)
 AND binding.freshness='CURRENT' AND binding.execution_scope IN ('PLANNED','FROZEN')
 AND binding.logical_key=prior.logical_key AND binding.contract_type=prior.planning_scope
 AND change.content->>'affected_scope'=binding.contract_type
 AND book.project_id=r.project_id AND book.workspace_id=r.workspace_id AND book.book_id=r.book_id
 AND book.state IN ('READY','PAUSED') AND book.active_chapter_request_id IS NULL
 AND book.current_chapter>book.accepted_through_chapter
 AND r.source_command#>>'{arc_working_set,working_manuscript,target_chapter}'=book.current_chapter::text
 AND ((binding.contract_type='CHAPTER_GROUP' AND prior.generator_operation_name='chapter_group_plan.generate'
     AND book.current_chapter BETWEEN (plan.content->'chapter_range'->>0)::integer AND (plan.content->'chapter_range'->>1)::integer)
   OR (binding.contract_type='CHAPTER' AND prior.generator_operation_name='chapter_plan.generate'
     AND (plan.content->>'chapter_number')::integer=book.current_chapter))
 AND formation.project_id=r.project_id AND formation.workspace_id=r.workspace_id AND formation.book_id=r.book_id
 AND formation.frozen_stage_inputs#>>'{generation_policy,auto_authorization,authorized_by_principal_id}'=registration.actor_id
 AND NOT EXISTS(SELECT 1 FROM authority_story_creation_cancellation WHERE formation_run_id=formation.formation_run_id)
 AND reference_operation.status='SUCCEEDED' AND reference_operation.actor_id=source.actor_id
 AND reference.project_id=r.project_id AND reference.workspace_id=r.workspace_id AND reference.book_id=r.book_id
 AND reference.generator_operation_name=prior.generator_operation_name
 AND r.decision_evidence#>>'{source_input_scope_failure,reference_operation_id}'=reference.operation_id
 AND effect.status='SUCCEEDED' AND effect.request_hash=r.decision_evidence#>>'{reference_route,request_hash}'
 AND effect.request_payload->>'stage'=prior.generator_operation_name
 AND effect.provider='production_execution_gateway' AND effect.model_id=r.target_runtime->>'model_id'
 AND effect.request_payload#>>'{_production_execution,capability_runtime,routing_decision,selected,candidate,provider}'=r.target_runtime->>'model_provider'
 AND effect.request_payload#>>'{_production_execution,capability_runtime,routing_decision,selected,candidate,model}'=r.target_runtime->>'model_id'
 AND effect.request_payload#>>'{_production_execution,capability_runtime,snapshot_id}'=pack.snapshot_id
 AND effect.request_payload#>>'{_production_execution,capability_runtime,snapshot_hash}'=pack.snapshot_hash
 AND EXISTS(SELECT 1 FROM authority_budget_reservation reservation WHERE reservation.external_effect_id=effect.external_effect_id AND reservation.status='SETTLED')
 AND EXISTS(SELECT 1 FROM authority_external_effect_dispatch dispatch JOIN authority_external_receipt receipt USING(dispatch_id)
   WHERE dispatch.external_effect_id=effect.external_effect_id AND dispatch.status='SUCCEEDED' AND receipt.status='VERIFIED')
 AND NOT EXISTS(SELECT 1 FROM (VALUES ('manifest_hash'),('prompt_bundle_hash'),('route_policy_hash'),('context_policy_hash'),('skill_bundle_hash'),('tool_policy_hash')) identity(key)
   WHERE pack.snapshot_payload->identity.key IS DISTINCT FROM r.target_runtime->'pack_snapshot'->identity.key)
 AND r.target_runtime#>>'{pack_snapshot,release_sha}'=r.target_release_sha
 AND NOT r.decision_evidence ? 'pack_version_successor' AND NOT r.decision_evidence ? 'capacity_policy_upgrade'
 AND prior.project_id=r.project_id AND prior.workspace_id=r.workspace_id AND prior.book_id=r.book_id
 AND generation->>'project_id'=r.project_id AND generation->>'workspace_id'=r.workspace_id AND generation->>'book_id'=r.book_id
 AND generation->>'generator_operation_name'=prior.generator_operation_name AND generation->>'logical_key'=prior.logical_key
 AND generation->>'planning_scope'=prior.planning_scope AND generation->'input_snapshot'=prior.input_snapshot
 AND generation->>'input_snapshot_hash'=prior.input_snapshot_hash AND generation->>'repair_number'='0'
 AND generation->>'repair_of_candidate_id' IS NOT DISTINCT FROM prior.repair_of_candidate_id
 AND generation->>'repair_of_operation_id' IS NOT DISTINCT FROM prior.repair_of_operation_id
 AND generation->>'repair_result_asset_version_id' IS NOT DISTINCT FROM prior.repair_result_asset_version_id
 AND generation->>'candidate_asset_version_id' IS NULL AND prior.candidate_asset_version_id IS NULL
 AND NOT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=source.operation_id)
 AND NOT EXISTS(SELECT 1 FROM authority_budget_reservation WHERE operation_id=source.operation_id)
 AND NOT EXISTS(SELECT 1 FROM authority_operation_output_asset WHERE operation_id=source.operation_id)
 AND NOT EXISTS(SELECT 1 FROM authority_attempt_capability_pack_snapshot WHERE operation_id=source.operation_id)
 AND NOT EXISTS(SELECT 1 FROM authority_lease_acquisition lease JOIN authority_attempt a USING(attempt_id) WHERE a.operation_id=source.operation_id AND lease.status='HELD')
 AND NOT EXISTS(SELECT 1 FROM authority_cancellation_command WHERE operation_id=source.operation_id)
 AND NOT EXISTS(SELECT 1 FROM authority_worker_cancel_signal WHERE operation_id=source.operation_id AND acknowledged_at IS NULL)
 AND EXISTS(SELECT 1 FROM authority_operation_output_asset output JOIN authority_asset_version receipt USING(asset_version_id)
   JOIN authority_asset asset ON asset.asset_id=receipt.asset_id WHERE output.operation_id=registration.operation_id
     AND output.role='primary' AND asset.asset_type='planning_runtime_continuation'
     AND receipt.content->>'source_operation_id'=source.operation_id AND receipt.content->'decision_evidence'=r.decision_evidence)
) $$"""

_ANCHOR = "AND NOT authority_chapter_prior_audit_continuation_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))"
assert PREVIOUS_GUARD.count(_ANCHOR) == 1
GUARD_STATEMENT = PREVIOUS_GUARD.replace(_ANCHOR, _ANCHOR + "\n               AND NOT authority_working_plan_input_continuation_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))")
UPGRADE_STATEMENTS = [PERMITTED, GUARD_STATEMENT]
DOWNGRADE_STATEMENTS: list[str] = []
