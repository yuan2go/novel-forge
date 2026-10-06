from __future__ import annotations

MIGRATION_ID = "20261006_0158_planning_capacity_causation"
DOWN_REVISION = "20261006_0157_creation_continuation_control"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Keep terminal capacity failures and admitted repair commands immutable; bind only their exact registered continuation and verified repair origin."

UPGRADE_STATEMENTS = [
    """
    CREATE OR REPLACE FUNCTION authority_planning_runtime_continuation_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP='DELETE' THEN
            RAISE EXCEPTION 'PLANNING_RUNTIME_CONTINUATION_IMMUTABLE' USING ERRCODE='check_violation';
        END IF;
        IF (to_jsonb(OLD)-'successor_operation_id') IS DISTINCT FROM (to_jsonb(NEW)-'successor_operation_id')
           OR (OLD.successor_operation_id IS NOT NULL AND OLD.successor_operation_id IS DISTINCT FROM NEW.successor_operation_id) THEN
            RAISE EXCEPTION 'PLANNING_RUNTIME_CONTINUATION_IMMUTABLE' USING ERRCODE='check_violation';
        END IF;
        IF NEW.successor_operation_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM authority_operation op
            WHERE op.operation_id=NEW.successor_operation_id AND op.project_id=NEW.project_id
              AND op.command_payload->'payload'=NEW.successor_command
              AND (op.causation_operation_id=NEW.source_operation_id OR (
                NEW.target_runtime #>> '{planning_capacity,version}'='planning-capacity-allocation.v1'
                AND NEW.successor_command->>'runtime_continuation_id'=NEW.continuation_id
                AND EXISTS (
                    SELECT 1 FROM authority_operation source
                    JOIN authority_operation_output_asset repair_output
                      ON repair_output.asset_version_id=NEW.source_command->>'repair_of_candidate_id'
                    JOIN authority_story_planning_generation repair
                      ON repair.operation_id=repair_output.operation_id AND repair.candidate_asset_version_id=repair_output.asset_version_id
                    WHERE source.operation_id=NEW.source_operation_id AND source.project_id=NEW.project_id
                      AND source.status IN ('FAILED_FINAL','DEAD_LETTER') AND source.command_payload->'payload'=NEW.source_command
                      AND repair.project_id=NEW.project_id AND repair.book_id=NEW.book_id
                      AND op.causation_operation_id=repair.operation_id
                      AND COALESCE((SELECT COALESCE(attempt.result->>'error_code',attempt.error->>'error_code')
                          FROM authority_attempt attempt WHERE attempt.operation_id=source.operation_id
                          ORDER BY attempt.attempt_number DESC LIMIT 1),'')='PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED'
                      AND NOT EXISTS(SELECT 1 FROM authority_external_effect effect WHERE effect.operation_id=source.operation_id)
                      AND NOT EXISTS(SELECT 1 FROM authority_budget_reservation reservation WHERE reservation.operation_id=source.operation_id)
                )
              ))
        ) THEN
            RAISE EXCEPTION 'PLANNING_RUNTIME_CONTINUATION_SUCCESSOR_INVALID' USING ERRCODE='check_violation';
        END IF;
        RETURN NEW;
    END; $$
    """,
]
DOWNGRADE_STATEMENTS: list[str] = []
