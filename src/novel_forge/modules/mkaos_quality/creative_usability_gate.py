from __future__ import annotations

from typing import Any


def evaluate_creative_usability(card: dict[str, Any], *, threshold: float = 0.7) -> dict[str, Any]:
    content = card.get("content", {}) if isinstance(card.get("content", {}), dict) else card
    quality = content.get("quality_dimensions") if isinstance(content.get("quality_dimensions"), dict) else {}
    scores = {
        "creative_usability_score": float(quality.get("creative_usability_score", content.get("creative_usability_score", 0.0)) or 0.0),
        "abstraction_score": float(quality.get("abstraction_score", content.get("abstraction_score", 0.0)) or 0.0),
        "flow_binding_score": float(quality.get("flow_binding_score", content.get("flow_binding_score", 0.0)) or 0.0),
        "originality_safety_score": float(quality.get("originality_safety_score", content.get("originality_safety_score", 0.0)) or 0.0),
    }
    applicable_flows = [str(item) for item in content.get("applicable_flows") or [] if str(item).strip()]
    originality_boundary = str(content.get("originality_boundary") or "").strip()
    issues: list[dict[str, Any]] = []
    for key, value in scores.items():
        if value < threshold:
            issues.append({"issue_type": "mkaos_extraction_quality", "field": key, "severity": "high", "blocking": True, "message": f"{key} below {threshold}"})
    if not applicable_flows:
        issues.append({"issue_type": "mkaos_extraction_quality", "field": "applicable_flows", "severity": "high", "blocking": True, "message": "applicable_flows is empty"})
    if not originality_boundary:
        issues.append({"issue_type": "mkaos_extraction_quality", "field": "originality_boundary", "severity": "high", "blocking": True, "message": "originality_boundary is empty"})
    return {"passed": not issues, "scores": scores, "issues": issues}
