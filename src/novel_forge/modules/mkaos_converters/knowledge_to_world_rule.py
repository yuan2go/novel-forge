from __future__ import annotations

from typing import Any

from .knowledge_to_genre import _evidence_refs, _source_isolation


def build_card(knowledge: dict[str, Any]) -> dict[str, Any]:
    content = knowledge.get("content", {})
    return {
        "asset_type": "world_rule_card",
        "title": f"World rule: {knowledge.get('title')}",
        "content": {
            "rule": content.get("worldbuilding_function") or content.get("creative_principle", ""),
            "constraint": content.get("originality_boundary", ""),
            "narrative_function": content.get("narrative_function", ""),
            "applicable_flows": content.get("applicable_flows", []),
            "source_knowledge_id": knowledge.get("id", ""),
            "evidence_refs": _evidence_refs(knowledge),
            "source_isolation": _source_isolation(),
        },
    }
