from __future__ import annotations

MIGRATION_ID = "20260913_0131_planning_result_recovery"
DOWN_REVISION = "20260912_0130_creative_experiment_budget"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = (
    "Retain failed Operations and repair lineage; append corrected linked generations."
)

UPGRADE_STATEMENTS = [
    "ALTER TABLE authority_story_planning_generation ADD COLUMN repair_of_operation_id TEXT REFERENCES authority_operation(operation_id)",
    "ALTER TABLE authority_story_planning_generation ADD COLUMN repair_result_asset_version_id TEXT REFERENCES authority_asset_version(asset_version_id)",
    "ALTER TABLE authority_story_planning_generation DROP CONSTRAINT authority_story_planning_generation_check",
    """
    ALTER TABLE authority_story_planning_generation ADD CONSTRAINT authority_planning_repair_source_check CHECK (
        (repair_number=0 AND repair_of_candidate_id IS NULL AND repair_of_operation_id IS NULL AND repair_result_asset_version_id IS NULL AND repair_reason IS NULL)
        OR (repair_number>0 AND repair_reason IS NOT NULL AND (
            (repair_of_candidate_id IS NOT NULL AND repair_of_operation_id IS NULL AND repair_result_asset_version_id IS NULL)
            OR (repair_of_candidate_id IS NULL AND repair_of_operation_id IS NOT NULL AND repair_result_asset_version_id IS NOT NULL AND repair_number<=2)
        ))
    )
    """,
    "CREATE UNIQUE INDEX authority_planning_result_repair_once_idx ON authority_story_planning_generation(repair_of_operation_id) WHERE repair_of_operation_id IS NOT NULL",
    "CREATE INDEX authority_planning_result_source_asset_idx ON authority_story_planning_generation(repair_result_asset_version_id) WHERE repair_result_asset_version_id IS NOT NULL",
    """
    CREATE FUNCTION authority_planning_result_repair_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
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
              AND parent.candidate_asset_version_id IS NULL AND op.status='FAILED_FINAL'
              AND NEW.repair_number=parent.repair_number+1
              AND child.causation_operation_id=parent.operation_id
              AND source.asset_version_id=NEW.repair_result_asset_version_id
        ) THEN
            RAISE EXCEPTION 'PLANNING_RESULT_REPAIR_SOURCE_INVALID' USING ERRCODE='check_violation';
        END IF;
        RETURN NEW;
    END; $$
    """,
    "CREATE TRIGGER authority_planning_result_repair_guard BEFORE INSERT OR UPDATE ON authority_story_planning_generation FOR EACH ROW EXECUTE FUNCTION authority_planning_result_repair_guard()",
]
