from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.agent_runs import record_agent_event
from novel_forge.modules.common import resolve_path
from novel_forge.modules.production_context import filter_project_safe_references
from novel_forge.schemas import AgentRollbackReport, validate_common_fields
from novel_forge.storage.local import LocalStorage


def rollback_operation_outputs(
    storage: LocalStorage,
    queue_item: dict[str, Any],
    agent_run: dict[str, Any],
    *,
    operation: str,
    output_assets: list[str],
    strategy: str,
    reason: str,
) -> dict[str, Any]:
    queue_content = queue_item.get("content", {}) if isinstance(queue_item.get("content", {}), dict) else {}
    run_content = agent_run.get("content", {}) if isinstance(agent_run.get("content", {}), dict) else {}
    metadata = agent_run.get("metadata", {}) if isinstance(agent_run.get("metadata", {}), dict) else {}
    target_paths = _dedupe(output_assets)
    applied_paths: list[str] = []
    errors: list[str] = []
    manual_required = strategy in {"manual_reconciliation_required", "rollback_patch_available"}
    for target in target_paths:
        try:
            path = resolve_path(storage.root, target)
            data = storage.read_json(path)
            if not isinstance(data, dict):
                raise ValueError("target asset is not a JSON object")
            target_metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
            target_metadata["rollback_status"] = "rollback_required" if manual_required else "rolled_back"
            target_metadata["rollback_strategy"] = strategy
            target_metadata["rollback_reason"] = reason
            target_metadata["rolled_back_by_agent_run_id"] = run_content.get("run_id", "")
            target_metadata["rolled_back_by_dispatch_id"] = queue_content.get("dispatch_id", "")
            target_metadata["rollback_at"] = utc_now()
            target_metadata["asset_status"] = "rollback_required" if manual_required else "rolled_back"
            data["metadata"] = target_metadata
            data["tags"] = _dedupe([*[str(tag) for tag in data.get("tags", [])], "rollback-required" if manual_required else "rolled-back"])
            data["updated_at"] = utc_now()
            _write_json_validated(storage, path, data)
            applied_paths.append(_display_path(storage.root, path))
        except Exception as exc:
            errors.append(f"{target}: {type(exc).__name__}: {exc}")
    status = "failed" if errors else "applied" if target_paths else "not_required"
    asset = AgentRollbackReport(
        title=f"Agent operation rollback: {operation or run_content.get('operation', '')}",
        source=str(run_content.get("run_id", "")),
        tags=["agent-rollback", "agent-operation-rollback", status, operation],
        content={
            "agent_run_id": run_content.get("run_id", ""),
            "agent_run_path": str(queue_content.get("agent_run_path", "")),
            "rollback_id": make_id("rollback", f"{run_content.get('run_id', '')}:{queue_content.get('dispatch_id', '')}:{operation}"),
            "target_asset_paths": target_paths,
            "applied_asset_paths": applied_paths,
            "rollback_strategy": strategy,
            "status": status,
            "reason": reason,
            "operation": operation,
            "dispatch_id": queue_content.get("dispatch_id", ""),
            "idempotency_key": queue_content.get("idempotency_key", ""),
            "errors": errors,
            "created_at": utc_now(),
        },
        metadata={"project_id": metadata.get("project_id", ""), "workspace_path": metadata.get("workspace_path", "")},
        references=filter_project_safe_references(storage, str(metadata.get("project_id", "")), _dedupe([str(queue_content.get("agent_run_path", "")), *target_paths, *applied_paths])),
    )
    report_path = storage.write_asset("runs", asset)
    result = {"status": status, "path": _display_path(storage.root, report_path), "target_asset_paths": target_paths, "applied_asset_paths": applied_paths, "errors": errors, "rollback_strategy": strategy}
    try:
        record_agent_event(
            storage,
            agent_run_path=str(queue_content.get("agent_run_path", "")),
            event_type="agent_operation.rollback",
            status="failed" if errors else "recovered",
            message=reason,
            payload=result,
        )
    except (FileNotFoundError, ValueError):
        pass
    return result


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
