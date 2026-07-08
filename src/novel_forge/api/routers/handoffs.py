from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from novel_forge.api import product as _product_services
from novel_forge.api.routers._bindings import bind_product_symbols
from novel_forge.api.routers.context import ProductRouterContext

bind_product_symbols(globals(), _product_services)


def create_router(ctx: ProductRouterContext) -> APIRouter:
    app_settings = ctx.app_settings
    models = ctx.models
    globals().update(models)
    bind_product_symbols(globals(), ctx.services)
    router = APIRouter(tags=['product-handoffs'])
    HandoffDeconstructRequest = models['HandoffDeconstructRequest']
    HandoffKnowledgeRequest = models['HandoffKnowledgeRequest']
    GitHubKnowledgeHandoffRequest = models['GitHubKnowledgeHandoffRequest']
    SourcePolicyCreateRequest = models['SourcePolicyCreateRequest']
    SourceLicenseCheckRequest = models['SourceLicenseCheckRequest']
    SourceRiskReportRequest = models['SourceRiskReportRequest']
    SourceSnapshotRequest = models['SourceSnapshotRequest']
    SourceSyncJobRequest = models['SourceSyncJobRequest']
    SourceRefreshReportRequest = models['SourceRefreshReportRequest']
    SourceConnectorExecutionPlanRequest = models['SourceConnectorExecutionPlanRequest']
    SourceConnectorAdapterLifecycleRequest = models['SourceConnectorAdapterLifecycleRequest']
    SourceDiffRepairPlanRequest = models['SourceDiffRepairPlanRequest']
    SourceDiffRepairApplyRequest = models['SourceDiffRepairApplyRequest']
    SourceConnectorRunRequest = models['SourceConnectorRunRequest']
    SourceDiffRepairRollbackRequest = models['SourceDiffRepairRollbackRequest']
    SourceGovernanceApplyRequest = models['SourceGovernanceApplyRequest']
    SourceGovernanceRollbackRequest = models['SourceGovernanceRollbackRequest']
    SourceStaleQuarantineSweepRequest = models['SourceStaleQuarantineSweepRequest']
    SourceRetentionExpirySweepRequest = models['SourceRetentionExpirySweepRequest']
    SourceContextEligibilityRequest = models['SourceContextEligibilityRequest']
    HandoffOutputRequest = models['HandoffOutputRequest']
    HandoffAcceptanceRequest = models['HandoffAcceptanceRequest']
    HandoffRetryRequest = models['HandoffRetryRequest']
    HandoffFailRequest = models['HandoffFailRequest']

    @router.get("/product/handoffs")
    def handoffs(
        project_id: str | None = None,
        status: str | None = None,
        operation: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        try:
            return list_handoffs(
                LocalStorage(app_settings.root),
                project_id=project_id,
                status=status,
                operation=operation,
                limit=limit,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/sources/policies")
    def source_policies(category: str | None = None) -> list[dict[str, Any]]:
        return list_source_policies(category=category)

    @router.get("/product/sources/github")
    def github_knowledge_sources(
        category: str | None = None,
        allowed_pipeline: str | None = None,
        max_risk: str | None = None,
    ) -> list[dict[str, Any]]:
        return list_github_knowledge_sources(category=category, allowed_pipeline=allowed_pipeline, max_risk=max_risk)

    @router.get("/product/sources/connectors")
    def source_connector_adapters(include_network: bool = True) -> list[dict[str, Any]]:
        return list_source_connector_adapters(include_network=include_network)

    @router.post("/product/sources/policy")
    def create_source_policy_endpoint(request: SourcePolicyCreateRequest) -> dict[str, Any]:
        try:
            return create_source_policy(LocalStorage(app_settings.root), _model_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/sources/license-check")
    def create_source_license_check_endpoint(request: SourceLicenseCheckRequest) -> dict[str, Any]:
        try:
            return create_license_check_result(LocalStorage(app_settings.root), _model_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/sources/risk-report")
    def create_source_risk_report_endpoint(request: SourceRiskReportRequest) -> dict[str, Any]:
        try:
            return create_source_risk_report(LocalStorage(app_settings.root), _model_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/sources/snapshot")
    def create_source_snapshot_endpoint(request: SourceSnapshotRequest) -> dict[str, Any]:
        try:
            return create_source_snapshot(LocalStorage(app_settings.root), _model_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/sources/sync-job")
    def create_source_sync_job_endpoint(request: SourceSyncJobRequest) -> dict[str, Any]:
        try:
            return create_source_sync_job(LocalStorage(app_settings.root), _model_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/sources/refresh-report")
    def create_source_refresh_report_endpoint(request: SourceRefreshReportRequest) -> dict[str, Any]:
        try:
            return create_source_refresh_report(LocalStorage(app_settings.root), _model_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/sources/connector-execution-plan")
    def create_source_connector_execution_plan_endpoint(request: SourceConnectorExecutionPlanRequest) -> dict[str, Any]:
        try:
            return plan_source_connector_execution(LocalStorage(app_settings.root), _model_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/sources/connector-adapter-lifecycle")
    def create_source_connector_adapter_lifecycle_endpoint(request: SourceConnectorAdapterLifecycleRequest) -> dict[str, Any]:
        try:
            return plan_source_connector_adapter_lifecycle(LocalStorage(app_settings.root), _model_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/sources/connector-run")
    def run_source_connector_endpoint(request: SourceConnectorRunRequest) -> dict[str, Any]:
        try:
            return run_source_connector(LocalStorage(app_settings.root), _model_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/sources/diff-repair-plan")
    def create_source_diff_repair_plan_endpoint(request: SourceDiffRepairPlanRequest) -> dict[str, Any]:
        try:
            return plan_source_diff_repair(LocalStorage(app_settings.root), _model_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/sources/diff-repair-apply")
    def apply_source_diff_repair_endpoint(request: SourceDiffRepairApplyRequest) -> dict[str, Any]:
        try:
            return apply_source_diff_repair(LocalStorage(app_settings.root), _model_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/sources/diff-repair-rollback")
    def rollback_source_diff_repair_endpoint(request: SourceDiffRepairRollbackRequest) -> dict[str, Any]:
        try:
            return rollback_source_diff_repair(LocalStorage(app_settings.root), _model_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/sources/governance-apply")
    def apply_source_governance_recommendations_endpoint(request: SourceGovernanceApplyRequest) -> dict[str, Any]:
        try:
            return apply_governance_recommendations(LocalStorage(app_settings.root), _model_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/sources/governance-rollback")
    def rollback_source_governance_application_endpoint(request: SourceGovernanceRollbackRequest) -> dict[str, Any]:
        try:
            return rollback_governance_application(LocalStorage(app_settings.root), _model_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/sources/stale-sweep")
    def sweep_source_stale_quarantine_endpoint(request: SourceStaleQuarantineSweepRequest) -> dict[str, Any]:
        try:
            return sweep_source_stale_quarantine(LocalStorage(app_settings.root), _model_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/sources/retention-sweep")
    def sweep_source_retention_expiry_endpoint(request: SourceRetentionExpirySweepRequest) -> dict[str, Any]:
        try:
            return sweep_source_retention_expiry(LocalStorage(app_settings.root), _model_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/sources/guarded-apply-readiness")
    def source_guarded_apply_readiness(project_id: str | None = None, persist: bool = True, limit: int = Query(default=1000, ge=1, le=5000)) -> dict[str, Any]:
        try:
            return build_source_guarded_apply_readiness_report(LocalStorage(app_settings.root), project_id=project_id or "", persist=persist, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/sources/runtime-gate")
    def source_governance_runtime_gate(
        project_id: str | None = None,
        environment: str = "",
        mode: str = "",
        persist_readiness: bool = True,
        limit: int = Query(default=1000, ge=1, le=5000),
    ) -> dict[str, Any]:
        try:
            return run_source_governance_runtime_gate(
                LocalStorage(app_settings.root),
                project_id=project_id or "",
                environment=environment,
                mode=mode,
                persist_readiness=persist_readiness,
                limit=limit,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/sources/source-leakage-readiness")
    def source_leakage_readiness(project_id: str | None = None, persist: bool = True, limit: int = Query(default=1000, ge=1, le=5000)) -> dict[str, Any]:
        try:
            return build_source_leakage_readiness_report(LocalStorage(app_settings.root), project_id=project_id or "", persist=persist, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/sources/source-leakage-preflight-gate")
    def source_leakage_preflight_gate(
        project_id: str | None = None,
        environment: str = "",
        mode: str = "",
        persist_readiness: bool = True,
        limit: int = Query(default=1000, ge=1, le=5000),
    ) -> dict[str, Any]:
        try:
            return run_source_leakage_preflight_gate(
                LocalStorage(app_settings.root),
                project_id=project_id or "",
                environment=environment,
                mode=mode,
                persist_readiness=persist_readiness,
                limit=limit,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/sources/context-eligibility")
    def source_context_eligibility_endpoint(request: SourceContextEligibilityRequest) -> dict[str, Any]:
        try:
            return evaluate_source_context_eligibility(LocalStorage(app_settings.root), _model_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/handoffs/deconstruct")
    def create_deconstruct_handoff(request: HandoffDeconstructRequest) -> dict[str, Any]:
        try:
            return create_product_deconstruction_handoff(app_settings.root, _model_data(request))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/handoffs/knowledge")
    def create_knowledge_handoff(request: HandoffKnowledgeRequest) -> dict[str, Any]:
        try:
            return create_product_knowledge_handoff(app_settings.root, _model_data(request))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/handoffs/github-knowledge")
    def create_github_knowledge_handoff_endpoint(request: GitHubKnowledgeHandoffRequest) -> dict[str, Any]:
        try:
            return create_github_knowledge_handoff(app_settings.root, _model_data(request))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/handoffs/validate-output")
    def validate_handoff_output_endpoint(request: HandoffOutputRequest) -> dict[str, Any]:
        try:
            return validate_handoff_output(app_settings.root, _model_data(request))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/handoffs/bind-output")
    def bind_handoff_output_endpoint(request: HandoffOutputRequest) -> dict[str, Any]:
        try:
            return bind_handoff_output(app_settings.root, _model_data(request))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/handoffs/acceptance")
    def handoff_acceptance_endpoint(handoff_path: str = Query(...)) -> dict[str, Any]:
        try:
            return handoff_acceptance_status(app_settings.root, handoff_path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.patch("/product/handoffs/acceptance")
    def update_handoff_acceptance_endpoint(request: HandoffAcceptanceRequest) -> dict[str, Any]:
        try:
            return update_handoff_acceptance(app_settings.root, _model_data(request))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/handoffs/fail")
    def fail_handoff_endpoint(request: HandoffFailRequest) -> dict[str, Any]:
        try:
            return fail_handoff(app_settings.root, _model_data(request))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/handoffs/retry")
    def retry_handoff_endpoint(request: HandoffRetryRequest) -> dict[str, Any]:
        try:
            return retry_handoff(app_settings.root, _model_data(request))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


    return router
