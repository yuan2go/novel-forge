from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.production_context import filter_project_safe_references
from novel_forge.modules.runtime_ledger import record_trace_span
from novel_forge.schemas import AgentConversationTrace, AgentHandoff, AgentInbox, AgentMessage, AgentOutbox, validate_common_fields
from novel_forge.storage.local import LocalStorage

AGENT_MESSAGE_TYPES = {"agent_message", "agent_inbox", "agent_outbox", "agent_handoff", "agent_conversation_trace"}


def send_agent_message(
    storage: LocalStorage,
    *,
    sender_agent: str,
    recipient_agent: str,
    topic: str,
    payload: dict[str, Any] | None = None,
    conversation_id: str = "",
    priority: int = 5,
    project_id: str = "",
    workspace_path: str = "",
    trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_conversation_id = conversation_id or make_id("conversation", f"{sender_agent}-{recipient_agent}-{topic}")
    content = {
        "message_id": make_id("agent_message", f"{sender_agent}-{recipient_agent}-{topic}-{utc_now()}"),
        "conversation_id": resolved_conversation_id,
        "sender_agent": sender_agent,
        "recipient_agent": recipient_agent,
        "topic": topic,
        "payload": payload or {},
        "priority": int(priority or 5),
        "status": "sent",
        "created_at": utc_now(),
        "acknowledged_at": "",
        "trace": trace or {},
    }
    asset = AgentMessage(
        title=f"Agent message {sender_agent} -> {recipient_agent}: {topic}",
        tags=["agent-message", sender_agent, recipient_agent, "sent"],
        content=content,
        metadata={"project_id": project_id, "workspace_path": workspace_path, "conversation_id": resolved_conversation_id},
        references=filter_project_safe_references(storage, project_id, _payload_paths(payload or {})),
    )
    message = _write(storage, asset)
    inbox = _write_box(storage, box_type="agent_inbox", agent_type=recipient_agent, message=message["asset"], project_id=project_id, workspace_path=workspace_path)
    outbox = _write_box(storage, box_type="agent_outbox", agent_type=sender_agent, message=message["asset"], project_id=project_id, workspace_path=workspace_path)
    _record_message_span(storage, trace, "agent_message", topic, message["path"], project_id, workspace_path)
    return {**message, "inbox": inbox, "outbox": outbox}


def acknowledge_agent_message(
    storage: LocalStorage,
    message_path_or_id: str,
    *,
    actor_agent: str = "",
    note: str = "",
) -> dict[str, Any]:
    path = _resolve_message(storage, message_path_or_id)
    if not path:
        raise FileNotFoundError(f"agent message not found: {message_path_or_id}")
    data = storage.read_json(path)
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    content["status"] = "acknowledged"
    content["acknowledged_at"] = utc_now()
    content["acknowledged_by"] = actor_agent
    content["ack_note"] = note
    data["content"] = content
    data["updated_at"] = utc_now()
    data["tags"] = _dedupe([*[str(tag) for tag in data.get("tags", [])], "acknowledged"])
    storage.write_json(path, data)
    return {"path": _display_path(storage.root, path), "id": data.get("id", ""), "asset": data, "validation": {"ok": True, "errors": []}}


def create_agent_handoff(
    storage: LocalStorage,
    *,
    from_agent: str,
    to_agent: str,
    payload: dict[str, Any],
    conversation_id: str = "",
    status: str = "ready",
    project_id: str = "",
    workspace_path: str = "",
) -> dict[str, Any]:
    content = {
        "handoff_id": make_id("agent_handoff", f"{from_agent}-{to_agent}-{utc_now()}"),
        "conversation_id": conversation_id or make_id("conversation", f"{from_agent}-{to_agent}"),
        "from_agent": from_agent,
        "to_agent": to_agent,
        "payload": payload,
        "status": _handoff_status(status),
        "created_at": utc_now(),
    }
    asset = AgentHandoff(
        title=f"Agent handoff {from_agent} -> {to_agent}",
        tags=["agent-handoff", from_agent, to_agent, content["status"]],
        content=content,
        metadata={"project_id": project_id, "workspace_path": workspace_path, "conversation_id": content["conversation_id"]},
        references=filter_project_safe_references(storage, project_id, _payload_paths(payload)),
    )
    return _write(storage, asset)


def list_agent_messages(
    storage: LocalStorage,
    *,
    agent_type: str | None = None,
    conversation_id: str | None = None,
    status: str | None = None,
    project_id: str | None = None,
    limit: int = 300,
) -> list[dict[str, Any]]:
    rows = []
    for path in storage.list_json("runs"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") not in AGENT_MESSAGE_TYPES:
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if project_id and str(metadata.get("project_id", "")) != project_id:
            continue
        if conversation_id and str(content.get("conversation_id", metadata.get("conversation_id", ""))) != conversation_id:
            continue
        if status and str(content.get("status", "")) != status:
            continue
        if agent_type and data.get("type") == "agent_message" and agent_type not in {str(content.get("sender_agent", "")), str(content.get("recipient_agent", ""))}:
            continue
        rows.append({**data, "path": _display_path(storage.root, path)})
    return sorted(rows, key=lambda row: str(row.get("updated_at", "")), reverse=True)[:limit]


def replay_agent_messages(storage: LocalStorage, *, conversation_id: str, project_id: str = "") -> dict[str, Any]:
    messages = [
        row
        for row in list_agent_messages(storage, conversation_id=conversation_id, project_id=project_id or None, limit=1000)
        if row.get("type") == "agent_message"
    ]
    ordered = sorted(messages, key=lambda row: str(row.get("content", {}).get("created_at", "")))
    return {
        "conversation_id": conversation_id,
        "message_count": len(ordered),
        "messages": [_message_summary(row) for row in ordered],
        "status": "ready",
    }


def create_agent_conversation_trace(storage: LocalStorage, *, conversation_id: str, project_id: str = "", workspace_path: str = "") -> dict[str, Any]:
    replay = replay_agent_messages(storage, conversation_id=conversation_id, project_id=project_id)
    agents = sorted(
        {
            str(message.get("sender_agent", ""))
            for message in replay["messages"]
            if str(message.get("sender_agent", "")).strip()
        }
        | {
            str(message.get("recipient_agent", ""))
            for message in replay["messages"]
            if str(message.get("recipient_agent", "")).strip()
        }
    )
    content = {
        "conversation_id": conversation_id,
        "agents": agents,
        "messages": replay["messages"],
        "status": "ready",
        "created_at": utc_now(),
    }
    asset = AgentConversationTrace(
        title=f"Agent conversation {conversation_id}",
        tags=["agent-conversation-trace", "ready"],
        content=content,
        metadata={"project_id": project_id, "workspace_path": workspace_path, "conversation_id": conversation_id},
    )
    return _write(storage, asset)


def _write_box(
    storage: LocalStorage,
    *,
    box_type: str,
    agent_type: str,
    message: dict[str, Any],
    project_id: str,
    workspace_path: str,
) -> dict[str, Any]:
    content = {
        "inbox_id" if box_type == "agent_inbox" else "outbox_id": make_id(box_type, f"{agent_type}-{utc_now()}"),
        "agent_type": agent_type,
        "messages": [_message_summary(message)],
        "created_at": utc_now(),
    }
    cls = AgentInbox if box_type == "agent_inbox" else AgentOutbox
    asset = cls(
        title=f"{agent_type} {'inbox' if box_type == 'agent_inbox' else 'outbox'} update",
        tags=[box_type, agent_type],
        content=content,
        metadata={"project_id": project_id, "workspace_path": workspace_path, "agent_type": agent_type},
    )
    return _write(storage, asset)


def _message_summary(row: dict[str, Any]) -> dict[str, Any]:
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    return {
        "path": row.get("path", ""),
        "message_id": content.get("message_id", row.get("id", "")),
        "conversation_id": content.get("conversation_id", ""),
        "sender_agent": content.get("sender_agent", ""),
        "recipient_agent": content.get("recipient_agent", ""),
        "topic": content.get("topic", ""),
        "status": content.get("status", ""),
        "created_at": content.get("created_at", ""),
    }


def _resolve_message(storage: LocalStorage, path_or_id: str) -> Path | None:
    candidate = storage.root / path_or_id
    if candidate.exists():
        return candidate
    for path in storage.list_json("runs"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        content = data.get("content", {}) if isinstance(data, dict) and isinstance(data.get("content", {}), dict) else {}
        if data.get("id") == path_or_id or content.get("message_id") == path_or_id:
            return path
    return None


def _record_message_span(storage: LocalStorage, trace: dict[str, Any] | None, span_type: str, name: str, path: str, project_id: str, workspace_path: str) -> None:
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


def _handoff_status(value: str) -> str:
    normalized = str(value or "ready").strip().lower().replace(" ", "_")
    return normalized if normalized in {"ready", "accepted", "rejected", "applied", "cancelled"} else "ready"


def _payload_paths(payload: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for key, value in payload.items():
        if isinstance(value, str) and (key == "path" or key.endswith("_path")):
            paths.append(value)
        elif isinstance(value, dict):
            paths.extend(_payload_paths(value))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    paths.extend(_payload_paths(item))
    return _dedupe(paths)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result = []
    for value in values:
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _write(storage: LocalStorage, asset: AgentMessage | AgentInbox | AgentOutbox | AgentHandoff | AgentConversationTrace) -> dict[str, Any]:
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
