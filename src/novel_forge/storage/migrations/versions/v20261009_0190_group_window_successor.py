from __future__ import annotations

from .v20261009_0189_unsent_context_successor import UPGRADE_STATEMENTS as UNSENT_STATEMENTS

MIGRATION_ID = "20261009_0190_group_window_successor"
DOWN_REVISION = "20261009_0189_unsent_context_successor"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Extend proven unsent Context succession to frozen ChapterGroup windows without changing input identities."

UPGRADE_STATEMENTS = [
    UNSENT_STATEMENTS[0].replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1).replace(
        "AND r.target_runtime #>> '{planning_capacity,context_revalidation,contract_version}'='typed-volume-context-projection.v1'",
        """AND ((generation->>'generator_operation_name'='arc_plan.generate'
          AND r.target_runtime #>> '{planning_capacity,context_revalidation,contract_version}'='typed-volume-context-projection.v1')
          OR (generation->>'generator_operation_name'='chapter_group_plan.generate'
          AND r.target_runtime #>> '{planning_capacity,context_revalidation,contract_version}'='typed-planning-window-projection.v1'
          AND r.source_command #>> '{narrative_search_planning_horizon,level}'='CHAPTER_GROUP'
          AND jsonb_array_length(r.source_command #> '{narrative_search_planning_horizon,chapter_range}')=2
          AND r.source_command->>'narrative_search_id' IS NOT NULL))""",
    ).replace(
        "AND generation->>'book_id'=r.book_id AND generation->>'generator_operation_name'='arc_plan.generate'",
        "AND generation->>'book_id'=r.book_id AND generation->>'generator_operation_name' IN ('arc_plan.generate','chapter_group_plan.generate')",
    ).replace("AND source.status='FAILED_FINAL'", "AND source.status IN ('FAILED_FINAL','DEAD_LETTER')"),
]
DOWNGRADE_STATEMENTS: list[str] = []
