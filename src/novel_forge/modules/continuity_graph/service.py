from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.constants import DATA_DIRS
from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.agent_runs import AgentExecutionContext
from novel_forge.modules.common import resolve_path
from novel_forge.modules.production_context import filter_project_safe_references, project_scope_from_asset
from novel_forge.schemas import ChapterContinuityReport, ContinuityGraphSnapshot, validate_common_fields
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
}


def build_continuity_graph(
    storage: LocalStorage,
    *,
    project_id: str | None = None,
    workspace_path: str | None = None,
    limit: int = 500,
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
            "nodes": [_strip_raw(node) for node in nodes],
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


def _strip_raw(node: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in node.items() if key != "raw"}


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


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _write(storage: LocalStorage, asset: ContinuityGraphSnapshot | ChapterContinuityReport) -> dict[str, Any]:
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
