"""Closure planning, unified payoff state, and ending quality gates."""
from __future__ import annotations
from typing import Any

CLOSURE_FIELDS = ("main_problem_resolution", "protagonist_final_choice", "protagonist_cost", "antagonist_end", "relationship_closures", "reader_promises", "foreshadow_payoffs", "open_questions", "theme_reanswer", "world_state_change", "aftertaste", "epilogue_policy")
ITEM_TYPES = {"promise", "foreshadow", "mystery", "relationship", "character_arc", "world_rule", "reward_expectation", "theme_question", "antagonist_threat"}
PAYOFF_STATES = {"OPEN", "PROGRESSING", "READY_FOR_PAYOFF", "PAID", "PARTIALLY_PAID", "SUBVERTED_WITH_JUSTIFICATION", "ABANDONED", "BREACHED"}

def build_closure_plan(*, project_id: str, ending_intent_version_id: str, plan: dict[str, Any]) -> dict[str, Any]:
    missing = [field for field in CLOSURE_FIELDS if plan.get(field) in (None, "", [])]
    if missing: raise ValueError("ClosurePlan missing: " + ", ".join(missing))
    if str(plan["protagonist_cost"]).lower() in {"none", "zero"}: raise ValueError("ending requires protagonist cost")
    return {"project_id": project_id, "ending_intent_version_id": ending_intent_version_id, **plan, "closure_plan_contract_version": "closure-plan-v1"}

def build_payoff_matrix(*, project_id: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    normalized = []
    for item in items:
        if item.get("type") not in ITEM_TYPES or item.get("status") not in PAYOFF_STATES or not item.get("asset_version_id"):
            raise ValueError("invalid PayoffMatrix item")
        if item["status"] == "SUBVERTED_WITH_JUSTIFICATION" and not item.get("justification"):
            raise ValueError("subverted payoff requires justification")
        normalized.append(dict(item))
    return {"project_id": project_id, "items": normalized, "open_count": sum(item["status"] in {"OPEN", "PROGRESSING", "READY_FOR_PAYOFF", "ABANDONED", "BREACHED"} for item in normalized), "payoff_matrix_contract_version": "payoff-matrix-v1"}

def evaluate_ending_quality(*, project_id: str, closure_plan_version_id: str, payoff_matrix: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    issues = []
    for item in payoff_matrix.get("items", []):
        if item["status"] in {"OPEN", "PROGRESSING", "READY_FOR_PAYOFF", "ABANDONED", "BREACHED"}:
            issues.append({"code": "UNPAID_" + item["type"].upper(), "asset_version_id": item["asset_version_id"], "severity": "blocking"})
    flags = {"mechanical_summary": "MECHANICAL_ENDING", "sudden_victory": "SUDDEN_VICTORY", "antagonist_collapse": "ANTAGONIST_COLLAPSE", "arc_interrupted": "CHARACTER_ARC_INTERRUPTED", "world_state_unclear": "WORLD_STATE_UNCLEAR", "insufficient_cost": "INSUFFICIENT_ENDING_COST", "undesigned_open_ending": "UNDESIGNED_OPEN_ENDING"}
    for flag, code in flags.items():
        if evidence.get(flag): issues.append({"code": code, "severity": "blocking", "evidence_locator": evidence.get("evidence_locator", {})})
    return {"project_id": project_id, "closure_plan_version_id": closure_plan_version_id, "issues": issues, "passed": not issues, "report_type": "EndingQualityReport"}

__all__ = ["build_closure_plan", "build_payoff_matrix", "evaluate_ending_quality"]
