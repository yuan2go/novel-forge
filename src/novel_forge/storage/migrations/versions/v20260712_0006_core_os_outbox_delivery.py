from __future__ import annotations

MIGRATION_ID = "20260712_0006_core_os_outbox_delivery"
DOWN_REVISION = "20260712_0005_core_os_runtime"
UPGRADE_STATEMENTS = [
    "ALTER TABLE outbox_event ADD COLUMN IF NOT EXISTS dead_letter_at TIMESTAMPTZ",
    "ALTER TABLE outbox_event ADD COLUMN IF NOT EXISTS replay_count INTEGER NOT NULL DEFAULT 0",
    "CREATE TABLE IF NOT EXISTS outbox_consumer_delivery (consumer_name TEXT NOT NULL, event_id TEXT NOT NULL REFERENCES state_event(event_id), delivered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), PRIMARY KEY(consumer_name,event_id))",
]
DOWNGRADE_STATEMENTS: list[str] = []
