from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from novel_forge.core.ids import utc_now
from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.workflow_nodes import (
    create_workflow_definition,
    create_workflow_node,
    execute_workflow,
    list_node_runs,
    record_node_run,
    resume_workflow,
    run_workflow_scheduler,
    run_workflow_scheduler_loop,
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
        if request.async_task:
            if request.dry_run:
                raise HTTPException(status_code=400, detail="dry_run scheduler requests cannot be enqueued")
            try:
                task = _enqueue_workflow_scheduler_task(
                    app_settings,
                    project_id=request.project_id,
                    limit=request.limit,
                    max_nodes_per_resume=request.max_nodes_per_resume,
                    iterations=request.iterations,
                    interval_seconds=request.interval_seconds,
                    apply_invalidation=request.apply_invalidation,
                    stop_when_idle=request.stop_when_idle,
                )
                return {"mode": "async", "task_id": task.id, "task_name": "novel_forge.workflow_scheduler_loop", "queue": app_settings.celery_default_queue}
            except Exception as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
        try:
            storage = LocalStorage(app_settings.root)
            if request.dry_run:
                return run_workflow_scheduler(
                    storage,
                    project_id=request.project_id,
                    limit=request.limit,
                    max_nodes_per_resume=request.max_nodes_per_resume,
                    dry_run=True,
                    apply_invalidation=request.apply_invalidation,
                )
            return run_workflow_scheduler_loop(
                storage,
                project_id=request.project_id,
                limit=request.limit,
                max_nodes_per_resume=request.max_nodes_per_resume,
                iterations=request.iterations,
                interval_seconds=request.interval_seconds,
                apply_invalidation=request.apply_invalidation,
                stop_when_idle=request.stop_when_idle,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router


def _enqueue_workflow_scheduler_task(
    app_settings: Any,
    *,
    project_id: str | None,
    limit: int,
    max_nodes_per_resume: int,
    iterations: int,
    interval_seconds: float,
    apply_invalidation: bool,
    stop_when_idle: bool,
):
    try:
        from novel_forge.workers.dispatch import enqueue_task
    except Exception as exc:
        raise RuntimeError(f"Celery dispatch import failed: {exc}") from exc
    return enqueue_task(
        "workflow_scheduler_loop_task",
        str(app_settings.root),
        project_id,
        limit,
        max_nodes_per_resume,
        iterations,
        interval_seconds,
        apply_invalidation,
        stop_when_idle,
        settings=app_settings,
        task_kwargs={"request_id": utc_now()},
    )
