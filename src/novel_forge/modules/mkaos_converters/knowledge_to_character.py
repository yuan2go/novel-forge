from __future__ import annotations

from typing import Any

from .knowledge_to_genre import _evidence_refs, _source_isolation


def build_card(knowledge: dict[str, Any]) -> dict[str, Any]:
    content = knowledge.get("content", {})
    return {
        "asset_type": "character_archetype_card",
        "title": f"Character archetype: {knowledge.get('title')}",
        "content": {
            "archetype_mechanism": content.get("character_function") or content.get("creative_principle", ""),
            "motivation_pressure": content.get("conflict_function", ""),
            "positive_usage": content.get("positive_usage", []),
            "anti_patterns": content.get("anti_patterns", []),
            "applicable_flows": content.get("applicable_flows", []),
            "source_knowledge_id": knowledge.get("id", ""),
            "evidence_refs": _evidence_refs(knowledge),
            "source_isolation": _source_isolation(),
        },
    }
