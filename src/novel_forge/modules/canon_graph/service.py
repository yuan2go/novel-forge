from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from novel_forge.core.constants import DATA_DIRS
from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.modules.production_context import filter_project_safe_references, project_scope_from_asset
from novel_forge.modules.review_issue import persist_issue_candidates
from novel_forge.schemas import CanonGraphSnapshot, validate_common_fields
from novel_forge.storage.local import LocalStorage

CANON_GRAPH_ASSET_TYPES = {
    "canon_database",
    "character_card",
    "character_state_ledger",
    "arc_plan",
    "foreshadowing_thread",
    "foreshadowing_graph",
    "world_bible",
    "continuity_bible",
    "power_scale_rule",
    "fact_ledger",
}

NODE_TYPES = {"canon_entity", "character", "arc", "foreshadowing", "world_rule", "fact"}


def build_canon_graph(
    storage: LocalStorage,
    *,
    project_id: str | None = None,
    workspace_path: str | None = None,
    limit: int = 1000,
    persist: bool = False,
) -> dict[str, Any]:
    storage.ensure_layout()
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    references: list[str] = []
    for path in _iter_asset_paths(storage):
        if len(nodes) >= limit:
            break
        data = _read_json_safe(storage, path)
        if not data or data.get("type") not in CANON_GRAPH_ASSET_TYPES:
            continue
        if not _project_matches(data, project_id=project_id, workspace_path=workspace_path):
            continue
        asset_nodes, asset_edges = _nodes_from_asset(storage, path, data)
        nodes.extend(asset_nodes)
        edges.extend(asset_edges)
        references.append(_display_path(storage.root, path))
    graph = {
        "status": "ready",
        "graph_id": make_id("canon_graph", project_id or workspace_path or "global"),
        "project_id": project_id or "",
        "workspace_path": workspace_path or "",
        "nodes": _dedupe_nodes(nodes)[:limit],
        "edges": _dedupe_edges(edges),
        "summary": _summary(nodes, edges),
        "references": _dedupe(references),
        "built_at": utc_now(),
    }
    if persist:
        result = _write_snapshot(storage, graph)
        graph["path"] = result["path"]
        graph["asset"] = result["asset"]
    return graph


def query_canon_graph(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    query = str(payload.get("query") or "").strip().lower()
    node_types = {str(item).strip() for item in payload.get("node_types", []) if str(item).strip()} if isinstance(payload.get("node_types", []), list) else set()
    limit = max(1, min(500, int(payload.get("limit", 100) or 100)))
    graph = build_canon_graph(
        storage,
        project_id=str(payload.get("project_id") or "") or None,
        workspace_path=str(payload.get("workspace_path") or "") or None,
        limit=max(limit * 4, 200),
        persist=bool(payload.get("persist_snapshot", False)),
    )
    rows: list[dict[str, Any]] = []
    for node in graph["nodes"]:
        if node_types and str(node.get("node_type", "")) not in node_types:
            continue
        haystack = " ".join(str(node.get(key, "")) for key in ["id", "name", "canonical_name", "status", "description", "source_asset_path"]).lower()
        aliases = " ".join(str(item) for item in node.get("aliases", []) if str(item).strip()).lower() if isinstance(node.get("aliases", []), list) else ""
        if query and query not in haystack and query not in aliases:
            continue
        rows.append({**node, "matched_query": query})
        if len(rows) >= limit:
            break
    return {
        "status": "ready",
        "query": query,
        "node_types": sorted(node_types),
        "matches": rows,
        "match_count": len(rows),
        "graph_summary": graph["summary"],
        "snapshot_path": graph.get("path", ""),
    }


def check_canon_graph_conflicts(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    target_path = str(payload.get("target_path") or payload.get("asset_path") or "").strip()
    artifact_text = str(payload.get("artifact_text") or payload.get("text") or "").strip()
    target_asset_id = str(payload.get("target_asset_id") or "").strip()
    target_asset_type = str(payload.get("target_asset_type") or "").strip()
    project_id = str(payload.get("project_id") or "").strip()
    workspace_path = str(payload.get("workspace_path") or "").strip()
    evidence_refs: list[str] = []
    if target_path:
        path = resolve_path(storage.root, target_path)
        asset = storage.read_asset(path)
        project = project_scope_from_asset(storage, asset, input_path=path, workspace_path=workspace_path)
        project_id = project_id or str(project.get("project_id") or "")
        workspace_path = workspace_path or str(project.get("workspace_path") or "")
        target_asset_id = target_asset_id or asset.id
        target_asset_type = target_asset_type or asset.type
        artifact_text = artifact_text or _asset_text(asset.to_dict())
        evidence_refs.append(_display_path(storage.root, path))
    graph = build_canon_graph(storage, project_id=project_id or None, workspace_path=workspace_path or None)
    conflicts = _conflicts_from_graph(
        graph,
        artifact_text=artifact_text,
        target_asset_id=target_asset_id or "unknown-target",
        target_asset_type=target_asset_type or "artifact",
        target_asset_path=target_path,
        project_id=project_id or "local-system",
        workspace_path=workspace_path,
        evidence_refs=evidence_refs,
    )
    severity_rank = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}
    max_severity = max((severity_rank.get(str(item.get("severity", "medium")), 2) for item in conflicts), default=0)
    return {
        "status": "blocked" if any(item.get("blocking") for item in conflicts) else "warning" if conflicts else "passed",
        "blocking": any(item.get("blocking") for item in conflicts),
        "max_severity": next((key for key, value in severity_rank.items() if value == max_severity), "info"),
        "conflicts": conflicts,
        "issue_candidates": conflicts,
        "graph_summary": graph["summary"],
        "checked_asset_types": sorted({str(node.get("source_asset_type", "")) for node in graph["nodes"] if str(node.get("source_asset_type", "")).strip()}),
        "references": graph["references"],
    }


def persist_canon_graph_issues(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    result = check_canon_graph_conflicts(storage, payload)
    summary = persist_issue_candidates(storage, result["issue_candidates"], source_system="canon_graph")
    return {"status": result["status"], "check": result, "review_issue_summary": summary}


def _nodes_from_asset(storage: LocalStorage, path: Path, data: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    asset_type = str(data.get("type", ""))
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    base = {
        "source_asset_id": str(data.get("id", "")),
        "source_asset_type": asset_type,
        "source_asset_path": _display_path(storage.root, path),
        "project_id": str(metadata.get("project_id", "")),
        "workspace_path": str(metadata.get("workspace_path", "")),
        "updated_at": str(data.get("updated_at", "")),
    }
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    if asset_type == "canon_database":
        for index, entity in enumerate(_list(content.get("entities")), start=1):
            if not isinstance(entity, dict):
                continue
            nodes.append(_entity_node(base, entity, index=index))
        for index, rule in enumerate(_rule_items(content), start=1):
            nodes.append(_world_rule_node(base, rule, index=index))
    elif asset_type in {"character_state_ledger"}:
        for index, character in enumerate(_list(content.get("characters")), start=1):
            if isinstance(character, dict):
                nodes.append(_character_node(base, character, index=index))
    elif asset_type == "character_card":
        nodes.append(_character_node(base, content, index=1, title=str(data.get("title") or "")))
    elif asset_type == "arc_plan":
        nodes.append(_arc_node(base, content))
    elif asset_type in {"foreshadowing_graph", "foreshadowing_thread"}:
        for index, clue in enumerate(_foreshadowing_items(content, asset_type=asset_type), start=1):
            node = _foreshadowing_node(base, clue, index=index)
            nodes.append(node)
            target = str(node.get("target_truth", "")).strip()
            if target:
                edges.append(_edge(node["id"], target, "points_to_truth", base["source_asset_path"]))
    elif asset_type in {"world_bible", "continuity_bible", "power_scale_rule"}:
        for index, rule in enumerate(_rule_items(content), start=1):
            nodes.append(_world_rule_node(base, rule, index=index))
        for index, entity in enumerate(_list(content.get("entities")), start=1):
            if isinstance(entity, dict):
                nodes.append(_entity_node(base, entity, index=index))
    elif asset_type == "fact_ledger":
        for index, fact in enumerate(_list(content.get("facts")), start=1):
            if isinstance(fact, dict):
                nodes.append(_fact_node(base, fact, index=index))
    for node in nodes:
        edges.append(_edge(base["source_asset_id"], node["id"], "contains", base["source_asset_path"]))
    return nodes, edges


def _entity_node(base: dict[str, Any], entity: dict[str, Any], *, index: int) -> dict[str, Any]:
    name = str(entity.get("canonical_name") or entity.get("name") or entity.get("title") or entity.get("entity_id") or "").strip()
    entity_id = str(entity.get("entity_id") or _slug(name) or index)
    entity_type = str(entity.get("entity_type") or entity.get("type") or "canon_entity")
    node_type = "character" if entity_type == "character" else "canon_entity"
    return {
        **base,
        "id": f"{base['source_asset_id']}:entity:{entity_id}",
        "node_type": node_type,
        "entity_id": entity_id,
        "entity_type": entity_type,
        "name": name,
        "canonical_name": name,
        "aliases": _strings(entity.get("aliases")),
        "forbidden_aliases": _strings(entity.get("forbidden_aliases")),
        "status": str(entity.get("status") or entity.get("state") or "active"),
        "role": str(entity.get("role") or ""),
        "quality": float(entity.get("quality", entity.get("confidence", 1.0)) or 1.0),
        "raw": entity,
    }


def _character_node(base: dict[str, Any], character: dict[str, Any], *, index: int, title: str = "") -> dict[str, Any]:
    name = str(character.get("canonical_name") or character.get("name") or character.get("character_id") or title or "").strip()
    character_id = str(character.get("character_id") or character.get("entity_id") or _slug(name) or index)
    return {
        **base,
        "id": f"{base['source_asset_id']}:character:{character_id}",
        "node_type": "character",
        "entity_id": character_id,
        "entity_type": "character",
        "name": name,
        "canonical_name": name,
        "aliases": _strings(character.get("aliases")),
        "forbidden_aliases": _strings(character.get("forbidden_aliases")),
        "status": str(character.get("status") or character.get("state") or "active"),
        "role": str(character.get("role") or character.get("authority") or ""),
        "active_burdens": _strings(character.get("active_burdens")),
        "risks": _strings(character.get("risks")),
        "debt_ledger": character.get("debt_ledger", {}) if isinstance(character.get("debt_ledger", {}), dict) else {},
        "raw": character,
    }


def _arc_node(base: dict[str, Any], content: dict[str, Any]) -> dict[str, Any]:
    arc_id = str(content.get("arc_id") or _slug(content.get("title")) or base["source_asset_id"])
    return {
        **base,
        "id": f"{base['source_asset_id']}:arc:{arc_id}",
        "node_type": "arc",
        "entity_id": arc_id,
        "name": str(content.get("title") or arc_id),
        "arc_question": str(content.get("arc_question") or ""),
        "chapter_range": str(content.get("chapter_range") or ""),
        "protagonist_goal": str(content.get("protagonist_goal") or ""),
        "villain_goal": str(content.get("villain_goal") or ""),
        "required_payoffs": _strings(content.get("required_payoffs")),
        "forbidden_expansion": _strings(content.get("forbidden_expansion")),
        "status": str(content.get("status") or "active"),
        "raw": content,
    }


def _foreshadowing_node(base: dict[str, Any], clue: dict[str, Any], *, index: int) -> dict[str, Any]:
    name = str(clue.get("name") or clue.get("setup") or clue.get("clue") or clue.get("clue_id") or "").strip()
    clue_id = str(clue.get("clue_id") or clue.get("thread_id") or _slug(name) or index)
    return {
        **base,
        "id": f"{base['source_asset_id']}:foreshadowing:{clue_id}",
        "node_type": "foreshadowing",
        "entity_id": clue_id,
        "name": name,
        "target_truth": str(clue.get("target_truth") or clue.get("payoff") or clue.get("payoff_plan") or ""),
        "source_chapter": clue.get("source_chapter") or clue.get("chapter") or "",
        "planned_payoff_chapter": clue.get("planned_payoff_chapter") or clue.get("payoff_chapter") or "",
        "status": str(clue.get("status") or "active"),
        "raw": clue,
    }


def _world_rule_node(base: dict[str, Any], rule: dict[str, Any], *, index: int) -> dict[str, Any]:
    name = str(rule.get("rule_id") or rule.get("name") or rule.get("title") or rule.get("rule") or f"rule-{index}")
    return {
        **base,
        "id": f"{base['source_asset_id']}:world_rule:{_slug(name) or index}",
        "node_type": "world_rule",
        "entity_id": _slug(name) or str(index),
        "name": name,
        "description": str(rule.get("description") or rule.get("rule") or rule.get("constraint") or ""),
        "forbidden_terms": _strings(rule.get("forbidden_terms")) or _strings(rule.get("must_not")) or _strings(rule.get("forbidden")),
        "required_terms": _strings(rule.get("required_terms")) or _strings(rule.get("must")),
        "status": str(rule.get("status") or "active"),
        "raw": rule,
    }


def _fact_node(base: dict[str, Any], fact: dict[str, Any], *, index: int) -> dict[str, Any]:
    fact_id = str(fact.get("fact_id") or _slug(fact.get("statement")) or index)
    return {
        **base,
        "id": f"{base['source_asset_id']}:fact:{fact_id}",
        "node_type": "fact",
        "entity_id": fact_id,
        "name": str(fact.get("statement") or fact.get("name") or fact_id),
        "status": str(fact.get("status") or "canon"),
        "raw": fact,
    }


def _conflicts_from_graph(
    graph: dict[str, Any],
    *,
    artifact_text: str,
    target_asset_id: str,
    target_asset_type: str,
    target_asset_path: str,
    project_id: str,
    workspace_path: str,
    evidence_refs: list[str],
) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    text = artifact_text or ""
    for node in graph["nodes"]:
        refs = _dedupe([*evidence_refs, str(node.get("source_asset_path", ""))])
        if node.get("node_type") in {"canon_entity", "character"}:
            for alias in _strings(node.get("forbidden_aliases")):
                if alias and alias in text:
                    conflicts.append(
                        _issue_candidate(
                            issue_type="canon_conflict",
                            severity="high",
                            message=f"forbidden canon alias appears in artifact: {alias}",
                            fix_suggestion=f"Replace with canonical name {node.get('canonical_name') or node.get('name')}.",
                            target_asset_id=target_asset_id,
                            target_asset_type=target_asset_type,
                            target_asset_path=target_asset_path,
                            project_id=project_id,
                            workspace_path=workspace_path,
                            evidence_refs=refs,
                            source_issue=node,
                        )
                    )
            status = str(node.get("status") or "").lower()
            name = str(node.get("canonical_name") or node.get("name") or "").strip()
            if name and name in text and status in {"dead", "deceased", "inactive", "retired", "死亡", "失效"} and any(marker in text for marker in ["活着", "复活", "现身", "出场", "继续行动"]):
                conflicts.append(
                    _issue_candidate(
                        issue_type="character_drift",
                        severity="high",
                        message=f"character state contradicts canon status for {name}: {status}",
                        fix_suggestion="Align character state before publishing or create an explicit canon patch.",
                        target_asset_id=target_asset_id,
                        target_asset_type=target_asset_type,
                        target_asset_path=target_asset_path,
                        project_id=project_id,
                        workspace_path=workspace_path,
                        evidence_refs=refs,
                        source_issue=node,
                    )
                )
        elif node.get("node_type") == "arc":
            for term in _strings(node.get("forbidden_expansion")):
                if term and _term_hit(term, text):
                    conflicts.append(
                        _issue_candidate(
                            issue_type="plot_logic_gap",
                            severity="high",
                            message=f"arc forbidden expansion appears in artifact: {term}",
                            fix_suggestion="Remove the expansion or update the arc plan through a governed canon change.",
                            target_asset_id=target_asset_id,
                            target_asset_type=target_asset_type,
                            target_asset_path=target_asset_path,
                            project_id=project_id,
                            workspace_path=workspace_path,
                            evidence_refs=refs,
                            source_issue=node,
                        )
                    )
        elif node.get("node_type") == "foreshadowing":
            if str(node.get("status") or "").lower() in {"dropped", "overdue", "失效", "逾期"} and str(node.get("name") or "") in text:
                conflicts.append(
                    _issue_candidate(
                        issue_type="foreshadowing_drop",
                        severity="medium",
                        message=f"artifact reuses dropped or overdue foreshadowing clue: {node.get('name')}",
                        fix_suggestion="Resolve or re-open the clue before reuse.",
                        target_asset_id=target_asset_id,
                        target_asset_type=target_asset_type,
                        target_asset_path=target_asset_path,
                        project_id=project_id,
                        workspace_path=workspace_path,
                        evidence_refs=refs,
                        source_issue=node,
                    )
                )
        elif node.get("node_type") == "world_rule":
            for term in _strings(node.get("forbidden_terms")):
                if term and term in text:
                    conflicts.append(
                        _issue_candidate(
                            issue_type="canon_conflict",
                            severity="high",
                            message=f"world rule forbidden term appears in artifact: {term}",
                            fix_suggestion=f"Respect world rule {node.get('name')}.",
                            target_asset_id=target_asset_id,
                            target_asset_type=target_asset_type,
                            target_asset_path=target_asset_path,
                            project_id=project_id,
                            workspace_path=workspace_path,
                            evidence_refs=refs,
                            source_issue=node,
                        )
                    )
    return _dedupe_issues(conflicts)


def _issue_candidate(
    *,
    issue_type: str,
    severity: str,
    message: str,
    fix_suggestion: str,
    target_asset_id: str,
    target_asset_type: str,
    target_asset_path: str,
    project_id: str,
    workspace_path: str,
    evidence_refs: list[str],
    source_issue: dict[str, Any],
) -> dict[str, Any]:
    return {
        "issue_type": issue_type,
        "severity": severity,
        "blocking": severity in {"high", "critical"} and issue_type in {"canon_conflict", "plot_logic_gap", "source_leakage", "context_budget_overflow"},
        "message": message,
        "fix_suggestion": fix_suggestion,
        "target_asset_id": target_asset_id,
        "target_asset_type": target_asset_type,
        "target_asset_path": target_asset_path,
        "project_id": project_id,
        "workspace_path": workspace_path,
        "evidence_refs": _dedupe(evidence_refs),
        "source_system": "canon_graph",
        "source_issue_id": str(source_issue.get("id") or source_issue.get("entity_id") or ""),
        "source_issue": {key: value for key, value in source_issue.items() if key != "raw"},
    }


def _write_snapshot(storage: LocalStorage, graph: dict[str, Any]) -> dict[str, Any]:
    asset = CanonGraphSnapshot(
        title="Unified Canon Graph snapshot",
        tags=["canon-graph", "snapshot", "unified-canon"],
        content={
            "snapshot_id": graph["graph_id"],
            "project_id": graph["project_id"],
            "workspace_path": graph["workspace_path"],
            "nodes": graph["nodes"],
            "edges": graph["edges"],
            "summary": graph["summary"],
            "built_at": graph["built_at"],
            "created_at": utc_now(),
        },
        metadata={"project_id": graph["project_id"], "workspace_path": graph["workspace_path"], "use_in_generation_rag": False},
        references=filter_project_safe_references(storage, graph["project_id"], graph["references"]),
    )
    data = asset.to_dict()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset("continuity", asset)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path)}


def _iter_asset_paths(storage: LocalStorage) -> list[Path]:
    paths: list[Path] = []
    for category in DATA_DIRS:
        if category in {"indexes", "backups"}:
            continue
        paths.extend(storage.list_json(category))
    return sorted(paths, key=lambda path: path.stat().st_mtime, reverse=True)


def _read_json_safe(storage: LocalStorage, path: Path) -> dict[str, Any]:
    try:
        data = storage.read_json(path)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _project_matches(data: dict[str, Any], *, project_id: str | None, workspace_path: str | None) -> bool:
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    row_project = str(metadata.get("project_id") or content.get("project_id") or "")
    row_workspace = str(metadata.get("workspace_path") or content.get("workspace_path") or "")
    if project_id and row_project and row_project != project_id:
        return False
    if workspace_path and row_workspace and row_workspace != workspace_path:
        return False
    return True


def _asset_text(asset: dict[str, Any]) -> str:
    content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
    for key in ["text", "body", "draft", "content"]:
        value = content.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _rule_items(content: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in ["world_rules", "rules", "worldview_rules", "constraints", "rule_cards"]:
        value = content.get(key)
        if isinstance(value, dict):
            rows.append(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    rows.append(item)
                elif str(item).strip():
                    rows.append({"rule": str(item)})
    return rows


def _foreshadowing_items(content: dict[str, Any], *, asset_type: str) -> list[dict[str, Any]]:
    if asset_type == "foreshadowing_thread":
        return [content]
    rows: list[dict[str, Any]] = []
    for key in ["clues", "threads", "items"]:
        rows.extend([item for item in _list(content.get(key)) if isinstance(item, dict)])
    return rows


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _strings(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _term_hit(term: str, text: str) -> bool:
    term = term.strip()
    if not term:
        return False
    if term in text:
        return True
    compact = term.replace("不要", "").replace("禁止", "").replace("不许", "").strip()
    return bool(compact and compact in text)


def _slug(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
    safe = "".join(ch.lower() if ch.isalnum() else "-" for ch in raw)[:24].strip("-")
    return safe or digest


def _edge(source: str, target: str, relation: str, evidence: str) -> dict[str, Any]:
    return {"source": source, "target": target, "relation": relation, "evidence": evidence}


def _dedupe_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for node in nodes:
        key = str(node.get("id") or "")
        if key and key not in seen:
            seen.add(key)
            result.append({key_: value for key_, value in node.items() if key_ != "raw"})
    return result


def _dedupe_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for edge in edges:
        key = (str(edge.get("source", "")), str(edge.get("target", "")), str(edge.get("relation", "")))
        if key not in seen:
            seen.add(key)
            result.append(edge)
    return result


def _dedupe_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for issue in issues:
        key = (str(issue.get("issue_type", "")), str(issue.get("target_asset_id", "")), str(issue.get("message", "")))
        if key not in seen:
            seen.add(key)
            result.append(issue)
    return result


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _summary(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
    by_type: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for node in nodes:
        by_type[str(node.get("node_type", ""))] = by_type.get(str(node.get("node_type", "")), 0) + 1
        by_source[str(node.get("source_asset_type", ""))] = by_source.get(str(node.get("source_asset_type", "")), 0) + 1
    return {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "by_node_type": by_type,
        "by_source_asset_type": by_source,
        "coverage": {node_type: by_type.get(node_type, 0) > 0 for node_type in sorted(NODE_TYPES)},
    }


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
