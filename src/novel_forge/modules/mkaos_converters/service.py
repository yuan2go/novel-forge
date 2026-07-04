from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules import mkaos as mkaos_service
from novel_forge.modules.common import resolve_path, run_metadata
from novel_forge.schemas import BaseAsset, validate_common_fields
from novel_forge.storage.local import LocalStorage

from . import knowledge_to_chapter_hook, knowledge_to_character, knowledge_to_conflict, knowledge_to_genre, knowledge_to_plot_template, knowledge_to_review_rule, knowledge_to_scene, knowledge_to_style_rule, knowledge_to_world_rule


CONVERTERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "genre_seed_card": knowledge_to_genre.build_card,
    "world_rule_card": knowledge_to_world_rule.build_card,
    "character_archetype_card": knowledge_to_character.build_card,
    "conflict_pattern_card": knowledge_to_conflict.build_card,
    "scene_material_card": knowledge_to_scene.build_card,
    "plot_template_card": knowledge_to_plot_template.build_card,
    "chapter_hook_card": knowledge_to_chapter_hook.build_card,
    "review_rule_card": knowledge_to_review_rule.build_card,
    "style_rule_card": knowledge_to_style_rule.build_card,
}


def convert_creative_assets(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    project_id = str(payload.get("project_id") or "local-system")
    dry_run = bool(payload.get("dry_run", False))
    conversion_types = [str(item) for item in payload.get("conversion_types") or payload.get("target_asset_types") or list(CONVERTERS) if str(item) in CONVERTERS]
    knowledge_rows = _knowledge_inputs(storage, payload)
    converted: list[dict[str, Any]] = []
    linked_rule_cards: list[dict[str, Any]] = []
    linked_template_cards: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []
    for knowledge in knowledge_rows:
        for target_type in conversion_types:
            card_payload = CONVERTERS[target_type](knowledge)
            asset = _creative_asset(project_id, knowledge, target_type, card_payload, payload)
            if dry_run:
                converted.append(asset.to_dict())
                continue
            path = _write(storage, asset)
            saved = storage.read_json(path)
            converted.append(saved)
            relations.append(_write_conversion_relation(storage, project_id, knowledge, saved, payload))
            if target_type == "review_rule_card":
                linked_rule_cards.append(
                    mkaos_service.create_rule_card(
                        storage,
                        {
                            **saved["content"],
                            "project_id": project_id,
                            "source": str(knowledge.get("id") or ""),
                            "trace_id": str(payload.get("trace_id") or ""),
                            "bypass_reason": str(payload.get("bypass_reason") or "creative asset converter"),
                        },
                    )["asset"]
                )
            if target_type == "plot_template_card":
                linked_template_cards.append(
                    mkaos_service.create_template_card(
                        storage,
                        {
                            "project_id": project_id,
                            "template_name": saved["content"].get("template_name") or saved["title"],
                            "template_type": "creative_application",
                            "structure": saved["content"].get("output_structure") or {},
                            "usage_constraints": saved["content"].get("forbidden_usage") or [],
                            "anti_copy_rules": ["no source expression", "abstract application only"],
                            "applicable_flows": saved["content"].get("applicable_flows") or ["outline", "chapter_outline"],
                            "source": str(knowledge.get("id") or ""),
                            "trace_id": str(payload.get("trace_id") or ""),
                            "bypass_reason": str(payload.get("bypass_reason") or "creative asset converter"),
                        },
                    )["asset"]
                )
    return {
        "dry_run": dry_run,
        "converted": converted,
        "converted_count": len(converted),
        "rule_cards": linked_rule_cards,
        "template_cards": linked_template_cards,
        "relations": relations,
        "source_isolation": {"raw_text_included": False, "clean_text_included": False, "parallel_pair_text_included": False},
    }


def _knowledge_inputs(storage: LocalStorage, payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ref in payload.get("knowledge_ids") or payload.get("knowledge_card_ids") or []:
        rows.append(_find_knowledge(storage, str(ref)))
    if not rows and isinstance(payload.get("knowledge_card"), dict):
        rows.append(payload["knowledge_card"])
    if not rows:
        candidates = mkaos_service.list_knowledge_cards(storage, project_id=str(payload.get("project_id") or "") or None, limit=int(payload.get("limit", 50) or 50))
        rows = [row.get("asset", row) for row in candidates if row.get("metadata", {}).get("knowledge_subtype") == "creative_knowledge_card" or row.get("content", {}).get("knowledge_subtype") == "creative_knowledge_card"]
    if not rows:
        raise ValueError("no CreativeKnowledgeCard inputs found")
    return rows


def _find_knowledge(storage: LocalStorage, ref: str) -> dict[str, Any]:
    if "/" in ref or ref.endswith(".json"):
        data = storage.read_json(resolve_path(storage.root, ref))
        if data.get("type") == "knowledge_card":
            return data
    for row in mkaos_service.list_knowledge_cards(storage, limit=2000):
        data = row.get("asset", row)
        if ref in {str(data.get("id") or ""), str(row.get("path") or "")}:
            return data
    raise FileNotFoundError(ref)


def _creative_asset(project_id: str, knowledge: dict[str, Any], target_type: str, payload: dict[str, Any], request: dict[str, Any]) -> BaseAsset:
    content = dict(payload.get("content") or {})
    content.update({
        "project_id": project_id,
        "creative_asset_type": target_type,
        "source_policy": {"raw_source_text_allowed": False, "source_chunk_raw_text_allowed": False, "parallel_pair_text_allowed": False},
        "conversion": {"from_asset_type": "knowledge_card", "from_asset_id": str(knowledge.get("id") or ""), "converter_version": "creative-converter-v1"},
    })
    return BaseAsset(
        id=make_id(target_type, f"{knowledge.get('id')} {target_type}"),
        type=target_type,
        title=str(payload.get("title") or f"{target_type}: {knowledge.get('title')}"),
        source=str(knowledge.get("id") or ""),
        tags=["mkaos", "creative-asset", target_type],
        content=_strip_source_text_fields(content),
        metadata={
            "project_id": project_id,
            "mkaos": True,
            "use_in_generation_rag": False,
            "source_policy": content["source_policy"],
            "trace_id": str(request.get("trace_id") or ""),
            "os_envelope": request.get("os_envelope") if isinstance(request.get("os_envelope"), dict) else {},
            "run_metadata": run_metadata("mkaos.convert_creative_assets", BaseAsset(title=target_type, content={})),
        },
        references=[str(knowledge.get("id") or ""), *[str(item) for item in content.get("evidence_refs", []) if str(item).strip()]],
    )


def _write(storage: LocalStorage, asset: BaseAsset) -> Path:
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    return storage.write_asset("knowledge", asset)


def _write_conversion_relation(storage: LocalStorage, project_id: str, knowledge: dict[str, Any], creative_asset: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    relation = BaseAsset(
        id=make_id("mkaos_graph_relation", f"{knowledge.get('id')} converted_to {creative_asset.get('id')}"),
        type="mkaos_graph_relation",
        title=f"converted_to: {knowledge.get('title')} -> {creative_asset.get('title')}",
        source=str(knowledge.get("id") or ""),
        tags=["mkaos", "knowledge-graph", "converted_to"],
        content={
            "project_id": project_id,
            "relation_type": "converted_to",
            "source_asset_type": "knowledge_card",
            "source_asset_id": str(knowledge.get("id") or ""),
            "target_asset_type": str(creative_asset.get("type") or ""),
            "target_asset_id": str(creative_asset.get("id") or ""),
            "evidence_refs": [str(item) for item in creative_asset.get("references", []) if str(item).strip()],
            "source_isolation": {"raw_text_included": False, "clean_text_included": False, "parallel_pair_text_included": False},
        },
        metadata={"project_id": project_id, "mkaos": True, "use_in_generation_rag": False, "trace_id": str(payload.get("trace_id") or "")},
        references=[str(knowledge.get("id") or ""), str(creative_asset.get("id") or "")],
    )
    path = storage.write_asset("knowledge", relation)
    return storage.read_json(path)


def _strip_source_text_fields(value: Any) -> Any:
    forbidden = {"raw_text", "clean_text", "source_text", "target_text"}
    if isinstance(value, dict):
        return {key: _strip_source_text_fields(item) for key, item in value.items() if key not in forbidden}
    if isinstance(value, list):
        return [_strip_source_text_fields(item) for item in value]
    return value
