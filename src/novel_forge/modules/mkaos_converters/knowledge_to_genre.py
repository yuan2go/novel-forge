from __future__ import annotations

from typing import Any


def build_card(knowledge: dict[str, Any]) -> dict[str, Any]:
    content = knowledge.get("content", {})
    return {
        "asset_type": "genre_seed_card",
        "title": f"Genre seed: {knowledge.get('title')}",
        "content": {
            "genre_seed": content.get("concept_name") or knowledge.get("title"),
            "market_angle": content.get("narrative_function", ""),
            "creative_principle": content.get("creative_principle", ""),
            "applicable_flows": content.get("applicable_flows", []),
            "source_knowledge_id": knowledge.get("id", ""),
            "evidence_refs": _evidence_refs(knowledge),
            "source_isolation": _source_isolation(),
        },
    }


def _evidence_refs(knowledge: dict[str, Any]) -> list[str]:
    content = knowledge.get("content", {})
    return [str(item) for item in [*(content.get("source_chunk_ids") or []), *(content.get("evidence_span_refs") or []), *(knowledge.get("references") or [])] if str(item).strip()]


def _source_isolation() -> dict[str, bool]:
    return {"raw_text_included": False, "clean_text_included": False, "parallel_pair_text_included": False}
