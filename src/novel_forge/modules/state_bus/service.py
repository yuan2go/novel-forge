from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.production_context import filter_project_safe_references
from novel_forge.modules.runtime_ledger import record_trace_span
from novel_forge.schemas import StateConflictReport, StateEvent, StateReplay, StateSnapshot, validate_common_fields
from novel_forge.storage.local import LocalStorage

STATE_ASSET_TYPES = {"state_event", "state_snapshot", "state_replay", "state_conflict_report"}


def record_state_event(
    storage: LocalStorage,
    *,
    stream: str,
    subject_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
    expected_version: int | None = None,
    project_id: str = "",
    workspace_path: str = "",
    trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current_version = _current_version(storage, stream=stream, subject_id=subject_id, project_id=project_id)
    conflict = expected_version is not None and int(expected_version) != current_version
    content = {
        "event_id": make_id("state_event", f"{stream}-{subject_id}-{event_type}-{utc_now()}"),
        "stream": stream,
        "subject_id": subject_id,
        "event_type": event_type,
        "payload": payload or {},
        "version": current_version + 1,
        "expected_version": expected_version,
        "conflict": conflict,
        "created_at": utc_now(),
        "trace": trace or {},
    }
    asset = StateEvent(
        title=f"State event {stream}/{subject_id}: {event_type}",
        tags=["state-event", stream, event_type, "conflict" if conflict else "accepted"],
        content=content,
        metadata={"project_id": project_id, "workspace_path": workspace_path, "stream": stream, "subject_id": subject_id},
        references=filter_project_safe_references(storage, project_id, _payload_paths(payload or {})),
    )
    written = _write(storage, asset)
    _record_state_span(storage, trace, "state_event", event_type, written["path"], project_id, workspace_path)
    return {**written, "conflict": conflict, "version": content["version"]}


def list_state_events(
    storage: LocalStorage,
    *,
    stream: str | None = None,
    subject_id: str | None = None,
    project_id: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    rows = []
    for path in storage.list_json("runs"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "state_event":
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if project_id and str(metadata.get("project_id", "")) != project_id:
            continue
        if stream and str(content.get("stream", "")) != stream:
            continue
        if subject_id and str(content.get("subject_id", "")) != subject_id:
            continue
        rows.append({**data, "path": _display_path(storage.root, path)})
    return sorted(rows, key=lambda row: (str(row.get("content", {}).get("version", 0)), str(row.get("updated_at", ""))))[:limit]


def create_state_snapshot(
    storage: LocalStorage,
    *,
    stream: str,
    subject_id: str,
    project_id: str = "",
    workspace_path: str = "",
    trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    events = list_state_events(storage, stream=stream, subject_id=subject_id, project_id=project_id or None, limit=5000)
    state = _fold_events(events)
    content = {
        "snapshot_id": make_id("state_snapshot", f"{stream}-{subject_id}-{len(events)}-{utc_now()}"),
        "stream": stream,
        "subject_id": subject_id,
        "state": state,
        "event_count": len(events),
        "last_event_id": str(events[-1].get("content", {}).get("event_id", "")) if events else "",
        "created_at": utc_now(),
        "trace": trace or {},
    }
    asset = StateSnapshot(
        title=f"State snapshot {stream}/{subject_id}",
        tags=["state-snapshot", stream],
        content=content,
        metadata={"project_id": project_id, "workspace_path": workspace_path, "stream": stream, "subject_id": subject_id},
    )
    written = _write(storage, asset)
    _record_state_span(storage, trace, "state_snapshot", f"{stream}/{subject_id}", written["path"], project_id, workspace_path)
    return written


def replay_state_events(
    storage: LocalStorage,
    *,
    stream: str,
    subject_id: str,
    from_version: int = 0,
    project_id: str = "",
    workspace_path: str = "",
) -> dict[str, Any]:
    events = [
        row
        for row in list_state_events(storage, stream=stream, subject_id=subject_id, project_id=project_id or None, limit=5000)
        if int(row.get("content", {}).get("version", 0) or 0) >= int(from_version or 0)
    ]
    content = {
        "replay_id": make_id("state_replay", f"{stream}-{subject_id}-{from_version}-{utc_now()}"),
        "stream": stream,
        "subject_id": subject_id,
        "from_version": int(from_version or 0),
        "events": [_event_summary(row) for row in events],
        "replayed_state": _fold_events(events),
        "created_at": utc_now(),
    }
    asset = StateReplay(
        title=f"State replay {stream}/{subject_id}",
        tags=["state-replay", stream],
        content=content,
        metadata={"project_id": project_id, "workspace_path": workspace_path, "stream": stream, "subject_id": subject_id},
    )
    return _write(storage, asset)


def detect_state_conflicts(
    storage: LocalStorage,
    *,
    stream: str | None = None,
    subject_id: str | None = None,
    project_id: str = "",
    workspace_path: str = "",
) -> dict[str, Any]:
    events = list_state_events(storage, stream=stream, subject_id=subject_id, project_id=project_id or None, limit=5000)
    conflicts = []
    seen_versions: dict[tuple[str, str, int], dict[str, Any]] = {}
    for row in events:
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        key = (str(content.get("stream", "")), str(content.get("subject_id", "")), int(content.get("version", 0) or 0))
        if bool(content.get("conflict", False)):
            conflicts.append({"reason": "expected_version_mismatch", "event": _event_summary(row)})
        if key in seen_versions:
            conflicts.append({"reason": "duplicate_version", "left": _event_summary(seen_versions[key]), "right": _event_summary(row)})
        seen_versions[key] = row
    content = {
        "report_id": make_id("state_conflict_report", f"{stream or 'all'}-{subject_id or 'all'}-{utc_now()}"),
        "stream": stream or "",
        "subject_id": subject_id or "",
        "conflicts": conflicts,
        "status": "conflicts_found" if conflicts else "clean",
        "created_at": utc_now(),
    }
    asset = StateConflictReport(
        title=f"State conflicts {content['status']}",
        tags=["state-conflict-report", content["status"]],
        content=content,
        metadata={"project_id": project_id, "workspace_path": workspace_path},
    )
    return _write(storage, asset)


def _current_version(storage: LocalStorage, *, stream: str, subject_id: str, project_id: str) -> int:
    versions = [int(row.get("content", {}).get("version", 0) or 0) for row in list_state_events(storage, stream=stream, subject_id=subject_id, project_id=project_id or None, limit=5000)]
    return max(versions) if versions else 0


def _fold_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    state: dict[str, Any] = {}
    for row in events:
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        payload = content.get("payload", {}) if isinstance(content.get("payload", {}), dict) else {}
        action = str(content.get("event_type", ""))
        if action.endswith(".deleted") or action == "deleted":
            state["deleted"] = True
        elif action.endswith(".patched") or action.endswith(".updated") or action in {"patch", "updated"}:
            state.update(payload)
        else:
            state.setdefault("events", []).append(_event_summary(row))
            if payload:
                state.update(payload)
        state["version"] = int(content.get("version", state.get("version", 0)) or 0)
        state["updated_at"] = str(content.get("created_at", ""))
    return state


def _event_summary(row: dict[str, Any]) -> dict[str, Any]:
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    return {
        "path": row.get("path", ""),
        "event_id": content.get("event_id", ""),
        "stream": content.get("stream", ""),
        "subject_id": content.get("subject_id", ""),
        "event_type": content.get("event_type", ""),
        "version": content.get("version", 0),
        "created_at": content.get("created_at", ""),
    }


def _record_state_span(storage: LocalStorage, trace: dict[str, Any] | None, span_type: str, name: str, path: str, project_id: str, workspace_path: str) -> None:
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


def _payload_paths(payload: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for key, value in payload.items():
        if isinstance(value, str) and (key.endswith("_path") or key == "path"):
            paths.append(value)
        elif isinstance(value, dict):
            paths.extend(_payload_paths(value))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    paths.extend(_payload_paths(item))
    return paths


def _write(storage: LocalStorage, asset: StateEvent | StateSnapshot | StateReplay | StateConflictReport) -> dict[str, Any]:
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
