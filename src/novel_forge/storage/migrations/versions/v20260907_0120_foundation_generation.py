from __future__ import annotations

MIGRATION_ID = "20260907_0120_foundation_generation"
DOWN_REVISION = "20260907_0119_grounded_chapter_acceptance"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = "repair unaccepted Formation candidates through their frozen generation operations"

UPGRADE_STATEMENTS = [
    "ALTER TABLE authority_story_planning_generation DROP CONSTRAINT authority_story_planning_generat_generator_operation_name_check",
    "ALTER TABLE authority_story_planning_generation DROP CONSTRAINT authority_story_planning_generation_planning_scope_check",
    """
    ALTER TABLE authority_story_planning_generation
    ADD CONSTRAINT authority_generation_scope_owner_check CHECK (
        (generator_operation_name='book_plan.generate' AND planning_scope='BOOK') OR
        (generator_operation_name='volume_plan.generate' AND planning_scope='VOLUME') OR
        (generator_operation_name='arc_plan.generate' AND planning_scope='ARC') OR
        (generator_operation_name='chapter_group_plan.generate' AND planning_scope='CHAPTER_GROUP') OR
        (generator_operation_name='chapter_plan.generate' AND planning_scope='CHAPTER') OR
        (generator_operation_name IN (
            'creative.candidates.generate', 'theme.candidates.generate',
            'ending.intent.generate', 'reader.promise.generate',
            'world.design.generate', 'character.cast.generate'
        ) AND planning_scope='NOT_APPLICABLE')
    )
    """,
]
