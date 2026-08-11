from __future__ import annotations


MIGRATION_ID = "20260811_0078_reprocessing_action_expansion"
DOWN_REVISION = "20260811_0077_source_reprocessing_execution"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "repair an invalid action or quarantine the affected reprocessing plan"


UPGRADE_STATEMENTS = [
    """
    ALTER TABLE authority_source_reprocessing_plan_item
      DROP CONSTRAINT authority_source_reprocessing_plan_item_action_check,
      ADD CONSTRAINT authority_source_reprocessing_plan_item_action_check CHECK (
        action IN (
          'REUSE', 'RECOMPUTE', 'RECOMPUTE_AGGREGATE',
          'REABSTRACT', 'REGOVERN', 'REBUILD_PROJECTION'
        )
      )
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []
