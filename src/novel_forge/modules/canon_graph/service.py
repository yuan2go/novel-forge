from __future__ import annotations

import hashlib
from collections import deque
from pathlib import Path
from typing import Any

from novel_forge.core.constants import DATA_DIRS
from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.modules.production_context import filter_project_safe_references, project_scope_from_asset
from novel_forge.modules.audit_log import record_audit_event
from novel_forge.modules.review_issue import persist_issue_candidates
from novel_forge.schemas import BaseAsset, CanonGraphSnapshot, validate_common_fields
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
ACTIVE_STATUSES = {"active", "alive", "canon", "open", "running", "生效", "存活", "活跃"}
INACTIVE_STATUSES = {"dead", "deceased", "inactive", "retired", "死亡", "失效", "dropped", "closed"}
REASONING_RELATIONS = {
    "same_identity",
    "alias_of",
    "forbids_alias",
    "participates_in_arc",
    "requires_payoff",
    "forbids_expansion",
    "points_to_truth",
    "supports_arc_payoff",
    "constrains",
    "forbids_term",
}


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
    graph_nodes = _dedupe_nodes(nodes)[:limit]
    graph_edges = _dedupe_edges(edges)
    inferred_edges = _infer_reasoning_edges(graph_nodes, graph_edges)
    graph_edges = _dedupe_edges([*graph_edges, *inferred_edges])
    reasoning = _reason_over_graph(
        graph_nodes,
        graph_edges,
        current_chapter=_positive_int_or_none(None),
        project_id=project_id or "",
        workspace_path=workspace_path or "",
    )
    graph = {
        "status": "ready",
        "graph_id": make_id("canon_graph", project_id or workspace_path or "global"),
        "project_id": project_id or "",
        "workspace_path": workspace_path or "",
        "nodes": graph_nodes,
        "edges": graph_edges,
        "adjacency": _adjacency(graph_edges),
        "reasoning": reasoning,
        "summary": _summary(graph_nodes, graph_edges, reasoning=reasoning),
        "references": _dedupe(references),
        "built_at": utc_now(),
    }
    if persist:
        result = _write_snapshot(storage, graph)
        graph["path"] = result["path"]
        graph["asset"] = result["asset"]
    return graph


def reason_canon_graph(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    current_chapter = _positive_int_or_none(payload.get("current_chapter") or payload.get("chapter"))
    persist_snapshot = bool(payload.get("persist_snapshot", False))
    graph = build_canon_graph(
        storage,
        project_id=str(payload.get("project_id") or "") or None,
        workspace_path=str(payload.get("workspace_path") or "") or None,
        limit=max(100, min(2000, int(payload.get("limit", 1000) or 1000))),
    )
    reasoning = _reason_over_graph(
        graph["nodes"],
        graph["edges"],
        current_chapter=current_chapter,
        project_id=graph.get("project_id", ""),
        workspace_path=graph.get("workspace_path", ""),
    )
    graph["reasoning"] = reasoning
    graph["summary"] = _summary(graph["nodes"], graph["edges"], reasoning=reasoning)
    snapshot_path = ""
    if persist_snapshot:
        snapshot = _write_snapshot(storage, graph)
        snapshot_path = snapshot["path"]
    return {
        "status": "blocked" if reasoning["blocking_issue_count"] else "warning" if reasoning["issue_count"] else "passed",
        "graph_id": graph["graph_id"],
        "project_id": graph.get("project_id", ""),
        "workspace_path": graph.get("workspace_path", ""),
        "reasoning": reasoning,
        "summary": graph["summary"],
        "snapshot_path": snapshot_path,
        "built_at": graph["built_at"],
    }


def query_canon_graph_paths(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    graph = build_canon_graph(
        storage,
        project_id=str(payload.get("project_id") or "") or None,
        workspace_path=str(payload.get("workspace_path") or "") or None,
        limit=max(100, min(2000, int(payload.get("limit", 1000) or 1000))),
    )
    source_ref = str(payload.get("source") or payload.get("source_ref") or "").strip()
    target_ref = str(payload.get("target") or payload.get("target_ref") or "").strip()
    max_depth = max(1, min(8, int(payload.get("max_depth", 4) or 4)))
    relation_filter = {str(item).strip() for item in payload.get("relations", []) if str(item).strip()} if isinstance(payload.get("relations", []), list) else set()
    source_ids = _resolve_node_refs(graph["nodes"], source_ref)
    target_ids = _resolve_node_refs(graph["nodes"], target_ref)
    paths = _shortest_paths(graph["nodes"], graph["edges"], source_ids=source_ids, target_ids=target_ids, max_depth=max_depth, relation_filter=relation_filter)
    return {
        "status": "ready",
        "source": source_ref,
        "target": target_ref,
        "source_node_ids": source_ids,
        "target_node_ids": target_ids,
        "paths": paths,
        "path_count": len(paths),
        "graph_summary": graph["summary"],
    }


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
        rows.append({**node, "matched_query": query, "degree": _node_degree(graph["edges"], str(node.get("id", "")))})
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
    artifact_conflicts = _conflicts_from_graph(
        graph,
        artifact_text=artifact_text,
        target_asset_id=target_asset_id or "unknown-target",
        target_asset_type=target_asset_type or "artifact",
        target_asset_path=target_path,
        project_id=project_id or "local-system",
        workspace_path=workspace_path,
        evidence_refs=evidence_refs,
    )
    graph_reasoning = _reason_over_graph(
        graph["nodes"],
        graph["edges"],
        current_chapter=_positive_int_or_none(payload.get("current_chapter") or payload.get("chapter")),
        project_id=project_id or "local-system",
        workspace_path=workspace_path,
    )
    graph_conflicts = _reasoning_issues_to_candidates(
        graph_reasoning.get("issues", []),
        target_asset_id=target_asset_id or "unknown-target",
        target_asset_type=target_asset_type or "artifact",
        target_asset_path=target_path,
        project_id=project_id or "local-system",
        workspace_path=workspace_path,
    )
    conflicts = _dedupe_issues([*artifact_conflicts, *graph_conflicts])
    severity_rank = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}
    max_severity = max((severity_rank.get(str(item.get("severity", "medium")), 2) for item in conflicts), default=0)
    return {
        "status": "blocked" if any(item.get("blocking") for item in conflicts) else "warning" if conflicts else "passed",
        "blocking": any(item.get("blocking") for item in conflicts),
        "max_severity": next((key for key, value in severity_rank.items() if value == max_severity), "info"),
        "conflicts": conflicts,
        "artifact_conflicts": artifact_conflicts,
        "graph_conflicts": graph_conflicts,
        "issue_candidates": conflicts,
        "reasoning": graph_reasoning,
        "graph_summary": graph["summary"],
        "checked_asset_types": sorted({str(node.get("source_asset_type", "")) for node in graph["nodes"] if str(node.get("source_asset_type", "")).strip()}),
        "references": graph["references"],
    }


def persist_canon_graph_issues(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    result = check_canon_graph_conflicts(storage, payload)
    summary = persist_issue_candidates(storage, result["issue_candidates"], source_system="canon_graph")
    return {"status": result["status"], "check": result, "review_issue_summary": summary}


def diff_canon_graph(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    """Compare two Canon Graph snapshots with stable node keys.

    Node ids include source asset ids, so graph diff uses semantic keys
    (node_type/entity_id/name) to detect meaningful canon changes across
    regenerated snapshots.
    """

    storage.ensure_layout()
    before = _graph_from_snapshot_or_current(
        storage,
        str(payload.get("baseline_snapshot_path") or payload.get("before_snapshot_path") or ""),
        project_id=str(payload.get("project_id") or "") or None,
        workspace_path=str(payload.get("workspace_path") or "") or None,
    )
    after = _graph_from_snapshot_or_current(
        storage,
        str(payload.get("candidate_snapshot_path") or payload.get("after_snapshot_path") or ""),
        project_id=str(payload.get("project_id") or "") or None,
        workspace_path=str(payload.get("workspace_path") or "") or None,
    )
    before_nodes = {_node_stable_key(node): node for node in before.get("nodes", []) if _node_stable_key(node)}
    after_nodes = {_node_stable_key(node): node for node in after.get("nodes", []) if _node_stable_key(node)}
    added_keys = sorted(set(after_nodes) - set(before_nodes))
    removed_keys = sorted(set(before_nodes) - set(after_nodes))
    changed: list[dict[str, Any]] = []
    for key in sorted(set(before_nodes) & set(after_nodes)):
        changes = _node_field_diff(before_nodes[key], after_nodes[key])
        if changes:
            changed.append({"node_key": key, "before": _node_public(before_nodes[key]), "after": _node_public(after_nodes[key]), "changed_fields": changes})
    before_edges = {_edge_key(edge): edge for edge in before.get("edges", []) if _edge_key(edge)}
    after_edges = {_edge_key(edge): edge for edge in after.get("edges", []) if _edge_key(edge)}
    added_edges = [_edge_public(after_edges[key]) for key in sorted(set(after_edges) - set(before_edges))]
    removed_edges = [_edge_public(before_edges[key]) for key in sorted(set(before_edges) - set(after_edges))]
    changed_terms = _dedupe(
        [
            *[str(after_nodes[key].get("name") or after_nodes[key].get("canonical_name") or after_nodes[key].get("entity_id") or "") for key in added_keys],
            *[str(before_nodes[key].get("name") or before_nodes[key].get("canonical_name") or before_nodes[key].get("entity_id") or "") for key in removed_keys],
            *[str(row.get("after", {}).get("name") or row.get("after", {}).get("canonical_name") or row.get("node_key") or "") for row in changed],
        ]
    )
    impact = locate_canon_graph_impacted_chapters(
        storage,
        {
            "project_id": payload.get("project_id") or after.get("project_id") or before.get("project_id") or "",
            "workspace_path": payload.get("workspace_path") or after.get("workspace_path") or before.get("workspace_path") or "",
            "keywords": changed_terms,
        },
    )
    report = {
        "status": "changed" if added_keys or removed_keys or changed or added_edges or removed_edges else "unchanged",
        "diff_id": make_id("canon_graph_diff", f"{before.get('graph_id', 'before')}->{after.get('graph_id', 'after')}"),
        "project_id": payload.get("project_id") or after.get("project_id") or before.get("project_id") or "",
        "workspace_path": payload.get("workspace_path") or after.get("workspace_path") or before.get("workspace_path") or "",
        "before_graph_id": before.get("graph_id", ""),
        "after_graph_id": after.get("graph_id", ""),
        "added_nodes": [_node_public(after_nodes[key]) for key in added_keys],
        "removed_nodes": [_node_public(before_nodes[key]) for key in removed_keys],
        "changed_nodes": changed,
        "added_edges": added_edges,
        "removed_edges": removed_edges,
        "impact": impact,
        "summary": {
            "added_node_count": len(added_keys),
            "removed_node_count": len(removed_keys),
            "changed_node_count": len(changed),
            "added_edge_count": len(added_edges),
            "removed_edge_count": len(removed_edges),
            "impacted_chapter_count": impact["summary"]["impacted_chapter_count"],
        },
        "created_at": utc_now(),
    }
    if payload.get("persist", True):
        written = _write_base_asset(
            storage,
            "continuity",
            "canon_graph_diff_report",
            "Canon Graph diff report",
            ["canon-graph", "diff", report["status"]],
            report,
            references=_dedupe([str(payload.get("baseline_snapshot_path") or ""), str(payload.get("candidate_snapshot_path") or ""), *impact.get("references", [])]),
        )
        report["path"] = written["path"]
    return report


def propagate_canon_graph_conflicts(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    check = check_canon_graph_conflicts(storage, payload)
    issue_terms = _dedupe(
        [
            *[str(issue.get("source_issue", {}).get("name") or issue.get("source_issue", {}).get("canonical_name") or issue.get("source_issue_id") or "") for issue in check.get("conflicts", []) if isinstance(issue, dict)],
            *[str(node_id).split(":")[-1] for issue in check.get("reasoning", {}).get("issues", []) if isinstance(issue, dict) for node_id in issue.get("node_ids", [])],
        ]
    )
    impact = locate_canon_graph_impacted_chapters(
        storage,
        {
            "project_id": payload.get("project_id") or check.get("project_id") or "",
            "workspace_path": payload.get("workspace_path") or "",
            "keywords": issue_terms,
            "limit": payload.get("impact_limit", 300),
        },
    )
    persisted = {}
    if payload.get("persist_issues", False) and check.get("issue_candidates"):
        persisted = persist_issue_candidates(storage, check["issue_candidates"], source_system="canon_graph.propagation")
    report = {
        "status": "blocked" if check.get("blocking") else "warning" if check.get("conflicts") else "passed",
        "propagation_id": make_id("canon_conflict_propagation", utc_now()),
        "check": check,
        "impact": impact,
        "review_issue_summary": persisted,
        "summary": {
            "conflict_count": len(check.get("conflicts", [])),
            "blocking": bool(check.get("blocking")),
            "impacted_chapter_count": impact["summary"]["impacted_chapter_count"],
            "review_issue_count": int(persisted.get("created_count", 0) or persisted.get("issue_count", 0) or 0) if persisted else 0,
        },
        "created_at": utc_now(),
    }
    if payload.get("persist", True):
        written = _write_base_asset(
            storage,
            "continuity",
            "canon_conflict_propagation_report",
            "Canon conflict propagation report",
            ["canon-graph", "conflict-propagation", report["status"]],
            report,
            references=_dedupe([*check.get("references", []), *impact.get("references", [])]),
        )
        report["path"] = written["path"]
    return report


def create_canon_change_approval(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    storage.ensure_layout()
    project_id = str(payload.get("project_id") or "")
    workspace_path = str(payload.get("workspace_path") or "")
    diff = diff_canon_graph(storage, {**payload, "persist": False}) if (payload.get("baseline_snapshot_path") or payload.get("candidate_snapshot_path")) else {}
    impact = diff.get("impact") if isinstance(diff.get("impact"), dict) else locate_canon_graph_impacted_chapters(storage, payload)
    approval_id = make_id("canon_change_approval", f"{project_id}-{payload.get('change_type', 'canon-change')}-{utc_now()}")
    trace_id = str(payload.get("trace_id") or make_id("trace", approval_id))
    content = {
        "approval_id": approval_id,
        "status": "pending",
        "requires_human_approval": True,
        "change_type": str(payload.get("change_type") or "canon_change"),
        "proposal": payload.get("proposal", {}) if isinstance(payload.get("proposal", {}), dict) else {"description": str(payload.get("proposal") or "")},
        "proposed_patch": payload.get("proposed_patch", {}) if isinstance(payload.get("proposed_patch", {}), dict) else {},
        "diff": diff,
        "impact": impact,
        "risk_level": "high" if impact.get("summary", {}).get("impacted_chapter_count", 0) else "medium",
        "actor": str(payload.get("actor") or "operator"),
        "trace_id": trace_id,
        "created_at": utc_now(),
        "resolved_at": "",
        "resolution": {},
    }
    written = _write_base_asset(
        storage,
        "continuity",
        "canon_change_approval",
        "Canon change approval",
        ["canon-graph", "approval", "pending"],
        content,
        project_id=project_id,
        workspace_path=workspace_path,
        references=_dedupe([str(payload.get("baseline_snapshot_path") or ""), str(payload.get("candidate_snapshot_path") or ""), *impact.get("references", [])]),
    )
    audit = record_audit_event(
        storage,
        event_type="canon_graph",
        action="canon_change_approval.created",
        actor_type="human" if str(payload.get("actor_type") or "operator") == "human" else "operator",
        actor_id=str(payload.get("actor") or "operator"),
        target={"asset_type": "canon_change_approval", "approval_id": approval_id},
        project_id=project_id,
        trace_id=trace_id,
        output_refs=[written["path"]],
        status="waiting_human",
        blocking=True,
        metadata={"risk_level": content["risk_level"]},
    )
    return {"status": "waiting_human", "path": written["path"], "asset": written["asset"], "audit_event_path": audit["path"], "approval": content}


def resolve_canon_change_approval(storage: LocalStorage, approval_ref: str | Path, payload: dict[str, Any]) -> dict[str, Any]:
    path = _resolve_asset_by_type(storage, approval_ref, "canon_change_approval", category="continuity")
    data = storage.read_json(path)
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    decision = str(payload.get("decision") or payload.get("status") or "").strip().lower()
    if decision not in {"approved", "rejected"}:
        raise ValueError("canon change approval decision must be approved or rejected")
    content["status"] = decision
    content["resolved_at"] = utc_now()
    trace_id = str(payload.get("trace_id") or content.get("trace_id") or make_id("trace", str(content.get("approval_id") or utc_now())))
    content["resolution"] = {
        "decision": decision,
        "actor": str(payload.get("actor") or "operator"),
        "reason": str(payload.get("reason") or ""),
        "trace_id": trace_id,
    }
    data["content"] = content
    data["metadata"] = {**(data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}), "asset_status": decision, "status": decision}
    data["tags"] = _dedupe([*[str(tag) for tag in data.get("tags", [])], decision])
    data["updated_at"] = utc_now()
    storage.write_json(path, data)
    patch_written = {}
    if decision == "approved" and isinstance(content.get("proposed_patch"), dict) and content.get("proposed_patch"):
        proposed_patch = content.get("proposed_patch", {}) if isinstance(content.get("proposed_patch", {}), dict) else {}
        patch_written = _write_base_asset(
            storage,
            "continuity",
            "canon_patch",
            "Approved canon patch",
            ["canon-graph", "canon-patch", "approved"],
            {
                "patch_id": make_id("canon_patch", content.get("approval_id", utc_now())),
                "approval_id": content.get("approval_id", ""),
                "target_draft_id": str(proposed_patch.get("target_draft_id") or content.get("target_draft_id") or "canon-change-approval"),
                "target_draft_path": str(proposed_patch.get("target_draft_path") or ""),
                "chapter": _positive_int_or_none(proposed_patch.get("chapter")) or 0,
                "status": "accepted",
                "proposed_events": proposed_patch.get("proposed_events", []) if isinstance(proposed_patch.get("proposed_events", []), list) else [],
                "entity_updates": proposed_patch.get("entity_updates", proposed_patch.get("characters", [])) if isinstance(proposed_patch.get("entity_updates", proposed_patch.get("characters", [])), list) else [],
                "thread_updates": proposed_patch.get("thread_updates", []) if isinstance(proposed_patch.get("thread_updates", []), list) else [],
                "relationship_updates": proposed_patch.get("relationship_updates", []) if isinstance(proposed_patch.get("relationship_updates", []), list) else [],
                "apply_plan": {
                    "mode": "human_approved_canon_graph_change",
                    "source_approval_id": content.get("approval_id", ""),
                    "writes": ["canon_patch.status", "canon_database|character_state_ledger|arc_plan|foreshadowing_graph|world_rule"],
                    "rollback": "restore JSON backup or reject the accepted canon_patch before apply",
                },
                "human_gate": {"required": True, "status": "approved", "approved_by": str(payload.get("actor") or "operator"), "approval_id": content.get("approval_id", "")},
                "patch": proposed_patch,
                "created_at": utc_now(),
            },
            project_id=str(data.get("metadata", {}).get("project_id") or content.get("project_id") or ""),
            workspace_path=str(data.get("metadata", {}).get("workspace_path") or content.get("workspace_path") or ""),
            references=[_display_path(storage.root, path)],
        )
    audit = record_audit_event(
        storage,
        event_type="canon_graph",
        action=f"canon_change_approval.{decision}",
        actor_type="human",
        actor_id=str(payload.get("actor") or "operator"),
        target={"asset_type": "canon_change_approval", "approval_id": content.get("approval_id", "")},
        project_id=str(data.get("metadata", {}).get("project_id", "")),
        trace_id=trace_id,
        input_refs=[_display_path(storage.root, path)],
        output_refs=[patch_written.get("path", "")] if patch_written else [],
        status="succeeded" if decision == "approved" else "rejected",
        blocking=False,
        metadata={"decision": decision},
    )
    return {"status": decision, "path": _display_path(storage.root, path), "asset": data, "canon_patch": patch_written, "audit_event_path": audit["path"]}


def locate_canon_graph_impacted_chapters(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    storage.ensure_layout()
    project_id = str(payload.get("project_id") or "")
    workspace_path = str(payload.get("workspace_path") or "")
    keyword_items = [str(item) for item in payload.get("keywords", []) if str(item).strip()] if isinstance(payload.get("keywords", []), list) else []
    keywords = _dedupe([*keyword_items, str(payload.get("keyword") or "")])
    for node in payload.get("nodes", []) if isinstance(payload.get("nodes", []), list) else []:
        if isinstance(node, dict):
            keywords.extend([str(node.get("name") or ""), str(node.get("canonical_name") or ""), str(node.get("entity_id") or "")])
    keywords = _dedupe(keywords)
    limit = max(1, min(1000, int(payload.get("limit", 300) or 300)))
    target_types = {"draft_chapter", "chapter_plan", "chapter_plan_version", "review_report", "publish_gate_report", "release_package", "longform_recap_report"}
    rows: list[dict[str, Any]] = []
    references: list[str] = []
    if not keywords:
        return {"status": "empty", "keywords": [], "impacted_chapters": [], "references": [], "summary": {"impacted_chapter_count": 0, "asset_count": 0}}
    for category in ["drafts", "chapter_plans", "reviews", "publishing", "continuity"]:
        for path in reversed(storage.list_json(category)):
            data = _read_json_safe(storage, path)
            if not data or data.get("type") not in target_types:
                continue
            if not _project_matches(data, project_id=project_id or None, workspace_path=workspace_path or None):
                continue
            text = _asset_search_text(data)
            matched = [term for term in keywords if term and _term_hit(term, text)]
            if not matched:
                continue
            row = {
                "path": _display_path(storage.root, path),
                "asset_id": str(data.get("id", "")),
                "asset_type": str(data.get("type", "")),
                "chapter_no": _chapter_no_from_asset(data),
                "matched_terms": matched[:12],
                "risk": "needs_recheck" if data.get("type") in {"draft_chapter", "release_package", "publish_gate_report"} else "needs_review",
            }
            rows.append(row)
            references.append(row["path"])
            if len(rows) >= limit:
                break
        if len(rows) >= limit:
            break
    chapter_numbers = sorted({int(row["chapter_no"]) for row in rows if isinstance(row.get("chapter_no"), int)})
    return {
        "status": "found" if rows else "none",
        "keywords": keywords,
        "impacted_chapters": rows,
        "references": _dedupe(references),
        "summary": {
            "impacted_chapter_count": len(chapter_numbers),
            "asset_count": len(rows),
            "chapter_numbers": chapter_numbers,
            "critical_asset_count": len([row for row in rows if row["asset_type"] in {"draft_chapter", "release_package", "publish_gate_report"}]),
        },
    }


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


def _infer_reasoning_edges(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    inferred: list[dict[str, Any]] = []
    identity_index: dict[str, list[dict[str, Any]]] = {}
    for node in nodes:
        for key in _identity_keys(node):
            identity_index.setdefault(key, []).append(node)
    for rows in identity_index.values():
        for index, source in enumerate(rows):
            for target in rows[index + 1 :]:
                if source.get("id") != target.get("id"):
                    inferred.append(_edge(str(source["id"]), str(target["id"]), "same_identity", "canonical identity key"))

    canonical_index = {_normal_key(node.get("canonical_name") or node.get("name")): node for node in nodes if str(node.get("canonical_name") or node.get("name") or "").strip()}
    for node in nodes:
        for alias in _strings(node.get("aliases")):
            target = canonical_index.get(_normal_key(alias))
            if target and target.get("id") != node.get("id"):
                inferred.append(_edge(str(node["id"]), str(target["id"]), "alias_of", f"alias {alias} matches canonical node"))
        for alias in _strings(node.get("forbidden_aliases")):
            inferred.append(_edge(str(node["id"]), f"literal:forbidden_alias:{_slug(alias)}", "forbids_alias", alias))

    character_nodes = [node for node in nodes if node.get("node_type") == "character"]
    arc_nodes = [node for node in nodes if node.get("node_type") == "arc"]
    clue_nodes = [node for node in nodes if node.get("node_type") == "foreshadowing"]
    rule_nodes = [node for node in nodes if node.get("node_type") == "world_rule"]

    for arc in arc_nodes:
        arc_text = _node_text(arc, keys=["name", "arc_question", "protagonist_goal", "villain_goal"])
        for character in character_nodes:
            if _node_mentions(arc_text, character):
                inferred.append(_edge(str(character["id"]), str(arc["id"]), "participates_in_arc", "character mentioned in arc goal/question"))
        for payoff in _strings(arc.get("required_payoffs")):
            inferred.append(_edge(str(arc["id"]), f"literal:payoff:{_slug(payoff)}", "requires_payoff", payoff))
            for clue in clue_nodes:
                clue_text = _node_text(clue, keys=["name", "target_truth"])
                if _semantic_overlap(payoff, clue_text):
                    inferred.append(_edge(str(clue["id"]), str(arc["id"]), "supports_arc_payoff", payoff))
        for term in _strings(arc.get("forbidden_expansion")):
            inferred.append(_edge(str(arc["id"]), f"literal:forbidden_expansion:{_slug(term)}", "forbids_expansion", term))

    for rule in rule_nodes:
        rule_text = _node_text(rule, keys=["name", "description"])
        for term in _strings(rule.get("forbidden_terms")):
            inferred.append(_edge(str(rule["id"]), f"literal:forbidden_term:{_slug(term)}", "forbids_term", term))
        for target in [*character_nodes, *arc_nodes, *clue_nodes]:
            if _node_mentions(rule_text, target) or any(_semantic_overlap(term, _node_text(target, keys=["name", "arc_question", "target_truth"])) for term in _strings(rule.get("required_terms"))):
                inferred.append(_edge(str(rule["id"]), str(target["id"]), "constrains", "world rule mentions target"))

    return _dedupe_edges(inferred)


def _reason_over_graph(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    current_chapter: int | None,
    project_id: str,
    workspace_path: str,
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    obligations: list[dict[str, Any]] = []
    inferences: list[dict[str, Any]] = []
    identity_clusters = _identity_clusters(nodes)
    for cluster in identity_clusters:
        statuses = {str(node.get("status") or "").lower() for node in cluster["nodes"] if str(node.get("status") or "").strip()}
        if statuses & ACTIVE_STATUSES and statuses & INACTIVE_STATUSES:
            issues.append(
                _graph_issue(
                    "entity_status_conflict",
                    "high",
                    f"identity cluster has contradictory lifecycle statuses: {', '.join(sorted(statuses))}",
                    "Resolve Canon/Character state before generation or create an explicit canon patch.",
                    nodes=cluster["nodes"],
                    blocking=True,
                    issue_type="canon_conflict",
                    project_id=project_id,
                    workspace_path=workspace_path,
                )
            )
        if len(cluster["nodes"]) > 1:
            inferences.append({"inference": "same_identity_cluster", "identity_key": cluster["identity_key"], "node_ids": [node["id"] for node in cluster["nodes"]]})

    canonical_names = {_normal_key(node.get("canonical_name") or node.get("name")): node for node in nodes if str(node.get("canonical_name") or node.get("name") or "").strip()}
    for node in nodes:
        for alias in _strings(node.get("forbidden_aliases")):
            other = canonical_names.get(_normal_key(alias))
            if other and other.get("id") != node.get("id"):
                issues.append(
                    _graph_issue(
                        "forbidden_alias_reused_as_canon",
                        "high",
                        f"forbidden alias is also registered as a canonical node: {alias}",
                        "Rename one identity or update forbidden_aliases with an approved canon patch.",
                        nodes=[node, other],
                        blocking=True,
                        issue_type="canon_conflict",
                        project_id=project_id,
                        workspace_path=workspace_path,
                    )
                )

    clue_nodes = [node for node in nodes if node.get("node_type") == "foreshadowing"]
    for clue in clue_nodes:
        clue_name = str(clue.get("name") or clue.get("entity_id") or "")
        if not str(clue.get("target_truth") or "").strip():
            issues.append(
                _graph_issue(
                    "foreshadowing_orphan",
                    "high",
                    f"foreshadowing clue has no target truth: {clue_name}",
                    "Bind the clue to a target_truth or close it before publication.",
                    nodes=[clue],
                    blocking=True,
                    issue_type="foreshadowing_drop",
                    project_id=project_id,
                    workspace_path=workspace_path,
                )
            )
        planned = _positive_int_or_none(clue.get("planned_payoff_chapter"))
        status = str(clue.get("status") or "").lower()
        if current_chapter and planned and planned < current_chapter and status in ACTIVE_STATUSES:
            issues.append(
                _graph_issue(
                    "foreshadowing_overdue",
                    "high",
                    f"foreshadowing clue is overdue at chapter {current_chapter}: {clue_name}",
                    "Pay off, defer, or explicitly close the clue.",
                    nodes=[clue],
                    blocking=True,
                    issue_type="foreshadowing_drop",
                    project_id=project_id,
                    workspace_path=workspace_path,
                )
            )

    clue_texts = [_node_text(clue, keys=["name", "target_truth"]) for clue in clue_nodes]
    for arc in [node for node in nodes if node.get("node_type") == "arc"]:
        for payoff in _strings(arc.get("required_payoffs")):
            covered = any(_semantic_overlap(payoff, text) for text in clue_texts)
            obligations.append(
                {
                    "obligation_type": "arc_required_payoff",
                    "status": "covered" if covered else "open",
                    "arc_id": arc.get("id", ""),
                    "payoff": payoff,
                    "evidence_refs": [arc.get("source_asset_path", "")],
                }
            )
            if not covered:
                issues.append(
                    _graph_issue(
                        "arc_payoff_uncovered",
                        "medium",
                        f"arc required payoff has no supporting foreshadowing edge: {payoff}",
                        "Add a foreshadowing clue/target_truth or update the arc plan.",
                        nodes=[arc],
                        blocking=False,
                        issue_type="plot_logic_gap",
                        project_id=project_id,
                        workspace_path=workspace_path,
                    )
                )

    for rule in [node for node in nodes if node.get("node_type") == "world_rule"]:
        if not _strings(rule.get("forbidden_terms")) and not _strings(rule.get("required_terms")):
            issues.append(
                _graph_issue(
                    "weak_world_rule",
                    "low",
                    f"world rule has no machine-checkable terms: {rule.get('name')}",
                    "Add forbidden_terms or required_terms so production gates can reason over the rule.",
                    nodes=[rule],
                    blocking=False,
                    issue_type="canon_conflict",
                    project_id=project_id,
                    workspace_path=workspace_path,
                )
            )

    issues = _dedupe_graph_issues(issues)
    return {
        "reasoning_version": "canon-graph-reasoner-v1",
        "current_chapter": current_chapter,
        "issue_count": len(issues),
        "blocking_issue_count": len([issue for issue in issues if issue.get("blocking")]),
        "issues": issues,
        "obligations": obligations,
        "inferences": inferences,
        "edge_relation_counts": _edge_relation_counts(edges),
        "identity_cluster_count": len(identity_clusters),
        "identity_clusters": [{key: value for key, value in cluster.items() if key != "nodes"} for cluster in identity_clusters],
        "created_at": utc_now(),
    }


def _reasoning_issues_to_candidates(
    issues: list[dict[str, Any]],
    *,
    target_asset_id: str,
    target_asset_type: str,
    target_asset_path: str,
    project_id: str,
    workspace_path: str,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for issue in issues:
        severity = str(issue.get("severity") or "medium")
        candidate = _issue_candidate(
            issue_type=str(issue.get("issue_type") or "canon_conflict"),
            severity=severity,
            message=str(issue.get("message") or ""),
            fix_suggestion=str(issue.get("fix_suggestion") or ""),
            target_asset_id=target_asset_id,
            target_asset_type=target_asset_type,
            target_asset_path=target_asset_path,
            project_id=project_id,
            workspace_path=workspace_path,
            evidence_refs=_strings(issue.get("evidence_refs")),
            source_issue=issue,
        )
        candidate["blocking"] = bool(issue.get("blocking", candidate.get("blocking", False)))
        candidates.append(candidate)
    return candidates


def _graph_issue(
    reason_type: str,
    severity: str,
    message: str,
    fix_suggestion: str,
    *,
    nodes: list[dict[str, Any]],
    blocking: bool,
    issue_type: str,
    project_id: str,
    workspace_path: str,
) -> dict[str, Any]:
    return {
        "reason_type": reason_type,
        "issue_type": issue_type,
        "severity": severity,
        "blocking": blocking,
        "message": message,
        "fix_suggestion": fix_suggestion,
        "node_ids": [str(node.get("id", "")) for node in nodes if str(node.get("id", "")).strip()],
        "node_types": sorted({str(node.get("node_type", "")) for node in nodes if str(node.get("node_type", "")).strip()}),
        "evidence_refs": _dedupe([str(node.get("source_asset_path", "")) for node in nodes]),
        "project_id": project_id,
        "workspace_path": workspace_path,
        "source_system": "canon_graph.reasoner",
    }


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
    projection = _schema_projection(graph)
    asset = CanonGraphSnapshot(
        title="Unified Canon Graph snapshot",
        tags=["canon-graph", "snapshot", "unified-canon"],
        content={
            "snapshot_id": graph["graph_id"],
            "project_id": graph["project_id"],
            "workspace_path": graph["workspace_path"],
            "entities": projection["entities"],
            "relationships": projection["relationships"],
            "state_machines": projection["state_machines"],
            "lifecycle_threads": projection["lifecycle_threads"],
            "event_graph": projection["event_graph"],
            "violations": projection["violations"],
            "nodes": graph["nodes"],
            "edges": graph["edges"],
            "adjacency": graph.get("adjacency", {}),
            "reasoning": graph.get("reasoning", {}),
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


def _identity_keys(node: dict[str, Any]) -> list[str]:
    keys = []
    for value in [node.get("entity_id"), node.get("canonical_name"), node.get("name"), *_strings(node.get("aliases"))]:
        normalized = _normal_key(value)
        if normalized:
            keys.append(normalized)
    return _dedupe(keys)


def _identity_clusters(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for node in nodes:
        if node.get("node_type") not in {"character", "canon_entity"}:
            continue
        for key in _identity_keys(node):
            index.setdefault(key, []).append(node)
    clusters: list[dict[str, Any]] = []
    seen_sets: set[tuple[str, ...]] = set()
    for key, rows in index.items():
        ids = tuple(sorted(str(row.get("id", "")) for row in rows))
        if len(rows) <= 1 or ids in seen_sets:
            continue
        seen_sets.add(ids)
        clusters.append(
            {
                "identity_key": key,
                "node_ids": list(ids),
                "canonical_names": _dedupe([str(row.get("canonical_name") or row.get("name") or "") for row in rows]),
                "statuses": _dedupe([str(row.get("status") or "") for row in rows]),
                "nodes": rows,
            }
        )
    return clusters


def _normal_key(value: Any) -> str:
    return "".join(ch.lower() for ch in str(value or "").strip() if not ch.isspace())


def _node_text(node: dict[str, Any], *, keys: list[str]) -> str:
    values: list[str] = []
    for key in keys:
        value = node.get(key)
        if isinstance(value, list):
            values.extend(str(item) for item in value)
        elif value is not None:
            values.append(str(value))
    return " ".join(item for item in values if item.strip())


def _node_mentions(text: str, node: dict[str, Any]) -> bool:
    if not text:
        return False
    for value in [node.get("canonical_name"), node.get("name"), *_strings(node.get("aliases"))]:
        item = str(value or "").strip()
        if item and item in text:
            return True
    return False


def _semantic_overlap(left: str, right: str) -> bool:
    left_norm = _normal_key(left)
    right_norm = _normal_key(right)
    if not left_norm or not right_norm:
        return False
    if left_norm in right_norm or right_norm in left_norm:
        return True
    left_tokens = _semantic_tokens(left)
    right_tokens = _semantic_tokens(right)
    return len(left_tokens & right_tokens) >= 1


def _semantic_tokens(value: str) -> set[str]:
    raw = str(value or "").replace("，", " ").replace("。", " ").replace("、", " ").replace("；", " ")
    tokens = {item.strip().lower() for item in raw.split() if len(item.strip()) >= 2}
    compact = _normal_key(value)
    tokens.update({compact[index : index + 2] for index in range(max(0, len(compact) - 1)) if compact[index : index + 2].strip()})
    return tokens


def _adjacency(edges: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        source = str(edge.get("source", ""))
        if not source:
            continue
        rows.setdefault(source, []).append({"target": edge.get("target", ""), "relation": edge.get("relation", ""), "evidence": edge.get("evidence", "")})
    return rows


def _node_degree(edges: list[dict[str, Any]], node_id: str) -> dict[str, int]:
    outgoing = len([edge for edge in edges if str(edge.get("source", "")) == node_id])
    incoming = len([edge for edge in edges if str(edge.get("target", "")) == node_id])
    return {"incoming": incoming, "outgoing": outgoing, "total": incoming + outgoing}


def _edge_relation_counts(edges: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for edge in edges:
        relation = str(edge.get("relation") or "")
        counts[relation] = counts.get(relation, 0) + 1
    return counts


def _resolve_node_refs(nodes: list[dict[str, Any]], ref: str) -> list[str]:
    if not ref:
        return []
    wanted = _normal_key(ref)
    matches = []
    for node in nodes:
        values = [node.get("id"), node.get("entity_id"), node.get("canonical_name"), node.get("name"), node.get("source_asset_path"), *_strings(node.get("aliases"))]
        if any(_normal_key(value) == wanted or (wanted and wanted in _normal_key(value)) for value in values):
            matches.append(str(node.get("id", "")))
    return _dedupe(matches)


def _shortest_paths(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    source_ids: list[str],
    target_ids: list[str],
    max_depth: int,
    relation_filter: set[str],
) -> list[dict[str, Any]]:
    node_index = {str(node.get("id", "")): node for node in nodes}
    edge_index: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        relation = str(edge.get("relation") or "")
        if relation_filter and relation not in relation_filter:
            continue
        source = str(edge.get("source", ""))
        target = str(edge.get("target", ""))
        if not source or not target:
            continue
        edge_index.setdefault(source, []).append(edge)
        edge_index.setdefault(target, []).append({**edge, "source": target, "target": source, "reversed": True})
    targets = set(target_ids)
    paths: list[dict[str, Any]] = []
    for source_id in source_ids:
        queue: deque[tuple[str, list[dict[str, Any]]]] = deque([(source_id, [])])
        seen = {source_id}
        while queue and len(paths) < 20:
            current, path_edges = queue.popleft()
            if len(path_edges) > max_depth:
                continue
            if current in targets and path_edges:
                node_ids = [source_id, *[str(edge.get("target", "")) for edge in path_edges]]
                paths.append(
                    {
                        "node_ids": node_ids,
                        "nodes": [_path_node(node_index, node_id) for node_id in node_ids],
                        "edges": path_edges,
                        "length": len(path_edges),
                    }
                )
                continue
            if len(path_edges) >= max_depth:
                continue
            for edge in edge_index.get(current, []):
                target = str(edge.get("target", ""))
                if not target or target in seen:
                    continue
                seen.add(target)
                queue.append((target, [*path_edges, edge]))
    return paths


def _path_node(node_index: dict[str, dict[str, Any]], node_id: str) -> dict[str, Any]:
    node = node_index.get(node_id, {})
    return {"id": node_id, "node_type": node.get("node_type", "literal"), "name": node.get("canonical_name") or node.get("name") or node_id}


def _dedupe_graph_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for issue in issues:
        key = (str(issue.get("reason_type", "")), str(issue.get("message", "")), ",".join(_strings(issue.get("node_ids"))))
        if key not in seen:
            seen.add(key)
            result.append(issue)
    return result


def _schema_projection(graph: dict[str, Any]) -> dict[str, Any]:
    nodes = graph.get("nodes", []) if isinstance(graph.get("nodes", []), list) else []
    edges = graph.get("edges", []) if isinstance(graph.get("edges", []), list) else []
    reasoning = graph.get("reasoning", {}) if isinstance(graph.get("reasoning", {}), dict) else {}
    return {
        "entities": [node for node in nodes if node.get("node_type") in {"canon_entity", "character", "fact"}],
        "relationships": edges,
        "state_machines": {
            "identity_clusters": reasoning.get("identity_clusters", []),
            "edge_relation_counts": reasoning.get("edge_relation_counts", {}),
        },
        "lifecycle_threads": [node for node in nodes if node.get("node_type") == "foreshadowing"],
        "event_graph": [edge for edge in edges if edge.get("relation") in REASONING_RELATIONS],
        "violations": reasoning.get("issues", []),
    }


def _term_hit(term: str, text: str) -> bool:
    term = term.strip()
    if not term:
        return False
    if term in text:
        return True
    compact = term.replace("不要", "").replace("禁止", "").replace("不许", "").strip()
    return bool(compact and compact in text)


def _positive_int_or_none(value: Any) -> int | None:
    try:
        integer = int(value)
    except (TypeError, ValueError):
        return None
    return integer if integer > 0 else None


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


def _graph_from_snapshot_or_current(
    storage: LocalStorage,
    snapshot_path: str,
    *,
    project_id: str | None,
    workspace_path: str | None,
) -> dict[str, Any]:
    if snapshot_path:
        data = _read_json_safe(storage, resolve_path(storage.root, snapshot_path))
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        nodes = content.get("nodes", []) if isinstance(content.get("nodes", []), list) else []
        edges = content.get("edges", []) if isinstance(content.get("edges", []), list) else []
        return {
            "graph_id": str(content.get("snapshot_id") or data.get("id") or snapshot_path),
            "project_id": str(content.get("project_id") or data.get("metadata", {}).get("project_id", "")),
            "workspace_path": str(content.get("workspace_path") or data.get("metadata", {}).get("workspace_path", "")),
            "nodes": nodes,
            "edges": edges,
            "summary": content.get("summary", {}) if isinstance(content.get("summary", {}), dict) else _summary(nodes, edges),
            "references": data.get("references", []) if isinstance(data.get("references", []), list) else [],
        }
    return build_canon_graph(storage, project_id=project_id, workspace_path=workspace_path)


def _node_stable_key(node: dict[str, Any]) -> str:
    node_type = str(node.get("node_type") or node.get("source_asset_type") or "").strip()
    entity_id = str(node.get("entity_id") or "").strip()
    name = str(node.get("canonical_name") or node.get("name") or "").strip()
    source_type = str(node.get("source_asset_type") or "").strip()
    if not node_type and not (entity_id or name):
        return ""
    return "|".join([node_type, source_type, _normal_key(entity_id or name)])


def _node_field_diff(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    fields = [
        "status",
        "canonical_name",
        "name",
        "role",
        "arc_question",
        "protagonist_goal",
        "villain_goal",
        "target_truth",
        "planned_payoff_chapter",
        "forbidden_terms",
        "required_terms",
        "required_payoffs",
        "forbidden_expansion",
    ]
    changes: list[dict[str, Any]] = []
    for field in fields:
        before_value = before.get(field)
        after_value = after.get(field)
        if before_value != after_value:
            changes.append({"field": field, "before": before_value, "after": after_value})
    return changes


def _node_public(node: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in node.items() if key not in {"raw"}}


def _edge_key(edge: dict[str, Any]) -> str:
    return "|".join([str(edge.get("source", "")), str(edge.get("target", "")), str(edge.get("relation", ""))])


def _edge_public(edge: dict[str, Any]) -> dict[str, Any]:
    return {key: edge.get(key, "") for key in ["source", "target", "relation", "evidence"] if key in edge}


def _asset_search_text(data: dict[str, Any]) -> str:
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    safe_parts: list[str] = [str(data.get("title") or ""), str(data.get("name") or ""), str(data.get("type") or "")]

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"raw_text", "clean_text", "source_text"}:
                    continue
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, (str, int, float, bool)):
            safe_parts.append(str(value))

    visit(content)
    visit({key: value for key, value in metadata.items() if key not in {"raw_text", "clean_text"}})
    return "\n".join(safe_parts)


def _chapter_no_from_asset(data: dict[str, Any]) -> int | str:
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    for key in ["chapter_no", "chapter", "chapter_number"]:
        value = content.get(key)
        parsed = _positive_int_or_none(value)
        if parsed:
            return parsed
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    for key in ["chapter_no", "chapter", "chapter_number"]:
        parsed = _positive_int_or_none(metadata.get(key))
        if parsed:
            return parsed
    return ""


def _write_base_asset(
    storage: LocalStorage,
    category: str,
    asset_type: str,
    title: str,
    tags: list[str],
    content: dict[str, Any],
    *,
    project_id: str = "",
    workspace_path: str = "",
    references: list[str] | None = None,
) -> dict[str, Any]:
    asset = BaseAsset(
        type=asset_type,
        title=title,
        tags=tags,
        content=content,
        metadata={
            "project_id": project_id or str(content.get("project_id") or ""),
            "workspace_path": workspace_path or str(content.get("workspace_path") or ""),
            "use_in_generation_rag": False,
            "asset_status": str(content.get("status") or tags[-1] if tags else "active"),
        },
        references=filter_project_safe_references(storage, project_id or str(content.get("project_id") or ""), references or []),
    )
    data = asset.to_dict()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset(category, asset)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path)}


def _resolve_asset_by_type(storage: LocalStorage, value: str | Path, asset_type: str, *, category: str) -> Path:
    candidate = resolve_path(storage.root, value)
    if candidate.exists():
        data = _read_json_safe(storage, candidate)
        if data.get("type") == asset_type:
            return candidate
    for path in reversed(storage.list_json(category)):
        data = _read_json_safe(storage, path)
        if data.get("type") != asset_type:
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if str(data.get("id", "")) == str(value) or str(content.get("approval_id", "")) == str(value):
            return path
    raise FileNotFoundError(f"{asset_type} not found: {value}")


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _summary(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], *, reasoning: dict[str, Any] | None = None) -> dict[str, Any]:
    by_type: dict[str, int] = {}
    by_source: dict[str, int] = {}
    reasoning_payload = reasoning if isinstance(reasoning, dict) else {}
    for node in nodes:
        by_type[str(node.get("node_type", ""))] = by_type.get(str(node.get("node_type", "")), 0) + 1
        by_source[str(node.get("source_asset_type", ""))] = by_source.get(str(node.get("source_asset_type", "")), 0) + 1
    return {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "by_node_type": by_type,
        "by_source_asset_type": by_source,
        "edge_relation_counts": _edge_relation_counts(edges),
        "reasoning_issue_count": int(reasoning_payload.get("issue_count", 0) or 0),
        "reasoning_blocking_issue_count": int(reasoning_payload.get("blocking_issue_count", 0) or 0),
        "reasoning_obligation_count": len(reasoning_payload.get("obligations", []) if isinstance(reasoning_payload.get("obligations", []), list) else []),
        "coverage": {node_type: by_type.get(node_type, 0) > 0 for node_type in sorted(NODE_TYPES)},
    }


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
