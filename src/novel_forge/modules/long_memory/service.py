from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from novel_forge.core.constants import DATA_DIRS
from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.modules.production_context import filter_project_safe_references, project_scope_from_asset
from novel_forge.modules.runtime_ledger import record_trace_span
from novel_forge.schemas import MemoryRecord, MemoryRetrievalReport, MemorySelection, validate_common_fields
from novel_forge.storage.local import LocalStorage

MEMORY_LEVELS = {"L0", "L1", "L2", "L3", "L4", "L5"}
MEMORY_SELECTOR_BY_TASK = {
    "workflow": ["L0", "L1", "L5"],
    "outline": ["L1", "L2", "L4", "L5"],
    "chapter_plan": ["L1", "L2", "L3", "L4", "L5"],
    "draft": ["L1", "L2", "L3", "L4", "L5"],
    "review": ["L1", "L3", "L4", "L5"],
    "revision": ["L1", "L3", "L4", "L5"],
    "feedback": ["L1", "L3", "L5"],
    "kg": ["L1", "L2", "L4"],
}


def create_memory_record(
    storage: LocalStorage,
    *,
    project_id: str,
    level: str,
    memory_type: str,
    title: str,
    summary: str,
    content: dict[str, Any] | str,
    source_artifact_ids: list[str] | None = None,
    related_entity_ids: list[str] | None = None,
    related_chapters: list[int] | None = None,
    priority: int = 5,
    stability: str = "stable",
    status: str = "active",
    workspace_path: str = "",
    trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_level = _memory_level(level)
    memory_id = make_id("memory", f"{project_id}-{normalized_level}-{memory_type}-{title}")
    content_payload = {
        "memory_id": memory_id,
        "project_id": project_id,
        "level": normalized_level,
        "memory_type": memory_type,
        "title": title,
        "summary": summary,
        "content": content,
        "source_artifact_ids": source_artifact_ids or [],
        "related_entity_ids": related_entity_ids or [],
        "related_chapters": related_chapters or [],
        "priority": int(priority or 5),
        "stability": stability,
        "status": _status(status),
        "last_verified_at": utc_now(),
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    asset = MemoryRecord(
        title=title,
        source=",".join(source_artifact_ids or []),
        tags=["memory", normalized_level, memory_type, content_payload["status"]],
        content=content_payload,
        metadata={"project_id": project_id, "workspace_path": workspace_path, "level": normalized_level, "memory_type": memory_type},
        references=filter_project_safe_references(storage, project_id, source_artifact_ids or []),
    )
    written = _write(storage, asset)
    _record_memory_span(storage, trace, "memory_record", title, written["path"], project_id, workspace_path)
    return written


def create_memory_from_asset(
    storage: LocalStorage,
    source_path: str | Path,
    *,
    level: str = "",
    memory_type: str = "",
    project_id: str = "",
    workspace_path: str = "",
) -> dict[str, Any]:
    source_file = resolve_path(storage.root, source_path)
    asset = storage.read_asset(source_file)
    project = project_scope_from_asset(storage, asset, input_path=source_file, workspace_path=workspace_path or None)
    resolved_project_id = project_id or str(project.get("project_id", ""))
    resolved_workspace = workspace_path or str(project.get("workspace_path", ""))
    summary = _asset_summary(asset.to_dict())
    resolved_level = level or _level_for_asset_type(asset.type)
    resolved_type = memory_type or asset.type
    return create_memory_record(
        storage,
        project_id=resolved_project_id,
        level=resolved_level,
        memory_type=resolved_type,
        title=asset.title or asset.name or asset.id,
        summary=summary,
        content={"asset_type": asset.type, "asset_path": _display_path(storage.root, source_file), "summary": summary},
        source_artifact_ids=[asset.id, _display_path(storage.root, source_file)],
        workspace_path=resolved_workspace,
    )


def select_memory_for_node(
    storage: LocalStorage,
    *,
    target_node: str,
    task_type: str,
    project_id: str = "",
    query: str = "",
    max_items: int = 12,
    trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    levels = MEMORY_SELECTOR_BY_TASK.get(task_type, MEMORY_SELECTOR_BY_TASK.get(_task_family(task_type), ["L1", "L3", "L5"]))
    results = retrieve_memory(storage, query=query or task_type, project_id=project_id, levels=levels, limit=max_items, persist_report=False)
    selected = results.get("results", []) if isinstance(results.get("results", []), list) else []
    content = {
        "selection_id": make_id("memory_selection", f"{target_node}-{task_type}-{utc_now()}"),
        "target_node": target_node,
        "task_type": task_type,
        "selected_memory_ids": [str(item.get("memory_id", "")) for item in selected],
        "levels": levels,
        "query": query,
        "results": selected,
        "created_at": utc_now(),
    }
    asset = MemorySelection(
        title=f"Memory selection {target_node}",
        tags=["memory-selection", task_type],
        content=content,
        metadata={"project_id": project_id, "target_node": target_node, "task_type": task_type},
        references=filter_project_safe_references(storage, project_id, [str(item.get("path", "")) for item in selected]),
    )
    written = _write(storage, asset)
    _record_memory_span(storage, trace, "memory_selection", target_node, written["path"], project_id, "")
    return {**written, "results": selected}


def retrieve_memory(
    storage: LocalStorage,
    *,
    query: str,
    project_id: str = "",
    levels: list[str] | None = None,
    memory_types: list[str] | None = None,
    limit: int = 20,
    persist_report: bool = True,
) -> dict[str, Any]:
    selected_levels = {_memory_level(level) for level in (levels or []) if str(level).strip()}
    query_tokens = _tokens(query)
    rows = []
    for record in list_memory_records(storage, project_id=project_id or None, limit=5000):
        content = record.get("content", {}) if isinstance(record.get("content", {}), dict) else {}
        if selected_levels and str(content.get("level", "")) not in selected_levels:
            continue
        if memory_types and str(content.get("memory_type", "")) not in set(memory_types):
            continue
        text = f"{content.get('title', '')} {content.get('summary', '')} {json.dumps(content.get('content', ''), ensure_ascii=False)}"
        score = _score(query_tokens, _tokens(text), int(content.get("priority", 5) or 5))
        if score <= 0 and query_tokens:
            continue
        rows.append(
            {
                "path": record.get("path", ""),
                "memory_id": content.get("memory_id", record.get("id", "")),
                "level": content.get("level", ""),
                "memory_type": content.get("memory_type", ""),
                "title": content.get("title", ""),
                "summary": content.get("summary", ""),
                "score": round(score, 4),
                "source_artifact_ids": content.get("source_artifact_ids", []),
            }
        )
    results = sorted(rows, key=lambda row: (-float(row["score"]), str(row["level"]), str(row["title"])))[: int(limit or 20)]
    report = {
        "report_id": make_id("memory_retrieval", f"{project_id}-{query}-{utc_now()}"),
        "query": query,
        "backend": "local_json_memory",
        "levels": sorted(selected_levels) if selected_levels else [],
        "results": results,
        "created_at": utc_now(),
    }
    if not persist_report:
        return report
    asset = MemoryRetrievalReport(
        title=f"Memory retrieval {query[:48]}",
        tags=["memory-retrieval", "local-json"],
        content=report,
        metadata={"project_id": project_id, "backend": "local_json_memory"},
        references=filter_project_safe_references(storage, project_id, [str(item.get("path", "")) for item in results]),
    )
    written = _write(storage, asset)
    return {**report, "path": written["path"], "asset": written["asset"], "validation": written["validation"]}


def list_memory_records(storage: LocalStorage, *, project_id: str | None = None, level: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
    rows = []
    for path in storage.list_json("contexts"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "memory_record":
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if project_id and str(metadata.get("project_id", content.get("project_id", ""))) != project_id:
            continue
        if level and str(content.get("level", "")) != _memory_level(level):
            continue
        rows.append({**data, "path": _display_path(storage.root, path)})
    return sorted(rows, key=lambda row: str(row.get("updated_at", "")), reverse=True)[:limit]


def _level_for_asset_type(asset_type: str) -> str:
    if asset_type in {"quality_standard_profile", "review_rule_pack", "style_profile"}:
        return "L5"
    if asset_type in {"character_card", "world_bible", "continuity_bible", "novel_kg_snapshot"}:
        return "L4"
    if asset_type in {"draft_chapter", "draft_version", "chapter_plan", "chapter_plan_version", "review_report"}:
        return "L3"
    if asset_type in {"outline", "outline_version", "long_form_macro_plan"}:
        return "L2"
    return "L1"


def _task_family(task_type: str) -> str:
    text = str(task_type or "").lower()
    for key in MEMORY_SELECTOR_BY_TASK:
        if key in text:
            return key
    return "workflow"


def _asset_summary(asset: dict[str, Any]) -> str:
    content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
    for key in ["summary", "text", "objective", "hook", "logline", "setting"]:
        value = content.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())[:600]
    return json.dumps(content, ensure_ascii=False, sort_keys=True)[:600]


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in "".join(ch if ch.isalnum() else " " for ch in str(text)).split() if len(token) >= 2}


def _score(query_tokens: set[str], text_tokens: set[str], priority: int) -> float:
    if not query_tokens:
        return priority / 10.0
    overlap = len(query_tokens & text_tokens)
    return (overlap / max(len(query_tokens), 1)) + (priority / 100.0)


def _memory_level(value: str) -> str:
    normalized = str(value or "L1").strip().upper()
    return normalized if normalized in MEMORY_LEVELS else "L1"


def _status(value: str) -> str:
    normalized = str(value or "active").strip().lower().replace(" ", "_")
    return normalized if normalized in {"active", "stale", "superseded", "archived"} else "active"


def _record_memory_span(storage: LocalStorage, trace: dict[str, Any] | None, span_type: str, name: str, path: str, project_id: str, workspace_path: str) -> None:
    payload = dict(trace or {})
    if not payload.get("trace_id"):
        return
    record_trace_span(
        storage,
        trace_id=str(payload["trace_id"]),
        span_type=span_type,
        name=name,
        status="succeeded",
        parent_span_id=str(payload.get("span_id") or payload.get("parent_span_id") or payload["trace_id"]),
        attributes={"path": path},
        references=[path],
        project_id=project_id,
        workspace_path=workspace_path,
    )


def _write(storage: LocalStorage, asset: MemoryRecord | MemorySelection | MemoryRetrievalReport) -> dict[str, Any]:
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
