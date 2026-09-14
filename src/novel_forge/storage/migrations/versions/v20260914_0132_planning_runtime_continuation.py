from __future__ import annotations

MIGRATION_ID = "20260914_0132_planning_runtime_continuation"
DOWN_REVISION = "20260913_0131_planning_result_recovery"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = "Retain cancelled source operations and immutable continuation approvals; append only lawful successor evidence."

UPGRADE_STATEMENTS = [
    """
    CREATE TABLE authority_story_planning_runtime_continuation (
        continuation_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        workspace_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        source_operation_id TEXT NOT NULL UNIQUE REFERENCES authority_operation(operation_id),
        source_evidence_asset_version_id TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        registered_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        successor_operation_id TEXT UNIQUE REFERENCES authority_operation(operation_id),
        source_command JSONB NOT NULL CHECK(jsonb_typeof(source_command)='object'),
        successor_command JSONB NOT NULL CHECK(jsonb_typeof(successor_command)='object'),
        target_runtime JSONB NOT NULL CHECK(jsonb_typeof(target_runtime)='object'),
        decision_evidence JSONB NOT NULL CHECK(jsonb_typeof(decision_evidence)='object'),
        source_release_sha TEXT NOT NULL CHECK(length(source_release_sha)=40),
        target_release_sha TEXT NOT NULL CHECK(length(target_release_sha)=40),
        chain_depth INTEGER NOT NULL CHECK(chain_depth BETWEEN 1 AND 2),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        FOREIGN KEY(project_id, workspace_id, book_id) REFERENCES authority_book(project_id, workspace_id, book_id)
    )
    """,
    "CREATE INDEX authority_planning_continuation_scope_idx ON authority_story_planning_runtime_continuation(project_id,workspace_id,book_id)",
    "CREATE INDEX authority_planning_continuation_evidence_idx ON authority_story_planning_runtime_continuation(source_evidence_asset_version_id)",
    "CREATE INDEX authority_planning_continuation_registration_idx ON authority_story_planning_runtime_continuation(registered_by_operation_id)",
    """
    CREATE FUNCTION authority_planning_runtime_continuation_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
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
              AND op.causation_operation_id=NEW.source_operation_id
              AND op.command_payload->'payload'=NEW.successor_command
        ) THEN
            RAISE EXCEPTION 'PLANNING_RUNTIME_CONTINUATION_SUCCESSOR_INVALID' USING ERRCODE='check_violation';
        END IF;
        RETURN NEW;
    END; $$
    """,
    "CREATE TRIGGER authority_planning_runtime_continuation_guard BEFORE UPDATE OR DELETE ON authority_story_planning_runtime_continuation FOR EACH ROW EXECUTE FUNCTION authority_planning_runtime_continuation_guard()",
]
