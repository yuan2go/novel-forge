from __future__ import annotations

MIGRATION_ID = '20261007_0172_failed_step_successor_v2'
DOWN_REVISION = '20261007_0171_world_projection_successor'
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "append exact versioned successor evidence; preserve published identities, terminal history and settled accounting"

UPGRADE_STATEMENTS = [
    r"""ALTER TABLE authority_saga_step_successor ADD COLUMN source_saga_snapshot JSONB""",
    r"""ALTER TABLE authority_saga_step_successor DROP CONSTRAINT authority_saga_step_successor_contract_version_check""",
    r"""ALTER TABLE authority_saga_step_successor ADD CONSTRAINT authority_saga_step_successor_contract_version_check CHECK ((contract_version='kernel-failed-step-successor.v1' AND source_saga_snapshot IS NULL) OR (contract_version='kernel-failed-step-successor.v2' AND source_saga_snapshot IS NOT NULL AND jsonb_typeof(source_saga_snapshot)='object' AND source_saga_snapshot->>'saga_id' IS NOT DISTINCT FROM saga_id))""",
    r"""CREATE TRIGGER authority_saga_step_successor_immutable BEFORE UPDATE OR DELETE ON authority_saga_step_successor FOR EACH ROW EXECUTE FUNCTION novel_forge_reject_immutable_mutation()""",
]
DOWNGRADE_STATEMENTS: list[str] = []
