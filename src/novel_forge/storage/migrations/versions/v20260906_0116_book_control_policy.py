from __future__ import annotations

MIGRATION_ID = "20260906_0116_book_control_policy"
DOWN_REVISION = "20260906_0115_reality_event_index"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = "append editorial policy versions; preserve chapter policy bindings and operator decisions"
UPGRADE_STATEMENTS = [
    "ALTER TABLE authority_runtime_policy_version DROP CONSTRAINT authority_runtime_policy_version_owner_check",
    "ALTER TABLE authority_runtime_policy_version ADD CONSTRAINT authority_runtime_policy_version_owner_check CHECK (owner IN ('CHAPTER_GROUP_EXECUTION', 'READER_PROXY', 'BOOK_CONTROL'))",
]
