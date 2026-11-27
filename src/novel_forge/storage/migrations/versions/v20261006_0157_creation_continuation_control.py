from __future__ import annotations

MIGRATION_ID = "20261006_0157_creation_continuation_control"
DOWN_REVISION = "20261006_0156_resource_journal_indexes"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Preserve the original creation cancellation and reconcile child owners; never delete the intent to restart a cancelled work."
UPGRADE_STATEMENTS = [
    """CREATE TABLE authority_story_creation_cancellation (
        formation_run_id TEXT PRIMARY KEY REFERENCES authority_story_formation_run(formation_run_id),
        operation_id TEXT NOT NULL UNIQUE REFERENCES authority_operation(operation_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        actor_id TEXT NOT NULL,
        frozen_input_digest TEXT NOT NULL,
        reason TEXT NOT NULL CHECK(length(trim(reason))>0),
        contract_version TEXT NOT NULL CHECK(contract_version='creation-cancellation.v1'),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    """CREATE TRIGGER authority_creation_cancellation_immutable BEFORE UPDATE OR DELETE
        ON authority_story_creation_cancellation FOR EACH ROW EXECUTE FUNCTION novel_forge_reject_immutable_mutation()""",
    "ALTER TABLE authority_recovery_command DROP CONSTRAINT authority_recovery_command_recovery_action_check",
    """ALTER TABLE authority_recovery_command ADD CONSTRAINT authority_recovery_command_recovery_action_check CHECK
        (recovery_action IN ('READY_FOR_RETRY','LEASE_TAKEOVER_VISIBLE','RECONCILIATION_DISPATCHED','GATE_RESUMED','ALREADY_COMPLETE','PRE_SEND_CHECKPOINT_RECONCILED'))""",
    "CREATE INDEX authority_creation_cancellation_project_idx ON authority_story_creation_cancellation(project_id)",
]
DOWNGRADE_STATEMENTS: list[str] = []
