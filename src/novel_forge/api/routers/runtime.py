from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.runtime_ledger import (
    create_cost_quality_dashboard,
    list_cost_ledgers,
    trace_timeline_payload,
)
from novel_forge.modules.operation_transactions import apply_rollback_plan, coordinate_runtime_rollback, preview_operation_rollback, verify_rollback_result
from novel_forge.modules.runtime_policy import check_runtime_policy, runtime_policy_enforcement_report, runtime_policy_legacy_entrypoint_audit, runtime_policy_status
from novel_forge.modules.runtime_policy import provider_hard_stop_evidence_report, runtime_policy_surface_coverage_report
from novel_forge.modules.production_kernel import list_production_operations, production_entrypoint_audit
from novel_forge.storage.local import LocalStorage


def create_router(ctx: ProductRouterContext) -> APIRouter:
    app_settings = ctx.app_settings
    models = ctx.models
    globals().update(models)
    router = APIRouter(tags=["product-runtime"])
    RuntimeCostSnapshotRequest = models["RuntimeCostSnapshotRequest"]
    RuntimePolicyCheckRequest = models["RuntimePolicyCheckRequest"]
    RollbackPreviewRequest = models["RollbackPreviewRequest"]
    RollbackApplyRequest = models["RollbackApplyRequest"]
    RollbackVerifyRequest = models["RollbackVerifyRequest"]
    RollbackCoordinateRequest = models["RollbackCoordinateRequest"]

    @router.get("/product/runtime/policy/status")
    def runtime_policy_status_endpoint(
        project_id: str | None = None,
        workspace_path: str | None = None,
        mode: str | None = None,
    ) -> dict[str, Any]:
        try:
            return runtime_policy_status(LocalStorage(app_settings.root), project_id=project_id, workspace_path=workspace_path, mode=mode)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/runtime/policy/enforcement-report")
    def runtime_policy_enforcement_report_endpoint(
        project_id: str | None = None,
        workspace_path: str | None = None,
        mode: str | None = None,
    ) -> dict[str, Any]:
        try:
            return runtime_policy_enforcement_report(LocalStorage(app_settings.root), project_id=project_id, workspace_path=workspace_path, mode=mode)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/runtime/policy/legacy-entrypoint-audit")
    def runtime_policy_legacy_entrypoint_audit_endpoint() -> dict[str, Any]:
        try:
            return runtime_policy_legacy_entrypoint_audit()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/runtime/production-entrypoint-audit")
    def production_entrypoint_audit_endpoint() -> dict[str, Any]:
        try:
            return production_entrypoint_audit()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/runtime/production-operations")
    def production_operations_endpoint(
        project_id: str | None = None,
        status: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        try:
            return list_production_operations(LocalStorage(app_settings.root), project_id=project_id, status=status, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/runtime/policy/surface-coverage")
    def runtime_policy_surface_coverage_endpoint(
        project_id: str | None = None,
        workspace_path: str | None = None,
        mode: str | None = None,
    ) -> dict[str, Any]:
        try:
            return runtime_policy_surface_coverage_report(LocalStorage(app_settings.root), project_id=project_id, workspace_path=workspace_path, mode=mode)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/runtime/provider-hard-stop-evidence")
    def runtime_provider_hard_stop_evidence_endpoint(
        project_id: str | None = None,
        workspace_path: str | None = None,
    ) -> dict[str, Any]:
        try:
            return provider_hard_stop_evidence_report(LocalStorage(app_settings.root), project_id=project_id, workspace_path=workspace_path)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/runtime/policy/check")
    def runtime_policy_check_endpoint(request: RuntimePolicyCheckRequest) -> dict[str, Any]:
        try:
            return check_runtime_policy(
                LocalStorage(app_settings.root),
                operation=request.operation,
                project_id=request.project_id or "",
                workspace_path=request.workspace_path or "",
                input_assets=request.input_assets,
                output_assets=request.output_assets,
                context_bundle_path=request.context_bundle_path,
                runtime_policy=request.runtime_policy,
                token_used=request.token_used,
                cost_estimate=request.cost_estimate,
                currency=request.currency,
                trace=request.trace,
                phase=request.phase,
                mode=request.mode,
                model_call_log_path=request.model_call_log_path,
                cost_ledger_paths=request.cost_ledger_paths,
                gate_result_paths=request.gate_result_paths,
                require_context_bundle=request.require_context_bundle,
                require_budget_policy=request.require_budget_policy,
                require_model_call_log=request.require_model_call_log,
                require_cost_ledger=request.require_cost_ledger,
                required_gates=request.required_gates,
                persist_gate_result=request.persist_gate_result,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/runtime/trace-timeline")
    def runtime_trace_timeline(
        trace_id: str | None = None,
        project_id: str | None = None,
        limit: int = Query(default=300, ge=1, le=1000),
    ) -> dict[str, Any]:
        try:
            return trace_timeline_payload(LocalStorage(app_settings.root), trace_id=trace_id, project_id=project_id, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/runtime/cost-ledger")
    def runtime_cost_ledger(
        project_id: str | None = None,
        scope: str | None = None,
        source_type: str | None = None,
        limit: int = Query(default=500, ge=1, le=2000),
    ) -> list[dict[str, Any]]:
        try:
            return list_cost_ledgers(LocalStorage(app_settings.root), project_id=project_id, scope=scope, source_type=source_type, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/runtime/cost-dashboard")
    def runtime_cost_dashboard(
        project_id: str | None = None,
        workspace_path: str | None = None,
        chapter: int | None = None,
    ) -> dict[str, Any]:
        try:
            return create_cost_quality_dashboard(
                LocalStorage(app_settings.root),
                project_id=project_id,
                workspace_path=workspace_path,
                chapter=chapter,
                persist_snapshots=False,
                persist_dashboard=False,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/runtime/cost-snapshot")
    def runtime_cost_snapshot(request: RuntimeCostSnapshotRequest) -> dict[str, Any]:
        try:
            return create_cost_quality_dashboard(
                LocalStorage(app_settings.root),
                project_id=request.project_id,
                workspace_path=request.workspace_path,
                chapter=request.chapter,
                persist_snapshots=request.persist_snapshots,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/runtime/rollback/verify")
    def runtime_rollback_verify(request: RollbackVerifyRequest) -> dict[str, Any]:
        try:
            return verify_rollback_result(LocalStorage(app_settings.root), request.result_path_or_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/runtime/rollback/preview")
    def runtime_rollback_preview(request: RollbackPreviewRequest) -> dict[str, Any]:
        try:
            return preview_operation_rollback(
                LocalStorage(app_settings.root),
                request.transaction_path_or_id,
                strategy=request.strategy,
                reason=request.reason,
                persist=request.persist,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/runtime/rollback/apply")
    def runtime_rollback_apply(request: RollbackApplyRequest) -> dict[str, Any]:
        try:
            return apply_rollback_plan(
                LocalStorage(app_settings.root),
                request.plan_path_or_id,
                confirm=request.confirm,
                actor=request.actor,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/runtime/rollback/coordinate")
    def runtime_rollback_coordinate(request: RollbackCoordinateRequest) -> dict[str, Any]:
        try:
            return coordinate_runtime_rollback(
                LocalStorage(app_settings.root),
                transaction_paths=request.transaction_paths,
                strategy=request.strategy,
                confirm=request.confirm,
                actor=request.actor,
                reason=request.reason,
                project_id=request.project_id or "",
                workspace_path=request.workspace_path or "",
                trace=request.trace,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
