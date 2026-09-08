from __future__ import annotations


MIGRATION_ID = "20260908_0123_source_analysis_dimensions"
DOWN_REVISION = "20260908_0122_source_work_manifest"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = (
    "preserve existing Observations; admit only the additional governed classical "
    "corpus analysis dimensions"
)


UPGRADE_STATEMENTS = [
    """
    ALTER TABLE authority_source_deconstruction_observation
      DROP CONSTRAINT
        authority_source_deconstruction_observation_dimension_check,
      ADD CONSTRAINT
        authority_source_deconstruction_observation_dimension_check CHECK (
          dimension IN (
            'structure', 'pacing', 'hook', 'reward_payoff', 'reader_promise',
            'conflict', 'character_mechanism', 'relationship_mechanism',
            'emotion_curve', 'foreshadowing', 'information_progression',
            'serialization', 'commercial_logic', 'originality_copyright_risk',
            'scene_craft', 'narrative_distance', 'character_arc', 'subtext',
            'transition', 'theme_system', 'social_pressure', 'symbol_function',
            'fate_curve', 'moral_dilemma', 'craft_principle',
            'causal_constraints', 'misuse_risk', 'review_check', 'core_concept',
            'credibility_rule', 'conflict_generator', 'historical_causality',
            'institutional_constraint', 'social_dynamics', 'source_reliability',
            'argument_structure', 'concept_definition', 'assumption',
            'counterargument', 'character_choice_cost', 'information_gap',
            'foreshadowing_payoff', 'chapter_hook', 'imagery', 'emotion_turn',
            'point_of_view', 'rhythm', 'concise_expression', 'scene_atmosphere',
            'value_conflict', 'historical_context', 'platform_policy',
            'eligibility_rule', 'retention_constraint', 'release_constraint',
            'compliance_risk'
          )
        ) NOT VALID
    """,
    """
    ALTER TABLE authority_source_deconstruction_observation
      VALIDATE CONSTRAINT
        authority_source_deconstruction_observation_dimension_check
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []
