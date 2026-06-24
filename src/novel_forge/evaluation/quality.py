from __future__ import annotations

QUALITY_DIMENSIONS = [
    "structure_integrity",
    "causal_chain",
    "character_motivation_chain",
    "conflict_strength",
    "rhythm_density",
    "payoff_density",
    "emotion_curve",
    "chapter_hook",
    "foreshadowing_setup",
    "foreshadowing_recovery",
    "world_consistency",
    "character_consistency",
    "style_consistency",
    "commercial_readability",
    "originality_and_copyright_boundary",
    "reader_feedback_fit",
]


def default_review_rubric() -> dict[str, list[str]]:
    return {"dimensions": QUALITY_DIMENSIONS}
