"""Theme evolution and evidence-located anti-preaching gates."""
from __future__ import annotations
from typing import Any

VALUE_FIELDS = ("conflicting_values", "character_initial_position", "pressure_event", "choice", "immediate_cost", "longterm_cost", "relationship_consequence", "world_consequence", "belief_change", "unresolved_tension")

def validate_theme_question(question: str) -> dict[str, Any]:
    text = question.strip()
    if len(text) < 24 or ("?" not in text and "？" not in text) or not any(word in text.lower() for word in ("when", "if", "当", "如果", "代价")):
        raise ValueError("ThemeQuestion must pose a concrete pressure-and-choice question")
    return {"question": text, "theme_question_contract_version": "theme-question-v1"}

def build_theme_arc(*, project_id: str, theme_question_version_id: str, conflicts: list[dict[str, Any]]) -> dict[str, Any]:
    if not conflicts: raise ValueError("ThemeArc requires value conflict evolution")
    beats = []
    for index, conflict in enumerate(conflicts, 1):
        missing = [field for field in VALUE_FIELDS if conflict.get(field) in (None, "", [])]
        if missing: raise ValueError("ValueConflict missing: " + ", ".join(missing))
        if str(conflict["immediate_cost"]).lower() in {"none", "zero"}: raise ValueError("theme choice requires an immediate cost")
        beats.append({"theme_beat_id": f"theme-beat-{index}", **conflict})
    return {"project_id": project_id, "theme_question_version_id": theme_question_version_id, "value_conflicts": conflicts, "theme_beats": beats, "meaning_strategy": "choices_change_positions_through_cost", "theme_arc_contract_version": "theme-arc-v1"}

def evaluate_anti_preaching(*, project_id: str, target_asset_version_id: str, passages: list[dict[str, Any]]) -> dict[str, Any]:
    issues = []
    checks = (
        ("AUTHOR_SUMMARY", "author_summary"), ("CORRECT_ANSWER_MONOLOGUE", "correct_answer_monologue"),
        ("PLOT_STOPS_FOR_PHILOSOPHY", "plot_stops"), ("COSTLESS_THEME_CHOICE", "choice_without_cost"),
        ("CONCLUSION_BEFORE_CONFLICT", "conclusion_before_conflict"), ("STRAWMAN_ANTAGONIST", "strawman_antagonist"),
        ("REPEATED_THEME_SENTENCE", "repeated_theme_statement"), ("NARRATION_REPLACES_ACTION", "narration_replaces_action"),
    )
    for passage in passages:
        for code, flag in checks:
            if passage.get(flag):
                issues.append({"code": code, "severity": "major", "evidence_locator": {"start": passage.get("start"), "end": passage.get("end"), "excerpt_digest": passage.get("excerpt_digest", "")}, "revision_strategy": "replace conclusion with a costly choice, opposition, and visible consequence", "review_issue": True})
    return {"project_id": project_id, "target_asset_version_id": target_asset_version_id, "issues": issues, "passed": not issues, "report_type": "AntiPreachingReport"}

__all__ = ["build_theme_arc", "evaluate_anti_preaching", "validate_theme_question"]
