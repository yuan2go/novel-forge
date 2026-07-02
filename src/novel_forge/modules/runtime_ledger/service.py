from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.modules.production_context import filter_project_safe_references
from novel_forge.schemas import (
    AgentCostSnapshot,
    BudgetPolicy,
    ChapterCostSnapshot,
    CostAlert,
    CostLedger,
    CostQualityDashboard,
    GateResult,
    ModelCallLog,
    ProjectCostSnapshot,
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
        "parent_span_id": parent_span_id or trace_id,
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
        references=filter_project_safe_references(
            storage,
            project_id,
            _dedupe([source_id, trace_payload.get("trace_id", "")] if _is_project_scoped(project_id, workspace_path) else [source_id]),
        ),
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


def trace_timeline_payload(
    storage: LocalStorage,
    *,
    trace_id: str | None = None,
    project_id: str | None = None,
    limit: int = 300,
) -> dict[str, Any]:
    spans = list_trace_timeline(storage, trace_id=trace_id, project_id=project_id, limit=limit)
    return {
        "trace_id": trace_id or "",
        "project_id": project_id or "",
        "spans": spans,
        "summary": _trace_summary(spans),
        "roots": [span for span in spans if not str(span.get("parent_span_id", "")).strip() or str(span.get("parent_span_id", "")) == str(span.get("trace_id", ""))],
    }


def list_cost_ledgers(
    storage: LocalStorage,
    *,
    project_id: str | None = None,
    scope: str | None = None,
    source_type: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    storage.ensure_layout()
    rows: list[dict[str, Any]] = []
    for path in reversed(storage.list_json("runs")):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "cost_ledger":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if project_id and str(metadata.get("project_id", "")) != project_id and str(content.get("scope", "")) != project_id:
            continue
        if scope and str(content.get("scope", "")) != scope:
            continue
        if source_type and str(content.get("source_type", "")) != source_type:
            continue
        rows.append(_cost_ledger_row(storage, path, data))
        if len(rows) >= max(1, int(limit or 500)):
            break
    return list(reversed(rows))


def create_project_cost_snapshot(
    storage: LocalStorage,
    *,
    project_id: str | None = None,
    workspace_path: str | None = None,
    scope: str | None = None,
) -> dict[str, Any]:
    resolved_scope = scope or project_id or "global"
    ledgers = list_cost_ledgers(storage, project_id=project_id, scope=None if project_id else resolved_scope, limit=2000)
    payload = _cost_snapshot_payload(kind="project", scope=resolved_scope, ledgers=ledgers, project_id=project_id or "", workspace_path=workspace_path or "")
    asset = ProjectCostSnapshot(
        title=f"Project cost snapshot: {resolved_scope}",
        source=resolved_scope,
        tags=["cost", "snapshot", "project"],
        content=payload,
        metadata={"project_id": project_id or "", "workspace_path": workspace_path or ""},
        references=filter_project_safe_references(storage, project_id or "", [row["path"] for row in ledgers]),
    )
    return _write_asset(storage, asset)


def create_agent_cost_snapshot(
    storage: LocalStorage,
    *,
    project_id: str | None = None,
    workspace_path: str | None = None,
    agent_run_id: str | None = None,
) -> dict[str, Any]:
    ledgers = list_cost_ledgers(storage, project_id=project_id, limit=2000)
    if agent_run_id:
        ledgers = [row for row in ledgers if str(row.get("source_id", "")).endswith(agent_run_id) or str(row.get("metadata", {}).get("agent_run_id", "")) == agent_run_id]
    by_agent: dict[str, dict[str, Any]] = {}
    for row in ledgers:
        agent_key = str(row.get("metadata", {}).get("agent_key") or row.get("metadata", {}).get("operation") or row.get("source_id") or "unknown")
        bucket = by_agent.setdefault(agent_key, {"agent": agent_key, "total_cost": 0.0, "ledger_count": 0, "model_calls": 0})
        bucket["total_cost"] = round(float(bucket["total_cost"]) + _float(row.get("amount")), 6)
        bucket["ledger_count"] = int(bucket["ledger_count"]) + 1
        if row.get("source_type") == "model_call_log":
            bucket["model_calls"] = int(bucket["model_calls"]) + 1
    payload = _cost_snapshot_payload(kind="agent", scope=agent_run_id or project_id or "global", ledgers=ledgers, project_id=project_id or "", workspace_path=workspace_path or "")
    payload["by_agent"] = sorted(by_agent.values(), key=lambda item: float(item.get("total_cost", 0.0)), reverse=True)
    asset = AgentCostSnapshot(
        title=f"Agent cost snapshot: {payload['scope']}",
        source=str(payload["scope"]),
        tags=["cost", "snapshot", "agent"],
        content=payload,
        metadata={"project_id": project_id or "", "workspace_path": workspace_path or "", "agent_run_id": agent_run_id or ""},
        references=filter_project_safe_references(storage, project_id or "", [row["path"] for row in ledgers]),
    )
    return _write_asset(storage, asset)


def create_chapter_cost_snapshot(
    storage: LocalStorage,
    *,
    project_id: str | None = None,
    workspace_path: str | None = None,
    chapter: int | None = None,
) -> dict[str, Any]:
    ledgers = list_cost_ledgers(storage, project_id=project_id, limit=2000)
    if chapter is not None:
        chapter_text = str(chapter)
        ledgers = [
            row
            for row in ledgers
            if str(row.get("metadata", {}).get("chapter", "")) == chapter_text
            or f"chapter {chapter_text}" in str(row.get("metadata", {}).get("operation", "")).lower()
            or f"chapter-{chapter_text}" in str(row.get("source_id", "")).lower()
        ]
    by_chapter: dict[str, dict[str, Any]] = {}
    for row in ledgers:
        chapter_key = str(row.get("metadata", {}).get("chapter") or chapter or "unknown")
        bucket = by_chapter.setdefault(chapter_key, {"chapter": chapter_key, "total_cost": 0.0, "ledger_count": 0})
        bucket["total_cost"] = round(float(bucket["total_cost"]) + _float(row.get("amount")), 6)
        bucket["ledger_count"] = int(bucket["ledger_count"]) + 1
    payload = _cost_snapshot_payload(kind="chapter", scope=f"{project_id or 'global'}:chapter:{chapter or 'all'}", ledgers=ledgers, project_id=project_id or "", workspace_path=workspace_path or "")
    payload["chapter"] = chapter
    payload["by_chapter"] = sorted(by_chapter.values(), key=lambda item: str(item.get("chapter", "")))
    asset = ChapterCostSnapshot(
        title=f"Chapter cost snapshot: {payload['scope']}",
        source=str(payload["scope"]),
        tags=["cost", "snapshot", "chapter"],
        content=payload,
        metadata={"project_id": project_id or "", "workspace_path": workspace_path or "", "chapter": chapter or ""},
        references=filter_project_safe_references(storage, project_id or "", [row["path"] for row in ledgers]),
    )
    return _write_asset(storage, asset)


def create_cost_quality_dashboard(
    storage: LocalStorage,
    *,
    project_id: str | None = None,
    workspace_path: str | None = None,
    chapter: int | None = None,
    persist_snapshots: bool = True,
    persist_dashboard: bool = True,
) -> dict[str, Any]:
    project_snapshot = create_project_cost_snapshot(storage, project_id=project_id, workspace_path=workspace_path) if persist_snapshots else {"asset": {"content": _cost_snapshot_payload(kind="project", scope=project_id or "global", ledgers=list_cost_ledgers(storage, project_id=project_id, limit=2000), project_id=project_id or "", workspace_path=workspace_path or "")}, "path": ""}
    agent_snapshot = create_agent_cost_snapshot(storage, project_id=project_id, workspace_path=workspace_path) if persist_snapshots else {"asset": {"content": {}}, "path": ""}
    chapter_snapshot = create_chapter_cost_snapshot(storage, project_id=project_id, workspace_path=workspace_path, chapter=chapter) if persist_snapshots else {"asset": {"content": {}}, "path": ""}
    quality = _quality_summary(storage, project_id=project_id)
    project_content = project_snapshot.get("asset", {}).get("content", {}) if isinstance(project_snapshot.get("asset", {}), dict) else {}
    total_cost = _float(project_content.get("total_cost", 0.0))
    quality_score = _float(quality.get("average_score", 0.0))
    dashboard_id = make_id("cost_quality_dashboard", f"{project_id or 'global'}-{utc_now()}")
    summary = {
        "total_cost": total_cost,
        "currency": project_content.get("currency", "USD"),
        "ledger_count": project_content.get("ledger_count", 0),
        "model_call_count": project_content.get("model_call_count", 0),
        "average_quality_score": quality_score,
        "cost_per_quality_point": round(total_cost / quality_score, 6) if quality_score > 0 else 0.0,
        "quality_report_count": quality.get("report_count", 0),
    }
    recommendations = _cost_recommendations(summary, project_content)
    asset = CostQualityDashboard(
        title=f"Cost quality dashboard: {project_id or 'global'}",
        source=project_id or "global",
        tags=["cost", "dashboard", "quality"],
        content={
            "dashboard_id": dashboard_id,
            "scope": project_id or "global",
            "summary": summary,
            "snapshots": {
                "project_cost_snapshot_path": project_snapshot.get("path", ""),
                "agent_cost_snapshot_path": agent_snapshot.get("path", ""),
                "chapter_cost_snapshot_path": chapter_snapshot.get("path", ""),
                "project": project_content,
                "agent": agent_snapshot.get("asset", {}).get("content", {}) if isinstance(agent_snapshot.get("asset", {}), dict) else {},
                "chapter": chapter_snapshot.get("asset", {}).get("content", {}) if isinstance(chapter_snapshot.get("asset", {}), dict) else {},
            },
            "quality": quality,
            "recommendations": recommendations,
            "created_at": utc_now(),
        },
        metadata={"project_id": project_id or "", "workspace_path": workspace_path or ""},
        references=filter_project_safe_references(
            storage,
            project_id or "",
            [str(project_snapshot.get("path", "")), str(agent_snapshot.get("path", "")), str(chapter_snapshot.get("path", ""))],
        ),
    )
    if not persist_dashboard:
        errors = validate_common_fields(asset.to_dict())
        return {"path": "", "id": asset.id, "asset": asset.to_dict(), "validation": {"ok": not errors, "errors": errors}}
    return _write_asset(storage, asset)


def _trace_summary(spans: list[dict[str, Any]]) -> dict[str, Any]:
    by_type: dict[str, int] = {}
    by_status: dict[str, int] = {}
    total_duration_ms = 0.0
    for span in spans:
        span_type = str(span.get("span_type") or "unknown")
        status = str(span.get("status") or "unknown")
        by_type[span_type] = by_type.get(span_type, 0) + 1
        by_status[status] = by_status.get(status, 0) + 1
        total_duration_ms += _duration_ms(str(span.get("started_at", "")), str(span.get("finished_at", "")))
    return {
        "span_count": len(spans),
        "by_type": by_type,
        "by_status": by_status,
        "failed_count": by_status.get("failed", 0),
        "total_duration_ms": round(total_duration_ms, 3),
    }


def _cost_ledger_row(storage: LocalStorage, path: Path, data: dict[str, Any]) -> dict[str, Any]:
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    ledger_metadata = content.get("metadata", {}) if isinstance(content.get("metadata", {}), dict) else {}
    return {
        "path": _display_path(storage.root, path),
        "id": data.get("id", ""),
        "ledger_id": content.get("ledger_id", ""),
        "scope": content.get("scope", ""),
        "amount": _float(content.get("amount", 0.0)),
        "currency": content.get("currency", "USD"),
        "source_type": content.get("source_type", ""),
        "source_id": content.get("source_id", ""),
        "metadata": ledger_metadata,
        "project_id": metadata.get("project_id", ""),
        "workspace_path": metadata.get("workspace_path", ""),
        "created_at": content.get("created_at", ""),
        "trace": content.get("trace", {}) if isinstance(content.get("trace", {}), dict) else {},
    }


def _cost_snapshot_payload(*, kind: str, scope: str, ledgers: list[dict[str, Any]], project_id: str, workspace_path: str) -> dict[str, Any]:
    total = round(sum(_float(row.get("amount", 0.0)) for row in ledgers), 6)
    currency = str(ledgers[0].get("currency", "USD")) if ledgers else "USD"
    by_provider: dict[str, dict[str, Any]] = {}
    by_model: dict[str, dict[str, Any]] = {}
    by_operation: dict[str, dict[str, Any]] = {}
    for row in ledgers:
        meta = row.get("metadata", {}) if isinstance(row.get("metadata", {}), dict) else {}
        _cost_bucket_add(by_provider, str(meta.get("provider") or "unknown"), row)
        _cost_bucket_add(by_model, str(meta.get("model") or "unknown"), row)
        _cost_bucket_add(by_operation, str(meta.get("operation") or row.get("source_type") or "unknown"), row)
    return {
        "snapshot_id": make_id(f"{kind}_cost_snapshot", f"{scope}-{utc_now()}"),
        "snapshot_kind": f"{kind}_cost_snapshot",
        "scope": scope or "global",
        "project_id": project_id,
        "workspace_path": workspace_path,
        "total_cost": total,
        "currency": currency,
        "ledger_count": len(ledgers),
        "model_call_count": sum(1 for row in ledgers if row.get("source_type") == "model_call_log"),
        "by_provider": _sorted_cost_buckets(by_provider),
        "by_model": _sorted_cost_buckets(by_model),
        "by_operation": _sorted_cost_buckets(by_operation),
        "ledger_paths": [row.get("path", "") for row in ledgers],
        "created_at": utc_now(),
    }


def _cost_bucket_add(buckets: dict[str, dict[str, Any]], key: str, row: dict[str, Any]) -> None:
    clean = key or "unknown"
    bucket = buckets.setdefault(clean, {"key": clean, "total_cost": 0.0, "ledger_count": 0})
    bucket["total_cost"] = round(_float(bucket.get("total_cost", 0.0)) + _float(row.get("amount", 0.0)), 6)
    bucket["ledger_count"] = int(bucket.get("ledger_count", 0) or 0) + 1


def _sorted_cost_buckets(buckets: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {key: value for key, value in sorted(buckets.items(), key=lambda item: float(item[1].get("total_cost", 0.0)), reverse=True)}


def _quality_summary(storage: LocalStorage, *, project_id: str | None) -> dict[str, Any]:
    scores: list[float] = []
    report_count = 0
    for category in ["reports", "runs", "quality_standards"]:
        for path in storage.list_json(category):
            try:
                data = storage.read_json(path)
            except Exception:
                continue
            if not isinstance(data, dict) or data.get("type") not in {"quality_score_report", "chapter_audit_report", "review_report", "publish_gate_report"}:
                continue
            metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
            if project_id and str(metadata.get("project_id", "")) != project_id:
                continue
            content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
            score = _quality_score(content)
            if score > 0:
                scores.append(score)
            report_count += 1
    average = round(sum(scores) / len(scores), 3) if scores else 0.0
    return {"average_score": average, "score_count": len(scores), "report_count": report_count}


def _quality_score(content: dict[str, Any]) -> float:
    for key in ["overall_score", "score", "quality_score", "average_score"]:
        value = _float(content.get(key, 0.0))
        if value > 0:
            return value
    scores = content.get("scores", {}) if isinstance(content.get("scores", {}), dict) else {}
    numeric = [_float(value) for value in scores.values() if isinstance(value, (int, float, str)) and _float(value) > 0]
    return sum(numeric) / len(numeric) if numeric else 0.0


def _cost_recommendations(summary: dict[str, Any], project_snapshot: dict[str, Any]) -> list[str]:
    recommendations: list[str] = []
    if _float(summary.get("total_cost", 0.0)) == 0:
        recommendations.append("cost ledger is empty; verify model adapters are recording provider usage")
    if int(summary.get("model_call_count", 0) or 0) == 0:
        recommendations.append("no model_call_log records are tied to this scope")
    if _float(summary.get("average_quality_score", 0.0)) == 0 and _float(summary.get("total_cost", 0.0)) > 0:
        recommendations.append("attach quality_score_report or review gates so cost-quality ratio can be evaluated")
    operations = project_snapshot.get("by_operation", {}) if isinstance(project_snapshot.get("by_operation", {}), dict) else {}
    if len(operations) > 5:
        recommendations.append("review high-cost operations and add routing policies for repeated expensive steps")
    return recommendations or ["cost and quality telemetry are within expected operating bounds"]


def _duration_ms(started_at: str, finished_at: str) -> float:
    start = _parse_datetime(started_at)
    finish = _parse_datetime(finished_at)
    if not start or not finish:
        return 0.0
    return max(0.0, (finish - start).total_seconds() * 1000)


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


def _is_project_scoped(project_id: str, workspace_path: str = "") -> bool:
    return bool((project_id and project_id != "local-system") or (workspace_path and workspace_path != "local-system"))


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
