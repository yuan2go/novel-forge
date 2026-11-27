from __future__ import annotations

MIGRATION_ID = "20260713_0008_authority_schema_recovery"
DOWN_REVISION = "20260712_0007_postgres_command_kernel_authority"

OPERATION_STATES = (
    "ADMITTED",
    "WAITING_APPROVAL",
    "READY",
    "EXECUTING",
    "WAITING_CHILDREN",
    "WAITING_EXTERNAL_RESULT",
    "WAITING_GATE",
    "FAILED_RETRYABLE",
    "FAILED_FINAL",
    "CANCELLATION_REQUESTED",
    "RECONCILIATION_REQUIRED",
    "COMPENSATION_REQUIRED",
    "COMPENSATING",
    "COMPENSATED",
    "COMPENSATION_FAILED",
    "SUCCEEDED",
    "CANCELLED",
    "DEAD_LETTER",
)


def _sql_values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


UPGRADE_STATEMENTS = [
    f"""
    ALTER TABLE authority_operation
    ADD CONSTRAINT authority_operation_status_check
    CHECK (status IN ({_sql_values(OPERATION_STATES)}))
    """,
    """
    ALTER TABLE authority_operation
    ADD CONSTRAINT authority_operation_parent_fk
    FOREIGN KEY (parent_operation_id)
    REFERENCES authority_operation(operation_id)
    DEFERRABLE INITIALLY DEFERRED
    """,
    """
    ALTER TABLE authority_operation
    ADD CONSTRAINT authority_operation_root_fk
    FOREIGN KEY (root_operation_id)
    REFERENCES authority_operation(operation_id)
    DEFERRABLE INITIALLY DEFERRED
    """,
    """
    ALTER TABLE authority_operation
    ADD CONSTRAINT authority_operation_causation_fk
    FOREIGN KEY (causation_operation_id)
    REFERENCES authority_operation(operation_id)
    DEFERRABLE INITIALLY DEFERRED
    """,
    """
    ALTER TABLE authority_operation_dependency
    ADD CONSTRAINT authority_operation_dependency_not_self
    CHECK (operation_id <> depends_on_operation_id)
    """,
    """
    CREATE OR REPLACE FUNCTION authority_validate_operation_scope()
    RETURNS TRIGGER
    LANGUAGE plpgsql
    AS $$
    DECLARE
        referenced_project_id TEXT;
    BEGIN
        IF NEW.parent_operation_id IS NOT NULL THEN
            SELECT project_id
            INTO referenced_project_id
            FROM authority_operation
            WHERE operation_id = NEW.parent_operation_id;
            IF FOUND AND referenced_project_id <> NEW.project_id THEN
                RAISE EXCEPTION 'parent operation belongs to another project'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'authority_operation_parent_project_check';
            END IF;
        END IF;

        IF NEW.root_operation_id <> NEW.operation_id THEN
            SELECT project_id
            INTO referenced_project_id
            FROM authority_operation
            WHERE operation_id = NEW.root_operation_id;
            IF FOUND AND referenced_project_id <> NEW.project_id THEN
                RAISE EXCEPTION 'root operation belongs to another project'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'authority_operation_root_project_check';
            END IF;
        END IF;

        IF NEW.causation_operation_id IS NOT NULL THEN
            SELECT project_id
            INTO referenced_project_id
            FROM authority_operation
            WHERE operation_id = NEW.causation_operation_id;
            IF FOUND AND referenced_project_id <> NEW.project_id THEN
                RAISE EXCEPTION 'causation operation belongs to another project'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'authority_operation_causation_project_check';
            END IF;
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE TRIGGER authority_operation_scope_guard
    BEFORE INSERT OR UPDATE OF project_id, parent_operation_id, root_operation_id, causation_operation_id
    ON authority_operation
    FOR EACH ROW
    EXECUTE FUNCTION authority_validate_operation_scope()
    """,
    """
    CREATE OR REPLACE FUNCTION authority_validate_operation_dependency()
    RETURNS TRIGGER
    LANGUAGE plpgsql
    AS $$
    DECLARE
        operation_project_id TEXT;
        dependency_project_id TEXT;
    BEGIN
        SELECT project_id
        INTO operation_project_id
        FROM authority_operation
        WHERE operation_id = NEW.operation_id;

        SELECT project_id
        INTO dependency_project_id
        FROM authority_operation
        WHERE operation_id = NEW.depends_on_operation_id;

        IF operation_project_id IS NOT NULL
           AND dependency_project_id IS NOT NULL
           AND operation_project_id <> dependency_project_id THEN
            RAISE EXCEPTION 'operation dependency crosses project boundary'
                USING ERRCODE = '23514',
                      CONSTRAINT = 'authority_operation_dependency_project_check';
        END IF;

        IF EXISTS (
            WITH RECURSIVE dependency_path(operation_id) AS (
                SELECT depends_on_operation_id
                FROM authority_operation_dependency
                WHERE operation_id = NEW.depends_on_operation_id
                UNION
                SELECT dependency.depends_on_operation_id
                FROM authority_operation_dependency AS dependency
                JOIN dependency_path AS path
                  ON dependency.operation_id = path.operation_id
            )
            SELECT 1
            FROM dependency_path
            WHERE operation_id = NEW.operation_id
        ) THEN
            RAISE EXCEPTION 'operation dependency cycle detected'
                USING ERRCODE = '23514',
                      CONSTRAINT = 'authority_operation_dependency_acyclic_check';
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE TRIGGER authority_operation_dependency_guard
    BEFORE INSERT OR UPDATE OF operation_id, depends_on_operation_id
    ON authority_operation_dependency
    FOR EACH ROW
    EXECUTE FUNCTION authority_validate_operation_dependency()
    """,
    "CREATE INDEX authority_operation_parent_idx ON authority_operation(parent_operation_id) WHERE parent_operation_id IS NOT NULL",
    "CREATE INDEX authority_operation_root_idx ON authority_operation(root_operation_id)",
    "CREATE INDEX authority_operation_causation_idx ON authority_operation(causation_operation_id) WHERE causation_operation_id IS NOT NULL",
    "CREATE INDEX authority_operation_dependency_target_idx ON authority_operation_dependency(depends_on_operation_id)",
]

DOWNGRADE_STATEMENTS: list[str] = []
