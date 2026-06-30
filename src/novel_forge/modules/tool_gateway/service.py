from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable
import urllib.error
import urllib.request

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.production_context import filter_project_safe_references
from novel_forge.modules.runtime_ledger import record_trace_span
from novel_forge.schemas import MCPServerRegistry, ToolDefinition, ToolInvocation, ToolPermissionPolicy, validate_common_fields
from novel_forge.storage.local import LocalStorage

INTERNAL_TOOL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "novel_kg.query": {"tool_kind": "internal", "description": "Query Novel KG snapshot by kind, keyword, or source."},
    "novel_kg.impact": {"tool_kind": "internal", "description": "Return Novel KG impact radius from a node."},
    "novel_kg.conflicts": {"tool_kind": "internal", "description": "Analyze Novel KG identity and relation conflicts."},
    "context_builder.build_bundle": {"tool_kind": "internal", "description": "Create a context build plan and bundle from a target asset."},
    "workflow.execute": {"tool_kind": "internal", "description": "Execute a workflow definition through the runtime kernel."},
    "workflow.resume": {"tool_kind": "internal", "description": "Resume a workflow run through the runtime kernel."},
    "agent_scheduler.tick": {"tool_kind": "internal", "description": "Run one Agent Scheduler tick."},
    "review.run": {"tool_kind": "internal", "description": "Create a deterministic review report for a draft."},
    "revision.apply_patch": {"tool_kind": "internal", "description": "Apply an editor patch to a draft."},
    "trace.timeline": {"tool_kind": "internal", "description": "Return trace timeline payload."},
    "cost.create_dashboard": {"tool_kind": "internal", "description": "Build runtime cost/quality dashboard."},
    "mcp.discover_tools": {"tool_kind": "mcp_control", "description": "Discover remote MCP tools from a registered HTTP JSON-RPC server."},
}

TOOL_ASSET_TYPES = {"tool_definition", "tool_invocation", "tool_permission_policy", "mcp_server_registry"}


def register_internal_tools(storage: LocalStorage, *, project_id: str = "", workspace_path: str = "") -> dict[str, Any]:
    tools: list[dict[str, Any]] = []
    for name, spec in sorted(INTERNAL_TOOL_DEFINITIONS.items()):
        tools.append(
            create_tool_definition(
                storage,
                name=name,
                tool_kind=str(spec.get("tool_kind", "internal")),
                description=str(spec.get("description", "")),
                input_schema=spec.get("input_schema", {}) if isinstance(spec.get("input_schema", {}), dict) else {},
                output_schema=spec.get("output_schema", {}) if isinstance(spec.get("output_schema", {}), dict) else {},
                project_id=project_id,
                workspace_path=workspace_path,
            )
        )
    return {"status": "registered", "count": len(tools), "tools": tools}


def create_tool_definition(
    storage: LocalStorage,
    *,
    name: str,
    tool_kind: str = "internal",
    description: str = "",
    input_schema: dict[str, Any] | None = None,
    output_schema: dict[str, Any] | None = None,
    status: str = "active",
    project_id: str = "",
    workspace_path: str = "",
) -> dict[str, Any]:
    content = {
        "tool_id": make_id("tool", name),
        "name": name,
        "tool_kind": tool_kind,
        "description": description,
        "input_schema": input_schema or {},
        "output_schema": output_schema or {},
        "status": _status(status),
        "created_at": utc_now(),
    }
    asset = ToolDefinition(
        title=f"Tool {name}",
        tags=["tool-definition", tool_kind, content["status"]],
        content=content,
        metadata={"project_id": project_id, "workspace_path": workspace_path, "tool_name": name, "status": content["status"]},
    )
    return _write(storage, asset)


def create_tool_permission_policy(
    storage: LocalStorage,
    *,
    tool_id: str,
    agent_types: list[str] | None = None,
    allowed_operations: list[str] | None = None,
    status: str = "active",
    project_id: str = "",
    workspace_path: str = "",
) -> dict[str, Any]:
    content = {
        "policy_id": make_id("tool_policy", f"{tool_id}-{'-'.join(agent_types or ['all'])}"),
        "tool_id": tool_id,
        "agent_types": agent_types or ["*"],
        "allowed_operations": allowed_operations or ["*"],
        "status": _status(status),
        "created_at": utc_now(),
    }
    asset = ToolPermissionPolicy(
        title=f"Tool policy {tool_id}",
        tags=["tool-permission-policy", content["status"]],
        content=content,
        metadata={"project_id": project_id, "workspace_path": workspace_path, "tool_id": tool_id, "status": content["status"]},
    )
    return _write(storage, asset)


def register_mcp_server(
    storage: LocalStorage,
    *,
    name: str,
    transport: str,
    tools: list[dict[str, Any]] | None = None,
    endpoint: str = "",
    status: str = "registered",
    project_id: str = "",
    workspace_path: str = "",
) -> dict[str, Any]:
    content = {
        "server_id": make_id("mcp_server", name),
        "name": name,
        "transport": transport,
        "endpoint": endpoint,
        "tools": tools or [],
        "status": status,
        "created_at": utc_now(),
    }
    asset = MCPServerRegistry(
        title=f"MCP server {name}",
        tags=["mcp-server", transport, status],
        content=content,
        metadata={"project_id": project_id, "workspace_path": workspace_path, "status": status},
    )
    written = _write(storage, asset)
    tool_definitions = [
        _create_mcp_tool_definition(
            storage,
            server=written["asset"],
            tool=item,
            project_id=project_id,
            workspace_path=workspace_path,
        )
        for item in tools or []
        if isinstance(item, dict) and str(item.get("name", "")).strip()
    ]
    return {**written, "tool_definitions": tool_definitions}


def invoke_tool(
    storage: LocalStorage,
    *,
    tool_name: str,
    input_payload: dict[str, Any] | None = None,
    agent_type: str = "",
    operation: str = "",
    project_id: str = "",
    workspace_path: str = "",
    trace: dict[str, Any] | None = None,
    enforce_permissions: bool = True,
) -> dict[str, Any]:
    payload = input_payload or {}
    tool = _find_tool(storage, tool_name) or _builtin_tool_definition(tool_name)
    if not tool:
        return _record_invocation(
            storage,
            tool_name=tool_name,
            input_payload=payload,
            output={"error": f"unknown tool: {tool_name}"},
            status="failed",
            agent_type=agent_type,
            operation=operation,
            project_id=project_id,
            workspace_path=workspace_path,
            trace=trace,
        )
    permission = _permission_status(storage, tool_name=tool_name, agent_type=agent_type, operation=operation) if enforce_permissions else {"status": "allowed"}
    if permission["status"] != "allowed":
        return _record_invocation(
            storage,
            tool_name=tool_name,
            input_payload=payload,
            output=permission,
            status="blocked",
            agent_type=agent_type,
            operation=operation,
            project_id=project_id,
            workspace_path=workspace_path,
            trace=trace,
        )
    try:
        output = _dispatch_tool(storage, tool, tool_name, payload, project_id=project_id, workspace_path=workspace_path)
        status = "succeeded"
    except Exception as exc:
        output = {"error": f"{type(exc).__name__}: {exc}"}
        status = "failed"
    return _record_invocation(
        storage,
        tool_name=tool_name,
        input_payload=payload,
        output=output,
        status=status,
        agent_type=agent_type,
        operation=operation,
        project_id=project_id,
        workspace_path=workspace_path,
        trace=trace,
    )


def list_tool_gateway_assets(storage: LocalStorage, *, project_id: str | None = None, limit: int = 300) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in storage.list_json("runs"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") not in TOOL_ASSET_TYPES:
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if project_id and str(metadata.get("project_id", "")) != project_id:
            continue
        rows.append({**data, "path": _display_path(storage.root, path)})
    return sorted(rows, key=lambda row: str(row.get("updated_at", "")), reverse=True)[:limit]


def _create_mcp_tool_definition(
    storage: LocalStorage,
    *,
    server: dict[str, Any],
    tool: dict[str, Any],
    project_id: str,
    workspace_path: str,
) -> dict[str, Any]:
    server_content = server.get("content", {}) if isinstance(server.get("content", {}), dict) else {}
    created = create_tool_definition(
        storage,
        name=str(tool.get("name", "")),
        tool_kind="mcp",
        description=str(tool.get("description", "")),
        input_schema=tool.get("input_schema", tool.get("inputSchema", {})) if isinstance(tool.get("input_schema", tool.get("inputSchema", {})), dict) else {},
        output_schema=tool.get("output_schema", tool.get("outputSchema", {})) if isinstance(tool.get("output_schema", tool.get("outputSchema", {})), dict) else {},
        status="active",
        project_id=project_id,
        workspace_path=workspace_path,
    )
    path = storage.root / created["path"]
    data = storage.read_json(path)
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    content["mcp_server_id"] = str(server_content.get("server_id", ""))
    content["mcp_server_name"] = str(server_content.get("name", ""))
    content["mcp_endpoint"] = str(server_content.get("endpoint", ""))
    content["remote_name"] = str(tool.get("remote_name") or tool.get("name", ""))
    data["content"] = content
    storage.write_json(path, data)
    return {"path": created["path"], "id": created["id"], "asset": data, "validation": created["validation"]}


def _dispatch_tool(storage: LocalStorage, tool: dict[str, Any], tool_name: str, payload: dict[str, Any], *, project_id: str, workspace_path: str) -> dict[str, Any]:
    content = tool.get("content", {}) if isinstance(tool.get("content", {}), dict) else {}
    if str(content.get("tool_kind", "")) == "mcp":
        return _dispatch_mcp_tool(storage, tool, tool_name, payload)
    return _dispatch_internal_tool(storage, tool_name, payload, project_id=project_id, workspace_path=workspace_path)


def _dispatch_internal_tool(storage: LocalStorage, tool_name: str, payload: dict[str, Any], *, project_id: str, workspace_path: str) -> dict[str, Any]:
    if tool_name == "mcp.discover_tools":
        server = _find_mcp_server(storage, str(payload.get("server_name") or payload.get("server_id") or ""))
        if not server:
            raise ValueError("mcp.discover_tools requires server_name or server_id for a registered MCP server")
        result = _mcp_json_rpc(server, "tools/list", {})
        tools = _mcp_tools_from_result(result)
        created = [
            _create_mcp_tool_definition(storage, server=server, tool=item, project_id=project_id, workspace_path=workspace_path)
            for item in tools
            if isinstance(item, dict) and str(item.get("name", "")).strip()
        ]
        return {"status": "discovered", "server": _mcp_server_summary(server), "tools": tools, "tool_definitions": created, "raw": result}
    if tool_name == "trace.timeline":
        from novel_forge.modules.runtime_ledger import trace_timeline_payload

        return trace_timeline_payload(storage, trace_id=payload.get("trace_id"), project_id=payload.get("project_id") or project_id, limit=int(payload.get("limit", 300) or 300))
    if tool_name == "cost.create_dashboard":
        from novel_forge.modules.runtime_ledger import create_cost_quality_dashboard

        return create_cost_quality_dashboard(storage, project_id=payload.get("project_id") or project_id, workspace_path=payload.get("workspace_path") or workspace_path, chapter=payload.get("chapter"), persist_dashboard=bool(payload.get("persist", False)))
    if tool_name == "novel_kg.query":
        from novel_forge.modules.novel_kg import query_novel_kg

        return query_novel_kg(storage, project_id=payload.get("project_id") or project_id, kind=payload.get("kind"), q=payload.get("keyword") or payload.get("q"), limit=int(payload.get("limit", 50) or 50))
    if tool_name == "novel_kg.impact":
        from novel_forge.modules.novel_kg import query_novel_kg_impact

        return query_novel_kg_impact(storage, project_id=payload.get("project_id") or project_id, node=str(payload.get("node") or payload.get("node_id", "")), max_depth=int(payload.get("depth", payload.get("max_depth", 2)) or 2))
    if tool_name == "novel_kg.conflicts":
        from novel_forge.modules.novel_kg import analyze_novel_kg_conflicts

        return analyze_novel_kg_conflicts(storage, project_id=payload.get("project_id") or project_id)
    if tool_name == "agent_scheduler.tick":
        from novel_forge.modules.agent_scheduler import run_agent_scheduler_tick

        return run_agent_scheduler_tick(storage, owner=str(payload.get("owner", "tool-gateway")), max_items=int(payload.get("max_items", 5) or 5))
    if tool_name == "workflow.execute":
        from novel_forge.modules.workflow_nodes import execute_workflow

        return execute_workflow(storage, workflow_definition_path=str(payload.get("workflow_definition_path", "")), input_assets=payload.get("input_assets", []))
    if tool_name == "workflow.resume":
        from novel_forge.modules.workflow_nodes import resume_workflow

        return resume_workflow(storage, workflow_run_path=str(payload.get("workflow_run_path", "")), output_assets=payload.get("output_assets", []))
    if tool_name == "context_builder.build_bundle":
        from novel_forge.modules.context_builder import create_context_build_plan, create_context_bundle

        plan = create_context_build_plan(
            storage,
            target_path=str(payload.get("target_path", "")),
            query=str(payload.get("query", "")),
            top_k=int(payload.get("top_k", 8) or 8),
            token_budget=int(payload.get("token_budget", 4000) or 4000),
            backend=str(payload.get("backend", payload.get("retrieval_backend", "auto"))),
            retrieval_backend=str(payload.get("retrieval_backend", "")) or None,
            memory_levels=[str(item) for item in payload.get("memory_levels", [])] if isinstance(payload.get("memory_levels", []), list) else None,
            kg_context_enabled=bool(payload.get("kg_context", True)),
            quality_memory_enabled=bool(payload.get("quality_memory", True)),
            workspace_path=payload.get("workspace_path") or workspace_path,
        )
        bundle = create_context_bundle(storage, plan["path"], max_items=payload.get("max_items"))
        return {"plan": plan, "bundle": bundle}
    if tool_name == "review.run":
        from novel_forge.modules.review import review

        return {"path": _display_path(storage.root, review(storage, str(payload.get("draft_path", ""))))}
    if tool_name == "revision.apply_patch":
        from novel_forge.modules.editor import apply_editor_patch

        return apply_editor_patch(storage, patch_path=str(payload.get("patch_path", "")), apply=bool(payload.get("apply", payload.get("confirmed", False))))
    return {"status": "unsupported", "message": f"tool {tool_name} is registered but has no local dispatcher"}


def _dispatch_mcp_tool(storage: LocalStorage, tool: dict[str, Any], tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    content = tool.get("content", {}) if isinstance(tool.get("content", {}), dict) else {}
    server = _find_mcp_server(storage, str(content.get("mcp_server_id") or content.get("mcp_server_name") or content.get("server_name") or ""))
    if not server:
        server = _find_mcp_server_for_tool(storage, tool_name)
    if not server:
        raise ValueError(f"no registered MCP server found for tool: {tool_name}")
    result = _mcp_json_rpc(server, "tools/call", {"name": str(content.get("remote_name") or tool_name), "arguments": payload})
    if "error" in result:
        raise RuntimeError(str(result["error"]))
    return {"status": "succeeded", "server": _mcp_server_summary(server), "tool_name": tool_name, "result": result.get("result", result), "raw": result}


def _find_mcp_server(storage: LocalStorage, name_or_id: str) -> dict[str, Any] | None:
    needle = str(name_or_id or "").strip()
    if not needle:
        return None
    for row in list_tool_gateway_assets(storage, limit=1000):
        if row.get("type") != "mcp_server_registry":
            continue
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        if needle in {str(content.get("server_id", "")), str(content.get("name", "")), str(row.get("id", ""))}:
            return row
    return None


def _find_mcp_server_for_tool(storage: LocalStorage, tool_name: str) -> dict[str, Any] | None:
    for row in list_tool_gateway_assets(storage, limit=1000):
        if row.get("type") != "mcp_server_registry":
            continue
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        tools = content.get("tools", []) if isinstance(content.get("tools", []), list) else []
        if any(isinstance(item, dict) and str(item.get("name", "")) == tool_name for item in tools):
            return row
    return None


def _mcp_json_rpc(server: dict[str, Any], method: str, params: dict[str, Any]) -> dict[str, Any]:
    content = server.get("content", {}) if isinstance(server.get("content", {}), dict) else {}
    transport = str(content.get("transport", "")).strip().lower()
    endpoint = str(content.get("endpoint", "")).strip()
    if transport not in {"http", "https", "jsonrpc", "streamable-http"}:
        raise ValueError(f"MCP remote adapter currently supports HTTP JSON-RPC transports only, got: {transport or 'missing'}")
    if not endpoint:
        raise ValueError("MCP HTTP transport requires endpoint")
    body = {
        "jsonrpc": "2.0",
        "id": make_id("mcp_rpc", f"{method}-{utc_now()}"),
        "method": method,
        "params": params,
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    timeout = _mcp_timeout_seconds()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"MCP server returned HTTP {exc.code}: {detail[:500]}") from exc
    except Exception as exc:
        raise RuntimeError(f"MCP JSON-RPC call failed: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("MCP JSON-RPC response must be a JSON object")
    return payload


def _mcp_tools_from_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    payload = result.get("result", result)
    if isinstance(payload, dict):
        tools = payload.get("tools", [])
        if isinstance(tools, list):
            return [item for item in tools if isinstance(item, dict)]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _mcp_server_summary(server: dict[str, Any]) -> dict[str, str]:
    content = server.get("content", {}) if isinstance(server.get("content", {}), dict) else {}
    return {
        "server_id": str(content.get("server_id", "")),
        "name": str(content.get("name", "")),
        "transport": str(content.get("transport", "")),
        "endpoint": str(content.get("endpoint", "")),
    }


def _mcp_timeout_seconds() -> int:
    try:
        return max(1, int(os.environ.get("NOVEL_FORGE_MCP_TIMEOUT_SECONDS", "30")))
    except Exception:
        return 30


def _record_invocation(
    storage: LocalStorage,
    *,
    tool_name: str,
    input_payload: dict[str, Any],
    output: dict[str, Any],
    status: str,
    agent_type: str,
    operation: str,
    project_id: str,
    workspace_path: str,
    trace: dict[str, Any] | None,
) -> dict[str, Any]:
    trace_payload = dict(trace or {})
    content = {
        "invocation_id": make_id("tool_invocation", f"{tool_name}-{utc_now()}"),
        "tool_id": tool_name,
        "tool_name": tool_name,
        "status": _invocation_status(status),
        "input": input_payload,
        "output": output,
        "agent_type": agent_type,
        "operation": operation,
        "created_at": utc_now(),
        "trace": trace_payload,
    }
    asset = ToolInvocation(
        title=f"Tool invocation {tool_name}",
        tags=["tool-invocation", tool_name, content["status"]],
        content=content,
        metadata={"project_id": project_id, "workspace_path": workspace_path, "agent_type": agent_type, "operation": operation},
        references=filter_project_safe_references(storage, project_id, _collect_paths(input_payload, output)),
    )
    written = _write(storage, asset)
    if trace_payload.get("trace_id"):
        record_trace_span(
            storage,
            trace_id=str(trace_payload["trace_id"]),
            span_type="tool",
            name=tool_name,
            status="succeeded" if content["status"] == "succeeded" else "failed",
            parent_span_id=str(trace_payload.get("span_id") or trace_payload.get("parent_span_id") or trace_payload["trace_id"]),
            attributes={"tool_invocation_path": written["path"], "status": content["status"], "operation": operation},
            references=[written["path"]],
            project_id=project_id,
            workspace_path=workspace_path,
        )
    return {**written, "status": content["status"], "output": output}


def _find_tool(storage: LocalStorage, tool_name: str) -> dict[str, Any] | None:
    for row in list_tool_gateway_assets(storage, limit=1000):
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        if row.get("type") == "tool_definition" and str(content.get("name", "")) == tool_name and content.get("status") == "active":
            return row
    return None


def _builtin_tool_definition(tool_name: str) -> dict[str, Any] | None:
    spec = INTERNAL_TOOL_DEFINITIONS.get(tool_name)
    if not spec:
        return None
    return {"type": "tool_definition", "content": {"name": tool_name, "tool_id": tool_name, "status": "active", **spec}}


def _permission_status(storage: LocalStorage, *, tool_name: str, agent_type: str, operation: str) -> dict[str, Any]:
    policies = [row for row in list_tool_gateway_assets(storage, limit=1000) if row.get("type") == "tool_permission_policy"]
    relevant = []
    for row in policies:
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        if content.get("status") != "active":
            continue
        if str(content.get("tool_id", "")) in {tool_name, "*"}:
            relevant.append(content)
    if not relevant:
        return {"status": "allowed", "source": "no_policy_default_allow"}
    for policy in relevant:
        agents = [str(item) for item in policy.get("agent_types", []) if str(item).strip()]
        operations = [str(item) for item in policy.get("allowed_operations", []) if str(item).strip()]
        agent_allowed = "*" in agents or not agent_type or agent_type in agents
        operation_allowed = "*" in operations or not operation or operation in operations
        if agent_allowed and operation_allowed:
            return {"status": "allowed", "source": policy.get("policy_id", "")}
    return {"status": "blocked", "message": f"agent {agent_type or 'unknown'} is not allowed to invoke {tool_name}"}


def _write(storage: LocalStorage, asset: ToolDefinition | ToolInvocation | ToolPermissionPolicy | MCPServerRegistry) -> dict[str, Any]:
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "id": asset.id, "asset": asset.to_dict(), "validation": {"ok": True, "errors": []}}


def _status(value: str) -> str:
    normalized = str(value or "active").strip().lower().replace(" ", "_")
    return normalized if normalized in {"active", "registered", "disabled", "archived"} else "active"


def _invocation_status(value: str) -> str:
    normalized = str(value or "succeeded").strip().lower().replace(" ", "_")
    return normalized if normalized in {"succeeded", "failed", "blocked", "running"} else "failed"


def _collect_paths(*payloads: Any) -> list[str]:
    paths: list[str] = []
    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key.endswith("path") or key.endswith("_path") or key in {"path", "target_path", "draft_path", "patch_path"}:
                    if isinstance(item, str):
                        paths.append(item)
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    for payload in payloads:
        walk(payload)
    return _dedupe(paths)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
