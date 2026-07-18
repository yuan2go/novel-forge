"""Explicit storage-free handler bindings for content-domain operations."""
from novel_forge.modules.characters.domain import build_character, build_relationship_state
from novel_forge.modules.creative.domain import build_project_proposal, cluster_candidates, evaluate_candidate, validate_creative_brief
from novel_forge.modules.ending.domain import build_closure_plan, build_payoff_matrix, evaluate_ending_quality
from novel_forge.modules.longform_stability.semantic_domain import build_enhanced_recap, detect_motivation_drift, detect_pattern_repetition, detect_power_conflicts, detect_world_rule_conflicts, evaluate_foreshadow_payoff, evaluate_narrative_debt, propose_entity_merge
from novel_forge.modules.theme.domain import build_theme_arc, evaluate_anti_preaching, validate_theme_question
from novel_forge.modules.worldbuilding.domain import build_world_bible, validate_world_rules
from novel_forge.modules.chapter_quality_authority.calibration import (
    QualityGoldenSample, QualityHumanDecision, evaluate_calibration_run,
    promote_calibration_profile,
)

CONTENT_DOMAIN_HANDLERS = {
    "creative.brief.create": validate_creative_brief,
    "creative.candidates.evaluate": evaluate_candidate,
    "creative.candidates.cluster": cluster_candidates,
    "creative.project.approve": build_project_proposal,
    "production.world.generate": build_world_bible,
    "world.validate": validate_world_rules,
    "production.character.generate": build_character,
    "character.relationships.generate": build_relationship_state,
    "theme.question.create": validate_theme_question,
    "theme.arc.build": build_theme_arc,
    "theme.anti_preaching.evaluate": evaluate_anti_preaching,
    "ending.closure.plan": build_closure_plan,
    "ending.payoff_matrix.build": build_payoff_matrix,
    "ending.quality.evaluate": evaluate_ending_quality,
    "longform.motivation.evaluate": detect_motivation_drift,
    "longform.entity_merge.propose": propose_entity_merge,
    "longform.foreshadow_payoff.evaluate": evaluate_foreshadow_payoff,
    "longform.world_rule.evaluate": detect_world_rule_conflicts,
    "longform.power.evaluate": detect_power_conflicts,
    "longform.pattern.evaluate": detect_pattern_repetition,
    "longform.narrative_debt.evaluate": evaluate_narrative_debt,
    "longform.recap.enhance": build_enhanced_recap,
    "quality.golden_sample.create": QualityGoldenSample,
    "quality.human_decision.record": QualityHumanDecision,
    "quality.calibration.run": evaluate_calibration_run,
    "quality.calibration.profile.promote": promote_calibration_profile,
    "quality.calibration.profile.revoke": promote_calibration_profile,
}
