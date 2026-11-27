from __future__ import annotations

MIGRATION_ID = '20261007_0176_quality_correction_control'
DOWN_REVISION = '20261007_0175_canon_output_repair'
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "append exact versioned successor evidence; preserve published identities, terminal history and settled accounting"

UPGRADE_STATEMENTS = [
    r"""CREATE OR REPLACE FUNCTION authority_planning_result_repair_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP='UPDATE' THEN
            IF ROW(OLD.repair_of_operation_id,OLD.repair_result_asset_version_id,OLD.runtime_continuation_id)
               IS DISTINCT FROM ROW(NEW.repair_of_operation_id,NEW.repair_result_asset_version_id,NEW.runtime_continuation_id) THEN
                RAISE EXCEPTION 'PLANNING_RESULT_REPAIR_IDENTITY_IMMUTABLE' USING ERRCODE='check_violation';
            END IF;
        ELSE
            IF NEW.runtime_continuation_id IS NOT NULL
               AND NOT authority_world_contract_continuation_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))
               AND NOT EXISTS (
                SELECT 1 FROM authority_story_planning_runtime_continuation r
                JOIN authority_operation source ON source.operation_id=r.source_operation_id AND source.status IN ('CANCELLED','FAILED_FINAL','DEAD_LETTER')
                JOIN authority_story_planning_generation source_generation ON source_generation.operation_id=source.operation_id
                JOIN authority_operation child ON child.operation_id=NEW.operation_id
                JOIN authority_operation registration ON registration.operation_id=r.registered_by_operation_id
                WHERE r.continuation_id=NEW.runtime_continuation_id
                  AND registration.status='SUCCEEDED' AND registration.definition_name IN ('story_planning.runtime_continuation.register','story_planning.world_preparation.defer')
                  AND r.project_id=NEW.project_id AND r.workspace_id=NEW.workspace_id AND r.book_id=NEW.book_id
                  AND r.source_command=source.command_payload->'payload' AND r.successor_command=child.command_payload->'payload'
                  AND (child.causation_operation_id=source.operation_id OR (
                    r.target_runtime #>> '{planning_capacity,version}'='planning-capacity-allocation.v1'
                    AND EXISTS (
                      SELECT 1 FROM authority_operation_output_asset repair_output
                      JOIN authority_story_planning_generation repair
                        ON repair.operation_id=repair_output.operation_id
                        AND repair.candidate_asset_version_id=repair_output.asset_version_id
                      WHERE repair_output.asset_version_id=r.source_command->>'repair_of_candidate_id'
                        AND repair.project_id=NEW.project_id AND repair.workspace_id=NEW.workspace_id
                        AND repair.book_id=NEW.book_id
                        AND child.causation_operation_id=repair.operation_id
                    )
                  ))
                  AND (r.successor_operation_id IS NULL OR r.successor_operation_id=child.operation_id)
                  AND source_generation.generator_operation_name=NEW.generator_operation_name
                  AND source_generation.logical_key=NEW.logical_key AND source_generation.input_snapshot_hash=NEW.input_snapshot_hash
                  AND source_generation.repair_number=NEW.repair_number
                  AND source_generation.repair_of_candidate_id IS NOT DISTINCT FROM NEW.repair_of_candidate_id
                  AND source_generation.repair_reason IS NOT DISTINCT FROM NEW.repair_reason
                  AND ((registration.definition_name='story_planning.runtime_continuation.register' AND (source.status='CANCELLED' OR (
                    source.status IN ('FAILED_FINAL','DEAD_LETTER')
                    AND r.target_runtime #>> '{planning_capacity,version}'='planning-capacity-allocation.v1'
                    AND source_generation.candidate_asset_version_id IS NULL
                    AND r.successor_command->>'runtime_continuation_id'=r.continuation_id
                    AND COALESCE((SELECT COALESCE(a.result->>'error_code',a.error->>'error_code')
                        FROM authority_attempt a WHERE a.operation_id=source.operation_id
                        ORDER BY a.attempt_number DESC LIMIT 1),'')='PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED'
                    AND NOT EXISTS(SELECT 1 FROM authority_external_effect e WHERE e.operation_id=source.operation_id)
                    AND NOT EXISTS(SELECT 1 FROM authority_budget_reservation b WHERE b.operation_id=source.operation_id)
                  ) OR (
                    source_generation.repair_of_candidate_id IS NOT NULL
                    AND NOT EXISTS (SELECT 1 FROM authority_external_effect e WHERE e.operation_id=source.operation_id)
                    AND NOT EXISTS (SELECT 1 FROM authority_budget_reservation b WHERE b.operation_id=source.operation_id)
                    AND EXISTS (SELECT 1 FROM authority_attempt a WHERE a.operation_id=source.operation_id
                        AND a.attempt_number=(SELECT max(last.attempt_number) FROM authority_attempt last WHERE last.operation_id=source.operation_id)
                        AND a.status='FAILED_FINAL'
                        AND COALESCE(a.error->>'error_code',a.result->>'error_code')='NATIVE_PLANNING_REPAIR_SOURCE_INVALID')
                    AND EXISTS (SELECT 1 FROM authority_operation_output_asset output
                        JOIN authority_asset_version v USING(asset_version_id)
                        JOIN authority_asset asset ON asset.asset_id=v.asset_id
                        WHERE output.operation_id=registration.operation_id AND asset.asset_type='planning_runtime_continuation'
                          AND v.content->>'source_operation_id'=source.operation_id
                          AND v.content #>> '{source_preflight_failure,contract_version}'='planning-input-order-preflight.v1')
                  ))) OR (
                    registration.definition_name='story_planning.world_preparation.defer'
                    AND source_generation.project_id=NEW.project_id
                    AND source_generation.workspace_id=NEW.workspace_id
                    AND source_generation.book_id=NEW.book_id
                    AND source_generation.planning_scope=NEW.planning_scope
                    AND source.status IN ('FAILED_FINAL','DEAD_LETTER') AND source_generation.candidate_asset_version_id IS NULL
                    AND source.command_payload #> '{payload,world_preparation_request}' IS NOT NULL
                    AND EXISTS (SELECT 1 FROM authority_attempt a WHERE a.operation_id=source.operation_id
                        AND a.attempt_number=(SELECT max(last.attempt_number) FROM authority_attempt last WHERE last.operation_id=source.operation_id)
                        AND a.status='FAILED_FINAL'
                        AND COALESCE(a.error->>'error_code',a.result->>'error_code') IN ('WORLD_PREPARATION_RESULT_INVALID','WORLD_PREPARATION_BLOCKED'))
                    AND (SELECT count(*) FROM authority_external_effect e WHERE e.operation_id=source.operation_id)=2
                    AND (SELECT count(DISTINCT e.request_payload->>'stage') FROM authority_external_effect e
                        WHERE e.operation_id=source.operation_id AND e.status='SUCCEEDED'
                        AND e.request_payload->>'stage' IN ('world_candidates.generate','world_candidates.evaluate'))=2
                    AND (SELECT count(*) FROM authority_budget_reservation b WHERE b.operation_id=source.operation_id)=2
                    AND NOT EXISTS (SELECT 1 FROM authority_budget_reservation b WHERE b.operation_id=source.operation_id AND b.status<>'SETTLED')
                    AND NOT EXISTS (SELECT 1 FROM authority_lease_acquisition l JOIN authority_attempt a USING(attempt_id)
                        WHERE a.operation_id=source.operation_id AND l.status='HELD')
                    AND EXISTS (SELECT 1 FROM authority_operation_output_asset output
                        JOIN authority_asset_version v USING(asset_version_id)
                        JOIN authority_asset asset ON asset.asset_id=v.asset_id
                        WHERE output.operation_id=registration.operation_id AND asset.asset_type='narrative_governance_action'
                          AND asset.project_id=NEW.project_id
                          AND v.asset_version_id=r.decision_evidence #>> '{world_optional_action,asset_version_id}'
                          AND v.content_hash=r.decision_evidence #>> '{world_optional_action,content_hash}'
                          AND v.content #>> '{contract,book_id}'=NEW.book_id
                          AND v.content #>> '{contract,optional_preparation,contract_version}'='world-optional-preparation.v1'
                          AND v.content #>> '{contract,optional_preparation,status}'='NOT_RUN'
                          AND v.content #>> '{contract,world_plan,disposition}'='DEFER'
                          AND v.content #>> '{contract,world_plan,selected_candidate_id}'=''
                          AND v.content #> '{contract,world_plan,preparation_schedule}'='[]'::jsonb
                          AND v.content #> '{contract,fact_mutation_allowed}'='false'::jsonb
                          AND v.content #> '{contract,optional_preparation,policy_admission}'=r.decision_evidence->'policy_admission'
                          AND EXISTS (SELECT 1 FROM jsonb_array_elements(r.decision_evidence #> '{policy_admission,policy_snapshot,policy,execution_templates}') t
                              WHERE t->>'book_id'=NEW.book_id AND t->>'mode'='CREATIVE_VALIDATION'
                                AND t->>'version' IN ('creative-execution-template.v3','creative-execution-template.v4','creative-execution-template.v5','creative-execution-template.v6','creative-execution-template.v7','creative-execution-template.v8','creative-execution-template.v9','creative-execution-template.v10','creative-execution-template.v11')
                                AND t->>'world_future_preparation' IN ('OPTIONAL','DISABLED')
                                AND t->'require_literary_qualification'='false'::jsonb))
                  ))
                  AND source_generation.repair_of_operation_id IS NOT DISTINCT FROM NEW.repair_of_operation_id
                  AND source_generation.repair_result_asset_version_id IS NOT DISTINCT FROM NEW.repair_result_asset_version_id
            ) THEN
                RAISE EXCEPTION 'PLANNING_RUNTIME_CONTINUATION_GENERATION_INVALID' USING ERRCODE='check_violation';
            END IF;
            IF NEW.repair_of_operation_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM authority_story_planning_generation parent
                JOIN authority_operation op ON op.operation_id=parent.operation_id
                JOIN authority_operation child ON child.operation_id=NEW.operation_id
                JOIN authority_operation_output_asset source ON source.operation_id=parent.operation_id
                WHERE parent.operation_id=NEW.repair_of_operation_id
                  AND parent.project_id=NEW.project_id AND parent.workspace_id=NEW.workspace_id
                  AND parent.book_id=NEW.book_id AND parent.generator_operation_name=NEW.generator_operation_name
                  AND parent.logical_key=NEW.logical_key AND parent.input_snapshot_hash=NEW.input_snapshot_hash
                  AND parent.candidate_asset_version_id IS NULL AND (op.status='FAILED_FINAL' OR (op.status='DEAD_LETTER' AND NOT EXISTS (
                  SELECT 1 FROM authority_external_effect pending
                  WHERE pending.operation_id=parent.operation_id
                    AND pending.status NOT IN ('SUCCEEDED','FAILED_FINAL','CANCELLED')
              ) AND EXISTS (
                  SELECT 1 FROM authority_external_effect known
                  WHERE known.operation_id=parent.operation_id AND known.status='SUCCEEDED'
              )))
                  AND NEW.repair_number=parent.repair_number+1
                  AND (child.causation_operation_id=parent.operation_id OR EXISTS (
                    SELECT 1 FROM authority_story_planning_runtime_continuation continuation
                    JOIN authority_operation runtime_source ON runtime_source.operation_id=continuation.source_operation_id
                    WHERE continuation.continuation_id=NEW.runtime_continuation_id
                      AND continuation.project_id=NEW.project_id AND continuation.workspace_id=NEW.workspace_id
                      AND continuation.book_id=NEW.book_id
                      AND continuation.successor_command=child.command_payload->'payload'
                      AND continuation.source_command=runtime_source.command_payload->'payload'
                      AND continuation.source_command->>'repair_of_operation_id'=parent.operation_id
                      AND continuation.source_command->>'repair_result_asset_version_id'=NEW.repair_result_asset_version_id
                      AND (continuation.source_command->>'repair_number')::int=NEW.repair_number
                      AND (continuation.successor_operation_id IS NULL OR continuation.successor_operation_id=child.operation_id)
                      AND child.causation_operation_id=runtime_source.operation_id
                  ))
                  AND source.asset_version_id=NEW.repair_result_asset_version_id
            ) THEN
                RAISE EXCEPTION 'PLANNING_RESULT_REPAIR_SOURCE_INVALID' USING ERRCODE='check_violation';
            END IF;
        END IF;
        IF TG_OP='INSERT' AND NEW.repair_of_operation_id IS NOT NULL AND NEW.repair_number>2 AND NOT EXISTS (
            SELECT 1 FROM authority_runtime_policy_selection s
            JOIN authority_runtime_policy_version v USING(owner,project_id,policy_version)
            JOIN authority_operation policy ON policy.operation_id=v.created_by_operation_id
            JOIN LATERAL jsonb_array_elements(v.content->'execution_templates') t ON TRUE
            WHERE s.owner='PROVIDER_ROUTING' AND s.project_id=NEW.project_id AND policy.status='SUCCEEDED'
              AND t->>'book_id'=NEW.book_id AND t->>'version' IN ('creative-execution-template.v4','creative-execution-template.v5','creative-execution-template.v6','creative-execution-template.v7','creative-execution-template.v8','creative-execution-template.v9','creative-execution-template.v10','creative-execution-template.v11')
              AND t->>'mode'='CREATIVE_VALIDATION' AND t->'require_literary_qualification'='false'::jsonb
              AND t #>> '{repair_routing,version}'='native-repair-routing.v2'
              AND (t #>> '{repair_routing,max_same_route_repairs}')::int BETWEEN 1 AND 2
        ) THEN
            RAISE EXCEPTION 'PLANNING_STAGE_REPAIR_POLICY_REQUIRED' USING ERRCODE='check_violation';
        END IF;
        RETURN NEW;
    END; $$""",
]
DOWNGRADE_STATEMENTS: list[str] = []
