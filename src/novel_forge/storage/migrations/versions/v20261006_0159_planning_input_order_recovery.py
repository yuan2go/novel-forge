from __future__ import annotations

MIGRATION_ID = "20261006_0159_planning_input_order_recovery"
DOWN_REVISION = "20261006_0158_planning_capacity_lineage"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "preserve failed-final undispatched input-order failures; only native same-input same-counter runtime successors may proceed"
UPGRADE_STATEMENTS = [
    """CREATE OR REPLACE FUNCTION authority_planning_result_repair_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP='UPDATE' THEN
            IF ROW(OLD.repair_of_operation_id,OLD.repair_result_asset_version_id,OLD.runtime_continuation_id)
               IS DISTINCT FROM ROW(NEW.repair_of_operation_id,NEW.repair_result_asset_version_id,NEW.runtime_continuation_id) THEN
                RAISE EXCEPTION 'PLANNING_RESULT_REPAIR_IDENTITY_IMMUTABLE' USING ERRCODE='check_violation';
            END IF;
        ELSE
            IF NEW.runtime_continuation_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM authority_story_planning_runtime_continuation r
                JOIN authority_operation source ON source.operation_id=r.source_operation_id AND source.status IN ('CANCELLED','FAILED_FINAL')
                JOIN authority_story_planning_generation source_generation ON source_generation.operation_id=source.operation_id
                JOIN authority_operation child ON child.operation_id=NEW.operation_id
                JOIN authority_operation registration ON registration.operation_id=r.registered_by_operation_id
                WHERE r.continuation_id=NEW.runtime_continuation_id
                  AND registration.status='SUCCEEDED' AND registration.definition_name='story_planning.runtime_continuation.register'
                  AND r.project_id=NEW.project_id AND r.workspace_id=NEW.workspace_id AND r.book_id=NEW.book_id
                  AND r.source_command=source.command_payload->'payload' AND r.successor_command=child.command_payload->'payload'
                  AND child.causation_operation_id=source.operation_id
                  AND (r.successor_operation_id IS NULL OR r.successor_operation_id=child.operation_id)
                  AND source_generation.generator_operation_name=NEW.generator_operation_name
                  AND source_generation.logical_key=NEW.logical_key AND source_generation.input_snapshot_hash=NEW.input_snapshot_hash
                  AND source_generation.repair_number=NEW.repair_number
                  AND source_generation.repair_of_candidate_id IS NOT DISTINCT FROM NEW.repair_of_candidate_id
                  AND source_generation.repair_reason IS NOT DISTINCT FROM NEW.repair_reason
                  AND (source.status='CANCELLED' OR (
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
                  AND parent.candidate_asset_version_id IS NULL AND op.status='FAILED_FINAL'
                  AND NEW.repair_number=parent.repair_number+1
                  AND (child.causation_operation_id=parent.operation_id OR NEW.runtime_continuation_id IS NOT NULL)
                  AND source.asset_version_id=NEW.repair_result_asset_version_id
            ) THEN
                RAISE EXCEPTION 'PLANNING_RESULT_REPAIR_SOURCE_INVALID' USING ERRCODE='check_violation';
            END IF;
        END IF;
        RETURN NEW;
    END; $$""",
]
DOWNGRADE_STATEMENTS: list[str] = []
