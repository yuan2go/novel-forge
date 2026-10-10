from __future__ import annotations

from .v20261009_0194_multi_model_generation_isolation import UPGRADE_STATEMENTS as PREVIOUS

MIGRATION_ID = "20261010_0197_authorized_planning_capacity"
DOWN_REVISION = "20261010_0196_stopped_cli_timeout_isolation"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Keep unsent Planning capacity succession inside authorized candidates; retain denied catalog routes and every frozen identity and lease guard."

UPGRADE_STATEMENTS = [PREVIOUS[1].replace(
    "AND jsonb_array_length(version.content->'candidates')>0",
    """AND EXISTS(SELECT 1 FROM jsonb_array_elements(version.content->'candidates') candidate
          WHERE NOT (candidate->'rejected_reasons' ? 'TEMPLATE_MODEL_UNAUTHORIZED'))""",
).replace(
    "WHERE NOT (candidate->'rejected_reasons' ? 'CONTEXT_CAPACITY_EXCEEDED')\n            OR (candidate->'rejected_reasons')-'CONTEXT_CAPACITY_EXCEEDED'-'BUDGET_HARD_LIMIT'<>'[]'::jsonb",
    """WHERE NOT (candidate->'rejected_reasons' ? 'TEMPLATE_MODEL_UNAUTHORIZED') AND (
            NOT (candidate->'rejected_reasons' ? 'CONTEXT_CAPACITY_EXCEEDED')
            OR (candidate->'rejected_reasons')-'CONTEXT_CAPACITY_EXCEEDED'-'BUDGET_HARD_LIMIT'<>'[]'::jsonb)""",
)]
DOWNGRADE_STATEMENTS: list[str] = []
