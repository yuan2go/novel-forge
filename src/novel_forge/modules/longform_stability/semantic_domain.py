"""Evidence-based long-form semantic stability reports."""
from __future__ import annotations
from collections import Counter
from typing import Any

def detect_motivation_drift(*, project_id: str, character_state_versions: list[dict[str, Any]], current_behavior: dict[str, Any]) -> dict[str, Any]:
    previous = character_state_versions[-1]
    evidence = current_behavior.get("change_evidence", [])
    old_goal, new_goal = previous.get("long_term_goal"), current_behavior.get("implied_goal")
    boundary_breach = current_behavior.get("moral_boundary_breached") and not current_behavior.get("boundary_change_evidence")
    if old_goal == new_goal: classification = "stable"
    elif current_behavior.get("hidden_motivation_revealed") and evidence: classification = "hidden_motivation_reveal"
    elif evidence: classification = "event_driven_growth"
    elif boundary_breach: classification = "unexplained_moral_boundary_break"
    elif not new_goal: classification = "long_term_goal_forgotten"
    else: classification = "unsupported_motivation_drift"
    blocking = classification in {"unexplained_moral_boundary_break", "long_term_goal_forgotten", "unsupported_motivation_drift"}
    return {"project_id": project_id, "character_state_version_ids": [item["asset_version_id"] for item in character_state_versions], "current_behavior_version_id": current_behavior["asset_version_id"], "classification": classification, "change_evidence": evidence, "missing_transition": blocking and not evidence, "review_issue": blocking, "revision_strategy": "add a pressure event, costly choice, and belief transition" if blocking else "", "future_chapter_plan_constraint": "preserve or explicitly transition the long-term goal" if blocking else "", "report_type": "MotivationDriftReport"}

def propose_entity_merge(*, project_id: str, left: dict[str, Any], right: dict[str, Any], mentions: list[dict[str, Any]]) -> dict[str, Any]:
    if left.get("project_id") != project_id or right.get("project_id") != project_id: raise ValueError("cross-project entity merge is forbidden")
    aliases_left = {str(left.get("name", "")).lower(), *[str(v).lower() for v in left.get("aliases", [])]}
    aliases_right = {str(right.get("name", "")).lower(), *[str(v).lower() for v in right.get("aliases", [])]}
    shared = sorted(aliases_left & aliases_right - {""})
    evidence = [item for item in mentions if item.get("project_id") == project_id and {item.get("entity_hint"), item.get("resolved_hint")} <= {left.get("entity_id"), right.get("entity_id")}]
    confidence = min(1.0, 0.45 * bool(shared) + 0.15 * len(evidence))
    high_impact = left.get("entity_type") in {"character", "organization"} or right.get("entity_type") in {"character", "organization"}
    return {"project_id": project_id, "left_entity_id": left["entity_id"], "right_entity_id": right["entity_id"], "shared_aliases": shared, "evidence": evidence, "confidence": confidence, "decision": "AUTO_MERGE" if confidence >= 0.9 and not high_impact else "REQUIRES_APPROVAL", "report_type": "EntityMergeProposal"}

def evaluate_foreshadow_payoff(*, project_id: str, thread_version_id: str, scores: dict[str, float]) -> dict[str, Any]:
    fields = ("setup_clarity", "reader_memory", "timing", "causal_relevance", "surprise", "fairness", "emotional_payoff", "plot_consequence", "character_consequence", "theme_relevance")
    if any(field not in scores for field in fields): raise ValueError("foreshadow payoff scores incomplete")
    average = sum(scores[field] for field in fields) / len(fields)
    if scores["causal_relevance"] < .4: classification = "causally_empty_payoff"
    elif scores["reader_memory"] < .35: classification = "reader_cannot_recall_setup"
    elif scores["plot_consequence"] < .35 and scores["character_consequence"] < .35: classification = "mechanical_explanation_only"
    elif average >= .75: classification = "excellent_payoff"
    elif scores["timing"] < .3: classification = "mistimed_payoff"
    else: classification = "partial_payoff"
    return {"project_id": project_id, "thread_version_id": thread_version_id, "scores": scores, "average": average, "classification": classification, "review_issue": classification != "excellent_payoff", "report_type": "ForeshadowPayoffReport"}

def detect_world_rule_conflicts(*, project_id: str, rule_versions: list[dict[str, Any]], events: list[dict[str, Any]]) -> dict[str, Any]:
    issues = []
    by_key = {}
    for rule in rule_versions:
        key = (rule.get("rule_key"), rule.get("scope")); previous = by_key.get(key)
        if previous and previous.get("definition") != rule.get("definition") and not rule.get("supersedes_version_id"): issues.append({"code": "RULE_DEFINITION_DRIFT", "versions": [previous["asset_version_id"], rule["asset_version_id"]]})
        by_key[key] = rule
    for event in events:
        for flag, code in (("unpaid_exception", "EXCEPTION_WITHOUT_COST"), ("sudden_immunity", "SUDDEN_IMMUNITY"), ("resource_created", "RESOURCE_FROM_NOTHING"), ("capability_out_of_scope", "CAPABILITY_OUT_OF_SCOPE"), ("institution_selective", "INSTITUTION_ONLY_WHEN_NEEDED")):
            if event.get(flag): issues.append({"code": code, "event_version_id": event.get("asset_version_id")})
    return {"project_id": project_id, "issues": issues, "passed": not issues, "report_type": "WorldRuleConflictReport"}

def detect_power_conflicts(*, project_id: str, previous_state: dict[str, Any], current_state: dict[str, Any]) -> dict[str, Any]:
    reasons = set(current_state.get("change_reasons", [])); allowed = {"training", "equipment", "temporary_buff", "environment", "intelligence", "counter", "teamwork"}
    issues = []
    if current_state.get("power_tier", 0) > previous_state.get("power_tier", 0) and not reasons & allowed: issues.append("UNEXPLAINED_POWER_INCREASE")
    if current_state.get("power_tier", 0) < previous_state.get("power_tier", 0) and not reasons: issues.append("UNEXPLAINED_WEAKENING")
    if current_state.get("cost", "") in {"", "none"} and current_state.get("new_capabilities"): issues.append("COSTLESS_CAPABILITY")
    if current_state.get("scale_growth", 1) >= 3: issues.append("POWER_INFLATION")
    return {"project_id": project_id, "previous_power_state_version_id": previous_state["asset_version_id"], "current_power_state_version_id": current_state["asset_version_id"], "issues": issues, "passed": not issues, "report_type": "PowerConflictReport"}

def detect_pattern_repetition(*, project_id: str, fingerprints: list[dict[str, Any]], threshold: int = 3) -> dict[str, Any]:
    fields = ("conflict_trigger", "antagonist_entry", "resolution", "reward", "misunderstanding", "humiliation", "chapter_ending", "revelation", "character_reaction")
    counts = Counter(tuple(item.get(field, "") for field in fields) for item in fingerprints)
    repeated = [{"fingerprint": dict(zip(fields, key)), "count": count} for key, count in counts.items() if count >= threshold]
    return {"project_id": project_id, "repeated_patterns": repeated, "trope_fatigue_risk": "HIGH" if repeated else "LOW", "report_type": "PatternRepetitionReport"}

def evaluate_narrative_debt(*, project_id: str, current_chapter: int, debts: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for debt in debts:
        age = current_chapter - int(debt["opened_chapter"])
        window_end = int(debt.get("payoff_window_end", current_chapter))
        breach = current_chapter > window_end
        rows.append({**debt, "age": age, "urgency": "CRITICAL" if breach else debt.get("urgency", "MEDIUM"), "reader_visibility": debt.get("reader_visibility", "VISIBLE"), "breach_risk": "BREACHED" if breach else "OPEN", "recommended_chapter_range": [current_chapter + 1, max(current_chapter + 1, window_end)]})
    return {"project_id": project_id, "debts": rows, "breached_count": sum(item["breach_risk"] == "BREACHED" for item in rows), "arc_progress": "STALLED" if any(item.get("type") == "main_plot" and item["age"] >= 5 for item in rows) else "MOVING", "report_type": "NarrativeDebtReport"}

def build_enhanced_recap(*, project_id: str, reports: dict[str, Any]) -> dict[str, Any]:
    required = ("motivation", "relationships", "canon", "world_rules", "power", "foreshadow", "promise_debt", "reward_cadence", "antagonist_pressure", "patterns", "theme", "quality")
    missing = [key for key in required if key not in reports]
    if missing: raise ValueError("semantic recap reports missing: " + ", ".join(missing))
    constraints = [item for item in reports.get("constraints", [])]
    return {"project_id": project_id, "main_plot_progress": reports.get("main_plot_progress", ""), "character_motivation_changes": reports["motivation"], "relationship_movement": reports["relationships"], "canon_conflicts": reports["canon"], "world_rule_conflicts": reports["world_rules"], "power_conflicts": reports["power"], "foreshadow_status": reports["foreshadow"], "promise_debt": reports["promise_debt"], "reward_cadence": reports["reward_cadence"], "antagonist_pressure": reports["antagonist_pressure"], "pattern_repetition": reports["patterns"], "theme_movement": reports["theme"], "quality_trend": reports["quality"], "next_window_production_policy": {"constraints": constraints, "mutate_accepted_chapters": False}, "chapter_plan_constraints": constraints, "review_focus": reports.get("review_focus", []), "report_type": "LongformRecapReport"}

__all__ = ["build_enhanced_recap", "detect_motivation_drift", "detect_pattern_repetition", "detect_power_conflicts", "detect_world_rule_conflicts", "evaluate_foreshadow_payoff", "evaluate_narrative_debt", "propose_entity_merge"]
