from __future__ import annotations

from .v20261009_0188_saved_result_admission import UPGRADE_STATEMENTS as SAVED_STATEMENTS

MIGRATION_ID = '20261009_0193_completed_planning_admission'
DOWN_REVISION = '20261009_0192_generation_retry_lineage'
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = 'Reuse verified complete Planning output after host assembly failure without resending or granting isolated attempts commit rights.'

UPGRADE_STATEMENTS = [SAVED_STATEMENTS[0].replace(
    "AND receipt.payload #>> '{evidence,recovery_action}'='LOCAL_SAVED_RESULT_REUSE'",
    "AND (receipt.payload #>> '{evidence,recovery_action}'='LOCAL_SAVED_RESULT_REUSE' OR NEW.evidence->>'completed_result_source'='VERIFIED_PROVIDER_COMPLETION')",
).replace(
    "WHERE source.operation_id=NEW.source_operation_id AND source.status IN ('FAILED_FINAL','DEAD_LETTER')",
    "WHERE source.operation_id=NEW.source_operation_id AND source.status IN ('FAILED_FINAL','DEAD_LETTER') AND NOT EXISTS(SELECT 1 FROM authority_generation_isolation isolation WHERE isolation.operation_id=source.operation_id) AND NOT EXISTS(SELECT 1 FROM authority_story_planning_runtime_continuation link WHERE link.source_operation_id=source.operation_id)",
)]
DOWNGRADE_STATEMENTS: list[str] = []
