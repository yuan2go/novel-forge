from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from novel_forge.agents import agent_runtime_profile, enforce_agent_action, runtime_profile_for_skill
from novel_forge.core.ids import make_id, utc_now
from novel_forge.model_adapters.runtime import evaluate_provider_runtime_guard, normalize_provider_usage, provider_runtime_guard_from_context
from novel_forge.modules.audit_log import record_audit_event
from novel_forge.modules.common import resolve_path, run_metadata
from novel_forge.modules.production_context import filter_project_safe_references, project_scope_from_asset
from novel_forge.modules.runtime_ledger import check_budget_policy, record_cost_ledger, record_model_call_log, record_trace_span
from novel_forge.schemas import (
    AgentBudget,
    AgentCheckpoint,
    AgentContract,
    AgentEvent,
    AgentFailureReport,
    AgentGate,
    AgentMetric,
    AgentRollbackReport,
    AgentRun,
    AgentSlaReport,
    validate_common_fields,
)
from novel_forge.storage.local import LocalStorage

AGENT_RUN_STATUSES = {
    "planned",
    "prepared",
    "running",
    "checkpointed",
    "waiting_human",
    "verifying",
    "succeeded",
    "needs_revision",
    "failed",
    "dead_letter",
    "recovered",
    "cancelled",
}
TERMINAL_STATUSES = {"succeeded", "failed", "dead_letter", "cancelled"}
AGENT_EVENT_POLICY_VERSION = "agent-event-policy-v1"
AGENT_EVENT_POLICY_MODES = {"full", "success_summary"}


class AgentRunStateMachine:
    ALLOWED_TRANSITIONS: dict[str, set[str]] = {
        "planned": {"prepared", "running", "cancelled", "failed"},
        "prepared": {"running", "waiting_human", "verifying", "succeeded", "failed", "cancelled"},
        "running": {"checkpointed", "verifying", "waiting_human", "succeeded", "needs_revision", "failed", "cancelled"},
        "checkpointed": {"running", "verifying", "succeeded", "failed", "cancelled"},
        "waiting_human": {"prepared", "running", "verifying", "succeeded", "failed", "cancelled"},
        "verifying": {"succeeded", "needs_revision", "failed", "waiting_human", "cancelled"},
        "needs_revision": {"prepared", "running", "failed", "cancelled"},
        "failed": {"prepared", "recovered", "dead_letter", "cancelled"},
        "dead_letter": {"prepared", "recovered", "cancelled"},
        "recovered": {"prepared", "running", "succeeded"},
        "succeeded": set(),
        "cancelled": set(),
    }

    @classmethod
    def apply_transition(
        cls,
        data: dict[str, Any],
        target_status: str,
        *,
        action: str = "",
        actor: str = "agent-runtime",
        message: str = "",
    ) -> dict[str, Any]:
        if target_status not in AGENT_RUN_STATUSES and target_status != "checkpointed":
            raise ValueError(f"agent_run status must be one of: {', '.join(sorted(AGENT_RUN_STATUSES))}")
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        current_status = str(content.get("status") or "planned")
        if current_status == target_status:
            allowed = True
        else:
            allowed = target_status in cls.ALLOWED_TRANSITIONS.get(current_status, set())
        if not allowed:
            raise ValueError(f"invalid agent_run transition: {current_status} -> {target_status}")
        now = utc_now()
        status_history = content.get("status_history", []) if isinstance(content.get("status_history", []), list) else []
        status_history.append(
            {
                "from_status": current_status,
                "to_status": target_status,
                "action": action,
                "actor": actor,
                "message": message,
                "transitioned_at": now,
            }
        )
        content["status_history"] = status_history[-100:]
        content["status"] = target_status
        if target_status in TERMINAL_STATUSES:
            content["finished_at"] = now
        elif target_status in {"running", "prepared", "waiting_human", "verifying", "needs_revision", "recovered"}:
            content["finished_at"] = ""
        data["content"] = content
        data["updated_at"] = now
        data["tags"] = _dedupe([*[str(tag) for tag in data.get("tags", [])], target_status])
        return {"from_status": current_status, "to_status": target_status, "allowed": True, "asset": data}


def _agent_event_policy(
    policy: dict[str, Any] | None = None,
    *,
    evidence: dict[str, Any] | None = None,
    stored: Any = None,
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    if isinstance(stored, dict):
        merged.update(stored)
    if isinstance(evidence, dict):
        runtime_spec = evidence.get("runtime_policy")
        if isinstance(runtime_spec, dict) and isinstance(runtime_spec.get("agent_event_policy"), dict):
            merged.update(runtime_spec["agent_event_policy"])
        runtime_policy = evidence.get("runtime_event_policy")
        if isinstance(runtime_policy, dict) and isinstance(runtime_policy.get("agent_event_policy"), dict):
            merged.update(runtime_policy["agent_event_policy"])
        artifact_policy = evidence.get("runtime_artifact_policy")
        if isinstance(artifact_policy, dict) and isinstance(artifact_policy.get("agent_event_policy"), dict):
            merged.update(artifact_policy["agent_event_policy"])
        if isinstance(evidence.get("agent_event_policy"), dict):
            merged.update(evidence["agent_event_policy"])
    if isinstance(policy, dict):
        merged.update(policy)

    mode = str(merged.get("mode") or "full").strip().lower()
    if mode in {"summary", "compact", "success_compact"}:
        mode = "success_summary"
    if mode not in AGENT_EVENT_POLICY_MODES:
        mode = "full"

    recording = {
        "started": mode == "full",
        "checkpoint": mode == "full",
        "succeeded": mode == "full",
        "needs_revision": True,
        "waiting_human": True,
        "failed": True,
        "dead_letter": True,
        "cancelled": True,
        "direct_event": True,
    }
    overrides = merged.get("recording", {}) if isinstance(merged.get("recording", {}), dict) else {}
    for key in ["started", "checkpoint", "succeeded", "needs_revision", "waiting_human"]:
        if key in overrides:
            recording[key] = bool(overrides[key])
    for key in ["failed", "dead_letter", "cancelled", "direct_event"]:
        recording[key] = True

    return {
        "policy_version": AGENT_EVENT_POLICY_VERSION,
        "mode": mode,
        "recording": recording,
        "reason": str(
            merged.get("reason")
            or (
                "success_summary skips low-value success-path AgentEvent assets and their event trace spans while preserving failure, dead-letter, checkpoint asset, gate, budget, audit, and status history evidence."
                if mode == "success_summary"
                else "full event recording preserves historical AgentRun behavior."
            )
        ),
    }


def _should_record_agent_event(*, policy: dict[str, Any], event_type: str, status: str) -> bool:
    recording = policy.get("recording", {}) if isinstance(policy.get("recording", {}), dict) else {}
    normalized_status = str(status or "").strip().lower()
    normalized_event = str(event_type or "").strip().lower()
    if normalized_status in {"failed", "dead_letter", "cancelled"}:
        return True
    if any(marker in normalized_event for marker in ["failed", "dead_letter", "cancelled"]):
        return True
    if normalized_event == "agent_run.started":
        return bool(recording.get("started", True))
    if normalized_event == "agent_run.checkpoint":
        return bool(recording.get("checkpoint", True))
    if normalized_status == "succeeded" or normalized_event.endswith(".succeeded"):
        return bool(recording.get("succeeded", True))
    if normalized_status == "needs_revision":
        return bool(recording.get("needs_revision", True))
    if normalized_status == "waiting_human":
        return bool(recording.get("waiting_human", True))
    return bool(recording.get("direct_event", True))


def _skipped_agent_event(*, event_type: str, status: str, message: str, policy: dict[str, Any]) -> dict[str, Any]:
    return {
        "skipped": True,
        "event_type": event_type,
        "status": status,
        "message": message,
        "policy_version": policy.get("policy_version", AGENT_EVENT_POLICY_VERSION),
        "policy_mode": policy.get("mode", "full"),
        "reason": "agent_event_policy compacted this low-value success-path event",
    }


def _record_agent_event_if_enabled(
    storage: LocalStorage,
    *,
    agent_run_path: str,
    event_type: str,
    status: str = "info",
    message: str = "",
    payload: dict[str, Any] | None = None,
    policy: dict[str, Any],
) -> dict[str, Any]:
    if _should_record_agent_event(policy=policy, event_type=event_type, status=status):
        return record_agent_event(
            storage,
            agent_run_path=agent_run_path,
            event_type=event_type,
            status=status,
            message=message,
            payload=payload,
        )
    skipped = _skipped_agent_event(event_type=event_type, status=status, message=message, policy=policy)
    _append_skipped_agent_event_summary(storage, agent_run_path=agent_run_path, skipped=skipped)
    return skipped


def _append_skipped_agent_event_summary(storage: LocalStorage, *, agent_run_path: str, skipped: dict[str, Any]) -> None:
    path = _resolve_agent_run(storage, agent_run_path)
    data = storage.read_json(path)
    if not isinstance(data, dict) or data.get("type") != "agent_run":
        return
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    summary = content.get("agent_event_summary", {}) if isinstance(content.get("agent_event_summary", {}), dict) else {}
    event_types = summary.get("skipped_event_types", []) if isinstance(summary.get("skipped_event_types", []), list) else []
    events = summary.get("recent_skipped_events", []) if isinstance(summary.get("recent_skipped_events", []), list) else []
    event_type = str(skipped.get("event_type", ""))
    summary.update(
        {
            "policy_version": skipped.get("policy_version", AGENT_EVENT_POLICY_VERSION),
            "policy_mode": skipped.get("policy_mode", "full"),
            "skipped_event_count": int(summary.get("skipped_event_count", 0) or 0) + 1,
            "skipped_event_types": _dedupe([*[str(item) for item in event_types], event_type]),
            "recent_skipped_events": [
                *events,
                {
                    "event_type": event_type,
                    "status": skipped.get("status", ""),
                    "message": skipped.get("message", ""),
                    "reason": skipped.get("reason", ""),
                    "skipped_at": utc_now(),
                },
            ][-20:],
        }
    )
    content["agent_event_summary"] = summary
    data["content"] = content
    data["updated_at"] = utc_now()
    _write_json_validated(storage, path, data)


@dataclass
class AgentExecutionContext:
    storage: LocalStorage
    agent_key: str
    operation: str
    input_assets: list[str | Path] = field(default_factory=list)
    output_types: list[str] = field(default_factory=list)
    skill: str = ""
    model_provider: str = "local"
    model_name: str = "local"
    prompt_version: str = "prompt-v1"
    token_budget: int = 0
    sla_seconds: int = 1800
    workspace_path: str | None = None
    knowledge_context_contract: dict[str, Any] | None = None
    agent_event_policy: dict[str, Any] | None = None
    run: dict[str, Any] | None = None

    def __enter__(self) -> "AgentExecutionContext":
        contract = ensure_agent_contract(
            self.storage,
            agent_key=self.agent_key,
            skill=self.skill,
            operation=self.operation,
            input_types=[],
            output_types=self.output_types,
            workspace_path=self.workspace_path,
        )
        self.run = start_agent_run(
            self.storage,
            agent_key=self.agent_key,
            skill=self.skill,
            operation=self.operation,
            input_assets=self.input_assets,
            status="running",
            contract_path=contract["path"],
            workspace_path=self.workspace_path,
            model_provider=self.model_provider,
            model_name=self.model_name,
            prompt_version=self.prompt_version,
            token_budget=self.token_budget,
            agent_event_policy=self.agent_event_policy,
            evidence={
                "sla_seconds": self.sla_seconds,
                **(_knowledge_context_evidence(self.knowledge_context_contract) if self.knowledge_context_contract else {}),
            },
        )
        return self

    @property
    def path(self) -> str:
        if not self.run:
            raise RuntimeError("agent execution context has not been entered")
        return str(self.run["path"])

    def guard(self, tool_name: str, output_type: str | None = None) -> None:
        guard_agent_action(self.storage, self.path, tool_name=tool_name, output_type=output_type)

    def succeed(self, output_assets: list[str | Path] | None = None, token_used: int = 0, cost_estimate: float = 0.0) -> dict[str, Any]:
        result = update_agent_run_status(
            self.storage,
            self.path,
            status="succeeded",
            output_assets=output_assets or [],
            event_type="agent_run.succeeded",
            message=f"{self.operation} completed",
        )
        if int(token_used or 0) > 0 or float(cost_estimate or 0.0) > 0:
            run_asset = result.get("asset", {}) if isinstance(result.get("asset", {}), dict) else {}
            content = run_asset.get("content", {}) if isinstance(run_asset.get("content", {}), dict) else {}
            metadata = run_asset.get("metadata", {}) if isinstance(run_asset.get("metadata", {}), dict) else {}
            trace_payload = _agent_trace_payload(
                content.get("trace", {}) if isinstance(content.get("trace", {}), dict) else {},
                fallback_trace_id=str(content.get("run_id", "")),
                span_name=f"model-call-{self.operation}",
            )
            result["model_call"] = record_model_call_log(
                self.storage,
                provider=self.model_provider or str(metadata.get("model_provider", "")) or "local",
                model=self.model_name or str(metadata.get("model_name", "")) or "local",
                operation=self.operation,
                status="succeeded",
                usage={"total_tokens": int(token_used or 0), "token_source": "agent_execution_context"},
                cost={"amount": float(cost_estimate or 0.0), "currency": "USD", "source": "agent_execution_context"},
                trace=trace_payload,
                project_id=str(metadata.get("project_id", "")),
                workspace_path=str(metadata.get("workspace_path", "")),
                source_id=str(content.get("run_id", "")),
                prompt_version=self.prompt_version or str(metadata.get("prompt_version", "")),
            )
        record_agent_budget(
            self.storage,
            agent_run_path=self.path,
            token_budget=self.token_budget,
            token_used=token_used,
            cost_estimate=cost_estimate,
            status=_budget_status(self.token_budget, token_used),
        )
        result["sla"] = create_agent_sla_report(self.storage, agent_run_path=self.path, sla_seconds=self.sla_seconds)
        return result

    def fail(self, exc: BaseException) -> dict[str, Any]:
        report = create_agent_failure_report(
            self.storage,
            agent_run_path=self.path,
            error_type=type(exc).__name__,
            error_message=str(exc),
            recovery_instruction=f"Retry operation {self.operation} after fixing the reported precondition or output validation issue.",
        )
        create_agent_sla_report(self.storage, agent_run_path=self.path, sla_seconds=self.sla_seconds)
        return report

    def __exit__(self, exc_type: Any, exc: BaseException | None, tb: Any) -> bool:
        if exc is not None:
            try:
                if self.path:
                    current = self.storage.read_json(resolve_path(self.storage.root, self.path))
                    content = current.get("content", {}) if isinstance(current, dict) and isinstance(current.get("content", {}), dict) else {}
                    if str(content.get("status", "")) in TERMINAL_STATUSES:
                        return False
            except Exception:
                pass
            self.fail(exc)
        return False


def ensure_agent_contract(
    storage: LocalStorage,
    *,
    agent_key: str = "",
    skill: str = "",
    operation: str,
    input_types: list[str] | None = None,
    output_types: list[str] | None = None,
    quality_gates: list[dict[str, Any]] | None = None,
    workspace_path: str | None = None,
) -> dict[str, Any]:
    storage.ensure_layout()
    profile = _runtime_profile(agent_key=agent_key, skill=skill)
    normalized_input_types = _dedupe(input_types or [])
    normalized_output_types = _dedupe(output_types or [])
    project = _project_scope(storage, [], workspace_path=workspace_path)
    project_id = str(project.get("project_id", ""))
    existing = _find_contract(
        storage,
        agent_type=str(profile.get("agent", "")),
        operation=operation,
        input_types=normalized_input_types,
        output_types=normalized_output_types,
        skill=skill,
        project_id=project_id,
    )
    if existing:
        return existing
    contract_id = make_id("agent_contract", f"{profile.get('agent', agent_key)}-{operation}-{skill or 'local'}")
    permissions = {
        "permission_profile": profile.get("permission_profile", ""),
        "forbidden": profile.get("forbidden", []),
        "boundary_contract": profile.get("boundary_contract", {}),
    }
    asset = AgentContract(
        title=f"{profile.get('agent', agent_key)} contract: {operation}",
        tags=["agent-contract", _normalize_agent_tag(str(profile.get("agent", agent_key))), operation],
        content={
            "contract_id": contract_id,
            "agent_type": profile.get("agent", agent_key),
            "operation": operation,
            "input_types": normalized_input_types,
            "output_types": normalized_output_types,
            "permissions": permissions,
            "tool_allowlist": list(profile.get("allowed_tools", [])),
            "allowed_write_types": list(profile.get("allowed_write_types", [])),
            "quality_gates": quality_gates or _default_quality_gates(profile),
            "status": "active",
            "contract_version": "0.1.0",
        },
        metadata={
            "project_id": project_id,
            "workspace_path": str(project.get("workspace_path", "")),
            "agent_key": _agent_key_from_profile(agent_key, profile),
            "skill": skill,
            "runtime_profile": profile,
        },
        references=filter_project_safe_references(storage, project_id, _dedupe([skill, str(project.get("workspace_path", ""))])),
    )
    return _write(storage, asset)


def start_agent_run(
    storage: LocalStorage,
    *,
    agent_key: str = "",
    skill: str = "",
    operation: str,
    input_assets: list[str | Path] | None = None,
    output_assets: list[str | Path] | None = None,
    status: str = "running",
    contract_path: str | Path | None = None,
    workspace_path: str | None = None,
    model_provider: str = "local",
    model_name: str = "local",
    prompt_version: str = "prompt-v1",
    token_budget: int = 0,
    agent_event_policy: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
    human_gate: dict[str, Any] | None = None,
    retry_count: int = 0,
) -> dict[str, Any]:
    if status not in AGENT_RUN_STATUSES:
        raise ValueError(f"agent_run status must be one of: {', '.join(sorted(AGENT_RUN_STATUSES))}")
    storage.ensure_layout()
    profile = _runtime_profile(agent_key=agent_key, skill=skill)
    input_rows = [_asset_ref(storage, item) for item in input_assets or []]
    output_rows = [_asset_ref(storage, item) for item in output_assets or []]
    project = _project_scope(storage, [*input_rows, *output_rows], workspace_path=workspace_path)
    project_id = str(project.get("project_id", ""))
    contract = _contract_row(
        storage,
        contract_path,
        profile=profile,
        operation=operation,
        input_types=_dedupe([str(row.get("type", "")) for row in input_rows if row.get("type")]),
        output_types=_dedupe([str(row.get("type", "")) for row in output_rows if row.get("type")]),
        skill=skill,
        agent_key=agent_key,
        workspace_path=workspace_path,
    )
    now = utc_now()
    run_id = make_id("agent_run", f"{profile.get('agent', agent_key)}-{operation}")
    evidence_payload = evidence or {}
    normalized_event_policy = _agent_event_policy(agent_event_policy, evidence=evidence_payload)
    knowledge_context = _knowledge_context_from_evidence(evidence_payload)
    agent_registry = _agent_registry_for_run(storage, agent_key, operation, evidence_payload)
    trace_payload = _agent_trace_payload(evidence_payload, fallback_trace_id=run_id, span_name=f"agent-run-{operation}")
    first_input = _first_existing_asset(storage, input_rows)
    metadata = {
        "project_id": project_id,
        "workspace_path": str(project.get("workspace_path", "")),
        "agent_key": _agent_key_from_profile(agent_key, profile),
        "skill": skill,
        "model_provider": model_provider,
        "model_name": model_name,
        "prompt_version": prompt_version,
        **_knowledge_context_metadata(knowledge_context),
        **agent_registry,
    }
    if first_input:
        metadata["run_metadata"] = run_metadata(operation, first_input, provider=model_provider, model=model_name, prompt_version=prompt_version)
    asset = AgentRun(
        title=f"{profile.get('agent', agent_key)} run: {operation}",
        source=contract.get("id", ""),
        tags=["agent-run", _normalize_agent_tag(str(profile.get("agent", agent_key))), operation, status],
        content={
            "run_id": run_id,
            "agent_type": profile.get("agent", agent_key),
            "operation": operation,
            "input_assets": input_rows,
            "output_assets": output_rows,
            "contract_id": contract.get("id", ""),
            "contract_path": contract.get("path", ""),
            "permissions": {
                "permission_profile": profile.get("permission_profile", ""),
                "tool_allowlist": list(profile.get("allowed_tools", [])),
                "allowed_write_types": list(profile.get("allowed_write_types", [])),
                "forbidden": list(profile.get("forbidden", [])),
            },
            "model_provider": model_provider,
            "model_name": model_name,
            "prompt_version": prompt_version,
            "token_budget": token_budget,
            "token_used": 0,
            "cost_estimate": 0,
            "started_at": now,
            "finished_at": now if status in TERMINAL_STATUSES else "",
            "status": status,
            "status_history": [
                {
                    "from_status": "",
                    "to_status": status,
                    "action": "start",
                    "actor": "agent-runtime",
                    "message": f"agent run created in {status}",
                    "transitioned_at": now,
                }
            ],
            "error": "",
            "checkpoint": {},
            "evidence": evidence_payload,
            "agent_event_policy": normalized_event_policy,
            **_knowledge_context_content(knowledge_context),
            "agent_registry": agent_registry,
            "trace": trace_payload,
            "human_gate": human_gate or {"required": status == "waiting_human", "status": "waiting" if status == "waiting_human" else "not_required"},
            "retry_count": retry_count,
        },
        metadata=metadata,
        references=filter_project_safe_references(
            storage,
            project_id,
            _dedupe(
                [
                    contract.get("id", ""),
                    contract.get("path", ""),
                    *[str(row.get("id", "")) for row in input_rows],
                    *[str(row.get("path", "")) for row in input_rows],
                    *[str(row.get("id", "")) for row in output_rows],
                    *[str(row.get("path", "")) for row in output_rows],
                    str(project.get("workspace_path", "")),
                    str(knowledge_context.get("context_bundle_path", "")),
                    str(knowledge_context.get("knowledge_pack_path", "")),
                    str(knowledge_context.get("context_bundle_id", "")),
                    str(knowledge_context.get("knowledge_pack_id", "")),
                ]
            ),
        ),
    )
    result = _write(storage, asset)
    _record_agent_trace_span(
        storage,
        trace=trace_payload,
        span_type="agent_run",
        name=operation,
        status=status,
        started_at=now,
        finished_at=now if status in TERMINAL_STATUSES else "",
        project_id=project_id,
        workspace_path=str(project.get("workspace_path", "")),
        attributes={"agent_run_path": result.get("path", ""), "agent_type": profile.get("agent", agent_key), "operation": operation},
        references=[result.get("path", "")],
    )
    event = _record_agent_event_if_enabled(
        storage,
        agent_run_path=result["path"],
        event_type="agent_run.started",
        status=status,
        message=f"{profile.get('agent', agent_key)} started {operation}",
        payload={"operation": operation, "skill": skill},
        policy=normalized_event_policy,
    )
    _record_audit_safely(
        storage,
        event_type="agent_run",
        action="started",
        actor_type="agent",
        actor_id=agent_key,
        project_id=project_id,
        trace_id=str(trace_payload.get("trace_id", "")),
        target={"agent_run_id": run_id, "operation": operation, "path": result["path"]},
        input_refs=[str(row.get("path", "")) for row in input_rows],
        output_refs=[result["path"]],
        evidence_refs=[event.get("path", ""), contract.get("path", "")],
        status=status,
    )
    result["event"] = event
    return result


def attach_agent_run_context_contract(
    storage: LocalStorage,
    agent_run_path: str | Path,
    contract: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(contract, dict) or not contract:
        return {"path": str(agent_run_path), "asset": {}}
    path = _resolve_agent_run(storage, str(agent_run_path))
    data = storage.read_json(path)
    if not isinstance(data, dict) or data.get("type") != "agent_run":
        raise ValueError(f"agent_run JSON must be an object: {path}")
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    evidence = content.get("evidence", {}) if isinstance(content.get("evidence", {}), dict) else {}
    evidence.update(_knowledge_context_evidence(contract))
    content["evidence"] = evidence
    content.update(_knowledge_context_content(contract))
    metadata.update(_knowledge_context_metadata(contract))
    data["content"] = content
    data["metadata"] = metadata
    data["references"] = filter_project_safe_references(
        storage,
        str(metadata.get("project_id", "")),
        _dedupe(
            [
                *[str(ref) for ref in data.get("references", [])],
                str(contract.get("context_bundle_path", "")),
                str(contract.get("knowledge_pack_path", "")),
                str(contract.get("context_bundle_id", "")),
                str(contract.get("knowledge_pack_id", "")),
            ]
        ),
    )
    data["updated_at"] = utc_now()
    _write_json_validated(storage, path, data)
    return {"path": _display_path(storage.root, path), "asset": data}


def update_agent_run_status(
    storage: LocalStorage,
    agent_run_path_or_id: str,
    *,
    status: str,
    output_assets: list[str | Path] | None = None,
    error: str = "",
    checkpoint: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
    human_gate: dict[str, Any] | None = None,
    agent_event_policy: dict[str, Any] | None = None,
    event_type: str = "agent_run.status",
    message: str = "",
) -> dict[str, Any]:
    if status not in AGENT_RUN_STATUSES:
        raise ValueError(f"agent_run status must be one of: {', '.join(sorted(AGENT_RUN_STATUSES))}")
    path = _resolve_agent_run(storage, agent_run_path_or_id)
    data = storage.read_json(path)
    if not isinstance(data, dict) or data.get("type") != "agent_run":
        raise ValueError(f"agent_run JSON must be an object: {path}")
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    project_id = str(metadata.get("project_id", ""))
    output_rows = content.get("output_assets", []) if isinstance(content.get("output_assets", []), list) else []
    for item in output_assets or []:
        output_rows.append(_asset_ref(storage, item))
    content["output_assets"] = _dedupe_asset_rows(output_rows)
    content["error"] = error
    if checkpoint is not None:
        content["checkpoint"] = checkpoint
    if evidence is not None:
        merged_evidence = content.get("evidence", {}) if isinstance(content.get("evidence", {}), dict) else {}
        merged_evidence.update(evidence)
        content["evidence"] = merged_evidence
    if human_gate is not None:
        content["human_gate"] = human_gate
    normalized_event_policy = _agent_event_policy(agent_event_policy, stored=content.get("agent_event_policy", {}))
    content["agent_event_policy"] = normalized_event_policy
    data["content"] = content
    AgentRunStateMachine.apply_transition(data, status, action=event_type, message=message)
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    data["references"] = filter_project_safe_references(
        storage,
        project_id,
        _dedupe(
            [
                *[str(ref) for ref in data.get("references", [])],
                *[str(row.get("id", "")) for row in content["output_assets"]],
                *[str(row.get("path", "")) for row in content["output_assets"]],
            ]
        ),
    )
    _write_json_validated(storage, path, data)
    trace_payload = content.get("trace", {}) if isinstance(content.get("trace", {}), dict) else {}
    _record_agent_trace_span(
        storage,
        trace=trace_payload,
        span_type="agent_status",
        name=event_type,
        status=status,
        started_at=content.get("started_at", ""),
        finished_at=content.get("finished_at", ""),
        project_id=project_id,
        workspace_path=str(metadata.get("workspace_path", "")),
        attributes={"agent_run_path": _display_path(storage.root, path), "event_type": event_type, "status": status, "message": message, "error": error},
        references=[_display_path(storage.root, path)],
    )
    event = _record_agent_event_if_enabled(
        storage,
        agent_run_path=_display_path(storage.root, path),
        event_type=event_type,
        status=status,
        message=message or f"agent run moved to {status}",
        payload={"error": error, "output_count": len(content["output_assets"])},
        policy=normalized_event_policy,
    )
    _record_audit_safely(
        storage,
        event_type="agent_run",
        action=event_type,
        actor_type="agent",
        actor_id=str(content.get("agent_type", "")),
        project_id=project_id,
        trace_id=str(trace_payload.get("trace_id", "")),
        target={"agent_run_id": content.get("run_id", ""), "operation": content.get("operation", ""), "path": _display_path(storage.root, path)},
        input_refs=[str(row.get("path", "")) for row in content.get("input_assets", []) if isinstance(row, dict)],
        output_refs=[str(row.get("path", "")) for row in content.get("output_assets", []) if isinstance(row, dict)],
        evidence_refs=[event.get("path", "")],
        status=status,
        blocking=status in {"failed", "dead_letter", "cancelled"},
        metadata={"error": error, "message": message},
    )
    return {"path": _display_path(storage.root, path), "asset": data, "event": event}


def record_agent_event(
    storage: LocalStorage,
    *,
    agent_run_path: str,
    event_type: str,
    status: str = "info",
    message: str = "",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_path = _resolve_agent_run(storage, agent_run_path)
    run = storage.read_json(run_path)
    if not isinstance(run, dict):
        raise ValueError(f"agent_run JSON must be an object: {run_path}")
    content = run.get("content", {}) if isinstance(run.get("content", {}), dict) else {}
    metadata = run.get("metadata", {}) if isinstance(run.get("metadata", {}), dict) else {}
    now = utc_now()
    trace_payload = _agent_trace_payload(content.get("trace", {}) if isinstance(content.get("trace", {}), dict) else {}, fallback_trace_id=str(content.get("run_id", "")), span_name=f"event-{event_type}")
    asset = AgentEvent(
        title=f"{event_type}: {content.get('operation', '')}",
        source=str(content.get("run_id", "")),
        tags=["agent-event", event_type, status],
        content={
            "agent_run_id": content.get("run_id", ""),
            "agent_run_path": _display_path(storage.root, run_path),
            "event_type": event_type,
            "status": status,
            "message": message,
            "payload": payload or {},
            "created_at": now,
            "trace": trace_payload,
        },
        metadata={
            "project_id": metadata.get("project_id", ""),
            "workspace_path": metadata.get("workspace_path", ""),
            "agent_type": content.get("agent_type", ""),
            "operation": content.get("operation", ""),
        },
        references=filter_project_safe_references(
            storage,
            str(metadata.get("project_id", "")),
            _dedupe([_display_path(storage.root, run_path)]),
        ),
    )
    result = _write(storage, asset)
    _record_agent_trace_span(
        storage,
        trace=trace_payload,
        span_type="agent_event",
        name=event_type,
        status=status,
        started_at=now,
        finished_at=now,
        project_id=str(metadata.get("project_id", "")),
        workspace_path=str(metadata.get("workspace_path", "")),
        attributes={"agent_event_path": result.get("path", ""), "message": message, "payload": payload or {}},
        references=[result.get("path", ""), _display_path(storage.root, run_path)],
    )
    return result


def record_agent_checkpoint(
    storage: LocalStorage,
    *,
    agent_run_path: str,
    status: str,
    state: dict[str, Any],
) -> dict[str, Any]:
    run_path = _resolve_agent_run(storage, agent_run_path)
    run = storage.read_json(run_path)
    if not isinstance(run, dict):
        raise ValueError(f"agent_run JSON must be an object: {run_path}")
    content = run.get("content", {}) if isinstance(run.get("content", {}), dict) else {}
    metadata = run.get("metadata", {}) if isinstance(run.get("metadata", {}), dict) else {}
    checkpoint_id = make_id("checkpoint", str(content.get("run_id", "")))
    now = utc_now()
    trace_payload = _agent_trace_payload(content.get("trace", {}) if isinstance(content.get("trace", {}), dict) else {}, fallback_trace_id=str(content.get("run_id", "")), span_name=f"checkpoint-{status}")
    asset = AgentCheckpoint(
        title=f"Checkpoint {status}: {content.get('operation', '')}",
        source=str(content.get("run_id", "")),
        tags=["agent-checkpoint", status],
        content={
            "agent_run_id": content.get("run_id", ""),
            "agent_run_path": _display_path(storage.root, run_path),
            "checkpoint_id": checkpoint_id,
            "status": status,
            "state": state,
            "created_at": now,
            "trace": trace_payload,
        },
        metadata={"project_id": metadata.get("project_id", ""), "workspace_path": metadata.get("workspace_path", "")},
        references=filter_project_safe_references(storage, str(metadata.get("project_id", "")), [_display_path(storage.root, run_path)]),
    )
    result = _write(storage, asset)
    _record_agent_trace_span(
        storage,
        trace=trace_payload,
        span_type="agent_checkpoint",
        name=status,
        status="succeeded",
        started_at=now,
        finished_at=now,
        project_id=str(metadata.get("project_id", "")),
        workspace_path=str(metadata.get("workspace_path", "")),
        attributes={"agent_checkpoint_path": result.get("path", ""), "state": state},
        references=[result.get("path", ""), _display_path(storage.root, run_path)],
    )
    update_agent_run_status(storage, _display_path(storage.root, run_path), status=str(content.get("status", "running")), checkpoint={"checkpoint_id": checkpoint_id, "path": result["path"]}, event_type="agent_run.checkpoint", message=f"checkpoint recorded: {status}")
    return result


def record_agent_budget(
    storage: LocalStorage,
    *,
    agent_run_path: str,
    token_budget: int,
    token_used: int = 0,
    cost_estimate: float = 0.0,
    status: str = "within_budget",
    write_ledger: bool = True,
) -> dict[str, Any]:
    run_path = _resolve_agent_run(storage, agent_run_path)
    run = storage.read_json(run_path)
    if not isinstance(run, dict):
        raise ValueError(f"agent_run JSON must be an object: {run_path}")
    content = run.get("content", {}) if isinstance(run.get("content", {}), dict) else {}
    metadata = run.get("metadata", {}) if isinstance(run.get("metadata", {}), dict) else {}
    trace_payload = _agent_trace_payload(content.get("trace", {}) if isinstance(content.get("trace", {}), dict) else {}, fallback_trace_id=str(content.get("run_id", "")), span_name="budget")
    asset = AgentBudget(
        title=f"Budget {status}: {content.get('operation', '')}",
        source=str(content.get("run_id", "")),
        tags=["agent-budget", status],
        content={
            "agent_run_id": content.get("run_id", ""),
            "agent_run_path": _display_path(storage.root, run_path),
            "token_budget": token_budget,
            "token_used": token_used,
            "cost_estimate": cost_estimate,
            "status": status,
            "trace": trace_payload,
        },
        metadata={"project_id": metadata.get("project_id", ""), "workspace_path": metadata.get("workspace_path", "")},
        references=filter_project_safe_references(storage, str(metadata.get("project_id", "")), [_display_path(storage.root, run_path)]),
    )
    result = _write(storage, asset)
    project_id = str(metadata.get("project_id", ""))
    workspace_path = str(metadata.get("workspace_path", ""))
    _record_agent_trace_span(
        storage,
        trace=trace_payload,
        span_type="agent_budget",
        name=str(content.get("operation", "")),
        status=status,
        project_id=project_id,
        workspace_path=workspace_path,
        attributes={"agent_budget_path": result.get("path", ""), "token_budget": token_budget, "token_used": token_used, "cost_estimate": cost_estimate},
        references=[result.get("path", ""), _display_path(storage.root, run_path)],
    )
    if write_ledger and float(cost_estimate or 0) > 0:
        try:
            result["cost_ledger"] = record_cost_ledger(
                storage,
                scope=project_id or f"agent:{content.get('run_id', '')}",
                amount=float(cost_estimate or 0),
                currency="USD",
                source_type="agent_budget",
                source_id=result.get("path", ""),
                trace=trace_payload,
                project_id=project_id,
                workspace_path=workspace_path,
                metadata={"agent_run_path": _display_path(storage.root, run_path), "token_used": token_used, "operation": content.get("operation", "")},
            )
        except Exception:
            pass
    data = storage.read_json(run_path)
    if isinstance(data, dict):
        run_content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        run_content["token_budget"] = token_budget
        run_content["token_used"] = token_used
        run_content["cost_estimate"] = cost_estimate
        data["content"] = run_content
        data["updated_at"] = utc_now()
        _write_json_validated(storage, run_path, data)
    return result


def record_agent_gate(
    storage: LocalStorage,
    *,
    agent_run_path: str,
    gate_type: str,
    status: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    run_path = _resolve_agent_run(storage, agent_run_path)
    run = storage.read_json(run_path)
    if not isinstance(run, dict):
        raise ValueError(f"agent_run JSON must be an object: {run_path}")
    content = run.get("content", {}) if isinstance(run.get("content", {}), dict) else {}
    metadata = run.get("metadata", {}) if isinstance(run.get("metadata", {}), dict) else {}
    gate_id = make_id("gate", f"{gate_type}-{status}")
    now = utc_now()
    asset = AgentGate(
        title=f"{gate_type} gate: {status}",
        source=str(content.get("run_id", "")),
        tags=["agent-gate", gate_type, status],
        content={
            "agent_run_id": content.get("run_id", ""),
            "agent_run_path": _display_path(storage.root, run_path),
            "gate_id": gate_id,
            "gate_type": gate_type,
            "status": status,
            "result": result,
            "created_at": now,
        },
        metadata={"project_id": metadata.get("project_id", ""), "workspace_path": metadata.get("workspace_path", "")},
        references=filter_project_safe_references(storage, str(metadata.get("project_id", "")), [_display_path(storage.root, run_path)]),
    )
    return _write(storage, asset)


def create_agent_failure_report(
    storage: LocalStorage,
    *,
    agent_run_path: str,
    error_type: str,
    error_message: str,
    recovery_instruction: str,
) -> dict[str, Any]:
    run_path = _resolve_agent_run(storage, agent_run_path)
    run = storage.read_json(run_path)
    if not isinstance(run, dict):
        raise ValueError(f"agent_run JSON must be an object: {run_path}")
    content = run.get("content", {}) if isinstance(run.get("content", {}), dict) else {}
    metadata = run.get("metadata", {}) if isinstance(run.get("metadata", {}), dict) else {}
    now = utc_now()
    safe_error_message = error_message or error_type or "agent execution failed"
    asset = AgentFailureReport(
        title=f"Failure: {content.get('operation', '')}",
        source=str(content.get("run_id", "")),
        tags=["agent-failure", error_type],
        content={
            "agent_run_id": content.get("run_id", ""),
            "agent_run_path": _display_path(storage.root, run_path),
            "error_type": error_type,
            "error_message": safe_error_message,
            "recovery_instruction": recovery_instruction,
            "created_at": now,
        },
        metadata={"project_id": metadata.get("project_id", ""), "workspace_path": metadata.get("workspace_path", "")},
        references=filter_project_safe_references(storage, str(metadata.get("project_id", "")), [_display_path(storage.root, run_path)]),
    )
    result = _write(storage, asset)
    update_agent_run_status(storage, _display_path(storage.root, run_path), status="failed", error=safe_error_message, event_type="agent_run.failed", message=safe_error_message)
    return result


def guard_agent_action(
    storage: LocalStorage,
    agent_run_path: str,
    *,
    tool_name: str,
    output_type: str | None = None,
) -> dict[str, Any]:
    run_path = _resolve_agent_run(storage, agent_run_path)
    run = storage.read_json(run_path)
    if not isinstance(run, dict) or run.get("type") != "agent_run":
        raise ValueError(f"agent_run JSON must be an object: {run_path}")
    content = run.get("content", {}) if isinstance(run.get("content", {}), dict) else {}
    permissions = content.get("permissions", {}) if isinstance(content.get("permissions", {}), dict) else {}
    profile = {
        "agent": content.get("agent_type", "Agent"),
        "allowed_tools": permissions.get("tool_allowlist", []),
        "allowed_write_types": permissions.get("allowed_write_types", []),
    }
    try:
        enforce_agent_action(profile, tool_name, output_type)
    except PermissionError as exc:
        record_agent_gate(
            storage,
            agent_run_path=_display_path(storage.root, run_path),
            gate_type="permission_allowlist",
            status="failed",
            result={"tool_name": tool_name, "output_type": output_type or "", "error": str(exc)},
        )
        create_agent_failure_report(
            storage,
            agent_run_path=_display_path(storage.root, run_path),
            error_type="PermissionError",
            error_message=str(exc),
            recovery_instruction="Change the Agent contract/profile or route the action to an Agent with the required permission.",
        )
        raise
    return record_agent_gate(
        storage,
        agent_run_path=_display_path(storage.root, run_path),
        gate_type="permission_allowlist",
        status="passed",
        result={"tool_name": tool_name, "output_type": output_type or ""},
    )


def execute_agent_run_once(
    storage: LocalStorage,
    agent_run_path: str,
    *,
    tool_name: str,
    output_type: str | None = None,
    token_used: int = 0,
    cost_estimate: float = 0.0,
    output_assets: list[str | Path] | None = None,
    checkpoint: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
    human_gate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_path = _resolve_agent_run(storage, agent_run_path)
    run = storage.read_json(run_path)
    if not isinstance(run, dict) or run.get("type") != "agent_run":
        raise ValueError(f"agent_run JSON must be an object: {run_path}")
    content = run.get("content", {}) if isinstance(run.get("content", {}), dict) else {}
    metadata = run.get("metadata", {}) if isinstance(run.get("metadata", {}), dict) else {}
    if str(content.get("status", "")) in TERMINAL_STATUSES:
        raise ValueError("agent_run is already terminal and cannot be executed again")
    guard = guard_agent_action(storage, _display_path(storage.root, run_path), tool_name=tool_name, output_type=output_type)
    token_budget = int(content.get("token_budget", 0) or 0)
    trace_payload = _agent_trace_payload(content.get("trace", {}) if isinstance(content.get("trace", {}), dict) else {}, fallback_trace_id=str(content.get("run_id", "")), span_name=f"execute-{tool_name}")
    project_id = str(metadata.get("project_id", ""))
    workspace_path = str(metadata.get("workspace_path", ""))
    run_evidence = content.get("evidence", {}) if isinstance(content.get("evidence", {}), dict) else {}
    evidence_payload = evidence or {}
    runtime_policy = _merge_runtime_policy(run_evidence, evidence_payload)
    if token_budget > 0 and token_used > token_budget:
        budget = record_agent_budget(
            storage,
            agent_run_path=_display_path(storage.root, run_path),
            token_budget=token_budget,
            token_used=token_used,
            cost_estimate=cost_estimate,
            status="exceeded",
        )
        record_agent_gate(
            storage,
            agent_run_path=_display_path(storage.root, run_path),
            gate_type="token_budget",
            status="failed",
            result={"token_budget": token_budget, "token_used": token_used},
        )
        failure = create_agent_failure_report(
            storage,
            agent_run_path=_display_path(storage.root, run_path),
            error_type="TokenBudgetExceeded",
            error_message=f"agent token budget exceeded: used {token_used}, budget {token_budget}",
            recovery_instruction="Resume with a smaller context, a larger explicit budget, or a different Agent contract.",
        )
        return {"status": "failed", "guard": guard, "budget": budget, "failure": failure}
    policy = check_budget_policy(
        storage,
        scope=project_id or "global",
        amount=float(cost_estimate or 0.0),
        token_used=int(token_used or 0),
        currency="USD",
        trace=trace_payload,
        project_id=project_id,
        workspace_path=workspace_path,
    )
    if policy.get("status") == "skipped" and bool(runtime_policy.get("require_budget_policy", False)):
        budget = record_agent_budget(
            storage,
            agent_run_path=_display_path(storage.root, run_path),
            token_budget=token_budget,
            token_used=token_used,
            cost_estimate=cost_estimate,
            status="exceeded",
        )
        record_agent_gate(
            storage,
            agent_run_path=_display_path(storage.root, run_path),
            gate_type="budget_policy",
            status="failed",
            result={**policy, "required": True},
        )
        failure = create_agent_failure_report(
            storage,
            agent_run_path=_display_path(storage.root, run_path),
            error_type="BudgetPolicyMissing",
            error_message="agent runtime policy requires an active budget_policy",
            recovery_instruction="Create an active budget_policy for the project or disable require_budget_policy before resuming.",
        )
        return {"status": "failed", "guard": guard, "budget": budget, "budget_policy": policy, "failure": failure}
    if policy.get("status") == "failed":
        budget = record_agent_budget(
            storage,
            agent_run_path=_display_path(storage.root, run_path),
            token_budget=token_budget,
            token_used=token_used,
            cost_estimate=cost_estimate,
            status="exceeded",
        )
        record_agent_gate(
            storage,
            agent_run_path=_display_path(storage.root, run_path),
            gate_type="budget_policy",
            status="failed",
            result=policy,
        )
        failure = create_agent_failure_report(
            storage,
            agent_run_path=_display_path(storage.root, run_path),
            error_type="BudgetPolicyExceeded",
            error_message=str(policy.get("message") or "agent budget policy exceeded"),
            recovery_instruction="Reduce provider usage, change routing, or update the active budget_policy before resuming.",
        )
        return {"status": "failed", "guard": guard, "budget": budget, "budget_policy": policy, "failure": failure}
    provider_guard = _provider_runtime_guard(
        storage,
        agent_run_path=_display_path(storage.root, run_path),
        trace=trace_payload,
        token_used=token_used,
        cost_estimate=cost_estimate,
        evidence=evidence_payload,
        project_id=project_id,
        workspace_path=workspace_path,
    )
    if provider_guard.get("status") == "failed":
        model_call = record_model_call_log(
            storage,
            provider=str(content.get("model_provider", metadata.get("model_provider", "local")) or "local"),
            model=str(content.get("model_name", metadata.get("model_name", "local")) or "local"),
            operation=str(content.get("operation", tool_name)),
            status="failed",
            usage=provider_guard.get("usage", {}) if isinstance(provider_guard.get("usage", {}), dict) else {},
            cost={"amount": float(cost_estimate or 0.0), "currency": "USD", "source": "provider_runtime_guard"},
            trace=trace_payload,
            project_id=project_id,
            workspace_path=workspace_path,
            source_id=str(content.get("run_id", "")),
            prompt_version=str(content.get("prompt_version", metadata.get("prompt_version", "")) or ""),
        )
        failure = create_agent_failure_report(
            storage,
            agent_run_path=_display_path(storage.root, run_path),
            error_type=str(provider_guard.get("error_type", "ProviderRuntimeGuardFailed")),
            error_message=str(provider_guard.get("message", "provider runtime guard failed")),
            recovery_instruction="Reduce provider usage, retry with a smaller context, or cancel/route the workflow before resuming.",
        )
        return {"status": "failed", "guard": guard, "provider_guard": provider_guard, "model_call": model_call, "failure": failure}
    model_call = record_model_call_log(
        storage,
        provider=str(content.get("model_provider", metadata.get("model_provider", "local")) or "local"),
        model=str(content.get("model_name", metadata.get("model_name", "local")) or "local"),
        operation=str(content.get("operation", tool_name)),
        status="succeeded",
        usage={"total_tokens": int(token_used or 0), "token_source": "executor"},
        cost={"amount": float(cost_estimate or 0.0), "currency": "USD", "source": "executor_estimate"},
        trace=trace_payload,
        project_id=project_id,
        workspace_path=workspace_path,
        source_id=str(content.get("run_id", "")),
        prompt_version=str(content.get("prompt_version", metadata.get("prompt_version", "")) or ""),
    )
    checkpoint_result = None
    if checkpoint:
        checkpoint_result = record_agent_checkpoint(
            storage,
            agent_run_path=_display_path(storage.root, run_path),
            status=str(checkpoint.get("status", "executor_checkpoint")),
            state=checkpoint,
        )
    budget = record_agent_budget(
        storage,
        agent_run_path=_display_path(storage.root, run_path),
        token_budget=token_budget,
        token_used=token_used,
        cost_estimate=cost_estimate,
        status=_budget_status(token_budget, token_used),
        write_ledger=False,
    )
    status = update_agent_run_status(
        storage,
        _display_path(storage.root, run_path),
        status="succeeded",
        output_assets=output_assets or [],
        evidence=evidence or {"executor_tool": tool_name, "output_type": output_type or ""},
        human_gate=human_gate or None,
        event_type="agent_run.executor.succeeded",
        message=f"executor completed {tool_name}",
    )
    evidence_payload = content.get("evidence", {}) if isinstance(content.get("evidence", {}), dict) else {}
    sla = create_agent_sla_report(
        storage,
        agent_run_path=_display_path(storage.root, run_path),
        sla_seconds=int(evidence_payload.get("sla_seconds", 1800)),
    )
    return {"status": "succeeded", "guard": guard, "budget": budget, "budget_policy": policy, "model_call": model_call, "checkpoint": checkpoint_result, "run": status, "sla": sla}


def create_agent_sla_report(
    storage: LocalStorage,
    *,
    agent_run_path: str,
    sla_seconds: int = 1800,
) -> dict[str, Any]:
    run_path = _resolve_agent_run(storage, agent_run_path)
    run = storage.read_json(run_path)
    if not isinstance(run, dict) or run.get("type") != "agent_run":
        raise ValueError(f"agent_run JSON must be an object: {run_path}")
    content = run.get("content", {}) if isinstance(run.get("content", {}), dict) else {}
    metadata = run.get("metadata", {}) if isinstance(run.get("metadata", {}), dict) else {}
    started_at = str(content.get("started_at", "") or utc_now())
    finished_at = str(content.get("finished_at", "") or utc_now())
    elapsed = _elapsed_seconds(started_at, finished_at)
    breach = elapsed > max(0, sla_seconds)
    trace_payload = _agent_trace_payload(content.get("trace", {}) if isinstance(content.get("trace", {}), dict) else {}, fallback_trace_id=str(content.get("run_id", "")), span_name="sla")
    asset = AgentSlaReport(
        title=f"SLA {content.get('operation', '')}: {'breached' if breach else 'within_sla'}",
        source=str(content.get("run_id", "")),
        tags=["agent-sla", "breached" if breach else "within-sla"],
        content={
            "agent_run_id": content.get("run_id", ""),
            "agent_run_path": _display_path(storage.root, run_path),
            "status": "breached" if breach else "within_sla",
            "started_at": started_at,
            "deadline_at": _deadline_at(started_at, sla_seconds),
            "finished_at": finished_at,
            "elapsed_seconds": elapsed,
            "sla_seconds": sla_seconds,
            "breach": breach,
            "trace": trace_payload,
        },
        metadata={"project_id": metadata.get("project_id", ""), "workspace_path": metadata.get("workspace_path", "")},
        references=filter_project_safe_references(storage, str(metadata.get("project_id", "")), [_display_path(storage.root, run_path)]),
    )
    result = _write(storage, asset)
    _record_agent_trace_span(
        storage,
        trace=trace_payload,
        span_type="agent_sla",
        name=str(content.get("operation", "")),
        status="failed" if breach else "succeeded",
        started_at=started_at,
        finished_at=finished_at,
        project_id=str(metadata.get("project_id", "")),
        workspace_path=str(metadata.get("workspace_path", "")),
        attributes={"agent_sla_path": result.get("path", ""), "elapsed_seconds": elapsed, "sla_seconds": sla_seconds, "breach": breach},
        references=[result.get("path", ""), _display_path(storage.root, run_path)],
    )
    return result


def _provider_runtime_guard(
    storage: LocalStorage,
    *,
    agent_run_path: str,
    trace: dict[str, Any],
    token_used: int,
    cost_estimate: float,
    evidence: dict[str, Any],
    project_id: str,
    workspace_path: str,
) -> dict[str, Any]:
    guard_spec = evidence.get("provider_runtime_guard", evidence.get("runtime_guard", {})) if isinstance(evidence, dict) else {}
    if not isinstance(guard_spec, dict):
        guard_spec = {}
    usage = evidence.get("provider_usage", {}) if isinstance(evidence.get("provider_usage", {}), dict) else {}
    normalized_usage = normalize_provider_usage({"total_tokens": int(token_used or 0), **usage}, usage_source="agent_executor")
    result = evaluate_provider_runtime_guard(
        operation="agent_execute",
        provider="agent_executor",
        usage=normalized_usage,
        guard=provider_runtime_guard_from_context({"provider_runtime_guard": guard_spec}),
        phase="postflight",
    )
    if result.get("status") != "failed":
        return {"status": "passed", "usage": result.get("usage", normalized_usage), "guard": result.get("guard", guard_spec), "events": result.get("events", [])}
    result = {**result, "cost_estimate": cost_estimate}
    record_agent_gate(
        storage,
        agent_run_path=agent_run_path,
        gate_type="provider_runtime_guard",
        status="failed",
        result=result,
    )
    record_trace_span(
        storage,
        trace_id=str(trace.get("trace_id", "")),
        span_id=str(trace.get("span_id", "")),
        parent_span_id=str(trace.get("parent_span_id", "")),
        span_type="provider_runtime_guard",
        name=str(result.get("error_type", "ProviderRuntimeGuardFailed")),
        status="failed",
        attributes=result,
        references=[agent_run_path],
        project_id=project_id,
        workspace_path=workspace_path,
    )
    return result


def create_agent_rollback_report(
    storage: LocalStorage,
    *,
    agent_run_path: str,
    rollback_strategy: str = "mark_outputs_rolled_back",
    apply: bool = False,
    reason: str = "",
) -> dict[str, Any]:
    run_path = _resolve_agent_run(storage, agent_run_path)
    run = storage.read_json(run_path)
    if not isinstance(run, dict) or run.get("type") != "agent_run":
        raise ValueError(f"agent_run JSON must be an object: {run_path}")
    content = run.get("content", {}) if isinstance(run.get("content", {}), dict) else {}
    metadata = run.get("metadata", {}) if isinstance(run.get("metadata", {}), dict) else {}
    output_rows = content.get("output_assets", []) if isinstance(content.get("output_assets", []), list) else []
    target_paths = _dedupe([str(row.get("path", "")) for row in output_rows if isinstance(row, dict)])
    applied_paths: list[str] = []
    errors: list[str] = []
    if apply:
        for target in target_paths:
            try:
                path = resolve_path(storage.root, target)
                data = storage.read_json(path)
                if not isinstance(data, dict):
                    raise ValueError("target asset is not a JSON object")
                target_metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
                target_metadata["rollback_status"] = "rolled_back"
                target_metadata["rollback_reason"] = reason or f"rollback for agent run {content.get('run_id', '')}"
                target_metadata["rollback_at"] = utc_now()
                data["metadata"] = target_metadata
                data["updated_at"] = utc_now()
                _write_json_validated(storage, path, data)
                applied_paths.append(target)
            except Exception as exc:
                errors.append(f"{target}: {exc}")
    status = "failed" if errors else "applied" if apply and target_paths else "planned" if target_paths else "not_required"
    asset = AgentRollbackReport(
        title=f"Rollback {status}: {content.get('operation', '')}",
        source=str(content.get("run_id", "")),
        tags=["agent-rollback", status],
        content={
            "agent_run_id": content.get("run_id", ""),
            "agent_run_path": _display_path(storage.root, run_path),
            "rollback_id": make_id("rollback", str(content.get("run_id", ""))),
            "target_asset_paths": target_paths,
            "applied_asset_paths": applied_paths,
            "rollback_strategy": rollback_strategy,
            "status": status,
            "reason": reason,
            "errors": errors,
            "created_at": utc_now(),
        },
        metadata={"project_id": metadata.get("project_id", ""), "workspace_path": metadata.get("workspace_path", "")},
        references=filter_project_safe_references(storage, str(metadata.get("project_id", "")), [_display_path(storage.root, run_path), *target_paths]),
    )
    written = _write(storage, asset)
    try:
        record_audit_event(
            storage,
            event_type="rollback",
            action="agent_rollback_report_created",
            actor_type="agent_runtime",
            actor_id=str(content.get("agent_type") or content.get("agent_key") or ""),
            target={"agent_run_id": content.get("run_id", ""), "rollback_strategy": rollback_strategy},
            project_id=str(metadata.get("project_id", "")),
            trace_id=str(metadata.get("trace_id") or content.get("trace_id") or ""),
            input_refs=[_display_path(storage.root, run_path)],
            output_refs=[written["path"]],
            evidence_refs=target_paths,
            status=status,
            blocking=status == "failed",
            rollback_ref=written["path"],
            metadata={"apply": bool(apply), "reason": reason},
        )
    except Exception:
        pass
    return written


def list_agent_runs(
    storage: LocalStorage,
    *,
    project_id: str | None = None,
    status: str | None = None,
    agent_type: str | None = None,
    operation: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in reversed(storage.list_json("runs")):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "agent_run":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if project_id and str(metadata.get("project_id", "")) != project_id:
            continue
        if status and str(content.get("status", "")) != status:
            continue
        if agent_type and agent_type.lower() not in str(content.get("agent_type", "")).lower():
            continue
        if operation and str(content.get("operation", "")) != operation:
            continue
        rows.append(_agent_run_row(storage, path, data))
        if len(rows) >= limit:
            break
    return rows


def list_agent_events(
    storage: LocalStorage,
    *,
    agent_run_id: str | None = None,
    agent_run_path: str | None = None,
    project_id: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    run_path_display = ""
    if agent_run_path:
        try:
            run_path_display = _display_path(storage.root, _resolve_agent_run(storage, agent_run_path))
        except Exception:
            run_path_display = agent_run_path
    for path in reversed(storage.list_json("runs")):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "agent_event":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if project_id and str(metadata.get("project_id", "")) != project_id:
            continue
        if agent_run_id and str(content.get("agent_run_id", "")) != agent_run_id:
            continue
        if run_path_display and str(content.get("agent_run_path", "")) != run_path_display:
            continue
        rows.append(
            {
                "path": _display_path(storage.root, path),
                "id": data.get("id", ""),
                "agent_run_id": content.get("agent_run_id", ""),
                "agent_run_path": content.get("agent_run_path", ""),
                "event_type": content.get("event_type", ""),
                "status": content.get("status", ""),
                "message": content.get("message", ""),
                "payload": content.get("payload", {}),
                "project_id": metadata.get("project_id", ""),
                "created_at": content.get("created_at", ""),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def create_agent_boundary_audit(storage: LocalStorage, *, apply_runtime_guard: bool = False) -> dict[str, Any]:
    """Create a static/runtime proof report for Agent boundary coverage.

    The audit intentionally stays local and deterministic: it scans known
    service/worker/model boundary files for asset writes and model calls, then
    flags files that do not mention AgentExecutionContext or guard wrappers.
    """

    root = Path(__file__).resolve().parents[2]
    scan_roots = [root / "modules", root / "workers", root / "model_adapters"]
    findings: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []
    for scan_root in scan_roots:
        if not scan_root.exists():
            continue
        for path in sorted(scan_root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            write_hits = _count_boundary_hits(text, ["write_asset", "write_asset_auto", "write_json("])
            model_hits = _count_boundary_hits(text, ["model_from_env", "GuardedModelAdapter", ".generate(", ".analyze(", ".review(", ".revise("])
            if not write_hits and not model_hits:
                continue
            has_context = "AgentExecutionContext" in text or "guard_agent_action" in text or "GuardedModelAdapter" in text
            has_guard = ".guard(" in text or "guard_agent_action" in text or "GuardedModelAdapter" in text
            severity = "low"
            if (write_hits or model_hits) and not has_context:
                severity = "high"
            elif (write_hits or model_hits) and not has_guard:
                severity = "medium"
            row = {
                "path": str(path.relative_to(root.parent)),
                "write_boundary_hits": write_hits,
                "model_boundary_hits": model_hits,
                "has_agent_context": has_context,
                "has_guard": has_guard,
                "severity": severity,
                "recommendation": _boundary_recommendation(write_hits, model_hits, has_context, has_guard),
            }
            coverage_rows.append(row)
            if severity in {"medium", "high"}:
                findings.append(row)
    runtime_guard_probe = _runtime_guard_probe(storage) if apply_runtime_guard else {"executed": False, "status": "not_requested"}
    status = "failed" if any(item["severity"] == "high" for item in findings) else "warning" if findings else "passed"
    asset = AgentMetric(
        title=f"Agent boundary audit {status}",
        tags=["agent-boundary-audit", status],
        content={
            "agent_run_id": "static-agent-boundary-audit",
            "metric_name": "agent_boundary_findings",
            "value": len(findings),
            "audit_id": make_id("agent_boundary_audit", utc_now()),
            "status": status,
            "coverage": coverage_rows,
            "findings": findings,
            "summary": {
                "scanned_files": len(coverage_rows),
                "finding_count": len(findings),
                "high_count": sum(1 for item in findings if item["severity"] == "high"),
                "medium_count": sum(1 for item in findings if item["severity"] == "medium"),
            },
            "runtime_guard_probe": runtime_guard_probe,
            "policy": "all worker/model/service write or model-call boundaries must use AgentExecutionContext and guard allowlist checks",
            "created_at": utc_now(),
        },
        metadata={"project_id": "local-system", "workspace_path": "local-system", "metric_kind": "agent_boundary_audit"},
    )
    return _write(storage, asset)


def _count_boundary_hits(text: str, needles: list[str]) -> int:
    return sum(text.count(needle) for needle in needles)


def _boundary_recommendation(write_hits: int, model_hits: int, has_context: bool, has_guard: bool) -> str:
    if not has_context:
        return "wrap this boundary with AgentExecutionContext before writing assets or calling model adapters"
    if not has_guard:
        return "add explicit run.guard(...) checks for read/write/model actions"
    if model_hits:
        return "model calls are routed through a guarded boundary; keep provider output schema validation attached"
    if write_hits:
        return "asset writes are guarded; keep output type controls current"
    return "no action"


def _runtime_guard_probe(storage: LocalStorage) -> dict[str, Any]:
    try:
        with AgentExecutionContext(
            storage,
            agent_key="review",
            operation="runtime-guard-negative-probe",
            output_types=["review_report"],
            workspace_path="local-system",
            sla_seconds=60,
        ) as run:
            try:
                run.guard("write_draft_chapter", "draft_chapter")
            except PermissionError as exc:
                return {"executed": True, "status": "passed", "blocked_action": "write_draft_chapter", "error": str(exc), "agent_run_path": run.path}
            return {"executed": True, "status": "failed", "error": "guard allowed forbidden write_draft_chapter for review agent", "agent_run_path": run.path}
    except Exception as exc:
        return {"executed": True, "status": "error", "error": str(exc)}


def _find_contract(
    storage: LocalStorage,
    *,
    agent_type: str,
    operation: str,
    input_types: list[str],
    output_types: list[str],
    skill: str,
    project_id: str = "",
) -> dict[str, Any] | None:
    for path in reversed(storage.list_json("runs")):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "agent_contract":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        contract_project_id = str(metadata.get("project_id", ""))
        if project_id:
            if contract_project_id != project_id:
                continue
        elif contract_project_id:
            continue
        if content.get("agent_type") != agent_type or content.get("operation") != operation:
            continue
        if _dedupe([str(item) for item in content.get("input_types", [])]) != input_types:
            continue
        if _dedupe([str(item) for item in content.get("output_types", [])]) != output_types:
            continue
        if str(metadata.get("skill", "")) != skill:
            continue
        return {"path": _display_path(storage.root, path), "id": data.get("id", ""), "asset": data, "validation": {"ok": True, "errors": []}}
    return None


def _contract_row(
    storage: LocalStorage,
    contract_path: str | Path | None,
    *,
    profile: dict[str, Any],
    operation: str,
    input_types: list[str],
    output_types: list[str],
    skill: str,
    agent_key: str,
    workspace_path: str | None = None,
) -> dict[str, Any]:
    if contract_path:
        path = resolve_path(storage.root, contract_path)
        data = storage.read_json(path)
        if not isinstance(data, dict) or data.get("type") != "agent_contract":
            raise ValueError(f"contract_path must point to an agent_contract asset: {contract_path}")
        return {"path": _display_path(storage.root, path), "id": data.get("id", ""), "asset": data}
    return ensure_agent_contract(
        storage,
        agent_key=agent_key,
        skill=skill,
        operation=operation,
        input_types=input_types,
        output_types=output_types,
        workspace_path=workspace_path,
    )


def _runtime_profile(agent_key: str = "", skill: str = "") -> dict[str, Any]:
    if skill:
        return runtime_profile_for_skill(skill)
    return agent_runtime_profile(agent_key or "quality")


def _default_quality_gates(profile: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"gate": "schema_validation", "required": True},
        {"gate": "permission_allowlist", "required": True, "allowed_tools": list(profile.get("allowed_tools", []))},
        {"gate": "output_type_control", "required": True, "allowed_write_types": list(profile.get("allowed_write_types", []))},
        {"gate": "human_review", "required": False},
    ]


def _asset_ref(storage: LocalStorage, value: str | Path) -> dict[str, str]:
    raw_value = str(value)
    path = resolve_path(storage.root, value)
    if path.exists() and path.is_file():
        try:
            asset = storage.read_asset(path)
            return {"id": asset.id, "type": asset.type, "title": asset.title or asset.name, "path": _display_path(storage.root, path)}
        except Exception:
            pass
    return {"id": raw_value, "type": "", "title": "", "path": raw_value}


def _project_scope(storage: LocalStorage, refs: list[dict[str, str]], *, workspace_path: str | None = None) -> dict[str, Any]:
    if workspace_path:
        return project_scope_from_asset(storage, {}, workspace_path=workspace_path)
    for ref in refs:
        path = ref.get("path", "")
        if not path:
            continue
        try:
            asset = storage.read_asset(resolve_path(storage.root, path))
        except Exception:
            continue
        project = project_scope_from_asset(storage, asset, input_path=path)
        if project.get("project_id") or project.get("workspace_path"):
            return project
    fallback = project_scope_from_asset(storage, {})
    if fallback.get("project_id") or fallback.get("workspace_path"):
        return fallback
    return {"project_id": "local-system", "workspace_path": "local-system", "title": "Local System", "project_config": {}}


def _first_existing_asset(storage: LocalStorage, refs: list[dict[str, str]]) -> Any | None:
    for ref in refs:
        try:
            return storage.read_asset(resolve_path(storage.root, ref.get("path", "")))
        except Exception:
            continue
    return None


def _resolve_agent_run(storage: LocalStorage, value: str | Path) -> Path:
    candidate = resolve_path(storage.root, value)
    if candidate.exists() and candidate.is_file():
        return candidate
    needle = str(value)
    for path in storage.list_json("runs"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "agent_run":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if needle in {str(data.get("id", "")), str(content.get("run_id", ""))}:
            return path
    raise FileNotFoundError(f"agent_run not found: {value}")


def _agent_run_row(storage: LocalStorage, path: Path, data: dict[str, Any]) -> dict[str, Any]:
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    return {
        "path": _display_path(storage.root, path),
        "id": data.get("id", ""),
        "run_id": content.get("run_id", ""),
        "agent_type": content.get("agent_type", ""),
        "operation": content.get("operation", ""),
        "status": content.get("status", ""),
        "input_count": len(content.get("input_assets", []) if isinstance(content.get("input_assets", []), list) else []),
        "output_count": len(content.get("output_assets", []) if isinstance(content.get("output_assets", []), list) else []),
        "contract_id": content.get("contract_id", ""),
        "contract_path": content.get("contract_path", ""),
        "model_provider": content.get("model_provider", ""),
        "model_name": content.get("model_name", ""),
        "prompt_version": content.get("prompt_version", ""),
        "token_budget": content.get("token_budget", 0),
        "token_used": content.get("token_used", 0),
        "cost_estimate": content.get("cost_estimate", 0),
        "error": content.get("error", ""),
        "input_assets": content.get("input_assets", []) if isinstance(content.get("input_assets", []), list) else [],
        "output_assets": content.get("output_assets", []) if isinstance(content.get("output_assets", []), list) else [],
        "checkpoint": content.get("checkpoint", {}) if isinstance(content.get("checkpoint", {}), dict) else {},
        "evidence": content.get("evidence", {}) if isinstance(content.get("evidence", {}), dict) else {},
        "human_gate": content.get("human_gate", {}),
        "agent_registry_entry_id": metadata.get("agent_registry_entry_id", ""),
        "agent_registry_entry_path": metadata.get("agent_registry_entry_path", ""),
        "agent_registry_version": metadata.get("agent_registry_version", ""),
        "agent_lifecycle_state": metadata.get("agent_lifecycle_state", ""),
        "agent_scheduler_enabled": metadata.get("agent_scheduler_enabled", False),
        "project_id": metadata.get("project_id", ""),
        "workspace_path": metadata.get("workspace_path", ""),
        "started_at": content.get("started_at", ""),
        "finished_at": content.get("finished_at", ""),
        "updated_at": data.get("updated_at", ""),
    }


def _agent_trace_payload(payload: dict[str, Any], *, fallback_trace_id: str, span_name: str) -> dict[str, str]:
    source = payload if isinstance(payload, dict) else {}
    nested = source.get("trace", {}) if isinstance(source.get("trace", {}), dict) else {}
    trace_id = str(source.get("trace_id") or nested.get("trace_id") or source.get("workflow_run_id") or fallback_trace_id)
    parent_span_id = str(source.get("parent_span_id") or nested.get("span_id") or nested.get("parent_span_id") or source.get("workflow_run_id") or trace_id)
    span_id = str(source.get("span_id") or make_id("span", f"{trace_id}-{span_name}-{utc_now()}"))
    return {"trace_id": trace_id, "span_id": span_id, "parent_span_id": parent_span_id}


def _merge_runtime_policy(*payloads: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        for key in ["runtime_policy", "provider_runtime_guard"]:
            value = payload.get(key)
            if isinstance(value, dict):
                merged.update(value)
        if "require_budget_policy" in payload:
            merged["require_budget_policy"] = bool(payload.get("require_budget_policy"))
    if str(merged.get("mode", "")).lower() in {"operating_system", "strict", "enforced"}:
        merged.setdefault("require_budget_policy", True)
    return merged


def _record_agent_trace_span(
    storage: LocalStorage,
    *,
    trace: dict[str, Any],
    span_type: str,
    name: str,
    status: str,
    started_at: str = "",
    finished_at: str = "",
    project_id: str = "",
    workspace_path: str = "",
    attributes: dict[str, Any] | None = None,
    references: list[str] | None = None,
) -> None:
    try:
        record_trace_span(
            storage,
            trace_id=str(trace.get("trace_id", "")),
            span_id=str(trace.get("span_id", "")),
            parent_span_id=str(trace.get("parent_span_id", "")),
            span_type=span_type,
            name=name,
            status=_agent_trace_status(status),
            started_at=started_at or None,
            finished_at=finished_at or None,
            attributes=attributes or {},
            references=references or [],
            project_id=project_id,
            workspace_path=workspace_path,
        )
    except Exception:
        return


def _agent_trace_status(status: str) -> str:
    value = str(status or "").lower()
    if value in {"succeeded", "within_budget", "within_sla", "passed", "info", "prepared"}:
        return "succeeded"
    if value in {"failed", "dead_letter", "exceeded", "breached"}:
        return "failed"
    if value in {"cancelled", "running", "skipped"}:
        return value
    return "succeeded"


def _write(
    storage: LocalStorage,
    asset: AgentContract
    | AgentRun
    | AgentCheckpoint
    | AgentEvent
    | AgentBudget
    | AgentGate
    | AgentMetric
    | AgentFailureReport
    | AgentSlaReport
    | AgentRollbackReport,
) -> dict[str, Any]:
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


def _record_audit_safely(storage: LocalStorage, **kwargs: Any) -> None:
    try:
        from novel_forge.modules.audit_log import record_audit_event

        record_audit_event(storage, **kwargs)
    except Exception:
        return


def _knowledge_context_from_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(evidence, dict):
        return {}
    contract = evidence.get("knowledge_context_contract")
    if isinstance(contract, dict) and contract:
        return contract
    context_bundle_id = str(evidence.get("context_bundle_id") or "").strip()
    knowledge_pack_id = str(evidence.get("knowledge_pack_id") or evidence.get("mkaos_knowledge_pack_id") or "").strip()
    if not context_bundle_id and not knowledge_pack_id:
        return {}
    return {
        "contract_version": str(evidence.get("knowledge_context_contract_version") or "knowledge-context-contract-v1"),
        "context_bundle_id": context_bundle_id,
        "context_bundle_path": str(evidence.get("context_bundle_path") or ""),
        "knowledge_pack_id": knowledge_pack_id,
        "knowledge_pack_path": str(evidence.get("knowledge_pack_path") or evidence.get("mkaos_knowledge_pack_path") or ""),
        "source_policy": evidence.get("source_policy", {}) if isinstance(evidence.get("source_policy", {}), dict) else {},
        "source_isolation": evidence.get("source_isolation", {}) if isinstance(evidence.get("source_isolation", {}), dict) else {},
        "mkaos_flow": str(evidence.get("mkaos_flow") or evidence.get("task_type") or ""),
        "selected_knowledge_ids": evidence.get("selected_knowledge_ids", []) if isinstance(evidence.get("selected_knowledge_ids", []), list) else [],
        "review_rules": evidence.get("review_rules", []) if isinstance(evidence.get("review_rules", []), list) else [],
        "risk_warnings": evidence.get("risk_warnings", []) if isinstance(evidence.get("risk_warnings", []), list) else [],
        "selector_policy_version": str(evidence.get("selector_policy_version") or ""),
    }


def _agent_registry_for_run(storage: LocalStorage, agent_key: str, operation: str, evidence: dict[str, Any]) -> dict[str, Any]:
    explicit = evidence.get("agent_registry", {}) if isinstance(evidence, dict) and isinstance(evidence.get("agent_registry", {}), dict) else {}
    if explicit:
        return {
            "agent_registry_entry_id": str(explicit.get("agent_registry_entry_id") or explicit.get("entry_id") or ""),
            "agent_registry_entry_path": str(explicit.get("agent_registry_entry_path") or explicit.get("entry_path") or ""),
            "agent_registry_version": str(explicit.get("agent_registry_version") or explicit.get("version") or ""),
            "agent_lifecycle_state": str(explicit.get("lifecycle_state") or ""),
            "agent_scheduler_enabled": bool(explicit.get("scheduler_enabled", False)),
        }
    try:
        from novel_forge.modules.agent_registry import resolve_agent_registry_entry

        resolved = resolve_agent_registry_entry(storage, agent_id=agent_key, operation=operation, require_schedulable=False, auto_sync=True)
    except Exception:
        return {}
    return {
        "agent_registry_entry_id": str(resolved.get("agent_registry_entry_id", "")),
        "agent_registry_entry_path": str(resolved.get("agent_registry_entry_path", "")),
        "agent_registry_version": str(resolved.get("agent_registry_version", "")),
        "agent_lifecycle_state": str(resolved.get("lifecycle_state", "")),
        "agent_scheduler_enabled": bool(resolved.get("scheduler_enabled", False)),
    }


def _knowledge_context_evidence(contract: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(contract, dict) or not contract:
        return {}
    return {
        "knowledge_context_contract": contract,
        "context_bundle_id": str(contract.get("context_bundle_id", "")),
        "context_bundle_path": str(contract.get("context_bundle_path", "")),
        "knowledge_pack_id": str(contract.get("knowledge_pack_id", "")),
        "knowledge_pack_path": str(contract.get("knowledge_pack_path", "")),
        "mkaos_flow": str(contract.get("mkaos_flow", "")),
        "selected_knowledge_ids": contract.get("selected_knowledge_ids", []) if isinstance(contract.get("selected_knowledge_ids", []), list) else [],
        "selector_policy_version": str(contract.get("selector_policy_version", "")),
        "source_policy": contract.get("source_policy", {}) if isinstance(contract.get("source_policy", {}), dict) else {},
        "source_isolation": contract.get("source_isolation", {}) if isinstance(contract.get("source_isolation", {}), dict) else {},
    }


def _knowledge_context_content(contract: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(contract, dict) or not contract:
        return {}
    return {
        "knowledge_context_contract": contract,
        "context_bundle_id": str(contract.get("context_bundle_id", "")),
        "knowledge_pack_id": str(contract.get("knowledge_pack_id", "")),
        "mkaos_flow": str(contract.get("mkaos_flow", "")),
    }


def _knowledge_context_metadata(contract: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(contract, dict) or not contract:
        return {}
    return {
        "knowledge_context_contract": contract,
        "context_bundle_id": str(contract.get("context_bundle_id", "")),
        "context_bundle_path": str(contract.get("context_bundle_path", "")),
        "knowledge_pack_id": str(contract.get("knowledge_pack_id", "")),
        "mkaos_knowledge_pack_id": str(contract.get("knowledge_pack_id", "")),
        "knowledge_pack_path": str(contract.get("knowledge_pack_path", "")),
        "mkaos_flow": str(contract.get("mkaos_flow", "")),
        "selected_knowledge_ids": contract.get("selected_knowledge_ids", []) if isinstance(contract.get("selected_knowledge_ids", []), list) else [],
        "selector_policy_version": str(contract.get("selector_policy_version", "")),
    }


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _dedupe(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "")
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _dedupe_asset_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, Any]] = []
    for row in rows:
        key = (str(row.get("id", "")), str(row.get("path", "")))
        if key in seen:
            continue
        seen.add(key)
        result.append({key: str(value) for key, value in row.items()})
    return result


def _budget_status(token_budget: int, token_used: int) -> str:
    if token_budget <= 0:
        return "within_budget"
    if token_used > token_budget:
        return "exceeded"
    if token_used >= token_budget * 0.85:
        return "near_limit"
    return "within_budget"


def _elapsed_seconds(started_at: str, finished_at: str) -> int:
    start = _parse_dt(started_at)
    finish = _parse_dt(finished_at) or datetime.now(timezone.utc)
    if not start:
        return 0
    return max(0, int((finish - start).total_seconds()))


def _deadline_at(started_at: str, sla_seconds: int) -> str:
    start = _parse_dt(started_at)
    if not start:
        return ""
    return (start + timedelta(seconds=max(0, sla_seconds))).isoformat().replace("+00:00", "Z")


def _parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _agent_key_from_profile(agent_key: str, profile: dict[str, Any]) -> str:
    if agent_key:
        return agent_key.strip().lower().replace(" ", "_").replace("-", "_")
    return _normalize_agent_tag(str(profile.get("agent", "quality")))


def _normalize_agent_tag(value: str) -> str:
    return value.strip().lower().replace(" agent", "").replace(" ", "_").replace("-", "_")
