from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from novel_forge.core.constants import DATA_DIRS
from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules import mkaos as mkaos_service
from novel_forge.modules.production_context import filter_project_safe_references
from novel_forge.schemas import BaseAsset, validate_common_fields
from novel_forge.storage.local import LocalStorage

RAW_FIELD_NAMES = {
    "raw_text",
    "clean_text",
    "source_text",
    "target_text",
    "quote",
    "quotation",
    "excerpt",
    "verbatim",
    "copied_sentence",
}

NODE_TYPES = {
    "source_repository",
    "repository_manifest",
    "book_source",
    "book_chapter_source",
    "parallel_text_pair",
    "source_document",
    "source_chunk",
    "knowledge_card",
    "mkaos_model_extraction_candidate",
    "genre_seed_card",
    "world_rule_card",
    "character_archetype_card",
    "conflict_pattern_card",
    "scene_material_card",
    "plot_template_card",
    "chapter_hook_card",
    "review_rule_card",
    "style_rule_card",
    "outline_mechanism_card",
    "chapter_injection_card",
    "context_bundle",
    "knowledge_pack",
    "draft_chapter",
    "draft_version",
    "review_report",
    "revision_task",
    "longform_recap_report",
    "publish_gate_report",
    "release_package",
    "reader_feedback",
    "review_issue",
    "evaluation_result",
    "mkaos_production_gate_report",
    "mkaos_feedback_attribution",
    "knowledge_usage_event",
    "material_usage_event",
    "source_refresh_report",
}

RELATION_WEIGHTS = {
    "violates_originality_boundary": 1.0,
    "blocked_by_gate": 0.95,
    "caused_review_issue": 0.9,
    "hurt_by_feedback": 0.85,
    "quarantined_by": 0.85,
    "fixed_by_revision": 0.8,
    "attributed_to_feedback": 0.75,
    "used_in_generation": 0.7,
    "used_in_context": 0.65,
    "selected_by_pack": 0.6,
    "converted_to": 0.55,
    "abstracted_to": 0.5,
    "derived_from": 0.45,
    "chunked_from": 0.4,
}


def build_lineage_index(storage: LocalStorage, project_id: str | None = None, *, persist: bool = True) -> dict[str, Any]:
    storage.ensure_layout()
    rows = _scan_assets(storage, project_id=project_id or "")
    by_id = {str(row["id"]): row for row in rows if str(row.get("id") or "")}
    by_key: dict[str, str] = {}
    for row in rows:
        for key in [row.get("id"), row.get("path"), row.get("relative_path")]:
            if str(key or "").strip():
                by_key[str(key)] = str(row["id"])
    nodes = [_node_from_asset(row) for row in rows]
    edges = _derive_edges(rows, by_id=by_id, by_key=by_key)
    index = {
        "index_id": make_id("mkaos_lineage_index", f"{project_id or 'all'} {utc_now()}"),
        "project_id": project_id or "",
        "nodes": nodes,
        "edges": edges,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "source_asset_ids": sorted({node["asset_id"] for node in nodes if node["asset_type"] in {"source_repository", "source_document", "source_chunk", "book_source", "book_chapter_source", "parallel_text_pair"}}),
        "source_isolation": {"raw_text_included": False, "clean_text_included": False, "source_text_included": False, "target_text_included": False},
        "generated_at": utc_now(),
    }
    if persist:
        asset = BaseAsset(
            id=index["index_id"],
            type="mkaos_lineage_index",
            title="MKAOS lineage index",
            source="mkaos-lineage",
            tags=["mkaos", "lineage", "index"],
            content=index,
            metadata={"project_id": project_id or "", "generated_at": index["generated_at"], "source_isolation": index["source_isolation"]},
            references=filter_project_safe_references(storage, project_id or "", index["source_asset_ids"][:200]),
        )
        _write_asset(storage, asset)
        index["path"] = _asset_path(storage, asset.id, "runs")
    return index


def get_latest_lineage_index(storage: LocalStorage, project_id: str | None = None) -> dict[str, Any]:
    for path in reversed(storage.list_json("runs")):
        try:
            data = storage.read_json(path)
        except (OSError, TypeError, ValueError):
            continue
        if not isinstance(data, dict) or data.get("type") != "mkaos_lineage_index":
            continue
        content = _content(data)
        if project_id and str(content.get("project_id") or _metadata(data).get("project_id") or "") != project_id:
            continue
        return {**content, "path": _display_path(storage, path), "asset": data}
    return build_lineage_index(storage, project_id=project_id, persist=True)


def list_lineage_reports(storage: LocalStorage, project_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in reversed(storage.list_json("runs")):
        if len(rows) >= limit:
            break
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") not in {"mkaos_lineage_index", "mkaos_lineage_query_report", "mkaos_lineage_diff_report", "mkaos_lineage_export_package", "mkaos_asset_impact_report", "mkaos_weight_governance_report"}:
            continue
        if project_id and str(_content(data).get("project_id") or _metadata(data).get("project_id") or "") != project_id:
            continue
        rows.append(_row(storage, path, data))
    return rows


def query_lineage_path(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    project_id = str(payload.get("project_id") or "")
    index = get_latest_lineage_index(storage, project_id=project_id or None) if not payload.get("rebuild") else build_lineage_index(storage, project_id=project_id or None)
    source_id = _resolve_query_asset_id(index, payload.get("source_asset_id") or payload.get("source_id") or payload.get("asset_id") or payload.get("from"))
    target_id = _resolve_query_asset_id(index, payload.get("target_asset_id") or payload.get("target_id") or payload.get("to"))
    if not source_id and payload.get("knowledge_id"):
        source_id = _resolve_query_asset_id(index, payload.get("knowledge_id"))
    max_depth = int(payload.get("max_depth") or 8)
    paths = _find_paths(index, source_id=source_id, target_id=target_id, max_depth=max_depth)
    report = {
        "query_report_id": make_id("mkaos_lineage_query_report", f"{source_id} {target_id} {utc_now()}"),
        "project_id": project_id,
        "source_asset_id": source_id,
        "target_asset_id": target_id,
        "paths": paths[: int(payload.get("limit") or 20)],
        "path_count": len(paths),
        "source_isolation": index.get("source_isolation", {}),
        "explanation": "Local lineage BFS over safe asset ids and references; source raw text fields are not indexed.",
        "generated_at": utc_now(),
    }
    if payload.get("persist", True):
        _persist_report(storage, "mkaos_lineage_query_report", report["query_report_id"], "MKAOS lineage query report", report, project_id=project_id, references=[source_id, target_id])
    return report


def diff_lineage_indexes(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    project_id = str(payload.get("project_id") or "")
    left = _lineage_index_from_payload(storage, payload, "left") or build_lineage_index(storage, project_id=project_id or None, persist=False)
    right = _lineage_index_from_payload(storage, payload, "right") or build_lineage_index(storage, project_id=project_id or None, persist=False)
    left_nodes = {str(node.get("asset_id") or ""): node for node in left.get("nodes", []) if isinstance(node, dict)}
    right_nodes = {str(node.get("asset_id") or ""): node for node in right.get("nodes", []) if isinstance(node, dict)}
    left_edges = {_edge_key(edge): edge for edge in left.get("edges", []) if isinstance(edge, dict)}
    right_edges = {_edge_key(edge): edge for edge in right.get("edges", []) if isinstance(edge, dict)}
    changed_nodes = [
        {
            "asset_id": asset_id,
            "left_status": left_nodes[asset_id].get("status", ""),
            "right_status": right_nodes[asset_id].get("status", ""),
            "left_risk": left_nodes[asset_id].get("risk_level", ""),
            "right_risk": right_nodes[asset_id].get("risk_level", ""),
        }
        for asset_id in sorted(set(left_nodes) & set(right_nodes))
        if left_nodes[asset_id].get("status") != right_nodes[asset_id].get("status")
        or left_nodes[asset_id].get("risk_level") != right_nodes[asset_id].get("risk_level")
    ]
    report = {
        "diff_report_id": make_id("mkaos_lineage_diff_report", f"{project_id or 'all'} {utc_now()}"),
        "project_id": project_id,
        "left_index_id": str(left.get("index_id") or left.get("id") or ""),
        "right_index_id": str(right.get("index_id") or right.get("id") or ""),
        "added_nodes": [right_nodes[key] for key in sorted(set(right_nodes) - set(left_nodes))],
        "removed_nodes": [left_nodes[key] for key in sorted(set(left_nodes) - set(right_nodes))],
        "changed_nodes": changed_nodes,
        "added_edges": [right_edges[key] for key in sorted(set(right_edges) - set(left_edges))],
        "removed_edges": [left_edges[key] for key in sorted(set(left_edges) - set(right_edges))],
        "source_isolation": {"raw_text_included": False, "source_text_included": False, "target_text_included": False},
        "generated_at": utc_now(),
    }
    if payload.get("persist", True):
        _persist_report(storage, "mkaos_lineage_diff_report", report["diff_report_id"], "MKAOS lineage diff report", report, project_id=project_id, references=[report["left_index_id"], report["right_index_id"]])
    return report


def export_lineage_graph(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    project_id = str(payload.get("project_id") or "")
    index = build_lineage_index(storage, project_id=project_id or None, persist=False) if payload.get("rebuild") else get_latest_lineage_index(storage, project_id=project_id or None)
    limit = int(payload.get("limit") or 200)
    nodes = [node for node in index.get("nodes", []) if isinstance(node, dict)][:limit]
    node_ids = {str(node.get("asset_id") or "") for node in nodes}
    edges = [edge for edge in index.get("edges", []) if isinstance(edge, dict) and edge.get("source") in node_ids and edge.get("target") in node_ids]
    relation_counts: dict[str, int] = defaultdict(int)
    clusters: dict[str, dict[str, Any]] = {}
    for node in nodes:
        asset_type = str(node.get("asset_type") or "unknown")
        cluster = clusters.setdefault(asset_type, {"cluster_id": asset_type, "asset_type": asset_type, "count": 0, "nodes": []})
        cluster["count"] += 1
        cluster["nodes"].append(str(node.get("asset_id") or ""))
    for edge in edges:
        relation_counts[str(edge.get("relation_type") or "derived_from")] += 1
        edge["semantic_weight"] = _relation_weight(str(edge.get("relation_type") or ""))
    ranked_edges = sorted(edges, key=lambda edge: (-float(edge.get("semantic_weight", 0.0)), str(edge.get("relation_type") or ""), str(edge.get("source") or "")))
    export = {
        "export_id": make_id("mkaos_lineage_export_package", f"{project_id or 'all'} {utc_now()}"),
        "project_id": project_id,
        "index_id": str(index.get("index_id") or ""),
        "nodes": nodes,
        "edges": ranked_edges[: limit * 3],
        "clusters": list(clusters.values()),
        "relation_counts": dict(sorted(relation_counts.items())),
        "semantic_ranking": {
            "relation_weights": RELATION_WEIGHTS,
            "top_edges": ranked_edges[:20],
            "ranking_note": "Deterministic local ranking by governance relation importance; protected evidence text fields are excluded.",
        },
        "visualization": _layout_nodes(nodes),
        "source_isolation": {"raw_text_included": False, "source_text_included": False, "target_text_included": False},
        "generated_at": utc_now(),
    }
    if payload.get("persist", True):
        _persist_report(storage, "mkaos_lineage_export_package", export["export_id"], "MKAOS lineage graph export", export, project_id=project_id, references=[str(index.get("index_id") or "")])
    return export


def analyze_asset_impact(storage: LocalStorage, payload: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(payload, str):
        payload = {"asset_id": payload}
    project_id = str(payload.get("project_id") or "")
    asset_id = _resolve_query_asset_id(get_latest_lineage_index(storage, project_id=project_id or None), payload.get("asset_id") or payload.get("knowledge_id"))
    index = get_latest_lineage_index(storage, project_id=project_id or None) if not payload.get("rebuild") else build_lineage_index(storage, project_id=project_id or None)
    downstream = _reachable(index, asset_id, direction="downstream", max_depth=int(payload.get("max_depth") or 8))
    upstream = _reachable(index, asset_id, direction="upstream", max_depth=4)
    nodes = {node["asset_id"]: node for node in index.get("nodes", []) if isinstance(node, dict)}
    downstream_nodes = [nodes[item] for item in downstream if item in nodes]
    review_issues = [node for node in downstream_nodes if node.get("asset_type") == "review_issue"]
    feedback_signals = [node for node in downstream_nodes if node.get("asset_type") in {"reader_feedback", "mkaos_feedback_attribution"}]
    usage_feedback_signals = [node for node in downstream_nodes if node.get("asset_type") in {"knowledge_usage_event", "material_usage_event"}]
    source_refresh_signals = _source_refresh_signals_for_asset(storage, nodes.get(asset_id, {}), project_id=project_id)
    source_refresh_risky = [item for item in source_refresh_signals if str(item.get("decision") or "") not in {"", "current"}]
    gate_blocks = [node for node in downstream_nodes if node.get("asset_type") == "mkaos_production_gate_report" and node.get("status") == "blocked"]
    negative_feedback = any(str(node.get("risk_level") or "") in {"medium", "high", "critical"} for node in feedback_signals)
    positive_feedback = bool(feedback_signals) and not negative_feedback
    quarantined_source = any(str(item.get("decision") or "") == "blocked_quarantined" for item in source_refresh_signals)
    stale_source = bool(source_refresh_risky)
    risk_level = "high" if gate_blocks or len(review_issues) >= 2 or quarantined_source else "medium" if review_issues or negative_feedback or stale_source else "low"
    action = "quarantine" if gate_blocks or quarantined_source else "review" if review_issues or negative_feedback or stale_source else "increase_weight" if positive_feedback else "keep"
    weight_delta = -0.25 if action == "quarantine" else -0.1 if action == "review" else 0.08 if action == "increase_weight" else 0.0
    invalidation_recommendations = _source_refresh_invalidation_recommendations(asset_id, source_refresh_risky)
    report = {
        "impact_report_id": make_id("mkaos_asset_impact_report", f"{asset_id} {utc_now()}"),
        "project_id": project_id,
        "asset_id": asset_id,
        "asset_type": nodes.get(asset_id, {}).get("asset_type", ""),
        "downstream_assets": downstream_nodes,
        "upstream_assets": [nodes[item] for item in upstream if item in nodes],
        "used_in_flows": sorted({node.get("flow", "") for node in downstream_nodes if node.get("flow")}),
        "review_issues": review_issues,
        "feedback_signals": feedback_signals,
        "usage_feedback_signals": usage_feedback_signals,
        "usage_feedback_count": len(usage_feedback_signals),
        "negative_feedback_signal": negative_feedback,
        "positive_feedback_signal": positive_feedback,
        "source_refresh_signals": source_refresh_signals,
        "source_refresh_signal_count": len(source_refresh_signals),
        "stale_source_signal": stale_source,
        "invalidation_recommendations": invalidation_recommendations,
        "gate_blocks": gate_blocks,
        "risk_level": risk_level,
        "recommended_action": action,
        "weight_delta_suggestion": weight_delta,
        "source_isolation": index.get("source_isolation", {}),
        "generated_at": utc_now(),
    }
    if payload.get("persist", True):
        _persist_report(storage, "mkaos_asset_impact_report", report["impact_report_id"], "MKAOS asset impact report", report, project_id=project_id, references=[asset_id])
    return report


def _source_refresh_signals_for_asset(storage: LocalStorage, node: dict[str, Any], *, project_id: str) -> list[dict[str, Any]]:
    asset_id = str(node.get("asset_id") or "")
    if not asset_id:
        return []
    asset = _asset_data_for_node(storage, node)
    content = _content(asset)
    metadata = _metadata(asset)
    source_eligibility = content.get("source_eligibility") if isinstance(content.get("source_eligibility"), dict) else {}
    if not source_eligibility and isinstance(metadata.get("source_eligibility"), dict):
        source_eligibility = metadata.get("source_eligibility", {})
    ref_keys: set[str] = set()
    for field in ["source_policy_refs", "source_risk_report_refs", "source_snapshot_refs"]:
        values = source_eligibility.get(field, [])
        if isinstance(values, list):
            ref_keys.update(str(item) for item in values if str(item).strip())
    source_refs = {str(item) for item in source_eligibility.get("source_refs", []) if str(item).strip()} if isinstance(source_eligibility.get("source_refs", []), list) else set()
    if not ref_keys and not source_refs:
        return []
    signals: list[dict[str, Any]] = []
    for path in reversed(storage.list_json("runs")):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "source_refresh_report":
            continue
        if project_id and _project_id(data) not in {"", project_id}:
            continue
        refresh = _content(data)
        governance_refs = refresh.get("governance_refs", {}) if isinstance(refresh.get("governance_refs"), dict) else {}
        refresh_refs = {str(value) for value in governance_refs.values() if str(value).strip()}
        refresh_source_ref = str(refresh.get("source_ref") or "")
        if not (ref_keys & refresh_refs or (refresh_source_ref and refresh_source_ref in source_refs)):
            continue
        signals.append(
            {
                "source_refresh_report_id": str(data.get("id") or refresh.get("refresh_report_id") or ""),
                "path": _display_path(storage, path),
                "source_ref": refresh_source_ref,
                "decision": str(refresh.get("decision") or ""),
                "stale_flags": _strip_raw(refresh.get("stale_flags", []) if isinstance(refresh.get("stale_flags", []), list) else []),
                "governance_refs": governance_refs,
                "next_actions": refresh.get("next_actions", []) if isinstance(refresh.get("next_actions", []), list) else [],
            }
        )
    return signals[:20]


def _source_refresh_invalidation_recommendations(asset_id: str, source_refresh_signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    for signal in source_refresh_signals:
        decision = str(signal.get("decision") or "")
        if not decision or decision == "current":
            continue
        stale_codes = {
            str(item.get("code") or "")
            for item in signal.get("stale_flags", [])
            if isinstance(item, dict)
        }
        recommendations.append(
            {
                "target_asset_id": asset_id,
                "source_refresh_report_id": str(signal.get("source_refresh_report_id") or ""),
                "decision": decision,
                "recommended_action": "quarantine_source_derived_asset" if decision == "blocked_quarantined" else "review_source_governance",
                "downstream_action": "invalidate_context_and_regenerate_after_review" if {"content_hash_drift", "source_snapshot_stale"} & stale_codes else "operator_review_before_next_context_selection",
                "auto_applied": False,
                "requires_operator_review": True,
                "reason": f"source refresh decision={decision}; stale_flags={', '.join(sorted(stale_codes)) or 'none'}",
            }
        )
    return recommendations


def _asset_data_for_node(storage: LocalStorage, node: dict[str, Any]) -> dict[str, Any]:
    path = str(node.get("path") or "").strip()
    if path:
        try:
            data = storage.read_json(storage.root / path)
            return data if isinstance(data, dict) else {}
        except (OSError, TypeError, ValueError):
            pass
    asset_id = str(node.get("asset_id") or "")
    for category in DATA_DIRS:
        for candidate in storage.list_json(category):
            try:
                data = storage.read_json(candidate)
            except (OSError, TypeError, ValueError):
                continue
            if isinstance(data, dict) and str(data.get("id") or "") == asset_id:
                return data
    return {}


def query_issue_attribution(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    issue_id = str(payload.get("review_issue_id") or payload.get("issue_id") or payload.get("asset_id") or "")
    return {
        "issue_id": issue_id,
        "lineage": query_lineage_path(storage, {**payload, "source_asset_id": issue_id, "max_depth": payload.get("max_depth", 6), "persist": False}),
        "impact": analyze_asset_impact(storage, {**payload, "asset_id": issue_id, "persist": False}),
    }


def query_feedback_attribution(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    feedback_id = str(payload.get("feedback_id") or payload.get("asset_id") or "")
    return {
        "feedback_id": feedback_id,
        "lineage": query_lineage_path(storage, {**payload, "source_asset_id": feedback_id, "max_depth": payload.get("max_depth", 6), "persist": False}),
        "impact": analyze_asset_impact(storage, {**payload, "asset_id": feedback_id, "persist": False}),
    }


def query_gate_attribution(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    gate_id = str(payload.get("gate_report_id") or payload.get("asset_id") or "")
    return {
        "gate_report_id": gate_id,
        "lineage": query_lineage_path(storage, {**payload, "source_asset_id": gate_id, "max_depth": payload.get("max_depth", 6), "persist": False}),
        "impact": analyze_asset_impact(storage, {**payload, "asset_id": gate_id, "persist": False}),
    }


def attribute_feedback_to_knowledge(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    project_id = str(payload.get("project_id") or "")
    generated_asset_id = str(payload.get("generated_asset_id") or payload.get("artifact_id") or payload.get("chapter_id") or "")
    feedback_id = str(payload.get("feedback_id") or make_id("reader_feedback", payload.get("feedback_text") or utc_now()))
    index = get_latest_lineage_index(storage, project_id=project_id or None) if not payload.get("rebuild") else build_lineage_index(storage, project_id=project_id or None)
    candidate_ids = _candidate_knowledge_for_asset(index, generated_asset_id)
    explicit_ids = _strings(payload.get("candidate_knowledge_ids"))
    knowledge_ids = _dedupe([*explicit_ids, *candidate_ids])
    sentiment = str(payload.get("sentiment") or _classify_sentiment(str(payload.get("feedback_text") or "")))
    issue_tags = _issue_tags(str(payload.get("feedback_text") or ""))
    negative = sentiment == "negative" or bool({"source_leakage", "exposition_overload", "ai_style"} & set(issue_tags))
    score = max(0.1, min(1.0, 0.8 if knowledge_ids else 0.35))
    attribution = {
        "feedback_attribution_id": make_id("mkaos_feedback_attribution", f"{feedback_id} {generated_asset_id} {utc_now()}"),
        "project_id": project_id,
        "feedback_id": feedback_id,
        "generated_asset_id": generated_asset_id,
        "related_agent_run_id": str(payload.get("related_agent_run_id") or ""),
        "related_context_bundle_id": str(payload.get("related_context_bundle_id") or payload.get("context_bundle_id") or ""),
        "related_knowledge_pack_id": str(payload.get("related_knowledge_pack_id") or payload.get("knowledge_pack_id") or ""),
        "knowledge_ids_used": knowledge_ids,
        "creative_asset_ids_used": _creative_assets_for_asset(index, generated_asset_id),
        "review_issue_ids": _strings(payload.get("review_issue_ids")),
        "gate_report_ids": _strings(payload.get("gate_report_ids")),
        "positive_signals": [] if negative else [sentiment],
        "negative_signals": issue_tags if negative else [],
        "attribution_score": score,
        "weight_delta": round((-0.08 if negative else 0.06) * score, 4),
        "reason": _attribution_reason(sentiment, issue_tags, bool(knowledge_ids)),
        "evidence_refs": _dedupe([feedback_id, generated_asset_id, *knowledge_ids, *payload.get("evidence_refs", [])]) if isinstance(payload.get("evidence_refs", []), list) else _dedupe([feedback_id, generated_asset_id, *knowledge_ids]),
        "source_isolation": {"raw_text_included": False, "source_text_included": False, "target_text_included": False},
        "created_at": utc_now(),
    }
    asset = BaseAsset(
        id=attribution["feedback_attribution_id"],
        type="mkaos_feedback_attribution",
        title="MKAOS feedback attribution",
        source="mkaos-lineage",
        tags=["mkaos", "feedback-attribution", sentiment],
        content=attribution,
        metadata={"project_id": project_id, "sentiment": sentiment, "source_isolation": attribution["source_isolation"]},
        references=filter_project_safe_references(storage, project_id, attribution["evidence_refs"]),
    )
    path = _write_asset(storage, asset)
    return {"path": _display_path(storage, path), "asset": asset.to_dict(), **attribution}


def apply_lineage_weight_governance(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    project_id = str(payload.get("project_id") or "")
    apply_updates = bool(payload.get("apply_updates") or payload.get("apply"))
    apply_policy = str(payload.get("apply_policy") or "").strip()
    if apply_updates and apply_policy not in {"explicit", "guarded_auto"}:
        raise ValueError("apply_policy=explicit or guarded_auto is required when apply_updates=true")
    dry_run = False if apply_updates else bool(payload.get("dry_run", True))
    asset_id = str(payload.get("asset_id") or payload.get("knowledge_id") or "")
    targets = [asset_id] if asset_id else _knowledge_ids_from_index(get_latest_lineage_index(storage, project_id=project_id or None))
    recommendations: list[dict[str, Any]] = []
    for target_id in targets[: int(payload.get("limit") or 50)]:
        impact = analyze_asset_impact(storage, {"project_id": project_id, "asset_id": target_id, "persist": False})
        recommendations.append(
            {
                "asset_id": target_id,
                "asset_type": impact.get("asset_type", ""),
                "recommended_action": impact.get("recommended_action", "keep"),
                "weight_delta": impact.get("weight_delta_suggestion", 0.0),
                "risk_level": impact.get("risk_level", "low"),
                "dry_run": dry_run,
                "reason": f"{len(impact.get('review_issues', []))} review issues, {len(impact.get('feedback_signals', []))} feedback signals, {len(impact.get('usage_feedback_signals', []))} usage events, {len(impact.get('source_refresh_signals', []))} source refresh signals, {len(impact.get('gate_blocks', []))} gate blocks",
                "usage_feedback_count": impact.get("usage_feedback_count", 0),
                "source_refresh_signal_count": impact.get("source_refresh_signal_count", 0),
                "invalidation_recommendations": impact.get("invalidation_recommendations", []),
                "review_required_before_apply": bool(impact.get("stale_source_signal") or impact.get("invalidation_recommendations")),
            }
        )
    applied_updates: list[dict[str, Any]] = []
    if apply_updates:
        for recommendation in recommendations:
            target_id = str(recommendation.get("asset_id") or "")
            delta = float(recommendation.get("weight_delta") or 0.0)
            action = str(recommendation.get("recommended_action") or "keep")
            if not target_id or (delta == 0.0 and action not in {"quarantine", "deprecate"}):
                continue
            update_payload = {
                "project_id": project_id or "local-system",
                "knowledge_id": target_id,
                "delta": delta,
                "flow": str(payload.get("flow") or "feedback"),
                "reason": str(payload.get("reason") or "lineage_weight_governance"),
                "actor": str(payload.get("actor") or "mkaos_lineage"),
                "trace_id": str(payload.get("trace_id") or ""),
                "environment": str(payload.get("environment") or "compat"),
                "bypass_reason": str(payload.get("bypass_reason") or "explicit_lineage_weight_governance_apply"),
                "os_envelope": payload.get("os_envelope") if isinstance(payload.get("os_envelope"), dict) else {},
            }
            applied: dict[str, Any] = {"asset_id": target_id, "action": action, "weight_delta": delta, "status_change": ""}
            if delta != 0.0:
                result = mkaos_service.apply_weight_update(storage, update_payload)
                applied["weight_result"] = {
                    "delta": result.get("delta"),
                    "status": result.get("status"),
                    "path": result.get("knowledge", {}).get("path", ""),
                }
            if action == "quarantine":
                status = mkaos_service.change_knowledge_status(
                    storage,
                    target_id,
                    {
                        "status": "quarantined",
                        "reason": str(payload.get("reason") or "lineage_weight_governance"),
                        "actor": str(payload.get("actor") or "mkaos_lineage"),
                        "trace_id": str(payload.get("trace_id") or ""),
                    },
                )
                applied["status_change"] = "quarantined"
                applied["status_path"] = status.get("path", "")
            elif action == "deprecate":
                result = mkaos_service.apply_weight_update(storage, {**update_payload, "action": "deprecated"})
                applied["weight_result"] = {
                    "delta": result.get("delta"),
                    "status": result.get("status"),
                    "path": result.get("knowledge", {}).get("path", ""),
                }
                applied["status_change"] = "deprecated"
            applied_updates.append(applied)
    report = {
        "weight_governance_report_id": make_id("mkaos_weight_governance_report", f"{project_id or 'all'} {utc_now()}"),
        "project_id": project_id,
        "dry_run": dry_run,
        "apply_updates": apply_updates,
        "apply_policy": apply_policy or "advisory",
        "recommendations": recommendations,
        "applied_updates": applied_updates,
        "applied_count": len(applied_updates),
        "governance_contract": {
            "contract_version": "usage-feedback-weight-governance-v1",
            "usage_feedback_auto_applied": False,
            "source_refresh_auto_invalidated": False,
            "operator_review_required_for_invalidation": True,
        },
        "source_isolation": {"raw_text_included": False, "source_text_included": False, "target_text_included": False},
        "generated_at": utc_now(),
    }
    _persist_report(storage, "mkaos_weight_governance_report", report["weight_governance_report_id"], "MKAOS weight governance report", report, project_id=project_id, references=[item["asset_id"] for item in recommendations])
    return report


def _scan_assets(storage: LocalStorage, *, project_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for category in DATA_DIRS:
        for path in storage.list_json(category):
            try:
                data = storage.read_json(path)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            asset_type = str(data.get("type") or "")
            if asset_type not in NODE_TYPES and not _is_mkaos_relevant(data):
                continue
            asset_project_id = _project_id(data)
            if project_id and asset_project_id and asset_project_id != project_id:
                continue
            rows.append({**data, "path": _display_path(storage, path), "relative_path": _display_path(storage, path), "category": category})
    return rows


def _derive_edges(rows: list[dict[str, Any]], *, by_id: dict[str, dict[str, Any]], by_key: dict[str, str]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def add(source: str, target: str, relation: str, evidence: str = "") -> None:
        source_id = by_key.get(str(source), str(source))
        target_id = by_key.get(str(target), str(target))
        if not source_id or not target_id or source_id == target_id:
            return
        if source_id not in by_id or target_id not in by_id:
            return
        key = (source_id, target_id, relation)
        if key in seen:
            return
        seen.add(key)
        edges.append({"source": source_id, "target": target_id, "relation_type": relation, "evidence_ref": evidence, "created_at": utc_now()})

    for row in rows:
        asset_id = str(row.get("id") or "")
        asset_type = str(row.get("type") or "")
        content = _content(row)
        for ref in _references(row):
            relation = _generic_relation(asset_type, by_id.get(by_key.get(ref, ref), {}))
            add(ref, asset_id, relation, ref)
        for ref in _strings(content.get("source_document_id")):
            add(ref, asset_id, "chunked_from" if asset_type == "source_chunk" else "derived_from", ref)
        for ref in _strings(content.get("source_chunk_id")) + _strings(content.get("source_chunk_ids")):
            add(ref, asset_id, "abstracted_to" if "knowledge" in asset_type or asset_type.endswith("_card") else "derived_from", ref)
        for ref in _strings(content.get("evidence_refs")):
            add(ref, asset_id, "derived_from", ref)
        for ref in _strings(content.get("knowledge_id")) + _strings(content.get("knowledge_ids")) + _strings(content.get("selected_knowledge_ids")) + _strings(content.get("related_knowledge_ids")):
            add(ref, asset_id, _relation_for_knowledge_target(asset_type), ref)
        for ref in _strings(content.get("material_id")) + _strings(content.get("material_ids")):
            add(ref, asset_id, "used_in_context" if asset_type == "material_usage_event" else "used_in_generation", ref)
        for ref in _strings(content.get("creative_asset_ids")) + _strings(content.get("creative_asset_ids_used")):
            add(ref, asset_id, "converted_to" if asset_type.endswith("_card") else "used_in_generation", ref)
        for ref in _strings(content.get("knowledge_pack_id")) + _strings(content.get("mkaos_pack_id")) + _strings(content.get("mkaos_knowledge_pack_id")) + _strings(content.get("related_knowledge_pack_id")):
            add(ref, asset_id, "used_in_context" if asset_type == "context_bundle" else "used_in_generation", ref)
        for ref in _strings(content.get("context_bundle_id")) + _strings(content.get("related_context_bundle_id")):
            add(ref, asset_id, "used_in_generation", ref)
        for ref in _strings(content.get("target_asset_id")) + _strings(content.get("generated_asset_id")) + _strings(content.get("artifact_id")):
            add(ref, asset_id, "reviewed_by" if asset_type in {"review_issue", "review_report"} else "used_in_generation", ref)
        for ref in _strings(content.get("review_issue_ids")):
            add(ref, asset_id, "fixed_by_revision" if asset_type == "revision_task" else "caused_review_issue", ref)
        for ref in _strings(content.get("feedback_id")):
            add(ref, asset_id, "attributed_to_feedback", ref)
        for ref in _strings(content.get("gate_report_ids")):
            add(ref, asset_id, "blocked_by_gate", ref)
        if asset_type == "knowledge_pack":
            for item in _pack_item_ids(content):
                add(item, asset_id, "selected_by_pack", item)
        if asset_type == "mkaos_production_gate_report":
            for ref in _strings(content.get("context_bundle_id")) + _strings(content.get("knowledge_pack_id")) + _strings(content.get("target_asset_id")):
                add(ref, asset_id, "blocked_by_gate" if not content.get("passed", True) else "reviewed_by", ref)
    return edges


def _find_paths(index: dict[str, Any], *, source_id: str, target_id: str, max_depth: int) -> list[dict[str, Any]]:
    if not source_id:
        return []
    edges = [edge for edge in index.get("edges", []) if isinstance(edge, dict)]
    adjacency: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        adjacency[str(edge.get("source") or "")].append(edge)
    found: list[list[dict[str, Any]]] = []
    queue: deque[tuple[str, list[dict[str, Any]]]] = deque([(source_id, [])])
    visited: set[tuple[str, int]] = {(source_id, 0)}
    while queue and len(found) < 50:
        node_id, path_edges = queue.popleft()
        if path_edges and (not target_id or node_id == target_id):
            found.append(path_edges)
            if target_id:
                continue
        if len(path_edges) >= max_depth:
            continue
        for edge in adjacency.get(node_id, []):
            next_id = str(edge.get("target") or "")
            state = (next_id, len(path_edges) + 1)
            if state in visited:
                continue
            visited.add(state)
            queue.append((next_id, [*path_edges, edge]))
    nodes = {node["asset_id"]: node for node in index.get("nodes", []) if isinstance(node, dict)}
    explained = [_explain_path(path, nodes) for path in found]
    return sorted(explained, key=lambda path: (-float(path.get("semantic_score") or 0.0), len(path.get("edges", [])), str(path.get("explanation") or "")))


def _reachable(index: dict[str, Any], asset_id: str, *, direction: str, max_depth: int) -> list[str]:
    if not asset_id:
        return []
    adjacency: dict[str, list[str]] = defaultdict(list)
    for edge in index.get("edges", []):
        if not isinstance(edge, dict):
            continue
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if direction == "upstream":
            adjacency[target].append(source)
        else:
            adjacency[source].append(target)
    result: list[str] = []
    queue: deque[tuple[str, int]] = deque([(asset_id, 0)])
    seen = {asset_id}
    while queue:
        current, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for next_id in adjacency.get(current, []):
            if next_id in seen:
                continue
            seen.add(next_id)
            result.append(next_id)
            queue.append((next_id, depth + 1))
    return result


def _explain_path(path_edges: list[dict[str, Any]], nodes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    node_ids = _dedupe([path_edges[0]["source"], *[edge["target"] for edge in path_edges]])
    score = round(sum(_relation_weight(str(edge.get("relation_type") or "")) for edge in path_edges) / max(1, len(path_edges)), 4)
    return {
        "path": [nodes.get(node_id, {"asset_id": node_id}) for node_id in node_ids],
        "edges": path_edges,
        "explanation": " -> ".join([f"{edge['source']} -{edge['relation_type']}-> {edge['target']}" for edge in path_edges]),
        "semantic_score": score,
        "semantic_rank_reason": "Weighted by governance-critical relation types such as gate blocks, review issues, feedback, and production usage.",
        "evidence_refs": _dedupe([str(edge.get("evidence_ref") or "") for edge in path_edges if str(edge.get("evidence_ref") or "").strip()]),
        "rules": [],
        "risks": [node for node in [nodes.get(node_id, {}) for node_id in node_ids] if str(node.get("risk_level") or "") in {"high", "critical"}],
        "observed_effects": [edge for edge in path_edges if edge.get("relation_type") in {"improved_by_feedback", "hurt_by_feedback", "attributed_to_feedback"}],
        "source_isolation": {"raw_text_included": False, "clean_text_included": False, "source_text_included": False, "target_text_included": False},
    }


def _node_from_asset(row: dict[str, Any]) -> dict[str, Any]:
    content = _content(row)
    metadata = _metadata(row)
    asset_type = str(row.get("type") or "")
    status = str(content.get("status") or metadata.get("asset_status") or metadata.get("status") or "")
    if asset_type == "mkaos_production_gate_report" and not content.get("passed", True):
        status = "blocked"
    risk_level = str(content.get("risk_level") or metadata.get("risk_level") or "")
    if asset_type == "mkaos_feedback_attribution" and (content.get("negative_signals") or float(content.get("weight_delta") or 0.0) < 0):
        risk_level = risk_level or "medium"
    return {
        "asset_id": str(row.get("id") or ""),
        "asset_type": asset_type,
        "title": str(row.get("title") or ""),
        "path": str(row.get("path") or ""),
        "project_id": _project_id(row),
        "status": status,
        "risk_level": risk_level,
        "flow": str(content.get("flow") or content.get("mkaos_flow") or metadata.get("flow") or metadata.get("mkaos_flow") or ""),
        "source": str(row.get("source") or ""),
        "content_summary": _safe_summary(content),
    }


def _safe_summary(content: dict[str, Any]) -> dict[str, Any]:
    allowed = [
        "source_type",
        "knowledge_type",
        "discipline",
        "abstraction_level",
        "creative_principle",
        "narrative_function",
        "conflict_function",
        "character_function",
        "worldbuilding_function",
        "review_function",
        "applicable_flows",
        "quality_dimensions",
        "confidence",
        "selector_policy_version",
        "recommendation",
        "decision",
        "stale_flags",
        "source_eligibility",
        "material_id",
        "passed",
        "blocking_issue_count",
        "positive_signals",
        "negative_signals",
        "weight_delta",
        "attribution_score",
    ]
    result: dict[str, Any] = {}
    for key in allowed:
        value = content.get(key)
        if value is None:
            continue
        result[key] = _strip_raw(value)
    return result


def _strip_raw(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _strip_raw(val) for key, val in value.items() if key not in RAW_FIELD_NAMES}
    if isinstance(value, list):
        return [_strip_raw(item) for item in value[:20]]
    if isinstance(value, str):
        return value[:500]
    return value


def _references(data: dict[str, Any]) -> list[str]:
    refs = _strings(data.get("references"))
    refs.extend(_strings(data.get("source")))
    content = _content(data)
    refs.extend(_strings(content.get("references")))
    refs.extend(_strings(content.get("evidence_refs")))
    return _dedupe(refs)


def _pack_item_ids(content: dict[str, Any]) -> list[str]:
    items = content.get("pack_items") or content.get("selected_items") or []
    ids: list[str] = []
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                ids.extend(_strings(item.get("knowledge_id") or item.get("asset_id") or item.get("id")))
            else:
                ids.extend(_strings(item))
    return _dedupe(ids)


def _relation_for_knowledge_target(asset_type: str) -> str:
    if asset_type == "knowledge_pack":
        return "selected_by_pack"
    if asset_type == "context_bundle":
        return "used_in_context"
    if asset_type in {"review_issue", "review_report"}:
        return "caused_review_issue"
    if asset_type in {"reader_feedback", "mkaos_feedback_attribution"}:
        return "attributed_to_feedback"
    if asset_type == "mkaos_production_gate_report":
        return "blocked_by_gate"
    return "used_in_generation"


def _generic_relation(asset_type: str, ref_asset: dict[str, Any]) -> str:
    ref_type = str(ref_asset.get("type") or "")
    if asset_type == "knowledge_pack" and ref_type in {"knowledge_card", "mkaos_model_extraction_candidate"}:
        return "selected_by_pack"
    if asset_type == "context_bundle" and ref_type == "knowledge_pack":
        return "used_in_context"
    if asset_type in {"draft_chapter", "draft_version", "review_report", "publish_gate_report", "release_package"} and ref_type == "context_bundle":
        return "used_in_generation"
    if asset_type.endswith("_card") and ref_type in {"knowledge_card", "mkaos_model_extraction_candidate"}:
        return "converted_to"
    if asset_type == "knowledge_card" and ref_type in {"source_chunk", "source_document", "book_chapter_source", "parallel_text_pair"}:
        return "abstracted_to"
    return "derived_from"


def _candidate_knowledge_for_asset(index: dict[str, Any], asset_id: str) -> list[str]:
    upstream = _reachable(index, asset_id, direction="upstream", max_depth=5)
    nodes = {node["asset_id"]: node for node in index.get("nodes", []) if isinstance(node, dict)}
    return [node_id for node_id in upstream if nodes.get(node_id, {}).get("asset_type") in {"knowledge_card", "mkaos_model_extraction_candidate"}]


def _creative_assets_for_asset(index: dict[str, Any], asset_id: str) -> list[str]:
    upstream = _reachable(index, asset_id, direction="upstream", max_depth=5)
    nodes = {node["asset_id"]: node for node in index.get("nodes", []) if isinstance(node, dict)}
    return [node_id for node_id in upstream if str(nodes.get(node_id, {}).get("asset_type") or "").endswith("_card") and nodes.get(node_id, {}).get("asset_type") != "knowledge_card"]


def _knowledge_ids_from_index(index: dict[str, Any]) -> list[str]:
    return [str(node.get("asset_id") or "") for node in index.get("nodes", []) if isinstance(node, dict) and node.get("asset_type") in {"knowledge_card", "mkaos_model_extraction_candidate"}]


def _resolve_query_asset_id(index: dict[str, Any], value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    for node in index.get("nodes", []):
        if not isinstance(node, dict):
            continue
        if raw in {str(node.get("asset_id") or ""), str(node.get("path") or ""), str(node.get("title") or "")}:
            return str(node.get("asset_id") or "")
    return raw


def _persist_report(storage: LocalStorage, asset_type: str, asset_id: str, title: str, content: dict[str, Any], *, project_id: str, references: list[str]) -> None:
    asset = BaseAsset(
        id=asset_id,
        type=asset_type,
        title=title,
        source="mkaos-lineage",
        tags=["mkaos", "lineage", asset_type],
        content=content,
        metadata={"project_id": project_id, "source_isolation": content.get("source_isolation", {})},
        references=filter_project_safe_references(storage, project_id, _dedupe(references)),
    )
    _write_asset(storage, asset)


def _write_asset(storage: LocalStorage, asset: BaseAsset):
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    return storage.write_asset_auto(asset)


def _asset_path(storage: LocalStorage, asset_id: str, category: str) -> str:
    return _display_path(storage, storage.data_dir(category) / f"{asset_id}.json")


def _display_path(storage: LocalStorage, path: Any) -> str:
    try:
        return str(path.relative_to(storage.root))
    except Exception:
        return str(path)


def _row(storage: LocalStorage, path: Any, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": _display_path(storage, path),
        "id": str(data.get("id") or ""),
        "type": str(data.get("type") or ""),
        "title": str(data.get("title") or ""),
        "content": _strip_raw(_content(data)),
        "metadata": _strip_raw(_metadata(data)),
        "references": _strings(data.get("references")),
    }


def _lineage_index_from_payload(storage: LocalStorage, payload: dict[str, Any], prefix: str) -> dict[str, Any] | None:
    direct = payload.get(f"{prefix}_index")
    if isinstance(direct, dict):
        return _content(direct) if direct.get("type") == "mkaos_lineage_index" else direct
    ref = str(payload.get(f"{prefix}_index_id") or payload.get(f"{prefix}_index_path") or "").strip()
    if not ref:
        return None
    candidate_path = storage.root / ref
    if candidate_path.exists():
        try:
            data = storage.read_json(candidate_path)
            return _content(data) if isinstance(data, dict) else None
        except Exception:
            return None
    for path in reversed(storage.list_json("runs")):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "mkaos_lineage_index":
            continue
        content = _content(data)
        if ref in {str(data.get("id") or ""), str(content.get("index_id") or ""), _display_path(storage, path)}:
            return {**content, "path": _display_path(storage, path), "asset": data}
    return None


def _edge_key(edge: dict[str, Any]) -> str:
    return "|".join([str(edge.get("source") or ""), str(edge.get("relation_type") or ""), str(edge.get("target") or "")])


def _relation_weight(relation: str) -> float:
    return float(RELATION_WEIGHTS.get(str(relation or ""), 0.35))


def _layout_nodes(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    clusters: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in nodes:
        clusters[str(node.get("asset_type") or "unknown")].append(node)
    positions: list[dict[str, Any]] = []
    for cluster_index, asset_type in enumerate(sorted(clusters)):
        for row_index, node in enumerate(clusters[asset_type]):
            positions.append(
                {
                    "asset_id": str(node.get("asset_id") or ""),
                    "asset_type": asset_type,
                    "x": cluster_index * 220,
                    "y": row_index * 84,
                    "cluster": asset_type,
                }
            )
    return {
        "layout": "deterministic_cluster_grid",
        "node_positions": positions,
        "cluster_count": len(clusters),
        "note": "Local first-slice graph layout for UI exploration; protected evidence text fields are excluded.",
    }


def _is_mkaos_relevant(data: dict[str, Any]) -> bool:
    tags = data.get("tags", []) if isinstance(data.get("tags", []), list) else []
    return str(data.get("type") or "").startswith("mkaos_") or "mkaos" in {str(tag) for tag in tags}


def _project_id(data: dict[str, Any]) -> str:
    return str(_metadata(data).get("project_id") or _content(data).get("project_id") or "")


def _content(data: dict[str, Any]) -> dict[str, Any]:
    return data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}


def _metadata(data: dict[str, Any]) -> dict[str, Any]:
    return data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}


def _strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (int, float)):
        return [str(value)]
    if isinstance(value, dict):
        result: list[str] = []
        for key in ["id", "asset_id", "knowledge_id", "path"]:
            if str(value.get(key) or "").strip():
                result.append(str(value.get(key)))
        return result
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_strings(item))
        return result
    return []


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _classify_sentiment(text: str) -> str:
    lowered = text.lower()
    if any(term in text for term in ["慢", "看不懂", "设定太多", "弃读", "像ai", "像 AI"]) or any(term in lowered for term in ["slow", "confusing", "boring", "ai style"]):
        return "negative"
    if any(term in text for term in ["好看", "期待", "爽", "想追"]) or any(term in lowered for term in ["great", "hooked", "strong"]):
        return "positive"
    return "neutral"


def _issue_tags(text: str) -> list[str]:
    tags: list[str] = []
    if any(term in text for term in ["设定太多", "资料", "百科"]):
        tags.append("exposition_overload")
    if any(term in text for term in ["节奏慢", "拖"]):
        tags.append("pacing")
    if any(term in text for term in ["像AI", "像 AI", "模板"]):
        tags.append("ai_style")
    if any(term in text for term in ["原文", "抄", "照搬"]):
        tags.append("source_leakage")
    if any(term in text for term in ["人物降智", "动机"]):
        tags.append("character_consistency")
    return tags or ["general_feedback"]


def _attribution_reason(sentiment: str, issue_tags: list[str], has_knowledge: bool) -> str:
    if not has_knowledge:
        return "No upstream knowledge found; needs human review."
    if sentiment == "negative":
        return f"Negative feedback mapped to {', '.join(issue_tags)} and upstream knowledge usage."
    if sentiment == "positive":
        return "Positive feedback mapped to upstream knowledge usage."
    return "Neutral feedback recorded for trend learning."
