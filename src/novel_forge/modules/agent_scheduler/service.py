from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.agent_runs import (
    create_agent_failure_report,
    execute_agent_run_once,
    record_agent_checkpoint,
    record_agent_event,
    update_agent_run_status,
)
from novel_forge.modules.common import resolve_path
from novel_forge.modules.production_context import filter_project_safe_references
from novel_forge.modules.runtime_ledger import acquire_scheduler_lease, release_scheduler_lease, scheduler_lease_status
from novel_forge.schemas import AgentDispatchQueue, validate_common_fields
from novel_forge.storage.local import LocalStorage

QUEUE_STATUSES = {"queued", "claimed", "running", "waiting_human", "acked", "retry_scheduled", "dead_letter", "cancelled"}
CLAIMABLE_STATUSES = {"queued", "retry_scheduled", "claimed"}
TERMINAL_QUEUE_STATUSES = {"acked", "dead_letter", "cancelled"}
OperationRunner = Callable[[LocalStorage, dict[str, Any], dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class AgentOperationSpec:
    operation: str
    aliases: tuple[str, ...]
    runner: OperationRunner
    agent_key: str
    input_types: tuple[str, ...]
    output_types: tuple[str, ...]
    required_tool: str
    checkpoint_strategy: str = "service_result"
    sla_seconds: int = 1800


@dataclass(frozen=True)
class AgentOperationContract:
    operation: str
    agent_key: str = ""
    runner_kind: str = "output_reuse"
    input_types: list[str] = field(default_factory=list)
    output_types: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)
    checkpoint_schema: dict[str, Any] = field(default_factory=dict)
    resume_supported: bool = True
    rollback_strategy: str = "agent_rollback_report"
    gates: list[str] = field(default_factory=lambda: ["permission", "schema", "budget", "sla"])
    sla_seconds: int = 1800

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "agent_key": self.agent_key,
            "runner_kind": self.runner_kind,
            "input_types": self.input_types,
            "output_types": self.output_types,
            "required_tools": self.required_tools,
            "checkpoint_schema": self.checkpoint_schema,
            "resume_supported": self.resume_supported,
            "rollback_strategy": self.rollback_strategy,
            "gates": self.gates,
            "sla_seconds": self.sla_seconds,
        }


class AgentOperationRegistry:
    def __init__(self) -> None:
        self._runner_map: dict[str, OperationRunner] | None = None
        self._spec_map: dict[str, AgentOperationSpec] | None = None

    @property
    def runners(self) -> dict[str, OperationRunner]:
        if self._runner_map is None:
            self._runner_map = _operation_runners()
        return self._runner_map

    @property
    def specs(self) -> dict[str, AgentOperationSpec]:
        if self._spec_map is None:
            self._spec_map = _operation_specs_by_alias()
        return self._spec_map

    def list_contracts(self) -> list[dict[str, Any]]:
        contracts = [
            AgentOperationContract(
                operation=spec.operation,
                agent_key=spec.agent_key,
                runner_kind="local_service",
                input_types=list(spec.input_types),
                output_types=list(spec.output_types),
                required_tools=[spec.required_tool],
                checkpoint_schema={"version": "0.1.0", "strategy": spec.checkpoint_strategy},
                resume_supported=True,
                rollback_strategy="service_checkpoint_or_agent_rollback_report",
                sla_seconds=spec.sla_seconds,
            ).to_dict()
            for spec in sorted({item.operation: item for item in self.specs.values()}.values(), key=lambda item: item.operation)
        ]
        contracts.append(
            AgentOperationContract(
                operation="*",
                runner_kind="output_reuse",
                required_tools=["read_asset", "run_validation"],
                checkpoint_schema={"version": "0.1.0", "strategy": "output_reuse"},
                resume_supported=True,
            ).to_dict()
        )
        return contracts

    def contract_for_run(self, agent_run: dict[str, Any], contract_asset: dict[str, Any] | None = None) -> AgentOperationContract:
        content = agent_run.get("content", {}) if isinstance(agent_run.get("content", {}), dict) else {}
        metadata = agent_run.get("metadata", {}) if isinstance(agent_run.get("metadata", {}), dict) else {}
        contract_content = contract_asset.get("content", {}) if isinstance(contract_asset, dict) and isinstance(contract_asset.get("content", {}), dict) else {}
        output_types = [str(item) for item in contract_content.get("output_types", []) if str(item).strip()] if isinstance(contract_content.get("output_types", []), list) else []
        permissions = content.get("permissions", {}) if isinstance(content.get("permissions", {}), dict) else {}
        canonical = _canonical_operation(str(content.get("operation", "")))
        spec = self.specs.get(canonical)
        runner_kind = "local_service" if canonical in self.runners else "output_reuse"
        resolved_output_types = output_types or (list(spec.output_types) if spec else [])
        required_tools = [spec.required_tool] if spec else ([_tool_name_for_output(resolved_output_types)] if resolved_output_types else [str((permissions.get("tool_allowlist") or ["run_validation"])[0])])
        return AgentOperationContract(
            operation=str(content.get("operation", "")),
            agent_key=str(metadata.get("agent_key", "") or (spec.agent_key if spec else "")),
            runner_kind=runner_kind,
            input_types=[str(item) for item in contract_content.get("input_types", []) if str(item).strip()] if isinstance(contract_content.get("input_types", []), list) else [],
            output_types=resolved_output_types,
            required_tools=required_tools,
            checkpoint_schema={"version": "0.1.0", "strategy": runner_kind},
            sla_seconds=spec.sla_seconds if spec else 1800,
        )

    def execute(self, storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
        queue_content = queue_item.get("content", {}) if isinstance(queue_item.get("content", {}), dict) else {}
        run_content = agent_run.get("content", {}) if isinstance(agent_run.get("content", {}), dict) else {}
        evidence = run_content.get("evidence", {}) if isinstance(run_content.get("evidence", {}), dict) else {}
        expected_outputs = _dedupe(
            [
                *_string_list(queue_content.get("expected_output_assets", [])),
                *_string_list(evidence.get("expected_output_assets", [])),
            ]
        )
        existing_outputs = [item for item in expected_outputs if _path_exists(storage, item)]
        output_rows = run_content.get("output_assets", []) if isinstance(run_content.get("output_assets", []), list) else []
        existing_outputs.extend([str(row.get("path", "")) for row in output_rows if isinstance(row, dict) and row.get("path")])
        existing_outputs = _dedupe(existing_outputs)
        checkpoint = {
            "status": "agent_scheduler_output_reuse",
            "dispatch_id": queue_content.get("dispatch_id", ""),
            "idempotency_key": queue_content.get("idempotency_key", ""),
            "expected_output_assets": expected_outputs,
            "output_assets": existing_outputs,
        }
        if existing_outputs:
            return {
                "status": "succeeded",
                "output_assets": existing_outputs,
                "token_used": int(queue_content.get("token_used", evidence.get("token_used", 0)) or 0),
                "cost_estimate": float(queue_content.get("cost_estimate", evidence.get("cost_estimate", 0.0)) or 0.0),
                "checkpoint": checkpoint,
                "evidence": {
                    "agent_scheduler": "output_reuse",
                    "dispatch_queue_path": _display_path(storage.root, _queue_path(storage, str(queue_content.get("dispatch_id", "")))),
                    "provider_usage": evidence.get("provider_usage", {}) if isinstance(evidence.get("provider_usage", {}), dict) else {},
                    "provider_runtime_guard": evidence.get("provider_runtime_guard", {}) if isinstance(evidence.get("provider_runtime_guard", {}), dict) else {},
                },
            }
        canonical = _canonical_operation(str(run_content.get("operation", queue_content.get("operation", ""))))
        runner = self.runners.get(canonical)
        if runner:
            service_result = runner(storage, queue_item, agent_run)
            output_assets = _dedupe(_paths_from_result(storage, service_result))
            if not output_assets:
                raise RuntimeError(f"agent operation {canonical} completed without output assets")
            token_used = int(service_result.get("token_used", 0) or sum(len(str(item)) for item in output_assets))
            return {
                "status": "succeeded",
                "output_assets": output_assets,
                "token_used": token_used,
                "cost_estimate": float(service_result.get("cost_estimate", 0.0) or 0.0),
                "checkpoint": {
                    **checkpoint,
                    "status": "agent_scheduler_service_completed",
                    "operation": canonical,
                    "runner_kind": "local_service",
                    "service_result": _json_safe_result(service_result),
                    "output_assets": output_assets,
                },
                "evidence": {
                    "agent_scheduler": "local_service",
                    "agent_operation": canonical,
                    "dispatch_queue_path": _display_path(storage.root, _queue_path(storage, str(queue_content.get("dispatch_id", "")))),
                    "service_result": _json_safe_result(service_result),
                    "provider_usage": evidence.get("provider_usage", {}) if isinstance(evidence.get("provider_usage", {}), dict) else {},
                    "provider_runtime_guard": evidence.get("provider_runtime_guard", {}) if isinstance(evidence.get("provider_runtime_guard", {}), dict) else {},
                },
            }
        return {
            "status": "waiting_human",
            "message": "agent scheduler has no verified output assets for this prepared AgentRun",
            "checkpoint": checkpoint,
        }


OPERATION_REGISTRY = AgentOperationRegistry()


def ensure_agent_dispatch_queue(
    storage: LocalStorage,
    *,
    agent_run_path: str | Path,
    workflow_run_id: str = "",
    workflow_run_path: str = "",
    workflow_node_id: str = "",
    expected_output_assets: list[str | Path] | None = None,
    token_used: int = 0,
    cost_estimate: float = 0.0,
    max_attempts: int = 3,
    priority: int = 100,
    trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    storage.ensure_layout()
    run_path = _resolve_agent_run(storage, agent_run_path)
    run = storage.read_json(run_path)
    if not isinstance(run, dict) or run.get("type") != "agent_run":
        raise ValueError(f"agent_run JSON must be an object: {run_path}")
    content = run.get("content", {}) if isinstance(run.get("content", {}), dict) else {}
    metadata = run.get("metadata", {}) if isinstance(run.get("metadata", {}), dict) else {}
    evidence = content.get("evidence", {}) if isinstance(content.get("evidence", {}), dict) else {}
    resolved_workflow_run_id = workflow_run_id or str(evidence.get("workflow_run_id", ""))
    resolved_node_id = workflow_node_id or str(evidence.get("workflow_node_id", ""))
    resolved_contract_id = str(content.get("contract_id", ""))
    idempotency_key = ":".join([resolved_workflow_run_id, resolved_node_id, str(content.get("run_id", "")), resolved_contract_id])
    dispatch_id = _dispatch_id_from_key(idempotency_key)
    path = _queue_path(storage, dispatch_id)
    existing = _read_json_safe(storage, path)
    if isinstance(existing, dict) and existing.get("type") == "agent_dispatch_queue":
        existing_content = existing.get("content", {}) if isinstance(existing.get("content", {}), dict) else {}
        merged_outputs = _dedupe(
            [
                *_string_list(existing_content.get("expected_output_assets", [])),
                *[str(item) for item in expected_output_assets or [] if str(item).strip()],
            ]
        )
        existing_content.update(
            {
                "workflow_run_path": workflow_run_path or existing_content.get("workflow_run_path", ""),
                "expected_output_assets": merged_outputs,
                "token_used": int(token_used or existing_content.get("token_used", 0) or 0),
                "cost_estimate": float(cost_estimate or existing_content.get("cost_estimate", 0.0) or 0.0),
                "updated_at": utc_now(),
            }
        )
        existing["content"] = existing_content
        existing["updated_at"] = utc_now()
        _write_json_validated(storage, path, existing)
        return _queue_row(storage, path, existing)
    trace_payload = _trace_payload(trace or evidence.get("trace", content.get("trace", {})))
    expected = _dedupe(
        [
            *[str(item) for item in expected_output_assets or [] if str(item).strip()],
            *_string_list(evidence.get("expected_output_assets", [])),
        ]
    )
    asset = AgentDispatchQueue(
        id=dispatch_id,
        title=f"Agent dispatch: {content.get('operation', '')}",
        source=str(content.get("run_id", "")),
        tags=["agent-dispatch-queue", "queued", str(content.get("operation", ""))],
        content={
            "dispatch_id": dispatch_id,
            "idempotency_key": idempotency_key,
            "status": "queued",
            "agent_run_id": content.get("run_id", ""),
            "agent_run_path": _display_path(storage.root, run_path),
            "agent_contract_path": content.get("contract_path", ""),
            "workflow_run_id": resolved_workflow_run_id,
            "workflow_run_path": workflow_run_path or str(evidence.get("workflow_run_path", "")),
            "workflow_node_id": resolved_node_id,
            "operation": content.get("operation", ""),
            "agent_key": metadata.get("agent_key", ""),
            "priority": max(0, int(priority or 100)),
            "attempt_count": 0,
            "max_attempts": max(1, int(max_attempts or 3)),
            "available_at": utc_now(),
            "lease_owner": "",
            "lease_expires_at": "",
            "claimed_at": "",
            "acked_at": "",
            "dead_lettered_at": "",
            "last_error": "",
            "checkpoint_path": "",
            "result": {},
            "expected_output_assets": expected,
            "token_used": int(token_used or evidence.get("token_used", 0) or 0),
            "cost_estimate": float(cost_estimate or evidence.get("cost_estimate", 0.0) or 0.0),
            "trace": trace_payload,
        },
        metadata={"project_id": metadata.get("project_id", ""), "workspace_path": metadata.get("workspace_path", ""), "agent_run_id": content.get("run_id", "")},
        references=filter_project_safe_references(
            storage,
            str(metadata.get("project_id", "")),
            _dedupe([_display_path(storage.root, run_path), content.get("contract_path", ""), workflow_run_path or str(evidence.get("workflow_run_path", "")), *expected]),
        ),
    )
    data = asset.to_dict()
    _write_json_validated(storage, path, data)
    record_agent_event(
        storage,
        agent_run_path=_display_path(storage.root, run_path),
        event_type="agent_dispatch.queued",
        status="prepared",
        message="AgentRun queued for scheduler dispatch",
        payload={"dispatch_queue_path": _display_path(storage.root, path), "workflow_run_id": resolved_workflow_run_id, "workflow_node_id": resolved_node_id},
    )
    return _queue_row(storage, path, data)


def dispatch_agent_run(storage: LocalStorage, *, agent_run_path: str | Path, **kwargs: Any) -> dict[str, Any]:
    return ensure_agent_dispatch_queue(storage, agent_run_path=agent_run_path, **kwargs)


def list_agent_dispatch_queue(
    storage: LocalStorage,
    *,
    project_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    storage.ensure_layout()
    rows: list[dict[str, Any]] = []
    for path in reversed(storage.list_json("runs")):
        data = _read_json_safe(storage, path)
        if not isinstance(data, dict) or data.get("type") != "agent_dispatch_queue":
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if project_id and str(metadata.get("project_id", "")) != project_id:
            continue
        if status and str(content.get("status", "")) != status:
            continue
        rows.append(_queue_row(storage, path, data))
        if len(rows) >= max(1, int(limit or 100)):
            break
    return rows


def scheduler_status(storage: LocalStorage) -> dict[str, Any]:
    queue = list_agent_dispatch_queue(storage, limit=500)
    by_status: dict[str, int] = {}
    for row in queue:
        by_status[str(row.get("status", ""))] = by_status.get(str(row.get("status", "")), 0) + 1
    return {"lease": scheduler_lease_status(storage, lease_key="agent_scheduler"), "queue_count": len(queue), "by_status": by_status}


def list_agent_operation_contracts() -> list[dict[str, Any]]:
    return OPERATION_REGISTRY.list_contracts()


def run_agent_scheduler_tick(
    storage: LocalStorage,
    *,
    project_id: str | None = None,
    limit: int = 20,
    lease_owner: str = "",
    lease_ttl_seconds: int = 300,
    force_lease: bool = False,
    retry_delay_seconds: int = 0,
    dry_run: bool = False,
) -> dict[str, Any]:
    storage.ensure_layout()
    tick_id = make_id("agent_scheduler_tick", utc_now())
    owner = lease_owner or tick_id
    lease = acquire_scheduler_lease(storage, lease_key="agent_scheduler", owner=owner, ttl_seconds=lease_ttl_seconds, force=force_lease)
    if not lease.get("acquired"):
        return {"scheduler_tick_id": tick_id, "status": "skipped", "reason": "agent_scheduler_lease_active", "lease": lease, "claimed": [], "acked": [], "waiting_human": [], "retried": [], "dead_lettered": [], "errors": []}
    materialized = _materialize_prepared_agent_runs(storage, project_id=project_id, limit=limit)
    candidates = _claimable_queue_candidates(storage, project_id=project_id, limit=limit)
    if dry_run:
        release = release_scheduler_lease(storage, lease_key="agent_scheduler", owner=owner, last_tick=tick_id)
        return {"scheduler_tick_id": tick_id, "status": "completed", "dry_run": True, "lease": release.get("lease", lease.get("lease", {})), "materialized": materialized, "candidate_count": len(candidates), "claimed": [], "acked": [], "waiting_human": [], "retried": [], "dead_lettered": [], "errors": []}
    claimed: list[dict[str, Any]] = []
    acked: list[dict[str, Any]] = []
    waiting_human: list[dict[str, Any]] = []
    retried: list[dict[str, Any]] = []
    dead_lettered: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for row in candidates:
        claim = _claim_queue_item(storage, row["path"], owner=owner, ttl_seconds=lease_ttl_seconds)
        if not claim.get("claimed"):
            continue
        claimed.append(claim["queue"])
        try:
            result = _run_claimed_dispatch(storage, claim["queue"], retry_delay_seconds=retry_delay_seconds)
            if result.get("queue_status") == "acked":
                acked.append(result)
            elif result.get("queue_status") == "waiting_human":
                waiting_human.append(result)
            elif result.get("queue_status") == "retry_scheduled":
                retried.append(result)
            elif result.get("queue_status") == "dead_letter":
                dead_lettered.append(result)
        except Exception as exc:
            errors.append({"queue_path": row["path"], "error": f"{type(exc).__name__}: {exc}"})
            _fail_queue_item(storage, row["path"], reason=f"{type(exc).__name__}: {exc}", retry_delay_seconds=retry_delay_seconds)
    release = release_scheduler_lease(storage, lease_key="agent_scheduler", owner=owner, last_tick=tick_id)
    status = "failed" if errors else "completed"
    return {
        "scheduler_tick_id": tick_id,
        "status": status,
        "lease": release.get("lease", lease.get("lease", {})) if isinstance(release, dict) else lease.get("lease", {}),
        "materialized": materialized,
        "candidate_count": len(candidates),
        "claimed_count": len(claimed),
        "acked_count": len(acked),
        "waiting_human_count": len(waiting_human),
        "retry_count": len(retried),
        "dead_letter_count": len(dead_lettered),
        "error_count": len(errors),
        "claimed": claimed,
        "acked": acked,
        "waiting_human": waiting_human,
        "retried": retried,
        "dead_lettered": dead_lettered,
        "errors": errors,
    }


def run_agent_scheduler_loop(
    storage: LocalStorage,
    *,
    project_id: str | None = None,
    limit: int = 20,
    iterations: int = 1,
    interval_seconds: float = 0.0,
    stop_when_idle: bool = True,
    lease_owner: str = "",
    lease_ttl_seconds: int = 300,
    force_lease: bool = False,
    retry_delay_seconds: int = 0,
) -> dict[str, Any]:
    loop_id = make_id("agent_scheduler_loop", utc_now())
    ticks: list[dict[str, Any]] = []
    for index in range(max(1, int(iterations or 1))):
        tick = run_agent_scheduler_tick(
            storage,
            project_id=project_id,
            limit=limit,
            lease_owner=lease_owner or loop_id,
            lease_ttl_seconds=lease_ttl_seconds,
            force_lease=force_lease,
            retry_delay_seconds=retry_delay_seconds,
        )
        tick["iteration"] = index + 1
        ticks.append(tick)
        if stop_when_idle and int(tick.get("candidate_count", 0) or 0) == 0:
            break
        if index + 1 < max(1, int(iterations or 1)) and interval_seconds > 0:
            time.sleep(min(float(interval_seconds), 60.0))
    errors = [item for tick in ticks for item in tick.get("errors", []) if isinstance(item, dict)]
    return {
        "scheduler_loop_id": loop_id,
        "status": "failed" if errors else "completed",
        "tick_count": len(ticks),
        "ticks": ticks,
        "latest_tick": ticks[-1] if ticks else {},
        "acked_count": sum(int(tick.get("acked_count", 0) or 0) for tick in ticks),
        "waiting_human_count": sum(int(tick.get("waiting_human_count", 0) or 0) for tick in ticks),
        "retry_count": sum(int(tick.get("retry_count", 0) or 0) for tick in ticks),
        "dead_letter_count": sum(int(tick.get("dead_letter_count", 0) or 0) for tick in ticks),
        "error_count": len(errors),
        "errors": errors,
    }


def recover_agent_dispatch(storage: LocalStorage, *, queue_path: str | Path, reason: str = "manual recovery") -> dict[str, Any]:
    path = _resolve_queue(storage, queue_path)
    data = _read_json_safe(storage, path)
    if not isinstance(data, dict) or data.get("type") != "agent_dispatch_queue":
        raise ValueError(f"agent_dispatch_queue JSON must be an object: {path}")
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    if str(content.get("status", "")) not in {"dead_letter", "retry_scheduled", "waiting_human", "claimed"}:
        raise ValueError("agent_dispatch_queue is not recoverable")
    content.update(
        {
            "status": "queued",
            "available_at": utc_now(),
            "lease_owner": "",
            "lease_expires_at": "",
            "last_error": "",
            "recovered_at": utc_now(),
            "recovery_reason": reason,
        }
    )
    data["content"] = content
    data["updated_at"] = utc_now()
    data["tags"] = _dedupe([*[str(tag) for tag in data.get("tags", [])], "queued", "recovered"])
    _write_json_validated(storage, path, data)
    try:
        update_agent_run_status(storage, str(content.get("agent_run_path", "")), status="prepared", event_type="agent_dispatch.recovered", message=reason)
    except Exception:
        pass
    return _queue_row(storage, path, data)


def _materialize_prepared_agent_runs(storage: LocalStorage, *, project_id: str | None, limit: int) -> list[dict[str, Any]]:
    materialized: list[dict[str, Any]] = []
    for path in reversed(storage.list_json("runs")):
        data = _read_json_safe(storage, path)
        if not isinstance(data, dict) or data.get("type") != "agent_run":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if str(content.get("status", "")) != "prepared":
            continue
        if project_id and str(metadata.get("project_id", "")) != project_id:
            continue
        evidence = content.get("evidence", {}) if isinstance(content.get("evidence", {}), dict) else {}
        if not evidence.get("workflow_run_id") and not evidence.get("workflow_node_id"):
            continue
        row = ensure_agent_dispatch_queue(
            storage,
            agent_run_path=_display_path(storage.root, path),
            workflow_run_id=str(evidence.get("workflow_run_id", "")),
            workflow_run_path=str(evidence.get("workflow_run_path", "")),
            workflow_node_id=str(evidence.get("workflow_node_id", "")),
            expected_output_assets=[str(item) for item in evidence.get("expected_output_assets", [])] if isinstance(evidence.get("expected_output_assets", []), list) else [],
            token_used=int(evidence.get("token_used", 0) or 0),
            cost_estimate=float(evidence.get("cost_estimate", 0.0) or 0.0),
        )
        materialized.append(row)
        if len(materialized) >= max(1, int(limit or 20)):
            break
    return materialized


def _claimable_queue_candidates(storage: LocalStorage, *, project_id: str | None, limit: int) -> list[dict[str, Any]]:
    rows = list_agent_dispatch_queue(storage, project_id=project_id, limit=500)
    candidates: list[dict[str, Any]] = []
    now = _utc_now_dt()
    for row in sorted(rows, key=lambda item: (int(item.get("priority", 100) or 100), str(item.get("created_at", "")))):
        status = str(row.get("status", ""))
        if status not in CLAIMABLE_STATUSES:
            continue
        if status == "claimed" and not _queue_lease_expired(row):
            continue
        available_at = _parse_utc_datetime(str(row.get("available_at", "") or ""))
        if available_at and available_at > now:
            continue
        candidates.append(row)
        if len(candidates) >= max(1, int(limit or 20)):
            break
    return candidates


def _claim_queue_item(storage: LocalStorage, queue_path: str | Path, *, owner: str, ttl_seconds: int) -> dict[str, Any]:
    path = _resolve_queue(storage, queue_path)
    data = _read_json_safe(storage, path)
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    status = str(content.get("status", ""))
    if status in TERMINAL_QUEUE_STATUSES or status == "waiting_human":
        return {"claimed": False, "reason": f"queue status is {status}", "queue": _queue_row(storage, path, data)}
    if status == "claimed" and not _queue_lease_expired(content) and str(content.get("lease_owner", "")) != owner:
        return {"claimed": False, "reason": "claimed_by_another_worker", "queue": _queue_row(storage, path, data)}
    content.update(
        {
            "status": "claimed",
            "attempt_count": int(content.get("attempt_count", 0) or 0) + 1,
            "lease_owner": owner,
            "lease_expires_at": _utc_datetime_after(ttl_seconds),
            "claimed_at": utc_now(),
        }
    )
    data["content"] = content
    data["updated_at"] = utc_now()
    data["tags"] = _dedupe([*[str(tag) for tag in data.get("tags", [])], "claimed"])
    _write_json_validated(storage, path, data)
    return {"claimed": True, "queue": _queue_row(storage, path, data)}


def _run_claimed_dispatch(storage: LocalStorage, queue_row: dict[str, Any], *, retry_delay_seconds: int) -> dict[str, Any]:
    queue_path = _resolve_queue(storage, str(queue_row.get("path", "")))
    queue_data = _read_json_safe(storage, queue_path)
    queue_content = queue_data.get("content", {}) if isinstance(queue_data.get("content", {}), dict) else {}
    agent_run_path = str(queue_content.get("agent_run_path", ""))
    run_path = _resolve_agent_run(storage, agent_run_path)
    run = storage.read_json(run_path)
    if not isinstance(run, dict) or run.get("type") != "agent_run":
        raise ValueError(f"agent_run JSON must be an object: {run_path}")
    run_content = run.get("content", {}) if isinstance(run.get("content", {}), dict) else {}
    if str(run_content.get("status", "")) in {"failed", "dead_letter", "waiting_human", "recovered"}:
        update_agent_run_status(storage, _display_path(storage.root, run_path), status="prepared", event_type="agent_dispatch.prepare_retry", message="Agent scheduler retry prepared the run")
    update_agent_run_status(storage, _display_path(storage.root, run_path), status="running", event_type="agent_dispatch.claimed", message="Agent scheduler claimed the run")
    contract_path = str(queue_content.get("agent_contract_path", "") or run_content.get("contract_path", ""))
    contract_asset = _read_json_safe(storage, resolve_path(storage.root, contract_path)) if contract_path else {}
    contract = OPERATION_REGISTRY.contract_for_run(run, contract_asset)
    operation_result = OPERATION_REGISTRY.execute(storage, queue_data, run)
    if operation_result.get("status") == "waiting_human":
        checkpoint = record_agent_checkpoint(
            storage,
            agent_run_path=_display_path(storage.root, run_path),
            status="agent_scheduler_waiting_human",
            state=operation_result.get("checkpoint", {}) if isinstance(operation_result.get("checkpoint", {}), dict) else {},
        )
        update_agent_run_status(
            storage,
            _display_path(storage.root, run_path),
            status="waiting_human",
            checkpoint={"path": checkpoint.get("path", ""), "status": "agent_scheduler_waiting_human"},
            event_type="agent_dispatch.waiting_human",
            message=str(operation_result.get("message", "Agent scheduler is waiting for output assets")),
        )
        updated = _update_queue_item(
            storage,
            queue_path,
            status="waiting_human",
            updates={"checkpoint_path": checkpoint.get("path", ""), "last_error": str(operation_result.get("message", "")), "result": operation_result},
        )
        return {"queue_status": "waiting_human", "queue": updated, "agent_run_path": _display_path(storage.root, run_path), "checkpoint_path": checkpoint.get("path", "")}
    execution = execute_agent_run_once(
        storage,
        _display_path(storage.root, run_path),
        tool_name=str(queue_content.get("tool_name") or (contract.required_tools[0] if contract.required_tools else "run_validation")),
        output_type=str(queue_content.get("output_type") or (contract.output_types[0] if contract.output_types else "")) or None,
        token_used=int(operation_result.get("token_used", 0) or 0),
        cost_estimate=float(operation_result.get("cost_estimate", 0.0) or 0.0),
        output_assets=[str(item) for item in operation_result.get("output_assets", []) if str(item).strip()] if isinstance(operation_result.get("output_assets", []), list) else [],
        checkpoint=operation_result.get("checkpoint", {}) if isinstance(operation_result.get("checkpoint", {}), dict) else None,
        evidence={**(operation_result.get("evidence", {}) if isinstance(operation_result.get("evidence", {}), dict) else {}), "agent_scheduler_dispatch_id": queue_content.get("dispatch_id", "")},
    )
    if execution.get("status") == "succeeded":
        workflow_resume = _resume_workflow_from_agent(storage, queue_data, execution, operation_result)
        updated = _update_queue_item(
            storage,
            queue_path,
            status="acked",
            updates={
                "acked_at": utc_now(),
                "result": {**operation_result, "workflow_resume": workflow_resume},
                "resume_workflow_run_path": str(workflow_resume.get("workflow_run", {}).get("path", "")) if isinstance(workflow_resume.get("workflow_run", {}), dict) else "",
                "last_error": "",
            },
        )
        return {
            "queue_status": "acked",
            "queue": updated,
            "agent_run_path": _display_path(storage.root, run_path),
            "workflow_resume": workflow_resume,
            "output_assets": operation_result.get("output_assets", []),
        }
    failure = _fail_queue_item(storage, queue_path, reason=_execution_error_message(execution), retry_delay_seconds=retry_delay_seconds)
    return {"queue_status": failure.get("status", ""), "queue": failure, "agent_run_path": _display_path(storage.root, run_path), "execution": execution}


def _resume_workflow_from_agent(storage: LocalStorage, queue_data: dict[str, Any], execution: dict[str, Any], operation_result: dict[str, Any]) -> dict[str, Any]:
    queue_content = queue_data.get("content", {}) if isinstance(queue_data.get("content", {}), dict) else {}
    workflow_run_path = str(queue_content.get("workflow_run_path", ""))
    if not workflow_run_path:
        workflow_run_path = _workflow_run_path_by_id(storage, str(queue_content.get("workflow_run_id", "")))
    node_id = str(queue_content.get("workflow_node_id", ""))
    if not workflow_run_path or not node_id:
        return {"status": "skipped", "reason": "agent dispatch has no workflow binding"}
    from novel_forge.modules.workflow_nodes import resume_workflow

    return resume_workflow(
        storage,
        workflow_run_path,
        resume_node_id=node_id,
        agent_run_path=str(queue_content.get("agent_run_path", "")),
        output_assets=[str(item) for item in operation_result.get("output_assets", []) if str(item).strip()] if isinstance(operation_result.get("output_assets", []), list) else [],
        token_used=int(operation_result.get("token_used", 0) or 0),
        cost_estimate=float(operation_result.get("cost_estimate", 0.0) or 0.0),
        checkpoint=operation_result.get("checkpoint", {}) if isinstance(operation_result.get("checkpoint", {}), dict) else {"status": "agent_scheduler_resume"},
        evidence={"agent_scheduler_dispatch_id": queue_content.get("dispatch_id", ""), "scheduled_by": "agent_scheduler"},
        max_nodes=5,
        archive_previous=True,
    )


def _fail_queue_item(storage: LocalStorage, queue_path: str | Path, *, reason: str, retry_delay_seconds: int = 0) -> dict[str, Any]:
    path = _resolve_queue(storage, queue_path)
    data = _read_json_safe(storage, path)
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    attempt_count = int(content.get("attempt_count", 0) or 0)
    max_attempts = int(content.get("max_attempts", 3) or 3)
    if attempt_count >= max_attempts:
        try:
            update_agent_run_status(storage, str(content.get("agent_run_path", "")), status="dead_letter", error=reason, event_type="agent_dispatch.dead_letter", message=reason)
        except Exception:
            pass
        return _update_queue_item(storage, path, status="dead_letter", updates={"dead_lettered_at": utc_now(), "last_error": reason})
    try:
        create_agent_failure_report(
            storage,
            agent_run_path=str(content.get("agent_run_path", "")),
            error_type="AgentSchedulerExecutionFailed",
            error_message=reason,
            recovery_instruction="Agent scheduler will retry after the queue backoff, or recover the dispatch manually from the Agent Scheduler console.",
        )
    except Exception:
        pass
    return _update_queue_item(storage, path, status="retry_scheduled", updates={"available_at": _utc_datetime_after(max(0, retry_delay_seconds)), "last_error": reason})


def _update_queue_item(storage: LocalStorage, queue_path: str | Path, *, status: str, updates: dict[str, Any]) -> dict[str, Any]:
    if status not in QUEUE_STATUSES:
        raise ValueError(f"agent_dispatch_queue status is invalid: {status}")
    path = _resolve_queue(storage, queue_path)
    data = _read_json_safe(storage, path)
    if not isinstance(data, dict) or data.get("type") != "agent_dispatch_queue":
        raise ValueError(f"agent_dispatch_queue JSON must be an object: {path}")
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    content.update(updates)
    content["status"] = status
    content["lease_owner"] = "" if status in {"acked", "retry_scheduled", "dead_letter", "waiting_human", "cancelled"} else content.get("lease_owner", "")
    content["lease_expires_at"] = "" if status in {"acked", "retry_scheduled", "dead_letter", "waiting_human", "cancelled"} else content.get("lease_expires_at", "")
    data["content"] = content
    data["updated_at"] = utc_now()
    data["tags"] = _dedupe([*[str(tag) for tag in data.get("tags", [])], status])
    _write_json_validated(storage, path, data)
    return _queue_row(storage, path, data)


def _queue_row(storage: LocalStorage, path: Path, data: dict[str, Any]) -> dict[str, Any]:
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


def _queue_path(storage: LocalStorage, dispatch_id: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in dispatch_id or "agent_dispatch")
    return storage.data_dir("runs") / f"{safe}.json"


def _dispatch_id_from_key(idempotency_key: str) -> str:
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:16]
    return f"agent-dispatch-{digest}"


def _resolve_queue(storage: LocalStorage, value: str | Path) -> Path:
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


def _resolve_agent_run(storage: LocalStorage, value: str | Path) -> Path:
    path = resolve_path(storage.root, value)
    if path.exists():
        return path
    for candidate in storage.list_json("runs"):
        data = _read_json_safe(storage, candidate)
        if not isinstance(data, dict) or data.get("type") != "agent_run":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if str(content.get("run_id", "")) == str(value) or str(data.get("id", "")) == str(value):
            return candidate
    raise FileNotFoundError(f"agent_run not found: {value}")


def _workflow_run_path_by_id(storage: LocalStorage, run_id: str) -> str:
    if not run_id:
        return ""
    for path in reversed(storage.list_json("runs")):
        data = _read_json_safe(storage, path)
        if not isinstance(data, dict) or data.get("type") != "workflow_run":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if str(content.get("run_id", "")) == run_id:
            return _display_path(storage.root, path)
    return ""


def _execution_error_message(execution: dict[str, Any]) -> str:
    if isinstance(execution.get("failure", {}), dict):
        failure = execution.get("failure", {})
        if isinstance(failure.get("asset", {}), dict):
            content = failure.get("asset", {}).get("content", {}) if isinstance(failure.get("asset", {}).get("content", {}), dict) else {}
            return str(content.get("error_message", "agent execution failed"))
    return str(execution.get("message", "agent execution failed"))


def _canonical_operation(value: str) -> str:
    safe = value.strip().lower().replace("_", "-").replace(".", "-").replace(" ", "-")
    while "--" in safe:
        safe = safe.replace("--", "-")
    return safe.strip("-")


def _operation_runners() -> dict[str, OperationRunner]:
    return {alias: spec.runner for alias, spec in _operation_specs_by_alias().items()}


def _operation_specs_by_alias() -> dict[str, AgentOperationSpec]:
    specs: dict[str, AgentOperationSpec] = {}
    for spec in _operation_specs():
        for alias in (spec.operation, *spec.aliases):
            specs[_canonical_operation(alias)] = spec
    return specs


def _operation_specs() -> list[AgentOperationSpec]:
    return [
        AgentOperationSpec(
            operation="decompose",
            aliases=("decomposition", "hot_novel_deconstruction"),
            runner=_run_decompose,
            agent_key="knowledge",
            input_types=("source_document",),
            output_types=("decomposition_report",),
            required_tool="write_decomposition_report",
            sla_seconds=900,
        ),
        AgentOperationSpec(
            operation="build-materials",
            aliases=("materials", "material"),
            runner=_run_build_materials,
            agent_key="material",
            input_types=("decomposition_report", "analysis_conversion_report"),
            output_types=("material_card",),
            required_tool="write_material_card",
            sla_seconds=900,
        ),
        AgentOperationSpec(
            operation="generate-outline",
            aliases=("outline",),
            runner=_run_generate_outline,
            agent_key="outline",
            input_types=("character_card", "world_bible", "topic_seed"),
            output_types=("outline", "outline_version"),
            required_tool="write_outline",
            sla_seconds=1200,
        ),
        AgentOperationSpec(
            operation="generate-chapter-plan",
            aliases=("chapter-plan", "chapter_plan"),
            runner=_run_generate_chapter_plan,
            agent_key="chapter_plan",
            input_types=("outline", "outline_version"),
            output_types=("chapter_plan", "chapter_plan_version"),
            required_tool="write_chapter_plan",
            sla_seconds=900,
        ),
        AgentOperationSpec(
            operation="draft",
            aliases=("generate-draft", "generate_chapter", "prose-generation"),
            runner=_run_draft,
            agent_key="draft",
            input_types=("chapter_plan", "chapter_plan_version"),
            output_types=("draft_chapter", "draft_version", "generation_run"),
            required_tool="write_draft_chapter",
            sla_seconds=1800,
        ),
        AgentOperationSpec(
            operation="review",
            aliases=("quality-review",),
            runner=_run_review,
            agent_key="review",
            input_types=("draft_chapter", "draft_version"),
            output_types=("review_report", "quality_score_report", "style_review_report", "originality_report", "chapter_audit_report"),
            required_tool="write_review_report",
            sla_seconds=1200,
        ),
        AgentOperationSpec(
            operation="revise",
            aliases=("revision", "revision-plan"),
            runner=_run_revise,
            agent_key="review",
            input_types=("review_report", "chapter_audit_report"),
            output_types=("revision_plan",),
            required_tool="write_revision_plan",
            sla_seconds=900,
        ),
        AgentOperationSpec(
            operation="run-analysis",
            aliases=("analysis",),
            runner=_run_analysis,
            agent_key="analysis",
            input_types=("source_document",),
            output_types=("common_novel_analysis_report",),
            required_tool="write_analysis_report",
            sla_seconds=1200,
        ),
        AgentOperationSpec(
            operation="convert-analysis-report",
            aliases=("analysis-conversion",),
            runner=_run_analysis_conversion,
            agent_key="analysis",
            input_types=("common_novel_analysis_report", "web_fiction_business_analysis_report", "published_fiction_analysis_report", "classic_literary_analysis_report"),
            output_types=("analysis_conversion_report",),
            required_tool="write_converted_creative_asset",
            sla_seconds=900,
        ),
        AgentOperationSpec(
            operation="create-editor-patch",
            aliases=("editor-patch",),
            runner=_run_create_editor_patch,
            agent_key="ai_editor",
            input_types=("draft_chapter", "draft_version"),
            output_types=("editor_patch",),
            required_tool="write_editor_patch",
            sla_seconds=900,
        ),
        AgentOperationSpec(
            operation="apply-editor-patch",
            aliases=("apply-editor",),
            runner=_run_apply_editor_patch,
            agent_key="ai_editor",
            input_types=("editor_patch",),
            output_types=("editor_patch", "draft_chapter", "draft_version", "draft_diff_report", "generation_run"),
            required_tool="write_editor_patch",
            sla_seconds=1200,
        ),
        AgentOperationSpec(
            operation="create-continuity-graph-snapshot",
            aliases=("continuity-graph-snapshot",),
            runner=_run_continuity_graph_snapshot,
            agent_key="continuity",
            input_types=(),
            output_types=("continuity_graph_snapshot",),
            required_tool="write_continuity_graph_snapshot",
            sla_seconds=600,
        ),
        AgentOperationSpec(
            operation="create-canon-graph-snapshot",
            aliases=("canon-graph-snapshot",),
            runner=_run_canon_graph_snapshot,
            agent_key="continuity",
            input_types=(),
            output_types=("canon_graph_snapshot",),
            required_tool="write_canon_graph_snapshot",
            sla_seconds=600,
        ),
        AgentOperationSpec(
            operation="create-chapter-continuity-report",
            aliases=("chapter-continuity-report",),
            runner=_run_chapter_continuity_report,
            agent_key="continuity",
            input_types=("draft_chapter", "draft_version"),
            output_types=("chapter_continuity_report",),
            required_tool="write_chapter_continuity_report",
            sla_seconds=600,
        ),
        AgentOperationSpec(
            operation="create-canon-patch-from-draft",
            aliases=("canon-patch-from-draft",),
            runner=_run_canon_patch_from_draft,
            agent_key="continuity",
            input_types=("draft_chapter", "draft_version"),
            output_types=("canon_patch",),
            required_tool="write_canon_patch",
            sla_seconds=600,
        ),
        AgentOperationSpec(
            operation="apply-canon-patch",
            aliases=(),
            runner=_run_apply_canon_patch,
            agent_key="continuity",
            input_types=("canon_patch",),
            output_types=("canon_patch", "continuity_bible"),
            required_tool="write_canon_patch",
            sla_seconds=600,
        ),
        AgentOperationSpec(
            operation="create-chapter-stability-preflight-report",
            aliases=("chapter-stability-preflight",),
            runner=_run_chapter_stability_preflight,
            agent_key="continuity",
            input_types=("chapter_plan", "chapter_plan_version"),
            output_types=("chapter_continuity_report",),
            required_tool="write_chapter_continuity_report",
            sla_seconds=600,
        ),
        AgentOperationSpec(
            operation="create-quality-score-report",
            aliases=("quality-score-report",),
            runner=_run_quality_score_report,
            agent_key="review",
            input_types=("draft_chapter", "draft_version"),
            output_types=("quality_score_report",),
            required_tool="write_quality_score_report",
            sla_seconds=300,
        ),
        AgentOperationSpec(
            operation="create-style-decomposition-report",
            aliases=("style-decomposition-report",),
            runner=_run_style_decomposition_report,
            agent_key="style",
            input_types=("source_document", "draft_chapter", "draft_version"),
            output_types=("style_decomposition_report",),
            required_tool="write_style_decomposition_report",
            sla_seconds=300,
        ),
        AgentOperationSpec(
            operation="create-style-review-report",
            aliases=("style-review-report",),
            runner=_run_style_review_report,
            agent_key="style",
            input_types=("draft_chapter", "draft_version"),
            output_types=("style_review_report",),
            required_tool="write_style_review_report",
            sla_seconds=300,
        ),
        AgentOperationSpec(
            operation="create-originality-report",
            aliases=("originality-report",),
            runner=_run_originality_report,
            agent_key="review",
            input_types=("draft_chapter", "draft_version"),
            output_types=("originality_report",),
            required_tool="write_originality_report",
            sla_seconds=600,
        ),
        AgentOperationSpec(
            operation="create-chapter-audit-report",
            aliases=("chapter-audit-report",),
            runner=_run_chapter_audit_report,
            agent_key="review",
            input_types=("draft_chapter", "draft_version"),
            output_types=("chapter_audit_report",),
            required_tool="write_chapter_audit_report",
            sla_seconds=600,
        ),
        AgentOperationSpec(
            operation="create-publish-gate-report",
            aliases=("publish-gate-report",),
            runner=_run_publish_gate_report,
            agent_key="publishing",
            input_types=("draft_chapter", "draft_version"),
            output_types=("publish_gate_report",),
            required_tool="write_publish_gate_report",
            sla_seconds=300,
        ),
        AgentOperationSpec(
            operation="create-release-package",
            aliases=("release-package",),
            runner=_run_release_package,
            agent_key="publishing",
            input_types=("draft_chapter", "draft_version"),
            output_types=("release_package",),
            required_tool="write_release_package",
            sla_seconds=300,
        ),
        AgentOperationSpec(
            operation="create-outline-version",
            aliases=("outline-version",),
            runner=_run_outline_version,
            agent_key="outline",
            input_types=("outline",),
            output_types=("outline_version",),
            required_tool="write_outline_version",
            sla_seconds=300,
        ),
        AgentOperationSpec(
            operation="create-chapter-plan-version",
            aliases=("chapter-plan-version",),
            runner=_run_chapter_plan_version,
            agent_key="chapter_plan",
            input_types=("chapter_plan",),
            output_types=("chapter_plan_version",),
            required_tool="write_chapter_plan_version",
            sla_seconds=300,
        ),
        AgentOperationSpec(
            operation="create-draft-version",
            aliases=("draft-version",),
            runner=_run_draft_version,
            agent_key="draft",
            input_types=("draft_chapter",),
            output_types=("draft_version",),
            required_tool="write_draft_version",
            sla_seconds=300,
        ),
        AgentOperationSpec(
            operation="create-reader-sentiment-report",
            aliases=("reader-sentiment-report",),
            runner=_run_reader_sentiment_report,
            agent_key="feedback",
            input_types=("reader_feedback",),
            output_types=("reader_sentiment_report",),
            required_tool="write_reader_sentiment_report",
            sla_seconds=300,
        ),
        AgentOperationSpec(
            operation="create-operational-metric-snapshot",
            aliases=("operational-metric-snapshot",),
            runner=_run_operational_metric_snapshot,
            agent_key="feedback",
            input_types=("reader_feedback",),
            output_types=("operational_metric_snapshot",),
            required_tool="write_operational_metric_snapshot",
            sla_seconds=300,
        ),
    ]


def _run_decompose(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.decomposition import decompose

    return {"path": decompose(storage, _required_input_path(agent_run))}


def _run_build_materials(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.materials import build_materials

    return {"path": build_materials(storage, _required_input_path(agent_run))}


def _run_generate_outline(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.outline import generate_outline

    return {"path": generate_outline(storage, _required_input_path(agent_run), workspace_path=_workspace_path(agent_run))}


def _run_generate_chapter_plan(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.chapter_plan import generate_chapter_plan

    evidence = _evidence(agent_run)
    chapter = evidence.get("chapter")
    return {
        "path": generate_chapter_plan(
            storage,
            _required_input_path(agent_run),
            workspace_path=_workspace_path(agent_run),
            chapter=int(chapter) if isinstance(chapter, int) or str(chapter).isdigit() else None,
            carry_forward=evidence.get("carry_forward", {}) if isinstance(evidence.get("carry_forward", {}), dict) else None,
        )
    }


def _run_draft(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.drafting import draft

    evidence = _evidence(agent_run)
    return {
        "path": draft(
            storage,
            _required_input_path(agent_run),
            context_bundle_path=evidence.get("context_bundle_path") or None,
            stability_preflight_path=evidence.get("stability_preflight_path") or None,
            workspace_path=_workspace_path(agent_run),
        )
    }


def _run_review(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.review import review

    return {"path": review(storage, _required_input_path(agent_run))}


def _run_revise(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.revision import revise

    return {"path": revise(storage, _required_input_path(agent_run))}


def _run_analysis(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.analysis import run_analysis

    evidence = _evidence(agent_run)
    return run_analysis(storage, _required_input_path(agent_run), str(evidence.get("analysis_type", "common")), workspace_path=_workspace_path(agent_run))


def _run_analysis_conversion(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.analysis import convert_analysis_report

    evidence = _evidence(agent_run)
    return convert_analysis_report(
        storage,
        _required_input_path(agent_run),
        targets=_string_list(evidence.get("targets", [])) or None,
        workspace_path=_workspace_path(agent_run),
        reuse_scope=str(evidence.get("reuse_scope", "project")),
        human_approved=bool(evidence.get("human_approved", False)),
        approval_note=str(evidence.get("approval_note", "")),
    )


def _run_create_editor_patch(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.editor import create_editor_patch

    evidence = _evidence(agent_run)
    return create_editor_patch(
        storage,
        _required_input_path(agent_run),
        instructions=str(evidence.get("instructions", "")),
        operations=evidence.get("operations", []) if isinstance(evidence.get("operations", []), list) else [],
        workspace_path=_workspace_path(agent_run),
    )


def _run_apply_editor_patch(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.editor import apply_editor_patch

    evidence = _evidence(agent_run)
    return apply_editor_patch(
        storage,
        _required_input_path(agent_run),
        apply=bool(evidence.get("apply", True)),
        change_summary=str(evidence.get("change_summary", "agent scheduler editor patch")),
        operation_ids=_string_list(evidence.get("operation_ids", [])),
        operation_indexes=[int(item) for item in evidence.get("operation_indexes", [])] if isinstance(evidence.get("operation_indexes", []), list) else [],
    )


def _run_continuity_graph_snapshot(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.continuity_graph import create_continuity_graph_snapshot

    return create_continuity_graph_snapshot(storage, project_id=_project_id(agent_run) or None, workspace_path=_workspace_path(agent_run) or None)


def _run_canon_graph_snapshot(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.continuity_graph import create_canon_graph_snapshot

    return create_canon_graph_snapshot(storage, project_id=_project_id(agent_run) or None, workspace_path=_workspace_path(agent_run) or None)


def _run_chapter_continuity_report(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.continuity_graph import create_chapter_continuity_report

    return create_chapter_continuity_report(storage, _required_input_path(agent_run), workspace_path=_workspace_path(agent_run) or None)


def _run_canon_patch_from_draft(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.continuity_graph import create_canon_patch_from_draft

    return create_canon_patch_from_draft(storage, _required_input_path(agent_run), workspace_path=_workspace_path(agent_run) or None)


def _run_apply_canon_patch(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.continuity_graph import apply_canon_patch

    evidence = _evidence(agent_run)
    return apply_canon_patch(storage, _required_input_path(agent_run), confirmed=bool(evidence.get("confirmed", False)), note=str(evidence.get("note", "agent scheduler")))


def _run_chapter_stability_preflight(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.continuity_graph import create_chapter_stability_preflight_report

    return create_chapter_stability_preflight_report(storage, _required_input_path(agent_run), workspace_path=_workspace_path(agent_run) or None)


def _run_quality_score_report(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.standards import create_quality_score_report

    return {"path": create_quality_score_report(storage, _required_input_path(agent_run), workspace_path=_workspace_path(agent_run) or None)}


def _run_style_decomposition_report(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.style import create_style_decomposition_report

    return {"path": create_style_decomposition_report(storage, _required_input_path(agent_run), workspace_path=_workspace_path(agent_run) or None)}


def _run_style_review_report(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.style import create_style_review_report

    evidence = _evidence(agent_run)
    return {
        "path": create_style_review_report(
            storage,
            _required_input_path(agent_run),
            style_profile_path=evidence.get("style_profile_path") or None,
            workspace_path=_workspace_path(agent_run) or None,
        )
    }


def _run_originality_report(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.audit import create_originality_report

    return {"path": create_originality_report(storage, _required_input_path(agent_run), workspace_path=_workspace_path(agent_run) or None)}


def _run_chapter_audit_report(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.audit import create_chapter_audit_report

    evidence = _evidence(agent_run)
    return {
        "path": create_chapter_audit_report(
            storage,
            _required_input_path(agent_run),
            workspace_path=_workspace_path(agent_run) or None,
            quality_path=evidence.get("quality_path") or None,
            style_path=evidence.get("style_path") or None,
            originality_path=evidence.get("originality_path") or None,
        )
    }


def _run_publish_gate_report(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.audit import create_publish_gate_report

    evidence = _evidence(agent_run)
    return {
        "path": create_publish_gate_report(
            storage,
            _required_input_path(agent_run),
            workspace_path=_workspace_path(agent_run) or None,
            chapter_audit_path=evidence.get("chapter_audit_path") or None,
            human_override=bool(evidence.get("human_override", False)),
        )
    }


def _run_release_package(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.audit import create_release_package

    evidence = _evidence(agent_run)
    return {
        "path": create_release_package(
            storage,
            _required_input_path(agent_run),
            workspace_path=_workspace_path(agent_run) or None,
            publish_gate_path=evidence.get("publish_gate_path") or None,
            channel=str(evidence.get("channel", "local")),
            human_override=bool(evidence.get("human_override", False)),
        )
    }


def _run_outline_version(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.production_chain import create_outline_version

    return create_outline_version(storage, _required_input_path(agent_run), change_summary="agent scheduler version")


def _run_chapter_plan_version(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.production_chain import create_chapter_plan_version

    return create_chapter_plan_version(storage, _required_input_path(agent_run), change_summary="agent scheduler version")


def _run_draft_version(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.production_chain import create_draft_version

    return create_draft_version(storage, _required_input_path(agent_run), change_summary="agent scheduler version")


def _run_reader_sentiment_report(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.feedback import create_reader_sentiment_report

    return create_reader_sentiment_report(
        storage,
        feedback_paths=_input_paths(agent_run) or None,
        project_id=_project_id(agent_run) or None,
        workspace_path=_workspace_path(agent_run) or None,
    )


def _run_operational_metric_snapshot(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.feedback import create_operational_metric_snapshot

    return create_operational_metric_snapshot(
        storage,
        feedback_paths=_input_paths(agent_run) or None,
        project_id=_project_id(agent_run) or None,
        workspace_path=_workspace_path(agent_run) or None,
    )


def _input_paths(agent_run: dict[str, Any]) -> list[str]:
    content = agent_run.get("content", {}) if isinstance(agent_run.get("content", {}), dict) else {}
    rows = content.get("input_assets", []) if isinstance(content.get("input_assets", []), list) else []
    paths = [str(row.get("path", "")) for row in rows if isinstance(row, dict) and str(row.get("path", "")).strip()]
    return _dedupe(paths)


def _primary_input_path(agent_run: dict[str, Any]) -> str:
    paths = _input_paths(agent_run)
    return paths[0] if paths else ""


def _required_input_path(agent_run: dict[str, Any]) -> str:
    value = _primary_input_path(agent_run)
    if not value:
        content = agent_run.get("content", {}) if isinstance(agent_run.get("content", {}), dict) else {}
        raise ValueError(f"agent operation requires at least one input asset: {content.get('operation', '')}")
    return value


def _workspace_path(agent_run: dict[str, Any]) -> str:
    metadata = agent_run.get("metadata", {}) if isinstance(agent_run.get("metadata", {}), dict) else {}
    evidence = _evidence(agent_run, include_processor=False)
    return str(metadata.get("workspace_path", "") or evidence.get("workspace_path", "") or "")


def _project_id(agent_run: dict[str, Any]) -> str:
    metadata = agent_run.get("metadata", {}) if isinstance(agent_run.get("metadata", {}), dict) else {}
    evidence = _evidence(agent_run, include_processor=False)
    return str(metadata.get("project_id", "") or evidence.get("project_id", "") or "")


def _evidence(agent_run: dict[str, Any], *, include_processor: bool = True) -> dict[str, Any]:
    content = agent_run.get("content", {}) if isinstance(agent_run.get("content", {}), dict) else {}
    base = content.get("evidence", {}) if isinstance(content.get("evidence", {}), dict) else {}
    result = dict(base)
    if include_processor:
        for key in ["processor", "operation_args", "runner_args", "service_args"]:
            value = base.get(key, {})
            if isinstance(value, dict):
                result.update(value)
    return result


def _paths_from_result(storage: LocalStorage, value: Any) -> list[str]:
    paths: list[str] = []

    output_keys = {
        "path",
        "output_path",
        "output_paths",
        "output_assets",
        "created_assets",
        "forward_patch_path",
        "rollback_patch_path",
        "final_draft_path",
        "final_draft_version_path",
        "draft_diff_report_path",
        "generation_run_path",
    }
    non_output_path_prefixes = ("input_", "source_", "target_", "base_", "context_", "workspace_", "agent_", "workflow_", "contract_", "dispatch_")

    def visit(item: Any, key: str = "", *, nested: bool = False) -> None:
        if item is None:
            return
        if isinstance(item, Path):
            paths.append(_display_path(storage.root, item))
            return
        if isinstance(item, dict):
            for child_key, child_value in item.items():
                child_name = str(child_key)
                child_lower = child_name.lower()
                explicit_output = child_lower in output_keys or (
                    child_lower.endswith("_path") and not any(child_lower.startswith(prefix) for prefix in non_output_path_prefixes)
                )
                if explicit_output or (nested and child_lower == "path"):
                    visit(child_value, child_name, nested=True)
            return
        if isinstance(item, (list, tuple, set)):
            for child in item:
                visit(child, key, nested=nested)
            return
        if not isinstance(item, str):
            return
        text = item.strip()
        if not text:
            return
        key_lower = key.lower()
        looks_like_path_key = key_lower in output_keys or key_lower.endswith("_path") or key_lower.endswith("_paths")
        if not looks_like_path_key:
            return
        if _path_exists(storage, text):
            paths.append(_display_path(storage.root, resolve_path(storage.root, text)))

    visit(value)
    return _dedupe(paths)


def _json_safe_result(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe_result(child) for key, child in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe_result(child) for child in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _tool_name_for_output(output_types: list[str]) -> str:
    if not output_types:
        return "run_validation"
    return f"write_{output_types[0]}"


def _queue_lease_expired(content_or_row: dict[str, Any]) -> bool:
    expires_at = str(content_or_row.get("lease_expires_at", "") or "")
    if not expires_at:
        return True
    return _parse_utc_datetime(expires_at) <= _utc_now_dt()


def _utc_datetime_after(seconds: int) -> str:
    return (_utc_now_dt() + timedelta(seconds=max(0, int(seconds or 0)))).isoformat().replace("+00:00", "Z")


def _parse_utc_datetime(value: str) -> datetime:
    if not value:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return datetime.fromtimestamp(0, tz=timezone.utc)


def _utc_now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _trace_payload(value: Any) -> dict[str, str]:
    payload = value if isinstance(value, dict) else {}
    return {
        "trace_id": str(payload.get("trace_id", "")),
        "span_id": str(payload.get("span_id", "")),
        "parent_span_id": str(payload.get("parent_span_id", "")),
    }


def _path_exists(storage: LocalStorage, value: str | Path) -> bool:
    try:
        return resolve_path(storage.root, value).exists()
    except Exception:
        return False


def _read_json_safe(storage: LocalStorage, path: Path) -> dict[str, Any]:
    try:
        data = storage.read_json(path)
    except Exception:
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


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]
