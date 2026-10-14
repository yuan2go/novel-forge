from __future__ import annotations

from .v20261014_0209_world_foundation_background import UPGRADE_STATEMENTS as PREVIOUS

MIGRATION_ID = "20261014_0210_world_working_frontier_revalidation"
DOWN_REVISION = "20261014_0209_world_foundation_background"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Admit exact complete World results at a bound working frontier; preserve original failures, accepted history, receipts and unknown usage."

_RECEIPT_ANCHOR = "    SELECT EXISTS(SELECT 1 FROM authority_story_planning_runtime_continuation r\n        CROSS JOIN LATERAL"
assert PREVIOUS[1].count(_RECEIPT_ANCHOR) == 1
_CAPACITY_VERSIONS = "IN ('world-host-revalidation.v1','world-host-revalidation.v2','world-host-revalidation.v3')"
assert PREVIOUS[2].count(_CAPACITY_VERSIONS) == 1
assert PREVIOUS[1].count("authority_world_contract_continuation_permitted(") == 1
_OWNER_ANCHOR = "          AND owner.project_id=r.project_id AND owner.workspace_id=r.workspace_id"
_RECEIPT_SUFFIX = _RECEIPT_ANCHOR + PREVIOUS[1].split(_RECEIPT_ANCHOR, 1)[1]
assert _RECEIPT_SUFFIX.count(_OWNER_ANCHOR) == 1
_RECEIPT_SUFFIX = _RECEIPT_SUFFIX.replace(_OWNER_ANCHOR, _OWNER_ANCHOR + r"""
          AND owner.definition_name='story_planning.generate' AND owner.definition_version='1.21.0'
          AND owner.command_payload#>>'{payload,book_id}'=r.book_id
          AND owner.command_payload#>>'{payload,logical_key}'=(SELECT logical_key FROM authority_story_planning_generation WHERE operation_id=source_id)
          AND owner.command_payload#>'{payload,world_preparation_request}'=(SELECT command_payload#>'{payload,world_preparation_request}' FROM authority_operation WHERE operation_id=source_id)
          AND EXISTS(WITH RECURSIVE ancestors(operation_id) AS (
              SELECT source_id UNION SELECT neighbor.operation_id FROM ancestors
              JOIN authority_operation anchor ON anchor.operation_id=ancestors.operation_id
              JOIN authority_operation neighbor ON neighbor.causation_operation_id=anchor.operation_id OR neighbor.operation_id=anchor.causation_operation_id
              WHERE neighbor.definition_name='story_planning.generate' AND neighbor.project_id=anchor.project_id
                AND neighbor.command_payload#>>'{payload,book_id}'=anchor.command_payload#>>'{payload,book_id}')
              SELECT 1 FROM ancestors WHERE operation_id=owner.operation_id)""")

UPGRADE_STATEMENTS = [
    PREVIOUS[1].replace("authority_world_contract_continuation_permitted(", "authority_world_contract_continuation_permitted_legacy_0210("),
    r"""CREATE OR REPLACE FUNCTION authority_world_contract_continuation_permitted(runtime_id TEXT, child_id TEXT, successor_generation JSONB)
RETURNS BOOLEAN LANGUAGE plpgsql AS $$
DECLARE source_id TEXT; admitted BOOLEAN;
BEGIN
    IF NOT EXISTS(SELECT 1 FROM authority_story_planning_runtime_continuation r WHERE r.continuation_id=runtime_id
        AND r.decision_evidence->>'host_revalidation'='world-host-revalidation.v4') THEN
        RETURN authority_world_contract_continuation_permitted_legacy_0210(runtime_id,child_id,successor_generation);
    END IF;
    SELECT source_operation_id INTO source_id FROM authority_story_planning_runtime_continuation WHERE continuation_id=runtime_id;
    SELECT EXISTS(SELECT 1 FROM authority_story_planning_runtime_continuation r
        JOIN authority_operation original ON original.operation_id=r.source_operation_id
        JOIN authority_story_planning_generation source ON source.operation_id=original.operation_id
        JOIN authority_operation child ON child.operation_id=child_id
        JOIN authority_operation registration ON registration.operation_id=r.registered_by_operation_id
        JOIN authority_asset_version frozen ON frozen.asset_version_id=r.target_runtime#>>'{world_host_revalidation,source,asset_version_id}'
        JOIN authority_asset_version generated ON generated.asset_version_id=r.target_runtime#>>'{world_host_revalidation,generation,asset_version_id}'
        JOIN authority_asset_version evaluated ON evaluated.asset_version_id=r.target_runtime#>>'{world_host_revalidation,evaluation,asset_version_id}'
        JOIN authority_book_production book ON book.book_run_id=frozen.content#>>'{contract,request,book_run_id}'
        WHERE r.continuation_id=runtime_id AND r.source_operation_id=source_id
          AND r.source_command=original.command_payload->'payload' AND r.successor_command=child.command_payload->'payload'
          AND (r.successor_operation_id IS NULL OR r.successor_operation_id=child_id)
          AND source.project_id=r.project_id AND source.workspace_id=r.workspace_id AND source.book_id=r.book_id
          AND source.generator_operation_name='chapter_plan.generate' AND source.planning_scope='CHAPTER' AND source.candidate_asset_version_id IS NULL
          AND original.definition_name='story_planning.generate' AND original.definition_version='1.21.0' AND original.status='FAILED_FINAL'
          AND registration.definition_name='story_planning.runtime_continuation.register' AND registration.definition_version='2.0.0' AND registration.status='SUCCEEDED'
          AND registration.actor_id=original.actor_id AND registration.project_id=r.project_id AND registration.workspace_id=r.workspace_id
          AND original.project_id=r.project_id AND original.workspace_id=r.workspace_id
          AND child.definition_name='story_planning.generate' AND child.definition_version='1.21.0'
          AND child.project_id=r.project_id AND child.workspace_id=r.workspace_id AND child.actor_id=original.actor_id AND child.causation_operation_id=source_id
          AND child.command_payload#>>'{payload,runtime_continuation_id}'=runtime_id
          AND child.command_payload#>>'{payload,book_id}'=r.book_id AND child.command_payload#>>'{payload,execution_contract_version}'=original.definition_version
          AND child.command_payload#>>'{payload,repair_reason}'='WORLD_HOST_REVALIDATION_SUCCESSOR'
          AND child.command_payload#>>'{payload,logical_key}'=source.logical_key
          AND child.command_payload#>>'{payload,generator_operation_name}'=source.generator_operation_name
          AND child.command_payload#>'{payload,world_preparation_request}'=original.command_payload#>'{payload,world_preparation_request}'
          AND r.target_runtime#>>'{world_host_revalidation,contract_version}'='world-host-revalidation.v4'
          AND r.target_runtime#>>'{world_host_revalidation,revalidation_kind}'='WORKING_CHAPTER_FRONTIER'
          AND r.target_runtime#>>'{world_host_revalidation,source_operation_id}'=source_id
          AND r.target_runtime#>>'{world_host_revalidation,accepted_history_mutation_allowed}'='false'
          AND r.target_runtime#>>'{world_host_revalidation,character_knowledge_granted}'='false'
          AND r.target_runtime#>>'{world_host_revalidation,plan_digest}' ~ '^sha256:[0-9a-f]{64}$'
          AND r.target_runtime#>>'{world_host_revalidation,working_snapshot_hash}' ~ '^sha256:[0-9a-f]{64}$'
          AND r.target_runtime#>>'{world_host_revalidation,working_observation_projection_hash}' ~ '^sha256:[0-9a-f]{64}$'
          AND jsonb_array_length(r.target_runtime#>'{world_host_revalidation,retained_effect_ids}')=2
          AND frozen.content_hash=r.target_runtime#>>'{world_host_revalidation,source,content_hash}'
          AND generated.content_hash=r.target_runtime#>>'{world_host_revalidation,generation,content_hash}'
          AND evaluated.content_hash=r.target_runtime#>>'{world_host_revalidation,evaluation,content_hash}'
          AND frozen.content#>>'{contract,contract_version}'='world-preparation-source.v5'
          AND frozen.content#>>'{contract,reality,epistemic_contract}'='world-agency.v2'
          AND frozen.content#>'{contract,actor_experiment}' IS NULL
          AND frozen.content#>>'{contract,target_chapter}'=r.target_runtime#>>'{world_host_revalidation,target_chapter}'
          AND frozen.content#>>'{contract,working_manuscript,target_chapter}'=frozen.content#>>'{contract,target_chapter}'
          AND frozen.content#>>'{contract,working_manuscript,book_run_id}'=book.book_run_id
          AND frozen.content#>>'{contract,working_manuscript,snapshot_hash}'=r.target_runtime#>>'{world_host_revalidation,working_snapshot_hash}'
          AND frozen.content#>>'{contract,reality,working_observation_context,snapshot_hash}'=r.target_runtime#>>'{world_host_revalidation,working_snapshot_hash}'
          AND frozen.content#>>'{contract,reality,working_observation_context,target_chapter}'=frozen.content#>>'{contract,target_chapter}'
          AND frozen.content#>>'{contract,reality,working_observation_context,projection_hash}'=r.target_runtime#>>'{world_host_revalidation,working_observation_projection_hash}'
          AND frozen.content#>>'{contract,reality,working_observation_context,accepted_history_mutation_allowed}'='false'
          AND frozen.content#>>'{contract,reality,working_observation_context,character_knowledge_granted}'='false'
          AND frozen.content#>'{contract,request}'=original.command_payload#>'{payload,world_preparation_request}'
          AND generated.content#>'{contract,source}'=r.target_runtime#>'{world_host_revalidation,source}'
          AND evaluated.content#>'{contract,source}'=generated.content#>'{contract,source}'
          AND evaluated.content#>'{contract,generation}'=r.target_runtime#>'{world_host_revalidation,generation}'
          AND r.source_evidence_asset_version_id=generated.asset_version_id
          AND EXISTS(SELECT 1 FROM authority_attempt a WHERE a.operation_id=source_id AND a.status='FAILED_FINAL'
              AND a.attempt_number=(SELECT max(attempt_number) FROM authority_attempt WHERE operation_id=source_id)
              AND a.result->>'error_code'='WORLD_DISCLOSURE_SOURCE_SCOPE_INVALID')
          AND book.project_id=r.project_id AND book.workspace_id=r.workspace_id AND book.book_id=r.book_id
          AND (book.current_chapter+1)::text=frozen.content#>>'{contract,target_chapter}'
          AND book.current_chapter>book.accepted_through_chapter
          AND book.accepted_through_chapter::text=frozen.content#>>'{contract,request,accepted_through_chapter}'
          AND book.active_chapter_request_id IS NULL AND book.state IN ('READY','CHAPTER_PLAN_REQUIRED')
          AND source.logical_key='chapter:'||(book.current_chapter+1)::text
          AND book.input_snapshot_id=frozen.content#>>'{contract,request,input_snapshot_id}'
          AND NOT EXISTS(SELECT 1 FROM authority_story_creation_cancellation c WHERE c.project_id=book.project_id
              AND book.stable_idempotency_key=c.formation_run_id||':production')
          AND successor_generation->>'project_id'=source.project_id AND successor_generation->>'workspace_id'=source.workspace_id
          AND successor_generation->>'book_id'=source.book_id AND successor_generation->>'generator_operation_name'=source.generator_operation_name
          AND successor_generation->>'logical_key'=source.logical_key AND successor_generation->>'planning_scope'=source.planning_scope
          AND successor_generation->>'input_snapshot_hash'=source.input_snapshot_hash AND successor_generation->'input_snapshot'=source.input_snapshot
          AND successor_generation->>'repair_number'=source.repair_number::text AND successor_generation->>'runtime_continuation_id'=runtime_id
          AND successor_generation->>'repair_reason'='WORLD_HOST_REVALIDATION_SUCCESSOR'
          AND successor_generation->>'candidate_asset_version_id' IS NULL AND successor_generation->>'repair_of_candidate_id' IS NULL
          AND successor_generation->>'repair_of_operation_id' IS NULL AND successor_generation->>'repair_result_asset_version_id' IS NULL
    ) INTO admitted;
    IF NOT admitted THEN RETURN FALSE; END IF;
""" + _RECEIPT_SUFFIX,
    PREVIOUS[2].replace(_CAPACITY_VERSIONS, "IN ('world-host-revalidation.v1','world-host-revalidation.v2','world-host-revalidation.v3','world-host-revalidation.v4')"),
]
DOWNGRADE_STATEMENTS: list[str] = []
