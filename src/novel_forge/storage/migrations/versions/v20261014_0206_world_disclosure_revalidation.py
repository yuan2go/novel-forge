from __future__ import annotations

from .v20261007_0171_world_projection_successor import UPGRADE_STATEMENTS as LEGACY_STATEMENTS

MIGRATION_ID = "20261014_0206_world_disclosure_revalidation"
DOWN_REVISION = "20261013_0205_completed_release_recovery"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Append exact field-address revalidation evidence; retain original outputs, failures and unknown usage."

UPGRADE_STATEMENTS = [
    LEGACY_STATEMENTS[0].replace("authority_world_contract_continuation_permitted(", "authority_world_contract_continuation_permitted_legacy_0206("),
    r"""CREATE OR REPLACE FUNCTION authority_world_contract_continuation_permitted(runtime_id TEXT, child_id TEXT, successor_generation JSONB)
RETURNS BOOLEAN LANGUAGE plpgsql AS $$
DECLARE source_id TEXT; admitted BOOLEAN;
BEGIN
    IF NOT EXISTS(SELECT 1 FROM authority_story_planning_runtime_continuation r WHERE r.continuation_id=runtime_id
        AND r.decision_evidence->>'host_revalidation'='world-host-revalidation.v2') THEN
        RETURN authority_world_contract_continuation_permitted_legacy_0206(runtime_id,child_id,successor_generation);
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
        WHERE r.continuation_id=runtime_id AND r.source_command=original.command_payload->'payload'
          AND r.successor_command=child.command_payload->'payload' AND (r.successor_operation_id IS NULL OR r.successor_operation_id=child_id)
          AND original.status='FAILED_FINAL' AND original.definition_name='story_planning.generate' AND original.definition_version='1.21.0'
          AND source.project_id=r.project_id AND source.workspace_id=r.workspace_id AND source.book_id=r.book_id
          AND source.generator_operation_name='chapter_plan.generate' AND source.planning_scope='CHAPTER' AND source.candidate_asset_version_id IS NULL
          AND registration.status='SUCCEEDED' AND registration.definition_name='story_planning.runtime_continuation.register' AND registration.definition_version='2.0.0'
          AND registration.project_id=r.project_id AND registration.workspace_id=r.workspace_id AND registration.actor_id=original.actor_id
          AND child.definition_name='story_planning.generate' AND child.definition_version='1.21.0'
          AND child.project_id=r.project_id AND child.workspace_id=r.workspace_id AND child.actor_id=original.actor_id AND child.causation_operation_id=source_id
          AND original.project_id=r.project_id AND original.workspace_id=r.workspace_id
          AND child.command_payload#>>'{payload,book_id}'=r.book_id
          AND child.command_payload#>>'{payload,runtime_continuation_id}'=runtime_id
          AND child.command_payload#>>'{payload,repair_reason}'='WORLD_HOST_REVALIDATION_SUCCESSOR'
          AND child.command_payload#>>'{payload,logical_key}'=source.logical_key
          AND child.command_payload#>>'{payload,generator_operation_name}'=source.generator_operation_name
          AND child.command_payload#>>'{payload,execution_contract_version}'=original.definition_version
          AND child.command_payload#>'{payload,world_preparation_request}'=original.command_payload#>'{payload,world_preparation_request}'
          AND r.target_runtime#>>'{world_host_revalidation,contract_version}'='world-host-revalidation.v2'
          AND r.target_runtime#>>'{world_host_revalidation,revalidation_kind}'='DISCLOSURE_FIELD_ADDRESS'
          AND r.target_runtime#>>'{world_host_revalidation,source_operation_id}'=source_id
          AND r.target_runtime#>>'{world_host_revalidation,disclosure_fields_contract}'='world-disclosure-fields.v2'
          AND r.target_runtime#>>'{world_host_revalidation,plan_digest}' ~ '^sha256:[0-9a-f]{64}$'
          AND r.target_runtime#>>'{world_host_revalidation,field_resolution_hash}' ~ '^sha256:[0-9a-f]{64}$'
          AND jsonb_array_length(r.target_runtime#>'{world_host_revalidation,field_resolutions}')>0
          AND frozen.content_hash=r.target_runtime#>>'{world_host_revalidation,source,content_hash}'
          AND generated.content_hash=r.target_runtime#>>'{world_host_revalidation,generation,content_hash}'
          AND evaluated.content_hash=r.target_runtime#>>'{world_host_revalidation,evaluation,content_hash}'
          AND frozen.content#>>'{contract,contract_version}'='world-preparation-source.v2'
          AND frozen.content#>>'{contract,reality,epistemic_contract}'='world-agency.v2'
          AND frozen.content#>'{contract,request}'=original.command_payload#>'{payload,world_preparation_request}'
          AND generated.content#>'{contract,source}'=r.target_runtime#>'{world_host_revalidation,source}'
          AND evaluated.content#>'{contract,source}'=generated.content#>'{contract,source}'
          AND evaluated.content#>'{contract,generation}'=r.target_runtime#>'{world_host_revalidation,generation}'
          AND r.source_evidence_asset_version_id=generated.asset_version_id
          AND EXISTS(SELECT 1 FROM authority_operation_output_asset output WHERE output.operation_id=source_id AND output.asset_version_id=frozen.asset_version_id)
          AND EXISTS(SELECT 1 FROM authority_operation_output_asset output WHERE output.operation_id=source_id AND output.asset_version_id=generated.asset_version_id)
          AND EXISTS(SELECT 1 FROM authority_operation_output_asset output WHERE output.operation_id=source_id AND output.asset_version_id=evaluated.asset_version_id)
          AND EXISTS(SELECT 1 FROM authority_external_effect effect WHERE effect.operation_id=source_id AND effect.effect_type='model.invoke'
              AND effect.status='SUCCEEDED' AND effect.external_effect_id=generated.content#>>'{contract,evidence,external_receipt_ref}' AND effect.request_payload->>'stage'='world_candidates.generate')
          AND EXISTS(SELECT 1 FROM authority_external_effect effect WHERE effect.operation_id=source_id AND effect.effect_type='model.invoke'
              AND effect.status='SUCCEEDED' AND effect.external_effect_id=evaluated.content#>>'{contract,evidence,external_receipt_ref}' AND effect.request_payload->>'stage'='world_candidates.evaluate')
          AND EXISTS(SELECT 1 FROM authority_attempt attempt WHERE attempt.operation_id=source_id AND attempt.status='FAILED_FINAL'
              AND attempt.attempt_number=(SELECT max(last.attempt_number) FROM authority_attempt last WHERE last.operation_id=source_id)
              AND attempt.result->>'error_code'='WORLD_DISCLOSURE_FIELDS_INVALID')
          AND book.project_id=r.project_id AND book.workspace_id=r.workspace_id AND book.book_id=r.book_id
          AND book.state NOT IN ('ABORTED','CANCELLED','COMPLETED') AND source.logical_key='chapter:'||(book.current_chapter+1)::text
          AND book.input_snapshot_id=frozen.content#>>'{contract,request,input_snapshot_id}'
          AND book.accepted_through_chapter::text=frozen.content#>>'{contract,request,accepted_through_chapter}'
          AND NOT EXISTS(SELECT 1 FROM authority_story_creation_cancellation cancellation WHERE cancellation.project_id=book.project_id
              AND book.stable_idempotency_key=cancellation.formation_run_id||':production')
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
    WITH RECURSIVE lineage(operation_id) AS (
        SELECT source_id UNION SELECT neighbor.operation_id FROM lineage JOIN authority_operation anchor ON anchor.operation_id=lineage.operation_id
        JOIN authority_operation neighbor ON neighbor.causation_operation_id=anchor.operation_id OR neighbor.operation_id=anchor.causation_operation_id
        WHERE neighbor.definition_name='story_planning.generate' AND neighbor.project_id=anchor.project_id)
    SELECT EXISTS(SELECT 1 FROM authority_external_effect effect JOIN lineage USING(operation_id) WHERE effect.status NOT IN ('SUCCEEDED','FAILED_FINAL','CANCELLED'))
        OR EXISTS(SELECT 1 FROM authority_budget_reservation reservation JOIN lineage USING(operation_id)
            LEFT JOIN authority_external_effect complete ON complete.external_effect_id=reservation.external_effect_id
            WHERE reservation.status NOT IN ('SETTLED','RELEASED') AND NOT (reservation.status='HELD_UNKNOWN' AND complete.status='SUCCEEDED'
                AND EXISTS(SELECT 1 FROM authority_story_planning_runtime_continuation r WHERE r.continuation_id=runtime_id
                    AND complete.external_effect_id IN (
                        (SELECT v.content#>>'{contract,evidence,external_receipt_ref}' FROM authority_asset_version v WHERE v.asset_version_id=r.target_runtime#>>'{world_host_revalidation,generation,asset_version_id}'),
                        (SELECT v.content#>>'{contract,evidence,external_receipt_ref}' FROM authority_asset_version v WHERE v.asset_version_id=r.target_runtime#>>'{world_host_revalidation,evaluation,asset_version_id}')))))
        OR NOT authority_planning_cli_lineage_reconciled(source_id)
        OR EXISTS(SELECT 1 FROM authority_lease_acquisition lease JOIN authority_attempt attempt USING(attempt_id) JOIN lineage USING(operation_id)
            WHERE lease.status='HELD' AND NOT (attempt.operation_id=child_id AND attempt.status='RUNNING'
                AND attempt.attempt_number=(SELECT max(active.attempt_number) FROM authority_attempt active WHERE active.operation_id=child_id)
                AND EXISTS(SELECT 1 FROM authority_operation executing WHERE executing.operation_id=child_id AND executing.status='RUNNING')))
    INTO admitted;
    RETURN NOT admitted;
END; $$""",
]
DOWNGRADE_STATEMENTS: list[str] = []
