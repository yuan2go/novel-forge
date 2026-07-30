from __future__ import annotations

MIGRATION_ID = "20260730_0040_chapter_group_authority"
DOWN_REVISION = "20260730_0039_hierarchical_planning"

UPGRADE_STATEMENTS = [
    """
    ALTER TABLE authority_book_chapter_request
    ADD COLUMN parent_group_version_id TEXT
        REFERENCES authority_asset_version(asset_version_id)
    """,
    """
    CREATE TABLE authority_chapter_group_production (
        group_run_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        book_run_id TEXT NOT NULL
            REFERENCES authority_book_production(book_run_id),
        group_plan_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        volume_plan_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        root_operation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_operation(operation_id),
        saga_id TEXT NOT NULL UNIQUE REFERENCES authority_saga(saga_id),
        stable_idempotency_key TEXT NOT NULL,
        chapter_start INTEGER NOT NULL,
        chapter_end INTEGER NOT NULL,
        accepted_through_chapter INTEGER NOT NULL,
        active_chapter_number INTEGER,
        active_chapter_request_id TEXT
            REFERENCES authority_book_chapter_request(chapter_request_id),
        state TEXT NOT NULL,
        recap_operation_id TEXT REFERENCES authority_operation(operation_id),
        plan_adjustment_proposal_version_id TEXT
            REFERENCES authority_asset_version(asset_version_id),
        failure_reason TEXT NOT NULL DEFAULT '',
        version BIGINT NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, stable_idempotency_key),
        UNIQUE(project_id, group_plan_version_id),
        CHECK (chapter_start > 0 AND chapter_end >= chapter_start),
        CHECK (chapter_end - chapter_start + 1 BETWEEN 3 AND 8),
        CHECK (
            accepted_through_chapter BETWEEN chapter_start - 1 AND chapter_end
        ),
        CHECK (
            active_chapter_number IS NULL
            OR active_chapter_number BETWEEN chapter_start AND chapter_end
        ),
        CHECK (state IN (
            'PREPARING', 'READY', 'CHAPTER_RUNNING', 'CLOSURE_PENDING',
            'PAUSED', 'COMPLETED', 'ABORTED', 'FAILED'
        ))
    )
    """,
    """
    CREATE UNIQUE INDEX chapter_group_one_active_per_book_idx
    ON authority_chapter_group_production(project_id, book_id)
    WHERE state IN (
        'PREPARING', 'READY', 'CHAPTER_RUNNING', 'CLOSURE_PENDING', 'PAUSED'
    )
    """,
    """
    CREATE TABLE authority_chapter_group_chapter (
        group_run_id TEXT NOT NULL
            REFERENCES authority_chapter_group_production(group_run_id),
        project_id TEXT NOT NULL,
        chapter_number INTEGER NOT NULL,
        chapter_plan_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        chapter_request_id TEXT NOT NULL UNIQUE
            REFERENCES authority_book_chapter_request(chapter_request_id),
        child_root_operation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_operation(operation_id),
        child_delegation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_child_delegation(delegation_id),
        acceptance_operation_id TEXT
            REFERENCES authority_operation(operation_id),
        chapter_outcome_version_id TEXT
            REFERENCES authority_asset_version(asset_version_id),
        status TEXT NOT NULL,
        accepted_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY(group_run_id, chapter_number),
        UNIQUE(group_run_id, chapter_plan_version_id),
        CHECK (chapter_number > 0),
        CHECK (status IN (
            'DISPATCHED', 'RUNNING', 'SUCCEEDED', 'ACCEPTED',
            'FAILED_RETRYABLE', 'FAILED_TERMINAL', 'CANCELLED'
        )),
        CHECK (
            (status = 'ACCEPTED' AND acceptance_operation_id IS NOT NULL
             AND chapter_outcome_version_id IS NOT NULL
             AND accepted_at IS NOT NULL)
            OR status <> 'ACCEPTED'
        )
    )
    """,
    """
    CREATE INDEX chapter_group_query_idx
    ON authority_chapter_group_production(
        project_id, book_id, state, updated_at DESC
    )
    """,
    """
    CREATE INDEX chapter_group_chapter_query_idx
    ON authority_chapter_group_chapter(
        group_run_id, status, chapter_number
    )
    """,
]

DOWNGRADE_STATEMENTS: list[str] = []
