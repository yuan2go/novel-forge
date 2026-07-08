from __future__ import annotations

from typing import Any

from novel_forge.modules.common import resolve_path
from novel_forge.storage.local import LocalStorage

REFERENCE_KEYS = {
    "agent_run_path",
    "context_bundle_path",
    "dispatch_queue_path",
    "gate_result_path",
    "path",
    "readiness_report_path",
    "runtime_policy_gate_result_path",
    "source_governance_runtime_gate_path",
    "source_governance_gate_result_path",
    "workflow_run_path",
}

REFERENCE_LIST_KEYS = {
    "evidence_paths",
    "expected_output_assets",
    "input_assets",
    "output_assets",
    "references",
    "target_asset_paths",
    "target_paths",
}


def asset_matches_project_scope(storage: LocalStorage, data: dict[str, Any], project_id: str) -> bool:
    if not project_id:
        return True
    direct = direct_project_id(data)
    if direct:
        return direct == project_id
    return any(path_matches_project_scope(storage, ref, project_id) for ref in runtime_scope_reference_paths(data))


def direct_project_id(data: dict[str, Any]) -> str:
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    return str(metadata.get("project_id") or content.get("project_id") or "")


def path_matches_project_scope(storage: LocalStorage, ref: str, project_id: str, *, _depth: int = 0, _seen: set[str] | None = None) -> bool:
    if not ref or not project_id:
        return False
    seen = _seen if _seen is not None else set()
    if ref in seen or _depth > 2:
        return False
    seen.add(ref)
    try:
        data = storage.read_json(resolve_path(storage.root, ref))
    except (FileNotFoundError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    direct = direct_project_id(data)
    if direct:
        return direct == project_id
    return any(path_matches_project_scope(storage, child, project_id, _depth=_depth + 1, _seen=seen) for child in runtime_scope_reference_paths(data))


def runtime_scope_reference_paths(data: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    refs.extend(_paths_from_value(data.get("references", []), list_context=True))
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    for source in [metadata, content]:
        for key in REFERENCE_KEYS:
            refs.extend(_paths_from_keyed_value(key, source.get(key)))
        for key in REFERENCE_LIST_KEYS:
            refs.extend(_paths_from_value(source.get(key, []), list_context=True))
    evidence = content.get("evidence", {}) if isinstance(content.get("evidence", {}), dict) else {}
    processor = content.get("processor", {}) if isinstance(content.get("processor", {}), dict) else {}
    state = content.get("state", {}) if isinstance(content.get("state", {}), dict) else {}
    for source in [evidence, processor, state]:
        refs.extend(_paths_from_value(source))
    service_result = state.get("service_result", {}) if isinstance(state.get("service_result", {}), dict) else {}
    refs.extend(_paths_from_value(service_result))
    return _dedupe(refs)


def _paths_from_keyed_value(key: str, value: Any) -> list[str]:
    if key not in REFERENCE_KEYS and key not in REFERENCE_LIST_KEYS:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    return _paths_from_value(value, list_context=key in REFERENCE_LIST_KEYS)


def _paths_from_value(value: Any, *, list_context: bool = False, depth: int = 0) -> list[str]:
    if depth > 4:
        return []
    if isinstance(value, str):
        return [value] if list_context and value.strip() else []
    if isinstance(value, list):
        refs: list[str] = []
        for item in value:
            refs.extend(_paths_from_value(item, list_context=True, depth=depth + 1))
        return refs
    if isinstance(value, dict):
        refs: list[str] = []
        for key in REFERENCE_KEYS:
            child = value.get(key)
            if isinstance(child, str) and child.strip():
                refs.append(child)
        for key in REFERENCE_LIST_KEYS:
            refs.extend(_paths_from_value(value.get(key, []), list_context=True, depth=depth + 1))
        for key in ["gate_result", "readiness_report", "runtime_policy_evidence", "source_governance_runtime_gate"]:
            child = value.get(key)
            if isinstance(child, dict):
                refs.extend(_paths_from_value(child, depth=depth + 1))
        return refs
    return []


def _dedupe(values: list[str]) -> list[str]:
    return [value for value in dict.fromkeys(str(item) for item in values if str(item or "").strip())]
