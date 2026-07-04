from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.os_envelope import is_production_environment
from novel_forge.modules.runtime_ledger import record_gate_result, record_trace_span
from novel_forge.storage.local import LocalStorage

CRITICAL_EMPTY_PACK_FLOWS = {"prose", "review", "publish", "recap"}
SOURCE_ISOLATION_ERROR_MARKERS = ("raw_text", "source_chunk.raw_text", "source isolation", "source_isolation")


class MkaosPackPolicyError(ValueError):
    """Raised when MKAOS pack policy requires a hard stop."""


def resolve_mkaos_pack_policy(
    flow: str,
    *,
    environment: str = "",
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    strict = is_production_environment(environment)
    normalized_flow = str(flow or "").strip() or "unknown"
    override = overrides if isinstance(overrides, dict) else {}
    return {
        "flow": normalized_flow,
        "environment": "production" if strict else str(environment or "compat" or "compat"),
        "strict": strict,
        "mkaos_pack_required": _override_bool(override, "mkaos_pack_required", strict),
        "context_bundle_required": _override_bool(override, "context_bundle_required", strict),
        "knowledge_pack_id_required": _override_bool(override, "knowledge_pack_id_required", strict),
        "compat_warning_allowed": _override_bool(override, "compat_warning_allowed", not strict),
        "empty_pack_policy": str(override.get("empty_pack_policy") or ("block" if strict and normalized_flow in CRITICAL_EMPTY_PACK_FLOWS else "warn")),
        "source_isolation_required": _override_bool(override, "source_isolation_required", True),
        "critical_flow": normalized_flow in CRITICAL_EMPTY_PACK_FLOWS,
    }


def build_mkaos_flow_context_with_policy(
    storage: LocalStorage,
    *,
    flow: str,
    project_id: str,
    workspace_path: str = "",
    target_path: str | Path = "",
    environment: str = "",
    builder: Callable[[], dict[str, Any]],
    policy_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy = resolve_mkaos_pack_policy(flow, environment=environment, overrides=policy_overrides)
    try:
        result = builder()
    except Exception as exc:
        if should_block_mkaos_pack_failure(policy, exc):
            _record_mkaos_pack_policy_event(
                storage,
                flow=flow,
                project_id=project_id,
                workspace_path=workspace_path,
                target_path=target_path,
                policy=policy,
                status="failed",
                message=f"MKAOS pack build failed in production for {flow}: {exc}",
                blocking=True,
            )
            raise MkaosPackPolicyError(f"MKAOS pack build failed in production for {flow}: {exc}") from exc
        fallback = mkaos_pack_warning_fallback(
            storage,
            flow=flow,
            project_id=project_id,
            workspace_path=workspace_path,
            target_path=target_path,
            policy=policy,
            warning=f"MKAOS pack build warning fallback for {flow}: {exc}",
        )
        return fallback
    pack = result.get("mkaos_pack", result) if isinstance(result, dict) else {}
    validate_mkaos_pack_result(
        storage,
        flow=flow,
        mkaos_pack=pack,
        project_id=project_id,
        workspace_path=workspace_path,
        target_path=target_path,
        environment=environment,
        context_bundle_path=str(result.get("path") or result.get("context_bundle_path") or "") if isinstance(result, dict) else "",
        policy_overrides=policy_overrides,
    )
    return result


def should_block_mkaos_pack_failure(policy: dict[str, Any], exc: Exception) -> bool:
    if bool(policy.get("source_isolation_required")) and _looks_like_source_isolation_error(exc):
        return True
    if bool(policy.get("strict")) or bool(policy.get("mkaos_pack_required")):
        return True
    return not bool(policy.get("compat_warning_allowed"))


def validate_mkaos_pack_result(
    storage: LocalStorage,
    *,
    flow: str,
    mkaos_pack: dict[str, Any],
    project_id: str,
    workspace_path: str = "",
    target_path: str | Path = "",
    environment: str = "",
    context_bundle_path: str = "",
    policy_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy = resolve_mkaos_pack_policy(flow, environment=environment, overrides=policy_overrides)
    asset = mkaos_pack.get("asset", {}) if isinstance(mkaos_pack.get("asset", {}), dict) else {}
    content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
    pack_id = str(content.get("knowledge_pack_id") or asset.get("id") or "").strip()
    pack_path = str(mkaos_pack.get("path") or "").strip()
    pack_items = content.get("pack_items", []) if isinstance(content.get("pack_items", []), list) else []
    failures: list[str] = []
    warnings: list[str] = []

    if policy["mkaos_pack_required"] and (not isinstance(mkaos_pack, dict) or not asset or not pack_path):
        failures.append("MKAOS pack is required but missing")
    if policy["context_bundle_required"] and not str(context_bundle_path or "").strip():
        failures.append("context_bundle is required but missing")
    if policy["knowledge_pack_id_required"] and not pack_id:
        failures.append("knowledge_pack_id is required but missing")
    if policy["source_isolation_required"] and _contains_key(content, "raw_text"):
        failures.append("MKAOS source isolation failed: source_chunk.raw_text is present")
    if policy["empty_pack_policy"] == "block" and not pack_items:
        failures.append(f"{flow} MKAOS pack is empty")
    elif not pack_items:
        warnings.append(f"{flow} MKAOS pack is empty")

    if failures:
        message = "; ".join(failures)
        _record_mkaos_pack_policy_event(
            storage,
            flow=flow,
            project_id=project_id,
            workspace_path=workspace_path,
            target_path=target_path,
            policy=policy,
            status="failed",
            message=message,
            blocking=True,
            context_bundle_path=context_bundle_path,
            pack_path=pack_path,
        )
        raise MkaosPackPolicyError(message)
    if warnings:
        event = _record_mkaos_pack_policy_event(
            storage,
            flow=flow,
            project_id=project_id,
            workspace_path=workspace_path,
            target_path=target_path,
            policy=policy,
            status="warning",
            message="; ".join(warnings),
            blocking=False,
            context_bundle_path=context_bundle_path,
            pack_path=pack_path,
        )
        _attach_policy_metadata_to_pack(storage, mkaos_pack, policy=policy, warning="; ".join(warnings), event=event)
    else:
        _attach_policy_metadata_to_pack(storage, mkaos_pack, policy=policy, warning="", event={})
    return mkaos_pack


def mkaos_pack_warning_fallback(
    storage: LocalStorage,
    *,
    flow: str,
    project_id: str,
    workspace_path: str = "",
    target_path: str | Path = "",
    policy: dict[str, Any],
    warning: str,
) -> dict[str, Any]:
    event = _record_mkaos_pack_policy_event(
        storage,
        flow=flow,
        project_id=project_id,
        workspace_path=workspace_path,
        target_path=target_path,
        policy=policy,
        status="warning",
        message=warning,
        blocking=False,
    )
    fallback = {
        "path": "",
        "asset": {
            "id": "",
            "type": "knowledge_pack",
            "content": {
                "flow": flow,
                "knowledge_pack_id": "",
                "pack_items": [],
                "warnings": [warning],
                "mkaos_pack_policy": policy,
                "runtime_policy_warning_path": event.get("gate_result_path", ""),
                "trace_span_path": event.get("trace_span_path", ""),
                "source_isolation": {"prose_raw_source_text_included": False, "source_chunk_ids_only": True},
            },
            "metadata": {
                "project_id": project_id,
                "workspace_path": workspace_path,
                "mkaos_pack_policy": policy,
                "mkaos_warning": warning,
                "runtime_policy_warning_path": event.get("gate_result_path", ""),
                "trace_span_path": event.get("trace_span_path", ""),
            },
        },
        "warning": warning,
        "mkaos_pack_policy": policy,
        "runtime_policy_warning_path": event.get("gate_result_path", ""),
        "trace_span_path": event.get("trace_span_path", ""),
    }
    return fallback


def mkaos_pack_metadata(pack: dict[str, Any]) -> dict[str, Any]:
    asset = pack.get("asset", {}) if isinstance(pack.get("asset", {}), dict) else {}
    metadata = asset.get("metadata", {}) if isinstance(asset.get("metadata", {}), dict) else {}
    content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
    return {
        "mkaos_pack_policy": pack.get("mkaos_pack_policy") or metadata.get("mkaos_pack_policy") or content.get("mkaos_pack_policy") or {},
        "mkaos_runtime_policy_warning_path": pack.get("runtime_policy_warning_path") or metadata.get("runtime_policy_warning_path") or content.get("runtime_policy_warning_path") or "",
        "mkaos_pack_trace_span_path": pack.get("trace_span_path") or metadata.get("trace_span_path") or content.get("trace_span_path") or "",
    }


def _record_mkaos_pack_policy_event(
    storage: LocalStorage,
    *,
    flow: str,
    project_id: str,
    workspace_path: str,
    target_path: str | Path,
    policy: dict[str, Any],
    status: str,
    message: str,
    blocking: bool,
    context_bundle_path: str = "",
    pack_path: str = "",
) -> dict[str, str]:
    trace_id = make_id("trace", f"mkaos-pack-policy-{flow}-{project_id}-{utc_now()}")
    trace = record_trace_span(
        storage,
        trace_id=trace_id,
        span_type="runtime_policy",
        name=f"mkaos_pack_policy.{flow}",
        status="failed" if status == "failed" else "warning",
        attributes={"flow": flow, "message": message, "policy": policy, "blocking": blocking},
        references=[str(item) for item in [target_path, context_bundle_path, pack_path] if str(item).strip()],
        project_id=project_id,
        workspace_path=workspace_path,
    )
    gate = record_gate_result(
        storage,
        gate_kind="runtime_policy",
        status="failed" if status == "failed" else "warning",
        target_paths=[str(item) for item in [target_path, context_bundle_path, pack_path] if str(item).strip()],
        result={"operation": "mkaos_pack_policy", "flow": flow, "policy": policy, "message": message},
        trace={"trace_id": trace_id},
        project_id=project_id,
        workspace_path=workspace_path,
        message=message,
        blocking=blocking,
    )
    return {"trace_span_path": str(trace.get("path", "")), "gate_result_path": str(gate.get("path", ""))}


def _attach_policy_metadata_to_pack(
    storage: LocalStorage,
    mkaos_pack: dict[str, Any],
    *,
    policy: dict[str, Any],
    warning: str,
    event: dict[str, str],
) -> None:
    path = str(mkaos_pack.get("path") or "").strip()
    asset = mkaos_pack.get("asset", {}) if isinstance(mkaos_pack.get("asset", {}), dict) else {}
    if asset:
        content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
        metadata = asset.get("metadata", {}) if isinstance(asset.get("metadata", {}), dict) else {}
        content["mkaos_pack_policy"] = policy
        metadata["mkaos_pack_policy"] = policy
        if warning:
            content["warnings"] = _dedupe([*[str(item) for item in content.get("warnings", []) if str(item).strip()], warning])
            metadata["mkaos_warning"] = warning
        if event.get("gate_result_path"):
            content["runtime_policy_warning_path"] = event["gate_result_path"]
            metadata["runtime_policy_warning_path"] = event["gate_result_path"]
        if event.get("trace_span_path"):
            content["trace_span_path"] = event["trace_span_path"]
            metadata["trace_span_path"] = event["trace_span_path"]
        asset["content"] = content
        asset["metadata"] = metadata
    if not path:
        return
    try:
        data_path = storage.root / path
        data = storage.read_json(data_path)
        if isinstance(data, dict):
            data["content"] = asset.get("content", data.get("content", {})) if asset else data.get("content", {})
            data["metadata"] = asset.get("metadata", data.get("metadata", {})) if asset else data.get("metadata", {})
            data["updated_at"] = utc_now()
            storage.write_json(data_path, data)
            mkaos_pack["asset"] = data
    except Exception:
        return


def _contains_key(value: Any, key: str) -> bool:
    if isinstance(value, dict):
        return any(str(item_key) == key or _contains_key(item_value, key) for item_key, item_value in value.items())
    if isinstance(value, list):
        return any(_contains_key(item, key) for item in value)
    return False


def _looks_like_source_isolation_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in SOURCE_ISOLATION_ERROR_MARKERS)


def _override_bool(overrides: dict[str, Any], key: str, default: bool) -> bool:
    if key not in overrides:
        return default
    return bool(overrides.get(key))


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
