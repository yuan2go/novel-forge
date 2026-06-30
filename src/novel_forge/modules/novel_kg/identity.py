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


def adjudicate_kg_identity_candidate(
    storage: LocalStorage,
    *,
    resolution_path_or_id: str | Path,
    candidate_id: str,
    decision: str,
    actor: str = "operator",
    note: str = "",
    apply_merge: bool = False,
) -> dict[str, Any]:
    """Record and optionally apply a human identity-merge decision.

    The KG snapshot remains immutable. Approved decisions are materialized as an
    identity overlay inside the resolution asset so workflow gates and context
    builders can treat the merge as reviewed evidence without rewriting the
    source graph.
    """

    storage.ensure_layout()
    path = _resolve_identity_resolution(storage, resolution_path_or_id)
    data = storage.read_json(path)
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    normalized_decision = str(decision or "").strip().lower()
    if normalized_decision not in {"approve", "reject", "defer"}:
        raise ValueError("decision must be approve, reject, or defer")
    candidate = _find_candidate(content, candidate_id)
    if not candidate:
        raise ValueError(f"identity candidate not found: {candidate_id}")
    now = utc_now()
    should_apply = apply_merge or normalized_decision == "approve"
    status = "approved" if normalized_decision == "approve" else "rejected" if normalized_decision == "reject" else "deferred"
    adjudication = {
        "candidate_id": candidate_id,
        "decision": normalized_decision,
        "status": status,
        "actor": actor,
        "note": note,
        "apply_merge": should_apply,
        "canonical_identity_id": candidate.get("canonical_identity_id", ""),
        "node_ids": candidate.get("node_ids", []),
        "aliases": candidate.get("aliases", []),
        "confidence": candidate.get("confidence", 0),
        "evidence_spans": candidate.get("evidence_spans", []),
        "created_at": now,
    }
    adjudications = content.get("adjudications", []) if isinstance(content.get("adjudications", []), list) else []
    adjudications = [item for item in adjudications if not (isinstance(item, dict) and item.get("candidate_id") == candidate_id)]
    adjudications.append(adjudication)
    content["adjudications"] = adjudications
    _mark_candidate_status(content, candidate_id, status)
    if should_apply:
        overlay = content.get("identity_overlay", {}) if isinstance(content.get("identity_overlay", {}), dict) else {}
        applied = overlay.get("applied_merges", []) if isinstance(overlay.get("applied_merges", []), list) else []
        applied = [item for item in applied if not (isinstance(item, dict) and item.get("candidate_id") == candidate_id)]
        applied.append(
            {
                "candidate_id": candidate_id,
                "canonical_identity_id": candidate.get("canonical_identity_id", ""),
                "kind": candidate.get("kind", ""),
                "normalized_alias": candidate.get("normalized_alias", ""),
                "node_ids": candidate.get("node_ids", []),
                "aliases": candidate.get("aliases", []),
                "source_paths": candidate.get("source_paths", []),
                "confidence": candidate.get("confidence", 0),
                "evidence_spans": candidate.get("evidence_spans", []),
                "applied_by": actor,
                "applied_at": now,
                "note": note,
            }
        )
        overlay["applied_merges"] = applied
        overlay["node_to_canonical_identity"] = _node_to_canonical_overlay(applied)
        overlay["updated_at"] = now
        content["identity_overlay"] = overlay
    content["merge_queue"] = _open_merge_queue(content)
    content["summary"] = _resolution_summary(content)
    content["status"] = "needs_review" if content["merge_queue"] else "ready"
    content["updated_at"] = now
    data["content"] = content
    data["updated_at"] = now
    data["tags"] = _dedupe([*[str(tag) for tag in data.get("tags", [])], "identity-adjudicated", content["status"]])
    storage.write_json(path, data)
    return {
        "path": _display_path(storage.root, path),
        "candidate_id": candidate_id,
        "decision": normalized_decision,
        "status": content["status"],
        "adjudication": adjudication,
        "identity_overlay": content.get("identity_overlay", {}),
        "asset": data,
    }


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


def _resolve_identity_resolution(storage: LocalStorage, path_or_id: str | Path) -> Path:
    candidate = resolve_path(storage.root, path_or_id)
    if candidate.exists():
        data = storage.read_json(candidate)
        if isinstance(data, dict) and data.get("type") == "kg_identity_resolution":
            return candidate
    needle = str(path_or_id)
    for path in storage.list_json("continuity"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if data.get("type") == "kg_identity_resolution" and (str(data.get("id", "")) == needle or str(content.get("resolution_id", "")) == needle):
            return path
    raise FileNotFoundError(f"kg_identity_resolution not found: {path_or_id}")


def _find_candidate(content: dict[str, Any], candidate_id: str) -> dict[str, Any] | None:
    for key in ["candidates", "merge_queue", "auto_merge_candidates"]:
        for item in content.get(key, []) if isinstance(content.get(key, []), list) else []:
            if isinstance(item, dict) and str(item.get("candidate_id", "")) == str(candidate_id):
                return item
    return None


def _mark_candidate_status(content: dict[str, Any], candidate_id: str, status: str) -> None:
    for key in ["candidates", "merge_queue", "auto_merge_candidates"]:
        rows = content.get(key, []) if isinstance(content.get(key, []), list) else []
        for item in rows:
            if isinstance(item, dict) and str(item.get("candidate_id", "")) == str(candidate_id):
                item["review_status"] = status
                item["requires_human_gate"] = status == "deferred"


def _open_merge_queue(content: dict[str, Any]) -> list[dict[str, Any]]:
    rows = content.get("candidates", []) if isinstance(content.get("candidates", []), list) else []
    return [
        item
        for item in rows
        if isinstance(item, dict)
        and item.get("requires_human_gate")
        and str(item.get("review_status", "pending")) in {"", "pending", "deferred"}
    ]


def _resolution_summary(content: dict[str, Any]) -> dict[str, Any]:
    candidates = content.get("candidates", []) if isinstance(content.get("candidates", []), list) else []
    adjudications = content.get("adjudications", []) if isinstance(content.get("adjudications", []), list) else []
    overlay = content.get("identity_overlay", {}) if isinstance(content.get("identity_overlay", {}), dict) else {}
    applied = overlay.get("applied_merges", []) if isinstance(overlay.get("applied_merges", []), list) else []
    return {
        "candidate_count": len(candidates),
        "human_gate_count": len(_open_merge_queue(content)),
        "auto_merge_count": len(content.get("auto_merge_candidates", [])) if isinstance(content.get("auto_merge_candidates", []), list) else 0,
        "adjudicated_count": len(adjudications),
        "approved_count": sum(1 for item in adjudications if isinstance(item, dict) and item.get("decision") == "approve"),
        "rejected_count": sum(1 for item in adjudications if isinstance(item, dict) and item.get("decision") == "reject"),
        "deferred_count": sum(1 for item in adjudications if isinstance(item, dict) and item.get("decision") == "defer"),
        "applied_merge_count": len(applied),
    }


def _node_to_canonical_overlay(applied_merges: list[dict[str, Any]]) -> dict[str, str]:
    overlay: dict[str, str] = {}
    for merge in applied_merges:
        canonical = str(merge.get("canonical_identity_id", ""))
        for node_id in merge.get("node_ids", []) if isinstance(merge.get("node_ids", []), list) else []:
            if str(node_id).strip() and canonical:
                overlay[str(node_id)] = canonical
    return overlay


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
