from __future__ import annotations

from typing import Any

from .knowledge_to_genre import _evidence_refs, _source_isolation


def build_card(knowledge: dict[str, Any]) -> dict[str, Any]:
    content = knowledge.get("content", {})
    return {
        "asset_type": "style_rule_card",
        "title": f"Style rule: {knowledge.get('title')}",
        "content": {
            "style_constraint": content.get("prose_function") or "show knowledge through concrete scene pressure",
            "anti_patterns": content.get("anti_patterns", []),
            "anti_copy_rules": ["no source sentence reuse", "no source-specific scene sequence", "no direct quote unless operator evidence view"],
            "applicable_flows": ["prose", "review"],
            "source_knowledge_id": knowledge.get("id", ""),
            "evidence_refs": _evidence_refs(knowledge),
            "source_isolation": _source_isolation(),
        },
    }
