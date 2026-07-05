from __future__ import annotations

from typing import Any


def score_extraction_candidate(candidate: dict[str, Any], validation: dict[str, Any], sanitizer: dict[str, Any], deterministic_candidates: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    quality = candidate.get("quality_dimensions") if isinstance(candidate.get("quality_dimensions"), dict) else {}
    schema_validity = 1.0 if validation.get("valid") else max(0.0, 1.0 - 0.12 * len(validation.get("errors", [])))
    evidence_binding = 1.0 if candidate.get("evidence_refs") else 0.55
    abstraction = _score_text(candidate.get("creative_principle"), bonus_terms=["机制", "pressure", "conflict", "选择", "代价"], default=float(quality.get("abstraction_score", 0.72)))
    creative_usability = _score_text(candidate.get("narrative_function"), bonus_terms=["冲突", "行动", "hook", "场景", "选择"], default=float(quality.get("creative_usability_score", 0.72)))
    originality = max(0.0, float(quality.get("originality_safety_score", 0.82)) - 0.12 * int(sanitizer.get("forbidden_field_count", 0)))
    flow_binding = 0.95 if candidate.get("applicable_flows") else 0.35
    source_risk = {"low": 0.95, "medium": 0.7, "high": 0.35}.get(str(candidate.get("risk_level") or "low"), 0.6)
    provider_reliability = 0.8 if candidate.get("metadata", {}).get("provider_mode") not in {"", "disabled"} else 0.7
    deterministic_consistency = _deterministic_consistency(candidate, deterministic_candidates or [])
    review_pass = float(quality.get("review_pass_score", 0.65))
    dimensions = {
        "schema_validity_score": round(schema_validity, 4),
        "evidence_binding_score": round(evidence_binding, 4),
        "abstraction_score": round(abstraction, 4),
        "creative_usability_score": round(creative_usability, 4),
        "originality_safety_score": round(originality, 4),
        "flow_binding_score": round(flow_binding, 4),
        "source_risk_score": round(source_risk, 4),
        "provider_reliability_score": round(provider_reliability, 4),
        "deterministic_consistency_score": round(deterministic_consistency, 4),
        "review_pass_score": round(review_pass, 4),
    }
    confidence = round(sum(dimensions.values()) / len(dimensions), 4)
    if sanitizer.get("forbidden_field_count", 0):
        recommendation = "reject" if confidence < 0.85 else "review"
    elif confidence >= 0.85:
        recommendation = "approve"
    elif confidence >= 0.65:
        recommendation = "review"
    else:
        recommendation = "reject"
    return {"confidence": confidence, "quality_dimensions": dimensions, "approval_recommendation": recommendation}


def _score_text(value: Any, *, bonus_terms: list[str], default: float) -> float:
    text = str(value or "")
    if not text:
        return min(default, 0.5)
    score = default
    if any(term.lower() in text.lower() for term in bonus_terms):
        score += 0.08
    if len(text) >= 20:
        score += 0.05
    return max(0.0, min(1.0, score))


def _deterministic_consistency(candidate: dict[str, Any], deterministic: list[dict[str, Any]]) -> float:
    if not deterministic:
        return 0.72
    candidate_flows = {str(item) for item in candidate.get("applicable_flows") or []}
    candidate_type = str(candidate.get("knowledge_type") or "")
    best = 0.45
    for item in deterministic:
        overlap = len(candidate_flows & {str(flow) for flow in item.get("applicable_flows") or []})
        type_match = candidate_type and candidate_type == str(item.get("knowledge_type") or "")
        best = max(best, 0.55 + overlap * 0.12 + (0.18 if type_match else 0))
    return min(1.0, best)
