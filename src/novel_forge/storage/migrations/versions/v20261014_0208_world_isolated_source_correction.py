from __future__ import annotations

from .v20261012_0200_generation_history_observations import UPGRADE_STATEMENTS as PREVIOUS
from .v20261014_0207_world_revalidation_capacity import UPGRADE_STATEMENTS as CAPACITY

MIGRATION_ID = "20261014_0208_world_isolated_source_correction"
DOWN_REVISION = "20261014_0207_world_revalidation_capacity"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Append exact unsent World source-version correction through native isolated continuation; preserve unknown effects and complete siblings."

_ANCHOR = "WHERE r.continuation_id=runtime_id AND r.successor_operation_id=child_id"
_BRANCH = """OR (
 r.decision_evidence->>'host_revalidation'='world-isolated-source-correction.v1'
 AND source.status='FAILED_FINAL' AND source.definition_version='1.21.0'
 AND registered.actor_id=source.actor_id AND registered.project_id=source.project_id AND registered.workspace_id=source.workspace_id
 AND NOT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=source.operation_id)
 AND NOT EXISTS(SELECT 1 FROM authority_budget_reservation WHERE operation_id=source.operation_id)
 AND NOT EXISTS(SELECT 1 FROM authority_lease_acquisition lease JOIN authority_attempt a USING(attempt_id) WHERE a.operation_id=source.operation_id AND lease.status='HELD')
 AND EXISTS(SELECT 1 FROM authority_attempt a WHERE a.operation_id=source.operation_id AND a.status='FAILED_FINAL'
   AND a.attempt_number=(SELECT max(attempt_number) FROM authority_attempt WHERE operation_id=source.operation_id)
   AND a.result->>'error_code'='WORLD_ISOLATED_RECEIPT_INVALID')
 AND r.target_runtime#>>'{world_source_correction,contract_version}'='world-isolated-source-correction.v1'
 AND r.target_runtime#>>'{world_source_correction,source_operation_id}'=source.operation_id
 AND r.target_runtime#>'{world_source_correction,isolation}'=i.proof
 AND jsonb_array_length(r.target_runtime#>'{world_source_correction,skipped_source_versions}')>0
 AND EXISTS(SELECT 1 FROM authority_story_planning_runtime_continuation parent
   JOIN authority_operation parent_registration ON parent_registration.operation_id=parent.registered_by_operation_id
   JOIN authority_operation origin ON origin.operation_id=i.operation_id
   JOIN authority_story_planning_generation origin_generation ON origin_generation.operation_id=origin.operation_id
   JOIN authority_asset_version frozen ON frozen.asset_version_id=r.target_runtime#>>'{world_source_correction,source,asset_version_id}'
   JOIN authority_asset_version generated ON generated.asset_version_id=r.target_runtime#>>'{world_source_correction,generation,asset_version_id}'
   JOIN authority_book_production book ON book.book_run_id=frozen.content#>>'{contract,request,book_run_id}'
   JOIN authority_external_effect effect ON effect.external_effect_id=generated.content#>>'{contract,evidence,external_receipt_ref}'
   WHERE parent.continuation_id=source.command_payload#>>'{payload,runtime_continuation_id}' AND parent.source_operation_id=i.operation_id
     AND parent.successor_operation_id=source.operation_id AND parent.successor_command=source.command_payload->'payload'
     AND parent.project_id=source.project_id AND parent.workspace_id=source.workspace_id AND parent.book_id=i.book_id
     AND parent_registration.status='SUCCEEDED' AND parent_registration.definition_name='story_planning.runtime_continuation.register'
     AND parent_registration.actor_id=source.actor_id AND parent.target_runtime->'generation_isolation'=i.proof
     AND r.target_runtime#>>'{world_source_correction,parent_continuation_id}'=parent.continuation_id
     AND r.target_runtime->'planning_capacity' IS NOT DISTINCT FROM parent.target_runtime->'planning_capacity'
     AND origin.actor_id=source.actor_id AND origin.workspace_id=source.workspace_id AND origin.project_id=source.project_id
     AND origin_generation.input_snapshot=prior.input_snapshot AND origin_generation.input_snapshot_hash=prior.input_snapshot_hash
     AND origin.command_payload#>'{payload,world_preparation_request}'=source.command_payload#>'{payload,world_preparation_request}'
     AND frozen.content_hash=r.target_runtime#>>'{world_source_correction,source,content_hash}'
     AND frozen.content#>>'{contract,contract_version}'='world-preparation-source.v3'
     AND frozen.content#>'{contract,request}'=source.command_payload#>'{payload,world_preparation_request}'
     AND book.project_id=source.project_id AND book.workspace_id=source.workspace_id AND book.book_id=i.book_id
     AND book.state NOT IN ('CANCELLED','ABORTED','COMPLETED') AND prior.logical_key='chapter:'||(book.current_chapter+1)::text
     AND book.input_snapshot_id=frozen.content#>>'{contract,request,input_snapshot_id}'
     AND book.accepted_through_chapter::text=frozen.content#>>'{contract,request,accepted_through_chapter}'
     AND NOT EXISTS(SELECT 1 FROM authority_story_creation_cancellation cancel WHERE cancel.project_id=book.project_id AND book.stable_idempotency_key=cancel.formation_run_id||':production')
     AND generated.content_hash=r.target_runtime#>>'{world_source_correction,generation,content_hash}'
     AND generated.content#>'{contract,source}'=r.target_runtime#>'{world_source_correction,source}'
     AND EXISTS(SELECT 1 FROM authority_operation_output_asset output WHERE output.operation_id=origin.operation_id AND output.asset_version_id=frozen.asset_version_id)
     AND EXISTS(SELECT 1 FROM authority_operation_output_asset output WHERE output.operation_id=origin.operation_id AND output.asset_version_id=generated.asset_version_id)
     AND effect.operation_id=origin.operation_id AND effect.effect_type='model.invoke' AND effect.status='SUCCEEDED'
     AND effect.request_payload->>'stage'='world_candidates.generate'
     AND EXISTS(SELECT 1 FROM authority_external_effect_dispatch dispatch JOIN authority_external_receipt receipt USING(dispatch_id)
       WHERE dispatch.external_effect_id=effect.external_effect_id AND dispatch.status='SUCCEEDED' AND receipt.status='VERIFIED'
       AND receipt.payload->'evidence'=dispatch.evidence AND receipt.payload#>'{evidence,result}'=generated.content#>'{contract,output}')))
"""
_FUNCTION = PREVIOUS[2]
assert _FUNCTION.count(_ANCHOR) == 1
_AUTH = "OR r.decision_evidence->>'capacity_inheritance'='generation-capacity-inheritance.v1'))"
assert _FUNCTION.count(_AUTH) == 1
_CORRECTION = _BRANCH.removeprefix("OR ").strip()
_CAPACITY_ANCHOR = "WHERE r.continuation_id=runtime_id AND r.successor_operation_id=child_id AND r.chain_depth>0"
_CAPACITY_BINDING = """AND (
 (r.target_runtime->'world_source_correction' IS NULL AND NOT EXISTS(
   SELECT 1 FROM authority_story_planning_runtime_continuation parent
   WHERE parent.continuation_id=source.command_payload#>>'{payload,runtime_continuation_id}'
     AND parent.successor_operation_id=source.operation_id AND parent.target_runtime->'world_source_correction' IS NOT NULL))
 OR EXISTS(SELECT 1 FROM authority_story_planning_runtime_continuation parent
   JOIN authority_operation registration ON registration.operation_id=parent.registered_by_operation_id
   WHERE parent.continuation_id=source.command_payload#>>'{payload,runtime_continuation_id}'
     AND parent.successor_operation_id=source.operation_id AND parent.successor_command=source.command_payload->'payload'
     AND parent.project_id=source.project_id AND parent.workspace_id=source.workspace_id
     AND parent.book_id=source.command_payload#>>'{payload,book_id}'
     AND registration.status='SUCCEEDED' AND registration.definition_name='story_planning.runtime_continuation.register'
     AND registration.actor_id=source.actor_id AND registration.project_id=source.project_id AND registration.workspace_id=source.workspace_id
     AND r.decision_evidence->>'world_source_inheritance'='world-source-inheritance.v1'
     AND r.target_runtime->'world_source_correction'=parent.target_runtime->'world_source_correction'
     AND r.target_runtime#>>'{world_source_correction,contract_version}'='world-isolated-source-correction.v1'
     AND r.target_runtime->'generation_isolation'=parent.target_runtime->'generation_isolation'
     AND r.target_runtime->'generation_isolation'=r.target_runtime#>'{world_source_correction,isolation}'))
"""
assert CAPACITY[0].count(_CAPACITY_ANCHOR) == 1
UPGRADE_STATEMENTS = [
    _FUNCTION.replace(_ANCHOR, _BRANCH + _ANCHOR).replace(_AUTH,
        "OR r.decision_evidence->>'capacity_inheritance'='generation-capacity-inheritance.v1' OR " + _CORRECTION + "))"),
    CAPACITY[0].replace(_CAPACITY_ANCHOR, _CAPACITY_ANCHOR + "\n" + _CAPACITY_BINDING),
]
DOWNGRADE_STATEMENTS: list[str] = []
