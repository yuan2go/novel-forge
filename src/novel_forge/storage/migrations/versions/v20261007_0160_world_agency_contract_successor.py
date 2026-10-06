from __future__ import annotations

MIGRATION_ID = "20261007_0160_world_agency_contract_successor"
DOWN_REVISION = "20261007_0159_planning_dead_letter_result_recovery"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Append exact World agency contract successors while preserving frozen failed Operations, content repair counts and accounted effects."

UPGRADE_STATEMENTS = [
    "ALTER TABLE authority_story_planning_generation DROP CONSTRAINT authority_planning_repair_source_check",
    """
    ALTER TABLE authority_story_planning_generation ADD CONSTRAINT authority_planning_repair_source_check CHECK (
        (repair_number=0 AND repair_of_candidate_id IS NULL AND repair_of_operation_id IS NULL AND repair_result_asset_version_id IS NULL AND repair_reason IS NULL)
        OR (repair_number>0 AND repair_reason IS NOT NULL AND (
            (repair_of_candidate_id IS NOT NULL AND repair_of_operation_id IS NULL AND repair_result_asset_version_id IS NULL)
            OR (repair_of_candidate_id IS NULL AND repair_of_operation_id IS NOT NULL AND repair_result_asset_version_id IS NOT NULL AND repair_number<=2)
        ))
        OR (repair_number BETWEEN 0 AND 2 AND repair_reason='WORLD_AGENCY_CONTRACT_SUCCESSOR'
            AND repair_of_candidate_id IS NULL AND repair_of_operation_id IS NULL AND repair_result_asset_version_id IS NULL)
    )
    """,
    """
    CREATE FUNCTION authority_world_agency_successor_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.repair_reason='WORLD_AGENCY_CONTRACT_SUCCESSOR' AND NOT EXISTS (
            SELECT 1 FROM authority_story_planning_runtime_continuation continuation
            JOIN authority_story_planning_generation source ON source.operation_id=continuation.source_operation_id
            JOIN authority_operation source_op ON source_op.operation_id=source.operation_id
            JOIN authority_operation child ON child.operation_id=NEW.operation_id
            WHERE continuation.project_id=NEW.project_id AND continuation.workspace_id=NEW.workspace_id
                AND continuation.book_id=NEW.book_id AND continuation.successor_command=child.command_payload->'payload'
                AND child.causation_operation_id=source.operation_id
                AND child.definition_version='1.19.0' AND source_op.definition_version='1.18.0'
                AND source_op.status IN ('FAILED_FINAL','DEAD_LETTER')
                AND NEW.generator_operation_name='chapter_plan.generate'
                AND source.generator_operation_name=NEW.generator_operation_name AND source.logical_key=NEW.logical_key
                AND source.input_snapshot_hash=NEW.input_snapshot_hash AND source.repair_number=NEW.repair_number
                AND continuation.decision_evidence->>'changed_contract'='world-agency.v2'
                AND NOT EXISTS (SELECT 1 FROM authority_external_effect effect WHERE effect.operation_id=source.operation_id
                    AND effect.status NOT IN ('SUCCEEDED','FAILED_FINAL','CANCELLED'))
                AND NOT EXISTS (SELECT 1 FROM authority_budget_reservation reservation WHERE reservation.operation_id=source.operation_id
                    AND reservation.status NOT IN ('SETTLED','RELEASED'))
        ) THEN
            RAISE EXCEPTION 'WORLD_AGENCY_CONTRACT_SUCCESSOR_INVALID' USING ERRCODE='check_violation';
        END IF;
        RETURN NEW;
    END; $$
    """,
    "CREATE TRIGGER authority_world_agency_successor_guard BEFORE INSERT ON authority_story_planning_generation FOR EACH ROW EXECUTE FUNCTION authority_world_agency_successor_guard()",
]
DOWNGRADE_STATEMENTS: list[str] = []
