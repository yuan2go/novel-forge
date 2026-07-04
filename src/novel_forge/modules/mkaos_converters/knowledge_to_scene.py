from __future__ import annotations

from typing import Any

from .knowledge_to_genre import _evidence_refs, _source_isolation


def build_card(knowledge: dict[str, Any]) -> dict[str, Any]:
    content = knowledge.get("content", {})
    return {
        "asset_type": "scene_material_card",
        "title": f"Scene material: {knowledge.get('title')}",
        "content": {
            "scene_application": content.get("prose_function") or "express through action, prop, setting pressure, or dialogue conflict",
            "pressure_source": content.get("conflict_function", ""),
            "anti_exposition_rule": "do not explain the source concept in prose",
            "applicable_flows": content.get("applicable_flows", []),
            "source_knowledge_id": knowledge.get("id", ""),
            "evidence_refs": _evidence_refs(knowledge),
            "source_isolation": _source_isolation(),
        },
    }
