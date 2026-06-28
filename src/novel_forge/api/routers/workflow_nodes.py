from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.workflow_nodes import (
    create_workflow_definition,
    create_workflow_node,
    execute_workflow,
    list_node_runs,
    record_node_run,
    resume_workflow,
    run_workflow_scheduler,
)
from novel_forge.storage.local import LocalStorage


def create_router(ctx: ProductRouterContext) -> APIRouter:
    app_settings = ctx.app_settings
    models = ctx.models
    globals().update(models)
    router = APIRouter(tags=["product-workflow-nodes"])
    WorkflowDefinitionCreateRequest = models["WorkflowDefinitionCreateRequest"]
    WorkflowNodeCreateRequest = models["WorkflowNodeCreateRequest"]
    NodeRunCreateRequest = models["NodeRunCreateRequest"]
    WorkflowExecuteRequest = models["WorkflowExecuteRequest"]
    WorkflowResumeRequest = models["WorkflowResumeRequest"]
    WorkflowSchedulerRequest = models["WorkflowSchedulerRequest"]

    @router.get("/product/workflow/node-runs")
    def node_runs(
        project_id: str | None = None,
        run_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        try:
            return list_node_runs(LocalStorage(app_settings.root), project_id=project_id, run_id=run_id, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/workflow/definitions")
    def workflow_definition_endpoint(request: WorkflowDefinitionCreateRequest) -> dict[str, Any]:
        try:
            return create_workflow_definition(
                LocalStorage(app_settings.root),
                name=request.name,
                nodes=request.nodes,
                entry_node_id=request.entry_node_id,
                status=request.status,
                version=request.version,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/workflow/nodes")
    def workflow_node_endpoint(request: WorkflowNodeCreateRequest) -> dict[str, Any]:
        try:
            return create_workflow_node(
                LocalStorage(app_settings.root),
                workflow_id=request.workflow_id,
                node_id=request.node_id,
                node_type=request.node_type,
                operation=request.operation,
                input_types=request.input_types,
                output_types=request.output_types,
                processor=request.processor,
                quality_gate=request.quality_gate,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/workflow/node-runs")
    def node_run_endpoint(request: NodeRunCreateRequest) -> dict[str, Any]:
        try:
            return record_node_run(
                LocalStorage(app_settings.root),
                run_id=request.run_id,
                node_id=request.node_id,
                node_type=request.node_type,
                operation=request.operation,
                status=request.status,
                input_assets=request.input_assets,
                output_assets=request.output_assets,
                processor=request.processor,
                error=request.error,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/workflow/execute")
    def workflow_execute_endpoint(request: WorkflowExecuteRequest) -> dict[str, Any]:
        try:
            return execute_workflow(
                LocalStorage(app_settings.root),
                request.workflow_path_or_id,
                input_assets=request.input_assets,
                run_id=request.run_id,
                start_node_id=request.start_node_id,
                max_nodes=request.max_nodes,
                dispatch_agents=request.dispatch_agents,
                execute_agents=request.execute_agents,
                apply_invalidation=request.apply_invalidation,
                workspace_path=request.workspace_path,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/workflow/resume")
    def workflow_resume_endpoint(request: WorkflowResumeRequest) -> dict[str, Any]:
        try:
            return resume_workflow(
                LocalStorage(app_settings.root),
                request.workflow_run_path_or_id,
                resume_node_id=request.resume_node_id,
                agent_run_path=request.agent_run_path,
                output_assets=request.output_assets,
                token_used=request.token_used,
                cost_estimate=request.cost_estimate,
                checkpoint=request.checkpoint or None,
                evidence=request.evidence,
                human_gate=request.human_gate or None,
                tool_name=request.tool_name,
                output_type=request.output_type,
                max_nodes=request.max_nodes,
                apply_invalidation=request.apply_invalidation,
                workspace_path=request.workspace_path,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/workflow/scheduler/tick")
    def workflow_scheduler_tick_endpoint(request: WorkflowSchedulerRequest) -> dict[str, Any]:
        try:
            return run_workflow_scheduler(
                LocalStorage(app_settings.root),
                project_id=request.project_id,
                limit=request.limit,
                max_nodes_per_resume=request.max_nodes_per_resume,
                dry_run=request.dry_run,
                apply_invalidation=request.apply_invalidation,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
