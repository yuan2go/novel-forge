from __future__ import annotations

from typing import Any

from .knowledge_to_genre import _evidence_refs, _source_isolation


def build_card(knowledge: dict[str, Any]) -> dict[str, Any]:
    content = knowledge.get("content", {})
    return {
        "asset_type": "review_rule_card",
        "title": f"Review rule: {knowledge.get('title')}",
        "content": {
            "rule_name": f"{content.get('concept_name') or knowledge.get('title')} creative usage check",
            "rule_type": "knowledge_usage_issue",
            "trigger_condition": content.get("review_function") or "knowledge is used in production asset",
            "check_items": ["knowledge changes action/conflict/consequence", "no encyclopedia explanation", "no source expression reuse"],
            "severity": "high",
            "blocking": True,
            "fix_suggestion": "convert the knowledge into character action, conflict pressure, or scene constraint",
            "applicable_flows": ["prose", "review", "revision"],
            "source_knowledge_id": knowledge.get("id", ""),
            "evidence_refs": _evidence_refs(knowledge),
            "source_isolation": _source_isolation(),
        },
    }
