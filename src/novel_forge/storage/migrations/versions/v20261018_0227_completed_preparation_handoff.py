from __future__ import annotations

from .v20261018_0226_semantic_preparation_continuation import GUARD_STATEMENT as PREVIOUS_GUARD

MIGRATION_ID = "20261018_0227_completed_preparation_handoff"
DOWN_REVISION = "20261018_0226_semantic_preparation_continuation"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Append exact cancelled preparation handoff without relabeling completed sends, altering source history or increasing capacity."

PERMITTED = """CREATE FUNCTION authority_completed_preparation_handoff_permitted(runtime_id TEXT, child_id TEXT, generation JSONB)
RETURNS BOOLEAN LANGUAGE SQL STABLE AS $$
SELECT EXISTS(SELECT 1 FROM authority_story_planning_runtime_continuation link
 JOIN authority_operation registration ON registration.operation_id=link.registered_by_operation_id
 JOIN authority_operation source ON source.operation_id=link.source_operation_id
 JOIN authority_operation child ON child.operation_id=child_id
 JOIN authority_story_planning_generation original ON original.operation_id=source.operation_id
 JOIN authority_story_planning_runtime_continuation parent
   ON parent.successor_operation_id=source.operation_id AND parent.continuation_id=source.command_payload#>>'{payload,runtime_continuation_id}'
 JOIN authority_attempt attempt ON attempt.operation_id=source.operation_id
 JOIN authority_attempt_capability_pack_snapshot snapshot ON snapshot.attempt_id=attempt.attempt_id AND snapshot.operation_id=source.operation_id
 JOIN authority_book_production book ON book.book_run_id=link.source_command#>>'{arc_working_set,working_manuscript,book_run_id}'
 JOIN authority_story_formation_run formation ON formation.formation_run_id=link.decision_evidence->>'formation_run_id'
 JOIN authority_operation_output_asset output ON output.operation_id=source.operation_id AND output.output_key='planning.context_bundle'
 JOIN authority_asset_version context ON context.asset_version_id=output.asset_version_id AND context.content_hash=output.content_hash
 JOIN authority_asset context_owner ON context_owner.asset_id=context.asset_id
 WHERE link.continuation_id=runtime_id AND link.successor_operation_id=child_id AND link.chain_depth=parent.chain_depth+1
 AND registration.status='SUCCEEDED' AND registration.definition_name='story_planning.runtime_continuation.register' AND registration.definition_version='5.0.0'
 AND source.status='RECONCILIATION_REQUIRED' AND source.definition_name='story_planning.generate' AND source.definition_version='1.21.0'
 AND source.project_id=link.project_id AND source.workspace_id=link.workspace_id AND source.actor_id=registration.actor_id
 AND child.definition_name=source.definition_name AND child.definition_version=source.definition_version
 AND child.project_id=source.project_id AND child.workspace_id=source.workspace_id AND child.actor_id=source.actor_id
 AND child.causation_operation_id=source.operation_id
 AND source.definition_snapshot->>'commit_sha'=link.source_release_sha
 AND child.definition_snapshot->>'commit_sha'=link.target_release_sha AND link.source_release_sha<>link.target_release_sha
 AND attempt.attempt_number=(SELECT max(attempt_number) FROM authority_attempt WHERE operation_id=source.operation_id)
 AND attempt.status='CANCELLED' AND link.target_runtime#>>'{preparation_handoff,source_attempt_id}'=attempt.attempt_id
 AND link.target_runtime#>>'{preparation_handoff,contract_version}'='planning-completed-preparation-handoff.v1'
 AND link.target_runtime#>>'{preparation_handoff,source_operation_id}'=source.operation_id
 AND link.target_runtime#>>'{preparation_handoff,source_submission_rights}'='REVOKED_BY_ACKNOWLEDGED_CANCELLATION'
 AND link.target_runtime#>'{preparation_handoff,main_dispatch_count}'='0'::jsonb
 AND parent.successor_command=link.source_command AND parent.project_id=link.project_id AND parent.book_id=link.book_id AND parent.workspace_id=link.workspace_id
 AND link.source_command=source.command_payload->'payload' AND link.successor_command=child.command_payload->'payload'
 AND (link.successor_command-'runtime_continuation_id'-'idempotency_key')=(link.source_command-'runtime_continuation_id'-'idempotency_key')
 AND generation->>'book_id'=original.book_id AND original.book_id=link.book_id
 AND generation->>'generator_operation_name'=original.generator_operation_name AND original.generator_operation_name IN ('chapter_plan.generate','chapter_group_plan.generate')
 AND generation->>'logical_key'=original.logical_key AND generation->>'planning_scope'=original.planning_scope
 AND generation->'input_snapshot'=original.input_snapshot AND generation->>'input_snapshot_hash'=original.input_snapshot_hash
 AND (generation->>'repair_number')::integer=original.repair_number
 AND generation->>'repair_of_candidate_id' IS NOT DISTINCT FROM original.repair_of_candidate_id
 AND generation->>'repair_reason' IS NOT DISTINCT FROM original.repair_reason
 AND generation->>'narrative_search_id' IS NOT DISTINCT FROM original.narrative_search_id
 AND generation->>'narrative_search_branch_key' IS NOT DISTINCT FROM original.narrative_search_branch_key
 AND generation->>'candidate_asset_version_id' IS NULL AND original.candidate_asset_version_id IS NULL
 AND link.target_runtime#>'{planning_capacity,allocated_task_tokens}'=parent.target_runtime#>'{planning_capacity,allocated_task_tokens}'
 AND link.target_runtime#>'{planning_capacity,prior_task_tokens}'=parent.target_runtime#>'{planning_capacity,allocated_task_tokens}'
 AND link.target_runtime#>'{planning_capacity,single_request_ceiling}'=parent.target_runtime#>'{planning_capacity,single_request_ceiling}'
 AND link.target_runtime#>'{planning_capacity,source_failure}'=parent.target_runtime#>'{planning_capacity,source_failure}'
 AND link.target_runtime#>>'{planning_capacity,context_revalidation,contract_version}'='same-capacity-semantic-preparation.v1'
 AND link.target_runtime#>>'{planning_capacity,context_revalidation,context_asset_version_id}'=context.asset_version_id
 AND link.target_runtime#>>'{planning_capacity,context_revalidation,context_content_hash}'=context.content_hash
 AND link.target_runtime#>>'{preparation_handoff,context_asset_version_id}'=context.asset_version_id
 AND link.target_runtime#>>'{preparation_handoff,context_content_hash}'=context.content_hash
 AND link.target_runtime#>>'{preparation_handoff,preparation_source_boundary,kind}'='FROZEN_STAGE_INPUTS'
 AND link.target_runtime#>>'{preparation_handoff,preparation_source_boundary,project_id}'=link.project_id
 AND link.target_runtime#>>'{preparation_handoff,preparation_source_boundary,book_id}'=link.book_id
 AND link.target_runtime#>>'{preparation_handoff,preparation_source_boundary,pack_snapshot_hash}'=snapshot.snapshot_hash
 AND link.target_runtime#>'{preparation_handoff,preparation_source_boundary,sources}'=jsonb_build_array(jsonb_build_object('asset_version_id',context.asset_version_id,'content_hash',context.content_hash))
 AND COALESCE(link.target_runtime#>>'{preparation_handoff,preparation_source_projection_hash}','')<>''
 AND snapshot.snapshot_payload->>'context_policy_ref'='context-policy:chapter-generation-pack:v4'
 AND context_owner.project_id=link.project_id AND context_owner.asset_type='context_bundle'
 AND context.content->>'project_id'=link.project_id AND context.content->>'workspace_id'=link.workspace_id AND context.content->>'book_id'=link.book_id
 AND context.content->'arc_working_set'=link.source_command->'arc_working_set'
 AND book.project_id=link.project_id AND book.workspace_id=link.workspace_id AND book.book_id=link.book_id AND book.state IN ('READY','PAUSED') AND book.active_chapter_request_id IS NULL
 AND (link.source_command#>>'{arc_working_set,working_manuscript,target_chapter}')::integer=book.current_chapter+1
 AND (link.source_command#>>'{arc_working_set,working_manuscript,accepted_through_chapter}')::integer=book.accepted_through_chapter
 AND link.target_runtime#>>'{preparation_handoff,input_snapshot_id}'=book.input_snapshot_id
 AND formation.project_id=link.project_id AND formation.workspace_id=link.workspace_id AND formation.book_id=link.book_id
 AND formation.frozen_stage_inputs#>>'{generation_policy,auto_authorization,authorized_by_principal_id}'=registration.actor_id
 AND NOT EXISTS(SELECT 1 FROM authority_story_creation_cancellation WHERE formation_run_id=formation.formation_run_id)
 AND NOT EXISTS(SELECT 1 FROM authority_cancellation_command WHERE operation_id=book.root_operation_id)
 AND NOT EXISTS(SELECT 1 FROM authority_attempt WHERE operation_id=source.operation_id AND status<>'CANCELLED')
 AND NOT EXISTS(SELECT 1 FROM authority_lease_acquisition lease JOIN authority_attempt a USING(attempt_id) WHERE a.operation_id=source.operation_id AND lease.status='HELD')
 AND EXISTS(SELECT 1 FROM authority_worker_cancel_signal WHERE operation_id=source.operation_id AND attempt_id=attempt.attempt_id AND status='ACKNOWLEDGED' AND acknowledged_at IS NOT NULL)
 AND NOT EXISTS(SELECT 1 FROM authority_worker_cancel_signal WHERE operation_id=source.operation_id AND acknowledged_at IS NULL)
 AND EXISTS(SELECT 1 FROM authority_cancellation_command WHERE operation_id=source.operation_id)
 AND NOT EXISTS(SELECT 1 FROM authority_cancellation_command WHERE operation_id=source.operation_id AND actor_id<>registration.actor_id)
 AND (SELECT count(*) FROM authority_external_effect WHERE operation_id=source.operation_id)>0
 AND (SELECT count(*) FROM authority_external_effect WHERE operation_id=source.operation_id)=jsonb_array_length(link.target_runtime#>'{preparation_handoff,retained_preparation}')
 AND (link.target_runtime#>>'{planning_capacity,external_intents_at_source}')::integer=jsonb_array_length(link.target_runtime#>'{preparation_handoff,retained_preparation}')
 AND NOT EXISTS(SELECT 1 FROM authority_external_effect effect LEFT JOIN authority_budget_reservation reservation USING(external_effect_id)
   WHERE effect.operation_id=source.operation_id AND (effect.status IS DISTINCT FROM 'SUCCEEDED' OR effect.effect_type IS DISTINCT FROM 'model.invoke'
     OR COALESCE(effect.request_payload->>'stage','') NOT IN ('context_compress','context_fidelity') OR reservation.status IS DISTINCT FROM 'SETTLED'
     OR jsonb_typeof(effect.request_payload#>'{input,context_compression_task}') IS DISTINCT FROM 'object'
     OR effect.request_payload#>'{input,context_compression_task,frozen_input_boundary}' IS DISTINCT FROM link.target_runtime#>'{preparation_handoff,preparation_source_boundary}'
     OR effect.request_payload#>>'{input,context_compression_task,task,source_projection_hash}' IS DISTINCT FROM link.target_runtime#>>'{preparation_handoff,preparation_source_projection_hash}'
     OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(link.target_runtime#>'{preparation_handoff,retained_preparation}') proof
       WHERE proof->>'external_effect_id'=effect.external_effect_id AND proof->>'request_hash'=effect.request_hash AND proof->>'stage'=effect.request_payload->>'stage')))
 AND NOT EXISTS(SELECT 1 FROM authority_budget_reservation WHERE operation_id=source.operation_id AND (external_effect_id IS NULL OR status<>'SETTLED'))
 AND EXISTS(SELECT 1 FROM authority_operation_output_asset receipt_output JOIN authority_asset_version receipt USING(asset_version_id)
   JOIN authority_asset asset ON asset.asset_id=receipt.asset_id WHERE receipt_output.operation_id=registration.operation_id
   AND receipt_output.role='primary' AND asset.asset_type='planning_runtime_continuation' AND asset.project_id=link.project_id
   AND receipt.content->>'source_operation_id'=source.operation_id AND receipt.content->'target_runtime'=link.target_runtime)
) $$"""

_ANCHOR = "AND NOT authority_semantic_preparation_continuation_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))"
assert PREVIOUS_GUARD.count(_ANCHOR) == 1
GUARD_STATEMENT = PREVIOUS_GUARD.replace(_ANCHOR, _ANCHOR + "\n               AND NOT authority_completed_preparation_handoff_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))")
UPGRADE_STATEMENTS = [PERMITTED, GUARD_STATEMENT]
DOWNGRADE_STATEMENTS: list[str] = []
