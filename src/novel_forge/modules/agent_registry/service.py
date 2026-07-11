from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.agents.runtime import AGENT_RUNTIME_PROFILES
from novel_forge.core.ids import utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.modules.production_context import filter_project_safe_references
from novel_forge.schemas import BaseAsset, validate_common_fields
from novel_forge.storage.local import LocalStorage

LIFECYCLE_STATES = {"draft", "experimental", "active", "deprecated", "archived"}
SCHEDULABLE_STATES = {"active"}
EVALUATION_STATES = {"experimental", "active"}
SYSTEM_PROJECT_ID = "local-system"
SYSTEM_WORKSPACE_PATH = "local-system"


def sync_runtime_profiles(storage: LocalStorage, *, default_state: str = "active") -> dict[str, Any]:
    _validate_state(default_state)
    entries = []
    versions = []
    for agent_id, profile in sorted(AGENT_RUNTIME_PROFILES.items()):
        synced = _sync_runtime_profile(storage, agent_id, profile=profile, default_state=default_state)
        entries.append(synced["entry"])
        versions.append(synced["version"])
    snapshot = create_agent_registry_snapshot(storage)
    return {"entries": entries, "versions": versions, "snapshot": snapshot, "count": len(entries)}


def _sync_runtime_profile(
    storage: LocalStorage,
    agent_id: str,
    *,
    profile: dict[str, Any] | None = None,
    default_state: str = "active",
) -> dict[str, Any]:
    _validate_state(default_state)
    profile = profile or AGENT_RUNTIME_PROFILES[agent_id]
    existing = get_agent_registry_entry(storage, agent_id)
    state = str(existing.get("content", {}).get("lifecycle_state") or default_state) if existing else default_state
    entry = upsert_agent_registry_entry(
        storage,
        {
            "agent_id": agent_id,
            "agent_type": agent_id,
            "display_name": str(profile.get("agent") or agent_id),
            "description": f"Runtime profile synced from AGENT_RUNTIME_PROFILES for {agent_id}.",
            "lifecycle_state": state,
            "capabilities": _capabilities_from_profile(profile),
            "operation_coverage": _operation_coverage_for_agent(agent_id),
            "prompt_bindings": [],
            "model_bindings": [],
            "evaluation_bindings": _evaluation_binding_refs(storage, agent_id),
            "scheduler_enabled": state in SCHEDULABLE_STATES,
            "source": "AGENT_RUNTIME_PROFILES",
        },
    )
    profile_version = str(profile.get("version") or "runtime-profile-v1")
    existing_version = _find_agent_version(storage, agent_id, profile_version)
    version = existing_version or create_agent_version(
        storage,
        agent_id=agent_id,
        version=profile_version,
        status="synced",
        runtime_profile=profile,
    )
    return {"entry": entry, "version": version}


def upsert_agent_registry_entry(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    agent_id = _required(payload, "agent_id")
    state = str(payload.get("lifecycle_state") or "draft")
    _validate_state(state)
    now = utc_now()
    path = _entry_path(storage, agent_id)
    existing = storage.read_json(path) if path.exists() else {}
    created_at = str(existing.get("created_at") or now) if isinstance(existing, dict) else now
    content = {
        "agent_id": agent_id,
        "agent_type": str(payload.get("agent_type") or agent_id),
        "display_name": str(payload.get("display_name") or agent_id),
        "description": str(payload.get("description") or ""),
        "lifecycle_state": state,
        "capabilities": payload.get("capabilities", []) if isinstance(payload.get("capabilities", []), list) else [],
        "operation_coverage": payload.get("operation_coverage", []) if isinstance(payload.get("operation_coverage", []), list) else [],
        "prompt_bindings": payload.get("prompt_bindings", []) if isinstance(payload.get("prompt_bindings", []), list) else [],
        "model_bindings": payload.get("model_bindings", []) if isinstance(payload.get("model_bindings", []), list) else [],
        "evaluation_bindings": payload.get("evaluation_bindings", []) if isinstance(payload.get("evaluation_bindings", []), list) else [],
        "scheduler_enabled": bool(payload.get("scheduler_enabled", state in SCHEDULABLE_STATES)) and state in SCHEDULABLE_STATES,
        "production_schedulable": state in SCHEDULABLE_STATES,
        "evaluation_allowed": state in EVALUATION_STATES,
        "source": str(payload.get("source") or "manual"),
        "created_at": created_at,
        "updated_at": now,
    }
    asset = BaseAsset(
        id=_entry_id(agent_id),
        type="agent_registry_entry",
        title=content["display_name"],
        tags=["agent-registry", state, agent_id],
        content=content,
        metadata=_system_metadata(agent_id=agent_id, lifecycle_state=state, scheduler_enabled=content["scheduler_enabled"]),
        references=filter_project_safe_references(storage, SYSTEM_PROJECT_ID, _binding_refs(content)),
    )
    return _write(storage, asset, path=path)


def create_agent_version(
    storage: LocalStorage,
    *,
    agent_id: str,
    version: str,
    status: str = "active",
    runtime_profile: dict[str, Any] | None = None,
    notes: str = "",
) -> dict[str, Any]:
    content = {
        "agent_id": agent_id,
        "version": version,
        "status": status,
        "runtime_profile": runtime_profile or {},
        "notes": notes,
        "created_at": utc_now(),
    }
    asset = BaseAsset(
        type="agent_version",
        title=f"{agent_id} {version}",
        tags=["agent-registry", "version", agent_id, status],
        content=content,
        metadata=_system_metadata(agent_id=agent_id, version=version, status=status),
    )
    return _write(storage, asset)


def record_agent_lifecycle_event(
    storage: LocalStorage,
    *,
    agent_id: str,
    to_state: str,
    reason: str = "",
    actor: str = "operator",
) -> dict[str, Any]:
    _validate_state(to_state)
    entry = get_agent_registry_entry(storage, agent_id)
    from_state = str(entry.get("content", {}).get("lifecycle_state") or "draft") if entry else "missing"
    merged = dict(entry.get("content", {}) if entry else {"agent_id": agent_id, "agent_type": agent_id, "display_name": agent_id})
    merged["lifecycle_state"] = to_state
    merged["scheduler_enabled"] = to_state in SCHEDULABLE_STATES
    updated = upsert_agent_registry_entry(storage, merged)
    content = {
        "agent_id": agent_id,
        "from_state": from_state,
        "to_state": to_state,
        "reason": reason,
        "actor": actor,
        "created_at": utc_now(),
    }
    asset = BaseAsset(
        type="agent_lifecycle_event",
        title=f"{agent_id}: {from_state} -> {to_state}",
        tags=["agent-registry", "lifecycle", agent_id, to_state],
        content=content,
        metadata=_system_metadata(agent_id=agent_id, from_state=from_state, to_state=to_state),
        references=[updated["asset"]["id"], updated["path"]],
    )
    event = _write(storage, asset)
    return {"entry": updated, "event": event}


def create_agent_capability(storage: LocalStorage, *, agent_id: str, capability_id: str, capability_type: str, status: str = "active", payload: dict[str, Any] | None = None) -> dict[str, Any]:
    content = {
        "agent_id": agent_id,
        "capability_id": capability_id,
        "capability_type": capability_type,
        "status": status,
        "payload": payload or {},
        "created_at": utc_now(),
    }
    asset = BaseAsset(
        type="agent_capability",
        title=f"{agent_id} capability {capability_id}",
        tags=["agent-registry", "capability", agent_id, capability_type, status],
        content=content,
        metadata=_system_metadata(agent_id=agent_id, capability_id=capability_id, status=status),
    )
    return _write(storage, asset)


def create_agent_evaluation_binding(storage: LocalStorage, *, agent_id: str, evaluation_suite_id: str, gate_policy: dict[str, Any] | None = None, status: str = "active") -> dict[str, Any]:
    content = {
        "binding_id": f"agent-eval-{agent_id}-{evaluation_suite_id}",
        "agent_id": agent_id,
        "evaluation_suite_id": evaluation_suite_id,
        "gate_policy": gate_policy or {"required_for_active": True, "minimum_score": 0.72},
        "status": status,
        "created_at": utc_now(),
    }
    asset = BaseAsset(
        type="agent_evaluation_binding",
        title=f"{agent_id} evaluation binding",
        tags=["agent-registry", "evaluation-binding", agent_id, status],
        content=content,
        metadata=_system_metadata(agent_id=agent_id, evaluation_suite_id=evaluation_suite_id, status=status),
    )
    result = _write(storage, asset)
    entry = get_agent_registry_entry(storage, agent_id)
    if entry:
        content_entry = dict(entry.get("content", {}))
        refs = content_entry.get("evaluation_bindings", []) if isinstance(content_entry.get("evaluation_bindings", []), list) else []
        refs.append({"binding_id": content["binding_id"], "evaluation_suite_id": evaluation_suite_id, "path": result["path"], "status": status})
        content_entry["evaluation_bindings"] = _dedupe_dicts(refs, "binding_id")
        upsert_agent_registry_entry(storage, content_entry)
    return result


def list_agent_registry_entries(storage: LocalStorage, *, lifecycle_state: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
    rows = [_row(storage, path) for path in reversed(storage.list_json("runs"))]
    entries = [row for row in rows if row.get("type") == "agent_registry_entry"]
    if lifecycle_state:
        entries = [row for row in entries if row.get("content", {}).get("lifecycle_state") == lifecycle_state]
    return entries[: max(1, int(limit or 500))]


def get_agent_registry_entry(storage: LocalStorage, agent_id: str) -> dict[str, Any]:
    path = _entry_path(storage, agent_id)
    if path.exists():
        return storage.read_json(path)
    return {}


def resolve_agent_registry_entry(
    storage: LocalStorage,
    *,
    agent_id: str,
    operation: str = "",
    environment: str = "",
    require_schedulable: bool = False,
    auto_sync: bool = True,
) -> dict[str, Any]:
    if auto_sync and not get_agent_registry_entry(storage, agent_id) and agent_id in AGENT_RUNTIME_PROFILES:
        _sync_runtime_profile(storage, agent_id)
    entry = get_agent_registry_entry(storage, agent_id)
    if not entry:
        raise ValueError(f"agent registry entry not found: {agent_id}")
    content = entry.get("content", {}) if isinstance(entry.get("content", {}), dict) else {}
    state = str(content.get("lifecycle_state") or "")
    schedulable = bool(content.get("scheduler_enabled")) and state in SCHEDULABLE_STATES
    if require_schedulable and not schedulable:
        raise RuntimeError(f"agent {agent_id} is not schedulable for {operation or 'operation'}: lifecycle_state={state}")
    return {
        "agent_id": agent_id,
        "entry": entry,
        "agent_registry_entry_id": entry.get("id", ""),
        "agent_registry_entry_path": _display_path(storage.root, _entry_path(storage, agent_id)),
        "agent_registry_version": str(content.get("updated_at") or entry.get("updated_at") or ""),
        "lifecycle_state": state,
        "scheduler_enabled": schedulable,
        "operation": operation,
        "environment": environment,
    }


def create_agent_registry_snapshot(storage: LocalStorage, *, project_id: str = "") -> dict[str, Any]:
    from novel_forge.modules.agent_scheduler import list_agent_operation_contracts, mkaos_agent_operation_coverage_report

    entries = list_agent_registry_entries(storage, limit=1000)
    operation_contracts = list_agent_operation_contracts()
    mkaos_coverage = mkaos_agent_operation_coverage_report()
    coverage = {
        "entry_count": len(entries),
        "active_count": sum(1 for row in entries if row.get("content", {}).get("lifecycle_state") == "active"),
        "schedulable_count": sum(1 for row in entries if row.get("content", {}).get("scheduler_enabled")),
        "operation_contract_count": len([row for row in operation_contracts if row.get("operation") != "*"]),
        "mkaos_required_operations": mkaos_coverage.get("summary", {}).get("required_count", 0),
    }
    resolved_project_id = project_id or SYSTEM_PROJECT_ID
    content = {
        "snapshot_id": f"agent-registry-snapshot-{utc_now()}",
        "project_id": resolved_project_id,
        "entries": entries,
        "coverage": coverage,
        "operation_contracts": operation_contracts,
        "mkaos_operation_coverage": mkaos_coverage,
        "created_at": utc_now(),
    }
    asset = BaseAsset(
        type="agent_registry_snapshot",
        title="Agent Registry snapshot",
        tags=["agent-registry", "snapshot"],
        content=content,
        metadata={
            "project_id": resolved_project_id,
            "workspace_path": SYSTEM_WORKSPACE_PATH if not project_id else "",
            "scope_kind": "project" if project_id else "system",
            **coverage,
        },
        references=[str(row.get("id", "")) for row in entries if row.get("id")],
    )
    return _write(storage, asset)


def agent_registry_coverage(storage: LocalStorage) -> dict[str, Any]:
    entries = list_agent_registry_entries(storage, limit=1000)
    states: dict[str, int] = {}
    for row in entries:
        state = str(row.get("content", {}).get("lifecycle_state") or "unknown")
        states[state] = states.get(state, 0) + 1
    return {
        "states": states,
        "entry_count": len(entries),
        "runtime_profile_count": len(AGENT_RUNTIME_PROFILES),
        "missing_runtime_profiles": sorted(set(AGENT_RUNTIME_PROFILES) - {str(row.get("content", {}).get("agent_id", "")) for row in entries}),
        "scheduler_policy": "draft/experimental/deprecated/archived agents cannot enter production scheduler; active only",
    }


def _entry_id(agent_id: str) -> str:
    return f"agent-registry-entry-{agent_id.replace('_', '-')}"


def _system_metadata(**values: Any) -> dict[str, Any]:
    return {
        "project_id": SYSTEM_PROJECT_ID,
        "workspace_path": SYSTEM_WORKSPACE_PATH,
        "scope_kind": "system",
        **values,
    }


def _entry_path(storage: LocalStorage, agent_id: str) -> Path:
    return storage.root / "data" / "runs" / f"{_entry_id(agent_id)}.json"


def _capabilities_from_profile(profile: dict[str, Any]) -> list[dict[str, Any]]:
    tools = profile.get("allowed_tools", []) if isinstance(profile.get("allowed_tools", []), list) else []
    writes = profile.get("allowed_write_types", []) if isinstance(profile.get("allowed_write_types", []), list) else []
    return [
        {"capability_id": f"tool:{tool}", "capability_type": "tool", "status": "active"}
        for tool in tools
    ] + [
        {"capability_id": f"write:{asset_type}", "capability_type": "output_asset", "status": "active"}
        for asset_type in writes
    ]


def _operation_coverage_for_agent(agent_id: str) -> list[dict[str, Any]]:
    from novel_forge.modules.agent_scheduler import list_agent_operation_contracts

    rows = []
    for contract in list_agent_operation_contracts():
        if contract.get("operation") == "*":
            continue
        if str(contract.get("agent_key", "")) == agent_id:
            rows.append({"operation": contract.get("operation", ""), "runner_kind": contract.get("runner_kind", ""), "output_types": contract.get("output_types", [])})
    return rows


def _evaluation_binding_refs(storage: LocalStorage, agent_id: str) -> list[dict[str, Any]]:
    refs = []
    for path in reversed(storage.list_json("runs")):
        data = _read_json_safe(storage, path)
        if data.get("type") != "agent_evaluation_binding":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if content.get("agent_id") == agent_id:
            refs.append({"binding_id": content.get("binding_id", ""), "evaluation_suite_id": content.get("evaluation_suite_id", ""), "path": _display_path(storage.root, path), "status": content.get("status", "")})
    return refs


def _find_agent_version(storage: LocalStorage, agent_id: str, version: str) -> dict[str, Any]:
    for path in reversed(storage.list_json("runs")):
        data = _read_json_safe(storage, path)
        if data.get("type") != "agent_version":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if str(content.get("agent_id", "")) == agent_id and str(content.get("version", "")) == version:
            return {"path": _display_path(storage.root, path), "asset": data, "validation": {"ok": True, "errors": []}}
    return {}


def _binding_refs(content: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for key in ["prompt_bindings", "model_bindings", "evaluation_bindings"]:
        for item in content.get(key, []) if isinstance(content.get(key, []), list) else []:
            if isinstance(item, dict):
                refs.extend(str(item.get(ref_key, "")) for ref_key in ["path", "prompt_id", "model_name", "evaluation_suite_id"] if item.get(ref_key))
            elif str(item).strip():
                refs.append(str(item))
    return [item for item in refs if item]


def _write(storage: LocalStorage, asset: BaseAsset, *, path: Path | None = None) -> dict[str, Any]:
    data = asset.to_dict()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    if path is None:
        written = storage.write_asset_auto(asset)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        storage.write_json(path, data)
        written = path
    return {"path": _display_path(storage.root, written), "asset": data, "validation": {"ok": True, "errors": []}}


def _row(storage: LocalStorage, path: Path) -> dict[str, Any]:
    data = _read_json_safe(storage, path)
    if data:
        data["path"] = _display_path(storage.root, path)
    return data


def _read_json_safe(storage: LocalStorage, path: Path) -> dict[str, Any]:
    try:
        data = storage.read_json(path)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _display_path(root: Path, path: str | Path) -> str:
    candidate = Path(path)
    try:
        return str(candidate.relative_to(root))
    except ValueError:
        return str(candidate)


def _required(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(f"{key} is required")
    return value


def _validate_state(state: str) -> None:
    if state not in LIFECYCLE_STATES:
        raise ValueError(f"invalid lifecycle_state: {state}")


def _dedupe_dicts(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    seen = set()
    result = []
    for row in rows:
        marker = str(row.get(key, ""))
        if not marker or marker in seen:
            continue
        seen.add(marker)
        result.append(row)
    return result
