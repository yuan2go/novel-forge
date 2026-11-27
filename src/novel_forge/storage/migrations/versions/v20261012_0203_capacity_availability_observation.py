from __future__ import annotations

from .v20261012_0202_prepared_planning_continuation import UPGRADE_STATEMENTS as PREVIOUS

MIGRATION_ID = '20261012_0203_capacity_availability_observation'
DOWN_REVISION = '20261012_0202_prepared_planning_continuation'
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = 'Recognize the native timestamped temporary model availability observation alongside proven unsent capacity failure; retain all authorization and receipt guards.'

_OLD = "OR (candidate->'rejected_reasons')-'CONTEXT_CAPACITY_EXCEEDED'-'BUDGET_HARD_LIMIT'-'PROVIDER_MODEL_CAPACITY_UNAVAILABLE'<>'[]'::jsonb"
assert PREVIOUS[1].count(_OLD) == 1
UPGRADE_STATEMENTS = [PREVIOUS[1].replace(_OLD, """OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(candidate->'rejected_reasons') reason
              WHERE reason NOT IN ('CONTEXT_CAPACITY_EXCEEDED','BUDGET_HARD_LIMIT','PROVIDER_MODEL_CAPACITY_UNAVAILABLE')
              AND reason NOT LIKE 'PROVIDER_UNAVAILABLE:PROVIDER_MODEL_CAPACITY_UNAVAILABLE:%')""")]
DOWNGRADE_STATEMENTS: list[str] = []
