from __future__ import annotations

from .v20261019_0233_acknowledged_preparation_routing import PERMITTED as PREVIOUS_PERMITTED
from .v20261019_0234_settled_preparation_capacity import GUARD_STATEMENT as PREVIOUS_GUARD

MIGRATION_ID = '20261020_0236_acknowledged_preparation_custody'
DOWN_REVISION = '20261019_0235_source_isolation_convergence'
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = 'Append v14 custody for a first acknowledged native preparation cancellation with no isolated ancestor; preserve original receipts, zero-send proof and old guards.'

PERMITTED = PREVIOUS_PERMITTED
for before, after in (
    ('authority_first_isolated_preparation_v12_permitted', 'authority_acknowledged_preparation_permitted'),
    ("registration.definition_version='12.0.0'", "registration.definition_version='14.0.0'"),
    ('planning-first-isolated-preparation-handoff.v2', 'planning-acknowledged-preparation-handoff.v1'),
):
    assert before in PERMITTED
    PERMITTED = PERMITTED.replace(before, after)
_ANCHOR = 'AND EXISTS(SELECT 1 FROM authority_generation_isolation WHERE operation_id=anchor.operation_id)'
assert PERMITTED.count(_ANCHOR) == 1
PERMITTED = PERMITTED.replace(_ANCHOR, """AND NOT EXISTS(SELECT 1 FROM authority_generation_isolation WHERE operation_id=anchor.operation_id)
 AND anchor.status='RECONCILIATION_REQUIRED'
 AND r.target_runtime#>'{preparation_handoff,isolated_generation_count}'='0'::jsonb
 AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(r.target_runtime#>'{preparation_handoff,stopped_ancestry}') member
  WHERE member->>'kind' IS DISTINCT FROM 'ACKNOWLEDGED_CANCELLATION')""")
_ANCHOR = 'AND NOT authority_first_isolated_preparation_v13_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))'
assert PREVIOUS_GUARD.count(_ANCHOR) == 1
GUARD_STATEMENT = PREVIOUS_GUARD.replace(_ANCHOR, _ANCHOR + '\n               AND NOT authority_acknowledged_preparation_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))')
UPGRADE_STATEMENTS = [PERMITTED, GUARD_STATEMENT]
DOWNGRADE_STATEMENTS: list[str] = []
