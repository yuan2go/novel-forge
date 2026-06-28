from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from novel_forge.core.constants import DATA_DIRS
from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.agent_runs import AgentExecutionContext
from novel_forge.modules.common import resolve_path
from novel_forge.modules.production_context import filter_project_safe_references
from novel_forge.schemas import NovelKGSnapshot, validate_common_fields
from novel_forge.storage.local import LocalStorage

ONTOLOGY_VERSION = "novel-kg-0.1.0"
NOVEL_KG_TYPES = {
    "character_card",
    "world_bible",
    "continuity_bible",
    "foreshadowing_thread",
    "power_scale_rule",
    "review_rule_pack",
    "quality_standard_profile",
    "writing_template",
    "craft_template",
    "material_card",
    "knowledge_card",
    "outline",
    "outline_version",
    "long_form_macro_plan",
    "chapter_plan",
    "chapter_plan_version",
    "draft_chapter",
    "draft_version",
    "chapter_audit_report",
    "review_report",
    "revision_plan",
    "canon_graph_snapshot",
    "canon_patch",
}


def build_novel_kg(
    storage: LocalStorage,
    *,
    project_id: str | None = None,
    workspace_path: str | None = None,
    limit: int = 1000,
    include_content_snapshot: bool = False,
) -> dict[str, Any]:
    storage.ensure_layout()
    assets = _load_kg_assets(storage, project_id=project_id, workspace_path=workspace_path, limit=limit)
    with AgentExecutionContext(
        storage,
        agent_key="continuity",
        operation="build-novel-kg",
        output_types=["novel_kg_snapshot"],
        workspace_path=workspace_path,
        sla_seconds=900,
    ) as run:
        run.guard("build_novel_kg")
        graph = _project_assets(storage, assets, include_content_snapshot=include_content_snapshot)
        graph.update(
            {
                "kg_id": make_id("novel_kg", project_id or workspace_path or "global"),
                "ontology_version": ONTOLOGY_VERSION,
                "project_id": project_id or "global",
                "workspace_path": workspace_path or "",
                "built_at": utc_now(),
            }
        )
        run.succeed(token_used=sum(len(graph.get(key, [])) for key in _ontology_collection_keys()))
        return graph


def create_novel_kg_snapshot(
    storage: LocalStorage,
    *,
    project_id: str | None = None,
    workspace_path: str | None = None,
    limit: int = 1000,
    include_content_snapshot: bool = False,
) -> dict[str, Any]:
    graph = build_novel_kg(
        storage,
        project_id=project_id,
        workspace_path=workspace_path,
        limit=limit,
        include_content_snapshot=include_content_snapshot,
    )
    with AgentExecutionContext(
        storage,
        agent_key="continuity",
        operation="create-novel-kg-snapshot",
        output_types=["novel_kg_snapshot"],
        workspace_path=workspace_path,
        sla_seconds=600,
    ) as run:
        run.guard("write_novel_kg_snapshot", "novel_kg_snapshot")
        asset = NovelKGSnapshot(
            title="Novel Knowledge Graph snapshot",
            tags=["novel-kg", "knowledge-graph", "snapshot"],
            content={
                **graph,
                "created_at": utc_now(),
            },
            metadata={"project_id": project_id or "", "workspace_path": workspace_path or "", "ontology_version": ONTOLOGY_VERSION},
            references=filter_project_safe_references(storage, project_id or "", _graph_references(graph)),
        )
        result = _write(storage, asset)
        run.succeed(output_assets=[result["path"]], token_used=sum(len(graph.get(key, [])) for key in _ontology_collection_keys()))
        return result


def query_novel_kg(
    storage: LocalStorage,
    *,
    snapshot_path: str | Path | None = None,
    project_id: str | None = None,
    workspace_path: str | None = None,
    kind: str | None = None,
    entity_type: str | None = None,
    q: str | None = None,
    source_asset_id: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    graph = _load_snapshot_or_build(storage, snapshot_path=snapshot_path, project_id=project_id, workspace_path=workspace_path)
    kinds = [kind] if kind else _ontology_collection_keys()
    rows: list[dict[str, Any]] = []
    needle = str(q or "").strip().lower()
    source_filter = str(source_asset_id or "").strip()
    for collection in kinds:
        if collection not in _ontology_collection_keys():
            continue
        for item in graph.get(collection, []) if isinstance(graph.get(collection, []), list) else []:
            if entity_type and str(item.get("entity_type", item.get("rule_type", item.get("template_type", "")))) != entity_type:
                continue
            if source_filter and not _matches_source(item, source_filter):
                continue
            if needle and needle not in _search_text(item):
                continue
            rows.append({"kind": collection, **item})
            if len(rows) >= max(1, int(limit or 100)):
                return {"items": rows, "count": len(rows), "summary": graph.get("summary", {}), "snapshot_path": graph.get("snapshot_path", "")}
    return {"items": rows, "count": len(rows), "summary": graph.get("summary", {}), "snapshot_path": graph.get("snapshot_path", "")}


def _load_kg_assets(storage: LocalStorage, *, project_id: str | None, workspace_path: str | None, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for category in DATA_DIRS:
        for path in storage.list_json(category):
            try:
                data = storage.read_json(path)
            except Exception:
                continue
            if not isinstance(data, dict) or data.get("type") not in NOVEL_KG_TYPES:
                continue
            metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
            row_project = str(metadata.get("project_id", ""))
            row_workspace = str(metadata.get("workspace_path", ""))
            if project_id and row_project and row_project != project_id:
                continue
            if workspace_path and row_workspace and row_workspace != workspace_path:
                continue
            rows.append({"path": _display_path(storage.root, path), "data": data})
            if len(rows) >= max(1, int(limit or 1000)):
                return rows
    return rows


def _project_assets(storage: LocalStorage, assets: list[dict[str, Any]], *, include_content_snapshot: bool) -> dict[str, Any]:
    graph = {key: [] for key in _ontology_collection_keys()}
    graph["source_assets"] = []
    primary_by_asset: dict[str, str] = {}
    entity_by_name: dict[str, str] = {}
    for row in assets:
        data = row["data"]
        path = row["path"]
        source = _source_row(data, path, include_content_snapshot=include_content_snapshot)
        graph["source_assets"].append(source)
        projection = _project_asset(data, path)
        for key in _ontology_collection_keys():
            graph[key].extend(projection.get(key, []))
        primary = _primary_node_id(projection)
        if primary:
            primary_by_asset[str(data.get("id", ""))] = primary
            primary_by_asset[path] = primary
        for item in projection.get("entities", []):
            name = str(item.get("name", "")).strip().lower()
            if name:
                entity_by_name[name] = str(item.get("id", ""))
    graph["relations"].extend(_reference_relations(assets, primary_by_asset))
    graph["relations"].extend(_name_relations(graph, entity_by_name))
    for key in _ontology_collection_keys():
        if key != "relations":
            graph[key] = _dedupe_items(graph[key])
    graph["relations"].extend(_semantic_relations(graph))
    graph["relations"] = _dedupe_items(graph["relations"])
    graph["summary"] = _summary(graph)
    return graph


def _project_asset(data: dict[str, Any], path: str) -> dict[str, list[dict[str, Any]]]:
    asset_type = str(data.get("type", ""))
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    title = str(data.get("title") or data.get("name") or data.get("id") or "")
    result = {key: [] for key in _ontology_collection_keys()}
    if asset_type == "character_card":
        result["entities"].append(_node("entity", data, path, "character", _first(content, ["name", "role"], title), attributes=_pick(content, ["role", "external_goal", "internal_need", "motivation_chain", "power_level", "current_location", "faction"])))
        if content.get("faction") or content.get("affiliation"):
            result["factions"].append(_node("faction", data, path, "affiliation", str(content.get("faction") or content.get("affiliation")), attributes={"character": _first(content, ["name"], title)}))
        if content.get("current_location") or content.get("location"):
            result["locations"].append(_node("location", data, path, "current_location", str(content.get("current_location") or content.get("location")), attributes={"character": _first(content, ["name"], title)}))
    elif asset_type in {"world_bible", "continuity_bible"}:
        result["entities"].extend(_entity_items(data, path, _list_items(content.get("entities")), default_type="canon_entity"))
        result["factions"].extend(_named_items(data, path, "faction", _list_items(_first_value(content, ["factions", "forces", "organizations", "sects"])), default_type="faction"))
        result["locations"].extend(_named_items(data, path, "location", _list_items(_first_value(content, ["locations", "places", "regions"])), default_type="location"))
        result["props"].extend(_named_items(data, path, "prop", _list_items(_first_value(content, ["props", "items", "artifacts", "resources"])), default_type="prop"))
        result["rules"].extend(_rule_items(data, path, _list_items(_first_value(content, ["rules", "worldview_rules", "constraints"])), rule_type="world_rule"))
        result["timelines"].extend(_timeline_items(data, path, _list_items(content.get("timeline"))))
    elif asset_type == "foreshadowing_thread":
        result["foreshadowing"].append(_node("foreshadowing", data, path, str(content.get("status") or "planned"), str(content.get("thread_id") or title), attributes=_pick(content, ["setup", "payoff_plan", "status", "related_chapters"])))
        result["events"].extend(_event_items(data, path, _list_items(content.get("related_chapters")), event_type="foreshadowing_marker"))
    elif asset_type == "power_scale_rule":
        result["power_scales"].append(_node("power_scale", data, path, "power_scale", str(content.get("scale_id") or title), attributes=_pick(content, ["levels", "constraints", "violation_checks"])))
        result["rules"].extend(_rule_items(data, path, _list_items(content.get("constraints")), rule_type="power_scale_constraint"))
    elif asset_type in {"review_rule_pack", "quality_standard_profile"}:
        result["review_rules"].append(_node("review_rule", data, path, asset_type, str(content.get("rule_pack_id") or content.get("standard_id") or title), attributes=_pick(content, ["dimensions", "checks", "severity_policy", "hard_gates"])))
        result["rules"].extend(_rule_items(data, path, _list_items(content.get("hard_gates")), rule_type="quality_gate"))
    elif asset_type in {"writing_template", "craft_template", "material_card", "knowledge_card"}:
        result["templates"].append(_node("template", data, path, asset_type, str(content.get("template_id") or content.get("name") or title), attributes=_pick(content, ["template_kind", "craft_domain", "structure", "pattern", "usage_constraints", "usable_patterns", "principles"])))
    elif asset_type in {"outline", "outline_version", "long_form_macro_plan"}:
        result["timelines"].extend(_outline_timeline_items(data, path, _list_items(content.get("acts"))))
        result["events"].extend(_outline_event_items(data, path, _list_items(content.get("acts"))))
    elif asset_type in {"chapter_plan", "chapter_plan_version"}:
        chapter = content.get("chapter", "")
        result["events"].append(_node("event", data, path, "chapter_plan", title, attributes={"chapter": chapter, "objective": content.get("objective", ""), "hook": content.get("hook", "")}))
        result["timelines"].append(_node("timeline", data, path, "chapter", f"chapter {chapter}", attributes={"chapter": chapter, "beats": content.get("beats", [])}))
    elif asset_type in {"draft_chapter", "draft_version"}:
        result["events"].append(_node("event", data, path, "draft_chapter", title, attributes={"chapter": content.get("chapter", ""), "status": data.get("metadata", {}).get("asset_status", "") if isinstance(data.get("metadata", {}), dict) else ""}))
    elif asset_type == "canon_graph_snapshot":
        result["entities"].extend(_canon_entities(data, path, content.get("entities", [])))
        result["relations"].extend(_canon_relations(data, path, content.get("relationships", [])))
        result["events"].extend(_event_items(data, path, _list_items(content.get("event_graph")), event_type="canon_event"))
    elif asset_type == "canon_patch":
        result["events"].extend(_event_items(data, path, _list_items(content.get("proposed_events")), event_type="canon_patch_event"))
        result["relations"].extend(_canon_relations(data, path, content.get("relationship_updates", [])))
    elif asset_type in {"review_report", "chapter_audit_report", "revision_plan"}:
        result["review_rules"].append(_node("review_rule", data, path, asset_type, title, attributes=_pick(content, ["issues", "gate_results", "recommendation", "revision_tasks"])))
    return result


def _source_row(data: dict[str, Any], path: str, *, include_content_snapshot: bool) -> dict[str, Any]:
    row = {
        "asset_id": data.get("id", ""),
        "asset_type": data.get("type", ""),
        "title": data.get("title") or data.get("name") or "",
        "path": path,
        "project_id": (data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}).get("project_id", ""),
        "workspace_path": (data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}).get("workspace_path", ""),
    }
    if include_content_snapshot:
        row["content"] = data.get("content", {})
    return row


def _node(kind: str, data: dict[str, Any], path: str, subtype: str, name: str, *, attributes: dict[str, Any] | None = None) -> dict[str, Any]:
    clean_name = str(name or "").strip() or str(data.get("title") or data.get("id") or kind)
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    return {
        "id": _kg_id(kind, data.get("id", ""), subtype, clean_name),
        "kind": kind,
        "entity_type": subtype,
        "name": clean_name,
        "source_asset_id": data.get("id", ""),
        "source_asset_type": data.get("type", ""),
        "source_path": path,
        "project_id": metadata.get("project_id", ""),
        "workspace_path": metadata.get("workspace_path", ""),
        "attributes": attributes or {},
        "evidence": {"title": data.get("title") or data.get("name") or "", "source": data.get("source", "")},
    }


def _entity_items(data: dict[str, Any], path: str, items: list[Any], *, default_type: str) -> list[dict[str, Any]]:
    rows = []
    for item in items:
        if isinstance(item, dict):
            name = _first(item, ["name", "title", "id"], "")
            subtype = str(item.get("entity_type") or item.get("type") or default_type)
            attrs = dict(item)
        else:
            name = str(item)
            subtype = default_type
            attrs = {}
        if str(name).strip():
            rows.append(_node("entity", data, path, subtype, str(name), attributes=attrs))
    return rows


def _named_items(data: dict[str, Any], path: str, kind: str, items: list[Any], *, default_type: str) -> list[dict[str, Any]]:
    rows = []
    for item in items:
        if isinstance(item, dict):
            name = _first(item, ["name", "title", "id"], "")
            attrs = dict(item)
            subtype = str(item.get("type") or item.get(f"{kind}_type") or default_type)
        else:
            name = str(item)
            attrs = {}
            subtype = default_type
        if str(name).strip():
            rows.append(_node(kind, data, path, subtype, str(name), attributes=attrs))
    return rows


def _rule_items(data: dict[str, Any], path: str, items: list[Any], *, rule_type: str) -> list[dict[str, Any]]:
    rows = []
    for item in items:
        attrs = dict(item) if isinstance(item, dict) else {"text": str(item)}
        name = _first(attrs, ["name", "title", "rule", "text", "id"], "")
        if str(name).strip():
            row = _node("rule", data, path, rule_type, str(name), attributes=attrs)
            row["rule_type"] = rule_type
            rows.append(row)
    return rows


def _timeline_items(data: dict[str, Any], path: str, items: list[Any]) -> list[dict[str, Any]]:
    rows = []
    for item in items:
        attrs = dict(item) if isinstance(item, dict) else {"text": str(item)}
        name = _first(attrs, ["chapter", "name", "title", "event", "text"], "")
        if str(name).strip():
            rows.append(_node("timeline", data, path, "canon_timeline", str(name), attributes=attrs))
    return rows


def _event_items(data: dict[str, Any], path: str, items: list[Any], *, event_type: str) -> list[dict[str, Any]]:
    rows = []
    for item in items:
        attrs = dict(item) if isinstance(item, dict) else {"text": str(item)}
        name = _first(attrs, ["event", "name", "title", "summary", "text", "chapter"], "")
        if str(name).strip():
            rows.append(_node("event", data, path, event_type, str(name), attributes=attrs))
    return rows


def _outline_timeline_items(data: dict[str, Any], path: str, acts: list[Any]) -> list[dict[str, Any]]:
    rows = []
    for act in acts:
        if not isinstance(act, dict):
            continue
        rows.append(_node("timeline", data, path, "outline_act", str(act.get("goal") or act.get("act") or "act"), attributes=act))
        for chapter in _list_items(act.get("chapters")):
            attrs = dict(chapter) if isinstance(chapter, dict) else {"chapter": chapter}
            rows.append(_node("timeline", data, path, "outline_chapter", str(attrs.get("chapter") or attrs.get("promise") or "chapter"), attributes=attrs))
    return rows


def _outline_event_items(data: dict[str, Any], path: str, acts: list[Any]) -> list[dict[str, Any]]:
    events = []
    for act in acts:
        if not isinstance(act, dict):
            continue
        for chapter in _list_items(act.get("chapters")):
            attrs = dict(chapter) if isinstance(chapter, dict) else {"chapter": chapter}
            events.append(_node("event", data, path, "outline_chapter", str(attrs.get("promise") or attrs.get("hook") or attrs.get("chapter") or "chapter"), attributes=attrs))
    return events


def _canon_entities(data: dict[str, Any], path: str, items: Any) -> list[dict[str, Any]]:
    rows = []
    for item in _list_items(items):
        if not isinstance(item, dict):
            continue
        name = _first(item, ["name", "entity_id", "asset_id"], "")
        if str(name).strip():
            rows.append(_node("entity", data, path, str(item.get("entity_type") or "canon_entity"), str(name), attributes=item))
    return rows


def _canon_relations(data: dict[str, Any], path: str, items: Any) -> list[dict[str, Any]]:
    rows = []
    for item in _list_items(items):
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or item.get("from") or item.get("source_entity") or "")
        target = str(item.get("target") or item.get("to") or item.get("target_entity") or "")
        if not source and not target:
            continue
        rows.append(
            {
                "id": _kg_id("relation", data.get("id", ""), str(item.get("relation") or item.get("type") or "canon_relation"), f"{source}->{target}"),
                "kind": "relation",
                "relation_type": str(item.get("relation") or item.get("type") or "canon_relation"),
                "source": source,
                "target": target,
                "source_asset_id": data.get("id", ""),
                "source_asset_type": data.get("type", ""),
                "source_path": path,
                "attributes": dict(item),
            }
        )
    return rows


def _reference_relations(assets: list[dict[str, Any]], primary_by_asset: dict[str, str]) -> list[dict[str, Any]]:
    rows = []
    for row in assets:
        data = row["data"]
        source_node = primary_by_asset.get(str(data.get("id", ""))) or primary_by_asset.get(row["path"])
        if not source_node:
            continue
        for ref in _reference_values(data):
            target_node = primary_by_asset.get(ref)
            if not target_node or target_node == source_node:
                continue
            rows.append(
                {
                    "id": _kg_id("relation", data.get("id", ""), "references", f"{source_node}->{target_node}"),
                    "kind": "relation",
                    "relation_type": "references",
                    "source": source_node,
                    "target": target_node,
                    "source_asset_id": data.get("id", ""),
                    "source_asset_type": data.get("type", ""),
                    "source_path": row["path"],
                    "attributes": {"reference": ref},
                }
            )
    return rows


def _name_relations(graph: dict[str, Any], entity_by_name: dict[str, str]) -> list[dict[str, Any]]:
    rows = []
    for event in graph.get("events", []):
        text = _search_text(event)
        for name, entity_id in entity_by_name.items():
            if name and name in text and entity_id != event.get("id"):
                rows.append(
                    {
                        "id": _kg_id("relation", event.get("id", ""), "mentions", entity_id),
                        "kind": "relation",
                        "relation_type": "mentions",
                        "source": str(event.get("id", "")),
                        "target": entity_id,
                        "source_asset_id": event.get("source_asset_id", ""),
                        "source_asset_type": event.get("source_asset_type", ""),
                        "source_path": event.get("source_path", ""),
                        "attributes": {"matched_name": name},
                    }
                )
    return rows


def _semantic_relations(graph: dict[str, Any]) -> list[dict[str, Any]]:
    faction_by_name = _node_index_by_name(graph.get("factions", []))
    location_by_name = _node_index_by_name(graph.get("locations", []))
    rows: list[dict[str, Any]] = []
    for entity in graph.get("entities", []):
        if not isinstance(entity, dict) or str(entity.get("entity_type", "")) != "character":
            continue
        attrs = entity.get("attributes", {}) if isinstance(entity.get("attributes", {}), dict) else {}
        faction = str(attrs.get("faction") or attrs.get("affiliation") or "").strip().lower()
        if faction and faction in faction_by_name:
            rows.append(_semantic_relation(entity, faction_by_name[faction], "affiliated_with", {"name": faction}))
        location = str(attrs.get("current_location") or attrs.get("location") or "").strip().lower()
        if location and location in location_by_name:
            rows.append(_semantic_relation(entity, location_by_name[location], "located_at", {"name": location}))
    return rows


def _semantic_relation(source: dict[str, Any], target_id: str, relation_type: str, attributes: dict[str, Any]) -> dict[str, Any]:
    source_id = str(source.get("id", ""))
    return {
        "id": _kg_id("relation", source_id, relation_type, target_id),
        "kind": "relation",
        "relation_type": relation_type,
        "source": source_id,
        "target": target_id,
        "source_asset_id": source.get("source_asset_id", ""),
        "source_asset_type": source.get("source_asset_type", ""),
        "source_path": source.get("source_path", ""),
        "attributes": attributes,
    }


def _node_index_by_name(items: Any) -> dict[str, str]:
    index: dict[str, str] = {}
    if not isinstance(items, list):
        return index
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip().lower()
        node_id = str(item.get("id", "")).strip()
        if name and node_id and name not in index:
            index[name] = node_id
    return index


def _load_snapshot_or_build(storage: LocalStorage, *, snapshot_path: str | Path | None, project_id: str | None, workspace_path: str | None) -> dict[str, Any]:
    if snapshot_path:
        path = resolve_path(storage.root, snapshot_path)
        data = storage.read_json(path)
        content = data.get("content", {}) if isinstance(data, dict) and isinstance(data.get("content", {}), dict) else {}
        content["snapshot_path"] = _display_path(storage.root, path)
        return content
    return build_novel_kg(storage, project_id=project_id, workspace_path=workspace_path)


def _write(storage: LocalStorage, asset: NovelKGSnapshot) -> dict[str, Any]:
    path = storage.write_asset("continuity", asset)
    data = storage.read_json(path)
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    return {"path": _display_path(storage.root, path), "id": asset.id, "asset": data, "validation": {"ok": True, "errors": []}}


def _ontology_collection_keys() -> list[str]:
    return ["entities", "relations", "events", "rules", "timelines", "foreshadowing", "factions", "locations", "props", "power_scales", "review_rules", "templates"]


def _summary(graph: dict[str, Any]) -> dict[str, Any]:
    by_source_type: dict[str, int] = {}
    for source in graph.get("source_assets", []):
        source_type = str(source.get("asset_type", ""))
        by_source_type[source_type] = by_source_type.get(source_type, 0) + 1
    return {
        "source_asset_count": len(graph.get("source_assets", [])),
        "counts": {key: len(graph.get(key, [])) for key in _ontology_collection_keys()},
        "by_source_type": by_source_type,
    }


def _primary_node_id(projection: dict[str, list[dict[str, Any]]]) -> str:
    for key in ["entities", "factions", "locations", "props", "power_scales", "review_rules", "templates", "events", "rules", "timelines", "foreshadowing"]:
        rows = projection.get(key, [])
        if rows:
            return str(rows[0].get("id", ""))
    return ""


def _graph_references(graph: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for source in graph.get("source_assets", []):
        refs.extend([str(source.get("asset_id", "")), str(source.get("path", ""))])
    return _dedupe(refs)


def _reference_values(data: dict[str, Any]) -> list[str]:
    values = [str(data.get("source", ""))]
    if isinstance(data.get("references", []), list):
        values.extend(str(item) for item in data.get("references", []) if str(item).strip())
    return _dedupe([item for item in values if item])


def _list_items(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, dict):
        return [value]
    if isinstance(value, str):
        return [item.strip() for item in value.splitlines() if item.strip()] or [value]
    return [value]


def _first(payload: dict[str, Any], keys: list[str], default: Any = "") -> Any:
    for key in keys:
        value = payload.get(key)
        if value is not None and value != "":
            return value
    return default


def _first_value(payload: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        value = payload.get(key)
        if value:
            return value
    return []


def _pick(payload: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    return {key: payload.get(key) for key in keys if key in payload}


def _kg_id(kind: str, source_id: Any, subtype: str, name: str) -> str:
    digest = hashlib.sha256(f"{kind}:{source_id}:{subtype}:{name}".encode("utf-8")).hexdigest()[:12]
    return f"kg-{kind}-{digest}"


def _dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    for item in items:
        key = _dedupe_key(item)
        if key in seen:
            existing = seen[key]
            attrs = existing.get("attributes", {}) if isinstance(existing.get("attributes", {}), dict) else {}
            sources = attrs.get("merged_source_asset_ids", []) if isinstance(attrs.get("merged_source_asset_ids", []), list) else []
            for source in [existing.get("source_asset_id", ""), item.get("source_asset_id", "")]:
                if source and source not in sources:
                    sources.append(source)
            attrs["merged_source_asset_ids"] = sources
            existing["attributes"] = attrs
            continue
        seen[key] = item
        rows.append(item)
    return rows


def _dedupe_key(item: dict[str, Any]) -> str:
    kind = str(item.get("kind", ""))
    if kind in {"faction", "location", "prop"}:
        return ":".join(
            [
                kind,
                str(item.get("name", "")).strip().lower(),
                str(item.get("project_id", "")),
            ]
        )
    if kind == "power_scale":
        return ":".join(
            [
                kind,
                str(item.get("entity_type", "")).lower(),
                str(item.get("name", "")).strip().lower(),
                str(item.get("project_id", "")),
            ]
        )
    return str(item.get("id", "")) or repr(sorted(item.items()))


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    rows: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        rows.append(value)
    return rows


def _search_text(item: dict[str, Any]) -> str:
    values = [str(item.get("id", "")), str(item.get("name", "")), str(item.get("entity_type", "")), str(item.get("relation_type", ""))]
    attrs = item.get("attributes", {}) if isinstance(item.get("attributes", {}), dict) else {}
    values.extend(str(value) for value in attrs.values())
    return " ".join(values).lower()


def _matches_source(item: dict[str, Any], source_filter: str) -> bool:
    if str(item.get("source_asset_id", "")) == source_filter:
        return True
    attrs = item.get("attributes", {}) if isinstance(item.get("attributes", {}), dict) else {}
    sources = attrs.get("merged_source_asset_ids", [])
    return isinstance(sources, list) and source_filter in {str(source) for source in sources}


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
