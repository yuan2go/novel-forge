from __future__ import annotations

MIGRATION_ID = "20260729_0034_unified_business_authority"
DOWN_REVISION = "20260728_0033_agent_collaboration_v1"

BOOK_STATES = """
    'READY', 'CHAPTER_SUBMITTED', 'CHAPTER_RUNNING',
    'CHAPTER_WAITING_RETRY', 'CHAPTER_COMPLETED',
    'CHAPTER_FAILED_RETRYABLE', 'CHAPTER_FAILED_TERMINAL',
    'CANON_PENDING', 'CANON_COMMITTED', 'READER_OUTCOME_PENDING',
    'CHECKPOINT_PENDING', 'REPLAN_REQUIRED', 'PAUSED',
    'COMPLETED', 'ABORTED'
"""

UPGRADE_STATEMENTS = [
    f"""
    CREATE TABLE authority_book_production (
        book_run_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        workspace_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        book_design_version TEXT NOT NULL,
        book_plan_version TEXT NOT NULL,
        production_profile_version TEXT NOT NULL,
        longform_context_versions JSONB NOT NULL,
        root_operation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_operation(operation_id),
        saga_id TEXT NOT NULL UNIQUE REFERENCES authority_saga(saga_id),
        stable_idempotency_key TEXT NOT NULL,
        state TEXT NOT NULL,
        current_chapter INTEGER NOT NULL DEFAULT 0,
        target_chapter_count INTEGER NOT NULL,
        light_recap_cadence INTEGER NOT NULL,
        formal_recap_cadence INTEGER NOT NULL,
        active_chapter_request_id TEXT,
        last_reader_outcome_operation_id TEXT
            REFERENCES authority_operation(operation_id),
        last_recap_operation_id TEXT
            REFERENCES authority_operation(operation_id),
        version BIGINT NOT NULL DEFAULT 0,
        paused_reason TEXT NOT NULL DEFAULT '',
        failure_classification TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, stable_idempotency_key),
        CHECK (state IN ({BOOK_STATES})),
        CHECK (current_chapter >= 0),
        CHECK (target_chapter_count > 0),
        CHECK (current_chapter <= target_chapter_count),
        CHECK (light_recap_cadence > 0 AND formal_recap_cadence > 0)
        ,CHECK (
            jsonb_typeof(longform_context_versions) = 'object'
            AND longform_context_versions ?& ARRAY[
                'volume_plan_version', 'arc_plan_version',
                'character_state_version', 'foreshadowing_state_version',
                'quality_trend_version', 'reward_ledger_version',
                'promise_ledger_version'
            ]
        )
    )
    """,
    """
    CREATE INDEX authority_book_production_query_idx
    ON authority_book_production(project_id, book_id, state, updated_at DESC)
    """,
    """
    CREATE INDEX authority_book_production_reader_operation_fk_idx
    ON authority_book_production(last_reader_outcome_operation_id)
    """,
    """
    CREATE INDEX authority_book_production_recap_operation_fk_idx
    ON authority_book_production(last_recap_operation_id)
    """,
    """
    CREATE TABLE authority_book_chapter_request (
        chapter_request_id TEXT PRIMARY KEY,
        book_run_id TEXT NOT NULL
            REFERENCES authority_book_production(book_run_id),
        project_id TEXT NOT NULL,
        chapter_number INTEGER NOT NULL,
        chapter_plan_version TEXT NOT NULL,
        chapter_plan_content_hash TEXT NOT NULL,
        production_profile_version TEXT NOT NULL,
        stable_idempotency_key TEXT NOT NULL,
        command_payload JSONB NOT NULL,
        chapter_root_operation_id TEXT UNIQUE
            REFERENCES authority_operation(operation_id),
        chapter_saga_id TEXT REFERENCES authority_saga(saga_id),
        status_reference TEXT NOT NULL,
        failure_classification TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, stable_idempotency_key),
        UNIQUE(
            book_run_id, chapter_number, chapter_plan_version,
            production_profile_version
        ),
        CHECK (chapter_number > 0),
        CHECK (status_reference IN (
            'SUBMITTING', 'ADMITTED', 'RUNNING', 'WAITING_RETRY',
            'SUCCEEDED', 'FAILED_RETRYABLE', 'FAILED_TERMINAL',
            'CANCELLED', 'UNKNOWN'
        ))
    )
    """,
    """
    CREATE INDEX authority_book_chapter_request_query_idx
    ON authority_book_chapter_request(
        book_run_id, chapter_number, updated_at DESC
    )
    """,
    """
    CREATE INDEX authority_book_chapter_request_saga_fk_idx
    ON authority_book_chapter_request(chapter_saga_id)
    """,
    """
    ALTER TABLE authority_book_production
    ADD CONSTRAINT authority_book_active_chapter_request_fk
    FOREIGN KEY(active_chapter_request_id)
    REFERENCES authority_book_chapter_request(chapter_request_id)
    """,
    """
    CREATE INDEX authority_book_production_active_request_fk_idx
    ON authority_book_production(active_chapter_request_id)
    """,
    """
    CREATE TABLE authority_book_followup_operation (
        followup_id TEXT PRIMARY KEY,
        book_run_id TEXT NOT NULL
            REFERENCES authority_book_production(book_run_id),
        chapter_request_id TEXT NOT NULL
            REFERENCES authority_book_chapter_request(chapter_request_id),
        project_id TEXT NOT NULL,
        followup_type TEXT NOT NULL,
        operation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_operation(operation_id),
        stable_idempotency_key TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, stable_idempotency_key),
        UNIQUE(chapter_request_id, followup_type),
        CHECK (followup_type IN ('READER_OUTCOME', 'LONGFORM_RECAP'))
    )
    """,
    """
    CREATE INDEX authority_book_followup_query_idx
    ON authority_book_followup_operation(
        book_run_id, followup_type, created_at DESC
    )
    """,
    """
    CREATE VIEW authority_reader_outcome_projection AS
    SELECT link.book_run_id, link.chapter_request_id, link.operation_id,
           operation.project_id, operation.status,
           binding.asset_version_id AS reader_outcome_report_asset_version,
           version.content AS reader_outcome_report,
           operation.updated_at
    FROM authority_book_followup_operation AS link
    JOIN authority_operation AS operation
      ON operation.operation_id = link.operation_id
    LEFT JOIN authority_operation_output_asset AS binding
      ON binding.operation_id = operation.operation_id
     AND binding.output_key = 'reader_outcome.report'
    LEFT JOIN authority_asset_version AS version
      ON version.asset_version_id = binding.asset_version_id
    WHERE link.followup_type = 'READER_OUTCOME'
    """,
    """
    CREATE VIEW authority_longform_recap_projection AS
    SELECT link.book_run_id, link.chapter_request_id, link.operation_id,
           operation.project_id, operation.status,
           binding.asset_version_id AS longform_recap_asset_version,
           version.content AS longform_recap,
           operation.updated_at
    FROM authority_book_followup_operation AS link
    JOIN authority_operation AS operation
      ON operation.operation_id = link.operation_id
    LEFT JOIN authority_operation_output_asset AS binding
      ON binding.operation_id = operation.operation_id
     AND binding.output_key = 'longform.recap.report'
    LEFT JOIN authority_asset_version AS version
      ON version.asset_version_id = binding.asset_version_id
    WHERE link.followup_type = 'LONGFORM_RECAP'
    """,
]

# Forward-only Authority migration. Rollback is operational: disable the new
# definitions/routes and retain append-only audit state, then repair forward.
# Destructive table removal is deliberately not automated.
DOWNGRADE_STATEMENTS: list[str] = []
