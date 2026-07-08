from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.exception_policy import require_recoverable_asset_scan_error
from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.agent_scheduler.dead_letter_runner import fail_queue_item as _fail_queue_item
from novel_forge.modules.agent_scheduler.operation_registry import AgentOperationSpec, OperationRegistryCatalog, OperationRunner
from novel_forge.modules.agent_scheduler.queue_lifecycle import (
    CLAIMABLE_STATUSES,
    QUEUE_STATUSES,
    claim_queue_item as _claim_queue_item,
    dispatch_id_from_key as _dispatch_id_from_key,
    parse_utc_datetime as _parse_utc_datetime,
    queue_lease_expired as _queue_lease_expired,
    queue_path as _queue_path,
    queue_row as _queue_row,
    resolve_queue as _resolve_queue,
    update_queue_item as _update_queue_item,
    utc_now_dt as _utc_now_dt,
)
from novel_forge.modules.agent_scheduler.publishing_runners import (
    run_publish_gate_report as _run_publishing_gate_report,
    run_release_package as _run_publishing_release_package,
)
from novel_forge.modules.agent_scheduler.production_governance import (
    enforce_scheduler_final_governance,
    enforce_scheduler_preflight_governance,
)
from novel_forge.modules.agent_scheduler.recovery_runner import recover_dispatch as _recover_dispatch
from novel_forge.modules.agent_scheduler.rollback_runner import rollback_operation_outputs as _rollback_operation_outputs
from novel_forge.modules.agent_scheduler.scheduler_tick import run_scheduler_loop as _run_scheduler_loop
from novel_forge.modules.agent_scheduler.scheduler_tick import run_scheduler_tick as _run_scheduler_tick
from novel_forge.modules.agent_runs import (
    attach_agent_run_context_contract,
    execute_agent_run_once,
    record_agent_checkpoint,
    record_agent_event,
    start_agent_run,
    update_agent_run_status,
)
from novel_forge.modules.common import resolve_path
from novel_forge.modules.os_envelope import is_production_environment
from novel_forge.modules.production_context import filter_project_safe_references
from novel_forge.modules.review_issue import review_issue_to_revision_task_candidate
from novel_forge.modules.runtime_ledger import acquire_scheduler_lease, release_scheduler_lease, scheduler_lease_status
from novel_forge.schemas import AgentDispatchQueue, AgentTask, BaseAsset, RevisionTask, validate_common_fields
from novel_forge.storage.local import LocalStorage

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
    "create-platform-strategy-pack": "required",
    "generate-training-exercise": "required",
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
    "platform_compliance": "create-platform-strategy-pack",
    "training": "generate-training-exercise",
    "publish_gate": "create-publish-gate-report",
    "feedback_backflow": "create-feedback-backflow-plan",
}


class AgentOperationRegistry(OperationRegistryCatalog):
    def __init__(self) -> None:
        super().__init__(
            operation_runners=lambda: _operation_runners(),
            operation_specs_by_alias=lambda: _operation_specs_by_alias(),
            canonical_operation=lambda value: _canonical_operation(value),
            mkaos_operation_contract_fields=lambda operation: _mkaos_operation_contract_fields(operation),
            tool_name_for_output=lambda output_types: _tool_name_for_output(output_types),
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
        queue_path = _queue_path(storage, str(queue_content.get("dispatch_id", "")))
        agent_run_path = _agent_run_path_for_governance(storage, agent_run, queue_path)
        preflight_governance: dict[str, Any] = {}
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
            preflight_governance = enforce_scheduler_preflight_governance(
                storage,
                operation=canonical,
                environment=environment,
                queue_path=queue_path,
                agent_run_path=agent_run_path,
                queue_item=queue_item,
                agent_run=agent_run,
            )
            final_governance = enforce_scheduler_final_governance(
                storage,
                operation=canonical,
                environment=environment,
                queue_path=queue_path,
                agent_run_path=agent_run_path,
                queue_item=queue_item,
                agent_run=agent_run,
                output_assets=existing_outputs,
                preflight_report=preflight_governance,
            )
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
                    **_governance_evidence(preflight_governance, final_governance),
                },
            }
        runner = self.runners.get(canonical)
        if runner:
            preflight_governance = enforce_scheduler_preflight_governance(
                storage,
                operation=canonical,
                environment=environment,
                queue_path=queue_path,
                agent_run_path=agent_run_path,
                queue_item=queue_item,
                agent_run=agent_run,
            )
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
            final_governance = enforce_scheduler_final_governance(
                storage,
                operation=canonical,
                environment=environment,
                queue_path=queue_path,
                agent_run_path=agent_run_path,
                queue_item=queue_item,
                agent_run=agent_run,
                output_assets=output_assets,
                preflight_report=preflight_governance,
            )
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
                "production_governance": _governance_evidence(preflight_governance, final_governance),
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
                    **_governance_evidence(preflight_governance, final_governance),
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


def create_agent_dag(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    storage.ensure_layout()
    nodes = _dag_nodes(payload.get("nodes", []))
    edges = _dag_edges(payload.get("edges", []), nodes)
    validation = _validate_dag(nodes, edges)
    dag_id = make_id("agent_dag", f"{payload.get('project_id', '')}:{payload.get('name', 'agent-dag')}:{utc_now()}")
    content = {
        "dag_id": dag_id,
        "name": str(payload.get("name") or "Agent DAG"),
        "status": "blocked" if validation["cycle_detected"] else "ready",
        "nodes": nodes,
        "edges": edges,
        "topological_order": validation["topological_order"],
        "cycle_detected": validation["cycle_detected"],
        "operation_coverage": agent_operation_coverage_full_report(storage, project_id=str(payload.get("project_id") or "")),
        "created_at": utc_now(),
    }
    written = _write_base_run_asset(
        storage,
        "agent_dag",
        content["name"],
        ["agent-center-v2", "dag", content["status"]],
        content,
        project_id=str(payload.get("project_id") or ""),
        workspace_path=str(payload.get("workspace_path") or ""),
        references=_dedupe([str(node.get("agent_run_path", "")) for node in nodes]),
    )
    return {**written, "status": content["status"], "validation": validation}


def agent_operation_coverage_full_report(storage: LocalStorage, *, project_id: str = "") -> dict[str, Any]:
    contracts = list_agent_operation_contracts()
    contract_by_op = {str(row.get("operation", "")): row for row in contracts}
    registry_entries = _agent_center_assets(storage, "agent_registry_entry", project_id=project_id or None, limit=1000)
    queue = list_agent_dispatch_queue(storage, project_id=project_id or None, limit=1000)
    runs = _agent_center_assets(storage, "agent_run", project_id=project_id or None, limit=1000)
    operations = sorted({*[str(row.get("operation", "")) for row in contracts], *CORE_MKAOS_CONTEXT_OPERATIONS.keys()})
    rows: list[dict[str, Any]] = []
    for operation in operations:
        contract = contract_by_op.get(operation, {})
        queue_hits = [row for row in queue if str(row.get("operation", "")) == operation]
        run_hits = [row for row in runs if str((row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}).get("operation", "")) == operation]
        rows.append(
            {
                "operation": operation,
                "registered": bool(contract),
                "runner_kind": str(contract.get("runner_kind", "")),
                "agent_key": str(contract.get("agent_key", "")),
                "mkaos_context_policy": CORE_MKAOS_CONTEXT_OPERATIONS.get(operation, "optional"),
                "queued_count": len(queue_hits),
                "run_count": len(run_hits),
                "dead_letter_count": len([row for row in queue_hits if str(row.get("status", "")) == "dead_letter"]),
                "waiting_human_count": len([row for row in queue_hits if str(row.get("status", "")) == "waiting_human"]),
                "hard_stop_ui_visible": True,
                "rollback_rehearsal_supported": bool(contract),
                "dead_letter_repair_supported": True,
            }
        )
    missing = [row for row in rows if not row["registered"] and row["mkaos_context_policy"] == "required"]
    status = "blocked" if missing else "ready"
    return {
        "status": status,
        "project_id": project_id,
        "summary": {
            "operation_count": len(rows),
            "registered_count": len([row for row in rows if row["registered"]]),
            "missing_required_count": len(missing),
            "agent_registry_entry_count": len(registry_entries),
            "dead_letter_count": sum(int(row["dead_letter_count"]) for row in rows),
        },
        "operations": rows,
        "missing_required_operations": missing,
        "created_at": utc_now(),
    }


def agent_hard_stop_dashboard(storage: LocalStorage, *, project_id: str = "", workspace_path: str = "") -> dict[str, Any]:
    from novel_forge.modules.runtime_policy import provider_hard_stop_evidence_report

    provider = provider_hard_stop_evidence_report(storage, project_id=project_id or None, workspace_path=workspace_path or None)
    gates = _agent_center_assets(storage, "agent_gate", project_id=project_id or None, limit=400)
    failures = _agent_center_assets(storage, "agent_failure_report", project_id=project_id or None, limit=400)
    hard_stop_gates = [row for row in gates if "provider_" in str(row.get("content", {}))]
    return {
        "status": "blocked" if provider.get("status") != "passed" else "ready",
        "project_id": project_id,
        "provider_hard_stop_evidence": provider,
        "hard_stop_gates": [_agent_gate_row(row) for row in hard_stop_gates[:120]],
        "recent_failures": [_agent_asset_compact(row) for row in failures[:80]],
        "summary": {
            "provider_status": provider.get("status", ""),
            "hard_stop_gate_count": len(hard_stop_gates),
            "failure_count": len(failures),
            "fail_closed": True,
            "silent_fallback_allowed": False,
        },
    }


def rehearse_agent_rollback(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    storage.ensure_layout()
    queue_ref = str(payload.get("queue_path") or "")
    agent_run_ref = str(payload.get("agent_run_path") or "")
    queue_data: dict[str, Any] = {}
    run_data: dict[str, Any] = {}
    if queue_ref:
        queue_path = _resolve_queue(storage, queue_ref)
        queue_data = _read_json_safe(storage, queue_path)
        agent_run_ref = agent_run_ref or str((queue_data.get("content", {}) if isinstance(queue_data.get("content", {}), dict) else {}).get("agent_run_path", ""))
    if agent_run_ref:
        run_path = _resolve_agent_run(storage, agent_run_ref)
        run_data = _read_json_safe(storage, run_path)
    run_content = run_data.get("content", {}) if isinstance(run_data.get("content", {}), dict) else {}
    operation = _canonical_operation(str(run_content.get("operation") or (queue_data.get("content", {}) if isinstance(queue_data.get("content", {}), dict) else {}).get("operation", "")))
    spec = OPERATION_REGISTRY.specs.get(operation)
    payload_outputs = [str(item) for item in payload.get("output_assets", []) if str(item).strip()] if isinstance(payload.get("output_assets", []), list) else []
    output_assets = _dedupe([*[str(item.get("path", "")) for item in run_content.get("output_assets", []) if isinstance(item, dict)], *payload_outputs])
    rehearsal = {
        "rehearsal_id": make_id("agent_rollback_rehearsal", f"{operation}:{utc_now()}"),
        "status": "ready",
        "apply": False,
        "operation": operation,
        "agent_run_path": agent_run_ref,
        "queue_path": queue_ref,
        "rollback_strategy": spec.rollback_strategy if spec else str(payload.get("rollback_strategy") or "mark_outputs_rolled_back"),
        "target_asset_paths": output_assets,
        "would_mark_assets": [{"path": path, "exists": _path_exists(storage, path)} for path in output_assets],
        "manual_required": (spec.rollback_strategy if spec else "") in {"manual_reconciliation_required", "rollback_patch_available"},
        "created_at": utc_now(),
    }
    written = _write_base_run_asset(
        storage,
        "agent_rollback_rehearsal",
        f"Agent rollback rehearsal {operation or 'unknown'}",
        ["agent-center-v2", "rollback-rehearsal", "dry-run"],
        rehearsal,
        project_id=str((run_data.get("metadata", {}) if isinstance(run_data.get("metadata", {}), dict) else {}).get("project_id") or payload.get("project_id") or ""),
        workspace_path=str((run_data.get("metadata", {}) if isinstance(run_data.get("metadata", {}), dict) else {}).get("workspace_path") or payload.get("workspace_path") or ""),
        references=_dedupe([queue_ref, agent_run_ref, *output_assets]),
    )
    return {**written, "rehearsal": rehearsal}


def repair_dead_letter_dispatch(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    reason = str(payload.get("reason") or "agent center v2 dead letter repair")
    queue_ref = str(payload.get("queue_path") or payload.get("dispatch_queue_path") or "")
    if not queue_ref:
        raise ValueError("queue_path is required for dead letter repair")
    before_path = _resolve_queue(storage, queue_ref)
    before = _read_json_safe(storage, before_path)
    before_content = before.get("content", {}) if isinstance(before.get("content", {}), dict) else {}
    before_metadata = before.get("metadata", {}) if isinstance(before.get("metadata", {}), dict) else {}
    before_status = str((before.get("content", {}) if isinstance(before.get("content", {}), dict) else {}).get("status", ""))
    if before_status != "dead_letter" and not payload.get("force", False):
        raise ValueError("dead letter repair requires queue status dead_letter unless force=true")
    governance_review = _validate_governance_dead_letter_repair(
        storage,
        queue_path=_display_path(storage.root, before_path),
        project_id=str(payload.get("project_id") or before_metadata.get("project_id") or ""),
        payload=payload,
    )
    rehearsal = rehearse_agent_rollback(storage, {"queue_path": _display_path(storage.root, before_path), "project_id": payload.get("project_id") or ""})
    recovered = recover_agent_dispatch(storage, queue_path=_display_path(storage.root, before_path), reason=reason, allow_governance_dead_letter=True)
    report = {
        "repair_id": make_id("dead_letter_repair", f"{queue_ref}:{utc_now()}"),
        "status": "queued",
        "before_status": before_status,
        "queue_path": _display_path(storage.root, before_path),
        "agent_run_path": str(before_content.get("agent_run_path", "")),
        "recovered_queue": recovered,
        "rollback_rehearsal_path": rehearsal.get("path", ""),
        "governance_review": governance_review,
        "reason": reason,
        "created_at": utc_now(),
    }
    written = _write_base_run_asset(
        storage,
        "agent_dead_letter_repair",
        "Agent dead letter repair",
        ["agent-center-v2", "dead-letter-repair", "queued"],
        report,
        project_id=str(payload.get("project_id") or recovered.get("project_id") or ""),
        workspace_path=str(payload.get("workspace_path") or ""),
        references=_dedupe(
            [
                _display_path(storage.root, before_path),
                rehearsal.get("path", ""),
                *[str(item) for item in governance_review.get("reviewed_failed_gate_paths", [])],
                *[str(item) for item in governance_review.get("reviewed_failed_checkpoint_paths", [])],
            ]
        ),
    )
    return {**written, "repair": report}


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
    runtime_gates = _agent_center_category_assets(storage, "runs", {"gate_result"}, project_id=project_id, limit=limit)
    gates = _merge_asset_rows(gates, runtime_gates)
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
    agent_event_summary_rows = _agent_event_summary_rows(run_rows)
    loop_rows = [_loop_run_row(row) for row in loops]
    context_rows = [_context_bundle_row(row) for row in contexts]
    review_issue_rows = [_review_issue_row(row) for row in review_issues]
    revision_task_rows = [_revision_task_row(row) for row in revision_tasks]
    checkpoint_rows = [_agent_checkpoint_row(row) for row in checkpoints]
    gate_rows = [_agent_gate_row(row) for row in gates]
    governance_dead_letters = _agent_center_governance_dead_letters(blocked_queue, runs, checkpoints, gates)
    budget_summary = _budget_coverage(budgets)
    rollback_rows = [_agent_asset_compact(row) for row in rollbacks]
    dead_letter_repairs = _agent_center_assets(storage, "agent_dead_letter_repair", project_id=project_id, limit=limit)
    dead_letter_repair_rows = [_agent_dead_letter_repair_row(row) for row in dead_letter_repairs[:80]]
    governance_repair_required_count = sum(1 for row in dead_letter_repair_rows if row.get("governance_review_required") is True)
    governance_repair_confirmed_count = sum(1 for row in dead_letter_repair_rows if row.get("governance_review_confirmed") is True)
    governance_repair_missing_review_count = max(0, governance_repair_required_count - governance_repair_confirmed_count)
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
        _agent_center_check("governance_dead_letters", not governance_dead_letters, "No production governance dead-letter is blocking Agent Center", "inspect governance_dead_letters before repairing or rerunning production dispatches"),
        _agent_center_check("governance_repair_review", governance_repair_missing_review_count == 0, "Governance repair records have explicit review evidence", "inspect dead_letter_repairs with missing governance review confirmation"),
    ]
    status = "blocked" if blocked_queue or failures else "warning" if any(check["status"] == "warning" for check in readiness_checks) else "ready"
    recommendations = _agent_center_recommendations(status, blocked_queue, failures, readiness_checks)
    if governance_dead_letters:
        recommendations.insert(0, "inspect governance_dead_letters and failed drift gates before repairing production dispatches")
    operation_coverage_full = agent_operation_coverage_full_report(storage, project_id=project_id or "")
    hard_stop_dashboard = agent_hard_stop_dashboard(storage, project_id=project_id or "")
    rollback_rehearsals = _agent_center_assets(storage, "agent_rollback_rehearsal", project_id=project_id, limit=limit)
    agent_dags = _agent_center_assets(storage, "agent_dag", project_id=project_id, limit=limit)
    return {
        "status": status,
        "agent_center_version": "v2",
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
            "governance_dead_letter_count": len(governance_dead_letters),
            "dead_letter_repair_count": len(dead_letter_repair_rows),
            "governance_repair_required_count": governance_repair_required_count,
            "governance_repair_confirmed_count": governance_repair_confirmed_count,
            "governance_repair_missing_review_count": governance_repair_missing_review_count,
            "agent_event_summary_count": len(agent_event_summary_rows),
            "agent_event_skipped_count": sum(int(row.get("skipped_event_count", 0) or 0) for row in agent_event_summary_rows),
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
        "governance_dead_letters": governance_dead_letters[:80],
        "rollback_preview": rollback_rows[:80],
        "rollback_rehearsals": [_agent_asset_compact(row) for row in rollback_rehearsals[:80]],
        "dead_letter_repairs": dead_letter_repair_rows,
        "agent_dags": [_agent_asset_compact(row) for row in agent_dags[:80]],
        "operation_coverage_full": operation_coverage_full,
        "hard_stop_dashboard": hard_stop_dashboard,
        "sla_duration": _agent_sla_duration_rows(run_rows),
        "agent_event_summaries": agent_event_summary_rows[:120],
        "evidence_drawer": _agent_evidence_drawer(events, checkpoints, gates, budgets, failures, rollbacks, tasks, loops, contexts, review_issues, revision_tasks, handoffs, dead_letter_repairs, agent_event_summary_rows)[:220],
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
    return _run_scheduler_tick(
        storage,
        project_id=project_id,
        limit=limit,
        lease_owner=lease_owner,
        lease_ttl_seconds=lease_ttl_seconds,
        force_lease=force_lease,
        retry_delay_seconds=retry_delay_seconds,
        dry_run=dry_run,
        acquire_lease=acquire_scheduler_lease,
        release_lease=release_scheduler_lease,
        materialize_prepared_agent_runs=_materialize_prepared_agent_runs,
        claimable_queue_candidates=_claimable_queue_candidates,
        claim_queue_item=_claim_queue_item,
        run_claimed_dispatch=_run_claimed_dispatch,
        fail_queue_item=_fail_queue_item,
    )


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
    return _run_scheduler_loop(
        run_agent_scheduler_tick,
        storage=storage,
        project_id=project_id,
        limit=limit,
        iterations=iterations,
        interval_seconds=interval_seconds,
        stop_when_idle=stop_when_idle,
        lease_owner=lease_owner,
        lease_ttl_seconds=lease_ttl_seconds,
        force_lease=force_lease,
        retry_delay_seconds=retry_delay_seconds,
    )


def recover_agent_dispatch(
    storage: LocalStorage,
    *,
    queue_path: str | Path,
    reason: str = "manual recovery",
    allow_governance_dead_letter: bool = False,
) -> dict[str, Any]:
    resolved = _resolve_queue(storage, queue_path)
    data = _read_json_safe(storage, resolved)
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    display_path = _display_path(storage.root, resolved)
    if not allow_governance_dead_letter:
        row = _governance_dead_letter_for_queue(storage, queue_path=display_path, project_id=str(metadata.get("project_id", "")))
        if row:
            raise ValueError("governance dead-letter recovery requires reviewed dead-letter repair via repair_dead_letter_dispatch")
    return _recover_dispatch(storage, queue_path=queue_path, reason=reason)


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
            agent_key="longform_recap",
            input_types=("draft_chapter", "draft_version"),
            output_types=("longform_recap_report", "revision_task"),
            required_tool="write_longform_recap_report",
            sla_seconds=900,
        ),
        AgentOperationSpec(
            operation="build-genre-strategy-pack",
            aliases=("genre-strategy-pack",),
            runner=_run_build_genre_strategy_pack,
            agent_key="outline",
            input_types=(),
            output_types=("genre_strategy_pack", "genre_profile", "subgenre_mechanic"),
            required_tool="write_genre_strategy_pack",
            sla_seconds=300,
        ),
        AgentOperationSpec(
            operation="run-genre-risk-gate",
            aliases=("genre-risk-gate",),
            runner=_run_genre_risk_gate,
            agent_key="review",
            input_types=("genre_strategy_pack",),
            output_types=("genre_risk_gate", "review_issue"),
            required_tool="write_review_issue",
            sla_seconds=300,
        ),
        AgentOperationSpec(
            operation="ingest-style-sample",
            aliases=("style-sample-ingestion",),
            runner=_run_ingest_style_sample,
            agent_key="knowledge",
            input_types=(),
            output_types=("style_sample",),
            required_tool="write_style_sample",
            sla_seconds=300,
        ),
        AgentOperationSpec(
            operation="extract-style-fingerprint",
            aliases=("style-fingerprint",),
            runner=_run_extract_style_fingerprint,
            agent_key="knowledge",
            input_types=("style_sample",),
            output_types=("style_fingerprint",),
            required_tool="write_style_fingerprint",
            sla_seconds=300,
        ),
        AgentOperationSpec(
            operation="build-style-profile",
            aliases=("style-profile",),
            runner=_run_build_style_profile,
            agent_key="knowledge",
            input_types=("style_fingerprint",),
            output_types=("style_profile", "style_generation_policy", "style_review_rule"),
            required_tool="write_style_profile",
            sla_seconds=300,
        ),
        AgentOperationSpec(
            operation="run-style-drift-gate",
            aliases=("style-drift-gate",),
            runner=_run_style_drift_gate,
            agent_key="review",
            input_types=("style_profile", "draft_chapter"),
            output_types=("style_drift_report", "style_rewrite_task", "review_issue", "revision_task"),
            required_tool="write_review_issue",
            sla_seconds=300,
        ),
        AgentOperationSpec(
            operation="run-canon-graph-plugin",
            aliases=("canon-graph-plugin",),
            runner=_run_canon_graph_plugin_operation,
            agent_key="continuity",
            input_types=(),
            output_types=(
                "fantasy_power_scale_report",
                "mystery_evidence_chain_report",
                "romance_relationship_state_report",
                "historical_faction_network_report",
                "sci_fi_rule_consistency_report",
                "horror_rule_contamination_report",
                "review_issue",
            ),
            required_tool="write_review_issue",
            sla_seconds=300,
        ),
        AgentOperationSpec(
            operation="run-quality-suite",
            aliases=("quality-suite",),
            runner=_run_quality_suite_operation,
            agent_key="model_evaluation",
            input_types=(),
            output_types=("opening_3_report", "golden_10_report", "volume_30_report", "longform_100_report", "review_issue", "revision_task"),
            required_tool="write_review_issue",
            sla_seconds=600,
        ),
        AgentOperationSpec(
            operation="run-provider-quality-judge",
            aliases=("provider-quality-judge",),
            runner=_run_provider_quality_judge_operation,
            agent_key="model_evaluation",
            input_types=(),
            output_types=("opening_3_report", "golden_10_report", "volume_30_report", "longform_100_report", "model_judge_result", "review_issue", "revision_task"),
            required_tool="call_model",
            sla_seconds=900,
        ),
        AgentOperationSpec(
            operation="run-quality-gate",
            aliases=("quality-gate",),
            runner=_run_quality_gate_operation,
            agent_key="quality",
            input_types=(),
            output_types=("evaluation_gate",),
            required_tool="write_gate_result",
            sla_seconds=300,
        ),
        AgentOperationSpec(
            operation="run-long-chain-proof",
            aliases=("long-chain-proof",),
            runner=_run_long_chain_proof_operation,
            agent_key="workflow",
            input_types=(),
            output_types=("long_chain_run", "long_chain_acceptance_report"),
            required_tool="run_validation",
            sla_seconds=1800,
        ),
        AgentOperationSpec(
            operation="run-v7-provider-proof",
            aliases=("v7-provider-proof",),
            runner=_run_v7_provider_proof_operation,
            agent_key="quality",
            input_types=(),
            output_types=("project_metric_snapshot",),
            required_tool="call_model",
            sla_seconds=3600,
        ),
        AgentOperationSpec(
            operation="build-platform-upload-package",
            aliases=("platform-upload-package",),
            runner=_run_build_platform_upload_package,
            agent_key="publishing",
            input_types=("release_package",),
            output_types=("platform_upload_package",),
            required_tool="write_release_package",
            sla_seconds=300,
        ),
        AgentOperationSpec(
            operation="record-platform-receipt",
            aliases=("platform-receipt",),
            runner=_run_record_platform_receipt,
            agent_key="publishing",
            input_types=(),
            output_types=("platform_publish_receipt", "platform_review_status"),
            required_tool="write_publishing_log",
            sla_seconds=300,
        ),
        AgentOperationSpec(
            operation="run-platform-adapter-gate",
            aliases=("platform-adapter-gate",),
            runner=_run_platform_adapter_gate,
            agent_key="publishing",
            input_types=("platform_upload_package",),
            output_types=("platform_review_status",),
            required_tool="run_validation",
            sla_seconds=300,
        ),
        AgentOperationSpec(
            operation="publish-platform-upload-package",
            aliases=("platform-api-publish",),
            runner=_run_publish_platform_upload_package,
            agent_key="publishing",
            input_types=("platform_upload_package",),
            output_types=("platform_publish_receipt", "platform_review_status"),
            required_tool="network_publish",
            sla_seconds=600,
        ),
        AgentOperationSpec(
            operation="import-platform-metrics",
            aliases=("platform-metrics-import",),
            runner=_run_import_platform_metrics,
            agent_key="feedback",
            input_types=(),
            output_types=("platform_metric_snapshot", "chapter_dropoff_report"),
            required_tool="write_feedback",
            sla_seconds=300,
        ),
        AgentOperationSpec(
            operation="cluster-platform-comments",
            aliases=("platform-comments-cluster",),
            runner=_run_cluster_platform_comments,
            agent_key="feedback",
            input_types=(),
            output_types=("platform_comment_batch", "comment_cluster_report"),
            required_tool="write_feedback",
            sla_seconds=300,
        ),
        AgentOperationSpec(
            operation="create-feedback-mutation-proposal",
            aliases=("feedback-mutation-proposal",),
            runner=_run_create_feedback_mutation_proposal,
            agent_key="feedback",
            input_types=("comment_cluster_report", "chapter_dropoff_report"),
            output_types=("feedback_plan_mutation_proposal",),
            required_tool="write_feedback",
            sla_seconds=300,
        ),
        AgentOperationSpec(
            operation="resolve-feedback-mutation-proposal",
            aliases=("feedback-mutation-resolution",),
            runner=_run_resolve_feedback_mutation_proposal,
            agent_key="feedback",
            input_types=("feedback_plan_mutation_proposal",),
            output_types=("feedback_plan_mutation_proposal", "feedback_mutation_application_report"),
            required_tool="write_feedback",
            sla_seconds=300,
        ),
        AgentOperationSpec(
            operation="apply-feedback-mutation-application-chain",
            aliases=("feedback-mutation-application",),
            runner=_run_apply_feedback_mutation_application_chain,
            agent_key="feedback",
            input_types=("feedback_plan_mutation_proposal",),
            output_types=("feedback_mutation_application_report", "feedback_mutation_patch", "revision_task", "agent_task"),
            required_tool="write_feedback",
            sla_seconds=300,
        ),
        AgentOperationSpec(
            operation="create-platform-strategy-pack",
            aliases=("platform-strategy-pack", "platform-strategy", "platform-compliance"),
            runner=_run_platform_strategy_pack,
            agent_key="platform_strategy",
            input_types=("topic_seed", "project_workspace_state"),
            output_types=("platform_strategy_pack",),
            required_tool="write_platform_strategy_pack",
            sla_seconds=300,
        ),
        AgentOperationSpec(
            operation="generate-training-exercise",
            aliases=("training-exercise", "training"),
            runner=_run_training_exercise,
            agent_key="training",
            input_types=("topic_seed",),
            output_types=("training_exercise",),
            required_tool="write_training_exercise",
            sla_seconds=300,
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

    evidence = _evidence(agent_run)
    return {"path": build_materials(storage, _required_input_path(agent_run), environment=str(evidence.get("environment") or ""))}


def _run_generate_outline(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.outline import generate_outline

    evidence = _evidence(agent_run)
    return {
        "path": generate_outline(
            storage,
            _required_input_path(agent_run),
            workspace_path=_workspace_path(agent_run),
            environment=str(evidence.get("environment") or ""),
            os_envelope=_envelope_from_evidence(evidence),
            source_policy=evidence.get("source_policy") if isinstance(evidence.get("source_policy"), dict) else None,
            provider_runtime_gate=_provider_runtime_gate_from_evidence(evidence),
        )
    }


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
            source_policy=evidence.get("source_policy") if isinstance(evidence.get("source_policy"), dict) else None,
            provider_runtime_gate=_provider_runtime_gate_from_evidence(evidence),
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
            source_policy=evidence.get("source_policy") if isinstance(evidence.get("source_policy"), dict) else None,
            provider_runtime_gate=_provider_runtime_gate_from_evidence(evidence),
        )
    }


def _run_review(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.review import review

    evidence = _evidence(agent_run)
    return {
        "path": review(
            storage,
            _required_input_path(agent_run),
            environment=str(evidence.get("environment") or ""),
            os_envelope=_envelope_from_evidence(evidence),
            source_policy=evidence.get("source_policy") if isinstance(evidence.get("source_policy"), dict) else None,
            provider_runtime_gate=_provider_runtime_gate_from_evidence(evidence),
        )
    }


def _run_revise(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.revision import revise

    evidence = _evidence(agent_run)
    return {
        "path": revise(
            storage,
            _required_input_path(agent_run),
            environment=str(evidence.get("environment") or ""),
            os_envelope=_envelope_from_evidence(evidence),
            source_policy=evidence.get("source_policy") if isinstance(evidence.get("source_policy"), dict) else None,
            provider_runtime_gate=_provider_runtime_gate_from_evidence(evidence),
        )
    }


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
    evidence = _evidence(agent_run)
    return _run_publishing_gate_report(storage, input_path=_required_input_path(agent_run), workspace_path=_workspace_path(agent_run) or None, evidence=evidence, envelope=_envelope_from_evidence(evidence))


def _run_release_package(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    evidence = _evidence(agent_run)
    return _run_publishing_release_package(storage, input_path=_required_input_path(agent_run), workspace_path=_workspace_path(agent_run) or None, evidence=evidence, envelope=_envelope_from_evidence(evidence))


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


def _run_platform_strategy_pack(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.platform_strategy import build_platform_strategy_pack

    evidence = _evidence(agent_run)
    input_path = _primary_input_path(agent_run)
    payload = {
        **evidence,
        "project_id": _project_id(agent_run) or evidence.get("project_id", ""),
        "workspace_path": _workspace_path(agent_run) or evidence.get("workspace_path", ""),
        "persist": True,
    }
    if input_path:
        source = _read_json_safe(storage, resolve_path(storage.root, input_path))
        content = source.get("content", {}) if isinstance(source.get("content", {}), dict) else {}
        metadata = source.get("metadata", {}) if isinstance(source.get("metadata", {}), dict) else {}
        if source.get("type") == "topic_seed":
            payload.setdefault("topic", content.get("logline") or source.get("title") or "Untitled topic")
            payload.setdefault("genre", content.get("genre") or metadata.get("genre") or "generic")
        if source.get("type") == "project_workspace_state":
            config = content.get("project_config", {}) if isinstance(content.get("project_config", {}), dict) else {}
            memory = content.get("memory", {}) if isinstance(content.get("memory", {}), dict) else {}
            payload.setdefault("platform", config.get("target_platform") or evidence.get("platform") or "qidian")
            payload.setdefault("topic", memory.get("series_title") or source.get("title") or "Untitled topic")
    return build_platform_strategy_pack(storage, payload)


def _run_training_exercise(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.training.service import generate_training_exercise

    return {"path": generate_training_exercise(storage, _required_input_path(agent_run))}


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
        environment=str(evidence.get("environment") or ""),
        allow_mock_fixture=bool(evidence.get("allow_mock_fixture") or evidence.get("mock_provider_test_mode")),
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
        selector_governance_report_path=str(evidence.get("selector_governance_report_path") or "") or None,
        selector_governance_binding_application_report_path=str(evidence.get("selector_governance_binding_application_report_path") or "") or None,
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


def _run_build_genre_strategy_pack(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.genre_os import build_genre_strategy_pack

    evidence = _evidence(agent_run)
    return build_genre_strategy_pack(
        storage,
        genre=str(evidence.get("genre") or "xuanhuan"),
        subgenre=str(evidence.get("subgenre") or ""),
        project_id=_project_id(agent_run) or str(evidence.get("project_id") or ""),
        platform_id=str(evidence.get("platform_id") or "local"),
        title=str(evidence.get("title") or ""),
        environment=str(evidence.get("environment") or ""),
        envelope=_envelope_from_evidence(evidence),
        source_policy=evidence.get("source_policy") if isinstance(evidence.get("source_policy"), dict) else None,
    )


def _run_genre_risk_gate(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.genre_os import run_genre_risk_gate

    evidence = _evidence(agent_run)
    return run_genre_risk_gate(
        storage,
        strategy_pack_path=str(evidence.get("strategy_pack_path") or _primary_input_path(agent_run)),
        target_path=evidence.get("target_path") or None,
        evidence=evidence.get("risk_evidence", {}) if isinstance(evidence.get("risk_evidence", {}), dict) else {},
        environment=str(evidence.get("environment") or ""),
        envelope=_envelope_from_evidence(evidence),
    )


def _run_ingest_style_sample(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.style_os import ingest_style_sample

    evidence = _evidence(agent_run)
    return ingest_style_sample(
        storage,
        sample_text=str(evidence.get("sample_text") or ""),
        project_id=_project_id(agent_run) or str(evidence.get("project_id") or ""),
        rights=evidence.get("rights") if isinstance(evidence.get("rights"), dict) else None,
        title=str(evidence.get("title") or "Style sample"),
        source=str(evidence.get("source") or "agent-operation"),
        environment=str(evidence.get("environment") or ""),
        envelope=_envelope_from_evidence(evidence),
    )


def _run_extract_style_fingerprint(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.style_os import extract_style_fingerprint

    evidence = _evidence(agent_run)
    return extract_style_fingerprint(
        storage,
        sample_path=str(evidence.get("sample_path") or _primary_input_path(agent_run)),
        environment=str(evidence.get("environment") or ""),
        envelope=_envelope_from_evidence(evidence),
    )


def _run_build_style_profile(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.style_os import build_style_profile

    evidence = _evidence(agent_run)
    return build_style_profile(
        storage,
        fingerprint_path=str(evidence.get("fingerprint_path") or _primary_input_path(agent_run)),
        style_name=str(evidence.get("style_name") or "Project style profile"),
        scope=str(evidence.get("scope") or "project"),
        environment=str(evidence.get("environment") or ""),
        envelope=_envelope_from_evidence(evidence),
    )


def _run_style_drift_gate(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.style_os import run_style_drift_gate

    evidence = _evidence(agent_run)
    return run_style_drift_gate(
        storage,
        style_profile_path=str(evidence.get("style_profile_path") or ""),
        target_path=str(evidence.get("target_path") or _primary_input_path(agent_run)),
        environment=str(evidence.get("environment") or ""),
        envelope=_envelope_from_evidence(evidence),
    )


def _run_canon_graph_plugin_operation(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.canon_graph import run_canon_graph_plugin

    evidence = _evidence(agent_run)
    return run_canon_graph_plugin(
        storage,
        {
            **evidence,
            "plugin": str(evidence.get("plugin") or "mystery_evidence_chain_engine"),
            "target_path": evidence.get("target_path") or _primary_input_path(agent_run),
            "project_id": _project_id(agent_run) or evidence.get("project_id", ""),
            "workspace_path": _workspace_path(agent_run) or evidence.get("workspace_path", ""),
        },
    )


def _run_quality_suite_operation(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.quality_eval import run_quality_suite

    evidence = _evidence(agent_run)
    target_paths = _string_list(evidence.get("target_paths", [])) or _input_paths(agent_run)
    return run_quality_suite(
        storage,
        suite_type=str(evidence.get("suite_type") or "opening_3"),
        target_paths=target_paths,
        rubric_path=str(evidence.get("rubric_path") or ""),
        genre_strategy_pack_path=str(evidence.get("genre_strategy_pack_path") or ""),
        style_profile_path=str(evidence.get("style_profile_path") or ""),
        platform_id=str(evidence.get("platform_id") or "local"),
        environment=str(evidence.get("environment") or ""),
        envelope=_envelope_from_evidence(evidence),
    )


class _FixtureReviewAdapter:
    def __init__(self, response: dict[str, Any], *, provider_name: str = "fixture-provider", external_provider_evidence: dict[str, Any] | None = None):
        self.response = response
        self.name = provider_name
        self.external_provider_evidence = external_provider_evidence or {}

    def generate(self, payload: str, context: dict[str, Any]) -> dict[str, Any]:
        return self.response

    def review(self, payload: str, context: dict[str, Any]) -> dict[str, Any]:
        return self.response


def _run_provider_quality_judge_operation(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.quality_eval import run_provider_quality_judge

    evidence = _evidence(agent_run)
    target_paths = _string_list(evidence.get("target_paths", [])) or _input_paths(agent_run)
    _ensure_agent_model_route(storage, evidence, task_type="quality_judge", project_id=_project_id(agent_run), workspace_path=_workspace_path(agent_run))
    fixture_response = evidence.get("fixture_judge_response") if isinstance(evidence.get("fixture_judge_response"), dict) else None
    adapter = _adapter_from_agent_evidence(evidence, fixture_response=fixture_response, default_operation="review")
    return run_provider_quality_judge(
        storage,
        suite_type=str(evidence.get("suite_type") or "opening_3"),
        target_paths=target_paths,
        rubric_path=str(evidence.get("rubric_path") or ""),
        adapter=adapter,
        genre_strategy_pack_path=str(evidence.get("genre_strategy_pack_path") or ""),
        style_profile_path=str(evidence.get("style_profile_path") or ""),
        platform_id=str(evidence.get("platform_id") or "local"),
        environment=str(evidence.get("environment") or ""),
        envelope=_envelope_from_evidence(evidence),
        provider_runtime_guard=evidence.get("provider_runtime_guard") if isinstance(evidence.get("provider_runtime_guard"), dict) else None,
        allow_mock_fixture=bool(evidence.get("allow_mock_fixture", False)),
        require_external_provider_proof=bool(evidence.get("require_external_provider_proof", False)),
    )


def _run_quality_gate_operation(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.quality_eval import run_quality_gate

    evidence = _evidence(agent_run)
    return run_quality_gate(
        storage,
        quality_report_path=str(evidence.get("quality_report_path") or _primary_input_path(agent_run)),
        environment=str(evidence.get("environment") or ""),
        envelope=_envelope_from_evidence(evidence),
    )


def _ensure_agent_model_route(storage: LocalStorage, evidence: dict[str, Any], *, task_type: str, project_id: str, workspace_path: str) -> None:
    route = evidence.get("provider_route", {}) if isinstance(evidence.get("provider_route", {}), dict) else {}
    provider_config = evidence.get("provider_config", {}) if isinstance(evidence.get("provider_config", {}), dict) else {}
    if not route and not provider_config:
        return
    from novel_forge.modules.model_router import create_model_route

    approval = evidence.get("operator_approval", {}) if isinstance(evidence.get("operator_approval", {}), dict) else {}
    route_allowlist = route.get("production_provider_allowlist")
    config_allowlist = provider_config.get("production_provider_allowlist")
    production_provider_allowlist = route_allowlist if isinstance(route_allowlist, list) else config_allowlist if isinstance(config_allowlist, list) else None
    create_model_route(
        storage,
        task_type=str(route.get("task_type") or task_type),
        provider=str(route.get("provider") or provider_config.get("provider") or "mock"),
        model_name=str(route.get("model_name") or provider_config.get("model_name") or provider_config.get("model") or "mock-model"),
        fallbacks=route.get("fallbacks") if isinstance(route.get("fallbacks"), list) else [],
        selection_rule=str(route.get("selection_rule") or "balanced"),
        max_cost_per_run=float(route.get("max_cost_per_run") or evidence.get("budget_cap") or provider_config.get("budget_cap") or 0.0),
        max_latency_ms=int(route.get("max_latency_ms") or provider_config.get("max_latency_ms") or 0),
        status=str(route.get("status") or "active"),
        project_id=project_id,
        workspace_path=workspace_path,
        environment=str(route.get("environment") or evidence.get("environment") or ""),
        approval_status=str(route.get("approval_status") or approval.get("status") or ""),
        approval_id=str(route.get("approval_id") or approval.get("approval_id") or ""),
        approved_by=str(route.get("approved_by") or approval.get("approved_by") or ""),
        approval_reason=str(route.get("approval_reason") or approval.get("reason") or ""),
        production_provider_allowlist=production_provider_allowlist,
        mock_provider_test_mode=bool(route.get("mock_provider_test_mode") or evidence.get("allow_mock_fixture") or provider_config.get("mock_provider_test_mode")),
    )


def _adapter_from_agent_evidence(evidence: dict[str, Any], *, fixture_response: dict[str, Any] | None, default_operation: str) -> Any | None:
    provider_config = evidence.get("provider_config", {}) if isinstance(evidence.get("provider_config", {}), dict) else {}
    provider = str(provider_config.get("provider") or evidence.get("provider") or "").strip().lower()
    mode = str(evidence.get("mode") or provider_config.get("mode") or ("fixture" if fixture_response else "real")).strip().lower()
    if fixture_response:
        if mode == "real" and not evidence.get("allow_mock_fixture"):
            raise ValueError("fixture provider response requires allow_mock_fixture=true unless mode is fixture")
        return _FixtureReviewAdapter(
            fixture_response,
            provider_name=provider or "fixture-provider",
            external_provider_evidence=provider_config.get("external_provider_evidence") if isinstance(provider_config.get("external_provider_evidence"), dict) else {},
        )
    if mode == "fixture":
        raise ValueError(f"{default_operation} fixture mode requires fixture response evidence")
    if not provider:
        return None
    from novel_forge.model_adapters import ModelAdapterConfig, PROVIDER_ADAPTERS

    adapter_cls = PROVIDER_ADAPTERS.get(provider)
    if adapter_cls is None:
        raise ValueError(f"unsupported provider adapter: {provider}")
    model_name = str(provider_config.get("model_name") or provider_config.get("model") or "").strip()
    if model_name:
        base = adapter_cls.config
        return adapter_cls(
            ModelAdapterConfig(
                provider=base.provider,
                role=base.role,
                default_model=model_name,
                required_env_vars=list(base.required_env_vars),
                external_api=base.external_api,
            )
        )
    return adapter_cls()


def _run_long_chain_proof_operation(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.long_chain_proof import run_long_chain_proof

    evidence = _evidence(agent_run)
    _ensure_agent_model_route(storage, evidence, task_type="chapter_draft", project_id=_project_id(agent_run), workspace_path=_workspace_path(agent_run))
    fixture_response = evidence.get("fixture_chapter_response") if isinstance(evidence.get("fixture_chapter_response"), dict) else None
    return run_long_chain_proof(
        storage,
        project_id=_project_id(agent_run) or str(evidence.get("project_id") or "local-project"),
        mode=str(evidence.get("mode") or "deterministic_50"),
        target_chapter_count=int(evidence["target_chapter_count"]) if str(evidence.get("target_chapter_count") or "").isdigit() else None,
        environment=str(evidence.get("environment") or ""),
        envelope=_envelope_from_evidence(evidence),
        opt_in_slow_provider=bool(evidence.get("opt_in_slow_provider", False)),
        provider_adapter=_adapter_from_agent_evidence(evidence, fixture_response=fixture_response, default_operation="generate") if str(evidence.get("mode") or "").startswith("provider_") else None,
        provider_runtime_guard=evidence.get("provider_runtime_guard") if isinstance(evidence.get("provider_runtime_guard"), dict) else None,
        require_external_provider_proof=bool(evidence.get("require_external_provider_proof", False)),
    )


def _run_v7_provider_proof_operation(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.v7_provider_proof import run_v7_provider_proof

    evidence = _evidence(agent_run)

    class _SchedulerProviderProofAdapter:
        def __init__(self, generate_response: dict[str, Any], review_response: dict[str, Any], external_evidence: dict[str, Any]):
            self.generate_response = generate_response
            self.review_response = review_response
            self.external_provider_evidence = external_evidence
            self.name = "scheduler-fixture-provider"

        def generate(self, payload: str, context: dict[str, Any]) -> dict[str, Any]:
            return self.generate_response

        def review(self, payload: str, context: dict[str, Any]) -> dict[str, Any]:
            return self.review_response

    generate_response = evidence.get("fixture_chapter_response") if isinstance(evidence.get("fixture_chapter_response"), dict) else {}
    review_response = evidence.get("fixture_review_response") if isinstance(evidence.get("fixture_review_response"), dict) else {}
    if not generate_response or not review_response:
        raise ValueError("run-v7-provider-proof requires fixture_chapter_response and fixture_review_response unless a real provider adapter runner is configured")
    return run_v7_provider_proof(
        storage,
        provider_adapter=_SchedulerProviderProofAdapter(
            generate_response,
            review_response,
            evidence.get("external_provider_evidence") if isinstance(evidence.get("external_provider_evidence"), dict) else {},
        ),
        project_id=_project_id(agent_run) or str(evidence.get("project_id") or "local-project"),
        draft_path=str(evidence.get("draft_path") or ""),
        genre_strategy_pack_path=str(evidence.get("genre_strategy_pack_path") or ""),
        style_profile_path=str(evidence.get("style_profile_path") or ""),
        platform_id=str(evidence.get("platform_id") or "local"),
        provider_runtime_guard=evidence.get("provider_runtime_guard") if isinstance(evidence.get("provider_runtime_guard"), dict) else None,
        require_external_provider_proof=bool(evidence.get("require_external_provider_proof", True)),
        environment=str(evidence.get("environment") or "production"),
        envelope=_envelope_from_evidence(evidence),
        target_chapter_count=int(evidence.get("target_chapter_count") or 50),
    )


def _run_build_platform_upload_package(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.publishing_feedback_adapters import build_platform_upload_package

    evidence = _evidence(agent_run)
    return build_platform_upload_package(
        storage,
        release_package_path=str(evidence.get("release_package_path") or _primary_input_path(agent_run)),
        platform_id=str(evidence.get("platform_id") or "manual"),
        book_metadata=evidence.get("book_metadata") if isinstance(evidence.get("book_metadata"), dict) else None,
        chapter_payloads=evidence.get("chapter_payloads") if isinstance(evidence.get("chapter_payloads"), list) else None,
        environment=str(evidence.get("environment") or ""),
        envelope=_envelope_from_evidence(evidence),
    )


def _run_record_platform_receipt(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.publishing_feedback_adapters import record_platform_receipt

    evidence = _evidence(agent_run)
    return record_platform_receipt(
        storage,
        platform_id=str(evidence.get("platform_id") or "manual"),
        platform_book_id=str(evidence.get("platform_book_id") or ""),
        platform_chapter_id=str(evidence.get("platform_chapter_id") or ""),
        review_status=str(evidence.get("review_status") or "submitted"),
        receipt_raw=evidence.get("receipt_raw") if isinstance(evidence.get("receipt_raw"), dict) else {},
        operator_note=str(evidence.get("operator_note") or ""),
        upload_package_path=str(evidence.get("upload_package_path") or _primary_input_path(agent_run)),
        environment=str(evidence.get("environment") or ""),
        envelope=_envelope_from_evidence(evidence),
    )


def _run_platform_adapter_gate(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.publishing_feedback_adapters import run_platform_adapter_gate

    evidence = _evidence(agent_run)
    return run_platform_adapter_gate(
        storage,
        upload_package_path=str(evidence.get("upload_package_path") or _primary_input_path(agent_run)),
        platform_id=str(evidence.get("platform_id") or ""),
        receipt_path=str(evidence.get("receipt_path") or ""),
        environment=str(evidence.get("environment") or ""),
        envelope=_envelope_from_evidence(evidence),
    )


def _run_publish_platform_upload_package(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.publishing_feedback_adapters import publish_platform_upload_package

    evidence = _evidence(agent_run)
    return publish_platform_upload_package(
        storage,
        upload_package_path=str(evidence.get("upload_package_path") or _primary_input_path(agent_run)),
        platform_config=evidence.get("platform_config") if isinstance(evidence.get("platform_config"), dict) else None,
        environment=str(evidence.get("environment") or ""),
        envelope=_envelope_from_evidence(evidence),
    )


def _run_import_platform_metrics(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.publishing_feedback_adapters import import_platform_metrics

    evidence = _evidence(agent_run)
    return import_platform_metrics(
        storage,
        platform_id=str(evidence.get("platform_id") or "manual"),
        chapter_metrics=evidence.get("chapter_metrics") if isinstance(evidence.get("chapter_metrics"), list) else [],
        book_metrics=evidence.get("book_metrics") if isinstance(evidence.get("book_metrics"), dict) else {},
        environment=str(evidence.get("environment") or ""),
        envelope=_envelope_from_evidence(evidence),
    )


def _run_cluster_platform_comments(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.publishing_feedback_adapters import cluster_platform_comments

    evidence = _evidence(agent_run)
    return cluster_platform_comments(
        storage,
        platform_id=str(evidence.get("platform_id") or "manual"),
        comments=evidence.get("comments") if isinstance(evidence.get("comments"), list) else [],
        environment=str(evidence.get("environment") or ""),
        envelope=_envelope_from_evidence(evidence),
        persist_issues=bool(evidence.get("persist_issues", False)),
    )


def _run_create_feedback_mutation_proposal(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.publishing_feedback_adapters import create_feedback_mutation_proposal

    evidence = _evidence(agent_run)
    return create_feedback_mutation_proposal(
        storage,
        source_feedback_paths=_string_list(evidence.get("source_feedback_paths", [])) or _input_paths(agent_run),
        target_assets=evidence.get("target_assets") if isinstance(evidence.get("target_assets"), list) else [],
        proposed_changes=evidence.get("proposed_changes") if isinstance(evidence.get("proposed_changes"), list) else [],
        environment=str(evidence.get("environment") or ""),
        envelope=_envelope_from_evidence(evidence),
    )


def _run_resolve_feedback_mutation_proposal(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.publishing_feedback_adapters import resolve_feedback_mutation_proposal

    evidence = _evidence(agent_run)
    return resolve_feedback_mutation_proposal(
        storage,
        proposal_ref=str(evidence.get("proposal_ref") or _primary_input_path(agent_run)),
        approved=bool(evidence.get("approved", False)),
        actor=str(evidence.get("actor") or "agent-scheduler"),
        decision_note=str(evidence.get("decision_note") or ""),
        create_application_chain=bool(evidence.get("create_application_chain", True)),
        auto_apply_application_chain=bool(evidence.get("auto_apply_application_chain", True)),
        auto_apply_invalidation=bool(evidence.get("auto_apply_invalidation", True)),
        environment=str(evidence.get("environment") or ""),
        envelope=_envelope_from_evidence(evidence),
    )


def _run_apply_feedback_mutation_application_chain(storage: LocalStorage, queue_item: dict[str, Any], agent_run: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.publishing_feedback_adapters import apply_feedback_mutation_application_chain

    evidence = _evidence(agent_run)
    return apply_feedback_mutation_application_chain(
        storage,
        proposal_ref=str(evidence.get("proposal_ref") or _primary_input_path(agent_run)),
        apply_invalidation=bool(evidence.get("apply_invalidation", True)),
        actor=str(evidence.get("actor") or "agent-scheduler"),
        environment=str(evidence.get("environment") or ""),
        envelope=_envelope_from_evidence(evidence),
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
    except Exception as exc:
        require_recoverable_asset_scan_error(exc, context=f"agent scheduler asset reference: {path}")
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
    strategy = candidate.get("revision_strategy", {}) if isinstance(candidate.get("revision_strategy", {}), dict) else {}
    required_evidence = candidate.get("required_output_evidence", []) if isinstance(candidate.get("required_output_evidence", []), list) else []
    re_review_focus = candidate.get("re_review_focus", []) if isinstance(candidate.get("re_review_focus", []), list) else []
    strategy_id = str(candidate.get("revision_strategy_id") or strategy.get("strategy_id") or "targeted_revision")
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
                "revision_strategy_id": strategy_id,
                "revision_strategy": strategy,
                "re_review_required": bool(candidate.get("re_review_required", True)),
                "re_review_focus": re_review_focus,
                "required_output_evidence": required_evidence,
            }
        ],
        "revision_strategy_plan": {
            "contract_version": "review-issue-revision-strategy-v1",
            "strategy_ids": [strategy_id],
            "issues": [
                {
                    "issue_id": issue_id,
                    "issue_type": content.get("issue_type", candidate.get("issue_type", "")),
                    "severity": content.get("severity", candidate.get("severity", "")),
                    "blocking": bool(content.get("blocking", candidate.get("blocking", False))),
                    "revision_strategy_id": strategy_id,
                    "revision_strategy": strategy,
                    "re_review_required": bool(candidate.get("re_review_required", True)),
                    "re_review_focus": re_review_focus,
                    "required_output_evidence": required_evidence,
                }
            ],
            "strategies": [
                {
                    "issue_id": issue_id,
                    "issue_index": 0,
                    "issue_type": content.get("issue_type", candidate.get("issue_type", "")),
                    "severity": content.get("severity", candidate.get("severity", "")),
                    "blocking": bool(content.get("blocking", candidate.get("blocking", False))),
                    "strategy": strategy,
                }
            ],
            "required_output_evidence": required_evidence,
            "re_review_required": bool(candidate.get("re_review_required", True)),
            "re_review_focus": re_review_focus,
            "quality_gate_required": bool(candidate.get("quality_gate_required", True)),
            "strategy_count": 1,
        },
        "revision_strategy_ids": [strategy_id],
        "required_output_evidence": required_evidence,
        "re_review_required": bool(candidate.get("re_review_required", True)),
        "re_review_focus": re_review_focus,
        "quality_gate_required": bool(candidate.get("quality_gate_required", True)),
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
            "revision_strategy_ids": [strategy_id],
            "re_review_required": bool(candidate.get("re_review_required", True)),
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
    metadata_value = str(metadata.get("workspace_path", "") or "")
    evidence_value = str(evidence.get("workspace_path", "") or "")
    if metadata_value and metadata_value != "local-system":
        return metadata_value
    return evidence_value or metadata_value


def _project_id(agent_run: dict[str, Any]) -> str:
    metadata = agent_run.get("metadata", {}) if isinstance(agent_run.get("metadata", {}), dict) else {}
    evidence = _evidence(agent_run, include_processor=False)
    metadata_value = str(metadata.get("project_id", "") or "")
    evidence_value = str(evidence.get("project_id", "") or "")
    if metadata_value and metadata_value != "local-system":
        return metadata_value
    return evidence_value or metadata_value


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


def _provider_runtime_gate_from_evidence(evidence: dict[str, Any]) -> dict[str, Any] | None:
    if isinstance(evidence.get("provider_runtime_gate"), dict):
        return evidence["provider_runtime_gate"]
    if isinstance(evidence.get("provider_runtime_guard"), dict):
        return evidence["provider_runtime_guard"]
    return None


def _governance_evidence(preflight: dict[str, Any], final: dict[str, Any]) -> dict[str, Any]:
    if not preflight and not final:
        return {}
    return {
        "production_governance_path": str(final.get("path") or ""),
        "production_governance_status": str(final.get("status") or ""),
        "production_governance_preflight_path": str(preflight.get("path") or ""),
        "production_governance_gate_result_path": str(final.get("gate_result_path") or ""),
    }


def _agent_run_path_for_governance(storage: LocalStorage, agent_run: dict[str, Any], queue_path: Path) -> Path:
    run_content = agent_run.get("content", {}) if isinstance(agent_run.get("content", {}), dict) else {}
    for value in [run_content.get("run_id"), agent_run.get("id"), agent_run.get("path"), agent_run.get("_path")]:
        if not str(value or "").strip():
            continue
        try:
            return _resolve_agent_run(storage, str(value))
        except (FileNotFoundError, ValueError):
            continue
    return queue_path


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


def _agent_dead_letter_repair_row(row: dict[str, Any]) -> dict[str, Any]:
    compact = _agent_asset_compact(row)
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    governance_review = content.get("governance_review", {}) if isinstance(content.get("governance_review", {}), dict) else {}
    recovered_queue = content.get("recovered_queue", {}) if isinstance(content.get("recovered_queue", {}), dict) else {}
    reviewed_gate_paths = _string_list(governance_review.get("reviewed_failed_gate_paths", []))
    reviewed_checkpoint_paths = _string_list(governance_review.get("reviewed_failed_checkpoint_paths", []))
    compact.update(
        {
            "repair_id": content.get("repair_id", row.get("id", "")),
            "before_status": content.get("before_status", ""),
            "queue_path": content.get("queue_path", ""),
            "rollback_rehearsal_path": content.get("rollback_rehearsal_path", ""),
            "reason": content.get("reason", ""),
            "governance_review": governance_review,
            "governance_review_required": bool(governance_review.get("required")),
            "governance_review_confirmed": bool(governance_review.get("confirmed")),
            "reviewed_failed_gate_count": len(reviewed_gate_paths),
            "reviewed_failed_checkpoint_count": len(reviewed_checkpoint_paths),
            "reviewed_failed_gate_paths": reviewed_gate_paths,
            "reviewed_failed_checkpoint_paths": reviewed_checkpoint_paths,
            "review_note": governance_review.get("review_note", ""),
            "recovered_queue_path": recovered_queue.get("queue_path", content.get("queue_path", "")) if isinstance(recovered_queue, dict) else content.get("queue_path", ""),
            "recovered_status": recovered_queue.get("status", "") if isinstance(recovered_queue, dict) else "",
        }
    )
    return compact


def _agent_run_summary(row: dict[str, Any]) -> dict[str, Any]:
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    metadata = row.get("metadata", {}) if isinstance(row.get("metadata", {}), dict) else {}
    event_policy = content.get("agent_event_policy", {}) if isinstance(content.get("agent_event_policy", {}), dict) else {}
    event_summary = content.get("agent_event_summary", {}) if isinstance(content.get("agent_event_summary", {}), dict) else {}
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
        "agent_event_policy": event_policy,
        "agent_event_policy_mode": event_policy.get("mode", "full"),
        "agent_event_summary": event_summary,
        "agent_event_skipped_count": int(event_summary.get("skipped_event_count", 0) or 0),
        "agent_event_skipped_types": _string_list(event_summary.get("skipped_event_types", [])),
    }


def _agent_event_summary_rows(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run in runs:
        skipped_count = int(run.get("agent_event_skipped_count", 0) or 0)
        if skipped_count <= 0:
            continue
        skipped_types = _string_list(run.get("agent_event_skipped_types", []))
        policy_mode = str(run.get("agent_event_policy_mode") or "full")
        run_path = str(run.get("path", ""))
        rows.append(
            {
                "path": run_path,
                "id": f"{run.get('run_id', run_path)}:agent_event_summary",
                "type": "agent_event_summary",
                "title": "Agent event summary",
                "status": "summarized",
                "operation": run.get("operation", ""),
                "agent_run_path": run_path,
                "policy_mode": policy_mode,
                "skipped_event_count": skipped_count,
                "skipped_event_types": skipped_types,
                "summary": f"{skipped_count} compacted AgentRun event(s): {', '.join(skipped_types)}",
                "created_at": "",
            }
        )
    return rows


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
            if row.get("type") == "agent_event_summary" and "summary" in row:
                compact = dict(row)
            else:
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


GOVERNANCE_DEAD_LETTER_MARKERS = (
    "production governance",
    "governance drift",
    "context governance",
    "provider_runtime_gate",
    "publish gate",
    "release gate",
)

GOVERNANCE_GATE_KINDS = {
    "production_governance_evidence_drift",
    "context_governance_runtime_coverage",
    "provider_runtime_gate",
    "publish_gate",
    "release_gate",
}


def _agent_center_governance_dead_letters(
    blocked_queue: list[dict[str, Any]],
    runs: list[dict[str, Any]],
    checkpoints: list[dict[str, Any]],
    gates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    run_by_path = {str(row.get("_path", "")): row for row in runs if str(row.get("_path", ""))}
    failed_gates = [_failed_governance_gate_row(row) for row in gates]
    failed_gates = [row for row in failed_gates if row]
    rows: list[dict[str, Any]] = []
    for queue in blocked_queue:
        if str(queue.get("status", "")) != "dead_letter":
            continue
        last_error = str(queue.get("last_error", ""))
        project_id = str(queue.get("project_id", ""))
        agent_run_path = str(queue.get("agent_run_path", ""))
        run = run_by_path.get(agent_run_path, {})
        run_content = run.get("content", {}) if isinstance(run.get("content", {}), dict) else {}
        run_id = str(run_content.get("run_id") or queue.get("agent_run_id") or "")
        related_checkpoints = _failed_checkpoints_for_run(checkpoints, agent_run_path=agent_run_path, run_id=run_id)
        related_gates = [
            gate
            for gate in failed_gates
            if (not project_id or str(gate.get("project_id", "")) == project_id)
            and _governance_gate_matches_queue(gate, queue, agent_run_path=agent_run_path)
        ]
        if not _is_governance_dead_letter(last_error, related_gates):
            continue
        if not related_gates:
            related_gates = [gate for gate in failed_gates if not project_id or str(gate.get("project_id", "")) == project_id][:5]
        rows.append(
            {
                "queue_path": queue.get("path", ""),
                "dispatch_id": queue.get("dispatch_id", ""),
                "operation": queue.get("operation") or run_content.get("operation", ""),
                "agent_key": queue.get("agent_key", ""),
                "agent_run_path": agent_run_path,
                "agent_run_status": run_content.get("status", ""),
                "dead_lettered_at": queue.get("dead_lettered_at", ""),
                "last_error": last_error,
                "failed_checkpoint_paths": [str(item.get("path", "")) for item in related_checkpoints if str(item.get("path", ""))],
                "failed_checkpoints": related_checkpoints[:5],
                "failed_gate_paths": [str(item.get("path", "")) for item in related_gates if str(item.get("path", ""))],
                "failed_gates": related_gates[:5],
                "repair": {
                    "auto_repair": False,
                    "requires_operator": True,
                    "manual_operation": "repair_dead_letter_dispatch",
                    "queue_path": queue.get("path", ""),
                    "precondition": "operator must inspect failed_gates and failed_checkpoints before retry",
                },
                "recommended_actions": [
                    "inspect failed production governance evidence",
                    "repair drifted publish/release/gate artifacts before rerun",
                    "use dead-letter repair only after the failed evidence is understood",
                ],
            }
        )
    return rows


def _failed_governance_gate_row(row: dict[str, Any]) -> dict[str, Any]:
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    metadata = row.get("metadata", {}) if isinstance(row.get("metadata", {}), dict) else {}
    gate_kind = str(content.get("gate_kind") or content.get("gate_type") or "")
    status = str(content.get("status") or "")
    if status != "failed" or gate_kind not in GOVERNANCE_GATE_KINDS:
        return {}
    result = content.get("result", {}) if isinstance(content.get("result", {}), dict) else {}
    blocking_rows = result.get("blocking_rows", []) if isinstance(result.get("blocking_rows", []), list) else []
    return {
        "path": row.get("_path", ""),
        "gate_kind": gate_kind,
        "status": status,
        "project_id": metadata.get("project_id", ""),
        "message": content.get("message", ""),
        "target_paths": content.get("target_paths", []) if isinstance(content.get("target_paths", []), list) else [],
        "report_path": result.get("report_path", ""),
        "blocking_row_count": len(blocking_rows),
        "blocking_rows": blocking_rows[:5],
    }


def _failed_checkpoints_for_run(checkpoints: list[dict[str, Any]], *, agent_run_path: str, run_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in checkpoints:
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        state = content.get("state", {}) if isinstance(content.get("state", {}), dict) else {}
        if agent_run_path and str(content.get("agent_run_path", "")) != agent_run_path:
            continue
        if run_id and str(content.get("agent_run_id", "")) != run_id:
            continue
        status = str(content.get("status") or state.get("status") or "")
        if "failed" not in status:
            continue
        rows.append(
            {
                "path": row.get("_path", ""),
                "status": status,
                "operation": state.get("operation", ""),
                "error": state.get("error", ""),
                "created_at": content.get("created_at", ""),
            }
        )
    return rows


def _governance_gate_matches_queue(gate: dict[str, Any], queue: dict[str, Any], *, agent_run_path: str) -> bool:
    targets = [str(item) for item in gate.get("target_paths", []) if str(item)]
    if agent_run_path and agent_run_path in targets:
        return True
    queue_path = str(queue.get("path", ""))
    if queue_path and queue_path in targets:
        return True
    last_error = str(queue.get("last_error", "")).lower()
    return any(marker in last_error for marker in GOVERNANCE_DEAD_LETTER_MARKERS)


def _is_governance_dead_letter(last_error: str, related_gates: list[dict[str, Any]]) -> bool:
    if related_gates:
        return True
    normalized = last_error.lower()
    return any(marker in normalized for marker in GOVERNANCE_DEAD_LETTER_MARKERS)


def _validate_governance_dead_letter_repair(
    storage: LocalStorage,
    *,
    queue_path: str,
    project_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    target = _governance_dead_letter_for_queue(storage, queue_path=queue_path, project_id=project_id)
    if not target:
        return {"required": False, "confirmed": False, "reason": "no governance dead-letter evidence for queue"}
    review = payload.get("governance_review", {}) if isinstance(payload.get("governance_review", {}), dict) else {}
    confirmed = bool(payload.get("confirm_governance_review") or review.get("confirmed") or review.get("confirm_governance_review"))
    reviewed_gate_paths = _dedupe(
        [
            *_string_list(payload.get("reviewed_failed_gate_paths", [])),
            *_string_list(payload.get("failed_gate_paths", [])),
            *_string_list(review.get("reviewed_failed_gate_paths", [])),
            *_string_list(review.get("failed_gate_paths", [])),
        ]
    )
    reviewed_checkpoint_paths = _dedupe(
        [
            *_string_list(payload.get("reviewed_failed_checkpoint_paths", [])),
            *_string_list(payload.get("failed_checkpoint_paths", [])),
            *_string_list(review.get("reviewed_failed_checkpoint_paths", [])),
            *_string_list(review.get("failed_checkpoint_paths", [])),
        ]
    )
    expected_gate_paths = _string_list(target.get("failed_gate_paths", []))
    expected_checkpoint_paths = _string_list(target.get("failed_checkpoint_paths", []))
    missing_gate_paths = [path for path in expected_gate_paths if path not in reviewed_gate_paths]
    missing_checkpoint_paths = [path for path in expected_checkpoint_paths if path not in reviewed_checkpoint_paths]
    if not confirmed or missing_gate_paths or missing_checkpoint_paths:
        raise ValueError(
            "governance dead-letter repair requires confirm_governance_review=true "
            "and reviewed failed gate/checkpoint paths covering Agent Center governance_dead_letters evidence"
        )
    return {
        "required": True,
        "confirmed": True,
        "queue_path": queue_path,
        "reviewed_failed_gate_paths": reviewed_gate_paths,
        "reviewed_failed_checkpoint_paths": reviewed_checkpoint_paths,
        "expected_failed_gate_paths": expected_gate_paths,
        "expected_failed_checkpoint_paths": expected_checkpoint_paths,
        "review_note": str(payload.get("governance_review_note") or review.get("review_note") or review.get("note") or ""),
    }


def _governance_dead_letter_for_queue(storage: LocalStorage, *, queue_path: str, project_id: str) -> dict[str, Any]:
    snapshot = agent_center_snapshot(storage, project_id=project_id or None)
    rows = snapshot.get("governance_dead_letters", []) if isinstance(snapshot.get("governance_dead_letters", []), list) else []
    return next((row for row in rows if str(row.get("queue_path", "")) == queue_path), {})


def _dag_nodes(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(value if isinstance(value, list) else [], start=1):
        if not isinstance(item, dict):
            continue
        node_id = str(item.get("id") or item.get("node_id") or item.get("operation") or f"node-{index}").strip()
        operation = _canonical_operation(str(item.get("operation") or node_id))
        rows.append(
            {
                "id": node_id,
                "operation": operation,
                "agent_key": str(item.get("agent_key") or item.get("agent_type") or ""),
                "depends_on": _dedupe([str(dep) for dep in item.get("depends_on", [])]) if isinstance(item.get("depends_on", []), list) else [],
                "agent_run_path": str(item.get("agent_run_path") or ""),
                "status": str(item.get("status") or "planned"),
                "mkaos_context_required": CORE_MKAOS_CONTEXT_OPERATIONS.get(operation) == "required",
            }
        )
    return rows


def _dag_edges(value: Any, nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    node_ids = {str(node.get("id", "")) for node in nodes}
    rows: list[dict[str, Any]] = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, dict):
            source = str(item.get("source") or item.get("from") or "").strip()
            target = str(item.get("target") or item.get("to") or "").strip()
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            source, target = str(item[0]), str(item[1])
        else:
            continue
        if source in node_ids and target in node_ids:
            rows.append({"source": source, "target": target, "relation": "precedes"})
    for node in nodes:
        target = str(node.get("id", ""))
        for source in node.get("depends_on", []) if isinstance(node.get("depends_on", []), list) else []:
            if source in node_ids and target in node_ids:
                rows.append({"source": source, "target": target, "relation": "depends_on"})
    return _dedupe_dag_edges(rows)


def _validate_dag(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
    node_ids = [str(node.get("id", "")) for node in nodes]
    incoming = {node_id: 0 for node_id in node_ids}
    outgoing: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    for edge in edges:
        source = str(edge.get("source", ""))
        target = str(edge.get("target", ""))
        if source not in outgoing or target not in incoming:
            continue
        outgoing[source].append(target)
        incoming[target] += 1
    ready = sorted([node_id for node_id, count in incoming.items() if count == 0])
    order: list[str] = []
    while ready:
        node_id = ready.pop(0)
        order.append(node_id)
        for target in sorted(outgoing.get(node_id, [])):
            incoming[target] -= 1
            if incoming[target] == 0:
                ready.append(target)
    cycle = len(order) != len(node_ids)
    return {"ok": not cycle, "cycle_detected": cycle, "topological_order": order, "node_count": len(nodes), "edge_count": len(edges), "errors": ["agent DAG contains a cycle"] if cycle else []}


def _dedupe_dag_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for edge in edges:
        key = (str(edge.get("source", "")), str(edge.get("target", "")))
        if key[0] and key[1] and key not in seen:
            seen.add(key)
            result.append(edge)
    return result


def _write_base_run_asset(
    storage: LocalStorage,
    asset_type: str,
    title: str,
    tags: list[str],
    content: dict[str, Any],
    *,
    project_id: str = "",
    workspace_path: str = "",
    references: list[str] | None = None,
) -> dict[str, Any]:
    asset = BaseAsset(
        type=asset_type,
        title=title,
        tags=tags,
        content=content,
        metadata={"project_id": project_id, "workspace_path": workspace_path, "asset_status": str(content.get("status") or ""), "use_in_generation_rag": False},
        references=filter_project_safe_references(storage, project_id, references or []),
    )
    data = asset.to_dict()
    _ensure_valid(data)
    path = storage.write_asset("runs", asset)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path)}


def _tool_name_for_output(output_types: list[str]) -> str:
    if not output_types:
        return "run_validation"
    return f"write_{output_types[0]}"


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
    except Exception as exc:
        require_recoverable_asset_scan_error(exc, context=f"agent scheduler JSON scan: {path}")
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
