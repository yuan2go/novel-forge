from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.modules.production_context import filter_project_safe_references
from novel_forge.schemas import BaseAsset, validate_common_fields
from novel_forge.storage.local import LocalStorage


def record_audit_event(
    storage: LocalStorage,
    *,
    event_type: str,
    action: str,
    actor_type: str = "system",
    actor_id: str = "",
    target: dict[str, Any] | None = None,
    project_id: str = "",
    trace_id: str = "",
    input_refs: list[str] | None = None,
    output_refs: list[str] | None = None,
    evidence_refs: list[str] | None = None,
    status: str = "succeeded",
    blocking: bool = False,
    rollback_ref: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = utc_now()
    target_payload = target or {}
    refs = _dedupe([*(input_refs or []), *(output_refs or []), *(evidence_refs or []), rollback_ref])
    content = {
        "event_id": make_id("audit_log", f"{event_type}-{action}-{now}"),
        "event_type": event_type,
        "actor_type": actor_type,
        "actor_id": actor_id,
        "action": action,
        "target": target_payload,
        "project_id": project_id,
        "trace_id": trace_id,
        "input_refs": input_refs or [],
        "output_refs": output_refs or [],
        "evidence_refs": evidence_refs or [],
        "status": status,
        "blocking": bool(blocking),
        "rollback_ref": rollback_ref,
        "created_at": now,
        "metadata": metadata or {},
    }
    asset = BaseAsset(
        type="audit_log",
        title=f"{event_type}: {action}",
        tags=["audit-log", event_type, action, status],
        content=content,
        metadata={"project_id": project_id, "trace_id": trace_id, "event_type": event_type, "status": status, "blocking": bool(blocking)},
        references=filter_project_safe_references(storage, project_id, refs),
    )
    return _write(storage, asset)


def list_audit_events(storage: LocalStorage, *, project_id: str | None = None, trace_id: str | None = None, event_type: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    rows = []
    for path in reversed(storage.list_json("runs")):
        data = _read_json_safe(storage, path)
        if data.get("type") != "audit_log":
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if project_id and str(metadata.get("project_id", "") or content.get("project_id", "")) != project_id:
            continue
        if trace_id and str(metadata.get("trace_id", "") or content.get("trace_id", "")) != trace_id:
            continue
        if event_type and str(metadata.get("event_type", "") or content.get("event_type", "")) != event_type:
            continue
        data["path"] = _display_path(storage.root, path)
        rows.append(data)
        if len(rows) >= max(1, int(limit or 200)):
            break
    return rows


def build_audit_trail(storage: LocalStorage, *, project_id: str = "", trace_id: str = "", limit: int = 500) -> dict[str, Any]:
    events = list_audit_events(storage, project_id=project_id or None, trace_id=trace_id or None, limit=limit)
    evidence = _dedupe([ref for event in events for ref in _event_refs(event)])
    return {
        "project_id": project_id,
        "trace_id": trace_id,
        "event_count": len(events),
        "events": events,
        "evidence_refs": evidence,
        "status": "empty" if not events else ("blocked" if any(event.get("content", {}).get("blocking") for event in events) else "recorded"),
    }


def create_audit_trail_report(storage: LocalStorage, *, project_id: str = "", trace_id: str = "", limit: int = 500) -> dict[str, Any]:
    trail = build_audit_trail(storage, project_id=project_id, trace_id=trace_id, limit=limit)
    content = {
        "report_id": make_id("audit_trail", f"{project_id}-{trace_id}-{utc_now()}"),
        "project_id": project_id,
        "trace_id": trace_id,
        "events": trail["events"],
        "evidence_refs": trail["evidence_refs"],
        "status": trail["status"],
        "created_at": utc_now(),
    }
    asset = BaseAsset(
        type="audit_trail_report",
        title=f"Audit trail {trace_id or project_id or 'global'}",
        tags=["audit-log", "trail-report", trail["status"]],
        content=content,
        metadata={"project_id": project_id, "trace_id": trace_id, "event_count": trail["event_count"], "status": trail["status"]},
        references=filter_project_safe_references(storage, project_id, trail["evidence_refs"]),
    )
    return _write(storage, asset)


def create_audit_export_package(storage: LocalStorage, *, project_id: str = "", trace_id: str = "", limit: int = 500) -> dict[str, Any]:
    trail = build_audit_trail(storage, project_id=project_id, trace_id=trace_id, limit=limit)
    sanitized_events = [_sanitize_event(event) for event in trail["events"]]
    content = {
        "export_id": make_id("audit_export", f"{project_id}-{trace_id}-{utc_now()}"),
        "project_id": project_id,
        "trace_id": trace_id,
        "events": sanitized_events,
        "source_isolation": {
            "raw_source_text_included": False,
            "source_chunk_raw_text_allowed": False,
            "policy": "metadata_and_refs_only",
        },
        "created_at": utc_now(),
    }
    asset = BaseAsset(
        type="audit_export_package",
        title=f"Audit export {trace_id or project_id or 'global'}",
        tags=["audit-log", "export", "source-isolated"],
        content=content,
        metadata={"project_id": project_id, "trace_id": trace_id, "event_count": len(sanitized_events), "raw_source_text_included": False},
        references=filter_project_safe_references(storage, project_id, trail["evidence_refs"]),
    )
    return _write(storage, asset)


def audit_chain_summary(storage: LocalStorage, *, project_id: str = "", trace_id: str = "") -> dict[str, Any]:
    events = list_audit_events(storage, project_id=project_id or None, trace_id=trace_id or None, limit=1000)
    by_type: dict[str, int] = {}
    for event in events:
        event_type = str(event.get("content", {}).get("event_type") or "unknown")
        by_type[event_type] = by_type.get(event_type, 0) + 1
    return {
        "project_id": project_id,
        "trace_id": trace_id,
        "event_count": len(events),
        "by_type": by_type,
        "blocking_count": sum(1 for event in events if event.get("content", {}).get("blocking")),
        "latest_event_at": max([str(event.get("content", {}).get("created_at", "")) for event in events] or [""]),
    }


def _sanitize_event(event: dict[str, Any]) -> dict[str, Any]:
    data = json.loads(json.dumps(event, ensure_ascii=False))

    def visit(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: ("[removed]" if key == "raw_text" else visit(child)) for key, child in value.items()}
        if isinstance(value, list):
            return [visit(child) for child in value]
        if isinstance(value, str) and "source_chunk.raw_text" in value:
            return value.replace("source_chunk.raw_text", "source_chunk.[raw_text_removed]")
        return value

    return visit(data)


def _event_refs(event: dict[str, Any]) -> list[str]:
    content = event.get("content", {}) if isinstance(event.get("content", {}), dict) else {}
    return _dedupe([*content.get("input_refs", []), *content.get("output_refs", []), *content.get("evidence_refs", []), str(content.get("rollback_ref", ""))])


def _write(storage: LocalStorage, asset: BaseAsset) -> dict[str, Any]:
    data = asset.to_dict()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "asset": data, "validation": {"ok": True, "errors": []}}


def _read_json_safe(storage: LocalStorage, path: Path) -> dict[str, Any]:
    try:
        data = storage.read_json(resolve_path(storage.root, path))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _display_path(root: Path, path: str | Path) -> str:
    candidate = Path(path)
    try:
        return str(candidate.relative_to(root))
    except ValueError:
        return str(candidate)


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
