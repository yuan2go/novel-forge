from __future__ import annotations

from .v20261020_0236_acknowledged_preparation_custody import PERMITTED as PREVIOUS_PERMITTED, GUARD_STATEMENT as PREVIOUS_GUARD

MIGRATION_ID = '20261020_0237_preparation_cli_version_identity'
DOWN_REVISION = '20261020_0236_acknowledged_preparation_custody'
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = 'Append v15 CLI-version-only custody with original verified account evidence; retain v14 strict authentication and every historical receipt.'

PERMITTED = PREVIOUS_PERMITTED
for before, after in (
    ('authority_acknowledged_preparation_permitted', 'authority_acknowledged_cli_version_permitted'),
    ("registration.definition_version='14.0.0'", "registration.definition_version='15.0.0'"),
    ('planning-acknowledged-preparation-handoff.v1', 'planning-acknowledged-preparation-handoff.v2'),
):
    assert before in PERMITTED
    PERMITTED = PERMITTED.replace(before, after)
_ANCHOR = """AND (NOT (r.target_runtime#>'{preparation_handoff,original_route}') ? 'auth_profile_ref'
  OR r.target_runtime->>'auth_profile_ref'=r.target_runtime#>>'{preparation_handoff,original_route,auth_profile_ref}')"""
assert PERMITTED.count(_ANCHOR) == 1
PERMITTED = PERMITTED.replace(_ANCHOR, """AND r.target_runtime#>>'{preparation_handoff,account_version_reconciliation,version}'='codex-cli-version-reconciliation.v1'
 AND r.target_runtime#>>'{preparation_handoff,account_version_reconciliation,source_auth_profile_ref}'=r.target_runtime#>>'{preparation_handoff,original_route,auth_profile_ref}'
 AND r.target_runtime#>>'{preparation_handoff,account_version_reconciliation,target_auth_profile_ref}'=r.target_runtime->>'auth_profile_ref'
 AND r.target_runtime#>'{preparation_handoff,account_version_reconciliation,target_entitlement}'=r.target_runtime#>'{account,entitlement}'
 AND (r.target_runtime#>'{preparation_handoff,account_version_reconciliation,original_entitlement}')-'cli_version'=(r.target_runtime#>'{account,entitlement}')-'cli_version'
 AND jsonb_typeof(r.target_runtime#>'{account,entitlement,billing_identity}')='object'
 AND length(r.target_runtime#>>'{account,entitlement,cli_version}')>0
 AND length(r.target_runtime#>>'{preparation_handoff,account_version_reconciliation,original_entitlement,cli_version}')>0
 AND r.target_runtime#>'{preparation_handoff,account_version_reconciliation,original_entitlement,cli_version}'<>r.target_runtime#>'{account,entitlement,cli_version}'
 AND EXISTS(SELECT 1 FROM authority_external_effect e
  JOIN authority_external_effect_dispatch d USING(external_effect_id)
  JOIN authority_external_receipt receipt USING(dispatch_id)
  WHERE e.operation_id=anchor.operation_id AND e.status='SUCCEEDED' AND d.status='SUCCEEDED' AND receipt.status='VERIFIED'
   AND receipt.payload#>>'{evidence,cost,accounting_basis}'='ACCOUNT_ENTITLEMENT'
   AND receipt.payload#>'{evidence,cost,entitlement_snapshot}'=r.target_runtime#>'{preparation_handoff,account_version_reconciliation,original_entitlement}'
   AND receipt.payload#>>'{evidence,cost,entitlement_snapshot_hash}'=r.target_runtime#>>'{preparation_handoff,account_version_reconciliation,original_entitlement_hash}')""")
_ANCHOR = 'AND NOT authority_acknowledged_preparation_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))'
assert PREVIOUS_GUARD.count(_ANCHOR) == 1
GUARD_STATEMENT = PREVIOUS_GUARD.replace(_ANCHOR, _ANCHOR + '\n               AND NOT authority_acknowledged_cli_version_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))')
UPGRADE_STATEMENTS = [PERMITTED, GUARD_STATEMENT]
DOWNGRADE_STATEMENTS: list[str] = []
