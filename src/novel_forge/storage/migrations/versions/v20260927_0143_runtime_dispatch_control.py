from __future__ import annotations


MIGRATION_ID = "20260927_0143_runtime_dispatch_control"
DOWN_REVISION = "20260921_0142_prose_editorial_foreign_key_indexes"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = "retain project dispatch controls and append new operator decisions"

UPGRADE_STATEMENTS = [
    """CREATE TABLE authority_runtime_dispatch_control (
        project_id TEXT PRIMARY KEY REFERENCES authority_project(project_id),
        state TEXT NOT NULL CHECK (state IN ('PAUSED','RUNNING')),
        version BIGINT NOT NULL CHECK (version > 0),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    """CREATE TABLE authority_runtime_dispatch_event (
        event_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_runtime_dispatch_control(project_id),
        version BIGINT NOT NULL CHECK (version > 0),
        idempotency_key TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('PAUSED','RUNNING')),
        previous_version BIGINT NOT NULL CHECK (previous_version >= 0),
        actor_id TEXT NOT NULL,
        reason TEXT NOT NULL CHECK (length(btrim(reason)) > 0),
        release_identity JSONB NOT NULL CHECK (jsonb_typeof(release_identity) = 'object'),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id,version),
        UNIQUE(project_id,idempotency_key)
    )""",
    """CREATE FUNCTION authority_runtime_dispatch_event_immutable() RETURNS trigger
       LANGUAGE plpgsql AS $$ BEGIN
       RAISE EXCEPTION 'runtime dispatch decisions are immutable'; END; $$""",
    """CREATE TRIGGER authority_runtime_dispatch_event_immutable
       BEFORE UPDATE OR DELETE ON authority_runtime_dispatch_event
       FOR EACH ROW EXECUTE FUNCTION authority_runtime_dispatch_event_immutable()""",
]
