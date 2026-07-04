from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.agent_runs import (
    attach_agent_run_context_contract,
    create_agent_failure_report,
    execute_agent_run_once,
    record_agent_checkpoint,
    record_agent_event,
    start_agent_run,
    update_agent_run_status,
)
from novel_forge.modules.common import resolve_path
from novel_forge.modules.operation_checkpoint import operation_checkpoint_schema
from novel_forge.modules.os_envelope import is_production_environment
from novel_forge.modules.production_context import filter_project_safe_references
from novel_forge.modules.review_issue import review_issue_to_revision_task_candidate
from novel_forge.modules.runtime_ledger import acquire_scheduler_lease, release_scheduler_lease, scheduler_lease_status
from novel_forge.schemas import AgentDispatchQueue, AgentRollbackReport, AgentTask, RevisionTask, validate_common_fields
from novel_forge.storage.local import LocalStorage

QUEUE_STATUSES = {"queued", "claimed", "running", "waiting_human", "acked", "retry_scheduled", "dead_letter", "cancelled"}
CLAIMABLE_STATUSES = {"queued", "retry_scheduled", "claimed"}
TERMINAL_QUEUE_STATUSES = {"acked", "dead_letter", "cancelled"}
OperationRunner = Callable[[LocalStorage, dict[str, Any], dict[str, Any]], dict[str, Any]]

CORE_MKAOS_CONTEXT_OPERATIONS = {
    "run-analysis": "required",
    "decompose": "required",
    "convert-analysis-report": "required",
    "generate-outline": "required",
    "generate-chapter-plan": "required",
    "draft": "required",
    "review": "required",
    "revise": "required",
    "create-editor-patch": "required",
    "apply-editor-patch": "compat",
    "run-longform-recap": "required",
    "create-publish-gate-report": "required",
    "create-feedback-backflow-plan": "required",
    "process-real-feedback-backflow": "required",
    "run-review-revision-publish-loop": "required",
    "build-context-bundle": "required",
}

MKAOS_OPERATION_ALIASES = {
    "analysis": "run-analysis",
    "decompose": "decompose",
    "convert": "convert-analysis-report",
    "outline": "generate-outline",
    "chapter_plan": "generate-chapter-plan",
    "draft": "draft",
    "review": "review",
    "revision": "revise",
    "editor_patch": "create-editor-patch",
    "recap": "run-longform-recap",
    "publish_gate": "create-publish-gate-report",
    "feedback_backflow": "create-feedback-backflow-plan",
}


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
    rollback_strategy: str = "mark_outputs_rolled_back"
    sla_seconds: int = 1800

    def checkpoint_schema(self) -> dict[str, Any]:
        schema = operation_checkpoint_schema(self.operation, checkpoint_strategy=self.checkpoint_strategy)
        return {
            **schema,
            "version": "1.0",
            "strategy": self.checkpoint_strategy,
            "required": ["status", "operation", "idempotency_key", "input_assets", "output_assets"],
            "states": ["operation_started", "agent_scheduler_service_completed", "agent_scheduler_service_failed", "agent_scheduler_rollback_applied"],
            "resume_from_checkpoint": {
                "output_committed": "reuse completed output_assets when assets still exist and are not rolled back or quarantined",
                "provider_completed": "resume output validation from durable raw provider output",
                "prompt_built": "restart provider call without rebuilding context when input fingerprints still match",
            },
            "idempotency_key": "agent_dispatch_queue.content.idempotency_key",
            "rollback_strategy": self.rollback_strategy,
        }


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
        contracts = []
        for spec in sorted({item.operation: item for item in self.specs.values()}.values(), key=lambda item: item.operation):
            contract = AgentOperationContract(
                operation=spec.operation,
                agent_key=spec.agent_key,
                runner_kind="local_service",
                input_types=list(spec.input_types),
                output_types=list(spec.output_types),
                required_tools=[spec.required_tool],
                checkpoint_schema=spec.checkpoint_schema(),
                resume_supported=True,
                rollback_strategy=spec.rollback_strategy,
                sla_seconds=spec.sla_seconds,
            ).to_dict()
            contract.update(_mkaos_operation_contract_fields(spec.operation))
            contracts.append(contract)
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
            checkpoint_schema=spec.checkpoint_schema() if spec else {"version": "0.1.0", "strategy": runner_kind},
            rollback_strategy=spec.rollback_strategy if spec else "agent_rollback_report",
            sla_seconds=spec.sla_seconds if spec else 1800,
        )

    def execute(self, storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
        queue_content = queue_item.get("content", {}) if isinstance(queue_item.get("content", {}), dict) else {}
        run_content = agent_run.get("content", {}) if isinstance(agent_run.get("content", {}), dict) else {}
        evidence = run_content.get("evidence", {}) if isinstance(run_content.get("evidence", {}), dict) else {}
        canonical = _canonical_operation(str(run_content.get("operation", queue_content.get("operation", ""))))
        environment = _environment_from_evidence(evidence)
        spec = self.specs.get(canonical)
        registry_resolution = _resolve_agent_registry_for_scheduler(storage, spec, canonical, environment=environment)
        _attach_agent_registry_resolution(storage, agent_run, registry_resolution)
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
        existing_knowledge_context = _knowledge_context_from_service_result(storage, {"knowledge_context_contract": evidence.get("knowledge_context_contract", {})}, existing_outputs)
        checkpoint = {
            "status": "agent_scheduler_output_reuse",
            "dispatch_id": queue_content.get("dispatch_id", ""),
            "idempotency_key": queue_content.get("idempotency_key", ""),
            "expected_output_assets": expected_outputs,
            "output_assets": existing_outputs,
        }
        if existing_outputs:
            _enforce_operation_knowledge_context(canonical, existing_knowledge_context, environment=environment)
            return {
                "status": "succeeded",
                "output_assets": existing_outputs,
                "token_used": int(queue_content.get("token_used", evidence.get("token_used", 0)) or 0),
                "cost_estimate": float(queue_content.get("cost_estimate", evidence.get("cost_estimate", 0.0)) or 0.0),
                "checkpoint": checkpoint,
                "evidence": {
                    "agent_scheduler": "output_reuse",
                    "dispatch_queue_path": _display_path(storage.root, _queue_path(storage, str(queue_content.get("dispatch_id", "")))),
                    "runtime_policy": evidence.get("runtime_policy", {}) if isinstance(evidence.get("runtime_policy", {}), dict) else {},
                    "context_bundle_path": evidence.get("context_bundle_path", ""),
                    **(
                        {
                            "knowledge_context_contract": existing_knowledge_context,
                            "context_bundle_id": existing_knowledge_context.get("context_bundle_id", ""),
                            "knowledge_pack_id": existing_knowledge_context.get("knowledge_pack_id", ""),
                        }
                        if existing_knowledge_context
                        else {}
                    ),
                    "provider_usage": evidence.get("provider_usage", {}) if isinstance(evidence.get("provider_usage", {}), dict) else {},
                    "provider_runtime_guard": evidence.get("provider_runtime_guard", {}) if isinstance(evidence.get("provider_runtime_guard", {}), dict) else {},
                },
            }
        runner = self.runners.get(canonical)
        if runner:
            checkpoint_resume = _resume_from_checkpoint(storage, queue_item, agent_run, canonical)
            if checkpoint_resume:
                return checkpoint_resume
            _record_operation_checkpoint(
                storage,
                queue_item,
                agent_run,
                status="operation_started",
                state={
                    **checkpoint,
                    "status": "operation_started",
                    "operation": canonical,
                    "runner_kind": "local_service",
                    "input_assets": _input_paths(agent_run),
                    "checkpoint_schema": spec.checkpoint_schema() if spec else {"version": "0.1.0", "strategy": "local_service"},
                },
            )
            try:
                service_result = runner(storage, queue_item, agent_run)
            except Exception as exc:
                _record_operation_checkpoint(
                    storage,
                    queue_item,
                    agent_run,
                    status="agent_scheduler_service_failed",
                    state={
                        **checkpoint,
                        "status": "agent_scheduler_service_failed",
                        "operation": canonical,
                        "runner_kind": "local_service",
                        "input_assets": _input_paths(agent_run),
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                )
                raise
            output_assets = _dedupe(_paths_from_result(storage, service_result))
            if not output_assets:
                raise RuntimeError(f"agent operation {canonical} completed without output assets")
            knowledge_context = _knowledge_context_from_service_result(storage, service_result, output_assets)
            _enforce_operation_knowledge_context(canonical, knowledge_context, environment=environment)
            if knowledge_context:
                run_id = str((agent_run.get("content", {}) if isinstance(agent_run.get("content", {}), dict) else {}).get("run_id", ""))
                if run_id:
                    attach_agent_run_context_contract(storage, _display_path(storage.root, _resolve_agent_run(storage, run_id)), knowledge_context)
            token_used = int(service_result.get("token_used", 0) or sum(len(str(item)) for item in output_assets))
            checkpoint_state = {
                **checkpoint,
                "status": "agent_scheduler_service_completed",
                "operation": canonical,
                "runner_kind": "local_service",
                "idempotency_key": queue_content.get("idempotency_key", ""),
                "input_assets": _input_paths(agent_run),
                "service_result": _json_safe_result(service_result),
                "output_assets": output_assets,
                "checkpoint_schema": spec.checkpoint_schema() if spec else {"version": "0.1.0", "strategy": "local_service"},
            }
            checkpoint_asset = _record_operation_checkpoint(storage, queue_item, agent_run, status="agent_scheduler_service_completed", state=checkpoint_state)
            checkpoint_state["checkpoint_path"] = checkpoint_asset.get("path", "")
            return {
                "status": "succeeded",
                "output_assets": output_assets,
                "token_used": token_used,
                "cost_estimate": float(service_result.get("cost_estimate", 0.0) or 0.0),
                "checkpoint": checkpoint_state,
                "evidence": {
                    "agent_scheduler": "local_service",
                    "agent_operation": canonical,
                    "dispatch_queue_path": _display_path(storage.root, _queue_path(storage, str(queue_content.get("dispatch_id", "")))),
                    "checkpoint_path": checkpoint_asset.get("path", ""),
                    "service_result": _json_safe_result(service_result),
                    **({"knowledge_context_contract": knowledge_context, "context_bundle_id": knowledge_context.get("context_bundle_id", ""), "knowledge_pack_id": knowledge_context.get("knowledge_pack_id", "")} if knowledge_context else {}),
                    "runtime_policy": evidence.get("runtime_policy", {}) if isinstance(evidence.get("runtime_policy", {}), dict) else {},
                    "context_bundle_path": evidence.get("context_bundle_path", ""),
                    "provider_usage": evidence.get("provider_usage", {}) if isinstance(evidence.get("provider_usage", {}), dict) else {},
                    "provider_runtime_guard": evidence.get("provider_runtime_guard", {}) if isinstance(evidence.get("provider_runtime_guard", {}), dict) else {},
                },
            }
        return {
            "status": "waiting_human",
            "message": "agent scheduler has no verified output assets for this prepared AgentRun",
            "checkpoint": checkpoint,
        }

    def rollback(
        self,
        storage: LocalStorage,
        queue_item: dict[str, Any],
        agent_run: dict[str, Any],
        operation_result: dict[str, Any],
        *,
        reason: str,
    ) -> dict[str, Any]:
        queue_content = queue_item.get("content", {}) if isinstance(queue_item.get("content", {}), dict) else {}
        run_content = agent_run.get("content", {}) if isinstance(agent_run.get("content", {}), dict) else {}
        canonical = _canonical_operation(str(run_content.get("operation", queue_content.get("operation", ""))))
        spec = self.specs.get(canonical)
        output_assets = [str(item) for item in operation_result.get("output_assets", []) if str(item).strip()] if isinstance(operation_result.get("output_assets", []), list) else []
        strategy = spec.rollback_strategy if spec else "mark_outputs_rolled_back"
        result = _rollback_operation_outputs(storage, queue_item, agent_run, operation=canonical, output_assets=output_assets, strategy=strategy, reason=reason)
        _record_operation_checkpoint(
            storage,
            queue_item,
            agent_run,
            status="agent_scheduler_rollback_applied",
            state={
                "status": "agent_scheduler_rollback_applied",
                "operation": canonical,
                "idempotency_key": queue_content.get("idempotency_key", ""),
                "output_assets": output_assets,
                "rollback": result,
                "reason": reason,
            },
        )
        return result


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


def mkaos_agent_operation_coverage_report() -> dict[str, Any]:
    contracts = list_agent_operation_contracts()
    by_operation = {str(row.get("operation", "")): row for row in contracts}
    operations: list[dict[str, Any]] = []
    for operation, mode in sorted(CORE_MKAOS_CONTEXT_OPERATIONS.items()):
        contract = by_operation.get(operation, {})
        operations.append(
            {
                "operation": operation,
                "status": "mkaos_required" if mode == "required" else "compat",
                "registered": bool(contract),
                "agent_key": str(contract.get("agent_key", "")),
                "runner_kind": str(contract.get("runner_kind", "")),
                "mkaos_context_required": mode == "required",
                "compat_allowed": mode == "compat",
                "production_bypass_forbidden": mode == "required",
                "context_contract_fields": [
                    "context_bundle_id",
                    "knowledge_pack_id",
                    "source_policy",
                    "source_isolation",
                    "mkaos_flow",
                    "selected_knowledge_ids",
                    "review_rules",
                    "risk_warnings",
                    "selector_policy_version",
                ],
            }
        )
    operation_aliases: list[dict[str, Any]] = []
    for alias, operation in MKAOS_OPERATION_ALIASES.items():
        mode = CORE_MKAOS_CONTEXT_OPERATIONS.get(operation, "")
        contract = by_operation.get(operation, {})
        operation_aliases.append(
            {
                "operation": alias,
                "canonical_operation": operation,
                "status": "mkaos_required" if mode == "required" else ("compat" if mode == "compat" else "not_covered"),
                "registered": bool(contract),
                "mkaos_context_required": mode == "required",
                "compat_allowed": mode == "compat",
                "production_bypass_forbidden": mode == "required",
                "context_contract_fields": [
                    "context_bundle_id",
                    "knowledge_pack_id",
                    "source_policy",
                    "source_isolation",
                    "mkaos_flow",
                    "selected_knowledge_ids",
                    "review_rules",
                    "risk_warnings",
                    "selector_policy_version",
                ],
            }
        )
    return {
        "summary": {
            "operation_count": len(operations),
            "operation_alias_count": len(operation_aliases),
            "registered_count": sum(1 for item in operations if item["registered"]),
            "registered_alias_count": sum(1 for item in operation_aliases if item["registered"]),
            "required_count": sum(1 for item in operations if item["mkaos_context_required"]),
            "compat_count": sum(1 for item in operations if item["compat_allowed"]),
            "production_bypass_forbidden_count": sum(1 for item in operations if item["production_bypass_forbidden"]),
        },
        "operations": operations,
        "operation_aliases": operation_aliases,
        "bypass_policy": "production/strict/operating_system operations cannot bypass Knowledge Context Contract; compat is explicit only",
    }


def create_agent_task(
    storage: LocalStorage,
    *,
    agent_type: str,
    operation: str,
    input_assets: list[str | Path] | None = None,
    output_targets: list[dict[str, Any]] | None = None,
    status: str = "planned",
    project_id: str = "",
    workspace_path: str = "",
    linked_loop_run_path: str = "",
    linked_context_bundle_path: str = "",
    linked_review_issue_path: str = "",
    linked_revision_task_path: str = "",
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    storage.ensure_layout()
    inputs = [_asset_ref(storage, item) for item in input_assets or []]
    task_id = make_id("agent_task", f"{agent_type}-{operation}-{project_id}-{utc_now()}")
    content = {
        "task_id": task_id,
        "agent_type": str(agent_type or "agent"),
        "operation": str(operation or "run"),
        "status": str(status or "planned"),
        "input_assets": inputs,
        "output_targets": output_targets or [],
        "linked_loop_run_path": linked_loop_run_path,
        "linked_context_bundle_path": linked_context_bundle_path,
        "linked_review_issue_path": linked_review_issue_path,
        "linked_revision_task_path": linked_revision_task_path,
        "agent_run_path": "",
        "dispatch_queue_path": "",
        "evidence": evidence or {},
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    asset = AgentTask(
        title=f"{content['agent_type']} task: {content['operation']}",
        source=linked_review_issue_path or linked_revision_task_path or linked_loop_run_path or project_id,
        tags=["agent-task", content["agent_type"], content["operation"], content["status"]],
        content=content,
        metadata={
            "project_id": project_id,
            "workspace_path": workspace_path,
            "agent_type": content["agent_type"],
            "operation": content["operation"],
            "asset_status": content["status"],
            "use_in_generation_rag": False,
        },
        references=filter_project_safe_references(
            storage,
            project_id,
            _dedupe([*[row.get("id", "") for row in inputs], *[row.get("path", "") for row in inputs], linked_loop_run_path, linked_context_bundle_path, linked_review_issue_path, linked_revision_task_path]),
        ),
    )
    _ensure_valid(asset.to_dict())
    path = storage.write_asset("runs", asset)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path)}


def dispatch_revision_task_from_issue(
    storage: LocalStorage,
    issue_ref: str | Path,
    *,
    agent_type: str = "review",
    operation: str = "fix_review_issue",
    token_budget: int = 1200,
    priority: int = 40,
) -> dict[str, Any]:
    issue_path, issue = _find_review_issue_asset(storage, issue_ref)
    content = issue.get("content", {}) if isinstance(issue.get("content", {}), dict) else {}
    metadata = issue.get("metadata", {}) if isinstance(issue.get("metadata", {}), dict) else {}
    project_id = str(metadata.get("project_id") or content.get("project_id") or "")
    workspace_path = str(metadata.get("workspace_path") or content.get("workspace_path") or "")
    issue_display_path = _display_path(storage.root, issue_path)
    candidate = review_issue_to_revision_task_candidate({"content": content})
    revision_task = _create_revision_task_from_review_issue(storage, issue_path=issue_path, issue=issue, candidate=candidate)
    task = create_agent_task(
        storage,
        agent_type=agent_type,
        operation=operation,
        input_assets=[issue_display_path],
        output_targets=[{**candidate, "revision_task_path": revision_task["path"]}],
        status="queued",
        project_id=project_id,
        workspace_path=workspace_path,
        linked_review_issue_path=issue_display_path,
        linked_revision_task_path=revision_task["path"],
        evidence={"dispatch_source": "agent_center", "revision_task_candidate": candidate},
    )
    run = start_agent_run(
        storage,
        agent_key=agent_type,
        operation=operation,
        input_assets=[issue_display_path],
        status="prepared",
        workspace_path=workspace_path or None,
        token_budget=token_budget,
        evidence={
            "agent_task_path": task["path"],
            "review_issue_path": issue_display_path,
            "revision_task_path": revision_task["path"],
            "revision_task_candidate": candidate,
            "expected_output_assets": [],
        },
    )
    queue = dispatch_agent_run(storage, agent_run_path=run["path"], expected_output_assets=[], priority=priority)
    _update_agent_task_links(storage, task["path"], status="queued", agent_run_path=run["path"], dispatch_queue_path=queue["path"])
    return {
        "status": "queued",
        "agent_task_path": task["path"],
        "agent_run_path": run["path"],
        "dispatch_queue_path": queue["path"],
        "review_issue_path": issue_display_path,
        "revision_task_path": revision_task["path"],
        "revision_task_candidate": candidate,
    }


def agent_center_snapshot(
    storage: LocalStorage,
    *,
    project_id: str | None = None,
    limit: int = 300,
) -> dict[str, Any]:
    """Operator-grade Agent Center aggregation.

    The scheduler owns execution. This snapshot gives the UI and acceptance
    tests one evidence payload for autonomy readiness, recovery, gates,
    checkpoints, budgets, failures, rollback, and queue health.
    """

    storage.ensure_layout()
    contracts = list_agent_operation_contracts()
    tasks = _agent_center_assets(storage, "agent_task", project_id=project_id, limit=limit)
    linked_run_paths = _task_linked_paths(tasks, "agent_run_path")
    linked_queue_paths = _task_linked_paths(tasks, "dispatch_queue_path")
    queue = list_agent_dispatch_queue(storage, project_id=project_id, limit=limit)
    if project_id and linked_queue_paths:
        linked_queue = [row for row in list_agent_dispatch_queue(storage, limit=limit) if str(row.get("path", "")) in linked_queue_paths]
        queue = _merge_queue_rows(queue, linked_queue)
    runs = _agent_center_assets(storage, "agent_run", project_id=project_id, limit=limit)
    if project_id and linked_run_paths:
        runs = _merge_asset_rows(runs, _agent_center_assets_by_paths(storage, linked_run_paths, asset_type="agent_run"))
    events = _agent_center_assets(storage, "agent_event", project_id=project_id, limit=limit)
    checkpoints = _agent_center_assets(storage, "agent_checkpoint", project_id=project_id, limit=limit)
    gates = _agent_center_assets(storage, "agent_gate", project_id=project_id, limit=limit)
    budgets = _agent_center_assets(storage, "agent_budget", project_id=project_id, limit=limit)
    failures = _agent_center_assets(storage, "agent_failure_report", project_id=project_id, limit=limit)
    rollbacks = _agent_center_assets(storage, "agent_rollback_report", project_id=project_id, limit=limit)
    handoffs = _agent_center_assets(storage, "agent_handoff", project_id=project_id, limit=limit)
    loops = _agent_center_category_assets(storage, "loops", {"loop_run"}, project_id=project_id, limit=limit)
    linked_context_paths = _task_linked_paths(loops, "context_bundle_path")
    contexts = _agent_center_category_assets(storage, "contexts", {"context_bundle"}, project_id=project_id, limit=limit)
    if project_id and linked_context_paths:
        contexts = _merge_asset_rows(contexts, _agent_center_assets_by_paths(storage, linked_context_paths, asset_type="context_bundle"))
    review_issues = _agent_center_category_assets(storage, "reviews", {"review_issue"}, project_id=project_id, limit=limit)
    revision_tasks = _agent_center_category_assets(storage, "reviews", {"revision_task"}, project_id=project_id, limit=limit)
    by_status: dict[str, int] = {}
    for row in queue:
        by_status[str(row.get("status", ""))] = by_status.get(str(row.get("status", "")), 0) + 1
    blocked_queue = [row for row in queue if str(row.get("status", "")) in {"waiting_human", "dead_letter", "retry_scheduled", "cancelled"}]
    task_rows = [_agent_task_row(row) for row in tasks]
    run_rows = [_agent_run_summary(row) for row in runs]
    loop_rows = [_loop_run_row(row) for row in loops]
    context_rows = [_context_bundle_row(row) for row in contexts]
    review_issue_rows = [_review_issue_row(row) for row in review_issues]
    revision_task_rows = [_revision_task_row(row) for row in revision_tasks]
    checkpoint_rows = [_agent_checkpoint_row(row) for row in checkpoints]
    gate_rows = [_agent_gate_row(row) for row in gates]
    budget_summary = _budget_coverage(budgets)
    rollback_rows = [_agent_asset_compact(row) for row in rollbacks]
    health_score = _agent_center_health_score(queue, runs, checkpoints, gates, budgets, failures, rollbacks, contracts)
    readiness_checks = [
        _agent_center_check("operation_contracts", bool(contracts), "Agent operation contracts are registered", "register at least one operation contract"),
        _agent_center_check("dispatch_queue", bool(queue) or bool(runs), "Agent queue or run evidence exists", "create an agent_run and dispatch it"),
        _agent_center_check("checkpoints", bool(checkpoints), "Agent checkpoints exist", "run scheduler or execute_agent_run_once with checkpointing"),
        _agent_center_check("gates", bool(gates), "Agent gate evidence exists", "record permission/schema/budget gates"),
        _agent_center_check("budgets", bool(budgets), "Agent budget evidence exists", "attach token/cost budgets to AgentRun"),
        _agent_center_check("context_bundles", bool(contexts), "ContextBundle evidence is visible to Agent Center", "route agent work through Context Builder"),
        _agent_center_check("review_issues", bool(review_issues) or not revision_tasks, "ReviewIssue evidence is visible or no revision task exists", "persist issues before dispatching revision tasks"),
        _agent_center_check("loop_runs", bool(loops) or not tasks, "LoopRun evidence is visible or no agent task requires a loop", "run Loop Kernel for governed generation/review work"),
        _agent_center_check("rollback", bool(rollbacks) or not failures, "Rollback evidence exists or no failures need rollback", "create rollback report for failed agent outputs"),
    ]
    status = "blocked" if blocked_queue or failures else "warning" if any(check["status"] == "warning" for check in readiness_checks) else "ready"
    recommendations = _agent_center_recommendations(status, blocked_queue, failures, readiness_checks)
    return {
        "status": status,
        "project_id": project_id or "",
        "health_score": health_score,
        "summary": {
            "health_score": health_score,
            "agent_run_count": len(runs),
            "agent_task_count": len(tasks),
            "queue_count": len(queue),
            "loop_run_count": len(loops),
            "context_bundle_count": len(contexts),
            "review_issue_count": len(review_issues),
            "revision_task_count": len(revision_tasks),
            "handoff_count": len(handoffs),
            "blocked_queue_count": len(blocked_queue),
            "checkpoint_count": len(checkpoints),
            "gate_count": len(gates),
            "budget_count": len(budgets),
            "failure_count": len(failures),
            "rollback_count": len(rollbacks),
            "contract_count": len(contracts),
            "queue_by_status": by_status,
        },
        "readiness_checks": readiness_checks,
        "run_graph": _agent_run_graph(run_rows, queue, tasks=task_rows, loops=loop_rows),
        "agent_tasks": task_rows[:120],
        "loop_runs": loop_rows[:120],
        "context_bundles": context_rows[:120],
        "review_issues": review_issue_rows[:120],
        "revision_tasks": revision_task_rows[:120],
        "handoffs": [_agent_asset_compact(row) for row in handoffs[:120]],
        "runtime_links": _agent_runtime_links(task_rows, run_rows, loop_rows, context_rows, review_issue_rows, revision_task_rows),
        "gate_timeline": gate_rows[:120],
        "checkpoints": checkpoint_rows[:120],
        "budget_burn": budget_summary,
        "retry_controls": [row for row in blocked_queue if str(row.get("status", "")) in {"waiting_human", "retry_scheduled", "dead_letter"}][:80],
        "dead_letter_queue": [row for row in blocked_queue if str(row.get("status", "")) == "dead_letter"][:80],
        "rollback_preview": rollback_rows[:80],
        "sla_duration": _agent_sla_duration_rows(run_rows),
        "evidence_drawer": _agent_evidence_drawer(events, checkpoints, gates, budgets, failures, rollbacks, tasks, loops, contexts, review_issues, revision_tasks, handoffs)[:220],
        "operation_coverage": contracts,
        "blocked_queue": blocked_queue[:80],
        "runs": run_rows[:80],
        "recent_events": [_agent_asset_compact(row) for row in events[:80]],
        "checkpoint_coverage": _checkpoint_coverage(checkpoints),
        "gate_coverage": _gate_coverage(gates),
        "budget_coverage": budget_summary,
        "failure_recovery": _failure_recovery_rows(failures, rollbacks),
        "contracts": contracts,
        "recommended_actions": recommendations,
        "recommendations": recommendations,
        "created_at": utc_now(),
    }


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
    failure_reason = _execution_error_message(execution)
    rollback = OPERATION_REGISTRY.rollback(storage, queue_data, run, operation_result, reason=failure_reason)
    failure = _fail_queue_item(
        storage,
        queue_path,
        reason=failure_reason,
        retry_delay_seconds=retry_delay_seconds,
        result={**operation_result, "execution": execution, "rollback": rollback},
    )
    return {"queue_status": failure.get("status", ""), "queue": failure, "agent_run_path": _display_path(storage.root, run_path), "execution": execution, "rollback": rollback}


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


def _fail_queue_item(storage: LocalStorage, queue_path: str | Path, *, reason: str, retry_delay_seconds: int = 0, result: dict[str, Any] | None = None) -> dict[str, Any]:
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
        updates = {"dead_lettered_at": utc_now(), "last_error": reason}
        if result is not None:
            updates["result"] = result
        return _update_queue_item(storage, path, status="dead_letter", updates=updates)
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
    updates = {"available_at": _utc_datetime_after(max(0, retry_delay_seconds)), "last_error": reason}
    if result is not None:
        updates["result"] = result
    return _update_queue_item(storage, path, status="retry_scheduled", updates=updates)


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


def _record_operation_checkpoint(
    storage: LocalStorage,
    queue_item: dict[str, Any],
    agent_run: dict[str, Any],
    *,
    status: str,
    state: dict[str, Any],
) -> dict[str, Any]:
    queue_content = queue_item.get("content", {}) if isinstance(queue_item.get("content", {}), dict) else {}
    agent_run_path = str(queue_content.get("agent_run_path", ""))
    if not agent_run_path:
        return {}
    return record_agent_checkpoint(
        storage,
        agent_run_path=agent_run_path,
        status=status,
        state={
            **state,
            "dispatch_id": queue_content.get("dispatch_id", ""),
            "idempotency_key": queue_content.get("idempotency_key", state.get("idempotency_key", "")),
            "recorded_by": "agent_operation_registry",
        },
    )


def _resume_from_checkpoint(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any], operation: str) -> dict[str, Any] | None:
    queue_content = queue_item.get("content", {}) if isinstance(queue_item.get("content", {}), dict) else {}
    state = _checkpoint_state(storage, agent_run)
    if not state:
        return None
    if str(state.get("status", "")) != "agent_scheduler_service_completed":
        return None
    state_operation = _canonical_operation(str(state.get("operation", "")))
    if state_operation and state_operation != operation:
        return None
    output_assets = _dedupe([str(item) for item in state.get("output_assets", []) if str(item).strip()] if isinstance(state.get("output_assets", []), list) else [])
    reusable_outputs = [item for item in output_assets if _output_asset_reusable(storage, item)]
    if len(reusable_outputs) != len(output_assets) or not reusable_outputs:
        return None
    token_used = int(state.get("token_used", 0) or sum(len(str(item)) for item in reusable_outputs))
    return {
        "status": "succeeded",
        "output_assets": reusable_outputs,
        "token_used": token_used,
        "cost_estimate": float(state.get("cost_estimate", 0.0) or 0.0),
        "checkpoint": {
            **state,
            "status": "agent_scheduler_service_completed",
            "resumed_from_checkpoint": True,
            "checkpoint_path": _checkpoint_path(agent_run),
        },
        "evidence": {
            "agent_scheduler": "checkpoint_resume",
            "agent_operation": operation,
            "dispatch_queue_path": _display_path(storage.root, _queue_path(storage, str(queue_content.get("dispatch_id", "")))),
            "checkpoint_path": _checkpoint_path(agent_run),
            "resume_from_checkpoint": True,
        },
    }


def _checkpoint_state(storage: LocalStorage, agent_run: dict[str, Any]) -> dict[str, Any]:
    content = agent_run.get("content", {}) if isinstance(agent_run.get("content", {}), dict) else {}
    checkpoint = content.get("checkpoint", {}) if isinstance(content.get("checkpoint", {}), dict) else {}
    if "state" in checkpoint and isinstance(checkpoint.get("state"), dict):
        return checkpoint.get("state", {})
    if str(checkpoint.get("status", "")):
        return checkpoint
    path_value = str(checkpoint.get("path", ""))
    if path_value:
        data = _read_json_safe(storage, resolve_path(storage.root, path_value))
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        state = content.get("state", {}) if isinstance(content.get("state", {}), dict) else {}
        return state
    return {}


def _checkpoint_path(agent_run: dict[str, Any]) -> str:
    content = agent_run.get("content", {}) if isinstance(agent_run.get("content", {}), dict) else {}
    checkpoint = content.get("checkpoint", {}) if isinstance(content.get("checkpoint", {}), dict) else {}
    return str(checkpoint.get("path", ""))


def _output_asset_reusable(storage: LocalStorage, value: str) -> bool:
    if not _path_exists(storage, value):
        return False
    data = _read_json_safe(storage, resolve_path(storage.root, value))
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    asset_status = str(metadata.get("asset_status", "")).lower()
    rollback_status = str(metadata.get("rollback_status", "")).lower()
    return asset_status not in {"quarantined", "rolled_back"} and rollback_status not in {"rolled_back", "rollback_required"}


def _rollback_operation_outputs(
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
            if manual_required:
                target_metadata["asset_status"] = "rollback_required"
            else:
                target_metadata["asset_status"] = "rolled_back"
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
    except Exception:
        pass
    return result


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
            aliases=("analysis-conversion", "convert"),
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
            rollback_strategy="rollback_patch_available",
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
            operation="create-novel-kg-snapshot",
            aliases=("novel-kg-snapshot", "novel_kg_snapshot"),
            runner=_run_novel_kg_snapshot,
            agent_key="continuity",
            input_types=(),
            output_types=("novel_kg_snapshot",),
            required_tool="write_novel_kg_snapshot",
            sla_seconds=900,
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
            rollback_strategy="manual_reconciliation_required",
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
            aliases=("publish-gate-report", "publish-gate"),
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
        AgentOperationSpec(
            operation="resolve-model-route",
            aliases=("model-route-resolution", "model_router_resolve"),
            runner=_run_resolve_model_route,
            agent_key="model_evaluation",
            input_types=(),
            output_types=("model_route_resolution",),
            required_tool="write_model_routing_policy",
            sla_seconds=120,
        ),
        AgentOperationSpec(
            operation="invoke-tool",
            aliases=("tool-invoke", "tool_gateway_invoke"),
            runner=_run_invoke_tool,
            agent_key="engineering",
            input_types=(),
            output_types=("tool_invocation",),
            required_tool="run_validation",
            sla_seconds=300,
        ),
        AgentOperationSpec(
            operation="record-state-event",
            aliases=("state-event",),
            runner=_run_record_state_event,
            agent_key="workflow",
            input_types=(),
            output_types=("state_event",),
            required_tool="run_validation",
            checkpoint_strategy="event_append",
            sla_seconds=120,
        ),
        AgentOperationSpec(
            operation="send-agent-message",
            aliases=("agent-message",),
            runner=_run_send_agent_message,
            agent_key="workflow",
            input_types=(),
            output_types=("agent_message", "agent_inbox", "agent_outbox"),
            required_tool="run_validation",
            checkpoint_strategy="event_append",
            sla_seconds=120,
        ),
        AgentOperationSpec(
            operation="select-memory",
            aliases=("memory-selection",),
            runner=_run_select_memory,
            agent_key="knowledge",
            input_types=(),
            output_types=("memory_selection",),
            required_tool="read_asset",
            sla_seconds=120,
        ),
        AgentOperationSpec(
            operation="hybrid-retrieve",
            aliases=("hybrid-retrieval", "pgvector-retrieve"),
            runner=_run_hybrid_retrieve,
            agent_key="knowledge",
            input_types=(),
            output_types=("hybrid_retrieval_report",),
            required_tool="read_asset",
            sla_seconds=120,
        ),
        AgentOperationSpec(
            operation="build-context-bundle",
            aliases=("context-build", "context_builder", "build-context"),
            runner=_run_build_context_bundle,
            agent_key="context",
            input_types=(),
            output_types=("context_bundle",),
            required_tool="write_context_bundle",
            sla_seconds=300,
        ),
        AgentOperationSpec(
            operation="check-canon-graph",
            aliases=("canon-graph-check", "canon-conflict-check"),
            runner=_run_check_canon_graph,
            agent_key="continuity",
            input_types=(),
            output_types=("canon_graph_snapshot", "review_issue"),
            required_tool="write_review_issue",
            sla_seconds=300,
        ),
        AgentOperationSpec(
            operation="run-review-revision-publish-loop",
            aliases=("review-revision-publish-loop", "main-review-loop"),
            runner=_run_review_revision_publish_loop,
            agent_key="workflow",
            input_types=("draft_chapter", "draft_version"),
            output_types=("loop_run", "loop_report", "review_report", "revision_plan", "publish_gate_report"),
            required_tool="run_validation",
            sla_seconds=900,
        ),
        AgentOperationSpec(
            operation="run-longform-recap",
            aliases=("longform-recap", "recap"),
            runner=_run_longform_recap,
            agent_key="workflow",
            input_types=("draft_chapter", "draft_version"),
            output_types=("longform_recap_report", "revision_task"),
            required_tool="run_validation",
            sla_seconds=900,
        ),
        AgentOperationSpec(
            operation="create-feedback-backflow-plan",
            aliases=("feedback-backflow",),
            runner=_run_create_feedback_backflow_plan,
            agent_key="feedback",
            input_types=("reader_feedback", "reader_sentiment_report", "reader_feedback_backflow_report"),
            output_types=("feedback_backflow_plan", "feedback_cluster", "plan_adjustment_proposal", "review_rule_update_proposal", "feedback_kg_patch"),
            required_tool="create_feedback_backflow_plan",
            sla_seconds=600,
        ),
        AgentOperationSpec(
            operation="process-real-feedback-backflow",
            aliases=("real-feedback-backflow",),
            runner=_run_process_real_feedback_backflow,
            agent_key="feedback",
            input_types=("release_package", "operational_metric_snapshot"),
            output_types=("reader_feedback_backflow_report", "platform_feedback_backflow", "review_rule_pack", "topic_seed", "writing_template"),
            required_tool="write_reader_feedback_backflow_report",
            sla_seconds=600,
        ),
        AgentOperationSpec(
            operation="preview-provider-fallback",
            aliases=("provider-fallback-preview",),
            runner=_run_preview_provider_fallback,
            agent_key="model_evaluation",
            input_types=(),
            output_types=("gate_result", "model_route_resolution"),
            required_tool="write_gate_result",
            sla_seconds=120,
        ),
        AgentOperationSpec(
            operation="approve-provider-fallback",
            aliases=("provider-fallback-approval",),
            runner=_run_approve_provider_fallback,
            agent_key="model_evaluation",
            input_types=("gate_result",),
            output_types=("gate_result",),
            required_tool="write_gate_result",
            sla_seconds=120,
        ),
    ]


def _run_decompose(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.decomposition import decompose

    evidence = _evidence(agent_run)
    return {"path": decompose(storage, _required_input_path(agent_run), environment=str(evidence.get("environment") or ""), os_envelope=_envelope_from_evidence(evidence))}


def _run_build_materials(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.materials import build_materials

    return {"path": build_materials(storage, _required_input_path(agent_run))}


def _run_generate_outline(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.outline import generate_outline

    evidence = _evidence(agent_run)
    return {"path": generate_outline(storage, _required_input_path(agent_run), workspace_path=_workspace_path(agent_run), environment=str(evidence.get("environment") or ""), os_envelope=_envelope_from_evidence(evidence))}


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
            environment=str(evidence.get("environment") or ""),
            os_envelope=_envelope_from_evidence(evidence),
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
            environment=str(evidence.get("environment") or ""),
            os_envelope=_envelope_from_evidence(evidence),
        )
    }


def _run_review(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.review import review

    evidence = _evidence(agent_run)
    return {"path": review(storage, _required_input_path(agent_run), environment=str(evidence.get("environment") or ""), os_envelope=_envelope_from_evidence(evidence))}


def _run_revise(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.revision import revise

    evidence = _evidence(agent_run)
    return {"path": revise(storage, _required_input_path(agent_run), environment=str(evidence.get("environment") or ""), os_envelope=_envelope_from_evidence(evidence))}


def _run_analysis(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.analysis import run_analysis

    evidence = _evidence(agent_run)
    return run_analysis(storage, _required_input_path(agent_run), str(evidence.get("analysis_type", "common")), workspace_path=_workspace_path(agent_run), environment=str(evidence.get("environment") or ""), os_envelope=_envelope_from_evidence(evidence))


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
        environment=str(evidence.get("environment") or ""),
        os_envelope=_envelope_from_evidence(evidence),
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
        environment=str(evidence.get("environment") or ""),
        os_envelope=_envelope_from_evidence(evidence),
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
        environment=str(evidence.get("environment") or ""),
        os_envelope=_envelope_from_evidence(evidence),
        source_policy=evidence.get("source_policy") if isinstance(evidence.get("source_policy"), dict) else None,
    )


def _run_continuity_graph_snapshot(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.continuity_graph import create_continuity_graph_snapshot

    return create_continuity_graph_snapshot(storage, project_id=_project_id(agent_run) or None, workspace_path=_workspace_path(agent_run) or None)


def _run_canon_graph_snapshot(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.continuity_graph import create_canon_graph_snapshot

    return create_canon_graph_snapshot(storage, project_id=_project_id(agent_run) or None, workspace_path=_workspace_path(agent_run) or None)


def _run_novel_kg_snapshot(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.novel_kg import create_novel_kg_snapshot

    evidence = _evidence(agent_run)
    return create_novel_kg_snapshot(
        storage,
        project_id=_project_id(agent_run) or None,
        workspace_path=_workspace_path(agent_run) or None,
        limit=int(evidence.get("limit", 1000) or 1000),
        include_content_snapshot=bool(evidence.get("include_content_snapshot", False)),
    )


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
            environment=str(evidence.get("environment") or ""),
            envelope=_envelope_from_evidence(evidence),
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


def _run_resolve_model_route(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.model_router import resolve_model_route

    evidence = _evidence(agent_run)
    return resolve_model_route(
        storage,
        task_type=str(evidence.get("task_type") or "generate"),
        project_id=_project_id(agent_run),
        workspace_path=_workspace_path(agent_run),
        prompt_id=str(evidence.get("prompt_id") or ""),
        prompt_version=str(evidence.get("prompt_version") or ""),
        workflow_node_id=str(evidence.get("workflow_node_id") or ""),
        trace=evidence.get("trace", {}) if isinstance(evidence.get("trace", {}), dict) else {},
        persist=True,
    )


def _run_invoke_tool(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.tool_gateway import invoke_tool

    evidence = _evidence(agent_run)
    return invoke_tool(
        storage,
        tool_name=str(evidence.get("tool_name") or ""),
        input_payload=evidence.get("input_payload", {}) if isinstance(evidence.get("input_payload", {}), dict) else {},
        agent_type=str(evidence.get("agent_type") or _project_id(agent_run) or ""),
        operation=str(evidence.get("tool_operation") or ""),
        project_id=_project_id(agent_run),
        workspace_path=_workspace_path(agent_run),
        trace=evidence.get("trace", {}) if isinstance(evidence.get("trace", {}), dict) else {},
        enforce_permissions=bool(evidence.get("enforce_permissions", True)),
    )


def _run_record_state_event(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.state_bus import record_state_event

    evidence = _evidence(agent_run)
    return record_state_event(
        storage,
        stream=str(evidence.get("stream") or "agent"),
        subject_id=str(evidence.get("subject_id") or _project_id(agent_run) or ""),
        event_type=str(evidence.get("event_type") or "updated"),
        payload=evidence.get("payload", {}) if isinstance(evidence.get("payload", {}), dict) else {},
        expected_version=int(evidence["expected_version"]) if evidence.get("expected_version") is not None else None,
        project_id=_project_id(agent_run),
        workspace_path=_workspace_path(agent_run),
        trace=evidence.get("trace", {}) if isinstance(evidence.get("trace", {}), dict) else {},
    )


def _run_send_agent_message(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.agent_messages import send_agent_message

    evidence = _evidence(agent_run)
    return send_agent_message(
        storage,
        sender_agent=str(evidence.get("sender_agent") or "workflow"),
        recipient_agent=str(evidence.get("recipient_agent") or "chief_editor"),
        topic=str(evidence.get("topic") or "agent_update"),
        payload=evidence.get("payload", {}) if isinstance(evidence.get("payload", {}), dict) else {},
        conversation_id=str(evidence.get("conversation_id") or ""),
        priority=int(evidence.get("priority", 5) or 5),
        project_id=_project_id(agent_run),
        workspace_path=_workspace_path(agent_run),
        trace=evidence.get("trace", {}) if isinstance(evidence.get("trace", {}), dict) else {},
    )


def _run_select_memory(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.long_memory import select_memory_for_node

    evidence = _evidence(agent_run)
    return select_memory_for_node(
        storage,
        target_node=str(evidence.get("target_node") or evidence.get("workflow_node_id") or ""),
        task_type=str(evidence.get("task_type") or "workflow"),
        project_id=_project_id(agent_run),
        query=str(evidence.get("query") or ""),
        max_items=int(evidence.get("max_items", 12) or 12),
        trace=evidence.get("trace", {}) if isinstance(evidence.get("trace", {}), dict) else {},
    )


def _run_hybrid_retrieve(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.pgvector_store import hybrid_retrieve

    evidence = _evidence(agent_run)
    return hybrid_retrieve(
        storage,
        query=str(evidence.get("query") or ""),
        project_id=_project_id(agent_run),
        retrieval_backend=str(evidence.get("retrieval_backend") or "hybrid"),
        limit=int(evidence.get("limit", 12) or 12),
        levels=[str(item) for item in evidence.get("levels", [])] if isinstance(evidence.get("levels", []), list) else [],
        persist=True,
    )


def _run_build_context_bundle(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.context_builder import build_flow_context_bundle

    evidence = _evidence(agent_run)
    target_path = str(evidence.get("target_path") or _primary_input_path(agent_run))
    if not target_path:
        raise ValueError("build-context-bundle requires target_path or one input asset")
    budget = evidence.get("budget", {}) if isinstance(evidence.get("budget", {}), dict) else {}
    return build_flow_context_bundle(
        storage,
        target_path,
        flow=str(evidence.get("flow") or evidence.get("task_type") or "prose"),
        project_id=_project_id(agent_run),
        workspace_path=_workspace_path(agent_run),
        chapter_id=str(evidence.get("chapter_id") or ""),
        current_goal=str(evidence.get("current_goal") or "agent context build"),
        query=str(evidence.get("query") or ""),
        top_k=int(evidence.get("top_k", 8) or 8),
        token_budget=int(budget.get("max_tokens", evidence.get("token_budget", 4000)) or 4000),
        source_policy=evidence.get("source_policy", {}) if isinstance(evidence.get("source_policy", {}), dict) else {},
        environment=str(evidence.get("environment") or ""),
        os_envelope=evidence.get("os_envelope") if isinstance(evidence.get("os_envelope"), dict) else evidence.get("envelope") if isinstance(evidence.get("envelope"), dict) else None,
    )


def _run_check_canon_graph(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.canon_graph import persist_canon_graph_issues

    evidence = _evidence(agent_run)
    payload = {
        **evidence,
        "target_path": evidence.get("target_path") or _primary_input_path(agent_run),
        "project_id": _project_id(agent_run) or evidence.get("project_id", ""),
        "workspace_path": _workspace_path(agent_run) or evidence.get("workspace_path", ""),
    }
    return persist_canon_graph_issues(storage, payload)


def _run_review_revision_publish_loop(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.loop_kernel import run_loop

    evidence = _evidence(agent_run)
    return run_loop(
        storage,
        {
            **evidence,
            "loop_type": "review_revision_publish",
            "target_path": evidence.get("target_path") or _primary_input_path(agent_run),
            "project_id": _project_id(agent_run) or evidence.get("project_id", ""),
            "workspace_path": _workspace_path(agent_run) or evidence.get("workspace_path", ""),
            "bypass_reason": str(evidence.get("bypass_reason") or "agent center governed local loop"),
        },
    )


def _run_longform_recap(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.longform_recap import run_longform_recap

    evidence = _evidence(agent_run)
    return run_longform_recap(
        storage,
        {
            **evidence,
            "project_id": _project_id(agent_run) or evidence.get("project_id", ""),
            "workspace_path": _workspace_path(agent_run) or evidence.get("workspace_path", ""),
            "environment": str(evidence.get("environment") or ""),
            "envelope": _envelope_from_evidence(evidence),
            "force": bool(evidence.get("force", True)),
        },
    )


def _run_create_feedback_backflow_plan(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.feedback_backflow import create_feedback_backflow_plan

    evidence = _evidence(agent_run)
    return create_feedback_backflow_plan(
        storage,
        feedback_paths=_input_paths(agent_run),
        project_id=_project_id(agent_run) or evidence.get("project_id", ""),
        workspace_path=_workspace_path(agent_run) or evidence.get("workspace_path", ""),
        require_human_gate=bool(evidence.get("require_human_gate", True)),
        environment=str(evidence.get("environment") or ""),
        os_envelope=_envelope_from_evidence(evidence),
    )


def _run_process_real_feedback_backflow(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.feedback import process_real_feedback_backflow

    evidence = _evidence(agent_run)
    metrics = evidence.get("metrics", {}) if isinstance(evidence.get("metrics", {}), dict) else {}
    if not metrics:
        metrics = {"completion_rate": 0.75, "follow_read_rate": 0.6, "comments": [], "favorites": 0, "bookshelf_adds": 0}
    return process_real_feedback_backflow(
        storage,
        metrics=metrics,
        project_id=_project_id(agent_run) or evidence.get("project_id", ""),
        workspace_path=_workspace_path(agent_run) or evidence.get("workspace_path", ""),
        platform=str(evidence.get("platform") or "qidian"),
        release_package_path=_primary_input_path(agent_run) or None,
        apply_mkaos_weight_update=bool(evidence.get("apply_mkaos_weight_update", True)),
        environment=str(evidence.get("environment") or ""),
        os_envelope=_envelope_from_evidence(evidence),
    )


def _run_preview_provider_fallback(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.provider_fallback import preview_provider_fallback

    evidence = _evidence(agent_run)
    return preview_provider_fallback(
        storage,
        {
            **evidence,
            "project_id": _project_id(agent_run) or evidence.get("project_id", ""),
            "workspace_path": _workspace_path(agent_run) or evidence.get("workspace_path", ""),
        },
    )


def _run_approve_provider_fallback(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.provider_fallback import approve_provider_fallback

    evidence = _evidence(agent_run)
    return approve_provider_fallback(
        storage,
        {
            **evidence,
            "project_id": _project_id(agent_run) or evidence.get("project_id", ""),
            "workspace_path": _workspace_path(agent_run) or evidence.get("workspace_path", ""),
        },
    )


def _input_paths(agent_run: dict[str, Any]) -> list[str]:
    content = agent_run.get("content", {}) if isinstance(agent_run.get("content", {}), dict) else {}
    rows = content.get("input_assets", []) if isinstance(content.get("input_assets", []), list) else []
    paths = [str(row.get("path", "")) for row in rows if isinstance(row, dict) and str(row.get("path", "")).strip()]
    return _dedupe(paths)


def _asset_ref(storage: LocalStorage, item: str | Path) -> dict[str, Any]:
    path = resolve_path(storage.root, item)
    try:
        data = storage.read_json(path)
    except Exception:
        return {"id": str(item), "type": "", "path": str(item), "title": ""}
    if not isinstance(data, dict):
        return {"id": str(item), "type": "", "path": str(item), "title": ""}
    return {
        "id": str(data.get("id", "")),
        "type": str(data.get("type", "")),
        "path": _display_path(storage.root, path),
        "title": str(data.get("title") or data.get("name") or ""),
    }


def _find_review_issue_asset(storage: LocalStorage, issue_ref: str | Path) -> tuple[Path, dict[str, Any]]:
    direct = resolve_path(storage.root, issue_ref)
    if direct.exists():
        data = storage.read_json(direct)
        if isinstance(data, dict) and data.get("type") == "review_issue":
            return direct, data
    wanted = str(issue_ref)
    for path in storage.list_json("reviews"):
        data = _read_json_safe(storage, path)
        if data.get("type") != "review_issue":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        candidates = {
            str(data.get("id", "")),
            str(content.get("issue_id", "")),
            _display_path(storage.root, path),
        }
        if wanted in candidates:
            return path, data
    raise FileNotFoundError(f"review_issue not found: {issue_ref}")


def _create_revision_task_from_review_issue(
    storage: LocalStorage,
    *,
    issue_path: Path,
    issue: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    content = issue.get("content", {}) if isinstance(issue.get("content", {}), dict) else {}
    metadata = issue.get("metadata", {}) if isinstance(issue.get("metadata", {}), dict) else {}
    project_id = str(metadata.get("project_id") or content.get("project_id") or "")
    workspace_path = str(metadata.get("workspace_path") or content.get("workspace_path") or "")
    issue_id = str(content.get("issue_id") or issue.get("id") or "")
    issue_display_path = _display_path(storage.root, issue_path)
    now = utc_now()
    task_id = make_id("revision_task", f"agent-center-{issue_id}-{now}")
    review_path = str(content.get("review_report_path") or metadata.get("review_report_path") or issue_display_path)
    draft_path = str(content.get("target_asset_path") or candidate.get("target_asset_path") or "")
    task_content = {
        "task_id": task_id,
        "review_id": str(content.get("review_report_id") or ""),
        "review_path": review_path,
        "source_draft_id": str(content.get("target_asset_id") or candidate.get("target_asset_id") or ""),
        "source_draft_path": draft_path,
        "issue_indexes": [0],
        "review_issue_ids": [issue_id],
        "issues": [
            {
                "issue_id": issue_id,
                "issue_type": content.get("issue_type", candidate.get("issue_type", "")),
                "severity": content.get("severity", candidate.get("severity", "")),
                "message": content.get("message", ""),
                "fix_suggestion": content.get("fix_suggestion", candidate.get("instructions", "")),
                "blocking": bool(content.get("blocking", candidate.get("blocking", False))),
                "review_issue_path": issue_display_path,
            }
        ],
        "status": "open",
        "stage": "agent_center_dispatch",
        "outputs": {"revision_task_candidate": candidate},
        "created_at": now,
        "updated_at": now,
    }
    asset = RevisionTask(
        title=f"Revision task for {issue_id or issue.get('title', 'review issue')}",
        source=issue_id,
        tags=["revision", "task", "review-issue", "agent-center"],
        content=task_content,
        metadata={
            "project_id": project_id,
            "workspace_path": workspace_path,
            "source_review_issue_path": issue_display_path,
            "source_draft_path": draft_path,
            "agent_center_dispatch": True,
        },
        references=filter_project_safe_references(
            storage,
            project_id,
            _dedupe([issue_id, issue_display_path, review_path, draft_path]),
        ),
    )
    _ensure_valid(asset.to_dict())
    path = storage.write_asset("reviews", asset)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path)}


def _update_agent_task_links(storage: LocalStorage, task_ref: str | Path, **updates: Any) -> dict[str, Any]:
    path = resolve_path(storage.root, task_ref)
    data = storage.read_json(path)
    if not isinstance(data, dict) or data.get("type") != "agent_task":
        raise ValueError("task_ref must point to an agent_task asset")
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    for key, value in updates.items():
        if value is None:
            continue
        content[key] = _display_path(storage.root, resolve_path(storage.root, value)) if key.endswith("_path") and str(value).strip() else value
    content["updated_at"] = utc_now()
    if content.get("status"):
        metadata["asset_status"] = content["status"]
        tags = [str(tag) for tag in data.get("tags", []) if str(tag).strip()]
        tags = [tag for tag in tags if tag not in QUEUE_STATUSES and tag not in {"planned", "running", "succeeded", "failed"}]
        data["tags"] = _dedupe([*tags, str(content["status"])])
    data["content"] = content
    data["metadata"] = metadata
    data["updated_at"] = utc_now()
    _write_json_validated(storage, path, data)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path)}


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


def _envelope_from_evidence(evidence: dict[str, Any]) -> dict[str, Any] | None:
    if isinstance(evidence.get("os_envelope"), dict):
        return evidence["os_envelope"]
    if isinstance(evidence.get("envelope"), dict):
        return evidence["envelope"]
    return None


def _environment_from_evidence(evidence: dict[str, Any]) -> str:
    direct = str(evidence.get("environment") or "").strip()
    if direct:
        return direct
    envelope = _envelope_from_evidence(evidence)
    if isinstance(envelope, dict):
        return str(envelope.get("environment") or "").strip()
    return ""


def _enforce_operation_knowledge_context(operation: str, contract: dict[str, Any], *, environment: str) -> None:
    if CORE_MKAOS_CONTEXT_OPERATIONS.get(operation) != "required":
        return
    if not is_production_environment(environment):
        return
    if not isinstance(contract, dict) or not contract:
        raise RuntimeError(f"agent operation {operation} requires knowledge context contract in production")
    missing = [
        field
        for field in ["context_bundle_id", "knowledge_pack_id", "source_policy", "source_isolation", "mkaos_flow"]
        if (field in {"source_policy", "source_isolation"} and not isinstance(contract.get(field), dict)) or (field not in {"source_policy", "source_isolation"} and not str(contract.get(field) or "").strip())
    ]
    if missing:
        raise RuntimeError(f"agent operation {operation} knowledge context contract missing: {', '.join(missing)}")


def _resolve_agent_registry_for_scheduler(storage: LocalStorage, spec: AgentOperationSpec | None, operation: str, *, environment: str) -> dict[str, Any]:
    if not spec:
        return {}
    try:
        from novel_forge.modules.agent_registry import resolve_agent_registry_entry

        return resolve_agent_registry_entry(
            storage,
            agent_id=spec.agent_key,
            operation=operation,
            environment=environment,
            require_schedulable=True,
            auto_sync=True,
        )
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"agent registry resolution failed for {spec.agent_key}/{operation}: {exc}") from exc


def _attach_agent_registry_resolution(storage: LocalStorage, agent_run: dict[str, Any], resolution: dict[str, Any]) -> None:
    if not resolution:
        return
    run_id = str((agent_run.get("content", {}) if isinstance(agent_run.get("content", {}), dict) else {}).get("run_id", ""))
    if not run_id:
        return
    try:
        path = _resolve_agent_run(storage, run_id)
        data = storage.read_json(path)
    except Exception:
        return
    if not isinstance(data, dict) or data.get("type") != "agent_run":
        return
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    registry = {
        "agent_id": str(resolution.get("agent_id", "")),
        "agent_registry_entry_id": str(resolution.get("agent_registry_entry_id", "")),
        "agent_registry_entry_path": str(resolution.get("agent_registry_entry_path", "")),
        "agent_registry_version": str(resolution.get("agent_registry_version", "")),
        "lifecycle_state": str(resolution.get("lifecycle_state", "")),
        "scheduler_enabled": bool(resolution.get("scheduler_enabled", False)),
    }
    content["agent_registry"] = registry
    metadata.update(
        {
            "agent_registry_entry_id": registry["agent_registry_entry_id"],
            "agent_registry_entry_path": registry["agent_registry_entry_path"],
            "agent_registry_version": registry["agent_registry_version"],
            "agent_lifecycle_state": registry["lifecycle_state"],
            "agent_scheduler_enabled": registry["scheduler_enabled"],
        }
    )
    data["content"] = content
    data["metadata"] = metadata
    refs = [str(item) for item in data.get("references", []) if str(item).strip()]
    refs.extend([registry["agent_registry_entry_id"], registry["agent_registry_entry_path"]])
    data["references"] = filter_project_safe_references(storage, str(metadata.get("project_id", "")), _dedupe(refs))
    data["updated_at"] = utc_now()
    storage.write_json(path, data)


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


def _mkaos_operation_contract_fields(operation: str) -> dict[str, Any]:
    mode = CORE_MKAOS_CONTEXT_OPERATIONS.get(operation, "")
    return {
        "mkaos_context_required": mode == "required",
        "mkaos_context_mode": mode or "not_required",
        "compat_warning_allowed": mode == "compat",
        "production_bypass_forbidden": mode == "required",
        "knowledge_context_contract_fields": [
            "context_bundle_id",
            "knowledge_pack_id",
            "source_policy",
            "source_isolation",
            "mkaos_flow",
            "selected_knowledge_ids",
            "review_rules",
            "risk_warnings",
            "selector_policy_version",
        ],
    }


def _knowledge_context_from_service_result(storage: LocalStorage, result: dict[str, Any], output_assets: list[str]) -> dict[str, Any]:
    if isinstance(result, dict) and isinstance(result.get("knowledge_context_contract"), dict) and result["knowledge_context_contract"]:
        return result["knowledge_context_contract"]
    asset = result.get("asset", {}) if isinstance(result, dict) and isinstance(result.get("asset", {}), dict) else {}
    direct = _knowledge_context_from_asset(asset)
    if direct:
        return direct
    for path_text in output_assets:
        try:
            data = storage.read_json(resolve_path(storage.root, path_text))
        except Exception:
            continue
        found = _knowledge_context_from_asset(data)
        if found:
            return found
    return {}


def _knowledge_context_from_asset(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    for source in [content, metadata]:
        contract = source.get("knowledge_context_contract")
        if isinstance(contract, dict) and contract:
            return contract
    return {}


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


def _agent_center_assets(storage: LocalStorage, asset_type: str, *, project_id: str | None, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in reversed(storage.list_json("runs")):
        data = _read_json_safe(storage, path)
        if data.get("type") != asset_type:
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if project_id and str(metadata.get("project_id", "")) != project_id:
            continue
        data["_path"] = _display_path(storage.root, path)
        rows.append(data)
        if len(rows) >= max(1, int(limit or 300)):
            break
    return rows


def _task_linked_paths(tasks: list[dict[str, Any]], field: str) -> set[str]:
    paths: set[str] = set()
    for task in tasks:
        content = task.get("content", {}) if isinstance(task.get("content", {}), dict) else {}
        value = str(content.get(field, "")).strip()
        if value:
            paths.add(value)
    return paths


def _agent_center_assets_by_paths(storage: LocalStorage, paths: set[str], *, asset_type: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in paths:
        try:
            path = resolve_path(storage.root, item)
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != asset_type:
            continue
        data["_path"] = _display_path(storage.root, path)
        rows.append(data)
    return rows


def _merge_asset_rows(primary: list[dict[str, Any]], extra: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in [*primary, *extra]:
        key = str(row.get("_path") or row.get("path") or row.get("id") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        rows.append(row)
    return rows


def _merge_queue_rows(primary: list[dict[str, Any]], extra: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in [*primary, *extra]:
        key = str(row.get("path") or row.get("dispatch_id") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        rows.append(row)
    return rows


def _agent_center_category_assets(storage: LocalStorage, category: str, asset_types: set[str], *, project_id: str | None, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in reversed(storage.list_json(category)):
        data = _read_json_safe(storage, path)
        if data.get("type") not in asset_types:
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if project_id and str(metadata.get("project_id") or content.get("project_id") or "") != project_id:
            continue
        data["_path"] = _display_path(storage.root, path)
        rows.append(data)
        if len(rows) >= max(1, int(limit or 300)):
            break
    return rows


def _agent_task_row(row: dict[str, Any]) -> dict[str, Any]:
    compact = _agent_asset_compact(row)
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    compact.update(
        {
            "task_id": content.get("task_id", row.get("id", "")),
            "agent_type": content.get("agent_type", ""),
            "operation": content.get("operation", ""),
            "input_assets": content.get("input_assets", []) if isinstance(content.get("input_assets", []), list) else [],
            "output_targets": content.get("output_targets", []) if isinstance(content.get("output_targets", []), list) else [],
            "agent_run_path": content.get("agent_run_path", ""),
            "dispatch_queue_path": content.get("dispatch_queue_path", ""),
            "linked_loop_run_path": content.get("linked_loop_run_path", ""),
            "linked_context_bundle_path": content.get("linked_context_bundle_path", ""),
            "linked_review_issue_path": content.get("linked_review_issue_path", ""),
            "linked_revision_task_path": content.get("linked_revision_task_path", ""),
        }
    )
    return compact


def _loop_run_row(row: dict[str, Any]) -> dict[str, Any]:
    compact = _agent_asset_compact(row)
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    compact.update(
        {
            "loop_run_id": content.get("loop_run_id", row.get("id", "")),
            "loop_type": content.get("loop_type", ""),
            "stop_condition": content.get("stop_condition", ""),
            "context_bundle_path": content.get("context_bundle_path", ""),
            "report_path": content.get("report_path", ""),
            "budget_used": content.get("budget_used", {}) if isinstance(content.get("budget_used", {}), dict) else {},
        }
    )
    return compact


def _context_bundle_row(row: dict[str, Any]) -> dict[str, Any]:
    compact = _agent_asset_compact(row)
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    compact.update(
        {
            "context_bundle_id": content.get("context_bundle_id", row.get("id", "")),
            "target_asset_id": content.get("target_asset_id", ""),
            "target_asset_type": content.get("target_asset_type", ""),
            "task_type": content.get("task_type", ""),
            "token_estimate": content.get("token_estimate", 0),
            "mkaos_pack_id": content.get("mkaos_pack_id", ""),
        }
    )
    return compact


def _review_issue_row(row: dict[str, Any]) -> dict[str, Any]:
    compact = _agent_asset_compact(row)
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    compact.update(
        {
            "issue_id": content.get("issue_id", row.get("id", "")),
            "issue_type": content.get("issue_type", ""),
            "severity": content.get("severity", ""),
            "blocking": bool(content.get("blocking")),
            "target_asset_id": content.get("target_asset_id", ""),
            "message": content.get("message", ""),
            "revision_task_candidate": content.get("revision_task_candidate", {}) if isinstance(content.get("revision_task_candidate", {}), dict) else {},
        }
    )
    return compact


def _revision_task_row(row: dict[str, Any]) -> dict[str, Any]:
    compact = _agent_asset_compact(row)
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    compact.update(
        {
            "task_id": content.get("task_id", row.get("id", "")),
            "source_draft_id": content.get("source_draft_id", ""),
            "source_draft_path": content.get("source_draft_path", ""),
            "issue_count": len(content.get("issues", []) if isinstance(content.get("issues", []), list) else []),
            "stage": content.get("stage", ""),
        }
    )
    return compact


def _agent_runtime_links(
    tasks: list[dict[str, Any]],
    runs: list[dict[str, Any]],
    loops: list[dict[str, Any]],
    contexts: list[dict[str, Any]],
    review_issues: list[dict[str, Any]],
    revision_tasks: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "agent_task_to_run": [
            {"agent_task_path": task.get("path", ""), "agent_run_path": task.get("agent_run_path", "")}
            for task in tasks
            if task.get("agent_run_path")
        ],
        "agent_task_to_review_issue": [
            {"agent_task_path": task.get("path", ""), "review_issue_path": task.get("linked_review_issue_path", "")}
            for task in tasks
            if task.get("linked_review_issue_path")
        ],
        "agent_task_to_revision_task": [
            {"agent_task_path": task.get("path", ""), "revision_task_path": task.get("linked_revision_task_path", "")}
            for task in tasks
            if task.get("linked_revision_task_path")
        ],
        "loop_to_context_bundle": [
            {"loop_run_path": loop.get("path", ""), "context_bundle_path": loop.get("context_bundle_path", "")}
            for loop in loops
            if loop.get("context_bundle_path")
        ],
        "issue_to_revision_task_candidates": [
            {"review_issue_path": issue.get("path", ""), "candidate": issue.get("revision_task_candidate", {})}
            for issue in review_issues
            if issue.get("revision_task_candidate")
        ],
        "counts": {
            "agent_tasks": len(tasks),
            "agent_runs": len(runs),
            "loop_runs": len(loops),
            "context_bundles": len(contexts),
            "review_issues": len(review_issues),
            "revision_tasks": len(revision_tasks),
        },
    }


def _agent_asset_compact(row: dict[str, Any]) -> dict[str, Any]:
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    metadata = row.get("metadata", {}) if isinstance(row.get("metadata", {}), dict) else {}
    return {
        "path": row.get("_path", ""),
        "id": row.get("id", ""),
        "type": row.get("type", ""),
        "title": row.get("title", ""),
        "status": content.get("status", metadata.get("status", "")),
        "operation": content.get("operation", ""),
        "agent_run_path": content.get("agent_run_path", metadata.get("agent_run_path", "")),
        "created_at": content.get("created_at", row.get("created_at", "")),
    }


def _agent_run_summary(row: dict[str, Any]) -> dict[str, Any]:
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    metadata = row.get("metadata", {}) if isinstance(row.get("metadata", {}), dict) else {}
    return {
        "path": row.get("_path", ""),
        "run_id": content.get("run_id", row.get("id", "")),
        "agent_key": metadata.get("agent_key", content.get("agent_key", "")),
        "operation": content.get("operation", ""),
        "status": content.get("status", ""),
        "model_provider": content.get("model_provider", metadata.get("model_provider", "")),
        "model_name": content.get("model_name", metadata.get("model_name", "")),
        "token_budget": content.get("token_budget", 0),
        "token_used": content.get("token_used", 0),
        "cost_estimate": content.get("cost_estimate", 0),
        "checkpoint": content.get("checkpoint", {}) if isinstance(content.get("checkpoint", {}), dict) else {},
        "output_count": len(content.get("output_assets", [])) if isinstance(content.get("output_assets", []), list) else 0,
    }


def _agent_checkpoint_row(row: dict[str, Any]) -> dict[str, Any]:
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    compact = _agent_asset_compact(row)
    compact.update(
        {
            "stage": content.get("stage", content.get("checkpoint_stage", "")),
            "operation": content.get("operation", ""),
            "status": content.get("status", compact.get("status", "")),
            "trace_id": (content.get("trace", {}) if isinstance(content.get("trace", {}), dict) else {}).get("trace_id", ""),
        }
    )
    return compact


def _agent_gate_row(row: dict[str, Any]) -> dict[str, Any]:
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    compact = _agent_asset_compact(row)
    compact.update(
        {
            "gate_kind": content.get("gate_kind", content.get("gate_type", "")),
            "status": content.get("status", compact.get("status", "")),
            "target": ", ".join(str(item) for item in content.get("target_paths", [])[:3]) if isinstance(content.get("target_paths", []), list) else content.get("target_path", ""),
            "trace_id": (content.get("trace", {}) if isinstance(content.get("trace", {}), dict) else {}).get("trace_id", ""),
        }
    )
    return compact


def _agent_run_graph(
    runs: list[dict[str, Any]],
    queue: list[dict[str, Any]],
    *,
    tasks: list[dict[str, Any]] | None = None,
    loops: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    tasks = tasks or []
    loops = loops or []
    nodes = []
    for row in tasks:
        nodes.append(
            {
                "id": row.get("task_id") or row.get("path"),
                "path": row.get("path", ""),
                "type": "agent_task",
                "agent_type": row.get("agent_type", ""),
                "operation": row.get("operation", ""),
                "status": row.get("status", ""),
            }
        )
    for row in runs:
        nodes.append(
            {
                "id": row.get("run_id") or row.get("path"),
                "path": row.get("path", ""),
                "type": "agent_run",
                "agent_type": row.get("agent_key", ""),
                "operation": row.get("operation", ""),
                "status": row.get("status", ""),
                "duration_ms": row.get("duration_ms", 0),
                "token_used": row.get("token_used", 0),
                "cost_estimate": row.get("cost_estimate", 0),
            }
        )
    for row in loops:
        nodes.append(
            {
                "id": row.get("loop_run_id") or row.get("path"),
                "path": row.get("path", ""),
                "type": "loop_run",
                "operation": row.get("loop_type", ""),
                "status": row.get("status", ""),
                "stop_condition": row.get("stop_condition", ""),
            }
        )
    run_paths = {str(row.get("path", "")): str(row.get("run_id") or row.get("path", "")) for row in runs}
    task_ids = {str(row.get("path", "")): str(row.get("task_id") or row.get("path", "")) for row in tasks}
    loop_ids = {str(row.get("path", "")): str(row.get("loop_run_id") or row.get("path", "")) for row in loops}
    edges = []
    for row in tasks:
        task_id = str(row.get("task_id") or row.get("path", ""))
        agent_path = str(row.get("agent_run_path", ""))
        if task_id and agent_path in run_paths:
            edges.append({"from": task_id, "to": run_paths[agent_path], "type": "task_run", "status": row.get("status", "")})
        loop_path = str(row.get("linked_loop_run_path", ""))
        if task_id and loop_path in loop_ids:
            edges.append({"from": loop_ids[loop_path], "to": task_id, "type": "loop_task", "status": row.get("status", "")})
    for row in queue:
        agent_path = str(row.get("agent_run_path", ""))
        if agent_path in run_paths:
            edges.append(
                {
                    "from": run_paths[agent_path],
                    "to": str(row.get("dispatch_id") or row.get("path", "")),
                    "type": "dispatch",
                    "status": row.get("status", ""),
                }
            )
        for task in tasks:
            if str(task.get("dispatch_queue_path", "")) == str(row.get("path", "")):
                task_id = task_ids.get(str(task.get("path", "")), str(task.get("task_id") or task.get("path", "")))
                edges.append({"from": task_id, "to": str(row.get("dispatch_id") or row.get("path", "")), "type": "task_dispatch", "status": row.get("status", "")})
    return {"nodes": nodes, "edges": edges}


def _agent_sla_duration_rows(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in runs:
        token_budget = int(row.get("token_budget", 0) or 0)
        token_used = int(row.get("token_used", 0) or 0)
        rows.append(
            {
                "path": row.get("path", ""),
                "operation": row.get("operation", ""),
                "status": row.get("status", ""),
                "duration_ms": row.get("duration_ms", 0),
                "sla_status": "over_token_budget" if token_budget and token_used > token_budget else "within_known_budget" if token_budget else "not_configured",
                "token_used": token_used,
                "token_budget": token_budget,
            }
        )
    return rows


def _agent_evidence_drawer(
    events: list[dict[str, Any]],
    checkpoints: list[dict[str, Any]],
    gates: list[dict[str, Any]],
    budgets: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    rollbacks: list[dict[str, Any]],
    *extra_sources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source in [events, checkpoints, gates, budgets, failures, rollbacks, *extra_sources]:
        for row in source:
            compact = _agent_asset_compact(row)
            compact["summary"] = compact.get("title") or compact.get("operation") or compact.get("id")
            rows.append(compact)
    return rows


def _agent_center_check(key: str, passed: bool, message: str, recommendation: str) -> dict[str, Any]:
    return {"key": key, "status": "passed" if passed else "warning", "message": message, "recommendation": "" if passed else recommendation}


def _checkpoint_coverage(checkpoints: list[dict[str, Any]]) -> dict[str, Any]:
    by_stage: dict[str, int] = {}
    by_operation: dict[str, int] = {}
    for row in checkpoints:
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        stage = str(content.get("stage", content.get("status", "")))
        operation = str(content.get("operation", ""))
        if stage:
            by_stage[stage] = by_stage.get(stage, 0) + 1
        if operation:
            by_operation[operation] = by_operation.get(operation, 0) + 1
    return {"by_stage": by_stage, "by_operation": by_operation, "count": len(checkpoints)}


def _gate_coverage(gates: list[dict[str, Any]]) -> dict[str, Any]:
    by_type: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for row in gates:
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        gate_type = str(content.get("gate_type", content.get("gate_kind", "")))
        status = str(content.get("status", ""))
        if gate_type:
            by_type[gate_type] = by_type.get(gate_type, 0) + 1
        if status:
            by_status[status] = by_status.get(status, 0) + 1
    return {"by_type": by_type, "by_status": by_status, "count": len(gates)}


def _budget_coverage(budgets: list[dict[str, Any]]) -> dict[str, Any]:
    exceeded = 0
    total_tokens = 0
    total_cost = 0.0
    for row in budgets:
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        if str(content.get("status", "")) in {"exceeded", "failed", "over_budget"}:
            exceeded += 1
        total_tokens += int(content.get("token_used", content.get("tokens", 0)) or 0)
        try:
            total_cost += float(content.get("cost_estimate", content.get("cost", 0.0)) or 0.0)
        except Exception:
            pass
    return {"count": len(budgets), "exceeded_count": exceeded, "token_used": total_tokens, "cost_estimate": round(total_cost, 6)}


def _failure_recovery_rows(failures: list[dict[str, Any]], rollbacks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rollback_sources = {
        str((row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}).get("agent_run_path", ""))
        for row in rollbacks
    }
    rows = []
    for failure in failures:
        content = failure.get("content", {}) if isinstance(failure.get("content", {}), dict) else {}
        agent_run_path = str(content.get("agent_run_path", ""))
        rows.append(
            {
                "path": failure.get("_path", ""),
                "agent_run_path": agent_run_path,
                "error_type": content.get("error_type", ""),
                "recovery_instruction": content.get("recovery_instruction", ""),
                "rollback_present": agent_run_path in rollback_sources if agent_run_path else bool(rollbacks),
            }
        )
    return rows[:80]


def _agent_center_health_score(
    queue: list[dict[str, Any]],
    runs: list[dict[str, Any]],
    checkpoints: list[dict[str, Any]],
    gates: list[dict[str, Any]],
    budgets: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    rollbacks: list[dict[str, Any]],
    contracts: list[dict[str, Any]],
) -> int:
    score = 100
    if not contracts:
        score -= 20
    if not runs and not queue:
        score -= 15
    if not checkpoints:
        score -= 15
    if not gates:
        score -= 10
    if not budgets:
        score -= 10
    blocked = [row for row in queue if str(row.get("status", "")) in {"waiting_human", "dead_letter", "retry_scheduled"}]
    score -= min(25, len(blocked) * 5)
    if failures and not rollbacks:
        score -= 15
    return max(0, min(100, score))


def _agent_center_recommendations(status: str, blocked_queue: list[dict[str, Any]], failures: list[dict[str, Any]], checks: list[dict[str, Any]]) -> list[str]:
    recommendations = [str(check["recommendation"]) for check in checks if check.get("recommendation")]
    if blocked_queue:
        recommendations.append("recover or cancel blocked dispatch queue items before scheduling more autonomous work")
    if failures:
        recommendations.append("create rollback reports and recovery instructions for failed Agent runs")
    if status == "ready" and not recommendations:
        recommendations.append("Agent Center evidence is ready for broader autonomous operation coverage")
    return recommendations


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


def _ensure_valid(data: dict[str, Any]) -> None:
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))


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
