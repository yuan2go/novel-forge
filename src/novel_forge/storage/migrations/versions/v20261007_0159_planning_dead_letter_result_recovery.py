from __future__ import annotations

MIGRATION_ID = "20261007_0159_planning_dead_letter_result_recovery"
DOWN_REVISION = "20261006_0158_planning_capacity_causation"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Preserve failed and dead-letter terminal history; permit only an exact bounded Planning repair with retained known effects and no unresolved outcome."

UPGRADE_STATEMENTS = [
    """
    CREATE OR REPLACE FUNCTION authority_planning_result_repair_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP='UPDATE' THEN
            IF ROW(OLD.repair_of_operation_id, OLD.repair_result_asset_version_id)
               IS DISTINCT FROM ROW(NEW.repair_of_operation_id, NEW.repair_result_asset_version_id) THEN
                RAISE EXCEPTION 'PLANNING_RESULT_REPAIR_IDENTITY_IMMUTABLE' USING ERRCODE='check_violation';
            END IF;
        ELSIF NEW.repair_of_operation_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM authority_story_planning_generation parent
            JOIN authority_operation op ON op.operation_id=parent.operation_id
            JOIN authority_operation child ON child.operation_id=NEW.operation_id
            JOIN authority_operation_output_asset source ON source.operation_id=parent.operation_id
            WHERE parent.operation_id=NEW.repair_of_operation_id
              AND parent.project_id=NEW.project_id AND parent.workspace_id=NEW.workspace_id
              AND parent.book_id=NEW.book_id AND parent.generator_operation_name=NEW.generator_operation_name
              AND parent.logical_key=NEW.logical_key AND parent.input_snapshot_hash=NEW.input_snapshot_hash
              AND parent.candidate_asset_version_id IS NULL
              AND (op.status='FAILED_FINAL' OR (op.status='DEAD_LETTER' AND NOT EXISTS (
                  SELECT 1 FROM authority_external_effect pending
                  WHERE pending.operation_id=parent.operation_id
                    AND pending.status NOT IN ('SUCCEEDED','FAILED_FINAL','CANCELLED')
              ) AND EXISTS (
                  SELECT 1 FROM authority_external_effect known
                  WHERE known.operation_id=parent.operation_id AND known.status='SUCCEEDED'
              )))
              AND NEW.repair_number=parent.repair_number+1
              AND child.causation_operation_id=parent.operation_id
              AND source.asset_version_id=NEW.repair_result_asset_version_id
        ) THEN
            RAISE EXCEPTION 'PLANNING_RESULT_REPAIR_SOURCE_INVALID' USING ERRCODE='check_violation';
        END IF;
        RETURN NEW;
    END; $$
    """,
]
