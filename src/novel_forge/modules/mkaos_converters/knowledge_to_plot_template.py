from __future__ import annotations

from typing import Any

from .knowledge_to_genre import _evidence_refs, _source_isolation


def build_card(knowledge: dict[str, Any]) -> dict[str, Any]:
    content = knowledge.get("content", {})
    return {
        "asset_type": "plot_template_card",
        "title": f"Plot template: {knowledge.get('title')}",
        "content": {
            "template_name": f"{content.get('concept_name') or knowledge.get('title')} application chain",
            "input_fields": ["current_goal", "active_character", "blocking_force", "choice_cost"],
            "application_steps": ["define pressure", "force choice", "show cost", "payoff or reversal", "open next hook"],
            "output_structure": {"beats": ["pressure", "choice", "cost", "payoff", "hook"]},
            "forbidden_usage": content.get("negative_usage", []),
            "success_criteria": ["knowledge changes action", "no source expression copied", "visible conflict exists"],
            "applicable_flows": content.get("applicable_flows", []),
            "source_knowledge_id": knowledge.get("id", ""),
            "evidence_refs": _evidence_refs(knowledge),
            "source_isolation": _source_isolation(),
        },
    }
