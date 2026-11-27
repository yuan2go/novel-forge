from __future__ import annotations

MIGRATION_ID = "20261006_0156_resource_journal_indexes"
DOWN_REVISION = "20261006_0155_unsent_resource_route_succession"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "retain immutable resource journals and their indexed ownership references"
UPGRADE_STATEMENTS = [
    "CREATE INDEX authority_opening_resource_project_idx ON authority_book_opening_resource_successor(project_id,book_id)",
    "CREATE INDEX authority_effect_resource_operation_idx ON authority_effect_resource_denial(operation_id,created_at)",
    "CREATE INDEX authority_effect_resource_project_idx ON authority_effect_resource_denial(project_id,external_effect_id)",
]
DOWNGRADE_STATEMENTS: list[str] = []
