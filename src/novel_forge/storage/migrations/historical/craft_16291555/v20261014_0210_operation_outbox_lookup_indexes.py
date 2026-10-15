from __future__ import annotations

MIGRATION_ID = "20261014_0210_operation_outbox_lookup_indexes"
DOWN_REVISION = "20261014_0209_planning_input_scope_point_reads"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Index both existing Operation completion outbox lookup paths without changing event or completion semantics."

UPGRADE_STATEMENTS = [
    """CREATE INDEX authority_outbox_operation_topics_idx
    ON outbox_event(project_id, (payload->>'operation_id')) INCLUDE(topic)""",
    """CREATE INDEX authority_outbox_event_topics_idx
    ON outbox_event(project_id, event_id) INCLUDE(topic)""",
]
DOWNGRADE_STATEMENTS: list[str] = []
