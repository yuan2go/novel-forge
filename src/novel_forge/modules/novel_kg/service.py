from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from novel_forge.core.constants import DATA_DIRS
from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.agent_runs import AgentExecutionContext
from novel_forge.modules.common import resolve_path
from novel_forge.modules.production_context import filter_project_safe_references
from novel_forge.schemas import NovelKGSnapshot, validate_common_fields
from novel_forge.storage.local import LocalStorage

ONTOLOGY_VERSION = "novel-kg-0.2.0"
ONTOLOGY_SCHEMA_VERSION = "2026-06-kg-typed-v1"
NODE_COLLECTIONS = ["entities", "events", "rules", "timelines", "foreshadowing", "factions", "locations", "props", "power_scales", "review_rules", "templates"]
LABEL_EXTRACTION_PATTERNS = [
    (re.compile(r"(?:人物|角色|character)\s*[:：]\s*([^\n,，;；。]{2,40})", re.IGNORECASE), "entity", "character"),
    (re.compile(r"(?:地点|场景|location|place)\s*[:：]\s*([^\n,，;；。]{2,40})", re.IGNORECASE), "location", "location"),
    (re.compile(r"(?:势力|组织|阵营|faction|organization)\s*[:：]\s*([^\n,，;；。]{2,40})", re.IGNORECASE), "faction", "faction"),
    (re.compile(r"(?:道具|物品|prop|artifact|item)\s*[:：]\s*([^\n,，;；。]{2,40})", re.IGNORECASE), "prop", "prop"),
    (re.compile(r"(?:规则|rule)\s*[:：]\s*([^\n。]{2,80})", re.IGNORECASE), "rule", "extracted_rule"),
    (re.compile(r"(?:伏笔|foreshadowing)\s*[:：]\s*([^\n。]{2,80})", re.IGNORECASE), "foreshadowing", "extracted_foreshadowing"),
    (re.compile(r"(?:模板|template)\s*[:：]\s*([^\n。]{2,80})", re.IGNORECASE), "template", "extracted_template"),
]
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
                "ontology_schema_version": ONTOLOGY_SCHEMA_VERSION,
                "ontology_schema": _ontology_schema(),
                "migrations": _ontology_migrations(),
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


def query_novel_kg_paths(
    storage: LocalStorage,
    *,
    snapshot_path: str | Path | None = None,
    project_id: str | None = None,
    workspace_path: str | None = None,
    source: str,
    target: str,
    max_depth: int = 4,
    relation_type: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    graph = _load_snapshot_or_build(storage, snapshot_path=snapshot_path, project_id=project_id, workspace_path=workspace_path)
    node_index = _all_nodes_by_id(graph)
    source_ids = _resolve_node_ids(graph, source)
    target_ids = set(_resolve_node_ids(graph, target))
    relations = _graph_relations(graph, relation_type=relation_type)
    adjacency = _adjacency(relations, direction="both")
    paths: list[dict[str, Any]] = []
    for source_id in source_ids:
        queue: list[tuple[str, list[str], list[dict[str, Any]]]] = [(source_id, [source_id], [])]
        while queue and len(paths) < max(1, int(limit or 20)):
            node_id, node_path, edge_path = queue.pop(0)
            if node_id in target_ids and edge_path:
                paths.append(
                    {
                        "node_ids": node_path,
                        "nodes": [node_index.get(item, {"id": item, "missing": True}) for item in node_path],
                        "edges": edge_path,
                        "depth": len(edge_path),
                    }
                )
                continue
            if len(edge_path) >= max(1, int(max_depth or 4)):
                continue
            for edge in adjacency.get(node_id, []):
                next_id = str(edge.get("_next", ""))
                if not next_id or next_id in node_path:
                    continue
                queue.append((next_id, [*node_path, next_id], [*edge_path, {key: value for key, value in edge.items() if key != "_next"}]))
    return {"paths": paths, "count": len(paths), "source_candidates": source_ids, "target_candidates": sorted(target_ids), "summary": graph.get("summary", {})}


def query_novel_kg_impact(
    storage: LocalStorage,
    *,
    snapshot_path: str | Path | None = None,
    project_id: str | None = None,
    workspace_path: str | None = None,
    node: str,
    max_depth: int = 3,
    direction: str = "out",
    limit: int = 100,
) -> dict[str, Any]:
    graph = _load_snapshot_or_build(storage, snapshot_path=snapshot_path, project_id=project_id, workspace_path=workspace_path)
    node_index = _all_nodes_by_id(graph)
    start_ids = _resolve_node_ids(graph, node)
    adjacency = _adjacency(_graph_relations(graph), direction=direction)
    visited: set[str] = set(start_ids)
    queue: list[tuple[str, int]] = [(item, 0) for item in start_ids]
    impacted_nodes: list[dict[str, Any]] = []
    impact_edges: list[dict[str, Any]] = []
    while queue and len(impacted_nodes) < max(1, int(limit or 100)):
        current, depth = queue.pop(0)
        if depth >= max(1, int(max_depth or 3)):
            continue
        for edge in adjacency.get(current, []):
            next_id = str(edge.get("_next", ""))
            if not next_id:
                continue
            clean_edge = {key: value for key, value in edge.items() if key != "_next"}
            impact_edges.append(clean_edge)
            if next_id in visited:
                continue
            visited.add(next_id)
            node_payload = dict(node_index.get(next_id, {"id": next_id, "missing": True}))
            node_payload["depth"] = depth + 1
            node_payload["impact_reason"] = str(edge.get("relation_type", edge.get("type", "related")))
            impacted_nodes.append(node_payload)
            queue.append((next_id, depth + 1))
    source_assets = _impacted_source_assets(graph, impacted_nodes)
    return {"start_nodes": [node_index.get(item, {"id": item}) for item in start_ids], "impacted_nodes": impacted_nodes, "impact_edges": _dedupe_relation_rows(impact_edges), "source_assets": source_assets, "count": len(impacted_nodes), "summary": graph.get("summary", {})}


def analyze_novel_kg_conflicts(
    storage: LocalStorage,
    *,
    snapshot_path: str | Path | None = None,
    project_id: str | None = None,
    workspace_path: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    graph = _load_snapshot_or_build(storage, snapshot_path=snapshot_path, project_id=project_id, workspace_path=workspace_path)
    node_index = _all_nodes_by_id(graph)
    conflicts: list[dict[str, Any]] = []
    alias_index: dict[str, list[dict[str, Any]]] = {}
    for item in node_index.values():
        for alias in item.get("aliases", []) if isinstance(item.get("aliases", []), list) else []:
            normalized = _normalize_name(str(alias))
            if normalized:
                alias_index.setdefault(normalized, []).append(item)
    for alias, nodes in alias_index.items():
        canonical_ids = sorted({str(item.get("canonical_id", item.get("id", ""))) for item in nodes if str(item.get("canonical_id", item.get("id", ""))).strip()})
        kinds = sorted({str(item.get("kind", "")) for item in nodes if str(item.get("kind", "")).strip()})
        if len(canonical_ids) > 1 and len(kinds) > 1:
            conflicts.append(
                {
                    "conflict_type": "alias_collision",
                    "severity": "high",
                    "alias": alias,
                    "node_ids": [str(item.get("id", "")) for item in nodes],
                    "message": f"Alias '{alias}' maps to multiple KG node kinds.",
                    "recommendation": "Add explicit aliases or rename one node before using this term in generation context.",
                }
            )
    for relation in _graph_relations(graph):
        source = str(relation.get("source", ""))
        target = str(relation.get("target", ""))
        if source and source not in node_index:
            conflicts.append(_dangling_relation_conflict(relation, "source"))
        if target and target not in node_index:
            conflicts.append(_dangling_relation_conflict(relation, "target"))
    conflicts.extend(_power_level_conflicts(node_index.values()))
    conflicts.extend(_rule_negation_conflicts(graph))
    conflicts = conflicts[: max(1, int(limit or 100))]
    severity_order = {"high": 0, "medium": 1, "low": 2}
    conflicts.sort(key=lambda item: (severity_order.get(str(item.get("severity", "")), 9), str(item.get("conflict_type", ""))))
    return {
        "conflicts": conflicts,
        "count": len(conflicts),
        "blocking_count": sum(1 for item in conflicts if item.get("severity") == "high"),
        "recommendation": "block" if any(item.get("severity") == "high" for item in conflicts) else "review" if conflicts else "pass",
        "summary": graph.get("summary", {}),
    }


def build_novel_kg_cypher(
    *,
    q: str | None = None,
    kind: str | None = None,
    source: str | None = None,
    target: str | None = None,
    relation_type: str | None = None,
    max_depth: int = 4,
    limit: int = 100,
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": max(1, int(limit or 100))}
    if source and target:
        params.update({"source": source, "target": target, "max_depth": max(1, int(max_depth or 4))})
        rel_clause = "" if not relation_type else "{relation_type: $relation_type}"
        if relation_type:
            params["relation_type"] = relation_type
        return {
            "mode": "path",
            "cypher": f"MATCH path=(s:NFNovelKGNode)-[:NF_KG_RELATION{rel_clause}*1..$max_depth]-(t:NFNovelKGNode) WHERE s.id = $source AND t.id = $target RETURN path LIMIT $limit",
            "params": params,
            "execution": "preview_only",
        }
    filters = []
    if q:
        params["q"] = str(q).lower()
        filters.append("(toLower(n.name) CONTAINS $q OR toLower(n.attributes_json) CONTAINS $q)")
    if kind:
        params["kind"] = kind
        filters.append("n.kind = $kind")
    where = f" WHERE {' AND '.join(filters)}" if filters else ""
    return {
        "mode": "search",
        "cypher": f"MATCH (n:NFNovelKGNode){where} RETURN n ORDER BY n.updated_at DESC LIMIT $limit",
        "params": params,
        "execution": "preview_only",
    }


def build_novel_kg_context(
    storage: LocalStorage,
    *,
    target_path: str | Path | None = None,
    query: str = "",
    project_id: str | None = None,
    workspace_path: str | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    graph = build_novel_kg(storage, project_id=project_id, workspace_path=workspace_path)
    target_text = ""
    target_asset_id = ""
    target_display_path = ""
    if target_path:
        path = resolve_path(storage.root, target_path)
        target_display_path = _display_path(storage.root, path)
        try:
            target = storage.read_json(path)
            if isinstance(target, dict):
                target_asset_id = str(target.get("id", ""))
                target_text = _extractable_text(target)
        except Exception:
            target_text = ""
    search = " ".join([query, target_text]).strip().lower()
    candidates: list[dict[str, Any]] = []
    for collection in NODE_COLLECTIONS:
        for item in graph.get(collection, []) if isinstance(graph.get(collection, []), list) else []:
            if not _kg_context_source_allowed(storage, item):
                continue
            score = _kg_context_score(item, search, target_asset_id)
            if score <= 0:
                continue
            candidates.append(_kg_context_candidate(item, score))
    candidates.sort(key=lambda item: (-float(item.get("score", 0) or 0), str(item.get("title", ""))))
    selected = _dedupe_context_candidates(candidates)[: max(1, int(limit or 8))]
    return {
        "target_path": target_display_path,
        "query": query,
        "items": selected,
        "source_asset_ids": _dedupe([str(item.get("asset_id", "")) for item in selected if str(item.get("asset_id", "")).strip()]),
        "kg_summary": graph.get("summary", {}),
        "recommendation": "use_kg_context" if selected else "no_kg_context_match",
    }


def evaluate_novel_kg_gate(
    storage: LocalStorage,
    *,
    snapshot_path: str | Path | None = None,
    target_path: str | Path | None = None,
    project_id: str | None = None,
    workspace_path: str | None = None,
) -> dict[str, Any]:
    target_query = ""
    if target_path:
        try:
            target_query = _extractable_text(storage.read_json(resolve_path(storage.root, target_path)))[:1200]
        except Exception:
            target_query = ""
    conflicts = analyze_novel_kg_conflicts(storage, snapshot_path=snapshot_path, project_id=project_id, workspace_path=workspace_path, limit=200)
    context = build_novel_kg_context(storage, target_path=target_path, query=target_query, project_id=project_id, workspace_path=workspace_path, limit=10)
    blocking = [item for item in conflicts.get("conflicts", []) if item.get("severity") == "high"]
    warnings = [item for item in conflicts.get("conflicts", []) if item.get("severity") != "high"]
    gate_status = "blocked" if blocking else "passed_with_warnings" if warnings else "passed"
    if not context.get("items"):
        warnings.append({"severity": "medium", "conflict_type": "kg_context_missing", "message": "No KG context matched the target asset.", "recommendation": "Bind project story assets before generation or review."})
        gate_status = "passed_with_warnings" if gate_status == "passed" else gate_status
    return {
        "gate": "novel_kg_gate",
        "status": gate_status,
        "gate_status": gate_status,
        "recommendation": "block" if gate_status == "blocked" else "review" if gate_status == "passed_with_warnings" else "pass",
        "blocking_issues": blocking,
        "warnings": warnings,
        "kg_context": context,
        "conflict_summary": {key: conflicts.get(key) for key in ["count", "blocking_count", "recommendation"]},
        "checked": {
            "snapshot_path": str(snapshot_path or ""),
            "target_path": str(target_path or ""),
            "project_id": project_id or "",
            "workspace_path": workspace_path or "",
            "context_item_count": len(context.get("items", [])) if isinstance(context.get("items", []), list) else 0,
        },
    }


def novel_kg_dirty_status(storage: LocalStorage, *, project_id: str | None = None, workspace_path: str | None = None) -> dict[str, Any]:
    path = storage.data_root / "indexes" / "novel_kg_dirty.json"
    if not path.exists():
        return {"dirty": False, "entries": [], "path": _display_path(storage.root, path)}
    try:
        data = storage.read_json(path)
    except Exception:
        return {"dirty": False, "entries": [], "path": _display_path(storage.root, path), "error": "dirty index is unreadable"}
    entries = data.get("entries", []) if isinstance(data, dict) and isinstance(data.get("entries", []), list) else []
    filtered = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if project_id and str(entry.get("project_id", "")) != project_id:
            continue
        if workspace_path and str(entry.get("workspace_path", "")) != workspace_path:
            continue
        filtered.append(entry)
    return {"dirty": bool(filtered), "entries": filtered, "path": _display_path(storage.root, path), "updated_at": data.get("updated_at", "") if isinstance(data, dict) else ""}


def refresh_novel_kg(
    storage: LocalStorage,
    *,
    project_id: str | None = None,
    workspace_path: str | None = None,
    changed_asset_path: str | Path | None = None,
    apply_invalidation: bool = True,
) -> dict[str, Any]:
    status = novel_kg_dirty_status(storage, project_id=project_id, workspace_path=workspace_path)
    snapshot = create_novel_kg_snapshot(storage, project_id=project_id, workspace_path=workspace_path)
    invalidation: dict[str, Any] = {"applied": False}
    if apply_invalidation and changed_asset_path:
        try:
            from novel_forge.modules.change_impact import mark_downstream_assets_stale

            invalidation = mark_downstream_assets_stale(
                storage,
                target_path=str(changed_asset_path),
                project_id=project_id,
                reason="novel kg source asset changed",
                apply=True,
            )
        except Exception as exc:
            invalidation = {"applied": False, "error": f"{type(exc).__name__}: {exc}"}
    _clear_dirty_entries(storage, project_id=project_id, workspace_path=workspace_path)
    return {"snapshot": snapshot, "dirty_before": status, "invalidation": invalidation, "refreshed_at": utc_now()}


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
            graph[key] = _dedupe_items(_normalize_nodes(graph[key], collection=key))
    alias_index = _alias_index(graph)
    graph["relations"].extend(_semantic_relations(graph))
    graph["relations"].extend(_known_mention_relations(assets, alias_index, primary_by_asset))
    graph["relations"] = _dedupe_relation_rows(_normalize_relations(graph["relations"]))
    graph["summary"] = _summary(graph)
    return graph


def _project_asset(data: dict[str, Any], path: str) -> dict[str, list[dict[str, Any]]]:
    asset_type = str(data.get("type", ""))
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    title = str(data.get("title") or data.get("name") or data.get("id") or "")
    result = {key: [] for key in _ontology_collection_keys()}
    if asset_type == "character_card":
        result["entities"].append(_node("entity", data, path, "character", _first(content, ["name", "role"], title), attributes=_pick(content, ["role", "external_goal", "internal_need", "motivation_chain", "power_level", "current_location", "faction", "aliases", "alias", "nicknames"])))
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
    text_nodes = _extract_labeled_text_nodes(data, path, _extractable_text(data))
    for key in _ontology_collection_keys():
        result[key].extend(text_nodes.get(key, []))
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


def _node(
    kind: str,
    data: dict[str, Any],
    path: str,
    subtype: str,
    name: str,
    *,
    attributes: dict[str, Any] | None = None,
    confidence: float = 0.9,
    evidence_spans: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    clean_name = str(name or "").strip() or str(data.get("title") or data.get("id") or kind)
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    attrs = attributes or {}
    return {
        "id": _kg_id(kind, data.get("id", ""), subtype, clean_name),
        "schema_kind": "NovelKGNode",
        "kind": kind,
        "node_type": kind,
        "entity_type": subtype,
        "canonical_id": _canonical_node_id(kind, subtype, clean_name, metadata.get("project_id", "")),
        "name": clean_name,
        "aliases": _aliases_for_node(clean_name, attrs),
        "source_asset_id": data.get("id", ""),
        "source_asset_type": data.get("type", ""),
        "source_path": path,
        "project_id": metadata.get("project_id", ""),
        "workspace_path": metadata.get("workspace_path", ""),
        "confidence": max(0.0, min(1.0, float(confidence))),
        "attributes": attrs,
        "evidence": {"title": data.get("title") or data.get("name") or "", "source": data.get("source", "")},
        "evidence_spans": evidence_spans or _node_evidence_spans(data, path, clean_name),
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


def _extract_labeled_text_nodes(data: dict[str, Any], path: str, text: str) -> dict[str, list[dict[str, Any]]]:
    result = {key: [] for key in _ontology_collection_keys()}
    if not text:
        return result
    for pattern, kind, subtype in LABEL_EXTRACTION_PATTERNS:
        for match in pattern.finditer(text):
            name = _clean_extracted_name(match.group(1))
            if not name:
                continue
            span = _evidence_span(path, "content.text", text, match.start(1), match.end(1), extractor="label_pattern")
            row = _node(kind, data, path, subtype, name, attributes={"extraction": "label_pattern", "label": pattern.pattern}, confidence=0.72, evidence_spans=[span])
            if kind == "rule":
                row["rule_type"] = subtype
                result["rules"].append(row)
            elif kind == "template":
                result["templates"].append(row)
            elif kind == "foreshadowing":
                result["foreshadowing"].append(row)
            elif kind in {"location", "faction", "prop"}:
                result[f"{kind}s" if kind != "faction" else "factions"].append(row)
            else:
                result["entities"].append(row)
    return result


def _known_mention_relations(assets: list[dict[str, Any]], alias_index: dict[str, dict[str, Any]], primary_by_asset: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    aliases = sorted(alias_index.keys(), key=len, reverse=True)
    for row in assets:
        data = row["data"]
        text = _extractable_text(data)
        if not text:
            continue
        source_id = primary_by_asset.get(str(data.get("id", ""))) or primary_by_asset.get(row["path"])
        if not source_id:
            continue
        mention_count = 0
        for alias in aliases:
            if mention_count >= 40:
                break
            if len(alias) < 2:
                continue
            target = alias_index.get(alias, {})
            target_id = str(target.get("id", ""))
            if not target_id or target_id == source_id:
                continue
            spans = _find_text_spans(text, alias, row["path"], limit=3)
            if not spans:
                continue
            mention_count += 1
            rows.append(
                _relation(
                    source_id,
                    target_id,
                    "mentions",
                    source_asset_id=str(data.get("id", "")),
                    source_asset_type=str(data.get("type", "")),
                    source_path=row["path"],
                    attributes={"matched_alias": alias, "target_name": target.get("name", "")},
                    confidence=0.78,
                    evidence_spans=spans,
                )
            )
    return rows


def _normalize_nodes(items: list[dict[str, Any]], *, collection: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or _collection_kind(collection))
        subtype = str(item.get("entity_type") or item.get("rule_type") or item.get("template_type") or kind)
        name = str(item.get("name") or item.get("id") or "")
        project_id = str(item.get("project_id", ""))
        attrs = item.get("attributes", {}) if isinstance(item.get("attributes", {}), dict) else {}
        normalized = {
            **item,
            "schema_kind": "NovelKGNode",
            "kind": kind,
            "node_type": kind,
            "entity_type": subtype,
            "canonical_id": str(item.get("canonical_id") or _canonical_node_id(kind, subtype, name, project_id)),
            "aliases": _aliases_for_node(name, attrs, existing=item.get("aliases", [])),
            "confidence": _safe_confidence(item.get("confidence", 0.9)),
            "evidence_spans": _normalize_evidence_spans(item.get("evidence_spans", [])),
        }
        rows.append(normalized)
    return rows


def _normalize_relations(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source", ""))
        target = str(item.get("target", ""))
        relation_type = str(item.get("relation_type") or item.get("type") or "related_to")
        rows.append(
            {
                **item,
                "id": str(item.get("id") or _kg_id("relation", source, relation_type, target)),
                "schema_kind": "NovelKGEdge",
                "kind": "relation",
                "edge_type": relation_type,
                "relation_type": relation_type,
                "source": source,
                "target": target,
                "confidence": _safe_confidence(item.get("confidence", 0.82)),
                "evidence_spans": _normalize_evidence_spans(item.get("evidence_spans", [])),
            }
        )
    return rows


def _relation(
    source: str,
    target: str,
    relation_type: str,
    *,
    source_asset_id: str = "",
    source_asset_type: str = "",
    source_path: str = "",
    attributes: dict[str, Any] | None = None,
    confidence: float = 0.82,
    evidence_spans: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": _kg_id("relation", source, relation_type, target),
        "schema_kind": "NovelKGEdge",
        "kind": "relation",
        "edge_type": relation_type,
        "relation_type": relation_type,
        "source": source,
        "target": target,
        "source_asset_id": source_asset_id,
        "source_asset_type": source_asset_type,
        "source_path": source_path,
        "confidence": _safe_confidence(confidence),
        "attributes": attributes or {},
        "evidence_spans": evidence_spans or [],
    }


def _alias_index(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for collection in NODE_COLLECTIONS:
        for item in graph.get(collection, []) if isinstance(graph.get(collection, []), list) else []:
            if not isinstance(item, dict):
                continue
            for alias in item.get("aliases", []) if isinstance(item.get("aliases", []), list) else []:
                normalized = _normalize_name(str(alias))
                if normalized and normalized not in index:
                    index[normalized] = item
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
    confidences: list[float] = []
    for key in NODE_COLLECTIONS:
        rows = graph.get(key, [])
        if not isinstance(rows, list):
            continue
        confidences.extend(float(item.get("confidence", 0.0) or 0.0) for item in rows if isinstance(item, dict))
    return {
        "source_asset_count": len(graph.get("source_assets", [])),
        "counts": {key: len(graph.get(key, [])) for key in _ontology_collection_keys()},
        "by_source_type": by_source_type,
        "confidence": {
            "average": round(sum(confidences) / len(confidences), 4) if confidences else 0,
            "low_confidence_count": sum(1 for value in confidences if value < 0.75),
        },
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
            existing["aliases"] = _dedupe([*[str(alias) for alias in existing.get("aliases", []) if str(alias).strip()], *[str(alias) for alias in item.get("aliases", []) if str(alias).strip()]])
            existing["evidence_spans"] = _merge_evidence_spans(existing.get("evidence_spans", []), item.get("evidence_spans", []))
            existing["confidence"] = max(_safe_confidence(existing.get("confidence", 0.0)), _safe_confidence(item.get("confidence", 0.0)))
            continue
        seen[key] = item
        rows.append(item)
    return rows


def _dedupe_key(item: dict[str, Any]) -> str:
    canonical_id = str(item.get("canonical_id", "")).strip()
    if canonical_id:
        return canonical_id
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


def _dedupe_relation_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    for item in items:
        key = str(item.get("id", "")) or f"{item.get('source', '')}:{item.get('relation_type', '')}:{item.get('target', '')}"
        if key in seen:
            existing = seen[key]
            existing["evidence_spans"] = _merge_evidence_spans(existing.get("evidence_spans", []), item.get("evidence_spans", []))
            existing["confidence"] = max(_safe_confidence(existing.get("confidence", 0.0)), _safe_confidence(item.get("confidence", 0.0)))
            continue
        seen[key] = item
        rows.append(item)
    return rows


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


def _ontology_schema() -> dict[str, Any]:
    return {
        "schema_version": ONTOLOGY_SCHEMA_VERSION,
        "node_collections": NODE_COLLECTIONS,
        "edge_collection": "relations",
        "node_required": ["id", "schema_kind", "kind", "canonical_id", "name", "aliases", "confidence", "evidence_spans", "source_asset_id"],
        "edge_required": ["id", "schema_kind", "relation_type", "source", "target", "confidence", "evidence_spans"],
        "evidence_span": ["source_path", "field_path", "start", "end", "snippet", "extractor"],
        "confidence_policy": {
            "structured_asset": 0.9,
            "label_pattern_extraction": 0.72,
            "known_alias_mention": 0.78,
            "semantic_relation": 0.82,
        },
    }


def _ontology_migrations() -> list[dict[str, str]]:
    return [
        {"from": "novel-kg-0.1.0", "to": "novel-kg-0.2.0", "change": "add typed node/edge contract, canonical_id, aliases, evidence_spans, confidence, query diagnostics"},
    ]


def _canonical_node_id(kind: str, subtype: str, name: str, project_id: Any) -> str:
    normalized = _normalize_name(name)
    semantic_subtype = "" if kind in {"faction", "location", "prop"} else subtype
    digest = hashlib.sha256(f"{project_id}:{kind}:{semantic_subtype}:{normalized}".encode("utf-8")).hexdigest()[:14]
    return f"kgc-{kind}-{digest}"


def _aliases_for_node(name: str, attrs: dict[str, Any], *, existing: Any = None) -> list[str]:
    aliases: list[str] = [str(name).strip()]
    for value in _list_items(existing):
        if str(value).strip():
            aliases.append(str(value).strip())
    for key in ["alias", "aliases", "nicknames", "other_names", "aka"]:
        value = attrs.get(key)
        for item in _list_items(value):
            if isinstance(item, dict):
                candidate = _first(item, ["name", "alias", "title"], "")
            else:
                candidate = item
            if str(candidate).strip():
                aliases.append(str(candidate).strip())
    aliases.extend(_parenthetical_aliases(name))
    return _dedupe([item for item in aliases if item])


def _parenthetical_aliases(name: str) -> list[str]:
    text = str(name)
    aliases: list[str] = []
    for pattern in [r"(.+?)\((.+?)\)", r"(.+?)（(.+?)）"]:
        match = re.match(pattern, text)
        if match:
            aliases.extend([match.group(1).strip(), match.group(2).strip()])
    return aliases


def _normalize_name(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().lower())


def _clean_extracted_name(value: str) -> str:
    clean = str(value or "").strip().strip("-*# \t")
    clean = re.split(r"[。.!?？]", clean, maxsplit=1)[0].strip()
    clean = re.split(r"\s+(?:and|or|into|enters|finds|demands|rings|follows|raises|requires|uses|opens|controls)\b", clean, maxsplit=1, flags=re.IGNORECASE)[0].strip()
    title_case = re.match(r"^([A-Z][\w'-]*(?:\s+[A-Z][\w'-]*){0,4})\b", clean)
    if title_case:
        clean = title_case.group(1).strip()
    return clean[:80]


def _extractable_text(data: dict[str, Any]) -> str:
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    fields = []
    for key in ["text", "body", "summary", "objective", "hook", "setup", "payoff_plan", "recommendation", "change_summary"]:
        value = content.get(key)
        if isinstance(value, str):
            fields.append(value)
    for key in ["beats", "scenes", "issues", "revision_tasks", "timeline", "acts"]:
        value = content.get(key)
        if value:
            fields.append(str(value))
    if not fields:
        fields.append(str(content))
    return "\n".join(fields)


def _node_evidence_spans(data: dict[str, Any], path: str, name: str) -> list[dict[str, Any]]:
    text = _extractable_text(data)
    spans = _find_text_spans(text, _normalize_name(name), path, field_path="content", limit=1, normalized=True)
    if spans:
        return spans
    return [_evidence_span(path, "content", text, 0, min(len(text), 120), extractor="structured_asset")]


def _find_text_spans(
    text: str,
    needle: str,
    path: str,
    *,
    field_path: str = "content.text",
    limit: int = 5,
    normalized: bool = False,
) -> list[dict[str, Any]]:
    if not text or not needle:
        return []
    haystack = _normalize_name(text) if normalized else text.lower()
    target = _normalize_name(needle) if normalized else needle.lower()
    if len(target) < 2:
        return []
    spans: list[dict[str, Any]] = []
    start = 0
    while len(spans) < limit:
        index = haystack.find(target, start)
        if index < 0:
            break
        if normalized:
            spans.append(_evidence_span(path, field_path, text, 0, min(len(text), 160), extractor="known_alias_mention"))
            break
        spans.append(_evidence_span(path, field_path, text, index, index + len(needle), extractor="known_alias_mention"))
        start = index + max(1, len(target))
    return spans


def _evidence_span(path: str, field_path: str, text: str, start: int, end: int, *, extractor: str) -> dict[str, Any]:
    safe_start = max(0, min(int(start), len(text)))
    safe_end = max(safe_start, min(int(end), len(text)))
    snippet_start = max(0, safe_start - 48)
    snippet_end = min(len(text), safe_end + 48)
    return {
        "source_path": path,
        "field_path": field_path,
        "start": safe_start,
        "end": safe_end,
        "snippet": _compact_text(text[snippet_start:snippet_end], 160),
        "extractor": extractor,
    }


def _normalize_evidence_spans(value: Any) -> list[dict[str, Any]]:
    rows = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "source_path": str(item.get("source_path", "")),
                "field_path": str(item.get("field_path", "")),
                "start": int(item.get("start", 0) or 0),
                "end": int(item.get("end", 0) or 0),
                "snippet": _compact_text(str(item.get("snippet", "")), 160),
                "extractor": str(item.get("extractor", "")),
            }
        )
    return rows[:20]


def _merge_evidence_spans(left: Any, right: Any) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, int, int]] = set()
    rows: list[dict[str, Any]] = []
    for item in [*_normalize_evidence_spans(left), *_normalize_evidence_spans(right)]:
        key = (item["source_path"], item["field_path"], item["start"], item["end"])
        if key in seen:
            continue
        seen.add(key)
        rows.append(item)
    return rows[:20]


def _safe_confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return 0.0


def _collection_kind(collection: str) -> str:
    if collection == "entities":
        return "entity"
    if collection == "relations":
        return "relation"
    if collection == "power_scales":
        return "power_scale"
    if collection == "review_rules":
        return "review_rule"
    return collection[:-1] if collection.endswith("s") else collection


def _all_nodes_by_id(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for collection in NODE_COLLECTIONS:
        for item in graph.get(collection, []) if isinstance(graph.get(collection, []), list) else []:
            if isinstance(item, dict) and str(item.get("id", "")).strip():
                index[str(item.get("id", ""))] = item
    return index


def _resolve_node_ids(graph: dict[str, Any], value: str) -> list[str]:
    needle = str(value or "").strip()
    if not needle:
        return []
    normalized = _normalize_name(needle)
    matches = []
    for node_id, item in _all_nodes_by_id(graph).items():
        aliases = item.get("aliases", []) if isinstance(item.get("aliases", []), list) else []
        candidates = [node_id, str(item.get("canonical_id", "")), str(item.get("name", "")), *[str(alias) for alias in aliases]]
        if needle in candidates or normalized in {_normalize_name(candidate) for candidate in candidates}:
            matches.append(node_id)
    return _dedupe(matches)


def _graph_relations(graph: dict[str, Any], *, relation_type: str | None = None) -> list[dict[str, Any]]:
    rows = []
    for item in graph.get("relations", []) if isinstance(graph.get("relations", []), list) else []:
        if not isinstance(item, dict):
            continue
        if relation_type and str(item.get("relation_type", "")) != relation_type:
            continue
        rows.append(item)
    return rows


def _adjacency(relations: list[dict[str, Any]], *, direction: str) -> dict[str, list[dict[str, Any]]]:
    adjacency: dict[str, list[dict[str, Any]]] = {}
    for relation in relations:
        source = str(relation.get("source", ""))
        target = str(relation.get("target", ""))
        if source and target and direction in {"out", "both"}:
            adjacency.setdefault(source, []).append({**relation, "_next": target})
        if source and target and direction in {"in", "both"}:
            adjacency.setdefault(target, []).append({**relation, "_next": source})
    return adjacency


def _impacted_source_assets(graph: dict[str, Any], nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    source_by_id = {str(item.get("asset_id", "")): item for item in graph.get("source_assets", []) if isinstance(item, dict)}
    rows = []
    seen: set[str] = set()
    for node in nodes:
        source_id = str(node.get("source_asset_id", ""))
        if not source_id or source_id in seen:
            continue
        seen.add(source_id)
        rows.append(source_by_id.get(source_id, {"asset_id": source_id, "path": node.get("source_path", ""), "asset_type": node.get("source_asset_type", "")}))
    return rows


def _dangling_relation_conflict(relation: dict[str, Any], side: str) -> dict[str, Any]:
    return {
        "conflict_type": "dangling_relation",
        "severity": "high",
        "relation_id": relation.get("id", ""),
        "side": side,
        "message": f"Relation {relation.get('id', '')} has missing {side} node.",
        "recommendation": "Rebuild the KG snapshot or repair source asset references.",
    }


def _power_level_conflicts(nodes: Any) -> list[dict[str, Any]]:
    grouped: dict[str, set[str]] = {}
    names: dict[str, str] = {}
    for item in nodes:
        if not isinstance(item, dict):
            continue
        attrs = item.get("attributes", {}) if isinstance(item.get("attributes", {}), dict) else {}
        value = str(attrs.get("power_level", "")).strip()
        if not value:
            continue
        key = str(item.get("canonical_id", item.get("id", "")))
        grouped.setdefault(key, set()).add(value)
        names[key] = str(item.get("name", ""))
    return [
        {
            "conflict_type": "power_level_conflict",
            "severity": "medium",
            "node_id": key,
            "name": names.get(key, ""),
            "values": sorted(values),
            "message": "Same canonical node has multiple power_level values.",
            "recommendation": "Confirm whether this is an intentional state transition; otherwise update the character card or power scale rule.",
        }
        for key, values in grouped.items()
        if len(values) > 1
    ]


def _rule_negation_conflicts(graph: dict[str, Any]) -> list[dict[str, Any]]:
    rules = graph.get("rules", []) if isinstance(graph.get("rules", []), list) else []
    normalized: dict[str, list[dict[str, Any]]] = {}
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        text = _normalize_rule_text(str(rule.get("name", "")))
        if text:
            normalized.setdefault(text, []).append(rule)
    conflicts = []
    for text, rows in normalized.items():
        has_negation = any(_has_negation(str(row.get("name", ""))) for row in rows)
        has_positive = any(not _has_negation(str(row.get("name", ""))) for row in rows)
        if has_negation and has_positive:
            conflicts.append(
                {
                    "conflict_type": "rule_negation_conflict",
                    "severity": "medium",
                    "rule_key": text,
                    "node_ids": [row.get("id", "") for row in rows],
                    "message": "Rules appear to contain both positive and negated forms of the same constraint.",
                    "recommendation": "Resolve rule wording before using KG gates as hard blockers.",
                }
            )
    return conflicts


def _normalize_rule_text(value: str) -> str:
    text = _normalize_name(value)
    for token in ["不能", "不可", "不要", "不得", "not", "never", "cannot", "can't", "no"]:
        text = text.replace(token, "")
    return text


def _has_negation(value: str) -> bool:
    lower = value.lower()
    return any(token in lower for token in ["不能", "不可", "不要", "不得", "not", "never", "cannot", "can't", " no "])


def _kg_context_score(item: dict[str, Any], search: str, target_asset_id: str) -> float:
    if target_asset_id and str(item.get("source_asset_id", "")) == target_asset_id:
        return 0.0
    text = _search_text(item)
    aliases = item.get("aliases", []) if isinstance(item.get("aliases", []), list) else []
    score = 0.0
    for alias in aliases:
        normalized = _normalize_name(str(alias))
        if normalized and normalized in _normalize_name(search):
            score += 40 + min(20, len(normalized))
    if search and any(token and token in text for token in _query_tokens(search)):
        score += 20
    score += _safe_confidence(item.get("confidence", 0)) * 20
    return round(score, 4)


def _kg_context_candidate(item: dict[str, Any], score: float) -> dict[str, Any]:
    return {
        "asset_id": str(item.get("source_asset_id", "")),
        "path": str(item.get("source_path", "")),
        "type": str(item.get("source_asset_type", "")),
        "title": str(item.get("name", "")),
        "categories": ["novel_kg", str(item.get("kind", "kg"))],
        "score": score,
        "ranker": "novel_kg_context",
        "project_id": str(item.get("project_id", "")),
        "workspace_path": str(item.get("workspace_path", "")),
        "summary": _compact_text(f"{item.get('kind', '')} {item.get('name', '')}: {item.get('attributes', {})}", 480),
        "kg_node_id": str(item.get("id", "")),
        "confidence": item.get("confidence", 0),
        "evidence_spans": item.get("evidence_spans", []),
        "copyright": {"eligible": True, "risk_level": "low", "source": "novel_kg"},
        "selected_by_default": True,
    }


def _kg_context_source_allowed(storage: LocalStorage, item: dict[str, Any]) -> bool:
    source_path = str(item.get("source_path", ""))
    if not source_path:
        return False
    try:
        data = storage.read_json(resolve_path(storage.root, source_path))
    except Exception:
        return False
    metadata = data.get("metadata", {}) if isinstance(data, dict) and isinstance(data.get("metadata", {}), dict) else {}
    content = data.get("content", {}) if isinstance(data, dict) and isinstance(data.get("content", {}), dict) else {}
    risk = str(metadata.get("copyright_risk") or metadata.get("risk_level") or content.get("copyright_risk") or "").lower()
    if risk == "high":
        return False
    if metadata.get("allow_downstream_generation") is False:
        return False
    return str(data.get("type", "")) not in {"source_document", "cleaned_text", "decomposition_report"}


def _query_tokens(value: str) -> list[str]:
    return [token for token in re.split(r"[\s,，。;；:：!?！？]+", value.lower()) if len(token) >= 2][:80]


def _dedupe_context_candidates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for item in items:
        key = str(item.get("path", "")) or str(item.get("kg_node_id", ""))
        if not key or key in seen:
            continue
        seen.add(key)
        rows.append(item)
    return rows


def _clear_dirty_entries(storage: LocalStorage, *, project_id: str | None, workspace_path: str | None) -> None:
    path = storage.data_root / "indexes" / "novel_kg_dirty.json"
    if not path.exists():
        return
    try:
        data = storage.read_json(path)
    except Exception:
        return
    entries = data.get("entries", []) if isinstance(data, dict) and isinstance(data.get("entries", []), list) else []
    remaining = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        project_matches = not project_id or str(entry.get("project_id", "")) == project_id
        workspace_matches = not workspace_path or str(entry.get("workspace_path", "")) == workspace_path
        if project_matches and workspace_matches:
            continue
        remaining.append(entry)
    data["entries"] = remaining
    data["updated_at"] = utc_now()
    storage.write_json(path, data)


def _compact_text(text: str, limit: int) -> str:
    compact = " ".join(str(text).split())
    return compact if len(compact) <= limit else compact[: max(0, limit - 3)] + "..."


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
