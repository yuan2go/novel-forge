from __future__ import annotations

from .v20261018_0223_working_plan_input_continuation import GUARD_STATEMENT as PREVIOUS_GUARD

MIGRATION_ID = "20261018_0226_semantic_preparation_continuation"
DOWN_REVISION = "20261018_0225_impacted_working_plan_continuation"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Append exact same-capacity semantic preparation successors; retain original failures, frozen inputs, cancellation and zero-send guards."

PERMITTED = """CREATE FUNCTION authority_semantic_preparation_continuation_permitted(runtime_id TEXT, child_id TEXT, generation JSONB)
RETURNS BOOLEAN LANGUAGE SQL STABLE AS $$
SELECT EXISTS(SELECT 1 FROM authority_story_planning_runtime_continuation r
 JOIN authority_operation registration ON registration.operation_id=r.registered_by_operation_id
 JOIN authority_operation source ON source.operation_id=r.source_operation_id
 JOIN authority_operation child ON child.operation_id=child_id
 JOIN authority_story_planning_generation prior ON prior.operation_id=source.operation_id
 JOIN authority_attempt attempt ON attempt.operation_id=source.operation_id
 JOIN authority_attempt_capability_pack_snapshot snapshot ON snapshot.attempt_id=attempt.attempt_id AND snapshot.operation_id=source.operation_id
 JOIN authority_operation_output_asset output ON output.operation_id=source.operation_id AND output.output_key='planning.context_bundle'
 JOIN authority_asset_version context ON context.asset_version_id=output.asset_version_id AND context.content_hash=output.content_hash
 JOIN authority_asset context_owner ON context_owner.asset_id=context.asset_id
 JOIN authority_book_production book ON book.book_run_id=r.source_command#>>'{arc_working_set,working_manuscript,book_run_id}'
 JOIN authority_story_formation_run formation ON formation.formation_run_id=r.decision_evidence->>'formation_run_id'
 WHERE r.continuation_id=runtime_id AND r.successor_operation_id=child_id AND r.chain_depth>0
 AND registration.status='SUCCEEDED' AND registration.definition_name='story_planning.runtime_continuation.register'
 AND source.status='FAILED_FINAL' AND source.definition_name='story_planning.generate' AND source.definition_version='1.21.0'
 AND source.project_id=r.project_id AND source.workspace_id=r.workspace_id
 AND child.definition_name=source.definition_name AND child.definition_version=source.definition_version
 AND child.project_id=r.project_id AND child.workspace_id=r.workspace_id AND child.actor_id=source.actor_id
 AND child.causation_operation_id=source.operation_id
 AND source.definition_snapshot->>'commit_sha'=r.source_release_sha
 AND child.definition_snapshot->>'commit_sha'=r.target_release_sha AND r.source_release_sha<>r.target_release_sha
 AND attempt.attempt_number=(SELECT max(attempt_number) FROM authority_attempt WHERE operation_id=source.operation_id)
 AND attempt.status='FAILED_RETRYABLE' AND attempt.result->>'error_code'='PROVIDER_CONTEXT_CAPACITY_UNCERTAIN'
 AND attempt.result->>'error_message'='PROVIDER_CONTEXT_CAPACITY_UNCERTAIN: a byte upper bound exceeds capacity; configure a matched tokenizer before lossy compression'
 AND attempt.result->>'failure_class'='retryable' AND attempt.result#>'{failure_details,actual_tokens}'='null'::jsonb
 AND (attempt.result#>>'{failure_details,upper_bound}')::integer>(attempt.result#>>'{failure_details,limit}')::integer
 AND (attempt.result#>>'{failure_details,limit}')::integer>0
 AND r.source_command=source.command_payload->'payload' AND r.successor_command=child.command_payload->'payload'
 AND (r.successor_command-'runtime_continuation_id'-'idempotency_key')=(r.source_command-'runtime_continuation_id'-'idempotency_key')
 AND generation->>'book_id'=r.book_id AND generation->>'generator_operation_name'=prior.generator_operation_name
 AND prior.generator_operation_name IN ('chapter_plan.generate','chapter_group_plan.generate')
 AND generation->>'logical_key'=prior.logical_key AND generation->>'planning_scope'=prior.planning_scope
 AND generation->'input_snapshot'=prior.input_snapshot AND generation->>'input_snapshot_hash'=prior.input_snapshot_hash
 AND (generation->>'repair_number')::integer=prior.repair_number
 AND generation->>'repair_of_candidate_id' IS NOT DISTINCT FROM prior.repair_of_candidate_id
 AND generation->>'repair_reason' IS NOT DISTINCT FROM prior.repair_reason
 AND generation->>'narrative_search_id' IS NOT DISTINCT FROM prior.narrative_search_id
 AND generation->>'narrative_search_branch_key' IS NOT DISTINCT FROM prior.narrative_search_branch_key
 AND generation->>'candidate_asset_version_id' IS NULL AND prior.candidate_asset_version_id IS NULL
 AND r.target_runtime#>>'{planning_capacity,context_revalidation,contract_version}'='same-capacity-semantic-preparation.v1'
 AND r.target_runtime#>>'{planning_capacity,context_revalidation,context_asset_version_id}'=context.asset_version_id
 AND r.target_runtime#>>'{planning_capacity,context_revalidation,context_content_hash}'=context.content_hash
 AND r.target_runtime#>'{planning_capacity,context_revalidation,source_failure}'=attempt.result
 AND r.target_runtime#>'{planning_capacity,context_revalidation,single_request_limit}'=attempt.result#>'{failure_details,limit}'
 AND r.target_runtime#>'{planning_capacity,external_intents_at_source}'='0'::jsonb
 AND r.target_runtime#>'{planning_capacity,allocated_task_tokens}'=r.target_runtime#>'{planning_capacity,prior_task_tokens}'
 AND r.target_runtime#>'{planning_capacity,single_request_ceiling}'=attempt.result#>'{failure_details,limit}'
 AND snapshot.snapshot_payload->>'context_policy_ref'='context-policy:chapter-generation-pack:v4'
 AND context_owner.project_id=r.project_id AND context_owner.asset_type='context_bundle'
 AND context.content->>'project_id'=r.project_id AND context.content->>'workspace_id'=r.workspace_id AND context.content->>'book_id'=r.book_id
 AND context.content->>'planning_context_policy_version'='context-policy:chapter-generation-pack:v4'
 AND context.content->'arc_working_set'=r.source_command->'arc_working_set'
 AND book.project_id=r.project_id AND book.workspace_id=r.workspace_id AND book.book_id=r.book_id
 AND book.state IN ('READY','PAUSED') AND book.active_chapter_request_id IS NULL
 AND (r.source_command#>>'{arc_working_set,working_manuscript,target_chapter}')::integer=book.current_chapter+1
 AND (r.source_command#>>'{arc_working_set,working_manuscript,accepted_through_chapter}')::integer=book.accepted_through_chapter
 AND formation.project_id=r.project_id AND formation.workspace_id=r.workspace_id AND formation.book_id=r.book_id
 AND formation.frozen_stage_inputs#>>'{generation_policy,auto_authorization,authorized_by_principal_id}'=registration.actor_id
 AND NOT EXISTS(SELECT 1 FROM authority_story_creation_cancellation WHERE formation_run_id=formation.formation_run_id)
 AND NOT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=source.operation_id)
 AND NOT EXISTS(SELECT 1 FROM authority_budget_reservation WHERE operation_id=source.operation_id)
 AND NOT EXISTS(SELECT 1 FROM authority_attempt WHERE operation_id=source.operation_id AND status NOT IN ('FAILED_RETRYABLE','FAILED_FINAL'))
 AND NOT EXISTS(SELECT 1 FROM authority_lease_acquisition lease JOIN authority_attempt a USING(attempt_id)
   WHERE a.operation_id=source.operation_id AND lease.status='HELD')
 AND NOT EXISTS(SELECT 1 FROM authority_cancellation_command WHERE operation_id=source.operation_id)
 AND NOT EXISTS(SELECT 1 FROM authority_worker_cancel_signal WHERE operation_id=source.operation_id AND acknowledged_at IS NULL)
 AND EXISTS(SELECT 1 FROM authority_operation_output_asset receipt_output JOIN authority_asset_version receipt USING(asset_version_id)
   JOIN authority_asset asset ON asset.asset_id=receipt.asset_id WHERE receipt_output.operation_id=registration.operation_id
   AND receipt_output.role='primary' AND asset.asset_type='planning_runtime_continuation' AND asset.project_id=r.project_id
   AND receipt.content->>'source_operation_id'=source.operation_id AND receipt.content->'target_runtime'=r.target_runtime)
) $$"""

_ANCHOR = "AND NOT authority_working_plan_input_continuation_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))"
assert PREVIOUS_GUARD.count(_ANCHOR) == 1
GUARD_STATEMENT = PREVIOUS_GUARD.replace(_ANCHOR, _ANCHOR + "\n               AND NOT authority_semantic_preparation_continuation_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))")
UPGRADE_STATEMENTS = [PERMITTED, GUARD_STATEMENT]
DOWNGRADE_STATEMENTS: list[str] = []
