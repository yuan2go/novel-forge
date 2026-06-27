from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.constants import DATA_DIRS
from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.agent_runs import AgentExecutionContext
from novel_forge.modules.common import resolve_path
from novel_forge.modules.production_context import filter_project_safe_references, project_scope_from_asset
from novel_forge.schemas import ChapterContinuityReport, ContinuityGraphSnapshot, CanonGraphSnapshot, validate_common_fields
from novel_forge.storage.local import LocalStorage

CONTINUITY_TYPES = {
    "continuity_bible",
    "foreshadowing_thread",
    "power_scale_rule",
    "world_bible",
    "character_card",
    "outline",
    "outline_version",
    "chapter_plan",
    "chapter_plan_version",
    "draft_chapter",
    "draft_version",
    "review_report",
    "revision_plan",
    "chapter_audit_report",
    "canon_graph_snapshot",
}


def build_continuity_graph(
    storage: LocalStorage,
    *,
    project_id: str | None = None,
    workspace_path: str | None = None,
    limit: int = 500,
    include_content_snapshot: bool = False,
) -> dict[str, Any]:
    storage.ensure_layout()
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    index: dict[str, dict[str, Any]] = {}
    with AgentExecutionContext(
        storage,
        agent_key="continuity",
        operation="build-continuity-graph",
        output_types=["continuity_graph_snapshot"],
        workspace_path=workspace_path,
        sla_seconds=900,
    ) as run:
        run.guard("build_continuity_graph")
        for path in _iter_asset_paths(storage):
            try:
                data = storage.read_json(path)
            except Exception:
                continue
            if not isinstance(data, dict) or data.get("type") not in CONTINUITY_TYPES:
                continue
            metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
            row_project_id = str(metadata.get("project_id", ""))
            row_workspace = str(metadata.get("workspace_path", ""))
            if project_id and row_project_id != project_id:
                continue
            if workspace_path and row_workspace and row_workspace != workspace_path:
                continue
            node = _node(storage, path, data)
            nodes.append(node)
            index[node["id"]] = node
            index[node["path"]] = node
            if len(nodes) >= limit:
                break
        for node in nodes:
            data = node["raw"]
            for ref in _reference_values(data):
                target = index.get(ref)
                if target:
                    edges.append(_edge(node, target, "references", "asset reference"))
            for edge in _content_edges(node, index):
                edges.append(edge)
        graph = {
            "nodes": [_strip_raw(node, include_content_snapshot=include_content_snapshot) for node in nodes],
            "edges": _dedupe_edges(edges),
            "summary": _summary(nodes, edges),
            "built_at": utc_now(),
            "project_id": project_id or "",
            "workspace_path": workspace_path or "",
        }
        run.succeed(token_used=len(nodes) + len(edges))
        return graph


def create_continuity_graph_snapshot(
    storage: LocalStorage,
    *,
    project_id: str | None = None,
    workspace_path: str | None = None,
) -> dict[str, Any]:
    graph = build_continuity_graph(storage, project_id=project_id, workspace_path=workspace_path)
    with AgentExecutionContext(
        storage,
        agent_key="continuity",
        operation="create-continuity-graph-snapshot",
        output_types=["continuity_graph_snapshot"],
        workspace_path=workspace_path,
        sla_seconds=600,
    ) as run:
        run.guard("write_continuity_graph_snapshot", "continuity_graph_snapshot")
        asset = ContinuityGraphSnapshot(
            title="Continuity graph snapshot",
            tags=["continuity", "graph", "snapshot"],
            content={
                "snapshot_id": make_id("continuity_graph", project_id or workspace_path or "global"),
                "project_id": project_id or "global",
                "nodes": graph["nodes"],
                "edges": graph["edges"],
                "summary": graph["summary"],
                "built_at": graph["built_at"],
                "created_at": utc_now(),
            },
            metadata={"project_id": project_id or "", "workspace_path": workspace_path or ""},
            references=filter_project_safe_references(
                storage,
                project_id or "",
                [node["id"] for node in graph["nodes"]] + [node["path"] for node in graph["nodes"]],
            ),
        )
        result = _write(storage, asset)
        run.succeed(output_assets=[result["path"]], token_used=len(graph["nodes"]) + len(graph["edges"]))
        return result


def create_canon_graph_snapshot(
    storage: LocalStorage,
    *,
    project_id: str | None = None,
    workspace_path: str | None = None,
) -> dict[str, Any]:
    graph = build_continuity_graph(storage, project_id=project_id, workspace_path=workspace_path, include_content_snapshot=True)
    canon = _build_canon_graph_payload(graph)
    with AgentExecutionContext(
        storage,
        agent_key="continuity",
        operation="create-canon-graph-snapshot",
        output_types=["canon_graph_snapshot"],
        workspace_path=workspace_path,
        sla_seconds=600,
    ) as run:
        run.guard("write_canon_graph_snapshot", "canon_graph_snapshot")
        asset = CanonGraphSnapshot(
            title="Canon graph snapshot",
            tags=["continuity", "canon", "snapshot"],
            content=canon,
            metadata={"project_id": project_id or "", "workspace_path": workspace_path or "", "risk_level": "high" if canon["violations"] else "low"},
            references=filter_project_safe_references(
                storage,
                project_id or "",
                [node["id"] for node in graph["nodes"]] + [node["path"] for node in graph["nodes"]],
            ),
        )
        result = _write(storage, asset)
        run.succeed(output_assets=[result["path"]], token_used=len(canon["entities"]) + len(canon["relationships"]))
        return result


def create_chapter_continuity_report(
    storage: LocalStorage,
    draft_path: str | Path,
    *,
    workspace_path: str | None = None,
) -> dict[str, Any]:
    path = resolve_path(storage.root, draft_path)
    draft = storage.read_asset(path)
    if draft.type not in {"draft_chapter", "draft_version"}:
        raise ValueError("draft_path must point to draft_chapter or draft_version")
    project = project_scope_from_asset(storage, draft, input_path=path, workspace_path=workspace_path)
    project_id = str(project.get("project_id", ""))
    graph = build_continuity_graph(storage, project_id=project_id or None, workspace_path=str(project.get("workspace_path", "")) or workspace_path)
    checks, violations = _continuity_checks(str(draft.content.get("text", "")), graph)
    recommendation = "block" if any(item["severity"] == "high" for item in violations) else "revise" if violations else "pass"
    with AgentExecutionContext(
        storage,
        agent_key="continuity",
        operation="create-chapter-continuity-report",
        input_assets=[path],
        output_types=["chapter_continuity_report"],
        workspace_path=str(project.get("workspace_path", "")),
        sla_seconds=600,
    ) as run:
        run.guard("read_asset")
        run.guard("write_chapter_continuity_report", "chapter_continuity_report")
        asset = ChapterContinuityReport(
            title=f"Continuity check for {draft.title or draft.id}",
            source=draft.id,
            tags=["continuity", "chapter-check", recommendation],
            content={
                "report_id": make_id("chapter_continuity", draft.id),
                "target_asset_id": draft.id,
                "draft_id": draft.id,
                "draft_path": _display_path(storage.root, path),
                "chapter": draft.content.get("chapter", 1),
                "continuity_checks": checks,
                "violations": violations,
                "graph_summary": graph["summary"],
                "recommendation": recommendation,
                "created_at": utc_now(),
            },
            metadata={"project_id": project_id, "workspace_path": project.get("workspace_path", "")},
            references=filter_project_safe_references(
                storage,
                project_id,
                [draft.id, _display_path(storage.root, path), *[node["id"] for node in graph["nodes"][:80]]],
            ),
        )
        result = _write(storage, asset)
        run.succeed(output_assets=[result["path"]], token_used=len(checks))
        return result


def create_chapter_stability_preflight_report(
    storage: LocalStorage,
    chapter_plan_path: str | Path,
    *,
    workspace_path: str | None = None,
) -> dict[str, Any]:
    path = resolve_path(storage.root, chapter_plan_path)
    plan = storage.read_asset(path)
    if plan.type != "chapter_plan":
        raise ValueError("chapter_plan_path must point to chapter_plan")
    project = project_scope_from_asset(storage, plan, input_path=path, workspace_path=workspace_path)
    project_id = str(project.get("project_id", ""))
    workspace = str(project.get("workspace_path", "") or workspace_path or "")
    graph = build_continuity_graph(storage, project_id=project_id or None, workspace_path=workspace, include_content_snapshot=True)
    chapter = _positive_int(plan.content.get("chapter", 1))
    canon_graph = _build_canon_graph_payload(graph, target_asset=plan.to_dict(), chapter=chapter)
    checks, violations, dimensions = _stability_preflight_checks(plan.to_dict(), graph)
    canon_violations = canon_graph.get("violations", []) if isinstance(canon_graph.get("violations", []), list) else []
    dimensions["canon_graph"] = {
        "status": "blocked" if any(item.get("severity") == "high" for item in canon_violations) else "warning" if canon_violations else "passed",
        "entity_count": len(canon_graph.get("entities", [])),
        "relationship_count": len(canon_graph.get("relationships", [])),
        "event_count": len(canon_graph.get("event_graph", [])),
        "violation_count": len(canon_violations),
        "summary": "checks structured character states, power levels, locations, foreshadowing lifecycle, and event causality",
    }
    checks.append(
        {
            "check": "canon_graph",
            "status": dimensions["canon_graph"]["status"],
            "asset_count": dimensions["canon_graph"]["entity_count"],
            "matched_count": dimensions["canon_graph"]["event_count"],
            "summary": dimensions["canon_graph"]["summary"],
        }
    )
    violations.extend(canon_violations)
    recommendation = "block" if any(item["severity"] == "high" for item in violations) else "revise" if violations else "pass"
    with AgentExecutionContext(
        storage,
        agent_key="continuity",
        operation="create-chapter-stability-preflight-report",
        input_assets=[path],
        output_types=["chapter_continuity_report"],
        workspace_path=workspace,
        sla_seconds=600,
    ) as run:
        run.guard("read_asset")
        run.guard("write_chapter_continuity_report", "chapter_continuity_report")
        asset = ChapterContinuityReport(
            title=f"Long-form stability preflight for {plan.title or plan.id}",
            source=plan.id,
            tags=["continuity", "preflight", "long-form-stability", recommendation],
            content={
                "report_id": make_id("chapter_stability_preflight", plan.id),
                "target_asset_id": plan.id,
                "target_asset_type": plan.type,
                "chapter_plan_id": plan.id,
                "chapter_plan_path": _display_path(storage.root, path),
                "chapter": plan.content.get("chapter", 1),
                "gate": "long_form_stability_preflight",
                "gate_status": "blocked" if recommendation == "block" else "passed_with_warnings" if recommendation == "revise" else "passed",
                "dimensions": dimensions,
                "canon_graph": canon_graph,
                "continuity_checks": checks,
                "violations": violations,
                "blocking_violations": [item for item in violations if item.get("severity") == "high"],
                "graph_summary": graph["summary"],
                "recommendation": recommendation,
                "created_at": utc_now(),
            },
            metadata={"project_id": project_id, "workspace_path": workspace, "gate": "long_form_stability_preflight"},
            references=filter_project_safe_references(
                storage,
                project_id,
                [plan.id, _display_path(storage.root, path), *[node["id"] for node in graph["nodes"][:100]], *[node["path"] for node in graph["nodes"][:100]]],
            ),
        )
        result = _write(storage, asset)
        run.succeed(output_assets=[result["path"]], token_used=len(checks) + len(violations))
        return result


def _build_canon_graph_payload(
    graph: dict[str, Any],
    *,
    target_asset: dict[str, Any] | None = None,
    chapter: int | None = None,
) -> dict[str, Any]:
    nodes = graph.get("nodes", []) if isinstance(graph.get("nodes", []), list) else []
    relationships = [
        {
            "source": edge.get("source", ""),
            "target": edge.get("target", ""),
            "relation": edge.get("relation", ""),
            "evidence": edge.get("evidence", ""),
            "source_path": edge.get("source_path", ""),
            "target_path": edge.get("target_path", ""),
        }
        for edge in graph.get("edges", [])
        if isinstance(edge, dict)
    ]
    entities = _canon_entities(nodes)
    state_machines = _canon_state_machines(nodes, entities)
    lifecycle_threads = _canon_lifecycle_threads(nodes)
    event_graph = _canon_event_graph(nodes, target_asset=target_asset, chapter=chapter)
    violations = _canon_violations(entities, lifecycle_threads, event_graph, target_asset=target_asset, chapter=chapter)
    return {
        "snapshot_id": make_id("canon_graph", graph.get("project_id") or graph.get("workspace_path") or "global"),
        "project_id": graph.get("project_id", "global") or "global",
        "workspace_path": graph.get("workspace_path", ""),
        "entities": entities,
        "relationships": relationships,
        "state_machines": state_machines,
        "lifecycle_threads": lifecycle_threads,
        "event_graph": event_graph,
        "violations": violations,
        "summary": {
            "entity_count": len(entities),
            "relationship_count": len(relationships),
            "state_machine_count": sum(len(value) for value in state_machines.values() if isinstance(value, list)),
            "thread_count": len(lifecycle_threads),
            "event_count": len(event_graph),
            "violation_count": len(violations),
        },
        "built_at": utc_now(),
    }


def _canon_entities(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    for node in nodes:
        content = _node_content(node)
        node_type = str(node.get("type", ""))
        if node_type == "character_card":
            entities.append(
                {
                    "entity_id": str(node.get("id", "")),
                    "asset_id": str(node.get("id", "")),
                    "asset_path": str(node.get("path", "")),
                    "entity_type": "character",
                    "name": str(content.get("name") or node.get("title") or ""),
                    "aliases": content.get("aliases", []) if isinstance(content.get("aliases", []), list) else [],
                    "state": str(content.get("current_state") or content.get("state") or content.get("status") or "active"),
                    "location": str(content.get("current_location") or content.get("location") or ""),
                    "power_level": str(content.get("power_level") or content.get("rank") or content.get("realm") or ""),
                    "chapter": node.get("chapter", ""),
                }
            )
        elif node_type in {"continuity_bible", "world_bible"}:
            for index, item in enumerate(content.get("entities", []) if isinstance(content.get("entities", []), list) else [], start=1):
                if isinstance(item, dict):
                    name = str(item.get("name") or item.get("title") or item.get("id") or "").strip()
                    entity_type = str(item.get("type") or item.get("entity_type") or "canon_entity").strip()
                else:
                    name = str(item).strip()
                    entity_type = "canon_entity"
                if not name:
                    continue
                entities.append(
                    {
                        "entity_id": f"{node.get('id', '')}:entity:{index}",
                        "asset_id": str(node.get("id", "")),
                        "asset_path": str(node.get("path", "")),
                        "entity_type": entity_type,
                        "name": name,
                        "aliases": [],
                        "state": "canon",
                        "location": "",
                        "power_level": "",
                        "chapter": "",
                    }
                )
        elif node_type == "power_scale_rule":
            entities.append(
                {
                    "entity_id": str(node.get("id", "")),
                    "asset_id": str(node.get("id", "")),
                    "asset_path": str(node.get("path", "")),
                    "entity_type": "power_scale",
                    "name": str(node.get("title") or content.get("scale_id") or "power scale"),
                    "aliases": [],
                    "state": "active",
                    "location": "",
                    "power_level": str(content.get("current_level") or content.get("level") or ""),
                    "chapter": "",
                }
            )
    return entities


def _canon_state_machines(nodes: list[dict[str, Any]], entities: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    character_states = [
        {
            "entity_id": entity.get("entity_id", ""),
            "name": entity.get("name", ""),
            "state": entity.get("state", ""),
            "location": entity.get("location", ""),
            "power_level": entity.get("power_level", ""),
            "allowed_transitions": ["active", "injured", "missing", "dead", "transformed"],
        }
        for entity in entities
        if entity.get("entity_type") == "character"
    ]
    power_scales: list[dict[str, Any]] = []
    locations: list[dict[str, Any]] = []
    item_ownership: list[dict[str, Any]] = []
    for node in nodes:
        content = _node_content(node)
        if node.get("type") == "power_scale_rule":
            power_scales.append(
                {
                    "asset_id": node.get("id", ""),
                    "name": node.get("title", ""),
                    "levels": content.get("levels", content.get("rules", [])),
                    "limits": content.get("limits", []),
                }
            )
        for item in content.get("locations", []) if isinstance(content.get("locations", []), list) else []:
            locations.append({"asset_id": node.get("id", ""), "location": item})
        for item in content.get("items", []) if isinstance(content.get("items", []), list) else []:
            item_ownership.append({"asset_id": node.get("id", ""), "item": item})
    return {
        "characters": character_states,
        "power_scales": power_scales,
        "locations": locations,
        "item_ownership": item_ownership,
    }


def _canon_lifecycle_threads(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    threads: list[dict[str, Any]] = []
    valid_status = {"planned", "seeded", "developing", "paid_off", "abandoned", "reopened"}
    for node in nodes:
        content = _node_content(node)
        if node.get("type") == "foreshadowing_thread":
            status = str(content.get("status") or "planned").strip() or "planned"
            threads.append(
                {
                    "thread_id": str(content.get("thread_id") or node.get("id", "")),
                    "asset_id": node.get("id", ""),
                    "asset_path": node.get("path", ""),
                    "title": node.get("title", ""),
                    "status": status,
                    "status_valid": status in valid_status,
                    "setup": content.get("setup", ""),
                    "payoff_plan": content.get("payoff_plan", ""),
                    "related_chapters": content.get("related_chapters", []) if isinstance(content.get("related_chapters", []), list) else [],
                }
            )
        if node.get("type") == "continuity_bible":
            for index, item in enumerate(content.get("open_threads", []) if isinstance(content.get("open_threads", []), list) else [], start=1):
                threads.append(
                    {
                        "thread_id": f"{node.get('id', '')}:open_thread:{index}",
                        "asset_id": node.get("id", ""),
                        "asset_path": node.get("path", ""),
                        "title": str(item),
                        "status": "seeded",
                        "status_valid": True,
                        "setup": str(item),
                        "payoff_plan": "",
                        "related_chapters": [],
                    }
                )
    return threads


def _canon_event_graph(
    nodes: list[dict[str, Any]],
    *,
    target_asset: dict[str, Any] | None = None,
    chapter: int | None = None,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for node in nodes:
        content = _node_content(node)
        for index, item in enumerate(content.get("timeline", []) if isinstance(content.get("timeline", []), list) else [], start=1):
            if isinstance(item, dict):
                text = str(item.get("event") or item.get("summary") or item.get("title") or "").strip()
                event_chapter = _positive_int(item.get("chapter", 0))
            else:
                text = str(item).strip()
                event_chapter = _positive_int(node.get("chapter", 0))
            if text:
                events.append({"event_id": f"{node.get('id', '')}:timeline:{index}", "asset_id": node.get("id", ""), "chapter": event_chapter, "event": text, "kind": "timeline"})
        if node.get("type") == "chapter_plan":
            events.append(
                {
                    "event_id": f"{node.get('id', '')}:plan",
                    "asset_id": node.get("id", ""),
                    "chapter": _positive_int(content.get("chapter") or node.get("chapter")),
                    "event": _compact_event_text([content.get("objective"), content.get("beats"), content.get("hook")]),
                    "kind": "chapter_plan",
                }
            )
        if node.get("type") == "draft_chapter":
            events.append(
                {
                    "event_id": f"{node.get('id', '')}:draft",
                    "asset_id": node.get("id", ""),
                    "chapter": _positive_int(content.get("chapter") or node.get("chapter")),
                    "event": _compact_event_text([content.get("summary"), content.get("text")]),
                    "kind": "draft",
                }
            )
    if target_asset:
        content = target_asset.get("content", {}) if isinstance(target_asset.get("content", {}), dict) else {}
        events.append(
            {
                "event_id": f"{target_asset.get('id', 'target')}:target",
                "asset_id": target_asset.get("id", ""),
                "chapter": _positive_int(chapter or content.get("chapter") or target_asset.get("chapter")),
                "event": _compact_event_text([content.get("objective"), content.get("beats"), content.get("hook"), content.get("text")]),
                "kind": "target",
            }
        )
    return [event for event in events if str(event.get("event", "")).strip()]


def _canon_violations(
    entities: list[dict[str, Any]],
    lifecycle_threads: list[dict[str, Any]],
    event_graph: list[dict[str, Any]],
    *,
    target_asset: dict[str, Any] | None = None,
    chapter: int | None = None,
) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    by_name: dict[str, list[dict[str, Any]]] = {}
    for entity in entities:
        name = str(entity.get("name", "")).strip().lower()
        if name:
            by_name.setdefault(name, []).append(entity)
    for name, rows in by_name.items():
        states = {str(row.get("state", "")).lower() for row in rows if str(row.get("state", "")).strip()}
        locations = {str(row.get("location", "")).lower() for row in rows if str(row.get("location", "")).strip()}
        if _state_conflict(states):
            violations.append(
                {
                    "severity": "high",
                    "dimension": "character_state_machine",
                    "message": f"Character '{name}' has conflicting canon states: {sorted(states)}",
                    "recommendation": "Resolve the character state before chapter generation.",
                    "evidence_asset_ids": _dedupe([str(row.get("asset_id", "")) for row in rows]),
                }
            )
        if len(locations) > 2:
            violations.append(
                {
                    "severity": "medium",
                    "dimension": "location_movement",
                    "message": f"Character '{name}' has multiple active locations: {sorted(locations)}",
                    "recommendation": "Add an explicit travel or location transition beat.",
                    "evidence_asset_ids": _dedupe([str(row.get("asset_id", "")) for row in rows]),
                }
            )
    for thread in lifecycle_threads:
        if not thread.get("status_valid"):
            violations.append(
                {
                    "severity": "medium",
                    "dimension": "foreshadowing_lifecycle",
                    "message": f"Foreshadowing thread '{thread.get('title') or thread.get('thread_id')}' has invalid status {thread.get('status')}.",
                    "recommendation": "Use planned/seeded/developing/paid_off/abandoned/reopened.",
                    "evidence_asset_ids": [str(thread.get("asset_id", ""))],
                }
            )
    target_chapter = _positive_int(chapter or 0)
    target_text = _searchable_text((target_asset or {}).get("content", {}) if isinstance((target_asset or {}).get("content", {}), dict) else {})
    if target_chapter:
        for event in event_graph:
            event_chapter = _positive_int(event.get("chapter", 0))
            event_text = str(event.get("event", "")).strip().lower()
            if event_chapter > target_chapter and event_text and event_text[:80] in target_text:
                violations.append(
                    {
                        "severity": "high",
                        "dimension": "event_causality",
                        "message": f"Target chapter {target_chapter} appears to use future canon event from chapter {event_chapter}.",
                        "recommendation": "Move the event or update the timeline.",
                        "evidence_asset_ids": [str(event.get("asset_id", ""))],
                    }
                )
    return violations


def _iter_asset_paths(storage: LocalStorage) -> list[Path]:
    paths: list[Path] = []
    for category in DATA_DIRS:
        if category in {"indexes", "backups"}:
            continue
        paths.extend(storage.list_json(category))
    return sorted(paths, key=lambda path: path.stat().st_mtime, reverse=True)


def _node(storage: LocalStorage, path: Path, data: dict[str, Any]) -> dict[str, Any]:
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    return {
        "id": str(data.get("id", "")),
        "path": _display_path(storage.root, path),
        "type": str(data.get("type", "")),
        "title": str(data.get("title") or data.get("name") or ""),
        "project_id": str(metadata.get("project_id", "")),
        "workspace_path": str(metadata.get("workspace_path", "")),
        "chapter": content.get("chapter", ""),
        "status": content.get("status") or metadata.get("status", ""),
        "updated_at": data.get("updated_at", ""),
        "tags": data.get("tags", []) if isinstance(data.get("tags", []), list) else [],
        "raw": data,
    }


def _strip_raw(node: dict[str, Any], *, include_content_snapshot: bool = False) -> dict[str, Any]:
    stripped = {key: value for key, value in node.items() if key != "raw"}
    if include_content_snapshot:
        raw = node.get("raw", {}) if isinstance(node.get("raw", {}), dict) else {}
        content = raw.get("content", {}) if isinstance(raw.get("content", {}), dict) else {}
        stripped["content"] = content
    return stripped


def _reference_values(data: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ["source"]:
        if data.get(key):
            values.append(str(data.get(key)))
    for ref in data.get("references", []) if isinstance(data.get("references", []), list) else []:
        if str(ref).strip():
            values.append(str(ref))
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    for key in [
        "draft_id",
        "draft_path",
        "chapter_plan_id",
        "chapter_plan_path",
        "outline_id",
        "outline_path",
        "context_bundle_id",
        "context_bundle_path",
    ]:
        if content.get(key):
            values.append(str(content.get(key)))
    return values


def _content_edges(node: dict[str, Any], index: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    data = node["raw"]
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    edges: list[dict[str, Any]] = []
    for key, relation in [
        ("characters", "uses_character"),
        ("character_ids", "uses_character"),
        ("world_rules", "uses_world_rule"),
        ("foreshadowing", "uses_foreshadowing"),
        ("open_threads", "opens_thread"),
        ("resolved_threads", "resolves_thread"),
        ("power_scale_rules", "uses_power_scale"),
    ]:
        for value in _as_list(content.get(key)):
            target = _lookup(index, value)
            if target:
                edges.append(_edge(node, target, relation, key))
    chapter = content.get("chapter")
    if chapter:
        for target in index.values():
            if target.get("chapter") == chapter and target["id"] != node["id"]:
                edges.append(_edge(node, target, "same_chapter", f"chapter {chapter}"))
    return edges


def _lookup(index: dict[str, dict[str, Any]], value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        for key in ["id", "path", "asset_id", "asset_path", "name", "title"]:
            if value.get(key) and str(value.get(key)) in index:
                return index[str(value.get(key))]
    text = str(value)
    if text in index:
        return index[text]
    lowered = text.lower()
    for node in index.values():
        if lowered and lowered in str(node.get("title", "")).lower():
            return node
    return None


def _edge(source: dict[str, Any], target: dict[str, Any], relation: str, evidence: str) -> dict[str, Any]:
    return {
        "source": source["id"],
        "source_path": source["path"],
        "target": target["id"],
        "target_path": target["path"],
        "relation": relation,
        "evidence": evidence,
    }


def _dedupe_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    result: list[dict[str, Any]] = []
    for edge in edges:
        key = (edge["source"], edge["target"], edge["relation"])
        if key in seen or edge["source"] == edge["target"]:
            continue
        seen.add(key)
        result.append(edge)
    return result


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _summary(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
    by_type: dict[str, int] = {}
    for node in nodes:
        by_type[node["type"]] = by_type.get(node["type"], 0) + 1
    return {
        "node_count": len(nodes),
        "edge_count": len(_dedupe_edges(edges)),
        "types": by_type,
        "orphan_count": len([node for node in nodes if not any(edge["source"] == node["id"] or edge["target"] == node["id"] for edge in edges)]),
    }


def _continuity_checks(text: str, graph: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = graph.get("nodes", []) if isinstance(graph.get("nodes", []), list) else []
    checks: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []
    for asset_type in ["continuity_bible", "character_card", "foreshadowing_thread", "power_scale_rule"]:
        relevant = [node for node in nodes if node.get("type") == asset_type]
        checks.append({"check": f"{asset_type}_available", "status": "passed" if relevant else "warning", "count": len(relevant)})
    named_nodes = [node for node in nodes if node.get("type") in {"character_card", "foreshadowing_thread"} and str(node.get("title", "")).strip()]
    referenced = [node for node in named_nodes if str(node.get("title", "")) in text]
    checks.append({"check": "known_entity_mentions", "status": "passed" if referenced else "warning", "count": len(referenced)})
    if len(named_nodes) >= 3 and not referenced:
        violations.append(
            {
                "severity": "medium",
                "dimension": "entity_continuity",
                "message": "Chapter text does not mention known character or foreshadowing nodes from the continuity graph.",
                "recommendation": "Review whether the chapter should connect to active long-form continuity assets.",
            }
        )
    return checks, violations


def _stability_preflight_checks(plan: dict[str, Any], graph: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    nodes = graph.get("nodes", []) if isinstance(graph.get("nodes", []), list) else []
    content = plan.get("content", {}) if isinstance(plan.get("content", {}), dict) else {}
    chapter = _positive_int(content.get("chapter", 1))
    plan_text = _searchable_text(content)
    checks: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []
    dimensions = {
        "characters": _check_character_stability(nodes, plan_text, chapter),
        "foreshadowing": _check_foreshadowing_stability(nodes, plan_text, chapter),
        "timeline": _check_timeline_stability(nodes, content, chapter),
        "setting_conflicts": _check_setting_conflicts(nodes, plan_text, chapter),
    }
    for dimension, payload in dimensions.items():
        checks.append(
            {
                "check": dimension,
                "status": payload["status"],
                "asset_count": payload.get("asset_count", 0),
                "matched_count": payload.get("matched_count", 0),
                "summary": payload.get("summary", ""),
            }
        )
        violations.extend(payload.get("violations", []))
    return checks, violations, dimensions


def _check_character_stability(nodes: list[dict[str, Any]], plan_text: str, chapter: int) -> dict[str, Any]:
    character_nodes = [node for node in nodes if node.get("type") == "character_card"]
    matched = [node for node in character_nodes if _node_mentioned(node, plan_text)]
    violations: list[dict[str, Any]] = []
    for node in matched:
        content = _node_content(node)
        status_text = " ".join(_strings([content.get("status"), content.get("state"), content.get("current_state"), content.get("fate")])).lower()
        if any(term in status_text for term in ["dead", "死亡", "已死", "阵亡"]) and _contains_any(plan_text, ["出场", "救", "行动", "alive", "appears", "returns"]):
            violations.append(
                _violation(
                    "high",
                    "character_state_conflict",
                    f"Chapter {chapter} appears to use character '{node.get('title')}' as active despite a dead/removed character state.",
                    "Update the character card or rewrite the chapter plan so character state remains consistent.",
                    node,
                )
            )
    if character_nodes and not matched:
        violations.append(
            {
                "severity": "medium",
                "dimension": "character_presence",
                "message": "Chapter plan does not explicitly connect to known character cards.",
                "recommendation": "Bind at least one active character or explain why this chapter is plot/world focused.",
            }
        )
    return {
        "status": "blocked" if any(item["severity"] == "high" for item in violations) else "warning" if violations else "passed",
        "asset_count": len(character_nodes),
        "matched_count": len(matched),
        "matched_assets": [_node_ref(node) for node in matched],
        "violations": violations,
        "summary": "checks active character state and whether chapter plan references known characters",
    }


def _check_foreshadowing_stability(nodes: list[dict[str, Any]], plan_text: str, chapter: int) -> dict[str, Any]:
    thread_nodes = [node for node in nodes if node.get("type") == "foreshadowing_thread"]
    matched = [node for node in thread_nodes if _node_mentioned(node, plan_text) or _thread_text(node) in plan_text]
    violations: list[dict[str, Any]] = []
    for node in thread_nodes:
        content = _node_content(node)
        status = str(content.get("status", "")).strip()
        related = [_positive_int(item) for item in content.get("related_chapters", []) if _positive_int(item)]
        due = bool(related and chapter in related)
        mentioned = node in matched
        if status in {"paid_off", "abandoned"} and mentioned:
            violations.append(
                _violation(
                    "high" if status == "abandoned" else "medium",
                    "foreshadowing_status_conflict",
                    f"Chapter {chapter} references foreshadowing '{node.get('title')}' with status {status}.",
                    "Reopen the thread intentionally or remove the stale foreshadowing reference.",
                    node,
                )
            )
        if due and status in {"planned", "seeded", "developing"} and not mentioned:
            violations.append(
                _violation(
                    "medium",
                    "foreshadowing_due_missing",
                    f"Foreshadowing '{node.get('title')}' is related to chapter {chapter} but is not visible in the chapter plan.",
                    "Add a setup/payoff beat or reschedule the thread.",
                    node,
                )
            )
    return {
        "status": "blocked" if any(item["severity"] == "high" for item in violations) else "warning" if violations else "passed",
        "asset_count": len(thread_nodes),
        "matched_count": len(matched),
        "matched_assets": [_node_ref(node) for node in matched],
        "violations": violations,
        "summary": "checks active foreshadowing threads, due chapters, and stale/payoff conflicts",
    }


def _check_timeline_stability(nodes: list[dict[str, Any]], plan_content: dict[str, Any], chapter: int) -> dict[str, Any]:
    timeline_entries: list[dict[str, Any]] = []
    for node in nodes:
        if node.get("type") != "continuity_bible":
            continue
        content = _node_content(node)
        for item in content.get("timeline", []) if isinstance(content.get("timeline", []), list) else []:
            if isinstance(item, dict):
                timeline_entries.append({**item, "_node": node})
            else:
                timeline_entries.append({"event": str(item), "_node": node})
    violations: list[dict[str, Any]] = []
    previous_chapter = _positive_int((plan_content.get("carry_forward", {}) if isinstance(plan_content.get("carry_forward", {}), dict) else {}).get("previous_chapter", 0))
    if previous_chapter >= chapter:
        violations.append(
            {
                "severity": "high",
                "dimension": "timeline_regression",
                "message": f"Chapter {chapter} carries forward from chapter {previous_chapter}, which is not earlier than the target chapter.",
                "recommendation": "Fix carry_forward.previous_chapter or target chapter number before generation.",
            }
        )
    for entry in timeline_entries:
        entry_chapter = _positive_int(entry.get("chapter", 0))
        if entry_chapter > chapter and _timeline_entry_mentions_plan(entry, plan_content):
            violations.append(
                _violation(
                    "high",
                    "future_timeline_leak",
                    f"Chapter {chapter} appears to use future timeline event from chapter {entry_chapter}: {entry.get('event') or entry.get('summary') or entry.get('title')}",
                    "Move the beat to the correct chapter or update continuity timeline.",
                    entry.get("_node", {}),
                )
            )
    return {
        "status": "blocked" if any(item["severity"] == "high" for item in violations) else "warning" if violations else "passed",
        "asset_count": len(timeline_entries),
        "matched_count": len([entry for entry in timeline_entries if _timeline_entry_mentions_plan(entry, plan_content)]),
        "violations": violations,
        "summary": "checks chapter order, carry-forward order, and future timeline leakage",
    }


def _check_setting_conflicts(nodes: list[dict[str, Any]], plan_text: str, chapter: int) -> dict[str, Any]:
    source_nodes = [node for node in nodes if node.get("type") in {"continuity_bible", "world_bible", "power_scale_rule"}]
    violations: list[dict[str, Any]] = []
    checked_rules = 0
    for node in source_nodes:
        content = _node_content(node)
        for rule in _setting_rules(content):
            checked_rules += 1
            forbidden = _forbidden_phrase(rule)
            if forbidden and forbidden in plan_text:
                violations.append(
                    _violation(
                        "high",
                        "setting_rule_conflict",
                        f"Chapter {chapter} conflicts with setting rule: {rule}",
                        "Rewrite the chapter plan or explicitly update the setting/continuity bible before generation.",
                        node,
                    )
                )
    return {
        "status": "blocked" if any(item["severity"] == "high" for item in violations) else "warning" if violations else "passed",
        "asset_count": len(source_nodes),
        "matched_count": checked_rules,
        "violations": violations,
        "summary": "checks continuity/world/power constraints for explicit forbidden setting conflicts",
    }


def _setting_rules(content: dict[str, Any]) -> list[str]:
    rules: list[str] = []
    for key in ["constraints", "worldview_rules", "rules", "power_rules", "limits"]:
        value = content.get(key)
        if isinstance(value, list):
            rules.extend(str(item).strip() for item in value if str(item).strip())
        elif isinstance(value, dict):
            rules.extend(f"{key}: {item}" for item in value.values() if str(item).strip())
        elif str(value or "").strip():
            rules.append(str(value).strip())
    return rules


def _forbidden_phrase(rule: str) -> str:
    text = str(rule).strip()
    prefixes = ["禁止", "不得", "不能", "不可", "不允许", "forbid ", "forbidden ", "prohibit ", "must not ", "cannot "]
    lowered = text.lower()
    for prefix in prefixes:
        if lowered.startswith(prefix):
            return text[len(prefix) :].strip().lower() if prefix.isascii() else text[len(prefix) :].strip()
        marker = f" {prefix}"
        if marker in lowered:
            index = lowered.index(marker) + len(marker)
            return text[index:].strip().lower() if prefix.isascii() else text[index:].strip()
    return ""


def _timeline_entry_mentions_plan(entry: dict[str, Any], plan_content: dict[str, Any]) -> bool:
    plan_text = _searchable_text(plan_content)
    values = [str(entry.get(key, "")).strip() for key in ["event", "summary", "title", "marker"] if str(entry.get(key, "")).strip()]
    return any(value and value in plan_text for value in values)


def _node_mentioned(node: dict[str, Any], text: str) -> bool:
    content = _node_content(node)
    names = [str(node.get("title", "")).strip(), str(content.get("name", "")).strip(), str(content.get("alias", "")).strip()]
    aliases = content.get("aliases", [])
    if isinstance(aliases, list):
        names.extend(str(item).strip() for item in aliases if str(item).strip())
    return any(name and name in text for name in names)


def _thread_text(node: dict[str, Any]) -> str:
    content = _node_content(node)
    return " ".join(_strings([content.get("thread_id"), content.get("setup"), content.get("payoff_plan")]))


def _node_content(node: dict[str, Any]) -> dict[str, Any]:
    snapshot = node.get("content", {}) if isinstance(node.get("content", {}), dict) else {}
    if snapshot:
        return snapshot
    raw = node.get("raw", {}) if isinstance(node.get("raw", {}), dict) else {}
    content = raw.get("content", {}) if isinstance(raw.get("content", {}), dict) else {}
    return content


def _node_ref(node: dict[str, Any]) -> dict[str, Any]:
    return {"id": node.get("id", ""), "path": node.get("path", ""), "type": node.get("type", ""), "title": node.get("title", "")}


def _violation(severity: str, dimension: str, message: str, recommendation: str, node: dict[str, Any]) -> dict[str, Any]:
    return {
        "severity": severity,
        "dimension": dimension,
        "message": message,
        "recommendation": recommendation,
        "evidence_asset_id": node.get("id", ""),
        "evidence_asset_path": node.get("path", ""),
    }


def _searchable_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_searchable_text(item) for item in value.values()).lower()
    if isinstance(value, list):
        return " ".join(_searchable_text(item) for item in value).lower()
    return str(value or "").lower()


def _strings(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value or "").strip() else []


def _contains_any(text: str, terms: list[str]) -> bool:
    return any(term.lower() in text for term in terms)


def _positive_int(value: Any) -> int:
    try:
        return max(int(value), 0)
    except Exception:
        return 0


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _compact_event_text(values: list[Any]) -> str:
    text = _searchable_text(values)
    return text[:360]


def _state_conflict(states: set[str]) -> bool:
    dead = {"dead", "死亡", "已死", "阵亡", "removed"}
    active = {"active", "alive", "行动", "出场", "injured", "missing", "transformed"}
    return bool(states & dead and states & active)


def _write(storage: LocalStorage, asset: ContinuityGraphSnapshot | CanonGraphSnapshot | ChapterContinuityReport) -> dict[str, Any]:
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "id": asset.id, "asset": asset.to_dict(), "validation": {"ok": True, "errors": []}}


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
