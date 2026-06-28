from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.agent_runs import (
    create_agent_boundary_audit,
    create_agent_rollback_report,
    ensure_agent_contract,
    create_agent_sla_report,
    list_agent_events,
    list_agent_runs,
    execute_agent_run_once,
    record_agent_event,
    start_agent_run,
    update_agent_run_status,
)
from novel_forge.storage.local import LocalStorage


def create_router(ctx: ProductRouterContext) -> APIRouter:
    app_settings = ctx.app_settings
    models = ctx.models
    globals().update(models)
    router = APIRouter(tags=["product-agents"])
    AgentContractCreateRequest = models["AgentContractCreateRequest"]
    AgentRunCreateRequest = models["AgentRunCreateRequest"]
    AgentEventCreateRequest = models["AgentEventCreateRequest"]
    AgentRunStatusRequest = models["AgentRunStatusRequest"]
    AgentSlaRequest = models["AgentSlaRequest"]
    AgentRollbackRequest = models["AgentRollbackRequest"]
    AgentExecutorRunRequest = models["AgentExecutorRunRequest"]

    @router.get("/product/agents/runs")
    def agent_runs(
        project_id: str | None = None,
        status: str | None = None,
        agent_type: str | None = None,
        operation: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        try:
            return list_agent_runs(
                LocalStorage(app_settings.root),
                project_id=project_id,
                status=status,
                agent_type=agent_type,
                operation=operation,
                limit=limit,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/agents/events")
    def agent_events(
        agent_run_id: str | None = None,
        agent_run_path: str | None = None,
        project_id: str | None = None,
        limit: int = Query(default=200, ge=1, le=1000),
    ) -> list[dict[str, Any]]:
        try:
            return list_agent_events(
                LocalStorage(app_settings.root),
                agent_run_id=agent_run_id,
                agent_run_path=agent_run_path,
                project_id=project_id,
                limit=limit,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/agents/boundary-audit")
    def agent_boundary_audit(apply_runtime_guard: bool = False) -> dict[str, Any]:
        try:
            return create_agent_boundary_audit(LocalStorage(app_settings.root), apply_runtime_guard=apply_runtime_guard)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/agents/contracts")
    def agent_contract_endpoint(request: AgentContractCreateRequest) -> dict[str, Any]:
        try:
            return ensure_agent_contract(
                LocalStorage(app_settings.root),
                agent_key=request.agent_key,
                skill=request.skill,
                operation=request.operation,
                input_types=request.input_types,
                output_types=request.output_types,
                quality_gates=request.quality_gates,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/agents/runs")
    def agent_run_endpoint(request: AgentRunCreateRequest) -> dict[str, Any]:
        try:
            return start_agent_run(
                LocalStorage(app_settings.root),
                agent_key=request.agent_key,
                skill=request.skill,
                operation=request.operation,
                input_assets=request.input_assets,
                output_assets=request.output_assets,
                status=request.status,
                contract_path=request.contract_path,
                workspace_path=request.workspace_path,
                model_provider=request.model_provider,
                model_name=request.model_name,
                prompt_version=request.prompt_version,
                token_budget=request.token_budget,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.patch("/product/agents/runs/status")
    def agent_run_status_endpoint(request: AgentRunStatusRequest) -> dict[str, Any]:
        try:
            return update_agent_run_status(
                LocalStorage(app_settings.root),
                request.agent_run_path,
                status=request.status,
                output_assets=request.output_assets,
                error=request.error,
                checkpoint=request.checkpoint or None,
                evidence=request.evidence or None,
                human_gate=request.human_gate or None,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/agents/events")
    def agent_event_endpoint(request: AgentEventCreateRequest) -> dict[str, Any]:
        try:
            return record_agent_event(
                LocalStorage(app_settings.root),
                agent_run_path=request.agent_run_path,
                event_type=request.event_type,
                status=request.status,
                message=request.message,
                payload=request.payload,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/agents/sla")
    def agent_sla_endpoint(request: AgentSlaRequest) -> dict[str, Any]:
        try:
            return create_agent_sla_report(
                LocalStorage(app_settings.root),
                agent_run_path=request.agent_run_path,
                sla_seconds=request.sla_seconds,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/agents/rollback")
    def agent_rollback_endpoint(request: AgentRollbackRequest) -> dict[str, Any]:
        try:
            return create_agent_rollback_report(
                LocalStorage(app_settings.root),
                agent_run_path=request.agent_run_path,
                rollback_strategy=request.rollback_strategy,
                apply=request.apply,
                reason=request.reason,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/agents/executor/run-once")
    def agent_executor_run_once_endpoint(request: AgentExecutorRunRequest) -> dict[str, Any]:
        try:
            return execute_agent_run_once(
                LocalStorage(app_settings.root),
                request.agent_run_path,
                tool_name=request.tool_name,
                output_type=request.output_type,
                token_used=request.token_used,
                cost_estimate=request.cost_estimate,
                output_assets=request.output_assets,
                checkpoint=request.checkpoint or None,
                evidence=request.evidence or None,
                human_gate=request.human_gate or None,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
