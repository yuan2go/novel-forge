from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

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
from novel_forge.modules.agent_scheduler import (
    agent_hard_stop_dashboard,
    agent_center_snapshot,
    agent_operation_coverage_full_report,
    create_agent_dag,
    create_agent_task,
    dispatch_agent_run,
    dispatch_revision_task_from_issue,
    list_agent_dispatch_queue,
    list_agent_operation_contracts,
    recover_agent_dispatch,
    repair_dead_letter_dispatch,
    rehearse_agent_rollback,
    run_agent_scheduler_loop,
    run_agent_scheduler_tick,
    scheduler_status,
)
from novel_forge.modules.production_kernel import dispatch_production_operation
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
    AgentSchedulerRequest = models["AgentSchedulerRequest"]
    AgentDispatchRequest = models["AgentDispatchRequest"]
    AgentDispatchRecoverRequest = models["AgentDispatchRecoverRequest"]
    AgentTaskCreateRequest = models["AgentTaskCreateRequest"]
    AgentTaskFromIssueRequest = models["AgentTaskFromIssueRequest"]

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

    @router.get("/product/agents/scheduler/status")
    def agent_scheduler_status_endpoint() -> dict[str, Any]:
        try:
            return scheduler_status(LocalStorage(app_settings.root))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/agents/scheduler/queue")
    def agent_scheduler_queue_endpoint(
        project_id: str | None = None,
        status: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        try:
            return list_agent_dispatch_queue(LocalStorage(app_settings.root), project_id=project_id, status=status, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/agents/operation-contracts")
    def agent_operation_contracts_endpoint() -> dict[str, Any]:
        return {"contracts": list_agent_operation_contracts()}

    @router.get("/product/agents/operation-coverage")
    def agent_operation_coverage_endpoint(project_id: str | None = None) -> dict[str, Any]:
        try:
            return agent_operation_coverage_full_report(LocalStorage(app_settings.root), project_id=project_id or "")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/agents/hard-stop-dashboard")
    def agent_hard_stop_dashboard_endpoint(project_id: str | None = None, workspace_path: str | None = None) -> dict[str, Any]:
        try:
            return agent_hard_stop_dashboard(LocalStorage(app_settings.root), project_id=project_id or "", workspace_path=workspace_path or "")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/agents/center")
    def agent_center_endpoint(
        project_id: str | None = None,
        limit: int = Query(default=300, ge=1, le=1000),
    ) -> dict[str, Any]:
        try:
            return agent_center_snapshot(LocalStorage(app_settings.root), project_id=project_id, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/agents/tasks")
    def agent_task_create_endpoint(request: AgentTaskCreateRequest) -> dict[str, Any]:
        try:
            return create_agent_task(
                LocalStorage(app_settings.root),
                agent_type=request.agent_type,
                operation=request.operation,
                input_assets=request.input_assets,
                output_targets=request.output_targets,
                status=request.status,
                project_id=request.project_id,
                workspace_path=request.workspace_path,
                linked_loop_run_path=request.linked_loop_run_path,
                linked_context_bundle_path=request.linked_context_bundle_path,
                linked_review_issue_path=request.linked_review_issue_path,
                linked_revision_task_path=request.linked_revision_task_path,
                evidence=request.evidence,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/agents/dag")
    async def agent_dag_endpoint(request: Request) -> dict[str, Any]:
        try:
            return create_agent_dag(LocalStorage(app_settings.root), await request.json())
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/agents/tasks/from-issue")
    def agent_task_from_issue_endpoint(request: AgentTaskFromIssueRequest) -> dict[str, Any]:
        try:
            return dispatch_revision_task_from_issue(
                LocalStorage(app_settings.root),
                request.issue_ref,
                agent_type=request.agent_type,
                operation=request.operation,
                token_budget=request.token_budget,
                priority=request.priority,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/agents/dispatch")
    def agent_dispatch_endpoint(request: AgentDispatchRequest) -> dict[str, Any]:
        try:
            return dispatch_production_operation(
                LocalStorage(app_settings.root),
                "agent.dispatch",
                agent_run_path=request.agent_run_path,
                workflow_run_id=request.workflow_run_id,
                workflow_run_path=request.workflow_run_path,
                workflow_node_id=request.workflow_node_id,
                expected_output_assets=request.expected_output_assets,
                token_used=request.token_used,
                cost_estimate=request.cost_estimate,
                max_attempts=request.max_attempts,
                priority=request.priority,
                project_id=request.project_id,
                environment=request.environment,
                envelope=request.envelope,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/agents/recover")
    def agent_dispatch_recover_endpoint(request: AgentDispatchRecoverRequest) -> dict[str, Any]:
        try:
            return recover_agent_dispatch(LocalStorage(app_settings.root), queue_path=request.queue_path, reason=request.reason)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/agents/rollback-rehearsal")
    async def agent_rollback_rehearsal_endpoint(request: Request) -> dict[str, Any]:
        try:
            return rehearse_agent_rollback(LocalStorage(app_settings.root), await request.json())
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/agents/dead-letter-repair")
    async def agent_dead_letter_repair_endpoint(request: Request) -> dict[str, Any]:
        try:
            return repair_dead_letter_dispatch(LocalStorage(app_settings.root), await request.json())
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/agents/scheduler/tick")
    def agent_scheduler_tick_endpoint(request: AgentSchedulerRequest) -> dict[str, Any]:
        try:
            if request.iterations > 1:
                return run_agent_scheduler_loop(
                    LocalStorage(app_settings.root),
                    project_id=request.project_id,
                    limit=request.limit,
                    iterations=request.iterations,
                    interval_seconds=request.interval_seconds,
                    stop_when_idle=request.stop_when_idle,
                    lease_ttl_seconds=request.lease_ttl_seconds,
                    lease_owner=request.lease_owner,
                    force_lease=request.force_lease,
                    retry_delay_seconds=request.retry_delay_seconds,
                )
            return run_agent_scheduler_tick(
                LocalStorage(app_settings.root),
                project_id=request.project_id,
                limit=request.limit,
                lease_ttl_seconds=request.lease_ttl_seconds,
                lease_owner=request.lease_owner,
                force_lease=request.force_lease,
                retry_delay_seconds=request.retry_delay_seconds,
                dry_run=request.dry_run,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
