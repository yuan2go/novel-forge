from __future__ import annotations

from .v20261009_0187_chapter_generation_isolation import UPGRADE_STATEMENTS as CHAPTER_STATEMENTS
from .v20261009_0190_group_window_successor import UPGRADE_STATEMENTS as CONTEXT_STATEMENTS

MIGRATION_ID = "20261009_0194_multi_model_generation_isolation"
DOWN_REVISION = "20261009_0193_completed_planning_admission"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Admit stopped pure Chapter preparation through native isolation and step succession; completed sibling receipts remain independently reusable."
UPGRADE_STATEMENTS = [CHAPTER_STATEMENTS[0].replace(
    "o.definition_name IN ('chapter.memo.generate'",
    "o.definition_name IN ('chapter.context.build','chapter.memo.generate'",
) , CONTEXT_STATEMENTS[0].replace(
    "IN ('arc_plan.generate','chapter_group_plan.generate')",
    "IN ('arc_plan.generate','chapter_group_plan.generate','chapter_plan.generate')",
).replace(
    "AND r.source_command->>'narrative_search_id' IS NOT NULL))",
    """AND r.source_command->>'narrative_search_id' IS NOT NULL)
          OR (generation->>'generator_operation_name'='chapter_plan.generate'
          AND r.target_runtime #>> '{planning_capacity,context_revalidation,contract_version}'='planning-exact-value-reference.v1'))""",
)]
DOWNGRADE_STATEMENTS: list[str] = []
