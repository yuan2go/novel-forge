from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.agent_messages import (
    acknowledge_agent_message,
    create_agent_conversation_trace,
    create_agent_handoff,
    list_agent_messages,
    replay_agent_messages,
    send_agent_message,
)
from novel_forge.modules.long_memory import (
    create_memory_from_asset,
    create_memory_record,
    list_memory_records,
    retrieve_memory,
    select_memory_for_node,
)
from novel_forge.modules.model_router import create_model_route, execute_model_gateway_call, list_model_router_assets, provider_approval_evidence_report, resolve_model_route
from novel_forge.modules.novel_os_cockpit import build_multi_book_daily_production_report, build_multi_book_production_schedule, build_project_cockpit_snapshot
from novel_forge.modules.pgvector_store import (
    build_embedding_job,
    create_pgvector_schema_plan,
    hybrid_retrieve,
    migrate_pgvector_online,
    pgvector_capabilities,
    pgvector_online_e2e_smoke,
    pgvector_operations_plan,
    pgvector_qdrant_comparison_report,
    rebuild_dirty_index,
    verify_pgvector_migration,
)
from novel_forge.modules.prompt_registry import (
    bind_prompt_to_node,
    create_prompt_template,
    create_prompt_version_asset,
    list_prompt_registry_assets,
    release_prompt_version,
    resolve_prompt,
)
from novel_forge.modules.state_bus import create_state_snapshot, detect_state_conflicts, list_state_events, record_state_event, replay_state_events
from novel_forge.modules.tool_gateway import (
    create_tool_permission_policy,
    invoke_tool,
    list_tool_gateway_assets,
    register_internal_tools,
    register_mcp_server,
)
from novel_forge.storage.local import LocalStorage


def create_router(ctx: ProductRouterContext) -> APIRouter:
    app_settings = ctx.app_settings
    models = ctx.models
    globals().update(models)
    router = APIRouter(prefix="/product/os", tags=["product-os-capabilities"])

    ModelRouteRequest = models["ModelRouteRequest"]
    ModelRouteResolveRequest = models["ModelRouteResolveRequest"]
    ModelGatewayCallRequest = models["ModelGatewayCallRequest"]
    PromptTemplateRequest = models["PromptTemplateRequest"]
    PromptVersionRequest = models["PromptVersionRequest"]
    PromptReleaseRequest = models["PromptReleaseRequest"]
    PromptNodeBindingRequest = models["PromptNodeBindingRequest"]
    ToolPermissionPolicyRequest = models["ToolPermissionPolicyRequest"]
    MCPServerRegistryRequest = models["MCPServerRegistryRequest"]
    ToolInvokeRequest = models["ToolInvokeRequest"]
    StateEventRequest = models["StateEventRequest"]
    StateSnapshotRequest = models["StateSnapshotRequest"]
    StateReplayRequest = models["StateReplayRequest"]
    StateConflictRequest = models["StateConflictRequest"]
    AgentMessageRequest = models["AgentMessageRequest"]
    AgentMessageAckRequest = models["AgentMessageAckRequest"]
    AgentHandoffRequest = models["AgentHandoffRequest"]
    AgentConversationTraceRequest = models["AgentConversationTraceRequest"]
    MemoryRecordRequest = models["MemoryRecordRequest"]
    MemoryFromAssetRequest = models["MemoryFromAssetRequest"]
    MemorySelectionRequest = models["MemorySelectionRequest"]
    MemoryRetrievalRequest = models["MemoryRetrievalRequest"]
    PgVectorSchemaPlanRequest = models["PgVectorSchemaPlanRequest"]
    EmbeddingJobRequest = models["EmbeddingJobRequest"]
    HybridRetrievalRequest = models["HybridRetrievalRequest"]
    PgVectorMigrateRequest = models["PgVectorMigrateRequest"]

    @router.get("/cockpit/project")
    def project_cockpit_snapshot(project_id: str = "local-project") -> dict[str, Any]:
        try:
            return build_project_cockpit_snapshot(LocalStorage(app_settings.root), project_id=project_id)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/cockpit/multi-book")
    def multi_book_daily_production_report(project_ids: str = "", provider_budget: float = 0.0) -> dict[str, Any]:
        try:
            ids = [item.strip() for item in project_ids.split(",") if item.strip()] if project_ids else None
            return build_multi_book_daily_production_report(LocalStorage(app_settings.root), project_ids=ids, provider_budget=provider_budget)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/cockpit/multi-book/schedule")
    def multi_book_production_schedule(project_ids: str = "", provider_budget: float = 0.0, max_parallel_books: int = 2, daily_chapter_goal: int = 1) -> dict[str, Any]:
        try:
            ids = [item.strip() for item in project_ids.split(",") if item.strip()] if project_ids else None
            return build_multi_book_production_schedule(
                LocalStorage(app_settings.root),
                project_ids=ids,
                provider_budget=provider_budget,
                max_parallel_books=max_parallel_books,
                daily_chapter_goal=daily_chapter_goal,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/model-router/assets")
    def model_router_assets(project_id: str | None = None, task_type: str | None = None, limit: int = Query(default=200, ge=1, le=1000)) -> list[dict[str, Any]]:
        try:
            return list_model_router_assets(LocalStorage(app_settings.root), project_id=project_id, task_type=task_type, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/model-router/provider-approval-report")
    def model_router_provider_approval_report(
        project_id: str | None = None,
        task_type: str | None = None,
        limit: int = Query(default=200, ge=1, le=1000),
    ) -> dict[str, Any]:
        try:
            return provider_approval_evidence_report(LocalStorage(app_settings.root), project_id=project_id, task_type=task_type, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/model-router/route")
    def model_route_create(request: ModelRouteRequest) -> dict[str, Any]:
        try:
            return create_model_route(
                LocalStorage(app_settings.root),
                task_type=request.task_type,
                provider=request.provider,
                model_name=request.model_name,
                fallbacks=request.fallbacks,
                selection_rule=request.selection_rule,
                max_cost_per_run=request.max_cost_per_run,
                max_latency_ms=request.max_latency_ms,
                status=request.status,
                project_id=request.project_id or "",
                workspace_path=request.workspace_path or "",
                environment=request.environment,
                approval_status=request.approval_status,
                approval_id=request.approval_id,
                approved_by=request.approved_by,
                approval_reason=request.approval_reason,
                production_provider_allowlist=request.production_provider_allowlist,
                mock_provider_test_mode=request.mock_provider_test_mode,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/model-router/resolve")
    def model_route_resolve(request: ModelRouteResolveRequest) -> dict[str, Any]:
        try:
            return resolve_model_route(
                LocalStorage(app_settings.root),
                task_type=request.task_type,
                project_id=request.project_id or "",
                workspace_path=request.workspace_path or "",
                prompt_id=request.prompt_id,
                prompt_version=request.prompt_version,
                workflow_node_id=request.workflow_node_id,
                trace=request.trace,
                persist=request.persist,
                environment=request.environment,
                allow_mock_fixture=request.allow_mock_fixture,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/model-router/gateway-call")
    def model_gateway_call(request: ModelGatewayCallRequest) -> dict[str, Any]:
        try:
            return execute_model_gateway_call(
                LocalStorage(app_settings.root),
                task_type=request.task_type,
                operation=request.operation,
                prompt_id=request.prompt_id,
                prompt_version=request.prompt_version,
                project_id=request.project_id or "",
                workspace_path=request.workspace_path or "",
                input_assets=request.input_assets,
                output_assets=request.output_assets,
                context_bundle_path=request.context_bundle_path,
                provider_runtime_guard=request.provider_runtime_guard,
                usage=request.usage,
                cost=request.cost,
                status=request.status,
                trace=request.trace,
                mode=request.mode,
                environment=request.environment,
                allow_mock_fixture=request.allow_mock_fixture,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/prompts/assets")
    def prompt_assets(project_id: str | None = None, task_type: str | None = None, limit: int = Query(default=200, ge=1, le=1000)) -> list[dict[str, Any]]:
        try:
            return list_prompt_registry_assets(LocalStorage(app_settings.root), project_id=project_id, task_type=task_type, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/prompts/template")
    def prompt_template_create(request: PromptTemplateRequest) -> dict[str, Any]:
        try:
            return create_prompt_template(LocalStorage(app_settings.root), **_request_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/prompts/version")
    def prompt_version_create(request: PromptVersionRequest) -> dict[str, Any]:
        try:
            return create_prompt_version_asset(
                LocalStorage(app_settings.root),
                prompt_id=request.prompt_id,
                version=request.version,
                task_type=request.task_type,
                template=request.template,
                status=request.status,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/prompts/release")
    def prompt_release_create(request: PromptReleaseRequest) -> dict[str, Any]:
        try:
            return release_prompt_version(LocalStorage(app_settings.root), **_request_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/prompts/binding")
    def prompt_binding_create(request: PromptNodeBindingRequest) -> dict[str, Any]:
        try:
            return bind_prompt_to_node(LocalStorage(app_settings.root), **_request_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/prompts/resolve")
    def prompt_resolve(prompt_id: str = "", task_type: str = "", version: str = "", workflow_node_id: str = "", project_id: str = "") -> dict[str, Any]:
        try:
            return resolve_prompt(LocalStorage(app_settings.root), prompt_id=prompt_id, task_type=task_type, version=version, workflow_node_id=workflow_node_id, project_id=project_id)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/tools/register-internal")
    def tools_register_internal(project_id: str | None = None, workspace_path: str | None = None) -> dict[str, Any]:
        try:
            return register_internal_tools(LocalStorage(app_settings.root), project_id=project_id or "", workspace_path=workspace_path or "")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/tools/assets")
    def tool_assets(project_id: str | None = None, limit: int = Query(default=300, ge=1, le=1000)) -> list[dict[str, Any]]:
        try:
            return list_tool_gateway_assets(LocalStorage(app_settings.root), project_id=project_id, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/tools/permission-policy")
    def tool_permission_create(request: ToolPermissionPolicyRequest) -> dict[str, Any]:
        try:
            return create_tool_permission_policy(LocalStorage(app_settings.root), **_request_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/tools/mcp-server")
    def mcp_server_create(request: MCPServerRegistryRequest) -> dict[str, Any]:
        try:
            return register_mcp_server(LocalStorage(app_settings.root), **_request_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/tools/invoke")
    def tool_invoke(request: ToolInvokeRequest) -> dict[str, Any]:
        try:
            return invoke_tool(LocalStorage(app_settings.root), **_request_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/state/event")
    def state_event_create(request: StateEventRequest) -> dict[str, Any]:
        try:
            return record_state_event(LocalStorage(app_settings.root), **_request_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/state/events")
    def state_events(stream: str | None = None, subject_id: str | None = None, project_id: str | None = None, limit: int = Query(default=500, ge=1, le=5000)) -> list[dict[str, Any]]:
        try:
            return list_state_events(LocalStorage(app_settings.root), stream=stream, subject_id=subject_id, project_id=project_id, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/state/snapshot")
    def state_snapshot_create(request: StateSnapshotRequest) -> dict[str, Any]:
        try:
            return create_state_snapshot(LocalStorage(app_settings.root), **_request_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/state/replay")
    def state_replay_create(request: StateReplayRequest) -> dict[str, Any]:
        try:
            return replay_state_events(LocalStorage(app_settings.root), **_request_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/state/conflicts")
    def state_conflicts_create(request: StateConflictRequest) -> dict[str, Any]:
        try:
            return detect_state_conflicts(LocalStorage(app_settings.root), **_request_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/messages/send")
    def message_send(request: AgentMessageRequest) -> dict[str, Any]:
        try:
            return send_agent_message(LocalStorage(app_settings.root), **_request_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/messages/ack")
    def message_ack(request: AgentMessageAckRequest) -> dict[str, Any]:
        try:
            return acknowledge_agent_message(LocalStorage(app_settings.root), request.message_path_or_id, actor_agent=request.actor_agent, note=request.note)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/messages")
    def messages(agent_type: str | None = None, conversation_id: str | None = None, status: str | None = None, project_id: str | None = None, limit: int = Query(default=300, ge=1, le=1000)) -> list[dict[str, Any]]:
        try:
            return list_agent_messages(LocalStorage(app_settings.root), agent_type=agent_type, conversation_id=conversation_id, status=status, project_id=project_id, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/messages/replay")
    def messages_replay(conversation_id: str, project_id: str | None = None) -> dict[str, Any]:
        try:
            return replay_agent_messages(LocalStorage(app_settings.root), conversation_id=conversation_id, project_id=project_id or "")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/messages/handoff")
    def message_handoff(request: AgentHandoffRequest) -> dict[str, Any]:
        try:
            return create_agent_handoff(LocalStorage(app_settings.root), **_request_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/messages/conversation-trace")
    def message_conversation_trace(request: AgentConversationTraceRequest) -> dict[str, Any]:
        try:
            return create_agent_conversation_trace(LocalStorage(app_settings.root), **_request_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/memory/record")
    def memory_record_create(request: MemoryRecordRequest) -> dict[str, Any]:
        try:
            return create_memory_record(LocalStorage(app_settings.root), **_request_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/memory/from-asset")
    def memory_from_asset(request: MemoryFromAssetRequest) -> dict[str, Any]:
        try:
            return create_memory_from_asset(LocalStorage(app_settings.root), **_request_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/memory/records")
    def memory_records(project_id: str | None = None, level: str | None = None, limit: int = Query(default=500, ge=1, le=2000)) -> list[dict[str, Any]]:
        try:
            return list_memory_records(LocalStorage(app_settings.root), project_id=project_id, level=level, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/memory/select")
    def memory_select(request: MemorySelectionRequest) -> dict[str, Any]:
        try:
            return select_memory_for_node(LocalStorage(app_settings.root), **_request_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/memory/retrieve")
    def memory_retrieve(request: MemoryRetrievalRequest) -> dict[str, Any]:
        try:
            return retrieve_memory(LocalStorage(app_settings.root), **_request_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/retrieval/pgvector-schema-plan")
    def pgvector_schema_plan(request: PgVectorSchemaPlanRequest) -> dict[str, Any]:
        try:
            return create_pgvector_schema_plan(LocalStorage(app_settings.root), **_request_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/retrieval/pgvector-capabilities")
    def pgvector_capability_report(project_id: str | None = None) -> dict[str, Any]:
        try:
            return pgvector_capabilities(LocalStorage(app_settings.root), project_id=project_id or "")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/retrieval/pgvector-operations-plan")
    def pgvector_operations(project_id: str | None = None, target_chunk_count: int = Query(default=500000, ge=1, le=5000000), target_qps: int = Query(default=20, ge=1, le=10000)) -> dict[str, Any]:
        try:
            return pgvector_operations_plan(LocalStorage(app_settings.root), project_id=project_id or "", target_chunk_count=target_chunk_count, target_qps=target_qps, persist=False)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/retrieval/pgvector-migrate")
    def pgvector_migrate(request: PgVectorMigrateRequest) -> dict[str, Any]:
        try:
            return migrate_pgvector_online(LocalStorage(app_settings.root), dry_run=request.dry_run, project_id=request.project_id or "")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/retrieval/pgvector-verify")
    def pgvector_verify(request: PgVectorMigrateRequest) -> dict[str, Any]:
        try:
            return verify_pgvector_migration(LocalStorage(app_settings.root), project_id=request.project_id or "")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/retrieval/pgvector-online-smoke")
    def pgvector_online_smoke(request: PgVectorMigrateRequest) -> dict[str, Any]:
        try:
            return pgvector_online_e2e_smoke(LocalStorage(app_settings.root), project_id=request.project_id or "", require_online=not request.dry_run)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/retrieval/rebuild-dirty-index")
    def pgvector_rebuild_dirty_index(request: PgVectorMigrateRequest) -> dict[str, Any]:
        try:
            return rebuild_dirty_index(LocalStorage(app_settings.root), project_id=request.project_id or "", persist=True)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/retrieval/pgvector-qdrant-comparison")
    def pgvector_qdrant_comparison(project_id: str | None = None) -> dict[str, Any]:
        try:
            return pgvector_qdrant_comparison_report(LocalStorage(app_settings.root), project_id=project_id or "")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/retrieval/embedding-job")
    def embedding_job(request: EmbeddingJobRequest) -> dict[str, Any]:
        try:
            return build_embedding_job(LocalStorage(app_settings.root), **_request_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/retrieval/hybrid")
    def hybrid_retrieval(request: HybridRetrievalRequest) -> dict[str, Any]:
        try:
            return hybrid_retrieve(LocalStorage(app_settings.root), **_request_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router


def _request_data(request: Any) -> dict[str, Any]:
    if hasattr(request, "model_dump"):
        return request.model_dump()
    return request.dict()
