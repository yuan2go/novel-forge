from __future__ import annotations


MIGRATION_ID = "20260905_0110_chapter_mission_scene_contract"
DOWN_REVISION = "20260905_0109_industrial_execution_policies"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = "append corrected future Chapter contracts; retain accepted assets and frozen command receipts"


UPGRADE_STATEMENTS = [
    """
    ALTER TABLE authority_narrative_design_qualification
    DROP CONSTRAINT authority_narrative_design_qualification_design_layer_check
    """,
    """
    ALTER TABLE authority_narrative_design_qualification
    ADD CONSTRAINT authority_narrative_design_qualification_design_layer_check
    CHECK (design_layer IN (
        'STORY_INTENT', 'STORY_FOUNDATION', 'BOOK_ARCHITECTURE',
        'VOLUME_ARCHITECTURE', 'NARRATIVE_ARC_GRAPH',
        'CHARACTER_DEVELOPMENT', 'DISCLOSURE_OBLIGATION',
        'NARRATIVE_SCHEDULING', 'NARRATIVE_REALIZATION_PROOF',
        'CHAPTER_EXECUTION_PLAN', 'CHAPTER_MISSION', 'SCENE_ARCHITECTURE'
    ))
    """,
    """
    UPDATE authority_operation_definition SET enabled=FALSE
    WHERE name='planning.binding.activate' AND definition_version IN ('1.0.0','1.1.0')
    """,
]
