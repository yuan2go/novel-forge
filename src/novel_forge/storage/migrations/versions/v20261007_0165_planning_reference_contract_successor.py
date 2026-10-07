from __future__ import annotations

MIGRATION_ID = "20261007_0165_planning_reference_contract_successor"
DOWN_REVISION = "20261007_0164_realization_comparison_uncertainty"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "retain rejected Arc Context candidates and permit one versioned source-selector contract successor with unchanged repair and resource lineage"
UPGRADE_STATEMENTS = [
    "ALTER TABLE authority_story_planning_runtime_continuation DROP CONSTRAINT authority_story_planning_runtime_continuation_chain_depth_check",
    """ALTER TABLE authority_story_planning_runtime_continuation ADD CONSTRAINT authority_story_planning_runtime_continuation_chain_depth_check
        CHECK (chain_depth BETWEEN 1 AND 2 OR (chain_depth=3 AND (
            COALESCE(decision_evidence->>'projection_revalidation','')='world-direction-projection.v1' OR (
                COALESCE(decision_evidence->>'changed_contract','')='planning-host-source-selectors.v1'
                AND target_runtime#>>'{planning_reference_contract,contract_version}'='planning-reference-contract-successor.v1'))))""",
    "ALTER TABLE authority_story_planning_generation DROP CONSTRAINT authority_planning_repair_source_check",
    """ALTER TABLE authority_story_planning_generation ADD CONSTRAINT authority_planning_repair_source_check CHECK (
        (repair_number=0 AND repair_of_candidate_id IS NULL AND repair_of_operation_id IS NULL AND repair_result_asset_version_id IS NULL AND repair_reason IS NULL)
        OR (repair_number>0 AND repair_reason IS NOT NULL AND (
            (repair_of_candidate_id IS NOT NULL AND repair_of_operation_id IS NULL AND repair_result_asset_version_id IS NULL)
            OR (repair_of_candidate_id IS NULL AND repair_of_operation_id IS NOT NULL AND repair_result_asset_version_id IS NOT NULL AND repair_number<=2)))
        OR (repair_number BETWEEN 0 AND 2 AND repair_reason IN ('WORLD_AGENCY_CONTRACT_SUCCESSOR','WORLD_HOST_REVALIDATION_SUCCESSOR','WORLD_HOST_PROJECTION_SUCCESSOR','PLANNING_REFERENCE_CONTRACT_SUCCESSOR')
            AND repair_of_candidate_id IS NULL AND repair_of_operation_id IS NULL AND repair_result_asset_version_id IS NULL))""",
    """CREATE FUNCTION authority_planning_reference_successor_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.repair_reason='PLANNING_REFERENCE_CONTRACT_SUCCESSOR' AND NOT EXISTS (
            SELECT 1 FROM authority_story_planning_runtime_continuation continuation
            JOIN authority_story_planning_generation source ON source.operation_id=continuation.source_operation_id
            JOIN authority_operation parent ON parent.operation_id=source.operation_id
            JOIN authority_operation child ON child.operation_id=NEW.operation_id
            WHERE continuation.successor_operation_id=NEW.operation_id AND continuation.chain_depth=3
              AND continuation.project_id=NEW.project_id AND continuation.book_id=NEW.book_id
              AND source.status='REJECTED' AND parent.status='SUCCEEDED'
              AND source.generator_operation_name=NEW.generator_operation_name
              AND source.logical_key=NEW.logical_key AND source.input_snapshot_hash=NEW.input_snapshot_hash
              AND source.repair_number=NEW.repair_number
              AND continuation.decision_evidence->>'changed_contract'='planning-host-source-selectors.v1'
              AND child.definition_version='1.20.0'
              AND child.command_payload->'payload'=continuation.successor_command)
        THEN RAISE EXCEPTION 'Planning reference contract requires its exact rejected source and unchanged repair consumption'; END IF;
        RETURN NEW;
    END; $$""",
    "CREATE TRIGGER authority_planning_reference_successor_before_insert BEFORE INSERT ON authority_story_planning_generation FOR EACH ROW EXECUTE FUNCTION authority_planning_reference_successor_guard()",
]
DOWNGRADE_STATEMENTS: list[str] = []
