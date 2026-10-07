from __future__ import annotations

MIGRATION_ID = '20261007_0170_world_host_revalidation'
DOWN_REVISION = '20261007_0169_world_agency_contract_successor'
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "append exact versioned successor evidence; preserve published identities, terminal history and settled accounting"

UPGRADE_STATEMENTS = [
    r"""CREATE OR REPLACE FUNCTION authority_world_contract_continuation_permitted(runtime_id TEXT, child_id TEXT, successor_generation JSONB)
RETURNS BOOLEAN LANGUAGE plpgsql AS $$
DECLARE mode TEXT; source_id TEXT; admitted BOOLEAN;
BEGIN
    SELECT command_payload #>> '{payload,repair_reason}' INTO mode FROM authority_operation WHERE operation_id=child_id;
    IF mode IS NULL OR mode NOT IN ('WORLD_AGENCY_CONTRACT_SUCCESSOR','WORLD_HOST_REVALIDATION_SUCCESSOR') THEN RETURN FALSE; END IF;
    SELECT source_operation_id INTO source_id FROM authority_story_planning_runtime_continuation WHERE continuation_id=runtime_id;
    SELECT EXISTS (
        SELECT 1 FROM authority_story_planning_runtime_continuation r
        JOIN authority_story_planning_generation source ON source.operation_id=r.source_operation_id
        JOIN authority_operation original ON original.operation_id=source.operation_id
        JOIN authority_operation child ON child.operation_id=child_id
        JOIN authority_operation registration ON registration.operation_id=r.registered_by_operation_id
        WHERE r.continuation_id=runtime_id AND r.source_command=original.command_payload->'payload'
          AND r.successor_command=child.command_payload->'payload'
          AND (r.successor_operation_id IS NULL OR r.successor_operation_id=child_id)
          AND registration.status='SUCCEEDED' AND registration.definition_name='story_planning.runtime_continuation.register' AND registration.definition_version='2.0.0'
          AND registration.project_id=original.project_id AND registration.workspace_id=original.workspace_id
          AND registration.actor_id=original.actor_id
          AND original.command_payload #>> '{payload,execution_contract_version}'=original.definition_version
          AND child.command_payload #>> '{payload,execution_contract_version}'='1.21.0'
          AND child.causation_operation_id=original.operation_id
          AND child.project_id=r.project_id AND child.workspace_id=r.workspace_id
          AND child.actor_id=original.actor_id
          AND original.project_id=r.project_id AND original.workspace_id=r.workspace_id
          AND source.project_id=r.project_id AND source.workspace_id=r.workspace_id AND source.book_id=r.book_id
          AND successor_generation->>'project_id'=source.project_id
          AND successor_generation->>'workspace_id'=source.workspace_id
          AND successor_generation->>'book_id'=source.book_id
          AND successor_generation->>'generator_operation_name'=source.generator_operation_name
          AND successor_generation->>'logical_key'=source.logical_key
          AND successor_generation->>'planning_scope'=source.planning_scope
          AND successor_generation->>'input_snapshot_hash'=source.input_snapshot_hash
          AND successor_generation->'input_snapshot'=source.input_snapshot
          AND (successor_generation->>'repair_number')::int=source.repair_number
          AND successor_generation->>'runtime_continuation_id'=r.continuation_id
          AND successor_generation->>'repair_reason'=mode
          AND successor_generation->>'candidate_asset_version_id' IS NULL
          AND successor_generation->>'repair_of_candidate_id' IS NULL
          AND successor_generation->>'repair_of_operation_id' IS NULL
          AND successor_generation->>'repair_result_asset_version_id' IS NULL
          AND child.command_payload #>> '{payload,book_id}'=r.book_id
          AND child.command_payload #>> '{payload,logical_key}'=source.logical_key
          AND child.command_payload #>> '{payload,generator_operation_name}'=source.generator_operation_name
          AND child.definition_name='story_planning.generate' AND child.definition_version='1.21.0'
          AND original.status IN ('FAILED_FINAL','DEAD_LETTER') AND source.candidate_asset_version_id IS NULL
          AND source.generator_operation_name='chapter_plan.generate'
          AND source.planning_scope='CHAPTER'
          AND original.command_payload #> '{payload,world_preparation_request}' IS NOT NULL
          AND original.command_payload #> '{payload,world_preparation_request}' <> 'null'::jsonb
          AND child.command_payload #> '{payload,world_preparation_request}'=original.command_payload #> '{payload,world_preparation_request}'
          AND (mode='WORLD_HOST_PROJECTION_SUCCESSOR' OR EXISTS (SELECT 1 FROM authority_external_effect known
              WHERE known.operation_id=original.operation_id AND known.status='SUCCEEDED'
                AND known.request_payload->>'stage' IN ('world_candidates.generate','world_candidates.evaluate')))
          AND source.repair_number BETWEEN 0 AND 4
          AND (child.command_payload #>> '{payload,repair_number}')::int=source.repair_number
          AND child.command_payload #>> '{payload,runtime_continuation_id}'=runtime_id
          AND EXISTS (SELECT 1 FROM authority_attempt a WHERE a.operation_id=original.operation_id
              AND a.attempt_number=(SELECT max(last.attempt_number) FROM authority_attempt last WHERE last.operation_id=original.operation_id)
              AND a.status='FAILED_FINAL')
          AND ((mode='WORLD_AGENCY_CONTRACT_SUCCESSOR' AND original.definition_version IN ('1.18.0','1.19.0')
              AND r.chain_depth=1 AND r.decision_evidence->>'changed_contract'='world-agency.v2'
              AND EXISTS (SELECT 1 FROM authority_attempt a WHERE a.operation_id=original.operation_id
                  AND a.attempt_number=(SELECT max(last.attempt_number) FROM authority_attempt last WHERE last.operation_id=original.operation_id)
                  AND COALESCE(a.result->>'error_code',a.error->>'error_code')='WORLD_PREPARATION_RESULT_INVALID')
              AND EXISTS (SELECT 1 FROM authority_operation_output_asset output JOIN authority_asset_version v USING(asset_version_id)
                  WHERE output.operation_id=original.operation_id AND v.content #>> '{contract,world_plan,disposition}'='BLOCKED'
                    AND (v.content #> '{contract,world_plan,candidate_futures}' @> '[{"rejection":{"code":"WORLD_CHARACTER_DECISION_BASIS_REQUIRED"}}]'::jsonb
                      OR v.content #> '{contract,world_plan,rejected_paths}' @> '[{"rejection":{"code":"WORLD_CHARACTER_DECISION_BASIS_REQUIRED"}}]'::jsonb))) OR (mode='WORLD_HOST_REVALIDATION_SUCCESSOR' AND original.definition_version='1.21.0'
              AND r.chain_depth=2 AND r.decision_evidence->>'host_revalidation'='world-host-revalidation.v1'
              AND r.target_runtime #>> '{world_host_revalidation,source_operation_id}'=original.operation_id
              AND r.target_runtime #>> '{world_host_revalidation,contract_version}'='world-host-revalidation.v1'
              AND r.target_runtime #>> '{world_host_revalidation,plan_digest}' ~ '^sha256:[0-9a-f]{64}$'
              AND EXISTS (SELECT 1 FROM authority_story_planning_runtime_continuation parent
                  WHERE parent.successor_operation_id=original.operation_id AND parent.chain_depth=1)
              AND EXISTS (SELECT 1 FROM authority_attempt a WHERE a.operation_id=original.operation_id
                  AND a.attempt_number=(SELECT max(last.attempt_number) FROM authority_attempt last WHERE last.operation_id=original.operation_id)
                  AND COALESCE(a.result->>'error_code',a.error->>'error_code')='WORLD_PREPARATION_RESULT_INVALID')
              AND EXISTS (SELECT 1 FROM authority_operation_output_asset output JOIN authority_asset_version v USING(asset_version_id)
                  WHERE output.operation_id=original.operation_id AND v.content #>> '{contract,world_plan,disposition}'='BLOCKED'
                    AND v.content #> '{contract,world_plan,rejected_paths}' @> '[{"rejection":{"code":"WORLD_PERCEPTION_ACTOR_INVALID"}}]'::jsonb)))
          AND NOT EXISTS (SELECT 1 FROM authority_book_production book WHERE book.project_id=r.project_id AND book.book_id=r.book_id
              AND (book.state IN ('ABORTED','COMPLETED','CANCELLED') OR EXISTS (
                  SELECT 1 FROM authority_story_creation_cancellation cancellation
                  WHERE cancellation.project_id=book.project_id AND book.stable_idempotency_key=cancellation.formation_run_id || ':production')))
    ) INTO admitted;
    IF NOT admitted THEN RETURN FALSE; END IF;
    WITH RECURSIVE lineage(operation_id) AS (
        SELECT source_id UNION SELECT neighbor.operation_id FROM lineage
        JOIN authority_operation anchor ON anchor.operation_id=lineage.operation_id
        JOIN authority_operation neighbor ON neighbor.causation_operation_id=anchor.operation_id OR neighbor.operation_id=anchor.causation_operation_id
        WHERE neighbor.definition_name='story_planning.generate' AND neighbor.project_id=anchor.project_id
    ) SELECT EXISTS (SELECT 1 FROM authority_external_effect effect JOIN lineage USING(operation_id)
        WHERE effect.status NOT IN ('SUCCEEDED','FAILED_FINAL','CANCELLED'))
        OR EXISTS (SELECT 1 FROM authority_budget_reservation budget JOIN lineage USING(operation_id) WHERE budget.status NOT IN ('SETTLED','RELEASED'))
        OR NOT authority_planning_cli_lineage_reconciled(source_id)
        OR EXISTS (SELECT 1 FROM authority_lease_acquisition lease JOIN authority_attempt attempt USING(attempt_id)
            JOIN lineage ON lineage.operation_id=attempt.operation_id WHERE lease.status='HELD'
              AND NOT (attempt.operation_id=child_id AND attempt.status='RUNNING'
                  AND attempt.attempt_number=(SELECT max(active.attempt_number) FROM authority_attempt active WHERE active.operation_id=child_id)
                  AND EXISTS (SELECT 1 FROM authority_operation executing WHERE executing.operation_id=child_id AND executing.status='RUNNING'))) INTO admitted;
    RETURN NOT admitted;
END; $$""",
]
DOWNGRADE_STATEMENTS: list[str] = []
