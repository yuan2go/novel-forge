from __future__ import annotations

MIGRATION_ID = "20261014_0212_prose_citation_revalidation"
DOWN_REVISION = "20261014_0211_world_input_delivery_recovery"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Append versioned literal-citation report derivation events; retain failed reviews, model receipts, manuscript and legacy event kinds."
UPGRADE_STATEMENTS = [
    "ALTER TABLE authority_book_prose_review_event DROP CONSTRAINT authority_book_prose_review_event_kind_check",
    "ALTER TABLE authority_book_prose_review_event ADD CONSTRAINT authority_book_prose_review_event_kind_check CHECK (kind IN ('WINDOW_ADMITTED','WINDOW_REUSED','WINDOW_REVALIDATED','FINDING_DISPOSITION','PAUSED','RESUMED'))",
]
DOWNGRADE_STATEMENTS: list[str] = []
