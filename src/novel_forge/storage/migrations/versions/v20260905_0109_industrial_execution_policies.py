from __future__ import annotations


MIGRATION_ID = "20260905_0109_industrial_execution_policies"
DOWN_REVISION = "20260903_0108_context_governance_projection"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = "append successor policy versions; preserve all frozen execution bindings"


UPGRADE_STATEMENTS = [
    """
    CREATE TABLE authority_runtime_policy_version (
        owner TEXT NOT NULL CHECK (owner IN ('CHAPTER_GROUP_EXECUTION', 'READER_PROXY')),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        policy_version TEXT NOT NULL CHECK (policy_version <> ''),
        content JSONB NOT NULL CHECK (jsonb_typeof(content) = 'object'),
        content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
        actor_id TEXT NOT NULL,
        created_by_operation_id TEXT REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY(owner, project_id, policy_version),
        CHECK (content->>'policy_version' = policy_version)
    )
    """,
    """
    CREATE TABLE authority_runtime_policy_selection (
        owner TEXT NOT NULL,
        project_id TEXT NOT NULL,
        policy_version TEXT NOT NULL,
        selected_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        PRIMARY KEY(owner, project_id),
        FOREIGN KEY(owner, project_id, policy_version)
            REFERENCES authority_runtime_policy_version(owner, project_id, policy_version)
    )
    """,
    """
    CREATE TABLE authority_runtime_policy_binding (
        owner TEXT NOT NULL,
        project_id TEXT NOT NULL,
        subject_id TEXT NOT NULL CHECK (subject_id <> ''),
        policy_version TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY(owner, project_id, subject_id),
        FOREIGN KEY(owner, project_id, policy_version)
            REFERENCES authority_runtime_policy_version(owner, project_id, policy_version)
    )
    """,
    """
    CREATE FUNCTION authority_runtime_policy_immutable() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'runtime policy versions and bindings are immutable'
            USING ERRCODE='23514';
    END;
    $$
    """,
    """
    CREATE TRIGGER authority_runtime_policy_version_immutable
    BEFORE UPDATE OR DELETE ON authority_runtime_policy_version
    FOR EACH ROW EXECUTE FUNCTION authority_runtime_policy_immutable()
    """,
    """
    CREATE TRIGGER authority_runtime_policy_binding_immutable
    BEFORE UPDATE OR DELETE ON authority_runtime_policy_binding
    FOR EACH ROW EXECUTE FUNCTION authority_runtime_policy_immutable()
    """,
    """
    DO $$
    DECLARE range_constraint TEXT;
    BEGIN
        SELECT conname INTO STRICT range_constraint FROM pg_constraint
        WHERE conrelid='authority_chapter_group_production'::regclass
          AND contype='c'
          AND pg_get_constraintdef(oid) LIKE '%chapter_end - chapter_start%';
        EXECUTE format(
            'ALTER TABLE authority_chapter_group_production DROP CONSTRAINT %I',
            range_constraint
        );
    END;
    $$
    """,
    """
    ALTER TABLE authority_chapter_group_production
    ADD COLUMN execution_policy_snapshot JSONB
        CHECK (execution_policy_snapshot IS NULL
               OR (jsonb_typeof(execution_policy_snapshot) = 'object'
                   AND execution_policy_snapshot->>'owner' = 'CHAPTER_GROUP_EXECUTION'
                   AND execution_policy_snapshot->>'project_id' = project_id
                   AND execution_policy_snapshot->>'subject_id' = book_run_id
                   AND chapter_end - chapter_start + 1 <=
                       (execution_policy_snapshot->'policy'->>'maximum_chapters')::integer))
    """,
    """
    CREATE TRIGGER authority_chapter_group_policy_immutable
    BEFORE UPDATE OF execution_policy_snapshot ON authority_chapter_group_production
    FOR EACH ROW
    WHEN (OLD.execution_policy_snapshot IS DISTINCT FROM NEW.execution_policy_snapshot)
    EXECUTE FUNCTION authority_runtime_policy_immutable()
    """,
]


def upgrade(connection) -> None:
    with connection.cursor() as cursor:
        for statement in UPGRADE_STATEMENTS:
            cursor.execute(statement)
