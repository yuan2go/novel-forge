from __future__ import annotations

from .v20261019_0232_first_isolated_preparation_custody import MEMBER_STOPPED as PREVIOUS_MEMBER, PERMITTED as PREVIOUS_PERMITTED, GUARD_STATEMENT as PREVIOUS_GUARD

MIGRATION_ID = '20261019_0233_acknowledged_preparation_routing'
DOWN_REVISION = '20261019_0232_first_isolated_preparation_custody'
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = 'Append v12 zero-send routing-lineage recovery and retain first-isolation custody without reinterpreting prior v11 requests or failed Attempts.'

MEMBER_STOPPED = PREVIOUS_MEMBER.replace('authority_first_preparation_member_stopped', 'authority_first_preparation_member_v12_stopped')
_ANCHOR = "OR (a.result->>'error_code'='PLANNING_ROUTING_LINEAGE_DEPTH_EXCEEDED'"
assert MEMBER_STOPPED.count(_ANCHOR) == 1
MEMBER_STOPPED = MEMBER_STOPPED.replace(_ANCHOR,
    "OR a.result='" + '{"error_code":"PLANNING_ROUTING_LINEAGE_INVALID","error_message":"PLANNING_ROUTING_LINEAGE_INVALID: Runtime successor lacks its exact native continuation","failure_class":"final_failure","failure_details":{}}' + "'::jsonb\n       " + _ANCHOR)
PERMITTED = PREVIOUS_PERMITTED
for before, after in (
    ('authority_first_isolated_preparation_permitted', 'authority_first_isolated_preparation_v12_permitted'),
    ('authority_first_preparation_member_stopped', 'authority_first_preparation_member_v12_stopped'),
    ("registration.definition_version='11.0.0'", "registration.definition_version='12.0.0'"),
    ('planning-first-isolated-preparation-handoff.v1', 'planning-first-isolated-preparation-handoff.v2'),
):
    assert before in PERMITTED
    PERMITTED = PERMITTED.replace(before, after)
_ANCHOR = 'AND NOT authority_first_isolated_preparation_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))'
assert PREVIOUS_GUARD.count(_ANCHOR) == 1
GUARD_STATEMENT = PREVIOUS_GUARD.replace(_ANCHOR, _ANCHOR + '\n               AND NOT authority_first_isolated_preparation_v12_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))')
UPGRADE_STATEMENTS = [MEMBER_STOPPED, PERMITTED, GUARD_STATEMENT]
DOWNGRADE_STATEMENTS: list[str] = []
