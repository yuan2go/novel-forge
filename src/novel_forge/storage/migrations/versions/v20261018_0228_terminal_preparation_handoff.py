from __future__ import annotations

from .v20261018_0227_completed_preparation_handoff import GUARD_STATEMENT as PREVIOUS_GUARD, PERMITTED as ACKNOWLEDGED_PERMITTED

MIGRATION_ID = '20261018_0228_terminal_preparation_handoff'
DOWN_REVISION = '20261018_0227_completed_preparation_handoff'
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = 'Append exact terminal host preparation custody without changing failed history, cancellation contracts or capacity.'

PERMITTED = ACKNOWLEDGED_PERMITTED.replace('authority_completed_preparation_handoff_permitted', 'authority_terminal_preparation_handoff_permitted')
for before, after in (
    ("registration.definition_version='5.0.0'", "registration.definition_version='6.0.0'"),
    ("source.status='RECONCILIATION_REQUIRED'", "source.status='FAILED_FINAL'"),
    ("attempt.status='CANCELLED'", "attempt.status='FAILED_FINAL'"),
    ("planning-completed-preparation-handoff.v1", "planning-terminal-preparation-handoff.v1"),
    ("REVOKED_BY_ACKNOWLEDGED_CANCELLATION", "RELEASED_BY_TERMINAL_FAILURE"),
    ("status<>'CANCELLED'", "status<>'FAILED_FINAL'"),
    (" AND EXISTS(SELECT 1 FROM authority_worker_cancel_signal WHERE operation_id=source.operation_id AND attempt_id=attempt.attempt_id AND status='ACKNOWLEDGED' AND acknowledged_at IS NOT NULL)", " AND NOT EXISTS(SELECT 1 FROM authority_worker_cancel_signal WHERE operation_id=source.operation_id)"),
    (" AND EXISTS(SELECT 1 FROM authority_cancellation_command WHERE operation_id=source.operation_id)", " AND NOT EXISTS(SELECT 1 FROM authority_cancellation_command WHERE operation_id=source.operation_id)"),
):
    assert before in PERMITTED
    PERMITTED = PERMITTED.replace(before, after)
PERMITTED = PERMITTED.replace(" AND attempt.status='FAILED_FINAL'", """ AND attempt.result->>'error_code'='CONTEXT_COMPRESSION_TASK_INVALID'
 AND attempt.result->>'failure_class'='final_failure'
 AND attempt.result->>'error_message'='CONTEXT_COMPRESSION_TASK_INVALID: compression needs a bounded source chunk and frozen task boundary'
 AND link.target_runtime#>'{preparation_handoff,host_failure}'=attempt.result
 AND attempt.status='FAILED_FINAL'""", 1)
_ANCHOR = 'AND NOT authority_completed_preparation_handoff_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))'
assert PREVIOUS_GUARD.count(_ANCHOR) == 1
GUARD_STATEMENT = PREVIOUS_GUARD.replace(_ANCHOR, _ANCHOR + '\n               AND NOT authority_terminal_preparation_handoff_permitted(NEW.runtime_continuation_id,NEW.operation_id,to_jsonb(NEW))')
UPGRADE_STATEMENTS = [PERMITTED, GUARD_STATEMENT]
DOWNGRADE_STATEMENTS: list[str] = []
