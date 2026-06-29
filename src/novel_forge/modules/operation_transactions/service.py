from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.modules.production_context import filter_project_safe_references
from novel_forge.modules.runtime_ledger import record_cost_ledger, record_trace_span
from novel_forge.schemas import OperationTransaction, RollbackPlan, RollbackResult, validate_common_fields
from novel_forge.storage.local import LocalStorage


def create_operation_transaction(
    storage: LocalStorage,
    *,
    operation: str,
    workflow_run_id: str = "",
    agent_run_id: str = "",
    input_assets: list[str | Path] | None = None,
    created_assets: list[str | Path] | None = None,
    updated_assets: list[str | Path] | None = None,
    previous_versions: list[str | Path] | None = None,
    indexes_touched: list[str] | None = None,
    ledger_paths: list[str | Path] | None = None,
    rollback_plan: dict[str, Any] | None = None,
    project_id: str = "",
    workspace_path: str = "",
    trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    storage.ensure_layout()
    transaction_id = make_id("operation_transaction", f"{operation}-{workflow_run_id or agent_run_id or utc_now()}")
    trace_payload = _trace_payload(trace, fallback=transaction_id)
    content = {
        "transaction_id": transaction_id,
        "operation": operation,
        "workflow_run_id": workflow_run_id,
        "agent_run_id": agent_run_id,
        "input_assets": _display_paths(storage, input_assets or []),
        "created_assets": _display_paths(storage, created_assets or []),
        "updated_assets": _display_paths(storage, updated_assets or []),
        "previous_versions": _display_paths(storage, previous_versions or []),
        "indexes_touched": [str(item) for item in indexes_touched or []],
        "ledger_paths": _display_paths(storage, ledger_paths or []),
        "rollback_plan": rollback_plan or {},
        "rollback_status": "available",
        "trace": trace_payload,
        "created_at": utc_now(),
    }
    asset = OperationTransaction(
        title=f"Operation transaction: {operation}",
        source=workflow_run_id or agent_run_id or transaction_id,
        tags=["operation-transaction", operation, "available"],
        content=content,
        metadata={"project_id": project_id, "workspace_path": workspace_path},
        references=filter_project_safe_references(storage, project_id, _dedupe([workflow_run_id, agent_run_id, *content["input_assets"], *content["created_assets"], *content["updated_assets"], *content["previous_versions"], *content["ledger_paths"]])),
    )
    result = _write(storage, asset)
    _record_span(storage, trace_payload, "operation_transaction", operation, "succeeded", project_id, workspace_path, {"transaction_path": result["path"]})
    return result


def preview_operation_rollback(
    storage: LocalStorage,
    transaction_path_or_id: str | Path,
    *,
    strategy: str = "supersede_outputs",
    reason: str = "",
    persist: bool = True,
) -> dict[str, Any]:
    transaction_path = _resolve_asset(storage, transaction_path_or_id, "operation_transaction")
    transaction = storage.read_json(transaction_path)
    content = transaction.get("content", {}) if isinstance(transaction.get("content", {}), dict) else {}
    metadata = transaction.get("metadata", {}) if isinstance(transaction.get("metadata", {}), dict) else {}
    actions = _rollback_actions(storage, content, strategy=strategy)
    unsafe_reasons = [action["reason"] for action in actions if action.get("status") == "unsafe"]
    rollback_status = "unsafe" if unsafe_reasons else "available"
    plan_id = make_id("rollback_plan", f"{content.get('transaction_id', '')}-{strategy}")
    plan_content = {
        "plan_id": plan_id,
        "transaction_id": content.get("transaction_id", ""),
        "transaction_path": _display_path(storage.root, transaction_path),
        "operation": content.get("operation", ""),
        "strategy": strategy,
        "reason": reason,
        "actions": actions,
        "unsafe_reasons": unsafe_reasons,
        "rollback_status": rollback_status,
        "created_at": utc_now(),
        "trace": content.get("trace", {}) if isinstance(content.get("trace", {}), dict) else {},
    }
    if not persist:
        return {"path": "", "asset": {"type": "rollback_plan", "content": plan_content}, "actions": actions, "unsafe_reasons": unsafe_reasons}
    asset = RollbackPlan(
        title=f"Rollback plan: {content.get('operation', '')}",
        source=str(content.get("transaction_id", "")),
        tags=["rollback-plan", strategy, rollback_status],
        content=plan_content,
        metadata=metadata,
        references=filter_project_safe_references(storage, str(metadata.get("project_id", "")), _dedupe([_display_path(storage.root, transaction_path), *content.get("created_assets", []), *content.get("updated_assets", [])])),
    )
    result = _write(storage, asset)
    _record_span(storage, plan_content["trace"], "rollback_plan", strategy, "failed" if rollback_status == "unsafe" else "succeeded", str(metadata.get("project_id", "")), str(metadata.get("workspace_path", "")), {"rollback_plan_path": result["path"]})
    return result


def apply_rollback_plan(
    storage: LocalStorage,
    plan_path_or_id: str | Path,
    *,
    confirm: bool = False,
    actor: str = "operation-rollback",
) -> dict[str, Any]:
    plan_path = _resolve_asset(storage, plan_path_or_id, "rollback_plan")
    plan = storage.read_json(plan_path)
    content = plan.get("content", {}) if isinstance(plan.get("content", {}), dict) else {}
    metadata = plan.get("metadata", {}) if isinstance(plan.get("metadata", {}), dict) else {}
    if not confirm:
        raise ValueError("confirm=True is required to apply rollback plan")
    if str(content.get("rollback_status", "")) == "unsafe":
        raise ValueError("rollback plan is unsafe and requires manual reconciliation")
    applied: list[dict[str, Any]] = []
    errors: list[str] = []
    for action in content.get("actions", []) if isinstance(content.get("actions", []), list) else []:
        try:
            applied.append(_apply_action(storage, action, actor=actor))
        except Exception as exc:
            errors.append(f"{action.get('action', 'unknown')}: {exc}")
    status = "failed" if errors else "applied"
    result_id = make_id("rollback_result", f"{content.get('plan_id', '')}-{status}")
    result_content = {
        "result_id": result_id,
        "plan_id": content.get("plan_id", ""),
        "plan_path": _display_path(storage.root, plan_path),
        "transaction_id": content.get("transaction_id", ""),
        "transaction_path": content.get("transaction_path", ""),
        "status": status,
        "applied_actions": applied,
        "errors": errors,
        "created_at": utc_now(),
        "trace": content.get("trace", {}) if isinstance(content.get("trace", {}), dict) else {},
    }
    result_content["verification"] = _verify_applied_actions(storage, applied, errors)
    asset = RollbackResult(
        title=f"Rollback result: {content.get('operation', '')}",
        source=str(content.get("plan_id", "")),
        tags=["rollback-result", status],
        content=result_content,
        metadata=metadata,
        references=filter_project_safe_references(storage, str(metadata.get("project_id", "")), _dedupe([_display_path(storage.root, plan_path), content.get("transaction_path", "")])),
    )
    result = _write(storage, asset)
    _mark_transaction_rolled_back(storage, str(content.get("transaction_path", "")), result["path"], status=status)
    _record_span(storage, result_content["trace"], "rollback_result", status, "failed" if errors else "succeeded", str(metadata.get("project_id", "")), str(metadata.get("workspace_path", "")), {"rollback_result_path": result["path"], "errors": errors})
    return result


def verify_rollback_result(storage: LocalStorage, result_path_or_id: str | Path) -> dict[str, Any]:
    result_path = _resolve_asset(storage, result_path_or_id, "rollback_result")
    result = storage.read_json(result_path)
    content = result.get("content", {}) if isinstance(result.get("content", {}), dict) else {}
    applied = content.get("applied_actions", []) if isinstance(content.get("applied_actions", []), list) else []
    errors = content.get("errors", []) if isinstance(content.get("errors", []), list) else []
    verification = _verify_applied_actions(storage, applied, [str(item) for item in errors])
    content["verification"] = verification
    result["content"] = content
    result["updated_at"] = utc_now()
    storage.write_json(result_path, result)
    return {"path": _display_path(storage.root, result_path), "verification": verification, "asset": result}


def _rollback_actions(storage: LocalStorage, transaction: dict[str, Any], *, strategy: str) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for path in transaction.get("created_assets", []) if isinstance(transaction.get("created_assets", []), list) else []:
        if _path_exists(storage, path):
            actions.append({"action": "mark_asset", "path": path, "asset_status": "superseded" if strategy in {"supersede_outputs", "restore_previous_versions"} else "rolled_back", "rollback_status": "rolled_back", "reason": "created output can be logically rolled back"})
        else:
            actions.append({"action": "mark_asset", "path": path, "status": "unsafe", "reason": f"created asset missing: {path}"})
    for path in transaction.get("updated_assets", []) if isinstance(transaction.get("updated_assets", []), list) else []:
        if _path_exists(storage, path):
            actions.append({"action": "mark_asset", "path": path, "asset_status": "rollback_required", "rollback_status": "rollback_required", "reason": "updated asset requires previous version reconciliation"})
        else:
            actions.append({"action": "mark_asset", "path": path, "status": "unsafe", "reason": f"updated asset missing: {path}"})
    for path in transaction.get("previous_versions", []) if isinstance(transaction.get("previous_versions", []), list) else []:
        if _path_exists(storage, path):
            if strategy == "restore_previous_versions":
                actions.append({"action": "restore_previous_version", "path": path, "asset_status": "active", "content_status": "active", "reason": "previous version will be restored as the active version"})
            else:
                actions.append({"action": "restore_previous_version_marker", "path": path, "asset_status": "active_restore_candidate", "reason": "previous version available for manual or automated restore"})
    for ledger_path in transaction.get("ledger_paths", []) if isinstance(transaction.get("ledger_paths", []), list) else []:
        if _path_exists(storage, ledger_path):
            actions.append({"action": "ledger_compensation", "path": ledger_path, "reason": "write compensating ledger evidence; original ledger remains immutable"})
    for index in transaction.get("indexes_touched", []) if isinstance(transaction.get("indexes_touched", []), list) else []:
        actions.append({"action": "mark_index_dirty", "index": str(index), "reason": "rollback touched indexed story state"})
    return actions


def _apply_action(storage: LocalStorage, action: dict[str, Any], *, actor: str) -> dict[str, Any]:
    name = str(action.get("action", ""))
    if name in {"mark_asset", "restore_previous_version_marker", "restore_previous_version"}:
        path = resolve_path(storage.root, str(action.get("path", "")))
        data = storage.read_json(path)
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        metadata["asset_status"] = action.get("asset_status", metadata.get("asset_status", ""))
        metadata["rollback_status"] = action.get("rollback_status", "restored" if name == "restore_previous_version" else "restore_candidate" if name == "restore_previous_version_marker" else "rolled_back")
        metadata["rollback_actor"] = actor
        metadata["rollback_at"] = utc_now()
        metadata["rollback_reason"] = action.get("reason", "")
        data["metadata"] = metadata
        if name == "restore_previous_version":
            content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
            content["status"] = str(action.get("content_status", "active") or "active")
            content["restored_at"] = utc_now()
            content["restored_by"] = actor
            data["content"] = content
        data["tags"] = _dedupe([*[str(tag) for tag in data.get("tags", [])], str(metadata.get("asset_status", "")), "rollback"])
        data["updated_at"] = utc_now()
        storage.write_json(path, data)
        return {**action, "status": "applied"}
    if name == "ledger_compensation":
        path = resolve_path(storage.root, str(action.get("path", "")))
        data = storage.read_json(path)
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        compensation = record_cost_ledger(
            storage,
            scope=str(content.get("scope", "global")),
            amount=0.0,
            currency=str(content.get("currency", "USD")),
            source_type="rollback_compensation",
            source_id=_display_path(storage.root, path),
            project_id=str(metadata.get("project_id", "")),
            workspace_path=str(metadata.get("workspace_path", "")),
            metadata={"compensates": _display_path(storage.root, path), "adjustment_amount": -float(content.get("amount", 0.0) or 0.0), "reason": action.get("reason", "")},
        )
        return {**action, "status": "applied", "compensation_ledger_path": compensation["path"]}
    if name == "mark_index_dirty":
        marker_path = storage.root / "data" / "indexes" / "rollback_dirty_indexes.json"
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"type": "rollback_dirty_indexes", "updated_at": utc_now(), "entries": []}
        if marker_path.exists():
            try:
                payload = storage.read_json(marker_path)
            except Exception:
                pass
        entries = payload.get("entries", []) if isinstance(payload.get("entries", []), list) else []
        entries.append({"index": action.get("index", ""), "reason": action.get("reason", ""), "updated_at": utc_now()})
        payload["entries"] = entries[-200:]
        storage.write_json(marker_path, payload)
        return {**action, "status": "applied", "marker_path": _display_path(storage.root, marker_path)}
    return {**action, "status": "skipped", "reason": "unknown rollback action"}


def _mark_transaction_rolled_back(storage: LocalStorage, transaction_path: str, result_path: str, *, status: str) -> None:
    if not transaction_path or not _path_exists(storage, transaction_path):
        return
    path = resolve_path(storage.root, transaction_path)
    data = storage.read_json(path)
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    content["rollback_status"] = "applied" if status == "applied" else "failed"
    content["rollback_result_path"] = result_path
    content["rollback_applied_at"] = utc_now()
    data["content"] = content
    data["updated_at"] = utc_now()
    data["tags"] = _dedupe([*[str(tag) for tag in data.get("tags", [])], content["rollback_status"]])
    storage.write_json(path, data)


def _verify_applied_actions(storage: LocalStorage, applied: list[dict[str, Any]], errors: list[str]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    for action in applied:
        name = str(action.get("action", ""))
        status = str(action.get("status", ""))
        if status != "applied":
            checks.append({**action, "verification_status": "skipped", "message": f"action status is {status or 'unknown'}"})
            continue
        if name in {"mark_asset", "restore_previous_version_marker", "restore_previous_version"}:
            checks.append(_verify_asset_marker(storage, action))
        elif name == "ledger_compensation":
            checks.append(_verify_compensation_ledger(storage, action))
        elif name == "mark_index_dirty":
            checks.append(_verify_dirty_index_marker(storage, action))
        else:
            checks.append({**action, "verification_status": "warning", "message": "unknown rollback action type"})
    failed = [item for item in checks if item.get("verification_status") == "failed"]
    warnings = [item for item in checks if item.get("verification_status") == "warning"]
    status = "failed" if errors or failed else "warning" if warnings else "passed"
    return {
        "status": status,
        "check_count": len(checks),
        "failed_count": len(failed),
        "warning_count": len(warnings),
        "checks": checks,
        "errors": errors,
        "recommendation": "manual_reconcile" if status == "failed" else "review" if status == "warning" else "rollback_verified",
    }


def _verify_asset_marker(storage: LocalStorage, action: dict[str, Any]) -> dict[str, Any]:
    path_value = str(action.get("path", ""))
    try:
        data = storage.read_json(resolve_path(storage.root, path_value))
    except Exception as exc:
        return {**action, "verification_status": "failed", "message": f"asset marker unreadable: {exc}"}
    metadata = data.get("metadata", {}) if isinstance(data, dict) and isinstance(data.get("metadata", {}), dict) else {}
    expected = str(action.get("asset_status", ""))
    actual = str(metadata.get("asset_status", ""))
    if expected and actual != expected:
        return {**action, "verification_status": "failed", "message": f"asset_status {actual or 'missing'} != {expected}"}
    expected_content_status = str(action.get("content_status", ""))
    if expected_content_status:
        content = data.get("content", {}) if isinstance(data, dict) and isinstance(data.get("content", {}), dict) else {}
        actual_content_status = str(content.get("status", ""))
        if actual_content_status != expected_content_status:
            return {**action, "verification_status": "failed", "message": f"content.status {actual_content_status or 'missing'} != {expected_content_status}"}
    return {**action, "verification_status": "passed", "message": "asset rollback marker verified"}


def _verify_compensation_ledger(storage: LocalStorage, action: dict[str, Any]) -> dict[str, Any]:
    path_value = str(action.get("compensation_ledger_path", ""))
    if not path_value:
        return {**action, "verification_status": "failed", "message": "missing compensation ledger path"}
    try:
        data = storage.read_json(resolve_path(storage.root, path_value))
    except Exception as exc:
        return {**action, "verification_status": "failed", "message": f"compensation ledger unreadable: {exc}"}
    content = data.get("content", {}) if isinstance(data, dict) and isinstance(data.get("content", {}), dict) else {}
    if data.get("type") != "cost_ledger" or content.get("source_type") != "rollback_compensation":
        return {**action, "verification_status": "failed", "message": "compensation ledger has wrong type or source_type"}
    return {**action, "verification_status": "passed", "message": "compensation ledger verified"}


def _verify_dirty_index_marker(storage: LocalStorage, action: dict[str, Any]) -> dict[str, Any]:
    path_value = str(action.get("marker_path", ""))
    if not path_value or not _path_exists(storage, path_value):
        return {**action, "verification_status": "failed", "message": "dirty index marker missing"}
    return {**action, "verification_status": "passed", "message": "dirty index marker verified"}


def _resolve_asset(storage: LocalStorage, path_or_id: str | Path, expected_type: str) -> Path:
    candidate = resolve_path(storage.root, path_or_id)
    if candidate.exists():
        data = storage.read_json(candidate)
        if isinstance(data, dict) and data.get("type") == expected_type:
            return candidate
    needle = str(path_or_id)
    for path in storage.list_json("runs"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if isinstance(data, dict) and data.get("type") == expected_type and str(data.get("id", "")) == needle:
            return path
    raise FileNotFoundError(f"{expected_type} not found: {path_or_id}")


def _write(storage: LocalStorage, asset: Any) -> dict[str, Any]:
    data = asset.to_dict()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path)}


def _record_span(storage: LocalStorage, trace: dict[str, Any], span_type: str, name: str, status: str, project_id: str, workspace_path: str, attributes: dict[str, Any]) -> None:
    if not trace.get("trace_id"):
        return
    record_trace_span(
        storage,
        trace_id=str(trace.get("trace_id", "")),
        span_type=span_type,
        name=name,
        status=status,
        parent_span_id=str(trace.get("parent_span_id", "") or trace.get("span_id", "")),
        attributes=attributes,
        project_id=project_id,
        workspace_path=workspace_path,
    )


def _trace_payload(trace: dict[str, Any] | None, *, fallback: str) -> dict[str, Any]:
    data = dict(trace or {})
    if not data.get("trace_id"):
        data["trace_id"] = fallback
    if not data.get("span_id"):
        data["span_id"] = make_id("span", fallback)
    if not data.get("parent_span_id"):
        data["parent_span_id"] = data["trace_id"]
    return data


def _display_paths(storage: LocalStorage, paths: list[str | Path]) -> list[str]:
    return [_display_path(storage.root, resolve_path(storage.root, item)) if _path_exists(storage, item) else str(item) for item in paths]


def _path_exists(storage: LocalStorage, path_or_id: str | Path) -> bool:
    if not str(path_or_id or "").strip():
        return False
    try:
        return resolve_path(storage.root, path_or_id).exists()
    except Exception:
        return False


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result
