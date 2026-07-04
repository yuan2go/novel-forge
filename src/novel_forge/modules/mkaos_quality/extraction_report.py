from __future__ import annotations

from typing import Any

from .creative_usability_gate import evaluate_creative_usability


def build_extraction_report_payload(payload: dict[str, Any], knowledge_cards: list[dict[str, Any]], creative_assets: list[dict[str, Any]]) -> dict[str, Any]:
    source_count = int(payload.get("source_count", 0) or 0)
    chunk_count = int(payload.get("chunk_count", 0) or 0)
    weak_cards: list[dict[str, Any]] = []
    scores: list[float] = []
    flow_bound = 0
    for card in knowledge_cards:
        gate = evaluate_creative_usability(card)
        content = card.get("content", {})
        quality = content.get("quality_dimensions") if isinstance(content.get("quality_dimensions"), dict) else {}
        scores.append(float(quality.get("creative_usability_score", content.get("creative_usability_score", 0.0)) or 0.0))
        if content.get("applicable_flows"):
            flow_bound += 1
        if not gate["passed"]:
            weak_cards.append({"knowledge_id": card.get("id", ""), "title": card.get("title", ""), "issues": gate["issues"]})
    creative_usability_score = round(sum(scores) / max(1, len(scores)), 4)
    flow_binding_coverage = round(flow_bound / max(1, len(knowledge_cards)), 4)
    return {
        "source_count": source_count,
        "chunk_count": chunk_count,
        "knowledge_card_count": len(knowledge_cards),
        "creative_asset_count": len(creative_assets),
        "extraction_coverage": round(len(knowledge_cards) / max(1, chunk_count or source_count or len(knowledge_cards)), 4),
        "duplicate_rate": float(payload.get("duplicate_rate", 0.0) or 0.0),
        "abstraction_score": creative_usability_score,
        "creative_usability_score": creative_usability_score,
        "flow_binding_coverage": flow_binding_coverage,
        "leakage_risk": str(payload.get("leakage_risk") or "low"),
        "weak_cards": weak_cards,
        "passed": not weak_cards and creative_usability_score >= 0.7 and flow_binding_coverage >= 0.7,
    }
