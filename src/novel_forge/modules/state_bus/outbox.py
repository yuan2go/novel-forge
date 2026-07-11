from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.production_context import filter_project_safe_references
from novel_forge.schemas import OutboxEvent, validate_common_fields
from novel_forge.storage.local import LocalStorage

OUTBOX_STATUSES = {"queued", "claimed", "acked", "failed"}


def enqueue_outbox_event(
    storage: LocalStorage,
    *,
    event_ref: str,
    event_id: str,
    event_type: str,
    project_id: str = "",
    workspace_path: str = "",
    idempotency_key: str = "",
    correlation_id: str = "",
) -> dict[str, Any]:
    key = str(idempotency_key or event_id or event_ref)
    existing = _find_by_key(storage, key, project_id=project_id)
    if existing:
        return existing
    outbox_id = make_id("outbox_event", key)
    content = {
        "outbox_id": outbox_id,
        "event_ref": event_ref,
        "event_id": event_id,
        "event_type": event_type,
        "idempotency_key": key,
        "status": "queued",
        "attempt_count": 0,
        "available_at": utc_now(),
        "claimed_by": "",
        "claimed_at": "",
        "acked_at": "",
        "failed_at": "",
        "last_error": "",
        "correlation_id": correlation_id,
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    asset = OutboxEvent(
        id=outbox_id,
        title=f"Outbox event {event_type}",
        source=event_ref,
        tags=["outbox-event", "queued", event_type],
        content=content,
        metadata={"project_id": project_id, "workspace_path": workspace_path, "authority": "transactional_outbox"},
        references=filter_project_safe_references(storage, project_id, [event_ref]),
    )
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset)
    return {"status": "queued", "path": _display_path(storage.root, path), "id": outbox_id, "asset": asset.to_dict(), "validation": {"ok": True, "errors": []}}


def list_outbox_events(storage: LocalStorage, *, project_id: str | None = None, status: str | None = None, limit: int = 1000) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in reversed(storage.list_json("runs")):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "outbox_event":
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if project_id and str(metadata.get("project_id") or "") != str(project_id):
            continue
        if status and str(content.get("status") or "") != str(status):
            continue
        rows.append({**data, "path": _display_path(storage.root, path)})
        if len(rows) >= max(1, int(limit or 1000)):
            break
    return rows


def claim_outbox_events(storage: LocalStorage, *, project_id: str = "", consumer: str = "state-projector", limit: int = 100) -> dict[str, Any]:
    claimed: list[dict[str, Any]] = []
    for row in list_outbox_events(storage, project_id=project_id or None, limit=max(1, int(limit or 100))):
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        if str(content.get("status") or "") not in {"queued", "failed"}:
            continue
        content.update({"status": "claimed", "attempt_count": int(content.get("attempt_count", 0) or 0) + 1, "claimed_by": consumer, "claimed_at": utc_now(), "updated_at": utc_now()})
        row["content"] = content
        row["updated_at"] = utc_now()
        storage.write_json(storage.root / str(row["path"]), row)
        claimed.append(row)
        if len(claimed) >= max(1, int(limit or 100)):
            break
    return {"status": "claimed", "claimed_count": len(claimed), "events": claimed, "consumer": consumer}


def ack_outbox_event(storage: LocalStorage, outbox_ref: str | Path, *, consumer: str = "state-projector") -> dict[str, Any]:
    row = _resolve(storage, outbox_ref)
    content = row["data"].get("content", {}) if isinstance(row["data"].get("content", {}), dict) else {}
    if str(content.get("status") or "") == "acked":
        return {"status": "acked", "path": row["path"], "asset": row["data"], "idempotent": True}
    if str(content.get("status") or "") not in {"claimed", "failed", "queued"}:
        raise ValueError(f"outbox event cannot be acked from status: {content.get('status', '')}")
    now = utc_now()
    content.update({"status": "acked", "acked_at": now, "claimed_by": consumer, "updated_at": now})
    row["data"]["content"] = content
    row["data"]["tags"] = [*{str(tag) for tag in row["data"].get("tags", [])}, "acked"]
    row["data"]["updated_at"] = now
    storage.write_json(storage.root / row["path"], row["data"])
    return {"status": "acked", "path": row["path"], "asset": row["data"], "idempotent": False}


def fail_outbox_event(storage: LocalStorage, outbox_ref: str | Path, *, error: str, consumer: str = "state-projector") -> dict[str, Any]:
    row = _resolve(storage, outbox_ref)
    content = row["data"].get("content", {}) if isinstance(row["data"].get("content", {}), dict) else {}
    now = utc_now()
    content.update({"status": "failed", "failed_at": now, "claimed_by": consumer, "last_error": str(error), "updated_at": now})
    row["data"]["content"] = content
    row["data"]["updated_at"] = now
    storage.write_json(storage.root / row["path"], row["data"])
    return {"status": "failed", "path": row["path"], "asset": row["data"]}


def _find_by_key(storage: LocalStorage, key: str, *, project_id: str) -> dict[str, Any] | None:
    for row in list_outbox_events(storage, project_id=project_id or None, limit=5000):
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        if str(content.get("idempotency_key") or "") == key:
            return {"status": str(content.get("status") or "queued"), "path": row["path"], "id": row.get("id", ""), "asset": row}
    return None


def _resolve(storage: LocalStorage, value: str | Path) -> dict[str, Any]:
    candidate = storage.root / value if not Path(value).is_absolute() else Path(value)
    if candidate.exists():
        data = storage.read_json(candidate)
        if isinstance(data, dict) and data.get("type") == "outbox_event":
            return {"path": candidate.relative_to(storage.root).as_posix(), "data": data}
    for row in list_outbox_events(storage, limit=5000):
        if str(row.get("id") or "") == str(value) or str(row.get("content", {}).get("outbox_id") or "") == str(value):
            return {"path": str(row["path"]), "data": row}
    raise FileNotFoundError(f"outbox_event not found: {value}")


def _display_path(root: Path, path: str | Path) -> str:
    candidate = Path(path)
    try:
        return str(candidate.relative_to(root))
    except ValueError:
        return str(candidate)
