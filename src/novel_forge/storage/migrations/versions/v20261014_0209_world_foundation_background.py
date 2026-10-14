from __future__ import annotations

from .v20261014_0206_world_disclosure_revalidation import UPGRADE_STATEMENTS as PREVIOUS
from .v20261014_0208_world_isolated_source_correction import UPGRADE_STATEMENTS as CAPACITY

MIGRATION_ID = "20261014_0209_world_foundation_background"
DOWN_REVISION = "20261014_0208_world_isolated_source_correction"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Append exact complete-result Foundation background revalidation; preserve original Source, rejected action, receipts and isolated unknowns."

_CAPACITY_VERSIONS = "IN ('world-host-revalidation.v1','world-host-revalidation.v2')"
assert CAPACITY[1].count(_CAPACITY_VERSIONS) == 1

UPGRADE_STATEMENTS = [
    PREVIOUS[1].replace("authority_world_contract_continuation_permitted(", "authority_world_contract_continuation_permitted_legacy_0209("),
    r"""CREATE OR REPLACE FUNCTION authority_world_contract_continuation_permitted(runtime_id TEXT, child_id TEXT, successor_generation JSONB)
RETURNS BOOLEAN LANGUAGE plpgsql AS $$
DECLARE source_id TEXT; admitted BOOLEAN;
BEGIN
    IF NOT EXISTS(SELECT 1 FROM authority_story_planning_runtime_continuation r WHERE r.continuation_id=runtime_id
        AND r.decision_evidence->>'host_revalidation'='world-host-revalidation.v3') THEN
        RETURN authority_world_contract_continuation_permitted_legacy_0209(runtime_id,child_id,successor_generation);
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
        JOIN authority_asset_version rejected ON rejected.asset_version_id=r.target_runtime#>>'{world_host_revalidation,action,asset_version_id}'
        JOIN authority_asset_version foundation ON foundation.asset_version_id=r.target_runtime#>>'{world_host_revalidation,foundation_binding,asset_version_id}'
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
          AND child.command_payload#>>'{payload,logical_key}'='chapter:1'
          AND child.command_payload#>>'{payload,generator_operation_name}'=source.generator_operation_name
          AND child.command_payload#>'{payload,world_preparation_request}'=original.command_payload#>'{payload,world_preparation_request}'
          AND r.target_runtime#>>'{world_host_revalidation,contract_version}'='world-host-revalidation.v3'
          AND r.target_runtime#>>'{world_host_revalidation,revalidation_kind}'='FOUNDATION_RULE_BACKGROUND'
          AND r.target_runtime#>>'{world_host_revalidation,source_operation_id}'=source_id
          AND r.target_runtime#>>'{world_host_revalidation,accepted_history_mutation_allowed}'='false'
          AND r.target_runtime#>>'{world_host_revalidation,character_knowledge_granted}'='false'
          AND r.target_runtime#>>'{world_host_revalidation,background_projection_hash}' ~ '^sha256:[0-9a-f]{64}$'
          AND r.target_runtime#>>'{world_host_revalidation,plan_digest}' ~ '^sha256:[0-9a-f]{64}$'
          AND jsonb_array_length(r.target_runtime#>'{world_host_revalidation,retained_effect_ids}')=2
          AND frozen.content_hash=r.target_runtime#>>'{world_host_revalidation,source,content_hash}'
          AND generated.content_hash=r.target_runtime#>>'{world_host_revalidation,generation,content_hash}'
          AND evaluated.content_hash=r.target_runtime#>>'{world_host_revalidation,evaluation,content_hash}'
          AND rejected.content_hash=r.target_runtime#>>'{world_host_revalidation,action,content_hash}'
          AND foundation.content_hash=r.target_runtime#>>'{world_host_revalidation,foundation_binding,content_hash}'
          AND frozen.content#>>'{contract,contract_version}'='world-preparation-source.v3'
          AND frozen.content#>>'{contract,reality,baseline_kind}'='APPROVED_FOUNDATION'
          AND frozen.content#>>'{contract,reality,epistemic_contract}'='world-agency.v2'
          AND frozen.content#>'{contract,reality,foundation_rule_background}' IS NULL
          AND frozen.content#>'{contract,actor_experiment}' IS NULL
          AND EXISTS(SELECT 1 FROM jsonb_array_elements(frozen.content#>'{contract,reality,world_rule_constraints}') rule
              WHERE rule->>'asset_version_id'=foundation.asset_version_id AND rule->>'content_hash'=foundation.content_hash)
          AND COALESCE(foundation.content#>'{candidate_payload,world_foundation}',foundation.content->'world_foundation')=frozen.content#>'{contract,world_foundation}'
          AND frozen.content#>'{contract,request}'=original.command_payload#>'{payload,world_preparation_request}'
          AND generated.content#>'{contract,source}'=r.target_runtime#>'{world_host_revalidation,source}'
          AND evaluated.content#>'{contract,source}'=generated.content#>'{contract,source}'
          AND evaluated.content#>'{contract,generation}'=r.target_runtime#>'{world_host_revalidation,generation}'
          AND rejected.content#>'{contract,source}'=generated.content#>'{contract,source}'
          AND rejected.content#>'{contract,generation}'=r.target_runtime#>'{world_host_revalidation,generation}'
          AND rejected.content#>'{contract,evaluation}'=r.target_runtime#>'{world_host_revalidation,evaluation}'
          AND rejected.content#>>'{contract,world_plan,disposition}'='BLOCKED'
          AND EXISTS(SELECT 1 FROM jsonb_array_elements(rejected.content#>'{contract,world_plan,rejected_paths}') path
              WHERE path#>>'{rejection,code}'='WORLD_COMPILED_RULE_VIOLATION')
          AND EXISTS(SELECT 1 FROM authority_attempt a WHERE a.operation_id=source_id AND a.status='FAILED_FINAL'
              AND a.attempt_number=(SELECT max(attempt_number) FROM authority_attempt WHERE operation_id=source_id)
              AND a.result->>'error_code'='WORLD_PREPARATION_RESULT_INVALID')
          AND r.source_evidence_asset_version_id=generated.asset_version_id
          AND EXISTS(SELECT 1 FROM authority_operation_output_asset output WHERE output.operation_id=source_id AND output.asset_version_id=rejected.asset_version_id)
          AND book.project_id=r.project_id AND book.workspace_id=r.workspace_id AND book.book_id=r.book_id
          AND book.current_chapter=0 AND book.accepted_through_chapter=0 AND book.active_chapter_request_id IS NULL
          AND book.state NOT IN ('ABORTED','CANCELLED','COMPLETED') AND source.logical_key='chapter:1'
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
    SELECT EXISTS(SELECT 1 FROM authority_story_planning_runtime_continuation r
        CROSS JOIN LATERAL (VALUES ('generation','world_candidates.generate'),('evaluation','world_candidates.evaluate')) stage(kind,name)
        JOIN authority_asset_version output ON output.asset_version_id=r.target_runtime#>>ARRAY['world_host_revalidation',stage.kind,'asset_version_id']
        JOIN authority_external_effect effect ON effect.external_effect_id=output.content#>>'{contract,evidence,external_receipt_ref}'
        JOIN authority_operation owner ON owner.operation_id=effect.operation_id
        WHERE r.continuation_id=runtime_id AND owner.actor_id=(SELECT actor_id FROM authority_operation WHERE operation_id=source_id)
          AND owner.project_id=r.project_id AND owner.workspace_id=r.workspace_id
          AND effect.status='SUCCEEDED' AND effect.request_payload->>'stage'=stage.name
          AND effect.effect_type='model.invoke' AND effect.operation_id=output.content#>>'{contract,evidence,operation_id}'
          AND EXISTS(SELECT 1 FROM authority_operation_output_asset stored WHERE stored.operation_id=owner.operation_id AND stored.asset_version_id=output.asset_version_id)
          AND effect.request_payload#>'{input,world_preparation,source_ref}'=r.target_runtime#>'{world_host_revalidation,source}'
          AND owner.operation_id=r.target_runtime#>>ARRAY['world_host_revalidation','result_owners',stage.kind]
          AND to_jsonb(effect.external_effect_id) <@ (r.target_runtime#>'{world_host_revalidation,retained_effect_ids}')
          AND EXISTS(SELECT 1 FROM authority_external_effect_dispatch d JOIN authority_external_receipt receipt USING(dispatch_id)
              WHERE d.external_effect_id=effect.external_effect_id AND d.status='SUCCEEDED' AND receipt.status='VERIFIED'
                AND d.evidence->'result'=output.content#>'{contract,output}' AND receipt.payload->'evidence'=d.evidence)
        GROUP BY r.continuation_id HAVING count(*)=2) INTO admitted;
    IF NOT admitted THEN RETURN FALSE; END IF;
    WITH RECURSIVE lineage(operation_id) AS (
          SELECT source_id UNION SELECT neighbor.operation_id FROM lineage JOIN authority_operation anchor ON anchor.operation_id=lineage.operation_id
          JOIN authority_operation neighbor ON neighbor.causation_operation_id=anchor.operation_id OR neighbor.operation_id=anchor.causation_operation_id
          WHERE neighbor.definition_name='story_planning.generate' AND neighbor.project_id=anchor.project_id
            AND neighbor.command_payload#>>'{payload,book_id}'=anchor.command_payload#>>'{payload,book_id}')
    SELECT EXISTS(SELECT 1 FROM authority_external_effect e JOIN lineage USING(operation_id)
            WHERE e.status NOT IN ('SUCCEEDED','FAILED_FINAL','CANCELLED') AND NOT authority_generation_isolated(e.external_effect_id))
        OR EXISTS(SELECT 1 FROM authority_budget_reservation b JOIN lineage USING(operation_id)
            LEFT JOIN authority_external_effect complete ON complete.external_effect_id=b.external_effect_id
            WHERE b.status NOT IN ('SETTLED','RELEASED') AND NOT COALESCE(authority_generation_isolated(b.external_effect_id),FALSE)
              AND NOT COALESCE((b.status='HELD_UNKNOWN' AND complete.status='SUCCEEDED'
                AND EXISTS(SELECT 1 FROM authority_story_planning_runtime_continuation r WHERE r.continuation_id=runtime_id
                  AND to_jsonb(complete.external_effect_id) <@ (r.target_runtime#>'{world_host_revalidation,retained_effect_ids}'))),FALSE))
        OR EXISTS(SELECT 1 FROM authority_lease_acquisition lease JOIN authority_attempt attempt USING(attempt_id) JOIN lineage USING(operation_id)
            WHERE lease.status='HELD' AND NOT (attempt.operation_id=child_id AND attempt.status='RUNNING'
                AND attempt.attempt_number=(SELECT max(active.attempt_number) FROM authority_attempt active WHERE active.operation_id=child_id)
                AND EXISTS(SELECT 1 FROM authority_operation executing WHERE executing.operation_id=child_id AND executing.status='EXECUTING')))
    INTO admitted;
    RETURN NOT admitted AND authority_planning_cli_lineage_reconciled(source_id);
END; $$""",
    CAPACITY[1].replace(_CAPACITY_VERSIONS, "IN ('world-host-revalidation.v1','world-host-revalidation.v2','world-host-revalidation.v3')"),
]
DOWNGRADE_STATEMENTS: list[str] = []
