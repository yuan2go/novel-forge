from __future__ import annotations

MIGRATION_ID = "20260730_0035_book_child_delegation"
DOWN_REVISION = "20260729_0034_unified_business_authority"

UPGRADE_STATEMENTS = [
    """
    ALTER TABLE authority_book_production
    ADD COLUMN accepted_through_chapter INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN active_child_delegation_id TEXT,
    ADD COLUMN active_chapter_number INTEGER,
    ADD COLUMN active_plan_version_id TEXT,
    ADD COLUMN active_story_state_version_id TEXT
        REFERENCES authority_asset_version(asset_version_id),
    ADD COLUMN last_chapter_outcome_version_id TEXT
        REFERENCES authority_asset_version(asset_version_id),
    ADD COLUMN failure_reason TEXT NOT NULL DEFAULT ''
    """,
    """
    ALTER TABLE authority_book_production
    ADD CONSTRAINT authority_book_accepted_range_check
    CHECK (
        accepted_through_chapter >= 0
        AND accepted_through_chapter <= target_chapter_count
        AND (active_chapter_number IS NULL OR active_chapter_number > 0)
    )
    """,
    """
    CREATE INDEX authority_book_story_state_fk_idx
    ON authority_book_production(active_story_state_version_id)
    """,
    """
    CREATE INDEX authority_book_chapter_outcome_fk_idx
    ON authority_book_production(last_chapter_outcome_version_id)
    """,
    """
    CREATE TABLE authority_child_delegation (
        delegation_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        owner_authority TEXT NOT NULL,
        owner_id TEXT NOT NULL
            REFERENCES authority_book_production(book_run_id),
        child_authority TEXT NOT NULL,
        chapter_request_id TEXT NOT NULL UNIQUE
            REFERENCES authority_book_chapter_request(chapter_request_id),
        chapter_number INTEGER NOT NULL,
        plan_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        child_root_operation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_operation(operation_id),
        child_saga_id TEXT NOT NULL UNIQUE
            REFERENCES authority_saga(saga_id),
        stable_idempotency_key TEXT NOT NULL,
        status TEXT NOT NULL,
        failure_classification TEXT NOT NULL DEFAULT '',
        version BIGINT NOT NULL DEFAULT 0,
        accepted_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, stable_idempotency_key),
        CHECK (owner_authority = 'BOOK'),
        CHECK (child_authority = 'CHAPTER'),
        CHECK (chapter_number > 0),
        CHECK (status IN (
            'DISPATCHED', 'RUNNING', 'WAITING_RETRY', 'SUCCEEDED',
            'ACCEPTED', 'FAILED_RETRYABLE', 'FAILED_TERMINAL',
            'CANCELLATION_REQUESTED', 'CANCELLED', 'UNKNOWN'
        ))
    )
    """,
    """
    CREATE UNIQUE INDEX authority_child_delegation_one_active_owner_idx
    ON authority_child_delegation(owner_id)
    WHERE status IN (
        'DISPATCHED', 'RUNNING', 'WAITING_RETRY', 'SUCCEEDED',
        'CANCELLATION_REQUESTED', 'UNKNOWN'
    )
    """,
    """
    CREATE INDEX authority_child_delegation_project_status_idx
    ON authority_child_delegation(project_id, status, updated_at)
    """,
    """
    CREATE INDEX authority_child_delegation_owner_fk_idx
    ON authority_child_delegation(owner_id)
    """,
    """
    CREATE INDEX authority_child_delegation_request_fk_idx
    ON authority_child_delegation(chapter_request_id)
    """,
    """
    CREATE INDEX authority_child_delegation_root_fk_idx
    ON authority_child_delegation(child_root_operation_id)
    """,
    """
    CREATE INDEX authority_child_delegation_saga_fk_idx
    ON authority_child_delegation(child_saga_id)
    """,
    """
    ALTER TABLE authority_book_production
    ADD CONSTRAINT authority_book_active_child_delegation_fk
    FOREIGN KEY(active_child_delegation_id)
    REFERENCES authority_child_delegation(delegation_id)
    """,
    """
    CREATE INDEX authority_book_active_delegation_fk_idx
    ON authority_book_production(active_child_delegation_id)
    """,
    """
    CREATE TABLE authority_book_chapter_acceptance (
        acceptance_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        book_run_id TEXT NOT NULL
            REFERENCES authority_book_production(book_run_id),
        chapter_request_id TEXT NOT NULL UNIQUE
            REFERENCES authority_book_chapter_request(chapter_request_id),
        delegation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_child_delegation(delegation_id),
        acceptance_operation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_operation(operation_id),
        chapter_number INTEGER NOT NULL,
        chapter_outcome_asset_version_id TEXT NOT NULL UNIQUE
            REFERENCES authority_asset_version(asset_version_id),
        story_state_asset_version_id TEXT NOT NULL UNIQUE
            REFERENCES authority_asset_version(asset_version_id),
        evidence JSONB NOT NULL,
        status TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CHECK (chapter_number > 0),
        CHECK (status = 'COMMITTED'),
        CHECK (jsonb_typeof(evidence) = 'object')
    )
    """,
    """
    CREATE INDEX authority_book_acceptance_project_chapter_idx
    ON authority_book_chapter_acceptance(
        project_id, book_run_id, chapter_number
    )
    """,
    """
    CREATE INDEX authority_book_acceptance_book_fk_idx
    ON authority_book_chapter_acceptance(book_run_id)
    """,
    """
    CREATE INDEX authority_book_acceptance_delegation_fk_idx
    ON authority_book_chapter_acceptance(delegation_id)
    """,
    """
    CREATE INDEX authority_book_acceptance_operation_fk_idx
    ON authority_book_chapter_acceptance(acceptance_operation_id)
    """,
    """
    CREATE INDEX authority_book_acceptance_outcome_fk_idx
    ON authority_book_chapter_acceptance(chapter_outcome_asset_version_id)
    """,
    """
    CREATE INDEX authority_book_acceptance_story_state_fk_idx
    ON authority_book_chapter_acceptance(story_state_asset_version_id)
    """,
]

# Authority records are append-only. Rollback disables definitions and repairs
# forward; destructive downgrade is intentionally unavailable.
DOWNGRADE_STATEMENTS: list[str] = []
