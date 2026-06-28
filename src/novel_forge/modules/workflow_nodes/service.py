from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.agent_runs import ensure_agent_contract, execute_agent_run_once, start_agent_run
from novel_forge.modules.change_impact import create_change_impact_report, mark_downstream_assets_stale
from novel_forge.modules.common import resolve_path
from novel_forge.modules.production_context import filter_project_safe_references, project_scope_from_asset
from novel_forge.schemas import NodeRun, WorkflowDefinition, WorkflowNode, WorkflowRun, validate_common_fields
from novel_forge.storage.local import LocalStorage

WORKFLOW_TERMINAL_NODE_STATUSES = {"succeeded", "failed", "dead_letter", "cancelled"}
WORKFLOW_SUCCESS_NODE_STATUSES = {"succeeded", "recovered"}
WORKFLOW_BLOCKING_NODE_STATUSES = {"failed", "dead_letter", "cancelled", "waiting_human", "needs_revision"}


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
) -> dict[str, Any]:
    input_rows = [_asset_ref(storage, item) for item in input_assets or []]
    output_rows = [_asset_ref(storage, item) for item in output_assets or []]
    project = _project_scope_from_refs(storage, [*input_rows, *output_rows])
    project_id = str(project.get("project_id", ""))
    workspace_path = str(project.get("workspace_path", ""))
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
    return _write(storage, asset)


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
        gate = _evaluate_node_gate(storage, node, node_inputs)
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


def _write(storage: LocalStorage, asset: WorkflowDefinition | WorkflowNode | NodeRun | WorkflowRun) -> dict[str, Any]:
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "asset": asset.to_dict(), "validation": {"ok": True, "errors": []}}


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


def _evaluate_node_gate(storage: LocalStorage, node: dict[str, Any], input_assets: list[str]) -> dict[str, Any]:
    quality_gate = dict(node.get("quality_gate", {}) if isinstance(node.get("quality_gate", {}), dict) else {})
    human_gate = dict(node.get("human_gate", {}) if isinstance(node.get("human_gate", {}), dict) else {})
    human_required = bool(human_gate.get("required", False))
    human_status = str(human_gate.get("status", "") or "").lower()
    if human_required and human_status not in {"approved", "accepted", "passed"}:
        human_gate["status"] = human_status or "waiting"
        return {
            "status": "blocked",
            "node_status": "waiting_human",
            "message": "human gate is required before this node can run",
            "quality_gate": quality_gate or {"required": False, "status": "not_evaluated"},
            "human_gate": human_gate,
        }
    gate_status = str(quality_gate.get("status", "") or "").lower()
    if gate_status in {"failed", "blocked", "rejected"}:
        return {
            "status": "blocked",
            "node_status": "failed",
            "message": str(quality_gate.get("message") or "quality gate failed"),
            "quality_gate": {**quality_gate, "status": gate_status},
            "human_gate": human_gate or {"required": False, "status": "not_required"},
        }
    min_input_count = int(quality_gate.get("min_input_count", 0) or 0)
    if min_input_count and len(input_assets) < min_input_count:
        return {
            "status": "blocked",
            "node_status": "failed",
            "message": f"quality gate requires at least {min_input_count} input assets",
            "quality_gate": {**quality_gate, "status": "failed"},
            "human_gate": human_gate or {"required": False, "status": "not_required"},
        }
    missing_types = _missing_required_input_types(storage, node, input_assets)
    if missing_types:
        return {
            "status": "blocked",
            "node_status": "failed",
            "message": f"missing required input asset types: {', '.join(missing_types)}",
            "quality_gate": {**quality_gate, "status": "failed"},
            "human_gate": human_gate or {"required": False, "status": "not_required"},
        }
    stale_inputs = _stale_inputs(storage, input_assets) if quality_gate.get("block_on_stale_inputs") else []
    if stale_inputs:
        return {
            "status": "blocked",
            "node_status": "failed",
            "message": f"stale input assets blocked execution: {', '.join(stale_inputs[:3])}",
            "quality_gate": {**quality_gate, "status": "failed", "stale_inputs": stale_inputs},
            "human_gate": human_gate or {"required": False, "status": "not_required"},
        }
    return {
        "status": "passed",
        "node_status": "running",
        "message": "",
        "quality_gate": {**quality_gate, "status": "passed" if quality_gate.get("required") else quality_gate.get("status", "not_applicable")},
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
            "started_at": started_at,
            "finished_at": utc_now() if status in {"completed", "failed"} else "",
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
    return _write(storage, asset)


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
