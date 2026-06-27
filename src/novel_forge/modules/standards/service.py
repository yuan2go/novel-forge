from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.ids import utc_now
from novel_forge.evaluation.creative_gate import evaluate_draft_quality
from novel_forge.modules.common import resolve_path
from novel_forge.modules.production_context import build_production_context
from novel_forge.schemas import QualityScoreReport
from novel_forge.storage.local import LocalStorage


def create_quality_score_report(
    storage: LocalStorage,
    target_path: str,
    *,
    workspace_path: str | None = None,
    review_result: dict[str, Any] | None = None,
) -> Path:
    path = resolve_path(storage.root, target_path)
    target = storage.read_asset(path)
    context = build_production_context(storage, target, input_path=path, workspace_path=workspace_path)
    evaluation = evaluate_quality_standard(target, context, review_result=review_result)
    project = context["project"]
    standard = context["profiles"].get("quality_standard_profile") or {}
    asset = QualityScoreReport(
        title=f"Quality score for {target.title}",
        source=target.id,
        tags=["quality", "quality-score", "publish-gate"],
        content={
            "target_asset_id": target.id,
            "standard_id": evaluation["standard_id"],
            "overall_score": evaluation["overall_score"],
            "scores": evaluation["scores"],
            "gate_results": evaluation["gate_results"],
            "recommendation": evaluation["recommendation"],
            "dimension_details": evaluation["dimension_details"],
        },
        metadata={
            "workflow": "quality-standard-gate",
            "project_id": project.get("project_id", ""),
            "workspace_path": project.get("workspace_path", ""),
            "quality_standard_profile_path": standard.get("path", "") if isinstance(standard, dict) else "",
            "created_at": utc_now(),
            "risk_level": "high" if evaluation["recommendation"] == "block_publish" else "medium",
        },
        references=_dedupe([target.id, str(standard.get("id", "")) if isinstance(standard, dict) else ""]),
    )
    return storage.write_asset("reviews", asset)


def evaluate_quality_standard(
    target_asset: Any,
    context: dict[str, Any],
    *,
    review_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    text = _asset_text(target_asset)
    gate = evaluate_draft_quality(text)
    standard = context.get("profiles", {}).get("quality_standard_profile") if isinstance(context.get("profiles", {}), dict) else {}
    standard_content = standard.get("content", {}) if isinstance(standard, dict) else {}
    dimensions = standard_content.get("dimensions", {}) if isinstance(standard_content.get("dimensions", {}), dict) else {}
    if not dimensions:
        dimensions = {
            "plot_causality": {"weight": 0.2, "threshold": 75},
            "character_drive": {"weight": 0.2, "threshold": 75},
            "chapter_rhythm": {"weight": 0.2, "threshold": 75},
            "style_consistency": {"weight": 0.2, "threshold": 75},
            "originality_safety": {"weight": 0.2, "threshold": 85},
        }
    base_score = _base_score(gate, review_result)
    scores: dict[str, float] = {}
    details: dict[str, dict[str, Any]] = {}
    total_weight = 0.0
    weighted = 0.0
    blocked = set(gate.get("blocked_dimensions", []))
    for name, raw_dimension in dimensions.items():
        dimension = raw_dimension if isinstance(raw_dimension, dict) else {}
        weight = float(dimension.get("weight", 1.0) or 0)
        threshold = float(dimension.get("threshold", 75) or 75)
        score = _dimension_score(str(name), base_score, blocked, review_result)
        scores[str(name)] = score
        total_weight += max(weight, 0)
        weighted += score * max(weight, 0)
        details[str(name)] = {
            "score": score,
            "threshold": threshold,
            "passed": score >= threshold,
            "weight": weight,
        }
    overall = round(weighted / total_weight, 2) if total_weight else base_score
    hard_gates = standard_content.get("hard_gates", []) if isinstance(standard_content.get("hard_gates", []), list) else []
    gate_results = _hard_gate_results(hard_gates, gate, scores)
    recommendation = "pass_publish_gate"
    if any(not value for value in gate_results.values()) or any(not item["passed"] for item in details.values()):
        recommendation = "revise_before_publish"
    if overall < 60 or not gate_results.get("copyright_boundary_passed", True):
        recommendation = "block_publish"
    return {
        "standard_id": standard_content.get("standard_id", standard.get("id", "quality_standard_missing") if isinstance(standard, dict) else "quality_standard_missing"),
        "overall_score": overall,
        "scores": scores,
        "gate_results": gate_results,
        "recommendation": recommendation,
        "dimension_details": details,
        "raw_gate": gate,
    }


def _base_score(gate: dict[str, Any], review_result: dict[str, Any] | None) -> float:
    if review_result and isinstance(review_result.get("score"), (int, float)):
        return float(review_result["score"])
    score = gate.get("score")
    return float(score) if isinstance(score, (int, float)) else 75.0


def _dimension_score(name: str, base_score: float, blocked: set[str], review_result: dict[str, Any] | None) -> float:
    aliases = {
        "opening_hook": {"chapter_hook", "foreshadowing_setup"},
        "plot_causality": {"causal_chain", "structure_integrity"},
        "character_drive": {"character_motivation_chain", "character_consistency"},
        "chapter_rhythm": {"rhythm_density", "payoff_density"},
        "style_consistency": {"style_consistency"},
        "originality_safety": {"originality_and_copyright_boundary"},
        "long_form_stability": {"world_consistency", "foreshadowing_recovery"},
        "platform_compliance": set(),
    }
    related = aliases.get(name, {name})
    score = base_score
    if related & blocked:
        score -= 25
    if review_result:
        for issue in review_result.get("issues", []):
            if not isinstance(issue, dict):
                continue
            if str(issue.get("dimension", "")) in related:
                score -= 10 if issue.get("severity") == "high" else 5
    return max(0.0, min(100.0, round(score, 2)))


def _hard_gate_results(hard_gates: list[Any], gate: dict[str, Any], scores: dict[str, float]) -> dict[str, bool]:
    results: dict[str, bool] = {}
    blocked = set(gate.get("blocked_dimensions", []))
    for raw_gate in hard_gates:
        name = str(raw_gate)
        if name == "copyright_boundary_passed":
            results[name] = scores.get("originality_safety", 100) >= 70
        elif name == "platform_compliance_passed":
            results[name] = True
        elif name == "no_major_continuity_break":
            results[name] = "world_consistency" not in blocked and scores.get("long_form_stability", 100) >= 60
        else:
            results[name] = True
    if "copyright_boundary_passed" not in results:
        results["copyright_boundary_passed"] = scores.get("originality_safety", 100) >= 70
    return results


def _asset_text(asset: Any) -> str:
    content = asset.content if hasattr(asset, "content") and isinstance(asset.content, dict) else {}
    text = content.get("text")
    if isinstance(text, str) and text.strip():
        return text
    return str(content.get("summary") or getattr(asset, "title", ""))


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
