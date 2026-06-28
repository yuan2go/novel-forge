from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.agent_runs import ensure_agent_contract, execute_agent_run_once, record_agent_checkpoint, start_agent_run
from novel_forge.modules.change_impact import create_change_impact_report, mark_downstream_assets_stale
from novel_forge.modules.common import resolve_path
from novel_forge.modules.production_context import filter_project_safe_references, project_scope_from_asset
from novel_forge.modules.runtime_ledger import (
    acquire_scheduler_lease,
    record_gate_result,
    record_trace_span,
    release_scheduler_lease,
)
from novel_forge.schemas import NodeRun, WorkflowDefinition, WorkflowNode, WorkflowRun, validate_common_fields
from novel_forge.storage.local import LocalStorage

WORKFLOW_TERMINAL_NODE_STATUSES = {"succeeded", "failed", "dead_letter", "cancelled"}
WORKFLOW_SUCCESS_NODE_STATUSES = {"succeeded", "recovered"}
WORKFLOW_BLOCKING_NODE_STATUSES = {"failed", "dead_letter", "cancelled", "waiting_human", "needs_revision"}
WORKFLOW_RUN_TERMINAL_STATUSES = {"completed", "failed", "superseded"}


def create_workflow_definition(
    storage: LocalStorage,
    *,
    name: str,
    nodes: list[dict[str, Any]],
    entry_node_id: str,
    status: str = "active",
    version: str = "0.1.0",
) -> dict[str, Any]:
    workflow_id = make_id("workflow", name)
    asset = WorkflowDefinition(
        title=name,
        tags=["workflow-definition", status],
        content={
            "workflow_id": workflow_id,
            "name": name,
            "version": version,
            "nodes": nodes,
            "entry_node_id": entry_node_id,
            "status": status,
        },
        metadata={"created_by": "workflow_nodes"},
    )
    return _write(storage, asset)


def create_workflow_node(
    storage: LocalStorage,
    *,
    workflow_id: str,
    node_id: str,
    node_type: str,
    operation: str,
    input_types: list[str],
    output_types: list[str],
    processor: dict[str, Any] | None = None,
    quality_gate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    asset = WorkflowNode(
        title=f"{workflow_id}:{node_id}",
        source=workflow_id,
        tags=["workflow-node", node_type, operation],
        content={
            "node_id": node_id,
            "workflow_id": workflow_id,
            "node_type": node_type,
            "operation": operation,
            "input_types": input_types,
            "output_types": output_types,
            "processor": processor or {"kind": "local_service"},
            "quality_gate": quality_gate or {"required": False},
        },
        references=[workflow_id],
    )
    return _write(storage, asset)


def record_node_run(
    storage: LocalStorage,
    *,
    run_id: str,
    node_id: str,
    node_type: str,
    operation: str,
    status: str,
    input_assets: list[str | Path] | None = None,
    output_assets: list[str | Path] | None = None,
    processor: dict[str, Any] | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    error: str = "",
    quality_gate: dict[str, Any] | None = None,
    human_gate: dict[str, Any] | None = None,
    trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    input_rows = [_asset_ref(storage, item) for item in input_assets or []]
    output_rows = [_asset_ref(storage, item) for item in output_assets or []]
    project = _project_scope_from_refs(storage, [*input_rows, *output_rows])
    project_id = str(project.get("project_id", ""))
    workspace_path = str(project.get("workspace_path", ""))
    trace_payload = _trace_payload(trace, trace_id=run_id, node_id=node_id)
    asset = NodeRun(
        title=f"{operation} {status}",
        source=run_id,
        tags=["node-run", node_type, operation, status],
        content={
            "run_id": run_id,
            "node_id": node_id,
            "node_type": node_type,
            "operation": operation,
            "status": status,
            "input_assets": input_rows,
            "output_assets": output_rows,
            "processor": processor or {"kind": "local_service", "name": operation},
            "started_at": started_at or utc_now(),
            "finished_at": finished_at or utc_now(),
            "error": error,
            "quality_gate": quality_gate or {"required": False, "status": "not_applicable"},
            "human_gate": human_gate or {"required": False, "status": "not_required"},
            "trace": trace_payload,
        },
        metadata={
            "project_id": project_id,
            "workspace_path": workspace_path,
            "recorded_at": utc_now(),
            "node_contract_version": "0.1.0",
        },
        references=filter_project_safe_references(
            storage,
            project_id,
            _dedupe([run_id, *[row.get("id", "") for row in input_rows], *[row.get("path", "") for row in input_rows], *[row.get("id", "") for row in output_rows], *[row.get("path", "") for row in output_rows]]),
        ),
    )
    result = _write(storage, asset)
    try:
        record_trace_span(
            storage,
            trace_id=str(trace_payload.get("trace_id", run_id)),
            span_id=str(trace_payload.get("span_id", "")),
            parent_span_id=str(trace_payload.get("parent_span_id", "")),
            span_type="node_run",
            name=f"{node_id}:{operation}",
            status=_trace_span_status(status),
            started_at=str(asset.content.get("started_at", "")),
            finished_at=str(asset.content.get("finished_at", "")),
            attributes={
                "node_run_path": result.get("path", ""),
                "node_id": node_id,
                "node_type": node_type,
                "operation": operation,
                "status": status,
                "error": error,
            },
            references=[result.get("path", ""), *[row.get("path", "") for row in input_rows], *[row.get("path", "") for row in output_rows]],
            project_id=project_id,
            workspace_path=workspace_path,
        )
    except Exception:
        pass
    return result


def list_node_runs(storage: LocalStorage, *, project_id: str | None = None, run_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in reversed(storage.list_json("runs")):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "node_run":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if project_id and str(metadata.get("project_id", "")) != project_id:
            continue
        if run_id and str(content.get("run_id", "")) != run_id:
            continue
        rows.append(
            {
                "path": _display_path(storage.root, path),
                "id": data.get("id", ""),
                "run_id": content.get("run_id", ""),
                "node_id": content.get("node_id", ""),
                "node_type": content.get("node_type", ""),
                "operation": content.get("operation", ""),
                "status": content.get("status", ""),
                "input_count": len(content.get("input_assets", []) if isinstance(content.get("input_assets", []), list) else []),
                "output_count": len(content.get("output_assets", []) if isinstance(content.get("output_assets", []), list) else []),
                "project_id": metadata.get("project_id", ""),
                "workspace_path": metadata.get("workspace_path", ""),
                "started_at": content.get("started_at", ""),
                "finished_at": content.get("finished_at", ""),
                "error": content.get("error", ""),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def list_workflow_definitions(storage: LocalStorage, *, limit: int = 100) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in reversed(storage.list_json("runs")):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "workflow_definition":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        rows.append(
            {
                "path": _display_path(storage.root, path),
                "id": data.get("id", ""),
                "workflow_id": content.get("workflow_id", ""),
                "name": content.get("name", data.get("title", "")),
                "version": content.get("version", ""),
                "entry_node_id": content.get("entry_node_id", ""),
                "status": content.get("status", ""),
                "node_count": len(content.get("nodes", []) if isinstance(content.get("nodes", []), list) else []),
                "updated_at": data.get("updated_at", ""),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def list_workflow_runs(storage: LocalStorage, *, project_id: str | None = None, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in reversed(storage.list_json("runs")):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "workflow_run":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if project_id and str(metadata.get("project_id", "")) != project_id:
            continue
        if status and str(content.get("status", "")) != status:
            continue
        blocked = content.get("blocked", {}) if isinstance(content.get("blocked", {}), dict) else {}
        trace = content.get("trace", {}) if isinstance(content.get("trace", {}), dict) else {}
        rows.append(
            {
                "path": _display_path(storage.root, path),
                "id": data.get("id", ""),
                "run_id": content.get("run_id", ""),
                "workflow_id": content.get("workflow_id", ""),
                "status": content.get("status", ""),
                "blocked_node_id": blocked.get("node_id", ""),
                "blocked_status": blocked.get("status", ""),
                "blocked_reason": blocked.get("reason", ""),
                "node_run_count": len(content.get("node_runs", []) if isinstance(content.get("node_runs", []), list) else []),
                "agent_run_count": len(content.get("agent_runs", []) if isinstance(content.get("agent_runs", []), list) else []),
                "output_count": len(content.get("outputs", []) if isinstance(content.get("outputs", []), list) else []),
                "trace_id": trace.get("trace_id", content.get("run_id", "")),
                "project_id": metadata.get("project_id", ""),
                "workspace_path": metadata.get("workspace_path", ""),
                "started_at": content.get("started_at", ""),
                "finished_at": content.get("finished_at", ""),
                "updated_at": data.get("updated_at", ""),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def execute_workflow(
    storage: LocalStorage,
    workflow_path_or_id: str | Path,
    *,
    input_assets: list[str | Path] | None = None,
    run_id: str | None = None,
    start_node_id: str | None = None,
    max_nodes: int | None = None,
    dispatch_agents: bool = True,
    execute_agents: bool = False,
    apply_invalidation: bool = True,
    workspace_path: str | None = None,
) -> dict[str, Any]:
    """Execute the first deterministic slice of a WorkflowDefinition DAG.

    This runner is intentionally conservative: it validates DAG shape, evaluates
    blocking gates before a node runs, records every node as a NodeRun, and
    dispatches AgentRun assets for agent processors. It only auto-completes
    processors that are deterministic local bookkeeping operations.
    """

    storage.ensure_layout()
    workflow_path, workflow = _resolve_workflow_definition(storage, workflow_path_or_id)
    content = workflow.get("content", {}) if isinstance(workflow.get("content", {}), dict) else {}
    workflow_id = str(content.get("workflow_id") or workflow.get("id") or workflow_path_or_id)
    nodes = _workflow_nodes(storage, workflow)
    node_map = {str(node.get("node_id", "")): node for node in nodes if str(node.get("node_id", "")).strip()}
    entry_node_id = start_node_id or str(content.get("entry_node_id", ""))
    run_id = run_id or make_id("workflow_run", f"{workflow_id}-{utc_now()}")
    initial_inputs = [str(_display_path(storage.root, resolve_path(storage.root, item))) if _path_exists(storage, item) else str(item) for item in input_assets or []]
    now = utc_now()
    node_runs: list[dict[str, Any]] = []
    agent_runs: list[dict[str, Any]] = []
    invalidations: list[dict[str, Any]] = []
    outputs_by_node: dict[str, list[str]] = {}
    run_log: list[dict[str, Any]] = []

    try:
        order = _topological_order(node_map, entry_node_id)
    except Exception as exc:
        workflow_run = _write_workflow_run(
            storage,
            workflow=workflow,
            workflow_path=workflow_path,
            run_id=run_id,
            status="failed",
            started_at=now,
            outputs=[],
            run_log=[],
            error_message=f"{type(exc).__name__}: {exc}",
            recovery_instruction="Fix the WorkflowDefinition DAG: ensure entry_node_id exists, dependencies point to existing nodes, and cycles are removed.",
            workspace_path=workspace_path,
        )
        return {"status": "failed", "run_id": run_id, "workflow_run": workflow_run, "errors": [str(exc)], "order": []}

    executed_count = 0
    status = "completed"
    blocked: dict[str, Any] = {}
    errors: list[str] = []
    for node_id in order:
        if max_nodes is not None and max_nodes > 0 and executed_count >= max_nodes:
            status = "running"
            blocked = {"node_id": node_id, "status": "paused", "reason": "max_nodes reached"}
            break
        node = node_map[node_id]
        dependency_ids = _node_dependencies(node)
        dependency_statuses = [_last_status_for_node(run_log, dependency_id) for dependency_id in dependency_ids]
        if any(item not in WORKFLOW_SUCCESS_NODE_STATUSES for item in dependency_statuses):
            status = "running" if any(item == "waiting_human" for item in dependency_statuses) else "failed"
            blocked = {"node_id": node_id, "status": "blocked", "reason": "dependency not satisfied", "dependencies": dict(zip(dependency_ids, dependency_statuses))}
            break
        node_inputs = _node_inputs(storage, node, dependency_ids, outputs_by_node, initial_inputs)
        gate = _evaluate_node_gate(storage, node, node_inputs, run_id=run_id)
        if gate["status"] != "passed":
            node_run = record_node_run(
                storage,
                run_id=run_id,
                node_id=node_id,
                node_type=str(node.get("node_type", "workflow_node")),
                operation=str(node.get("operation", node_id)),
                status=gate["node_status"],
                input_assets=node_inputs,
                output_assets=[],
                processor=_node_processor(node),
                started_at=utc_now(),
                finished_at=utc_now(),
                error=gate["message"],
                quality_gate=gate["quality_gate"],
                human_gate=gate["human_gate"],
            )
            node_runs.append(node_run)
            run_log.append(_node_run_log_entry(node_run, agent_run=None, invalidation=None))
            status = "running" if gate["node_status"] == "waiting_human" else "failed"
            blocked = {"node_id": node_id, "status": gate["node_status"], "reason": gate["message"]}
            errors.append(gate["message"])
            break

        try:
            result = _execute_node(
                storage,
                run_id=run_id,
                node=node,
                input_assets=node_inputs,
                dispatch_agents=dispatch_agents,
                execute_agents=execute_agents,
                apply_invalidation=apply_invalidation,
                workspace_path=workspace_path,
            )
        except Exception as exc:
            error_message = f"{type(exc).__name__}: {exc}"
            node_run = record_node_run(
                storage,
                run_id=run_id,
                node_id=node_id,
                node_type=str(node.get("node_type", "workflow_node")),
                operation=str(node.get("operation", node_id)),
                status="failed",
                input_assets=node_inputs,
                output_assets=[],
                processor=_node_processor(node),
                started_at=utc_now(),
                finished_at=utc_now(),
                error=error_message,
                quality_gate={"required": False, "status": "failed"},
                human_gate={"required": False, "status": "not_required"},
            )
            node_runs.append(node_run)
            run_log.append(_node_run_log_entry(node_run, agent_run=None, invalidation=None))
            status = "failed"
            blocked = {"node_id": node_id, "status": "failed", "reason": error_message}
            errors.append(error_message)
            break
        node_runs.append(result["node_run"])
        if result.get("agent_run"):
            agent_runs.append(result["agent_run"])
        if result.get("invalidation"):
            invalidations.append(result["invalidation"])
        outputs_by_node[node_id] = [str(item) for item in result.get("output_assets", []) if str(item).strip()]
        run_log.append(_node_run_log_entry(result["node_run"], agent_run=result.get("agent_run"), invalidation=result.get("invalidation")))
        executed_count += 1
        node_status = str(result.get("status", ""))
        if node_status in WORKFLOW_BLOCKING_NODE_STATUSES:
            status = "running" if node_status in {"prepared", "waiting_human"} else "failed"
            blocked = {"node_id": node_id, "status": node_status, "reason": result.get("message", "")}
            if status == "failed":
                errors.append(str(result.get("message", "workflow node failed")))
            break
        if node_status not in WORKFLOW_SUCCESS_NODE_STATUSES:
            status = "running"
            blocked = {"node_id": node_id, "status": node_status, "reason": result.get("message", "")}
            break

    all_outputs = _dedupe([path for paths in outputs_by_node.values() for path in paths])
    node_run_paths = [str(item.get("path", "")) for item in node_runs if item.get("path")]
    if status == "completed" and not all_outputs:
        all_outputs = node_run_paths
    workflow_run = _write_workflow_run(
        storage,
        workflow=workflow,
        workflow_path=workflow_path,
        run_id=run_id,
        status=status,
        started_at=now,
        outputs=all_outputs,
        node_run_paths=node_run_paths,
        agent_run_paths=[str(item.get("path", "")) for item in agent_runs if item.get("path")],
        run_log=run_log,
        blocked=blocked,
        error_message="; ".join(errors),
        recovery_instruction=_workflow_recovery_instruction(status, blocked, errors),
        workspace_path=workspace_path,
    )
    return {
        "status": status,
        "run_id": run_id,
        "workflow_id": workflow_id,
        "workflow_path": _display_path(storage.root, workflow_path),
        "workflow_run": workflow_run,
        "node_runs": node_runs,
        "agent_runs": agent_runs,
        "invalidations": invalidations,
        "order": order,
        "blocked": blocked,
        "errors": errors,
    }


def resume_workflow(
    storage: LocalStorage,
    workflow_run_path_or_id: str | Path,
    *,
    resume_node_id: str | None = None,
    agent_run_path: str | Path | None = None,
    output_assets: list[str | Path] | None = None,
    token_used: int = 0,
    cost_estimate: float = 0.0,
    checkpoint: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
    human_gate: dict[str, Any] | None = None,
    tool_name: str | None = None,
    output_type: str | None = None,
    max_nodes: int | None = None,
    apply_invalidation: bool = True,
    workspace_path: str | None = None,
    archive_previous: bool = True,
) -> dict[str, Any]:
    storage.ensure_layout()
    previous_run_path, previous_run = _resolve_workflow_run(storage, workflow_run_path_or_id)
    previous_content = previous_run.get("content", {}) if isinstance(previous_run.get("content", {}), dict) else {}
    previous_run_id = str(previous_content.get("run_id") or previous_run.get("id") or previous_run_path.stem)
    workflow_ref = str(previous_content.get("workflow_definition_path") or previous_content.get("workflow_id") or previous_run.get("source", ""))
    workflow_path, workflow = _resolve_workflow_definition(storage, workflow_ref)
    content = workflow.get("content", {}) if isinstance(workflow.get("content", {}), dict) else {}
    workflow_id = str(content.get("workflow_id") or workflow.get("id") or workflow_ref)
    nodes = _workflow_nodes(storage, workflow)
    node_map = {str(node.get("node_id", "")): node for node in nodes if str(node.get("node_id", "")).strip()}
    order = _topological_order(node_map, str(content.get("entry_node_id", "")))
    previous_log = previous_content.get("run_log", []) if isinstance(previous_content.get("run_log", []), list) else []
    blocked = previous_content.get("blocked", {}) if isinstance(previous_content.get("blocked", {}), dict) else {}
    node_id = resume_node_id or str(blocked.get("node_id") or _last_non_success_node(previous_log) or "")
    if not node_id:
        raise ValueError("workflow_run has no blocked node to resume")
    if node_id not in node_map:
        raise ValueError(f"resume node does not exist in workflow definition: {node_id}")
    if node_id not in order:
        raise ValueError(f"resume node is not reachable from workflow entry: {node_id}")

    run_id = make_id("workflow_run", f"{previous_run_id}-{node_id}-resume")
    now = utc_now()
    run_log = [dict(item) for item in previous_log if isinstance(item, dict)]
    outputs_by_node = _outputs_by_node_from_run_log(run_log)
    node_runs: list[dict[str, Any]] = []
    agent_runs: list[dict[str, Any]] = []
    invalidations: list[dict[str, Any]] = []
    errors: list[str] = []
    new_outputs: list[str] = []
    status = "completed"
    current_blocked: dict[str, Any] = {}
    resume_index = order.index(node_id)

    resume_node = node_map[node_id]
    resume_result = _resume_blocked_node(
        storage,
        run_id=run_id,
        node=resume_node,
        previous_run_id=previous_run_id,
        previous_log=run_log,
        explicit_agent_run_path=agent_run_path,
        output_assets=output_assets or [],
        token_used=token_used,
        cost_estimate=cost_estimate,
        checkpoint=checkpoint,
        evidence=evidence or {},
        human_gate=human_gate,
        tool_name=tool_name,
        output_type=output_type,
        workspace_path=workspace_path,
    )
    node_runs.append(resume_result["node_run"])
    if resume_result.get("agent_run"):
        agent_runs.append(resume_result["agent_run"])
    outputs_by_node[node_id] = [str(item) for item in resume_result.get("output_assets", []) if str(item).strip()]
    new_outputs.extend(outputs_by_node[node_id])
    run_log.append(_node_run_log_entry(resume_result["node_run"], agent_run=resume_result.get("agent_run"), invalidation=None))
    if resume_result["status"] not in WORKFLOW_SUCCESS_NODE_STATUSES:
        status = "failed"
        current_blocked = {"node_id": node_id, "status": resume_result["status"], "reason": resume_result.get("message", "")}
        errors.append(str(resume_result.get("message", "resume node failed")))
    else:
        executed_count = 1
        for next_node_id in order[resume_index + 1 :]:
            if max_nodes is not None and max_nodes > 0 and executed_count >= max_nodes:
                status = "running"
                current_blocked = {"node_id": next_node_id, "status": "paused", "reason": "max_nodes reached"}
                break
            next_node = node_map[next_node_id]
            dependency_ids = _node_dependencies(next_node)
            dependency_statuses = [_last_status_for_node(run_log, dependency_id) for dependency_id in dependency_ids]
            if any(item not in WORKFLOW_SUCCESS_NODE_STATUSES for item in dependency_statuses):
                status = "running" if any(item in {"prepared", "waiting_human"} for item in dependency_statuses) else "failed"
                current_blocked = {"node_id": next_node_id, "status": "blocked", "reason": "dependency not satisfied", "dependencies": dict(zip(dependency_ids, dependency_statuses))}
                if status == "failed":
                    errors.append("dependency not satisfied")
                break
            node_inputs = _node_inputs(storage, next_node, dependency_ids, outputs_by_node, [])
            gate = _evaluate_node_gate(storage, next_node, node_inputs, run_id=run_id)
            if gate["status"] != "passed":
                node_run = record_node_run(
                    storage,
                    run_id=run_id,
                    node_id=next_node_id,
                    node_type=str(next_node.get("node_type", "workflow_node")),
                    operation=str(next_node.get("operation", next_node_id)),
                    status=gate["node_status"],
                    input_assets=node_inputs,
                    output_assets=[],
                    processor=_node_processor(next_node),
                    started_at=utc_now(),
                    finished_at=utc_now(),
                    error=gate["message"],
                    quality_gate=gate["quality_gate"],
                    human_gate=gate["human_gate"],
                )
                node_runs.append(node_run)
                run_log.append(_node_run_log_entry(node_run, agent_run=None, invalidation=None))
                status = "running" if gate["node_status"] == "waiting_human" else "failed"
                current_blocked = {"node_id": next_node_id, "status": gate["node_status"], "reason": gate["message"]}
                errors.append(gate["message"])
                break
            try:
                result = _execute_node(
                    storage,
                    run_id=run_id,
                    node=next_node,
                    input_assets=node_inputs,
                    dispatch_agents=True,
                    execute_agents=True,
                    apply_invalidation=apply_invalidation,
                    workspace_path=workspace_path,
                )
            except Exception as exc:
                error_message = f"{type(exc).__name__}: {exc}"
                node_run = record_node_run(
                    storage,
                    run_id=run_id,
                    node_id=next_node_id,
                    node_type=str(next_node.get("node_type", "workflow_node")),
                    operation=str(next_node.get("operation", next_node_id)),
                    status="failed",
                    input_assets=node_inputs,
                    output_assets=[],
                    processor=_node_processor(next_node),
                    started_at=utc_now(),
                    finished_at=utc_now(),
                    error=error_message,
                    quality_gate={"required": False, "status": "failed"},
                    human_gate={"required": False, "status": "not_required"},
                )
                node_runs.append(node_run)
                run_log.append(_node_run_log_entry(node_run, agent_run=None, invalidation=None))
                status = "failed"
                current_blocked = {"node_id": next_node_id, "status": "failed", "reason": error_message}
                errors.append(error_message)
                break
            node_runs.append(result["node_run"])
            if result.get("agent_run"):
                agent_runs.append(result["agent_run"])
            if result.get("invalidation"):
                invalidations.append(result["invalidation"])
            outputs_by_node[next_node_id] = [str(item) for item in result.get("output_assets", []) if str(item).strip()]
            new_outputs.extend(outputs_by_node[next_node_id])
            run_log.append(_node_run_log_entry(result["node_run"], agent_run=result.get("agent_run"), invalidation=result.get("invalidation")))
            executed_count += 1
            node_status = str(result.get("status", ""))
            if node_status in WORKFLOW_BLOCKING_NODE_STATUSES:
                status = "running" if node_status in {"prepared", "waiting_human"} else "failed"
                current_blocked = {"node_id": next_node_id, "status": node_status, "reason": result.get("message", "")}
                if status == "failed":
                    errors.append(str(result.get("message", "workflow node failed")))
                break
            if node_status not in WORKFLOW_SUCCESS_NODE_STATUSES:
                status = "running"
                current_blocked = {"node_id": next_node_id, "status": node_status, "reason": result.get("message", "")}
                break

    all_outputs = _dedupe([path for paths in outputs_by_node.values() for path in paths])
    previous_node_run_paths = previous_content.get("node_runs", []) if isinstance(previous_content.get("node_runs", []), list) else []
    previous_agent_run_paths = previous_content.get("agent_runs", []) if isinstance(previous_content.get("agent_runs", []), list) else []
    node_run_paths = _dedupe([*[str(item) for item in previous_node_run_paths], *[str(item.get("path", "")) for item in node_runs if item.get("path")]])
    agent_run_paths = _dedupe([*[str(item) for item in previous_agent_run_paths], *[str(item.get("path", "")) for item in agent_runs if item.get("path")]])
    if status == "completed" and not all_outputs:
        all_outputs = node_run_paths
    workflow_run = _write_workflow_run(
        storage,
        workflow=workflow,
        workflow_path=workflow_path,
        run_id=run_id,
        status=status,
        started_at=now,
        outputs=all_outputs,
        node_run_paths=node_run_paths,
        agent_run_paths=agent_run_paths,
        run_log=run_log,
        blocked=current_blocked,
        error_message="; ".join(errors),
        recovery_instruction=_workflow_recovery_instruction(status, current_blocked, errors),
        workspace_path=workspace_path,
        lineage={
            "resumed_from_run_id": previous_run_id,
            "resumed_from_run_path": _display_path(storage.root, previous_run_path),
            "resume_node_id": node_id,
            "new_output_assets": _dedupe(new_outputs),
        },
    )
    if archive_previous and status != "failed":
        _mark_workflow_run_superseded(
            storage,
            previous_run_path,
            superseded_by_run_id=run_id,
            superseded_by_path=str(workflow_run.get("path", "")),
            scheduler_tick_id=str((evidence or {}).get("scheduler_tick_id", "")),
        )
    return {
        "status": status,
        "run_id": run_id,
        "workflow_id": workflow_id,
        "workflow_path": _display_path(storage.root, workflow_path),
        "resumed_from_run_id": previous_run_id,
        "resumed_from_run_path": _display_path(storage.root, previous_run_path),
        "resume_node_id": node_id,
        "workflow_run": workflow_run,
        "node_runs": node_runs,
        "agent_runs": agent_runs,
        "invalidations": invalidations,
        "order": order,
        "blocked": current_blocked,
        "errors": errors,
    }


def run_workflow_scheduler(
    storage: LocalStorage,
    *,
    project_id: str | None = None,
    limit: int = 20,
    max_nodes_per_resume: int = 5,
    dry_run: bool = False,
    apply_invalidation: bool = True,
) -> dict[str, Any]:
    storage.ensure_layout()
    tick_id = make_id("workflow_scheduler_tick", utc_now())
    candidates = _scheduler_candidates(storage, project_id=project_id, limit=limit)
    resumed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for candidate in candidates:
        if dry_run:
            skipped.append({**candidate, "reason": "dry_run"})
            continue
        try:
            output_assets = _scheduler_output_assets(storage, candidate)
            if not output_assets:
                checkpoint = record_agent_checkpoint(
                    storage,
                    agent_run_path=candidate["agent_run_path"],
                    status="scheduler_waiting_for_outputs",
                    state={
                        "scheduler_tick_id": tick_id,
                        "workflow_run_path": candidate["workflow_run_path"],
                        "workflow_node_id": candidate["node_id"],
                        "reason": "prepared agent has no concrete output assets to attach",
                    },
                )
                skipped.append({**candidate, "reason": "missing_output_assets", "checkpoint_path": checkpoint.get("path", "")})
                continue
            result = resume_workflow(
                storage,
                candidate["workflow_run_path"],
                resume_node_id=candidate["node_id"],
                agent_run_path=candidate["agent_run_path"],
                output_assets=output_assets,
                token_used=int(candidate.get("token_used", 0) or 0),
                cost_estimate=float(candidate.get("cost_estimate", 0) or 0),
                checkpoint={"status": "scheduler_resume", "scheduler_tick_id": tick_id, "node_id": candidate["node_id"]},
                evidence={"scheduler_tick_id": tick_id, "scheduled_by": "workflow_scheduler"},
                max_nodes=max_nodes_per_resume,
                apply_invalidation=apply_invalidation,
                workspace_path=candidate.get("workspace_path") or None,
                archive_previous=True,
            )
            resumed.append(
                {
                    "workflow_run_path": candidate["workflow_run_path"],
                    "agent_run_path": candidate["agent_run_path"],
                    "node_id": candidate["node_id"],
                    "resume_run_id": result.get("run_id", ""),
                    "resume_workflow_run_path": result.get("workflow_run", {}).get("path", "") if isinstance(result.get("workflow_run", {}), dict) else "",
                    "status": result.get("status", ""),
                    "output_assets": output_assets,
                }
            )
        except Exception as exc:
            errors.append({"workflow_run_path": candidate.get("workflow_run_path", ""), "node_id": candidate.get("node_id", ""), "error": f"{type(exc).__name__}: {exc}"})
    return {
        "scheduler_tick_id": tick_id,
        "status": "failed" if errors else "completed",
        "dry_run": dry_run,
        "project_id": project_id or "",
        "candidate_count": len(candidates),
        "resumed_count": len(resumed),
        "skipped_count": len(skipped),
        "error_count": len(errors),
        "resumed": resumed,
        "skipped": skipped,
        "errors": errors,
        "recommendation": _scheduler_recommendation(resumed, skipped, errors),
    }


def run_workflow_scheduler_loop(
    storage: LocalStorage,
    *,
    project_id: str | None = None,
    limit: int = 20,
    max_nodes_per_resume: int = 5,
    iterations: int = 1,
    interval_seconds: float = 0.0,
    apply_invalidation: bool = True,
    stop_when_idle: bool = True,
    run_id: str | None = None,
    lease_ttl_seconds: int = 300,
    lease_owner: str = "",
    force_lease: bool = False,
) -> dict[str, Any]:
    storage.ensure_layout()
    from novel_forge.workflows.status import write_task_status

    loop_id = run_id or make_id("workflow_scheduler_loop", utc_now())
    status_paths: list[str] = []
    pending_path = write_task_status(storage, loop_id, "workflow-scheduler-loop", "pending")
    status_paths.append(_display_path(storage.root, pending_path))
    running_path = write_task_status(storage, loop_id, "workflow-scheduler-loop", "running")
    status_paths.append(_display_path(storage.root, running_path))
    owner = lease_owner or loop_id
    lease = acquire_scheduler_lease(
        storage,
        lease_key="workflow_scheduler",
        owner=owner,
        ttl_seconds=lease_ttl_seconds,
        force=force_lease,
    )
    if not lease.get("acquired"):
        skipped_path = write_task_status(storage, loop_id, "workflow-scheduler-loop", "cancelled", error_message="workflow scheduler lease is active")
        status_paths.append(_display_path(storage.root, skipped_path))
        return {
            "scheduler_loop_id": loop_id,
            "status": "skipped",
            "project_id": project_id or "",
            "tick_count": 0,
            "candidate_count": 0,
            "resumed_count": 0,
            "skipped_count": 0,
            "error_count": 0,
            "resumed": [],
            "skipped": [],
            "errors": [],
            "ticks": [],
            "latest_tick": {},
            "task_status_paths": status_paths,
            "lease": lease,
            "recommendation": "scheduler_lease_active",
        }
    ticks: list[dict[str, Any]] = []
    resumed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    try:
        for index in range(max(1, int(iterations or 1))):
            tick = run_workflow_scheduler(
                storage,
                project_id=project_id,
                limit=limit,
                max_nodes_per_resume=max_nodes_per_resume,
                dry_run=False,
                apply_invalidation=apply_invalidation,
            )
            tick["iteration"] = index + 1
            ticks.append(tick)
            resumed.extend([item for item in tick.get("resumed", []) if isinstance(item, dict)])
            skipped.extend([item for item in tick.get("skipped", []) if isinstance(item, dict)])
            errors.extend([item for item in tick.get("errors", []) if isinstance(item, dict)])
            if stop_when_idle and int(tick.get("candidate_count", 0) or 0) == 0:
                break
            if index + 1 < max(1, int(iterations or 1)) and interval_seconds > 0:
                time.sleep(min(float(interval_seconds), 60.0))
    except Exception as exc:
        failed_path = write_task_status(storage, loop_id, "workflow-scheduler-loop", "failed", error_message=f"{type(exc).__name__}: {exc}")
        status_paths.append(_display_path(storage.root, failed_path))
        release_scheduler_lease(storage, lease_key="workflow_scheduler", owner=owner, last_tick=ticks[-1].get("scheduler_tick_id", "") if ticks else "")
        raise

    final_status = "failed" if errors else "completed"
    output_paths = _dedupe(
        [
            *[str(item.get("resume_workflow_run_path", "")) for item in resumed],
            *[str(item.get("checkpoint_path", "")) for item in skipped],
            *status_paths,
        ]
    )
    final_path = write_task_status(
        storage,
        loop_id,
        "workflow-scheduler-loop",
        final_status,
        output_paths=output_paths if final_status == "completed" else [],
        error_message="; ".join(str(item.get("error", "")) for item in errors if item.get("error")) if errors else "",
    )
    status_paths.append(_display_path(storage.root, final_path))
    released_lease = release_scheduler_lease(storage, lease_key="workflow_scheduler", owner=owner, last_tick=ticks[-1].get("scheduler_tick_id", "") if ticks else "")
    return {
        "scheduler_loop_id": loop_id,
        "status": final_status,
        "project_id": project_id or "",
        "tick_count": len(ticks),
        "candidate_count": sum(int(tick.get("candidate_count", 0) or 0) for tick in ticks),
        "resumed_count": len(resumed),
        "skipped_count": len(skipped),
        "error_count": len(errors),
        "resumed": resumed,
        "skipped": skipped,
        "errors": errors,
        "ticks": ticks,
        "latest_tick": ticks[-1] if ticks else {},
        "task_status_paths": status_paths,
        "lease": released_lease.get("lease", lease.get("lease", {})) if isinstance(released_lease, dict) else lease.get("lease", {}),
        "recommendation": _scheduler_recommendation(resumed, skipped, errors),
    }


def _write(storage: LocalStorage, asset: WorkflowDefinition | WorkflowNode | NodeRun | WorkflowRun) -> dict[str, Any]:
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "asset": asset.to_dict(), "validation": {"ok": True, "errors": []}}


def _resume_blocked_node(
    storage: LocalStorage,
    *,
    run_id: str,
    node: dict[str, Any],
    previous_run_id: str,
    previous_log: list[dict[str, Any]],
    explicit_agent_run_path: str | Path | None,
    output_assets: list[str | Path],
    token_used: int,
    cost_estimate: float,
    checkpoint: dict[str, Any] | None,
    evidence: dict[str, Any],
    human_gate: dict[str, Any] | None,
    tool_name: str | None,
    output_type: str | None,
    workspace_path: str | None,
) -> dict[str, Any]:
    processor = _node_processor(node)
    kind = str(processor.get("kind") or processor.get("type") or "record_only").strip().lower()
    input_assets = _input_assets_for_node(previous_log, str(node.get("node_id", "")))
    if kind not in {"agent", "agent_dispatch"}:
        return _execute_node(
            storage,
            run_id=run_id,
            node=node,
            input_assets=input_assets,
            dispatch_agents=True,
            execute_agents=True,
            apply_invalidation=True,
            workspace_path=workspace_path,
        )
    node_id = str(node.get("node_id", ""))
    agent_path = str(explicit_agent_run_path or _agent_run_path_for_node(previous_log, node_id) or "")
    if not agent_path:
        raise ValueError(f"workflow resume could not find prepared agent_run for node {node_id}")
    output_types = [str(item) for item in node.get("output_types", []) if str(item).strip()] if isinstance(node.get("output_types", []), list) else []
    planned_outputs = _dedupe([str(item) for item in output_assets if str(item).strip()] or _expected_output_assets(node, processor))
    resume_evidence = {
        "workflow_run_id": run_id,
        "resumed_from_run_id": previous_run_id,
        "workflow_node_id": node_id,
        **evidence,
    }
    execution = execute_agent_run_once(
        storage,
        agent_path,
        tool_name=tool_name or str(processor.get("tool_name") or _tool_name_for_output(output_types)),
        output_type=output_type or (output_types[0] if output_types else None),
        token_used=token_used,
        cost_estimate=cost_estimate,
        output_assets=planned_outputs,
        checkpoint=checkpoint,
        evidence=resume_evidence,
        human_gate=human_gate,
    )
    status = "succeeded" if execution.get("status") == "succeeded" else "failed"
    processor_payload = {
        **processor,
        "agent_run_path": _execution_agent_run_path(execution, agent_path),
        "agent_budget_path": _result_path(execution.get("budget")),
        "agent_checkpoint_path": _result_path(execution.get("checkpoint")),
        "agent_sla_path": _result_path(execution.get("sla")),
        "agent_failure_path": _result_path(execution.get("failure")),
        "resumed_from_run_id": previous_run_id,
    }
    message = "prepared agent run resumed"
    error = ""
    if status != "succeeded":
        message = _execution_error_message(execution)
        error = message
        planned_outputs = []
    result = _record_executed_node(
        storage,
        run_id=run_id,
        node=node,
        status=status,
        input_assets=input_assets,
        output_assets=planned_outputs,
        processor=processor_payload,
        started_at=utc_now(),
        error=error,
        quality_gate={**(node.get("quality_gate", {}) if isinstance(node.get("quality_gate", {}), dict) else {}), "status": "passed" if status == "succeeded" else "failed"},
        human_gate=human_gate or (node.get("human_gate", {}) if isinstance(node.get("human_gate", {}), dict) else {"required": False, "status": "not_required"}),
        message=message,
    )
    result["agent_run"] = execution.get("run") if isinstance(execution.get("run"), dict) else {"path": processor_payload["agent_run_path"]}
    return result


def _resolve_workflow_run(storage: LocalStorage, value: str | Path) -> tuple[Path, dict[str, Any]]:
    candidate = resolve_path(storage.root, value)
    if candidate.exists() and candidate.is_file():
        data = storage.read_json(candidate)
        if isinstance(data, dict) and data.get("type") == "workflow_run":
            return candidate, data
        raise ValueError(f"workflow_run JSON expected: {candidate}")
    lookup = str(value)
    for path in storage.list_json("runs"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "workflow_run":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if lookup in {str(data.get("id", "")), str(content.get("run_id", "")), str(path.stem)}:
            return path, data
    raise FileNotFoundError(f"workflow_run not found: {value}")


def _resolve_workflow_definition(storage: LocalStorage, value: str | Path) -> tuple[Path, dict[str, Any]]:
    candidate = resolve_path(storage.root, value)
    if candidate.exists() and candidate.is_file():
        data = storage.read_json(candidate)
        if isinstance(data, dict) and data.get("type") == "workflow_definition":
            return candidate, data
        raise ValueError(f"workflow_definition JSON expected: {candidate}")
    lookup = str(value)
    for path in storage.list_json("runs"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "workflow_definition":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if lookup in {str(data.get("id", "")), str(content.get("workflow_id", "")), str(data.get("title", ""))}:
            return path, data
    raise FileNotFoundError(f"workflow_definition not found: {value}")


def _workflow_nodes(storage: LocalStorage, workflow: dict[str, Any]) -> list[dict[str, Any]]:
    content = workflow.get("content", {}) if isinstance(workflow.get("content", {}), dict) else {}
    workflow_id = str(content.get("workflow_id") or workflow.get("id") or "")
    rows: dict[str, dict[str, Any]] = {}
    for item in content.get("nodes", []) if isinstance(content.get("nodes", []), list) else []:
        if not isinstance(item, dict):
            continue
        node_id = str(item.get("node_id") or item.get("id") or "").strip()
        if not node_id:
            continue
        rows[node_id] = _normalize_node(item, workflow_id=workflow_id)
    for path in storage.list_json("runs"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "workflow_node":
            continue
        node_content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if str(node_content.get("workflow_id", "")) != workflow_id:
            continue
        node_id = str(node_content.get("node_id", "")).strip()
        if not node_id:
            continue
        merged = {**rows.get(node_id, {}), **node_content}
        rows[node_id] = _normalize_node(merged, workflow_id=workflow_id)
    if not rows:
        raise ValueError("workflow_definition has no executable nodes")
    return list(rows.values())


def _normalize_node(node: dict[str, Any], *, workflow_id: str) -> dict[str, Any]:
    processor = node.get("processor", {}) if isinstance(node.get("processor", {}), dict) else {}
    quality_gate = node.get("quality_gate", {}) if isinstance(node.get("quality_gate", {}), dict) else {}
    human_gate = node.get("human_gate", {}) if isinstance(node.get("human_gate", {}), dict) else {}
    return {
        **node,
        "node_id": str(node.get("node_id") or node.get("id") or ""),
        "workflow_id": str(node.get("workflow_id") or workflow_id),
        "node_type": str(node.get("node_type") or processor.get("node_type") or "workflow_node"),
        "operation": str(node.get("operation") or processor.get("operation") or node.get("node_id") or node.get("id") or ""),
        "input_types": [str(item) for item in node.get("input_types", []) if str(item).strip()] if isinstance(node.get("input_types", []), list) else [],
        "output_types": [str(item) for item in node.get("output_types", []) if str(item).strip()] if isinstance(node.get("output_types", []), list) else [],
        "depends_on": _dedupe([str(item) for item in node.get("depends_on", []) if str(item).strip()] if isinstance(node.get("depends_on", []), list) else []),
        "processor": processor or {"kind": "record_only"},
        "quality_gate": quality_gate or {"required": False},
        "human_gate": human_gate or {"required": False},
    }


def _topological_order(node_map: dict[str, dict[str, Any]], entry_node_id: str) -> list[str]:
    if not entry_node_id:
        raise ValueError("workflow_definition entry_node_id is required")
    if entry_node_id not in node_map:
        raise ValueError(f"entry_node_id does not exist in workflow nodes: {entry_node_id}")
    dependents: dict[str, list[str]] = {node_id: [] for node_id in node_map}
    indegree: dict[str, int] = {node_id: 0 for node_id in node_map}
    for node_id, node in node_map.items():
        for dependency in _node_dependencies(node):
            if dependency not in node_map:
                raise ValueError(f"node {node_id} depends on missing node {dependency}")
            dependents[dependency].append(node_id)
            indegree[node_id] += 1
    queue = sorted([node_id for node_id, count in indegree.items() if count == 0])
    ordered: list[str] = []
    while queue:
        node_id = queue.pop(0)
        ordered.append(node_id)
        for dependent in sorted(dependents[node_id]):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                queue.append(dependent)
                queue.sort()
    if len(ordered) != len(node_map):
        cyclic = sorted(node_id for node_id, count in indegree.items() if count > 0)
        raise ValueError(f"workflow DAG contains a cycle: {', '.join(cyclic)}")
    reachable = _reachable_nodes(entry_node_id, dependents)
    return [node_id for node_id in ordered if node_id in reachable]


def _reachable_nodes(entry_node_id: str, dependents: dict[str, list[str]]) -> set[str]:
    seen: set[str] = set()
    stack = [entry_node_id]
    while stack:
        node_id = stack.pop()
        if node_id in seen:
            continue
        seen.add(node_id)
        stack.extend(dependents.get(node_id, []))
    return seen


def _node_dependencies(node: dict[str, Any]) -> list[str]:
    return [str(item) for item in node.get("depends_on", []) if str(item).strip()] if isinstance(node.get("depends_on", []), list) else []


def _node_processor(node: dict[str, Any]) -> dict[str, Any]:
    processor = node.get("processor", {}) if isinstance(node.get("processor", {}), dict) else {}
    return processor or {"kind": "record_only", "name": node.get("operation", node.get("node_id", ""))}


def _node_inputs(
    storage: LocalStorage,
    node: dict[str, Any],
    dependency_ids: list[str],
    outputs_by_node: dict[str, list[str]],
    initial_inputs: list[str],
) -> list[str]:
    explicit = [str(item) for item in node.get("input_assets", []) if str(item).strip()] if isinstance(node.get("input_assets", []), list) else []
    dependency_outputs = [path for dependency_id in dependency_ids for path in outputs_by_node.get(dependency_id, [])]
    if explicit:
        values = explicit
    elif dependency_outputs:
        values = dependency_outputs
    else:
        values = initial_inputs
    return _dedupe([_display_path(storage.root, resolve_path(storage.root, item)) if _path_exists(storage, item) else str(item) for item in values])


def _evaluate_node_gate(storage: LocalStorage, node: dict[str, Any], input_assets: list[str], *, run_id: str = "") -> dict[str, Any]:
    quality_gate = dict(node.get("quality_gate", {}) if isinstance(node.get("quality_gate", {}), dict) else {})
    human_gate = dict(node.get("human_gate", {}) if isinstance(node.get("human_gate", {}), dict) else {})
    trace = _gate_trace(run_id, str(node.get("node_id", "")), "static")
    human_required = bool(human_gate.get("required", False))
    human_status = str(human_gate.get("status", "") or "").lower()
    if human_required and human_status not in {"approved", "accepted", "passed"}:
        human_gate["status"] = human_status or "waiting"
        return _record_gate_decision(
            storage,
            node=node,
            input_assets=input_assets,
            gate_kind="human",
            decision={
            "status": "blocked",
            "node_status": "waiting_human",
            "message": "human gate is required before this node can run",
            "quality_gate": quality_gate or {"required": False, "status": "not_evaluated"},
            "human_gate": human_gate,
            },
            trace=trace,
        )
    gate_status = str(quality_gate.get("status", "") or "").lower()
    if gate_status in {"failed", "blocked", "rejected"}:
        return _record_gate_decision(
            storage,
            node=node,
            input_assets=input_assets,
            gate_kind="static_quality",
            decision={
            "status": "blocked",
            "node_status": "failed",
            "message": str(quality_gate.get("message") or "quality gate failed"),
            "quality_gate": {**quality_gate, "status": gate_status},
            "human_gate": human_gate or {"required": False, "status": "not_required"},
            },
            trace=trace,
        )
    min_input_count = int(quality_gate.get("min_input_count", 0) or 0)
    if min_input_count and len(input_assets) < min_input_count:
        return _record_gate_decision(
            storage,
            node=node,
            input_assets=input_assets,
            gate_kind="input_count",
            decision={
            "status": "blocked",
            "node_status": "failed",
            "message": f"quality gate requires at least {min_input_count} input assets",
            "quality_gate": {**quality_gate, "status": "failed"},
            "human_gate": human_gate or {"required": False, "status": "not_required"},
            },
            trace=trace,
        )
    missing_types = _missing_required_input_types(storage, node, input_assets)
    if missing_types:
        return _record_gate_decision(
            storage,
            node=node,
            input_assets=input_assets,
            gate_kind="input_type",
            decision={
            "status": "blocked",
            "node_status": "failed",
            "message": f"missing required input asset types: {', '.join(missing_types)}",
            "quality_gate": {**quality_gate, "status": "failed"},
            "human_gate": human_gate or {"required": False, "status": "not_required"},
            },
            trace=trace,
        )
    stale_inputs = _stale_inputs(storage, input_assets) if quality_gate.get("block_on_stale_inputs") else []
    if stale_inputs:
        return _record_gate_decision(
            storage,
            node=node,
            input_assets=input_assets,
            gate_kind="stale_input",
            decision={
            "status": "blocked",
            "node_status": "failed",
            "message": f"stale input assets blocked execution: {', '.join(stale_inputs[:3])}",
            "quality_gate": {**quality_gate, "status": "failed", "stale_inputs": stale_inputs},
            "human_gate": human_gate or {"required": False, "status": "not_required"},
            },
            trace=trace,
        )
    registry = _evaluate_gate_registry(
        storage,
        node=node,
        input_assets=input_assets,
        run_id=run_id,
        quality_gate=quality_gate,
        human_gate=human_gate,
    )
    if registry["status"] != "passed":
        return registry
    return {
        "status": "passed",
        "node_status": "running",
        "message": "",
        "quality_gate": {
            **quality_gate,
            "status": "passed" if quality_gate.get("required") else quality_gate.get("status", "not_applicable"),
            "registry_results": registry.get("registry_results", []),
        },
        "human_gate": human_gate or {"required": False, "status": "not_required"},
    }


def _execute_node(
    storage: LocalStorage,
    *,
    run_id: str,
    node: dict[str, Any],
    input_assets: list[str],
    dispatch_agents: bool,
    execute_agents: bool,
    apply_invalidation: bool,
    workspace_path: str | None,
) -> dict[str, Any]:
    started_at = utc_now()
    processor = _node_processor(node)
    kind = str(processor.get("kind") or processor.get("type") or "record_only").strip().lower()
    operation = str(node.get("operation") or processor.get("operation") or node.get("node_id", ""))
    output_assets = _expected_output_assets(node, processor)
    quality_gate = dict(node.get("quality_gate", {}) if isinstance(node.get("quality_gate", {}), dict) else {})
    human_gate = dict(node.get("human_gate", {}) if isinstance(node.get("human_gate", {}), dict) else {})

    if kind in {"manual", "human"}:
        return _record_executed_node(
            storage,
            run_id=run_id,
            node=node,
            status="waiting_human",
            input_assets=input_assets,
            output_assets=[],
            processor=processor,
            started_at=started_at,
            error="manual workflow node requires human completion",
            quality_gate={**quality_gate, "status": quality_gate.get("status", "not_applicable")},
            human_gate={**human_gate, "required": True, "status": human_gate.get("status", "waiting")},
            message="manual workflow node requires human completion",
        )

    if kind in {"agent", "agent_dispatch"}:
        return _dispatch_agent_node(
            storage,
            run_id=run_id,
            node=node,
            input_assets=input_assets,
            output_assets=output_assets,
            processor=processor,
            started_at=started_at,
            dispatch_agents=dispatch_agents,
            execute_agents=execute_agents,
            workspace_path=workspace_path,
        )

    if kind in {"service", "local_service"}:
        checkpoint_state = _processor_checkpoint_state(storage, node=node, processor=processor, input_assets=input_assets, workspace_path=workspace_path)
        checkpoint_hit = _checkpoint_resume_hit(storage, checkpoint_state)
        if checkpoint_hit:
            output_assets = _dedupe([*output_assets, *checkpoint_hit.get("output_assets", [])])
            return _record_executed_node(
                storage,
                run_id=run_id,
                node=node,
                status="recovered",
                input_assets=input_assets,
                output_assets=output_assets,
                processor={**processor, "checkpoint": checkpoint_state, "resumed_from_checkpoint": True},
                started_at=started_at,
                quality_gate={**quality_gate, "status": "passed"},
                human_gate=human_gate or {"required": False, "status": "not_required"},
                message="service processor resumed from checkpoint",
            )
        service_result = _execute_registered_service_processor(
            storage,
            processor={**processor, "operation": processor.get("operation") or operation},
            input_assets=input_assets,
            workspace_path=workspace_path,
        )
        output_assets = _dedupe([*output_assets, *service_result.get("output_assets", [])])
        checkpoint_state["output_assets"] = output_assets
        service_result["checkpoint"] = checkpoint_state
        status = str(service_result.get("status", "succeeded"))
        return _record_executed_node(
            storage,
            run_id=run_id,
            node=node,
            status=status,
            input_assets=input_assets,
            output_assets=output_assets,
            processor={**processor, "registry_operation": service_result.get("operation", ""), "registry_payload": service_result.get("payload", {}), "checkpoint": checkpoint_state},
            started_at=started_at,
            error=str(service_result.get("error", "")),
            quality_gate={**quality_gate, "status": "passed" if status == "succeeded" else "failed"},
            human_gate=human_gate or {"required": False, "status": "not_required"},
            message=str(service_result.get("message", "")),
        )

    if kind in {"change_impact", "impact"}:
        target_path = str(processor.get("target_path") or (input_assets[0] if input_assets else ""))
        if not target_path:
            raise ValueError(f"workflow node {node.get('node_id')} requires a target_path or input asset for change impact")
        impact = create_change_impact_report(
            storage,
            target_path,
            max_depth=int(processor.get("max_depth", 4) or 4),
            project_id=str(processor.get("project_id") or "") or None,
        )
        output_assets = [str(impact["path"])]
        result = _record_executed_node(
            storage,
            run_id=run_id,
            node=node,
            status="succeeded",
            input_assets=input_assets,
            output_assets=output_assets,
            processor=processor,
            started_at=started_at,
            quality_gate={**quality_gate, "status": "passed"},
            human_gate=human_gate or {"required": False, "status": "not_required"},
        )
        result["invalidation"] = {"impact_report": impact, "applied": False}
        return result

    if kind in {"invalidation", "mark_stale"}:
        target_path = str(processor.get("target_path") or (input_assets[0] if input_assets else ""))
        if not target_path:
            raise ValueError(f"workflow node {node.get('node_id')} requires a target_path or input asset for invalidation")
        invalidation = mark_downstream_assets_stale(
            storage,
            target_path,
            max_depth=int(processor.get("max_depth", 4) or 4),
            project_id=str(processor.get("project_id") or "") or None,
            reason=str(processor.get("reason") or "workflow upstream asset changed"),
            apply=bool(apply_invalidation and processor.get("apply", True)),
        )
        impact_report = invalidation.get("impact_report", {}) if isinstance(invalidation.get("impact_report", {}), dict) else {}
        output_assets = [str(impact_report.get("path", ""))] if impact_report.get("path") else []
        status = "failed" if invalidation.get("status") == "failed" else "succeeded"
        result = _record_executed_node(
            storage,
            run_id=run_id,
            node=node,
            status=status,
            input_assets=input_assets,
            output_assets=output_assets,
            processor=processor,
            started_at=started_at,
            error="; ".join(invalidation.get("errors", []) if isinstance(invalidation.get("errors", []), list) else []),
            quality_gate={**quality_gate, "status": "passed" if status == "succeeded" else "failed"},
            human_gate=human_gate or {"required": False, "status": "not_required"},
        )
        result["invalidation"] = invalidation
        return result

    if kind in {"noop", "local_noop", "record_only", "deterministic"}:
        status = str(processor.get("status") or "succeeded")
        return _record_executed_node(
            storage,
            run_id=run_id,
            node=node,
            status=status,
            input_assets=input_assets,
            output_assets=output_assets,
            processor=processor,
            started_at=started_at,
            quality_gate={**quality_gate, "status": "passed"},
            human_gate=human_gate or {"required": False, "status": "not_required"},
        )

    return _record_executed_node(
        storage,
        run_id=run_id,
        node=node,
        status="failed",
        input_assets=input_assets,
        output_assets=[],
        processor=processor,
        started_at=started_at,
        error=f"unsupported workflow processor kind: {kind}",
        quality_gate={**quality_gate, "status": "failed"},
        human_gate=human_gate or {"required": False, "status": "not_required"},
        message=f"unsupported workflow processor kind: {kind}",
    )


def _dispatch_agent_node(
    storage: LocalStorage,
    *,
    run_id: str,
    node: dict[str, Any],
    input_assets: list[str],
    output_assets: list[str],
    processor: dict[str, Any],
    started_at: str,
    dispatch_agents: bool,
    execute_agents: bool,
    workspace_path: str | None,
) -> dict[str, Any]:
    if not dispatch_agents:
        return _record_executed_node(
            storage,
            run_id=run_id,
            node=node,
            status="planned",
            input_assets=input_assets,
            output_assets=[],
            processor=processor,
            started_at=started_at,
            quality_gate={**(node.get("quality_gate", {}) if isinstance(node.get("quality_gate", {}), dict) else {}), "status": "passed"},
            human_gate=node.get("human_gate", {}) if isinstance(node.get("human_gate", {}), dict) else {"required": False, "status": "not_required"},
            message="agent dispatch disabled",
        )
    agent_key = str(processor.get("agent_key") or node.get("agent_key") or "")
    skill = str(processor.get("skill") or node.get("skill") or "")
    operation = str(processor.get("operation") or node.get("operation") or node.get("node_id"))
    output_types = [str(item) for item in node.get("output_types", []) if str(item).strip()] if isinstance(node.get("output_types", []), list) else []
    contract = ensure_agent_contract(
        storage,
        agent_key=agent_key,
        skill=skill,
        operation=operation,
        input_types=[str(item) for item in node.get("input_types", []) if str(item).strip()] if isinstance(node.get("input_types", []), list) else [],
        output_types=output_types,
        quality_gates=[node.get("quality_gate", {})] if isinstance(node.get("quality_gate", {}), dict) and node.get("quality_gate", {}) else [],
        workspace_path=workspace_path,
    )
    agent_status = "running" if execute_agents else str(processor.get("agent_status") or "prepared")
    agent_run = start_agent_run(
        storage,
        agent_key=agent_key,
        skill=skill,
        operation=operation,
        input_assets=input_assets,
        output_assets=[],
        status=agent_status,
        contract_path=contract["path"],
        workspace_path=workspace_path,
        model_provider=str(processor.get("model_provider") or "local"),
        model_name=str(processor.get("model_name") or "local"),
        prompt_version=str(processor.get("prompt_version") or "prompt-v1"),
        token_budget=int(processor.get("token_budget", 0) or 0),
        evidence={"workflow_run_id": run_id, "workflow_node_id": node.get("node_id", "")},
    )
    node_status = "prepared"
    message = "agent run dispatched"
    if execute_agents:
        execution = execute_agent_run_once(
            storage,
            agent_run["path"],
            tool_name=str(processor.get("tool_name") or _tool_name_for_output(output_types)),
            output_type=output_types[0] if output_types else None,
            token_used=int(processor.get("token_used", 0) or 0),
            cost_estimate=float(processor.get("cost_estimate", 0) or 0),
            output_assets=output_assets,
            evidence={"workflow_run_id": run_id, "workflow_node_id": node.get("node_id", "")},
        )
        agent_run = execution.get("run", agent_run) if isinstance(execution, dict) else agent_run
        node_status = "succeeded" if isinstance(execution, dict) and execution.get("status") == "succeeded" else "failed"
        message = "agent run executed once" if node_status == "succeeded" else "agent run failed"
    result = _record_executed_node(
        storage,
        run_id=run_id,
        node=node,
        status=node_status,
        input_assets=input_assets,
        output_assets=output_assets if node_status == "succeeded" else [],
        processor={**processor, "agent_run_path": agent_run.get("path", "")},
        started_at=started_at,
        quality_gate={**(node.get("quality_gate", {}) if isinstance(node.get("quality_gate", {}), dict) else {}), "status": "passed" if node_status != "failed" else "failed"},
        human_gate=node.get("human_gate", {}) if isinstance(node.get("human_gate", {}), dict) else {"required": False, "status": "not_required"},
        message=message,
    )
    result["agent_run"] = agent_run
    return result


def _record_executed_node(
    storage: LocalStorage,
    *,
    run_id: str,
    node: dict[str, Any],
    status: str,
    input_assets: list[str],
    output_assets: list[str],
    processor: dict[str, Any],
    started_at: str,
    error: str = "",
    quality_gate: dict[str, Any] | None = None,
    human_gate: dict[str, Any] | None = None,
    message: str = "",
) -> dict[str, Any]:
    node_run = record_node_run(
        storage,
        run_id=run_id,
        node_id=str(node.get("node_id", "")),
        node_type=str(node.get("node_type", "workflow_node")),
        operation=str(node.get("operation", node.get("node_id", ""))),
        status=status,
        input_assets=input_assets,
        output_assets=output_assets,
        processor=processor,
        started_at=started_at,
        finished_at=utc_now() if status in WORKFLOW_TERMINAL_NODE_STATUSES or status in {"prepared", "waiting_human", "planned"} else "",
        error=error,
        quality_gate=quality_gate,
        human_gate=human_gate,
    )
    return {"status": status, "node_run": node_run, "output_assets": output_assets, "message": message or error}


def _write_workflow_run(
    storage: LocalStorage,
    *,
    workflow: dict[str, Any],
    workflow_path: Path,
    run_id: str,
    status: str,
    started_at: str,
    outputs: list[str],
    run_log: list[dict[str, Any]],
    node_run_paths: list[str] | None = None,
    agent_run_paths: list[str] | None = None,
    blocked: dict[str, Any] | None = None,
    error_message: str = "",
    recovery_instruction: str = "",
    workspace_path: str | None = None,
    lineage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    content = workflow.get("content", {}) if isinstance(workflow.get("content", {}), dict) else {}
    output_refs = [_asset_ref(storage, item) for item in outputs]
    project = _project_scope_from_refs(storage, output_refs)
    project_id = str(project.get("project_id", ""))
    asset = WorkflowRun(
        id=run_id,
        title=f"{content.get('name') or workflow.get('title') or 'workflow'} execution",
        source=str(content.get("workflow_id") or workflow.get("id", "")),
        tags=["workflow-executor", status],
        content={
            "run_id": run_id,
            "workflow_id": content.get("workflow_id") or workflow.get("id", ""),
            "workflow_definition_path": _display_path(storage.root, workflow_path),
            "status": status,
            "outputs": outputs,
            "node_runs": node_run_paths or [],
            "agent_runs": agent_run_paths or [],
            "run_log": run_log,
            "blocked": blocked or {},
            "error_message": error_message,
            "recovery_instruction": recovery_instruction,
            "lineage": lineage or {},
            "trace": {"trace_id": run_id, "span_id": make_id("span", f"{run_id}-workflow-{utc_now()}"), "parent_span_id": ""},
            "started_at": started_at,
            "finished_at": utc_now() if status in WORKFLOW_RUN_TERMINAL_STATUSES else "",
        },
        metadata={
            "project_id": project_id,
            "workspace_path": str(project.get("workspace_path") or workspace_path or ""),
            "executor_version": "0.1.0",
            "recorded_at": utc_now(),
        },
        references=filter_project_safe_references(
            storage,
            project_id,
            _dedupe([
                str(content.get("workflow_id") or workflow.get("id", "")),
                _display_path(storage.root, workflow_path),
                *(node_run_paths or []),
                *(agent_run_paths or []),
                *outputs,
            ]),
        ),
    )
    result = _write(storage, asset)
    try:
        trace = asset.content.get("trace", {}) if isinstance(asset.content.get("trace", {}), dict) else {}
        record_trace_span(
            storage,
            trace_id=run_id,
            span_id=str(trace.get("span_id", "")),
            parent_span_id="",
            span_type="workflow_run",
            name=str(content.get("name") or workflow.get("title") or "workflow"),
            status=_trace_span_status(status),
            started_at=started_at,
            finished_at=str(asset.content.get("finished_at", "")),
            attributes={
                "workflow_run_path": result.get("path", ""),
                "workflow_id": content.get("workflow_id") or workflow.get("id", ""),
                "status": status,
                "blocked": blocked or {},
                "lineage": lineage or {},
            },
            references=[result.get("path", ""), _display_path(storage.root, workflow_path), *(node_run_paths or []), *(agent_run_paths or [])],
            project_id=project_id,
            workspace_path=str(project.get("workspace_path") or workspace_path or ""),
        )
    except Exception:
        pass
    return result


def _node_run_log_entry(node_run: dict[str, Any], *, agent_run: dict[str, Any] | None, invalidation: dict[str, Any] | None) -> dict[str, Any]:
    asset = node_run.get("asset", {}) if isinstance(node_run.get("asset", {}), dict) else {}
    content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
    entry = {
        "node_run_path": node_run.get("path", ""),
        "node_id": content.get("node_id", ""),
        "node_type": content.get("node_type", ""),
        "operation": content.get("operation", ""),
        "status": content.get("status", ""),
        "input_assets": content.get("input_assets", []),
        "output_assets": content.get("output_assets", []),
        "quality_gate": content.get("quality_gate", {}),
        "human_gate": content.get("human_gate", {}),
        "error": content.get("error", ""),
        "started_at": content.get("started_at", ""),
        "finished_at": content.get("finished_at", ""),
    }
    if agent_run:
        entry["agent_run_path"] = agent_run.get("path", "")
    if invalidation:
        impact_report = invalidation.get("impact_report", {}) if isinstance(invalidation.get("impact_report", {}), dict) else {}
        entry["change_impact_report_path"] = impact_report.get("path", "")
        entry["invalidated_count"] = len(invalidation.get("updated_assets", []) if isinstance(invalidation.get("updated_assets", []), list) else [])
    return entry


def _last_status_for_node(run_log: list[dict[str, Any]], node_id: str) -> str:
    for entry in reversed(run_log):
        if str(entry.get("node_id", "")) == node_id:
            return str(entry.get("status", ""))
    return "planned"


def _expected_output_assets(node: dict[str, Any], processor: dict[str, Any]) -> list[str]:
    for key in ["output_assets", "expected_output_assets"]:
        values = node.get(key)
        if isinstance(values, list) and values:
            return _dedupe([str(item) for item in values if str(item).strip()])
    for key in ["output_assets", "expected_output_assets"]:
        values = processor.get(key)
        if isinstance(values, list) and values:
            return _dedupe([str(item) for item in values if str(item).strip()])
    return []


def _processor_checkpoint_state(
    storage: LocalStorage,
    *,
    node: dict[str, Any],
    processor: dict[str, Any],
    input_assets: list[str],
    workspace_path: str | None,
) -> dict[str, Any]:
    operation = str(processor.get("operation") or node.get("operation") or processor.get("name") or node.get("node_id", ""))
    expected_outputs = _expected_output_assets(node, processor)
    idempotency_key = str(processor.get("idempotency_key") or make_id("processor_checkpoint", f"{node.get('workflow_id', '')}-{node.get('node_id', '')}-{operation}-{'|'.join(input_assets)}-{'|'.join(expected_outputs)}"))
    return {
        "checkpoint_schema": processor.get("checkpoint_schema") if isinstance(processor.get("checkpoint_schema"), dict) else {"version": "0.1.0", "operation": operation},
        "resume_from_checkpoint": bool(processor.get("resume_from_checkpoint", False)),
        "idempotency_key": idempotency_key,
        "operation": operation,
        "node_id": str(node.get("node_id", "")),
        "input_assets": input_assets,
        "expected_output_assets": expected_outputs,
        "workspace_path": workspace_path or "",
        "created_at": utc_now(),
    }


def _checkpoint_resume_hit(storage: LocalStorage, checkpoint_state: dict[str, Any]) -> dict[str, Any]:
    if not bool(checkpoint_state.get("resume_from_checkpoint", False)):
        return {}
    expected = [str(item) for item in checkpoint_state.get("expected_output_assets", []) if str(item).strip()] if isinstance(checkpoint_state.get("expected_output_assets", []), list) else []
    existing = [_display_path(storage.root, resolve_path(storage.root, item)) for item in expected if _path_exists(storage, item)]
    if expected and len(existing) == len(expected):
        return {"status": "recovered", "output_assets": existing, "reason": "expected outputs exist"}
    return {}


def _missing_required_input_types(storage: LocalStorage, node: dict[str, Any], input_assets: list[str]) -> list[str]:
    required = [str(item) for item in node.get("input_types", []) if str(item).strip()] if isinstance(node.get("input_types", []), list) else []
    if not required:
        return []
    actual: set[str] = set()
    for item in input_assets:
        try:
            actual.add(storage.read_asset(resolve_path(storage.root, item)).type)
        except Exception:
            continue
    return [asset_type for asset_type in required if asset_type not in actual]


def _stale_inputs(storage: LocalStorage, input_assets: list[str]) -> list[str]:
    stale: list[str] = []
    for item in input_assets:
        try:
            data = storage.read_json(resolve_path(storage.root, item))
        except Exception:
            continue
        metadata = data.get("metadata", {}) if isinstance(data, dict) and isinstance(data.get("metadata", {}), dict) else {}
        if metadata.get("asset_status") == "stale":
            stale.append(str(item))
    return stale


def _evaluate_gate_registry(
    storage: LocalStorage,
    *,
    node: dict[str, Any],
    input_assets: list[str],
    run_id: str,
    quality_gate: dict[str, Any],
    human_gate: dict[str, Any],
) -> dict[str, Any]:
    specs = _gate_specs(node)
    if not specs:
        return {"status": "passed", "registry_results": []}
    results: list[dict[str, Any]] = []
    for index, spec in enumerate(specs):
        kind = str(spec.get("kind") or spec.get("gate") or "").strip().lower()
        if not kind or not bool(spec.get("required", True)):
            continue
        trace = _gate_trace(run_id, str(node.get("node_id", "")), f"{kind}-{index + 1}")
        try:
            evaluation = _evaluate_gate_spec(storage, node=node, spec=spec, input_assets=input_assets, workspace_path=str(spec.get("workspace_path") or ""))
        except Exception as exc:
            evaluation = {"status": "failed", "message": f"{type(exc).__name__}: {exc}", "result": {"error": str(exc)}}
        status = str(evaluation.get("status", "failed"))
        target_paths = [str(item) for item in spec.get("target_paths", [])] if isinstance(spec.get("target_paths", []), list) else input_assets
        gate_result = record_gate_result(
            storage,
            gate_kind=kind,
            status=status,
            target_paths=target_paths,
            result=evaluation.get("result", {}) if isinstance(evaluation.get("result", {}), dict) else {"result": evaluation.get("result")},
            trace=trace,
            project_id=_project_id_for_paths(storage, target_paths),
            workspace_path=str(spec.get("workspace_path") or ""),
            message=str(evaluation.get("message", "")),
            blocking=bool(spec.get("blocking", True)),
        )
        row = {
            "kind": kind,
            "status": status,
            "message": str(evaluation.get("message", "")),
            "gate_result_path": gate_result.get("path", ""),
        }
        results.append(row)
        if status == "failed" and bool(spec.get("blocking", True)):
            return {
                "status": "blocked",
                "node_status": "failed",
                "message": row["message"] or f"{kind} gate failed",
                "quality_gate": {**quality_gate, "status": "failed", "registry_results": results},
                "human_gate": human_gate or {"required": False, "status": "not_required"},
            }
    return {"status": "passed", "registry_results": results}


def _gate_specs(node: dict[str, Any]) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    quality_gate = node.get("quality_gate", {}) if isinstance(node.get("quality_gate", {}), dict) else {}
    for value in quality_gate.get("gates", []) if isinstance(quality_gate.get("gates", []), list) else []:
        if isinstance(value, dict):
            specs.append(value)
    for key in ["kind", "gate"]:
        if str(quality_gate.get(key, "")).strip():
            specs.append(quality_gate)
            break
    for value in node.get("gates", []) if isinstance(node.get("gates", []), list) else []:
        if isinstance(value, dict):
            specs.append(value)
    return specs


def _evaluate_gate_spec(
    storage: LocalStorage,
    *,
    node: dict[str, Any],
    spec: dict[str, Any],
    input_assets: list[str],
    workspace_path: str,
) -> dict[str, Any]:
    kind = str(spec.get("kind") or spec.get("gate") or "").strip().lower()
    if kind == "schema":
        return _schema_gate(storage, input_assets)
    if kind == "review":
        return _report_gate(storage, input_assets, report_types={"review_report", "quality_score_report", "chapter_audit_report"}, block_recommendations={"block", "needs_revision", "revise", "reject"}, service_operation="review", spec=spec, workspace_path=workspace_path)
    if kind == "originality":
        return _report_gate(storage, input_assets, report_types={"originality_report"}, block_recommendations={"block", "block_publish", "reject"}, service_operation="originality_report", spec=spec, workspace_path=workspace_path)
    if kind == "publish":
        return _report_gate(storage, input_assets, report_types={"publish_gate_report"}, block_recommendations={"block", "blocked", "reject", "needs_revision"}, service_operation="publish_gate_report", spec=spec, workspace_path=workspace_path)
    if kind == "continuity":
        return _report_gate(storage, input_assets, report_types={"chapter_continuity_report", "chapter_stability_preflight_report", "canon_graph_snapshot", "continuity_graph_snapshot"}, block_recommendations={"block", "blocked", "reject", "needs_revision"}, service_operation=str(spec.get("operation") or "chapter_stability_preflight"), spec=spec, workspace_path=workspace_path)
    if kind == "custom_service":
        processor = spec.get("processor", {}) if isinstance(spec.get("processor", {}), dict) else {}
        operation = str(spec.get("operation") or processor.get("operation") or "").strip()
        if not operation:
            return {"status": "failed", "message": "custom_service gate requires operation", "result": {}}
        result = _execute_registered_service_processor(
            storage,
            processor={**processor, **spec, "operation": operation},
            input_assets=input_assets,
            workspace_path=workspace_path or None,
        )
        status = "failed" if str(result.get("status", "")) == "failed" else "passed"
        return {"status": status, "message": str(result.get("error") or result.get("message") or ""), "result": result}
    return {"status": "failed", "message": f"unknown gate kind: {kind}", "result": {"kind": kind}}


def _schema_gate(storage: LocalStorage, input_assets: list[str]) -> dict[str, Any]:
    errors: list[str] = []
    checked: list[str] = []
    for item in input_assets:
        try:
            path = resolve_path(storage.root, item)
            data = storage.read_json(path)
            checked.append(_display_path(storage.root, path))
            if isinstance(data, dict):
                for error in validate_common_fields(data):
                    errors.append(f"{_display_path(storage.root, path)}: {error}")
            else:
                errors.append(f"{item}: asset JSON must be an object")
        except Exception as exc:
            errors.append(f"{item}: {type(exc).__name__}: {exc}")
    if errors:
        return {"status": "failed", "message": "; ".join(errors[:3]), "result": {"errors": errors, "checked": checked}}
    return {"status": "passed", "message": "", "result": {"checked": checked}}


def _report_gate(
    storage: LocalStorage,
    input_assets: list[str],
    *,
    report_types: set[str],
    block_recommendations: set[str],
    service_operation: str,
    spec: dict[str, Any],
    workspace_path: str,
) -> dict[str, Any]:
    reports = [_read_report_asset(storage, item) for item in input_assets]
    reports = [item for item in reports if item and str(item.get("type", "")) in report_types]
    if not reports and bool(spec.get("run_service", spec.get("auto_run", False))):
        result = _execute_registered_service_processor(
            storage,
            processor={**spec, "operation": str(spec.get("operation") or service_operation)},
            input_assets=input_assets,
            workspace_path=workspace_path or None,
        )
        reports = [_read_report_asset(storage, item) for item in result.get("output_assets", []) if str(item).strip()]
        reports = [item for item in reports if item and str(item.get("type", "")) in report_types]
        if not reports:
            return {"status": "failed" if result.get("status") == "failed" else "passed", "message": str(result.get("error") or result.get("message") or ""), "result": result}
    if not reports:
        return {"status": "passed", "message": "no report asset required or available for gate", "result": {"checked": []}}
    failures: list[str] = []
    checked: list[dict[str, Any]] = []
    for report in reports:
        content = report.get("content", {}) if isinstance(report.get("content", {}), dict) else {}
        recommendation = str(content.get("recommendation") or content.get("decision") or content.get("status") or "").lower()
        risk_level = str(content.get("risk_level") or content.get("overall_risk") or "").lower()
        high_count = _high_severity_count(content)
        checked.append({"path": report.get("path", ""), "type": report.get("type", ""), "recommendation": recommendation, "risk_level": risk_level, "high_count": high_count})
        if recommendation in block_recommendations or risk_level in {"high", "critical"} or high_count > 0:
            failures.append(f"{report.get('path', '')}: {recommendation or risk_level or 'high severity finding'}")
    if failures:
        return {"status": "failed", "message": "; ".join(failures[:3]), "result": {"checked": checked, "failures": failures}}
    return {"status": "passed", "message": "", "result": {"checked": checked}}


def _read_report_asset(storage: LocalStorage, item: str | Path) -> dict[str, Any]:
    try:
        path = resolve_path(storage.root, item)
        data = storage.read_json(path)
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {**data, "path": _display_path(storage.root, path)}


def _high_severity_count(content: dict[str, Any]) -> int:
    count = 0
    for key in ["issues", "findings", "violations", "gate_results"]:
        value = content.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and str(item.get("severity") or item.get("risk") or "").lower() in {"high", "critical"}:
                    count += 1
        elif isinstance(value, dict):
            for item in value.values():
                if isinstance(item, dict) and str(item.get("severity") or item.get("status") or "").lower() in {"high", "critical", "failed"}:
                    count += 1
    return count


def _record_gate_decision(
    storage: LocalStorage,
    *,
    node: dict[str, Any],
    input_assets: list[str],
    gate_kind: str,
    decision: dict[str, Any],
    trace: dict[str, Any],
) -> dict[str, Any]:
    try:
        gate = record_gate_result(
            storage,
            gate_kind=gate_kind,
            status="failed" if decision.get("status") != "passed" else "passed",
            target_paths=input_assets,
            result={"node_id": node.get("node_id", ""), "decision": decision},
            trace=trace,
            project_id=_project_id_for_paths(storage, input_assets),
            message=str(decision.get("message", "")),
            blocking=True,
        )
        quality_gate = decision.get("quality_gate", {}) if isinstance(decision.get("quality_gate", {}), dict) else {}
        quality_gate["gate_result_path"] = gate.get("path", "")
        decision["quality_gate"] = quality_gate
    except Exception:
        pass
    return decision


def _gate_trace(run_id: str, node_id: str, gate_kind: str) -> dict[str, str]:
    trace_id = run_id or make_id("workflow_trace", utc_now())
    return {
        "trace_id": trace_id,
        "span_id": make_id("span", f"{trace_id}-{node_id}-{gate_kind}-{utc_now()}"),
        "parent_span_id": trace_id,
    }


def _project_id_for_paths(storage: LocalStorage, paths: list[str | Path]) -> str:
    refs = [_asset_ref(storage, item) for item in paths]
    project = _project_scope_from_refs(storage, refs)
    return str(project.get("project_id", ""))


def _tool_name_for_output(output_types: list[str]) -> str:
    if output_types:
        return f"write_{output_types[0]}"
    return "read_asset"


def _workflow_recovery_instruction(status: str, blocked: dict[str, Any], errors: list[str]) -> str:
    if status == "completed":
        return ""
    if blocked.get("status") == "waiting_human":
        return f"Complete the human gate for node {blocked.get('node_id')} and resume the workflow."
    if blocked.get("status") in {"prepared", "planned", "paused"}:
        return f"Continue workflow execution from node {blocked.get('node_id')} after the prepared work is accepted."
    if errors:
        return "Fix the failed node precondition or gate, then rerun the workflow with the same WorkflowDefinition."
    return "Inspect node_runs and agent_runs for the blocked node, then resume or rerun from the last successful checkpoint."


def _path_exists(storage: LocalStorage, value: str | Path) -> bool:
    try:
        return resolve_path(storage.root, value).exists()
    except Exception:
        return False


def _outputs_by_node_from_run_log(run_log: list[dict[str, Any]]) -> dict[str, list[str]]:
    outputs: dict[str, list[str]] = {}
    for entry in run_log:
        if not isinstance(entry, dict):
            continue
        node_id = str(entry.get("node_id", ""))
        status = str(entry.get("status", ""))
        if not node_id or status not in WORKFLOW_SUCCESS_NODE_STATUSES:
            continue
        paths = _asset_paths_from_rows(entry.get("output_assets", []))
        if paths:
            outputs[node_id] = paths
    return outputs


def _input_assets_for_node(run_log: list[dict[str, Any]], node_id: str) -> list[str]:
    for entry in reversed(run_log):
        if not isinstance(entry, dict) or str(entry.get("node_id", "")) != node_id:
            continue
        return _asset_paths_from_rows(entry.get("input_assets", []))
    return []


def _asset_paths_from_rows(rows: Any) -> list[str]:
    result: list[str] = []
    if not isinstance(rows, list):
        return result
    for item in rows:
        if isinstance(item, dict):
            value = str(item.get("path") or item.get("id") or "")
        else:
            value = str(item or "")
        if value.strip():
            result.append(value)
    return _dedupe(result)


def _agent_run_path_for_node(run_log: list[dict[str, Any]], node_id: str) -> str:
    for entry in reversed(run_log):
        if isinstance(entry, dict) and str(entry.get("node_id", "")) == node_id and str(entry.get("agent_run_path", "")).strip():
            return str(entry.get("agent_run_path", ""))
    return ""


def _last_non_success_node(run_log: list[dict[str, Any]]) -> str:
    for entry in reversed(run_log):
        if not isinstance(entry, dict):
            continue
        status = str(entry.get("status", ""))
        if status and status not in WORKFLOW_SUCCESS_NODE_STATUSES:
            return str(entry.get("node_id", ""))
    return ""


def _execution_agent_run_path(execution: dict[str, Any], fallback: str | Path) -> str:
    run = execution.get("run", {}) if isinstance(execution.get("run", {}), dict) else {}
    if run.get("path"):
        return str(run.get("path", ""))
    return str(fallback)


def _result_path(result: Any) -> str:
    if isinstance(result, dict):
        return str(result.get("path", ""))
    return ""


def _execution_error_message(execution: dict[str, Any]) -> str:
    failure = execution.get("failure", {}) if isinstance(execution.get("failure", {}), dict) else {}
    failure_asset = failure.get("asset", {}) if isinstance(failure.get("asset", {}), dict) else {}
    failure_content = failure_asset.get("content", {}) if isinstance(failure_asset.get("content", {}), dict) else {}
    if failure_content.get("error_message"):
        return str(failure_content.get("error_message"))
    return "agent scheduler failed to resume prepared run"


def _scheduler_candidates(storage: LocalStorage, *, project_id: str | None, limit: int) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for path in reversed(storage.list_json("runs")):
        if len(candidates) >= limit:
            break
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "workflow_run":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if str(content.get("status", "")) != "running":
            continue
        if project_id and str(metadata.get("project_id", "")) != project_id:
            continue
        blocked = content.get("blocked", {}) if isinstance(content.get("blocked", {}), dict) else {}
        node_id = str(blocked.get("node_id") or _last_non_success_node(content.get("run_log", []) if isinstance(content.get("run_log", []), list) else []))
        if not node_id or str(blocked.get("status", "")) not in {"prepared", "planned", "paused"}:
            continue
        run_log = content.get("run_log", []) if isinstance(content.get("run_log", []), list) else []
        agent_run_path = _agent_run_path_for_node(run_log, node_id)
        if not agent_run_path:
            continue
        try:
            agent_run = storage.read_json(resolve_path(storage.root, agent_run_path))
        except Exception:
            continue
        if not isinstance(agent_run, dict) or agent_run.get("type") != "agent_run":
            continue
        agent_content = agent_run.get("content", {}) if isinstance(agent_run.get("content", {}), dict) else {}
        if str(agent_content.get("status", "")) != "prepared":
            continue
        workflow_node = _workflow_node_for_run(storage, data, node_id)
        candidates.append(
            {
                "workflow_run_path": _display_path(storage.root, path),
                "workflow_run_id": str(content.get("run_id") or data.get("id", "")),
                "agent_run_path": agent_run_path,
                "agent_run_id": str(agent_content.get("run_id", "")),
                "node_id": node_id,
                "project_id": str(metadata.get("project_id", "")),
                "workspace_path": str(metadata.get("workspace_path", "")),
                "expected_output_assets": _expected_output_assets(workflow_node or {}, _node_processor(workflow_node or {})) if workflow_node else [],
                "token_used": _processor_number(workflow_node, "token_used"),
                "cost_estimate": _processor_number(workflow_node, "cost_estimate"),
            }
        )
    return candidates


def _workflow_node_for_run(storage: LocalStorage, workflow_run: dict[str, Any], node_id: str) -> dict[str, Any] | None:
    content = workflow_run.get("content", {}) if isinstance(workflow_run.get("content", {}), dict) else {}
    workflow_ref = str(content.get("workflow_definition_path") or content.get("workflow_id") or workflow_run.get("source", ""))
    try:
        _, workflow = _resolve_workflow_definition(storage, workflow_ref)
        nodes = _workflow_nodes(storage, workflow)
    except Exception:
        return None
    for node in nodes:
        if str(node.get("node_id", "")) == node_id:
            return node
    return None


def _processor_number(node: dict[str, Any] | None, key: str) -> float:
    processor = _node_processor(node or {})
    try:
        return float(processor.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0


def _scheduler_output_assets(storage: LocalStorage, candidate: dict[str, Any]) -> list[str]:
    values = [str(item) for item in candidate.get("expected_output_assets", []) if str(item).strip()] if isinstance(candidate.get("expected_output_assets", []), list) else []
    try:
        agent_run = storage.read_json(resolve_path(storage.root, str(candidate.get("agent_run_path", ""))))
    except Exception:
        agent_run = {}
    content = agent_run.get("content", {}) if isinstance(agent_run, dict) and isinstance(agent_run.get("content", {}), dict) else {}
    for row in content.get("output_assets", []) if isinstance(content.get("output_assets", []), list) else []:
        if isinstance(row, dict):
            values.append(str(row.get("path") or row.get("id") or ""))
    return _dedupe([_display_path(storage.root, resolve_path(storage.root, value)) for value in values if value and _path_exists(storage, value)])


def _mark_workflow_run_superseded(
    storage: LocalStorage,
    workflow_run_path: str | Path,
    *,
    superseded_by_run_id: str,
    superseded_by_path: str,
    scheduler_tick_id: str,
) -> None:
    path = resolve_path(storage.root, workflow_run_path)
    data = storage.read_json(path)
    if not isinstance(data, dict) or data.get("type") != "workflow_run":
        return
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    content["status"] = "superseded"
    content["superseded_by_run_id"] = superseded_by_run_id
    content["superseded_by_path"] = superseded_by_path
    content["scheduler_tick_id"] = scheduler_tick_id
    content["finished_at"] = utc_now()
    data["content"] = content
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    metadata["asset_status"] = "superseded"
    metadata["superseded_by_run_id"] = superseded_by_run_id
    metadata["superseded_by_path"] = superseded_by_path
    metadata["scheduler_tick_id"] = scheduler_tick_id
    data["metadata"] = metadata
    data["tags"] = _dedupe([*[str(tag) for tag in data.get("tags", [])], "superseded"])
    data["updated_at"] = utc_now()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    storage.write_json(path, data)


def _scheduler_recommendation(resumed: list[dict[str, Any]], skipped: list[dict[str, Any]], errors: list[dict[str, str]]) -> str:
    if errors:
        return "inspect_scheduler_errors"
    if skipped and not resumed:
        return "waiting_for_agent_outputs"
    if resumed:
        return "review_resumed_workflow_runs"
    return "no_ready_workflows"


def _execute_registered_service_processor(
    storage: LocalStorage,
    *,
    processor: dict[str, Any],
    input_assets: list[str],
    workspace_path: str | None,
) -> dict[str, Any]:
    operation = str(processor.get("operation") or processor.get("service") or processor.get("name") or "").strip()
    if operation in {"change_impact_report", "create_change_impact_report"}:
        target_path = str(processor.get("target_path") or (input_assets[0] if input_assets else ""))
        if not target_path:
            raise ValueError("service processor change_impact_report requires target_path or input asset")
        result = create_change_impact_report(
            storage,
            target_path,
            max_depth=int(processor.get("max_depth", 4) or 4),
            project_id=str(processor.get("project_id") or "") or None,
        )
        return {"status": "succeeded", "operation": operation, "output_assets": [result["path"]], "payload": {"path": result["path"]}}
    if operation in {"invalidate_downstream", "mark_downstream_assets_stale"}:
        target_path = str(processor.get("target_path") or (input_assets[0] if input_assets else ""))
        if not target_path:
            raise ValueError("service processor invalidate_downstream requires target_path or input asset")
        result = mark_downstream_assets_stale(
            storage,
            target_path,
            max_depth=int(processor.get("max_depth", 4) or 4),
            project_id=str(processor.get("project_id") or "") or None,
            reason=str(processor.get("reason") or "workflow service processor invalidation"),
            apply=bool(processor.get("apply", True)),
        )
        report = result.get("impact_report", {}) if isinstance(result.get("impact_report", {}), dict) else {}
        return {"status": "failed" if result.get("status") == "failed" else "succeeded", "operation": operation, "output_assets": [str(report.get("path", ""))] if report.get("path") else [], "payload": result}
    if operation == "project_metric_snapshot":
        from novel_forge.modules.metrics import create_project_metric_snapshot

        result = create_project_metric_snapshot(
            storage,
            project_id=str(processor.get("project_id") or "") or None,
            workspace_path=str(processor.get("workspace_path") or workspace_path or "") or None,
        )
        return {"status": "succeeded", "operation": operation, "output_assets": [result["path"]], "payload": {"path": result["path"]}}
    if operation == "module_completion_snapshot":
        from novel_forge.modules.module_completion import module_completion_report

        result = module_completion_report(
            storage,
            project_id=str(processor.get("project_id") or "") or None,
            persist=True,
        )
        return {"status": "succeeded", "operation": operation, "output_assets": [str(result.get("path", ""))] if result.get("path") else [], "payload": {"path": result.get("path", "")}}
    if operation in {"continuity_graph_snapshot", "create_continuity_graph_snapshot"}:
        from novel_forge.modules.continuity_graph import create_continuity_graph_snapshot

        result = create_continuity_graph_snapshot(
            storage,
            project_id=str(processor.get("project_id") or "") or None,
            workspace_path=str(processor.get("workspace_path") or workspace_path or "") or None,
        )
        return _service_success(storage, operation, result)
    if operation in {"canon_graph_snapshot", "create_canon_graph_snapshot"}:
        from novel_forge.modules.continuity_graph import create_canon_graph_snapshot

        result = create_canon_graph_snapshot(
            storage,
            project_id=str(processor.get("project_id") or "") or None,
            workspace_path=str(processor.get("workspace_path") or workspace_path or "") or None,
        )
        return _service_success(storage, operation, result)
    if operation in {"chapter_continuity_report", "create_chapter_continuity_report"}:
        from novel_forge.modules.continuity_graph import create_chapter_continuity_report

        result = create_chapter_continuity_report(
            storage,
            _processor_path(processor, input_assets, "draft_path", "target_path"),
            workspace_path=str(processor.get("workspace_path") or workspace_path or "") or None,
        )
        return _service_success(storage, operation, result)
    if operation in {"canon_patch_from_draft", "create_canon_patch_from_draft"}:
        from novel_forge.modules.continuity_graph import create_canon_patch_from_draft

        result = create_canon_patch_from_draft(
            storage,
            _processor_path(processor, input_assets, "draft_path", "target_path"),
            workspace_path=str(processor.get("workspace_path") or workspace_path or "") or None,
        )
        return _service_success(storage, operation, result)
    if operation in {"apply_canon_patch", "canon_patch_apply"}:
        from novel_forge.modules.continuity_graph import apply_canon_patch

        result = apply_canon_patch(
            storage,
            _processor_path(processor, input_assets, "patch_path", "target_path"),
            confirmed=bool(processor.get("confirmed", False)),
            note=str(processor.get("note") or "workflow service processor"),
        )
        return _service_success(storage, operation, result)
    if operation in {"chapter_stability_preflight", "create_chapter_stability_preflight_report"}:
        from novel_forge.modules.continuity_graph import create_chapter_stability_preflight_report

        result = create_chapter_stability_preflight_report(
            storage,
            _processor_path(processor, input_assets, "chapter_plan_path", "target_path"),
            workspace_path=str(processor.get("workspace_path") or workspace_path or "") or None,
        )
        return _service_success(storage, operation, result)
    if operation in {"quality_score_report", "create_quality_score_report"}:
        from novel_forge.modules.standards import create_quality_score_report

        result = create_quality_score_report(
            storage,
            _processor_path(processor, input_assets, "target_path", "draft_path"),
            workspace_path=str(processor.get("workspace_path") or workspace_path or "") or None,
        )
        return _service_success(storage, operation, result)
    if operation in {"style_decomposition_report", "create_style_decomposition_report"}:
        from novel_forge.modules.style import create_style_decomposition_report

        result = create_style_decomposition_report(
            storage,
            _processor_path(processor, input_assets, "source_path", "target_path"),
            workspace_path=str(processor.get("workspace_path") or workspace_path or "") or None,
        )
        return _service_success(storage, operation, result)
    if operation in {"style_review_report", "create_style_review_report"}:
        from novel_forge.modules.style import create_style_review_report

        result = create_style_review_report(
            storage,
            _processor_path(processor, input_assets, "draft_path", "target_path"),
            style_profile_path=str(processor.get("style_profile_path") or "") or None,
            workspace_path=str(processor.get("workspace_path") or workspace_path or "") or None,
        )
        return _service_success(storage, operation, result)
    if operation in {"originality_report", "create_originality_report"}:
        from novel_forge.modules.audit import create_originality_report

        result = create_originality_report(
            storage,
            _processor_path(processor, input_assets, "draft_path", "target_path"),
            workspace_path=str(processor.get("workspace_path") or workspace_path or "") or None,
        )
        return _service_success(storage, operation, result)
    if operation in {"chapter_audit_report", "create_chapter_audit_report"}:
        from novel_forge.modules.audit import create_chapter_audit_report

        result = create_chapter_audit_report(
            storage,
            _processor_path(processor, input_assets, "draft_path", "target_path"),
            workspace_path=str(processor.get("workspace_path") or workspace_path or "") or None,
            quality_path=str(processor.get("quality_path") or "") or None,
            style_path=str(processor.get("style_path") or "") or None,
            originality_path=str(processor.get("originality_path") or "") or None,
        )
        return _service_success(storage, operation, result)
    if operation in {"publish_gate_report", "create_publish_gate_report"}:
        from novel_forge.modules.audit import create_publish_gate_report

        result = create_publish_gate_report(
            storage,
            _processor_path(processor, input_assets, "draft_path", "target_path"),
            workspace_path=str(processor.get("workspace_path") or workspace_path or "") or None,
            chapter_audit_path=str(processor.get("chapter_audit_path") or "") or None,
            human_override=bool(processor.get("human_override", False)),
        )
        return _service_success(storage, operation, result)
    if operation in {"release_package", "create_release_package"}:
        from novel_forge.modules.audit import create_release_package

        result = create_release_package(
            storage,
            _processor_path(processor, input_assets, "draft_path", "target_path"),
            workspace_path=str(processor.get("workspace_path") or workspace_path or "") or None,
            publish_gate_path=str(processor.get("publish_gate_path") or "") or None,
            channel=str(processor.get("channel") or "local"),
            human_override=bool(processor.get("human_override", False)),
        )
        return _service_success(storage, operation, result)
    if operation in {"outline_version", "create_outline_version"}:
        from novel_forge.modules.production_chain import create_outline_version

        result = create_outline_version(storage, _processor_path(processor, input_assets, "outline_path", "target_path"), change_summary=str(processor.get("change_summary") or "workflow service processor"), status=str(processor.get("status") or "active"))
        return _service_success(storage, operation, result)
    if operation in {"chapter_plan_version", "create_chapter_plan_version"}:
        from novel_forge.modules.production_chain import create_chapter_plan_version

        result = create_chapter_plan_version(storage, _processor_path(processor, input_assets, "chapter_plan_path", "target_path"), change_summary=str(processor.get("change_summary") or "workflow service processor"), status=str(processor.get("status") or "active"))
        return _service_success(storage, operation, result)
    if operation in {"draft_version", "create_draft_version"}:
        from novel_forge.modules.production_chain import create_draft_version

        result = create_draft_version(storage, _processor_path(processor, input_assets, "draft_path", "target_path"), change_summary=str(processor.get("change_summary") or "workflow service processor"), status=str(processor.get("status") or "active"))
        return _service_success(storage, operation, result)
    if operation in {"review", "review_report"}:
        from novel_forge.modules.review.service import review

        result = review(storage, _processor_path(processor, input_assets, "draft_path", "target_path"))
        return _service_success(storage, operation, result)
    if operation in {"editor_patch", "create_editor_patch"}:
        from novel_forge.modules.editor import create_editor_patch

        operations = processor.get("operations", [])
        result = create_editor_patch(
            storage,
            _processor_path(processor, input_assets, "draft_path", "target_path"),
            instructions=str(processor.get("instructions") or ""),
            operations=operations if isinstance(operations, list) else [],
            workspace_path=str(processor.get("workspace_path") or workspace_path or "") or None,
        )
        return _service_success(storage, operation, result)
    if operation in {"apply_editor_patch", "editor_patch_apply"}:
        from novel_forge.modules.editor import apply_editor_patch

        result = apply_editor_patch(
            storage,
            _processor_path(processor, input_assets, "patch_path", "target_path"),
            apply=bool(processor.get("apply", True)),
            change_summary=str(processor.get("change_summary") or "workflow service processor"),
            operation_ids=[str(item) for item in processor.get("operation_ids", [])] if isinstance(processor.get("operation_ids", []), list) else [],
            operation_indexes=[int(item) for item in processor.get("operation_indexes", [])] if isinstance(processor.get("operation_indexes", []), list) else [],
        )
        return _service_success(storage, operation, result)
    if operation in {"draft_diff_report", "create_draft_diff_report"}:
        from novel_forge.modules.editor import create_draft_diff_report

        result = create_draft_diff_report(
            storage,
            _processor_path(processor, input_assets, "base_path", "draft_path"),
            _processor_path(processor, input_assets[1:], "target_path"),
        )
        return _service_success(storage, operation, result)
    if operation in {"publishing_plan", "create_publishing_plan"}:
        from novel_forge.modules.publishing import create_publishing_plan

        release_paths = processor.get("release_package_paths", input_assets)
        result = create_publishing_plan(
            storage,
            release_package_paths=[str(item) for item in release_paths] if isinstance(release_paths, list) else [],
            project_id=str(processor.get("project_id") or "") or None,
            workspace_path=str(processor.get("workspace_path") or workspace_path or "") or None,
            channel=str(processor.get("channel") or "local"),
            cadence=str(processor.get("cadence") or "daily"),
            start_date=str(processor.get("start_date") or ""),
        )
        return _service_success(storage, operation, result)
    if operation in {"publishing_log", "create_publishing_log"}:
        from novel_forge.modules.publishing import create_publishing_log

        result = create_publishing_log(
            storage,
            _processor_path(processor, input_assets, "release_package_path", "target_path"),
            publishing_plan_path=str(processor.get("publishing_plan_path") or "") or None,
            channel=str(processor.get("channel") or "local"),
            status=str(processor.get("status") or "published"),
            external_url=str(processor.get("external_url") or ""),
            rollback_note=str(processor.get("rollback_note") or ""),
        )
        return _service_success(storage, operation, result)
    raise ValueError(f"unknown service processor operation: {operation or '<empty>'}")


def _service_success(storage: LocalStorage, operation: str, result: Any) -> dict[str, Any]:
    return {"status": "succeeded", "operation": operation, "output_assets": _service_output_assets(storage, result), "payload": _json_safe_service_payload(result)}


def _processor_path(processor: dict[str, Any], input_assets: list[str], *keys: str) -> str:
    for key in keys:
        value = str(processor.get(key) or "").strip()
        if value:
            return value
    if input_assets:
        return str(input_assets[0])
    raise ValueError(f"service processor requires one of: {', '.join(keys) or 'input_assets'}")


def _service_output_assets(storage: LocalStorage, result: Any) -> list[str]:
    values: list[str] = []
    if isinstance(result, (str, Path)):
        values.append(str(result))
    elif isinstance(result, dict):
        for key, value in result.items():
            if key.endswith("path") and isinstance(value, (str, Path)):
                values.append(str(value))
            elif key.endswith("paths") and isinstance(value, list):
                values.extend(str(item) for item in value if isinstance(item, (str, Path)))
            elif key in {"updated_targets", "output_assets"} and isinstance(value, list):
                values.extend(str(item) for item in value if isinstance(item, (str, Path)))
            elif isinstance(value, dict) and key not in {"asset", "content", "metadata", "references", "payload"}:
                values.extend(_service_output_assets(storage, value))
    return _dedupe([_display_path(storage.root, resolve_path(storage.root, value)) if value and _path_exists(storage, value) else str(value) for value in values if str(value).strip()])


def _json_safe_service_payload(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe_service_payload(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_json_safe_service_payload(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe_service_payload(item) for item in value]
    return value


def _trace_payload(trace: dict[str, Any] | None, *, trace_id: str, node_id: str) -> dict[str, str]:
    payload = trace if isinstance(trace, dict) else {}
    resolved_trace_id = str(payload.get("trace_id") or trace_id)
    parent_span_id = str(payload.get("parent_span_id") or resolved_trace_id)
    span_id = str(payload.get("span_id") or make_id("span", f"{resolved_trace_id}-{node_id}-{utc_now()}"))
    return {"trace_id": resolved_trace_id, "span_id": span_id, "parent_span_id": parent_span_id}


def _trace_span_status(status: str) -> str:
    value = str(status or "").lower()
    if value in {"succeeded", "recovered", "completed", "within_sla"}:
        return "succeeded"
    if value in {"failed", "dead_letter", "needs_revision", "breached", "exceeded"}:
        return "failed"
    if value in {"cancelled", "skipped", "running"}:
        return value
    if value in {"prepared", "planned", "paused", "waiting_human"}:
        return "skipped"
    return "succeeded"


def _asset_ref(storage: LocalStorage, value: str | Path) -> dict[str, str]:
    path = resolve_path(storage.root, value)
    if path.exists() and path.is_file():
        try:
            asset = storage.read_asset(path)
            return {"id": asset.id, "type": asset.type, "title": asset.title, "path": _display_path(storage.root, path)}
        except Exception:
            pass
    return {"id": str(value), "type": "", "title": "", "path": str(value)}


def _project_scope_from_refs(storage: LocalStorage, refs: list[dict[str, str]]) -> dict[str, str]:
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
            return {"project_id": str(project.get("project_id", "")), "workspace_path": str(project.get("workspace_path", ""))}
    return {"project_id": "", "workspace_path": ""}


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
