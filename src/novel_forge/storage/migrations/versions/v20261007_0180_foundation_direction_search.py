from __future__ import annotations

MIGRATION_ID = '20261007_0180_foundation_direction_search'
DOWN_REVISION = '20261007_0179_planning_arc_scope_revalidation'
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "append scoped evidence without rewriting published history or permitting uncertain consumption"

UPGRADE_STATEMENTS = [
    r"""ALTER TABLE authority_story_narrative_search DROP CONSTRAINT authority_story_narrative_search_generator_operation_name_check""",
    r"""ALTER TABLE authority_story_narrative_search DROP CONSTRAINT authority_story_narrative_search_planning_scope_check""",
    r"""ALTER TABLE authority_story_narrative_search ADD CONSTRAINT authority_story_narrative_search_scope_check CHECK (
        (generator_operation_name='creative.candidates.generate' AND planning_scope='NOT_APPLICABLE'
            AND accepted_through_chapter=0 AND parent_state_asset_version_id IS NULL)
        OR (generator_operation_name,planning_scope) IN (('book_plan.generate','BOOK'),('volume_plan.generate','VOLUME'),
            ('arc_plan.generate','ARC'),('chapter_group_plan.generate','CHAPTER_GROUP')))""",
]
DOWNGRADE_STATEMENTS: list[str] = []
