from __future__ import annotations


MIGRATION_ID = "20260814_0090_progressive_replan_scopes"
DOWN_REVISION = "20260814_0089_progressive_narrative_design"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = (
    "Map Narrative Segment and Arc Segment replans onto the existing Volume "
    "and Arc planning Authorities"
)


UPGRADE_STATEMENTS = [
    """
    CREATE INDEX authority_narrative_design_qualification_scope_fk_idx
    ON authority_narrative_design_qualification(project_id, book_id)
    """,
    """
    CREATE INDEX authority_narrative_design_qualification_book_fk_idx
    ON authority_narrative_design_qualification(book_id)
    """,
    """
    ALTER TABLE authority_book_replan
    DROP CONSTRAINT authority_book_replan_affected_scope_check,
    ADD CONSTRAINT authority_book_replan_affected_scope_check
    CHECK (affected_scope IN (
        'CHAPTER', 'CHAPTER_GROUP', 'ARC', 'ARC_SEGMENT',
        'VOLUME', 'NARRATIVE_SEGMENT', 'BOOK'
    ))
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []
