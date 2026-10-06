from __future__ import annotations

MIGRATION_ID = "20261007_0161_world_host_revalidation"
DOWN_REVISION = "20261007_0160_world_agency_contract_successor"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Append one accounted native host revalidation successor reusing known settled World results; retain the failed task and its repair consumption."

UPGRADE_STATEMENTS = [
    "ALTER TABLE authority_story_planning_generation DROP CONSTRAINT authority_planning_repair_source_check",
    """
    ALTER TABLE authority_story_planning_generation ADD CONSTRAINT authority_planning_repair_source_check CHECK (
        (repair_number=0 AND repair_of_candidate_id IS NULL AND repair_of_operation_id IS NULL AND repair_result_asset_version_id IS NULL AND repair_reason IS NULL)
        OR (repair_number>0 AND repair_reason IS NOT NULL AND (
            (repair_of_candidate_id IS NOT NULL AND repair_of_operation_id IS NULL AND repair_result_asset_version_id IS NULL)
            OR (repair_of_candidate_id IS NULL AND repair_of_operation_id IS NOT NULL AND repair_result_asset_version_id IS NOT NULL AND repair_number<=2)
        ))
        OR (repair_number BETWEEN 0 AND 2 AND repair_reason IN ('WORLD_AGENCY_CONTRACT_SUCCESSOR','WORLD_HOST_REVALIDATION_SUCCESSOR')
            AND repair_of_candidate_id IS NULL AND repair_of_operation_id IS NULL AND repair_result_asset_version_id IS NULL)
    )
    """,
    """
    CREATE FUNCTION authority_world_host_revalidation_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.repair_reason='WORLD_HOST_REVALIDATION_SUCCESSOR' AND NOT EXISTS (
            SELECT 1 FROM authority_story_planning_runtime_continuation continuation
            JOIN authority_story_planning_generation source ON source.operation_id=continuation.source_operation_id
            JOIN authority_operation source_op ON source_op.operation_id=source.operation_id
            JOIN authority_operation child ON child.operation_id=NEW.operation_id
            JOIN authority_story_planning_runtime_continuation parent ON parent.successor_operation_id=source.operation_id
            WHERE continuation.project_id=NEW.project_id AND continuation.workspace_id=NEW.workspace_id
                AND continuation.book_id=NEW.book_id AND continuation.successor_command=child.command_payload->'payload'
                AND child.causation_operation_id=source.operation_id
                AND child.definition_version='1.19.0' AND source_op.definition_version='1.19.0'
                AND source_op.status IN ('FAILED_FINAL','DEAD_LETTER') AND source.candidate_asset_version_id IS NULL
                AND continuation.chain_depth=2 AND parent.chain_depth=1
                AND NEW.generator_operation_name='chapter_plan.generate'
                AND source.generator_operation_name=NEW.generator_operation_name AND source.logical_key=NEW.logical_key
                AND source.input_snapshot_hash=NEW.input_snapshot_hash AND source.repair_number=NEW.repair_number
                AND continuation.decision_evidence->>'host_revalidation'='world-host-revalidation.v1'
                AND continuation.target_runtime#>>'{world_host_revalidation,source_operation_id}'=source.operation_id
                AND continuation.target_runtime#>>'{world_host_revalidation,contract_version}'='world-host-revalidation.v1'
                AND continuation.target_runtime#>>'{world_host_revalidation,plan_digest}' LIKE 'sha256:%'
                AND NOT EXISTS (SELECT 1 FROM authority_external_effect effect WHERE effect.operation_id=source.operation_id
                    AND effect.status NOT IN ('SUCCEEDED','FAILED_FINAL','CANCELLED'))
                AND NOT EXISTS (SELECT 1 FROM authority_budget_reservation reservation WHERE reservation.operation_id=source.operation_id
                    AND reservation.status NOT IN ('SETTLED','RELEASED'))
                AND NOT EXISTS (SELECT 1 FROM authority_book_production book WHERE book.project_id=NEW.project_id AND book.book_id=NEW.book_id AND book.state='ABORTED')
        ) THEN
            RAISE EXCEPTION 'WORLD_HOST_REVALIDATION_SUCCESSOR_INVALID' USING ERRCODE='check_violation';
        END IF;
        RETURN NEW;
    END; $$
    """,
    "CREATE TRIGGER authority_world_host_revalidation_guard BEFORE INSERT ON authority_story_planning_generation FOR EACH ROW EXECUTE FUNCTION authority_world_host_revalidation_guard()",
]
DOWNGRADE_STATEMENTS: list[str] = []
