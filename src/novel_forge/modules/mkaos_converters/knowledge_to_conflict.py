from __future__ import annotations

from typing import Any

from .knowledge_to_genre import _evidence_refs, _source_isolation


def build_card(knowledge: dict[str, Any]) -> dict[str, Any]:
    content = knowledge.get("content", {})
    return {
        "asset_type": "conflict_pattern_card",
        "title": f"Conflict pattern: {knowledge.get('title')}",
        "content": {
            "conflict_pattern": content.get("conflict_function") or content.get("creative_principle", ""),
            "choice_cost": "force a visible choice, cost, or tradeoff",
            "forbidden_usage": content.get("negative_usage", []),
            "applicable_flows": content.get("applicable_flows", []),
            "source_knowledge_id": knowledge.get("id", ""),
            "evidence_refs": _evidence_refs(knowledge),
            "source_isolation": _source_isolation(),
        },
    }
