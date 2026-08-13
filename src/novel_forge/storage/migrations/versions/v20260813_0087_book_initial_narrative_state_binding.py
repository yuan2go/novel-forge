from __future__ import annotations


MIGRATION_ID = "20260813_0087_book_initial_narrative_state_binding"
DOWN_REVISION = "20260812_0086_corrective_generation_terminal_lineage"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = (
    "Book Production input snapshots bind an optional, complete pre-Chapter-1 "
    "Story State and Canon pair instead of trusting model-declared prior state"
)


UPGRADE_STATEMENTS = [
    """
    ALTER TABLE authority_book_production_input_snapshot
    ADD COLUMN initial_story_state_version TEXT
      REFERENCES authority_asset_version(asset_version_id),
    ADD COLUMN initial_canon_snapshot_version TEXT
      REFERENCES authority_asset_version(asset_version_id)
    """,
    """
    ALTER TABLE authority_book_production_input_snapshot
    ADD CONSTRAINT authority_book_input_initial_narrative_pair_check
    CHECK (
      (initial_story_state_version IS NULL
       AND initial_canon_snapshot_version IS NULL)
      OR
      (initial_story_state_version IS NOT NULL
       AND initial_canon_snapshot_version IS NOT NULL)
    )
    """,
    """
    CREATE INDEX idx_book_input_initial_story_state
    ON authority_book_production_input_snapshot(initial_story_state_version)
    WHERE initial_story_state_version IS NOT NULL
    """,
    """
    CREATE INDEX idx_book_input_initial_canon_snapshot
    ON authority_book_production_input_snapshot(initial_canon_snapshot_version)
    WHERE initial_canon_snapshot_version IS NOT NULL
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []
