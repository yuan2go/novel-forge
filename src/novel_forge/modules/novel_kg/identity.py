from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.modules.production_context import filter_project_safe_references
from novel_forge.schemas import KgIdentityResolution, validate_common_fields
from novel_forge.storage.local import LocalStorage

IDENTITY_NODE_COLLECTIONS = ["entities", "factions", "locations", "props", "rules", "power_scales", "foreshadowing", "review_rules", "templates"]


def build_identity_merge_queue(graph: dict[str, Any], *, min_confidence: float = 0.7) -> dict[str, Any]:
    nodes = _all_identity_nodes(graph)
    alias_index: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for node in nodes:
        kind = str(node.get("kind", node.get("node_type", "")) or "")
        aliases = _dedupe([str(node.get("name", "")), *[str(alias) for alias in node.get("aliases", []) if str(alias).strip()]]) if isinstance(node.get("aliases", []), list) else [str(node.get("name", ""))]
        for alias in aliases:
            normalized = normalize_identity_name(alias)
            if normalized:
                alias_index.setdefault((kind, normalized), []).append(node)
    candidates: list[dict[str, Any]] = []
    seen_node_sets: set[tuple[str, ...]] = set()
    for (kind, normalized), rows in alias_index.items():
        unique = _unique_nodes(rows)
        canonical_ids = {str(item.get("canonical_id", item.get("id", ""))) for item in unique if str(item.get("canonical_id", item.get("id", ""))).strip()}
        if len(unique) < 2 or len(canonical_ids) <= 1:
            continue
        node_signature = tuple(sorted(str(item.get("id", "")) for item in unique))
        if node_signature in seen_node_sets:
            continue
        seen_node_sets.add(node_signature)
        confidence = round(sum(_confidence(item) for item in unique) / max(1, len(unique)), 4)
        if confidence < min_confidence:
            continue
        candidates.append(
            {
                "candidate_id": _candidate_id(kind, normalized, unique),
                "kind": kind,
                "normalized_alias": normalized,
                "canonical_identity_id": _canonical_identity_id(graph, kind, normalized),
                "confidence": confidence,
                "requires_human_gate": confidence < 0.88 or len({str(item.get("source_path", "")) for item in unique}) > 1,
                "aliases": _dedupe([alias for item in unique for alias in ([str(item.get("name", ""))] + [str(value) for value in item.get("aliases", [])]) if str(alias).strip()]),
                "node_ids": [str(item.get("id", "")) for item in unique],
                "source_paths": _dedupe([str(item.get("source_path", "")) for item in unique if str(item.get("source_path", "")).strip()]),
                "evidence_spans": _merge_evidence_spans(unique),
                "merge_recommendation": "auto_merge_candidate" if confidence >= 0.9 else "human_review_required",
            }
        )
    candidates.sort(key=lambda item: (-float(item.get("confidence", 0)), str(item.get("kind", "")), str(item.get("normalized_alias", ""))))
    return {
        "candidates": candidates,
        "merge_queue": [candidate for candidate in candidates if candidate.get("requires_human_gate")],
        "auto_merge_candidates": [candidate for candidate in candidates if not candidate.get("requires_human_gate")],
        "summary": {
            "candidate_count": len(candidates),
            "human_gate_count": sum(1 for item in candidates if item.get("requires_human_gate")),
            "auto_merge_count": sum(1 for item in candidates if not item.get("requires_human_gate")),
        },
    }


def create_kg_identity_resolution(
    storage: LocalStorage,
    *,
    snapshot_path: str | Path | None = None,
    graph: dict[str, Any] | None = None,
    project_id: str | None = None,
    workspace_path: str | None = None,
    min_confidence: float = 0.7,
) -> dict[str, Any]:
    storage.ensure_layout()
    resolved_graph = graph or _load_snapshot_graph(storage, snapshot_path)
    queue = build_identity_merge_queue(resolved_graph, min_confidence=min_confidence)
    resolved_project_id = project_id or str(resolved_graph.get("project_id", ""))
    resolved_workspace_path = workspace_path or str(resolved_graph.get("workspace_path", ""))
    display_snapshot = _display_path(storage.root, resolve_path(storage.root, snapshot_path)) if snapshot_path else ""
    resolution_id = make_id("kg_identity_resolution", f"{resolved_project_id or 'global'}-{utc_now()}")
    asset = KgIdentityResolution(
        title="Novel KG identity resolution",
        source=str(resolved_graph.get("kg_id", "")),
        tags=["novel-kg", "identity-resolution", "merge-queue"],
        content={
            "resolution_id": resolution_id,
            "snapshot_path": display_snapshot,
            "project_id": resolved_project_id,
            "workspace_path": resolved_workspace_path,
            "candidates": queue["candidates"],
            "merge_queue": queue["merge_queue"],
            "auto_merge_candidates": queue["auto_merge_candidates"],
            "summary": queue["summary"],
            "status": "needs_review" if queue["merge_queue"] else "ready",
            "created_at": utc_now(),
        },
        metadata={"project_id": resolved_project_id, "workspace_path": resolved_workspace_path},
        references=filter_project_safe_references(storage, resolved_project_id, _dedupe([display_snapshot, *[path for candidate in queue["candidates"] for path in candidate.get("source_paths", [])]])),
    )
    data = asset.to_dict()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path)}


def normalize_identity_name(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[《》「」『』\"'`.,，。:：;；!?！？()\[\]{}<>]", "", text)
    return text


def _load_snapshot_graph(storage: LocalStorage, snapshot_path: str | Path | None) -> dict[str, Any]:
    if not snapshot_path:
        raise ValueError("snapshot_path or graph is required")
    data = storage.read_json(resolve_path(storage.root, snapshot_path))
    if not isinstance(data, dict) or data.get("type") != "novel_kg_snapshot":
        raise ValueError(f"snapshot_path must point to novel_kg_snapshot: {snapshot_path}")
    return data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}


def _all_identity_nodes(graph: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for collection in IDENTITY_NODE_COLLECTIONS:
        for item in graph.get(collection, []) if isinstance(graph.get(collection, []), list) else []:
            if isinstance(item, dict) and str(item.get("id", "")).strip():
                rows.append({**item, "_collection": collection})
    return rows


def _unique_nodes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in rows:
        node_id = str(item.get("id", ""))
        if node_id and node_id not in seen:
            seen.add(node_id)
            result.append(item)
    return result


def _confidence(item: dict[str, Any]) -> float:
    try:
        return max(0.0, min(1.0, float(item.get("confidence", 0.0) or 0.0)))
    except Exception:
        return 0.0


def _candidate_id(kind: str, normalized: str, nodes: list[dict[str, Any]]) -> str:
    raw = "|".join([kind, normalized, *sorted(str(item.get("id", "")) for item in nodes)])
    return f"kg_identity_candidate_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def _canonical_identity_id(graph: dict[str, Any], kind: str, normalized: str) -> str:
    project_id = str(graph.get("project_id", ""))
    raw = f"{project_id}:{kind}:{normalized}"
    return f"kg_identity_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def _merge_evidence_spans(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, int, int]] = set()
    spans: list[dict[str, Any]] = []
    for node in nodes:
        for span in node.get("evidence_spans", []) if isinstance(node.get("evidence_spans", []), list) else []:
            if not isinstance(span, dict):
                continue
            source_path = str(span.get("source_path", ""))
            field_path = str(span.get("field_path", ""))
            start = _int(span.get("start", 0))
            end = _int(span.get("end", 0))
            key = (source_path, field_path, start, end)
            if key in seen:
                continue
            seen.add(key)
            spans.append(
                {
                    "source_path": source_path,
                    "field_path": field_path,
                    "start": start,
                    "end": end,
                    "snippet": str(span.get("snippet", ""))[:240],
                    "confidence": _confidence(span) if span.get("confidence") is not None else _confidence(node),
                    "extractor": str(span.get("extractor", "identity_resolution")),
                }
            )
    return spans[:20]


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0
