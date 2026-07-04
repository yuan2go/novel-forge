from __future__ import annotations

from typing import Any

from .knowledge_to_genre import _evidence_refs, _source_isolation


def build_card(knowledge: dict[str, Any]) -> dict[str, Any]:
    content = knowledge.get("content", {})
    return {
        "asset_type": "chapter_hook_card",
        "title": f"Chapter hook: {knowledge.get('title')}",
        "content": {
            "hook_mechanism": f"turn {content.get('concept_name') or knowledge.get('title')} into a new obligation, risk, or reveal",
            "reader_question": "what cost will the character pay next",
            "payoff_boundary": content.get("originality_boundary", ""),
            "applicable_flows": ["chapter_outline", "prose", "review"],
            "source_knowledge_id": knowledge.get("id", ""),
            "evidence_refs": _evidence_refs(knowledge),
            "source_isolation": _source_isolation(),
        },
    }
