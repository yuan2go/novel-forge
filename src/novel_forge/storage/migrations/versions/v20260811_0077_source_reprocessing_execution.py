from __future__ import annotations


MIGRATION_ID = "20260811_0077_source_reprocessing_execution"
DOWN_REVISION = "20260811_0076_source_import_runtime"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = (
    "repair invalid reprocessing dependencies/results or quarantine the affected plan"
)


UPGRADE_STATEMENTS = [
    """
    ALTER TABLE authority_source_reprocessing_plan_item
      ADD COLUMN dependency_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
      ADD COLUMN result JSONB NOT NULL DEFAULT '{}'::jsonb,
      ADD CONSTRAINT authority_source_reprocessing_item_execution_json_check CHECK (
        jsonb_typeof(dependency_ids) = 'array'
        AND jsonb_typeof(result) = 'object'
      )
    """,
    """
    CREATE INDEX authority_source_reprocessing_item_child_idx
    ON authority_source_reprocessing_plan_item(child_operation_id)
    WHERE child_operation_id IS NOT NULL
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []
