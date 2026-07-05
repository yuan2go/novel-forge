from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from novel_forge.core.exception_policy import require_recoverable_asset_scan_error
from novel_forge.core.ids import utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.schemas import validate_common_fields
from novel_forge.storage.local import LocalStorage

QUEUE_STATUSES = {"queued", "claimed", "running", "waiting_human", "acked", "retry_scheduled", "dead_letter", "cancelled"}
CLAIMABLE_STATUSES = {"queued", "retry_scheduled", "claimed"}
TERMINAL_QUEUE_STATUSES = {"acked", "dead_letter", "cancelled"}


def dispatch_id_from_key(idempotency_key: str) -> str:
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:16]
    return f"agent-dispatch-{digest}"


def queue_path(storage: LocalStorage, dispatch_id: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in dispatch_id or "agent_dispatch")
    return storage.data_dir("runs") / f"{safe}.json"


def resolve_queue(storage: LocalStorage, value: str | Path) -> Path:
    path = resolve_path(storage.root, value)
    if path.exists():
        return path
    for candidate in storage.list_json("runs"):
        data = _read_json_safe(storage, candidate)
        if not isinstance(data, dict) or data.get("type") != "agent_dispatch_queue":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if str(content.get("dispatch_id", "")) == str(value) or str(data.get("id", "")) == str(value):
            return candidate
    raise FileNotFoundError(f"agent_dispatch_queue not found: {value}")


def queue_lease_expired(content_or_row: dict[str, Any]) -> bool:
    expires_at = str(content_or_row.get("lease_expires_at", "") or "")
    if not expires_at:
        return True
    return parse_utc_datetime(expires_at) <= utc_now_dt()


def claim_queue_item(storage: LocalStorage, queue_ref: str | Path, *, owner: str, ttl_seconds: int) -> dict[str, Any]:
    path = resolve_queue(storage, queue_ref)
    data = _read_json_safe(storage, path)
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    status = str(content.get("status", ""))
    if status in TERMINAL_QUEUE_STATUSES or status == "waiting_human":
        return {"claimed": False, "reason": f"queue status is {status}", "queue": queue_row(storage, path, data)}
    if status == "claimed" and not queue_lease_expired(content) and str(content.get("lease_owner", "")) != owner:
        return {"claimed": False, "reason": "claimed_by_another_worker", "queue": queue_row(storage, path, data)}
    content.update(
        {
            "status": "claimed",
            "attempt_count": int(content.get("attempt_count", 0) or 0) + 1,
            "lease_owner": owner,
            "lease_expires_at": utc_datetime_after(ttl_seconds),
            "claimed_at": utc_now(),
        }
    )
    data["content"] = content
    data["updated_at"] = utc_now()
    data["tags"] = _dedupe([*[str(tag) for tag in data.get("tags", [])], "claimed"])
    _write_json_validated(storage, path, data)
    return {"claimed": True, "queue": queue_row(storage, path, data)}


def update_queue_item(storage: LocalStorage, queue_ref: str | Path, *, status: str, updates: dict[str, Any]) -> dict[str, Any]:
    if status not in QUEUE_STATUSES:
        raise ValueError(f"agent_dispatch_queue status is invalid: {status}")
    path = resolve_queue(storage, queue_ref)
    data = _read_json_safe(storage, path)
    if not isinstance(data, dict) or data.get("type") != "agent_dispatch_queue":
        raise ValueError(f"agent_dispatch_queue JSON must be an object: {path}")
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    content.update(updates)
    content["status"] = status
    if status in {"acked", "retry_scheduled", "dead_letter", "waiting_human", "cancelled"}:
        content["lease_owner"] = ""
        content["lease_expires_at"] = ""
    data["content"] = content
    data["updated_at"] = utc_now()
    data["tags"] = _dedupe([*[str(tag) for tag in data.get("tags", [])], status])
    _write_json_validated(storage, path, data)
    return queue_row(storage, path, data)


def queue_row(storage: LocalStorage, path: Path, data: dict[str, Any]) -> dict[str, Any]:
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    return {
        "path": _display_path(storage.root, path),
        "id": data.get("id", ""),
        "dispatch_id": content.get("dispatch_id", ""),
        "idempotency_key": content.get("idempotency_key", ""),
        "status": content.get("status", ""),
        "agent_run_id": content.get("agent_run_id", ""),
        "agent_run_path": content.get("agent_run_path", ""),
        "agent_contract_path": content.get("agent_contract_path", ""),
        "workflow_run_id": content.get("workflow_run_id", ""),
        "workflow_run_path": content.get("workflow_run_path", ""),
        "workflow_node_id": content.get("workflow_node_id", ""),
        "operation": content.get("operation", ""),
        "agent_key": content.get("agent_key", ""),
        "priority": content.get("priority", 100),
        "attempt_count": content.get("attempt_count", 0),
        "max_attempts": content.get("max_attempts", 3),
        "available_at": content.get("available_at", ""),
        "lease_owner": content.get("lease_owner", ""),
        "lease_expires_at": content.get("lease_expires_at", ""),
        "claimed_at": content.get("claimed_at", ""),
        "acked_at": content.get("acked_at", ""),
        "dead_lettered_at": content.get("dead_lettered_at", ""),
        "last_error": content.get("last_error", ""),
        "checkpoint_path": content.get("checkpoint_path", ""),
        "expected_output_assets": content.get("expected_output_assets", []),
        "project_id": metadata.get("project_id", ""),
        "workspace_path": metadata.get("workspace_path", ""),
        "created_at": data.get("created_at", ""),
        "updated_at": data.get("updated_at", ""),
    }


def utc_datetime_after(seconds: int) -> str:
    return (utc_now_dt() + timedelta(seconds=max(0, int(seconds or 0)))).isoformat().replace("+00:00", "Z")


def parse_utc_datetime(value: str) -> datetime:
    if not value:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return datetime.fromtimestamp(0, tz=timezone.utc)


def utc_now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _read_json_safe(storage: LocalStorage, path: Path) -> dict[str, Any]:
    try:
        data = storage.read_json(path)
    except Exception as exc:
        require_recoverable_asset_scan_error(exc, context=f"agent dispatch queue scan: {path}")
        return {}
    return data if isinstance(data, dict) else {}


def _write_json_validated(storage: LocalStorage, path: Path, data: dict[str, Any]) -> None:
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    storage.write_json(path, data)


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _dedupe(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
