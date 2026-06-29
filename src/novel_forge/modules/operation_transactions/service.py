from __future__ import annotations

import shutil
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


def coordinate_runtime_rollback(
    storage: LocalStorage,
    *,
    transaction_paths: list[str | Path],
    strategy: str = "physical_restore",
    confirm: bool = False,
    actor: str = "runtime-rollback-coordinator",
    reason: str = "",
    project_id: str = "",
    workspace_path: str = "",
    trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    storage.ensure_layout()
    trace_payload = _trace_payload(trace, fallback=make_id("rollback_coordination", utc_now()))
    ordered_transactions = _ordered_transactions(storage, transaction_paths)
    previews: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    unsafe: list[str] = []
    for item in ordered_transactions:
        preview = preview_operation_rollback(storage, item["path"], strategy=strategy, reason=reason or "coordinated runtime rollback", persist=True)
        previews.append(_compact_rollback_asset(preview))
        content = preview.get("asset", {}).get("content", {}) if isinstance(preview.get("asset", {}).get("content", {}), dict) else {}
        unsafe.extend([str(value) for value in content.get("unsafe_reasons", []) if str(value).strip()])
    if confirm and not unsafe:
        for preview in previews:
            result = apply_rollback_plan(storage, preview["path"], confirm=True, actor=actor)
            results.append(_compact_rollback_asset(result))
    verification = {
        "status": "unsafe" if unsafe else "applied" if confirm else "previewed",
        "unsafe_reasons": unsafe,
        "preview_count": len(previews),
        "result_count": len(results),
        "domains": _rollback_domain_summary(ordered_transactions, previews, results),
    }
    report_id = make_id("rollback_coordination", f"{strategy}-{len(transaction_paths)}-{utc_now()}")
    report = {
        "type": "rollback_coordination_report",
        "id": report_id,
        "title": f"Rollback coordination {strategy}",
        "source": ",".join([str(item) for item in transaction_paths]),
        "tags": ["rollback-coordination", strategy, verification["status"]],
        "content": {
            "report_id": report_id,
            "strategy": strategy,
            "confirm": confirm,
            "actor": actor,
            "reason": reason,
            "transaction_paths": [item["path"] for item in ordered_transactions],
            "execution_order": [item["operation"] for item in ordered_transactions],
            "previews": previews,
            "results": results,
            "verification": verification,
            "trace": trace_payload,
            "created_at": utc_now(),
        },
        "metadata": {"project_id": project_id, "workspace_path": workspace_path},
        "references": _dedupe([*[item["path"] for item in ordered_transactions], *[str(item.get("path", "")) for item in previews], *[str(item.get("path", "")) for item in results]]),
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    path = storage.root / "data" / "runs" / f"{report_id}.json"
    storage.write_json(path, report)
    _record_span(storage, trace_payload, "rollback_coordination", strategy, "failed" if unsafe else "succeeded", project_id, workspace_path, {"report_path": _display_path(storage.root, path), "confirm": confirm, "transaction_count": len(ordered_transactions)})
    return {"path": _display_path(storage.root, path), "asset": report, "verification": verification}


def _rollback_actions(storage: LocalStorage, transaction: dict[str, Any], *, strategy: str) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    transaction_id = str(transaction.get("transaction_id") or make_id("operation_transaction", utc_now()))
    if strategy == "physical_restore":
        previous_versions = transaction.get("previous_versions", []) if isinstance(transaction.get("previous_versions", []), list) else []
        for path in transaction.get("created_assets", []) if isinstance(transaction.get("created_assets", []), list) else []:
            if _path_exists(storage, path):
                actions.append(
                    {
                        "action": "quarantine_asset_file",
                        "path": path,
                        "quarantine_path": _rollback_archive_path(storage, transaction_id, "quarantine", path),
                        "asset_status": "physically_rolled_back",
                        "rollback_status": "quarantined",
                        "reason": "created output will be physically moved out of active asset storage",
                    }
                )
            else:
                actions.append({"action": "quarantine_asset_file", "path": path, "status": "unsafe", "reason": f"created asset missing: {path}"})
        for path in transaction.get("updated_assets", []) if isinstance(transaction.get("updated_assets", []), list) else []:
            if not _path_exists(storage, path):
                actions.append({"action": "restore_asset_file", "path": path, "status": "unsafe", "reason": f"updated asset missing: {path}"})
                continue
            previous_path = _match_previous_version(storage, path, previous_versions)
            if not previous_path:
                actions.append({"action": "restore_asset_file", "path": path, "status": "unsafe", "reason": f"no previous version matched updated asset: {path}"})
                continue
            actions.append(
                {
                    "action": "restore_asset_file",
                    "path": path,
                    "previous_path": previous_path,
                    "backup_path": _rollback_archive_path(storage, transaction_id, "pre_restore_backup", path),
                    "asset_status": "active",
                    "content_status": "active",
                    "reason": "updated asset will be physically restored from a previous version with current file backed up first",
                }
            )
    else:
        actions.extend(_logical_rollback_actions(storage, transaction, strategy=strategy))
    for ledger_path in transaction.get("ledger_paths", []) if isinstance(transaction.get("ledger_paths", []), list) else []:
        if _path_exists(storage, ledger_path):
            actions.append({"action": "ledger_compensation", "path": ledger_path, "reason": "write compensating ledger evidence; original ledger remains immutable"})
    for index in transaction.get("indexes_touched", []) if isinstance(transaction.get("indexes_touched", []), list) else []:
        actions.append({"action": "mark_index_dirty", "index": str(index), "reason": "rollback touched indexed story state"})
    return actions


def _ordered_transactions(storage: LocalStorage, transaction_paths: list[str | Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in transaction_paths:
        path = _resolve_asset(storage, item, "operation_transaction")
        data = storage.read_json(path)
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        rows.append(
            {
                "path": _display_path(storage.root, path),
                "operation": str(content.get("operation", "")),
                "workflow_run_id": str(content.get("workflow_run_id", "")),
                "agent_run_id": str(content.get("agent_run_id", "")),
                "created_assets": content.get("created_assets", []) if isinstance(content.get("created_assets", []), list) else [],
                "updated_assets": content.get("updated_assets", []) if isinstance(content.get("updated_assets", []), list) else [],
                "ledger_paths": content.get("ledger_paths", []) if isinstance(content.get("ledger_paths", []), list) else [],
                "indexes_touched": content.get("indexes_touched", []) if isinstance(content.get("indexes_touched", []), list) else [],
                "created_at": str(content.get("created_at", data.get("created_at", ""))),
            }
        )
    return sorted(rows, key=lambda row: (_rollback_order_weight(row), str(row.get("created_at", ""))), reverse=True)


def _rollback_order_weight(row: dict[str, Any]) -> int:
    weight = 0
    if row.get("workflow_run_id"):
        weight += 40
    if row.get("agent_run_id"):
        weight += 30
    if row.get("created_assets") or row.get("updated_assets"):
        weight += 20
    if row.get("indexes_touched"):
        weight += 10
    if row.get("ledger_paths"):
        weight += 5
    return weight


def _compact_rollback_asset(result: dict[str, Any]) -> dict[str, Any]:
    asset = result.get("asset", {}) if isinstance(result.get("asset", {}), dict) else {}
    content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
    return {
        "path": result.get("path", ""),
        "type": asset.get("type", ""),
        "id": asset.get("id", ""),
        "status": content.get("status", content.get("rollback_status", "")),
        "strategy": content.get("strategy", ""),
        "transaction_id": content.get("transaction_id", ""),
        "action_count": len(content.get("actions", [])) if isinstance(content.get("actions", []), list) else len(content.get("applied_actions", [])) if isinstance(content.get("applied_actions", []), list) else 0,
        "verification": content.get("verification", {}),
        "unsafe_reasons": content.get("unsafe_reasons", []),
    }


def _rollback_domain_summary(transactions: list[dict[str, Any]], previews: list[dict[str, Any]], results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "workflow_transaction_count": len([item for item in transactions if item.get("workflow_run_id")]),
        "agent_transaction_count": len([item for item in transactions if item.get("agent_run_id")]),
        "asset_create_count": sum(len(item.get("created_assets", [])) for item in transactions),
        "asset_update_count": sum(len(item.get("updated_assets", [])) for item in transactions),
        "kg_or_index_touch_count": sum(len(item.get("indexes_touched", [])) for item in transactions),
        "ledger_compensation_count": sum(len(item.get("ledger_paths", [])) for item in transactions),
        "preview_count": len(previews),
        "applied_result_count": len(results),
    }


def _logical_rollback_actions(storage: LocalStorage, transaction: dict[str, Any], *, strategy: str) -> list[dict[str, Any]]:
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
    return actions


def _apply_action(storage: LocalStorage, action: dict[str, Any], *, actor: str) -> dict[str, Any]:
    name = str(action.get("action", ""))
    if name == "quarantine_asset_file":
        path = resolve_path(storage.root, str(action.get("path", "")))
        quarantine = resolve_path(storage.root, str(action.get("quarantine_path", "")))
        quarantine.parent.mkdir(parents=True, exist_ok=True)
        data = storage.read_json(path)
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        metadata["asset_status"] = action.get("asset_status", "physically_rolled_back")
        metadata["rollback_status"] = action.get("rollback_status", "quarantined")
        metadata["rollback_actor"] = actor
        metadata["rollback_at"] = utc_now()
        metadata["rollback_reason"] = action.get("reason", "")
        data["metadata"] = metadata
        data["updated_at"] = utc_now()
        storage.write_json(path, data)
        shutil.move(str(path), str(quarantine))
        return {**action, "status": "applied", "quarantine_path": _display_path(storage.root, quarantine)}
    if name == "restore_asset_file":
        target = resolve_path(storage.root, str(action.get("path", "")))
        previous = resolve_path(storage.root, str(action.get("previous_path", "")))
        backup = resolve_path(storage.root, str(action.get("backup_path", "")))
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup)
        data = storage.read_json(previous)
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        metadata["asset_status"] = action.get("asset_status", "active")
        metadata["rollback_status"] = "physically_restored"
        metadata["rollback_actor"] = actor
        metadata["rollback_at"] = utc_now()
        metadata["rollback_reason"] = action.get("reason", "")
        metadata["rollback_backup_path"] = _display_path(storage.root, backup)
        metadata["rollback_previous_path"] = _display_path(storage.root, previous)
        data["metadata"] = metadata
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if action.get("content_status"):
            content["status"] = str(action.get("content_status"))
        content["restored_at"] = utc_now()
        content["restored_by"] = actor
        data["content"] = content
        data["updated_at"] = utc_now()
        data["tags"] = _dedupe([*[str(tag) for tag in data.get("tags", [])], "physical-rollback", str(metadata.get("asset_status", ""))])
        storage.write_json(target, data)
        return {**action, "status": "applied", "backup_path": _display_path(storage.root, backup)}
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
        elif name == "quarantine_asset_file":
            checks.append(_verify_quarantine_action(storage, action))
        elif name == "restore_asset_file":
            checks.append(_verify_physical_restore_action(storage, action))
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


def _verify_quarantine_action(storage: LocalStorage, action: dict[str, Any]) -> dict[str, Any]:
    active_path = resolve_path(storage.root, str(action.get("path", "")))
    quarantine_path = resolve_path(storage.root, str(action.get("quarantine_path", "")))
    if active_path.exists():
        return {**action, "verification_status": "failed", "message": "active asset still exists after physical quarantine"}
    if not quarantine_path.exists():
        return {**action, "verification_status": "failed", "message": "quarantined asset file missing"}
    try:
        data = storage.read_json(quarantine_path)
    except Exception as exc:
        return {**action, "verification_status": "failed", "message": f"quarantined asset unreadable: {exc}"}
    metadata = data.get("metadata", {}) if isinstance(data, dict) and isinstance(data.get("metadata", {}), dict) else {}
    if str(metadata.get("rollback_status", "")) != str(action.get("rollback_status", "quarantined")):
        return {**action, "verification_status": "failed", "message": "quarantined asset rollback_status mismatch"}
    return {**action, "verification_status": "passed", "message": "asset file physically quarantined"}


def _verify_physical_restore_action(storage: LocalStorage, action: dict[str, Any]) -> dict[str, Any]:
    target = resolve_path(storage.root, str(action.get("path", "")))
    backup = resolve_path(storage.root, str(action.get("backup_path", "")))
    previous = resolve_path(storage.root, str(action.get("previous_path", "")))
    if not target.exists():
        return {**action, "verification_status": "failed", "message": "restored target missing"}
    if not backup.exists():
        return {**action, "verification_status": "failed", "message": "pre-restore backup missing"}
    try:
        target_data = storage.read_json(target)
        previous_data = storage.read_json(previous)
    except Exception as exc:
        return {**action, "verification_status": "failed", "message": f"restore files unreadable: {exc}"}
    if _restore_comparable_content(target_data.get("content", {})) != _restore_comparable_content(previous_data.get("content", {})):
        return {**action, "verification_status": "failed", "message": "target content does not match previous version content"}
    metadata = target_data.get("metadata", {}) if isinstance(target_data.get("metadata", {}), dict) else {}
    if str(metadata.get("rollback_status", "")) != "physically_restored":
        return {**action, "verification_status": "failed", "message": "target rollback_status is not physically_restored"}
    return {**action, "verification_status": "passed", "message": "asset file physically restored from previous version"}


def _restore_comparable_content(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    return {key: item for key, item in value.items() if key not in {"restored_at", "restored_by"}}


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


def _match_previous_version(storage: LocalStorage, updated_path: str, previous_versions: list[str]) -> str:
    if len(previous_versions) == 1 and _path_exists(storage, previous_versions[0]):
        return previous_versions[0]
    try:
        updated = storage.read_json(resolve_path(storage.root, updated_path))
    except Exception:
        return ""
    updated_keys = _asset_identity_keys(updated)
    for previous_path in previous_versions:
        if not _path_exists(storage, previous_path):
            continue
        try:
            previous = storage.read_json(resolve_path(storage.root, previous_path))
        except Exception:
            continue
        if updated_keys & _asset_identity_keys(previous):
            return previous_path
    return ""


def _asset_identity_keys(data: dict[str, Any]) -> set[str]:
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    keys = {
        str(data.get("source", "")),
        str(content.get("source_draft_id", "")),
        str(content.get("draft_id", "")),
        str(content.get("source_outline_id", "")),
        str(content.get("outline_id", "")),
        str(content.get("chapter_plan_id", "")),
    }
    return {key for key in keys if key.strip()}


def _rollback_archive_path(storage: LocalStorage, transaction_id: str, section: str, path_value: str) -> str:
    relative = _safe_relative_for_archive(storage, path_value)
    return _display_path(storage.root, storage.root / "data" / "rollback_archive" / _safe_name(transaction_id) / _safe_name(section) / relative)


def _safe_relative_for_archive(storage: LocalStorage, path_value: str) -> Path:
    try:
        relative = resolve_path(storage.root, path_value).resolve().relative_to(storage.root.resolve())
    except Exception:
        relative = Path(_safe_name(path_value or "asset.json"))
    return Path(*[_safe_name(part) for part in relative.parts])


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in str(value or "").strip())[:160] or "item"


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
