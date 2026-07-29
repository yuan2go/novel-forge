from __future__ import annotations

MIGRATION_ID = "20260730_0037_story_state_reducer_registry"
DOWN_REVISION = "20260730_0036_book_canon_checkpoint"

UPGRADE_STATEMENTS = [
    """
    CREATE TABLE authority_story_state_reducer_application (
        reducer_application_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        chapter_outcome_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        reducer_key TEXT NOT NULL,
        input_contract_version TEXT NOT NULL,
        output_state_type TEXT NOT NULL,
        current_state_version INTEGER NOT NULL,
        transition_hash TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        validation_policy TEXT NOT NULL,
        dependency_keys JSONB NOT NULL,
        story_state_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        status TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, chapter_outcome_asset_version_id, reducer_key),
        UNIQUE(project_id, idempotency_key),
        UNIQUE(project_id, transition_hash),
        CHECK (current_state_version >= 0),
        CHECK (transition_hash LIKE 'sha256:%'),
        CHECK (jsonb_typeof(dependency_keys) = 'array'),
        CHECK (status = 'APPLIED')
    )
    """,
    """
    CREATE INDEX authority_story_reducer_outcome_idx
    ON authority_story_state_reducer_application(
        project_id, chapter_outcome_asset_version_id
    )
    """,
    """
    CREATE INDEX authority_story_reducer_state_idx
    ON authority_story_state_reducer_application(
        project_id, story_state_asset_version_id
    )
    """,
    """
    CREATE INDEX authority_story_reducer_key_idx
    ON authority_story_state_reducer_application(
        project_id, reducer_key, created_at
    )
    """,
]

DOWNGRADE_STATEMENTS: list[str] = []
