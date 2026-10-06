from __future__ import annotations

MIGRATION_ID = "20261006_0150_creative_pack_admission"
DOWN_REVISION = "20261005_0149_zero_increment_chapter_outcome"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "append exact scoped admission or a successor Pack; retain prior approvals and snapshots"
UPGRADE_STATEMENTS = [
    """CREATE TABLE authority_capability_pack_validation_admission (
        admission_id TEXT PRIMARY KEY,
        compilation_id TEXT NOT NULL REFERENCES authority_capability_pack_compilation(compilation_id),
        compilation_hash TEXT NOT NULL,
        project_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        policy_snapshot JSONB NOT NULL,
        admission_scope JSONB NOT NULL,
        checks JSONB NOT NULL,
        actor_id TEXT NOT NULL,
        operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(compilation_id,project_id,book_id),
        CHECK (project_id<>'' AND book_id<>'' AND actor_id<>''),
        CHECK (admission_scope->'allowed_environments'='["validation"]'::jsonb)
    )""",
    """CREATE INDEX authority_capability_pack_validation_admission_operation_idx
        ON authority_capability_pack_validation_admission(operation_id)""",
    """CREATE TRIGGER authority_capability_pack_validation_admission_immutable
        BEFORE UPDATE OR DELETE ON authority_capability_pack_validation_admission
        FOR EACH ROW EXECUTE FUNCTION authority_capability_pack_immutable_guard()""",
]
DOWNGRADE_STATEMENTS: list[str] = []
