from __future__ import annotations

MIGRATION_ID = "20261007_0162_world_projection_successor"
DOWN_REVISION = "20261007_0161_world_host_revalidation"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Retain the zero-dispatch public World projection failure and append one accounted native successor without increasing Provider or content repair allowances."

UPGRADE_STATEMENTS = [
    "ALTER TABLE authority_story_planning_runtime_continuation DROP CONSTRAINT authority_story_planning_runtime_continuation_chain_depth_check",
    "ALTER TABLE authority_story_planning_runtime_continuation ADD CONSTRAINT authority_story_planning_runtime_continuation_chain_depth_check CHECK (chain_depth BETWEEN 1 AND 2 OR (chain_depth=3 AND COALESCE(decision_evidence->>'projection_revalidation','')='world-direction-projection.v1'))",
    "ALTER TABLE authority_story_planning_generation DROP CONSTRAINT authority_planning_repair_source_check",
    """ALTER TABLE authority_story_planning_generation ADD CONSTRAINT authority_planning_repair_source_check CHECK (
        (repair_number=0 AND repair_of_candidate_id IS NULL AND repair_of_operation_id IS NULL AND repair_result_asset_version_id IS NULL AND repair_reason IS NULL)
        OR (repair_number>0 AND repair_reason IS NOT NULL AND (
            (repair_of_candidate_id IS NOT NULL AND repair_of_operation_id IS NULL AND repair_result_asset_version_id IS NULL)
            OR (repair_of_candidate_id IS NULL AND repair_of_operation_id IS NOT NULL AND repair_result_asset_version_id IS NOT NULL AND repair_number<=2)))
        OR (repair_number BETWEEN 0 AND 2 AND repair_reason IN ('WORLD_AGENCY_CONTRACT_SUCCESSOR','WORLD_HOST_REVALIDATION_SUCCESSOR','WORLD_HOST_PROJECTION_SUCCESSOR')
            AND repair_of_candidate_id IS NULL AND repair_of_operation_id IS NULL AND repair_result_asset_version_id IS NULL))""",
    """CREATE FUNCTION authority_world_projection_successor_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.repair_reason='WORLD_HOST_PROJECTION_SUCCESSOR' AND NOT EXISTS (
            SELECT 1 FROM authority_story_planning_runtime_continuation continuation
            JOIN authority_story_planning_generation source ON source.operation_id=continuation.source_operation_id
            JOIN authority_operation source_op ON source_op.operation_id=source.operation_id
            JOIN authority_operation child ON child.operation_id=NEW.operation_id
            JOIN authority_story_planning_runtime_continuation parent ON parent.successor_operation_id=source.operation_id
            WHERE continuation.project_id=NEW.project_id AND continuation.workspace_id=NEW.workspace_id AND continuation.book_id=NEW.book_id
                AND continuation.successor_command=child.command_payload->'payload' AND child.causation_operation_id=source.operation_id
                AND child.definition_version='1.19.0' AND source_op.definition_version='1.19.0'
                AND source_op.status='FAILED_FINAL' AND source.candidate_asset_version_id IS NULL
                AND source.repair_reason='WORLD_HOST_REVALIDATION_SUCCESSOR' AND continuation.chain_depth=3 AND parent.chain_depth=2
                AND continuation.target_runtime->'world_host_revalidation'=parent.target_runtime->'world_host_revalidation'
                AND continuation.target_runtime->'pack_snapshot'=parent.target_runtime->'pack_snapshot'
                AND continuation.decision_evidence->>'projection_revalidation'='world-direction-projection.v1'
                AND NEW.generator_operation_name='chapter_plan.generate' AND source.generator_operation_name=NEW.generator_operation_name
                AND source.logical_key=NEW.logical_key AND source.input_snapshot_hash=NEW.input_snapshot_hash AND source.repair_number=NEW.repair_number
                AND EXISTS(SELECT 1 FROM authority_attempt attempt WHERE attempt.operation_id=source.operation_id
                    AND attempt.result->>'error_code'='PROGRAMMING_BUG' AND attempt.result->>'error_message'=$msg$'frozen_source'$msg$)
                AND NOT EXISTS(SELECT 1 FROM authority_external_effect effect WHERE effect.operation_id=source.operation_id)
                AND NOT EXISTS(SELECT 1 FROM authority_budget_reservation reservation WHERE reservation.operation_id=source.operation_id)
                AND NOT EXISTS(SELECT 1 FROM authority_book_production book WHERE book.project_id=NEW.project_id AND book.book_id=NEW.book_id AND book.state='ABORTED')
        ) THEN
            RAISE EXCEPTION 'WORLD_HOST_PROJECTION_SUCCESSOR_INVALID' USING ERRCODE='check_violation';
        END IF;
        RETURN NEW;
    END; $$""",
    "CREATE TRIGGER authority_world_projection_successor_guard BEFORE INSERT ON authority_story_planning_generation FOR EACH ROW EXECUTE FUNCTION authority_world_projection_successor_guard()",
]
DOWNGRADE_STATEMENTS: list[str] = []
