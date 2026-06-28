from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.modules.production_context import filter_project_safe_references
from novel_forge.schemas import (
    BudgetPolicy,
    CostAlert,
    CostLedger,
    GateResult,
    ModelCallLog,
    SchedulerLease,
    TraceSpan,
    validate_common_fields,
)
from novel_forge.storage.local import LocalStorage


def record_trace_span(
    storage: LocalStorage,
    *,
    trace_id: str,
    span_type: str,
    name: str,
    status: str = "succeeded",
    span_id: str = "",
    parent_span_id: str = "",
    started_at: str | None = None,
    finished_at: str | None = None,
    attributes: dict[str, Any] | None = None,
    references: list[str] | None = None,
    project_id: str = "",
    workspace_path: str = "",
) -> dict[str, Any]:
    storage.ensure_layout()
    now = utc_now()
    resolved_span_id = span_id or make_id("span", f"{trace_id}-{span_type}-{name}-{now}")
    resolved_started_at = started_at or now
    content = {
        "trace_id": trace_id,
        "span_id": resolved_span_id,
        "parent_span_id": parent_span_id or "",
        "span_type": span_type,
        "name": name,
        "status": _span_status(status),
        "started_at": resolved_started_at,
        "finished_at": finished_at or (now if _span_status(status) != "running" else ""),
        "attributes": attributes or {},
    }
    asset = TraceSpan(
        title=f"{span_type}: {name}",
        source=trace_id,
        tags=["trace-span", span_type, _span_status(status)],
        content=content,
        metadata={"project_id": project_id, "workspace_path": workspace_path},
        references=filter_project_safe_references(storage, project_id, _dedupe([trace_id, *(references or [])])),
    )
    return _write_asset(storage, asset)


def record_gate_result(
    storage: LocalStorage,
    *,
    gate_kind: str,
    status: str,
    target_paths: list[str | Path],
    result: dict[str, Any] | None = None,
    trace: dict[str, Any] | None = None,
    project_id: str = "",
    workspace_path: str = "",
    message: str = "",
    blocking: bool = True,
) -> dict[str, Any]:
    storage.ensure_layout()
    now = utc_now()
    normalized_targets = [_display_path(storage.root, resolve_path(storage.root, item)) if _path_exists(storage, item) else str(item) for item in target_paths]
    gate_status = _gate_status(status)
    gate_id = make_id("gate", f"{gate_kind}-{gate_status}-{now}")
    trace_payload = _trace_payload(trace)
    content = {
        "gate_id": gate_id,
        "gate_kind": gate_kind,
        "status": gate_status,
        "target_paths": _dedupe(normalized_targets),
        "result": result or {},
        "message": message,
        "blocking": blocking,
        "created_at": now,
        "trace": trace_payload,
    }
    asset = GateResult(
        title=f"{gate_kind} gate {gate_status}",
        source=trace_payload.get("trace_id", "") or gate_id,
        tags=["gate-result", gate_kind, gate_status],
        content=content,
        metadata={"project_id": project_id, "workspace_path": workspace_path},
        references=filter_project_safe_references(storage, project_id, _dedupe([*normalized_targets, trace_payload.get("trace_id", "")])),
    )
    written = _write_asset(storage, asset)
    if trace_payload.get("trace_id"):
        record_trace_span(
            storage,
            trace_id=str(trace_payload.get("trace_id", "")),
            span_id=str(trace_payload.get("span_id", "")) or "",
            parent_span_id=str(trace_payload.get("parent_span_id", "")) or "",
            span_type="gate",
            name=gate_kind,
            status="succeeded" if gate_status in {"passed", "warning", "skipped"} else "failed",
            attributes={"gate_result_path": written.get("path", ""), "message": message, "target_paths": normalized_targets},
            references=[written.get("path", ""), *normalized_targets],
            project_id=project_id,
            workspace_path=workspace_path,
        )
    return written


def record_model_call_log(
    storage: LocalStorage,
    *,
    provider: str,
    model: str,
    operation: str,
    status: str = "succeeded",
    usage: dict[str, Any] | None = None,
    cost: dict[str, Any] | None = None,
    trace: dict[str, Any] | None = None,
    project_id: str = "",
    workspace_path: str = "",
    source_id: str = "",
    prompt_version: str = "",
) -> dict[str, Any]:
    storage.ensure_layout()
    now = utc_now()
    trace_payload = _trace_payload(trace)
    call_id = make_id("model_call", f"{provider}-{model}-{operation}-{now}")
    content = {
        "call_id": call_id,
        "provider": provider or "unknown",
        "model": model or "unknown",
        "operation": operation,
        "status": _model_call_status(status),
        "usage": usage or {},
        "cost": cost or {"amount": 0.0, "currency": "USD"},
        "prompt_version": prompt_version,
        "source_id": source_id,
        "created_at": now,
        "trace": trace_payload,
    }
    asset = ModelCallLog(
        title=f"{provider}/{model}: {operation}",
        source=source_id or trace_payload.get("trace_id", ""),
        tags=["model-call", provider or "unknown", model or "unknown", _model_call_status(status)],
        content=content,
        metadata={"project_id": project_id, "workspace_path": workspace_path},
        references=filter_project_safe_references(storage, project_id, _dedupe([source_id, trace_payload.get("trace_id", "")])),
    )
    written = _write_asset(storage, asset)
    amount = _float((cost or {}).get("amount", 0.0))
    if amount > 0:
        ledger = record_cost_ledger(
            storage,
            scope=project_id or "global",
            amount=amount,
            currency=str((cost or {}).get("currency") or "USD"),
            source_type="model_call_log",
            source_id=written.get("path", ""),
            trace=trace_payload,
            project_id=project_id,
            workspace_path=workspace_path,
            metadata={"provider": provider, "model": model, "operation": operation, "usage": usage or {}},
        )
        written["cost_ledger"] = ledger
    if trace_payload.get("trace_id"):
        record_trace_span(
            storage,
            trace_id=str(trace_payload.get("trace_id", "")),
            span_id=str(trace_payload.get("span_id", "")) or "",
            parent_span_id=str(trace_payload.get("parent_span_id", "")) or "",
            span_type="model_call",
            name=operation,
            status=_span_status(status),
            attributes={"model_call_log_path": written.get("path", ""), "provider": provider, "model": model, "usage": usage or {}, "cost": cost or {}},
            references=[written.get("path", ""), source_id],
            project_id=project_id,
            workspace_path=workspace_path,
        )
    return written


def record_cost_ledger(
    storage: LocalStorage,
    *,
    scope: str,
    amount: float,
    currency: str = "USD",
    source_type: str,
    source_id: str,
    trace: dict[str, Any] | None = None,
    project_id: str = "",
    workspace_path: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    storage.ensure_layout()
    now = utc_now()
    trace_payload = _trace_payload(trace)
    ledger_id = make_id("cost_ledger", f"{scope}-{source_type}-{source_id}-{now}")
    content = {
        "ledger_id": ledger_id,
        "scope": scope or "global",
        "amount": max(0.0, _float(amount)),
        "currency": currency or "USD",
        "source_type": source_type,
        "source_id": source_id,
        "metadata": metadata or {},
        "created_at": now,
        "trace": trace_payload,
    }
    asset = CostLedger(
        title=f"Cost {content['amount']:.6f} {content['currency']}: {source_type}",
        source=source_id,
        tags=["cost-ledger", content["scope"], source_type],
        content=content,
        metadata={"project_id": project_id, "workspace_path": workspace_path},
        references=filter_project_safe_references(storage, project_id, _dedupe([source_id, trace_payload.get("trace_id", "")])),
    )
    written = _write_asset(storage, asset)
    if trace_payload.get("trace_id"):
        record_trace_span(
            storage,
            trace_id=str(trace_payload.get("trace_id", "")),
            span_type="cost",
            name=source_type,
            status="succeeded",
            parent_span_id=str(trace_payload.get("parent_span_id", "") or trace_payload.get("span_id", "")),
            attributes={"cost_ledger_path": written.get("path", ""), "scope": scope, "amount": amount, "currency": currency},
            references=[written.get("path", ""), source_id],
            project_id=project_id,
            workspace_path=workspace_path,
        )
    return written


def create_budget_policy(
    storage: LocalStorage,
    *,
    scope: str,
    limits: dict[str, Any],
    project_id: str | None = None,
    status: str = "active",
    workspace_path: str = "",
) -> dict[str, Any]:
    storage.ensure_layout()
    policy_id = make_id("budget_policy", f"{scope}-{utc_now()}")
    asset = BudgetPolicy(
        title=f"Budget policy: {scope}",
        source=project_id or scope,
        tags=["budget-policy", scope, status],
        content={
            "policy_id": policy_id,
            "scope": scope or project_id or "global",
            "limits": limits,
            "status": status,
            "created_at": utc_now(),
        },
        metadata={"project_id": project_id or "", "workspace_path": workspace_path},
        references=filter_project_safe_references(storage, project_id or "", [project_id or scope]),
    )
    return _write_asset(storage, asset)


def budget_usage(storage: LocalStorage, *, scope: str) -> dict[str, Any]:
    storage.ensure_layout()
    amount_by_currency: dict[str, float] = {}
    source_count = 0
    for path in storage.list_json("runs"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "cost_ledger":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if str(content.get("scope", "")) != scope:
            continue
        currency = str(content.get("currency") or "USD")
        amount_by_currency[currency] = amount_by_currency.get(currency, 0.0) + _float(content.get("amount", 0.0))
        source_count += 1
    return {"scope": scope, "amount_by_currency": amount_by_currency, "ledger_count": source_count}


def check_budget_policy(
    storage: LocalStorage,
    *,
    scope: str,
    amount: float = 0.0,
    token_used: int = 0,
    currency: str = "USD",
    trace: dict[str, Any] | None = None,
    project_id: str = "",
    workspace_path: str = "",
) -> dict[str, Any]:
    policy = _latest_budget_policy(storage, scope=scope)
    if not policy:
        return {"status": "skipped", "scope": scope, "reason": "no active budget policy"}
    policy_path, policy_data = policy
    content = policy_data.get("content", {}) if isinstance(policy_data.get("content", {}), dict) else {}
    limits = content.get("limits", {}) if isinstance(content.get("limits", {}), dict) else {}
    usage = budget_usage(storage, scope=scope)
    current_amount = _float(usage.get("amount_by_currency", {}).get(currency, 0.0) if isinstance(usage.get("amount_by_currency", {}), dict) else 0.0)
    projected_amount = current_amount + max(0.0, _float(amount))
    max_cost = _float(limits.get("max_cost", limits.get(f"max_cost_{currency.lower()}", 0.0)))
    max_tokens = int(limits.get("max_tokens_per_run", 0) or 0)
    failures: list[str] = []
    if max_cost > 0 and projected_amount > max_cost:
        failures.append(f"cost budget exceeded for {scope}: projected {projected_amount:.6f} {currency}, limit {max_cost:.6f}")
    if max_tokens > 0 and int(token_used or 0) > max_tokens:
        failures.append(f"token budget exceeded for {scope}: used {token_used}, limit {max_tokens}")
    status = "failed" if failures else "passed"
    alert = None
    if failures:
        alert = _record_cost_alert(
            storage,
            scope=scope,
            severity="critical",
            message="; ".join(failures),
            trace=trace,
            project_id=project_id,
            workspace_path=workspace_path,
            references=[_display_path(storage.root, policy_path)],
        )
    return {
        "status": status,
        "scope": scope,
        "policy_path": _display_path(storage.root, policy_path),
        "usage": usage,
        "projected": {"amount": projected_amount, "currency": currency, "token_used": token_used},
        "limits": limits,
        "alert": alert,
        "message": "; ".join(failures),
    }


def acquire_scheduler_lease(
    storage: LocalStorage,
    *,
    lease_key: str = "workflow_scheduler",
    owner: str = "",
    ttl_seconds: int = 300,
    force: bool = False,
) -> dict[str, Any]:
    storage.ensure_layout()
    path = _lease_path(storage, lease_key)
    now = _utc_datetime()
    current = _read_json_safe(storage, path)
    current_content = current.get("content", {}) if isinstance(current, dict) and isinstance(current.get("content", {}), dict) else {}
    current_owner = str(current_content.get("owner", ""))
    current_status = str(current_content.get("status", ""))
    expires_at = _parse_datetime(str(current_content.get("expires_at", "")))
    if current_status == "active" and expires_at and expires_at > now and current_owner and current_owner != owner and not force:
        return {"acquired": False, "lease": _lease_row(storage, path, current), "reason": "active_lease"}
    status = "stolen" if current_status == "active" and current_owner and current_owner != owner else "active"
    acquired_at = utc_now()
    lease = SchedulerLease(
        id=make_id("scheduler_lease", lease_key),
        title=f"Scheduler lease: {lease_key}",
        source=lease_key,
        tags=["scheduler-lease", lease_key, "active"],
        content={
            "lease_key": lease_key,
            "owner": owner or make_id("scheduler_owner", utc_now()),
            "status": "active",
            "acquired_at": acquired_at,
            "expires_at": _format_datetime(now + timedelta(seconds=max(1, int(ttl_seconds or 300)))),
            "previous_status": status,
            "last_tick": str(current_content.get("last_tick", "")),
        },
        metadata={"lease_key": lease_key},
    )
    data = lease.to_dict()
    _write_json_validated(storage, path, data)
    return {"acquired": True, "lease": _lease_row(storage, path, data), "reason": status}


def release_scheduler_lease(storage: LocalStorage, *, lease_key: str = "workflow_scheduler", owner: str = "", last_tick: str = "") -> dict[str, Any]:
    storage.ensure_layout()
    path = _lease_path(storage, lease_key)
    data = _read_json_safe(storage, path)
    if not isinstance(data, dict):
        return {"released": False, "reason": "missing_lease"}
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    if owner and str(content.get("owner", "")) and str(content.get("owner", "")) != owner:
        return {"released": False, "reason": "lease_owned_by_another_worker", "lease": _lease_row(storage, path, data)}
    content["status"] = "released"
    content["released_at"] = utc_now()
    if last_tick:
        content["last_tick"] = last_tick
    data["content"] = content
    data["updated_at"] = utc_now()
    data["tags"] = _dedupe([*[str(tag) for tag in data.get("tags", [])], "released"])
    _write_json_validated(storage, path, data)
    return {"released": True, "lease": _lease_row(storage, path, data)}


def scheduler_lease_status(storage: LocalStorage, *, lease_key: str = "workflow_scheduler") -> dict[str, Any]:
    storage.ensure_layout()
    path = _lease_path(storage, lease_key)
    data = _read_json_safe(storage, path)
    if not isinstance(data, dict):
        return {"lease_key": lease_key, "status": "missing", "path": _display_path(storage.root, path)}
    row = _lease_row(storage, path, data)
    expires_at = _parse_datetime(str(row.get("expires_at", "")))
    if row.get("status") == "active" and expires_at and expires_at <= _utc_datetime():
        row["status"] = "expired"
    return row


def list_trace_timeline(storage: LocalStorage, *, trace_id: str | None = None, project_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    storage.ensure_layout()
    rows: list[dict[str, Any]] = []
    for path in reversed(storage.list_json("runs")):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "trace_span":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if trace_id and str(content.get("trace_id", "")) != trace_id:
            continue
        if project_id and str(metadata.get("project_id", "")) != project_id:
            continue
        rows.append(
            {
                "path": _display_path(storage.root, path),
                "id": data.get("id", ""),
                "trace_id": content.get("trace_id", ""),
                "span_id": content.get("span_id", ""),
                "parent_span_id": content.get("parent_span_id", ""),
                "span_type": content.get("span_type", ""),
                "name": content.get("name", ""),
                "status": content.get("status", ""),
                "started_at": content.get("started_at", ""),
                "finished_at": content.get("finished_at", ""),
                "attributes": content.get("attributes", {}),
                "project_id": metadata.get("project_id", ""),
                "workspace_path": metadata.get("workspace_path", ""),
            }
        )
        if len(rows) >= limit:
            break
    return sorted(rows, key=lambda item: str(item.get("started_at", "")))


def _record_cost_alert(
    storage: LocalStorage,
    *,
    scope: str,
    severity: str,
    message: str,
    trace: dict[str, Any] | None,
    project_id: str,
    workspace_path: str,
    references: list[str] | None = None,
) -> dict[str, Any]:
    now = utc_now()
    trace_payload = _trace_payload(trace)
    alert_id = make_id("cost_alert", f"{scope}-{severity}-{now}")
    asset = CostAlert(
        title=f"Cost alert {severity}: {scope}",
        source=scope,
        tags=["cost-alert", scope, severity, "open"],
        content={
            "alert_id": alert_id,
            "scope": scope,
            "severity": severity,
            "message": message,
            "status": "open",
            "created_at": now,
            "trace": trace_payload,
        },
        metadata={"project_id": project_id, "workspace_path": workspace_path},
        references=filter_project_safe_references(storage, project_id, _dedupe([*(references or []), trace_payload.get("trace_id", "")])),
    )
    return _write_asset(storage, asset)


def _latest_budget_policy(storage: LocalStorage, *, scope: str) -> tuple[Path, dict[str, Any]] | None:
    for path in reversed(storage.list_json("runs")):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "budget_policy":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if str(content.get("scope", "")) == scope and str(content.get("status", "")) == "active":
            return path, data
    return None


def _lease_path(storage: LocalStorage, lease_key: str) -> Path:
    safe_key = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in lease_key or "workflow_scheduler")
    return storage.data_dir("runs") / f"{safe_key}-lease.json"


def _lease_row(storage: LocalStorage, path: Path, data: dict[str, Any]) -> dict[str, Any]:
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    return {
        "path": _display_path(storage.root, path),
        "id": data.get("id", ""),
        "lease_key": content.get("lease_key", ""),
        "owner": content.get("owner", ""),
        "status": content.get("status", ""),
        "acquired_at": content.get("acquired_at", ""),
        "expires_at": content.get("expires_at", ""),
        "released_at": content.get("released_at", ""),
        "last_tick": content.get("last_tick", ""),
        "updated_at": data.get("updated_at", ""),
    }


def _write_asset(storage: LocalStorage, asset: Any) -> dict[str, Any]:
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "id": asset.id, "asset": asset.to_dict(), "validation": {"ok": True, "errors": []}}


def _write_json_validated(storage: LocalStorage, path: Path, data: dict[str, Any]) -> None:
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    storage.write_json(path, data)


def _read_json_safe(storage: LocalStorage, path: Path) -> dict[str, Any]:
    try:
        data = storage.read_json(path)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _trace_payload(trace: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(trace, dict):
        return {"trace_id": "", "span_id": "", "parent_span_id": ""}
    return {
        "trace_id": str(trace.get("trace_id", "")),
        "span_id": str(trace.get("span_id", "")),
        "parent_span_id": str(trace.get("parent_span_id", "")),
    }


def _span_status(status: str) -> str:
    value = str(status or "").lower()
    if value in {"succeeded", "passed", "within_sla"}:
        return "succeeded"
    if value in {"failed", "breached", "exceeded"}:
        return "failed"
    if value in {"cancelled", "skipped", "running"}:
        return value
    return "succeeded"


def _gate_status(status: str) -> str:
    value = str(status or "").lower()
    if value in {"passed", "failed", "warning", "skipped"}:
        return value
    if value in {"succeeded", "accepted", "approved"}:
        return "passed"
    if value in {"blocked", "rejected"}:
        return "failed"
    return "failed"


def _model_call_status(status: str) -> str:
    value = str(status or "").lower()
    if value in {"succeeded", "failed", "skipped"}:
        return value
    if value in {"passed", "within_budget"}:
        return "succeeded"
    return "failed" if value in {"error", "exceeded"} else "succeeded"


def _path_exists(storage: LocalStorage, value: str | Path) -> bool:
    try:
        return resolve_path(storage.root, value).exists()
    except Exception:
        return False


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _utc_datetime() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _format_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
