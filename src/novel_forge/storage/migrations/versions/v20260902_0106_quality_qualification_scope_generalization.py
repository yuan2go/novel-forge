from __future__ import annotations


MIGRATION_ID = "20260902_0106_quality_qualification_scope_generalization"
DOWN_REVISION = "20260830_0105_p0_backend_qualification_repairs"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = (
    "remove fixed campaign-size constraints while preserving frozen campaign bounds"
)


UPGRADE_STATEMENTS = [
    """
    DO $$
    DECLARE
        constraint_name TEXT;
    BEGIN
        FOR constraint_name IN
            SELECT conname
            FROM pg_constraint
            WHERE conrelid = 'authority_quality_qualification_campaign'::regclass
              AND contype = 'c'
              AND (
                  pg_get_constraintdef(oid) LIKE '%chapter_start = 1%'
                  OR pg_get_constraintdef(oid) LIKE
                     '%jsonb_array_length(chapter_group_ranges) = 2%'
              )
        LOOP
            EXECUTE format(
                'ALTER TABLE authority_quality_qualification_campaign DROP CONSTRAINT %I',
                constraint_name
            );
        END LOOP;
    END
    $$
    """,
    """
    ALTER TABLE authority_quality_qualification_campaign
    ADD CONSTRAINT authority_quality_qualification_campaign_bounds_check
    CHECK (chapter_start > 0 AND chapter_end >= chapter_start)
    """,
    """
    ALTER TABLE authority_quality_qualification_campaign
    ADD CONSTRAINT authority_quality_qualification_campaign_ranges_nonempty_check
    CHECK (jsonb_array_length(chapter_group_ranges) >= 1)
    """,
    """
    DO $$
    DECLARE
        constraint_name TEXT;
    BEGIN
        FOR constraint_name IN
            SELECT conname
            FROM pg_constraint
            WHERE conrelid = 'human_preference_evaluation_pack'::regclass
              AND contype = 'c'
              AND pg_get_constraintdef(oid) LIKE '%chapter_pair_count = 8%'
        LOOP
            EXECUTE format(
                'ALTER TABLE human_preference_evaluation_pack DROP CONSTRAINT %I',
                constraint_name
            );
        END LOOP;
    END
    $$
    """,
    """
    ALTER TABLE human_preference_evaluation_pack
    ADD CONSTRAINT human_preference_evaluation_pack_chapter_count_check
    CHECK (chapter_pair_count > 0)
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []
