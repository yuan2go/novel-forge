from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.feedback import (
    analyze_feedback,
    apply_feedback_strategy_to_workspace,
    create_feedback_import_batch,
    create_operational_metric_snapshot,
    create_reader_simulation_report,
    create_reader_sentiment_report,
    list_feedback_assets,
    process_publish_feedback_loop,
    process_real_feedback_backflow,
)
from novel_forge.modules.feedback_backflow import apply_feedback_backflow_plan, create_feedback_backflow_plan
from novel_forge.storage.local import LocalStorage


def create_router(ctx: ProductRouterContext) -> APIRouter:
    app_settings = ctx.app_settings
    models = ctx.models
    globals().update(models)
    router = APIRouter(tags=["product-feedback"])
    FeedbackImportBatchRequest = models["FeedbackImportBatchRequest"]
    ReaderSentimentReportRequest = models["ReaderSentimentReportRequest"]
    FeedbackInsightRequest = models["FeedbackInsightRequest"]
    FeedbackStrategyApplyRequest = models["FeedbackStrategyApplyRequest"]
    FeedbackBackflowPlanRequest = models["FeedbackBackflowPlanRequest"]
    FeedbackBackflowApplyRequest = models["FeedbackBackflowApplyRequest"]
    PublishFeedbackLoopRequest = models["PublishFeedbackLoopRequest"]
    ReaderSimulationRequest = models["ReaderSimulationRequest"]
    RealFeedbackBackflowRequest = models["RealFeedbackBackflowRequest"]
    OperationalMetricSnapshotRequest = models["OperationalMetricSnapshotRequest"]

    @router.get("/product/feedback/assets")
    def feedback_assets(project_id: str | None = None, limit: int = Query(default=100, ge=1, le=500)) -> list[dict[str, Any]]:
        try:
            return list_feedback_assets(LocalStorage(app_settings.root), project_id=project_id, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/feedback/import-batch")
    def feedback_import_batch_endpoint(request: FeedbackImportBatchRequest) -> dict[str, Any]:
        try:
            return create_feedback_import_batch(
                LocalStorage(app_settings.root),
                request.input_path,
                workspace_path=request.workspace_path,
                source_label=request.source_label,
                platform=request.platform,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/feedback/sentiment-report")
    def feedback_sentiment_report_endpoint(request: ReaderSentimentReportRequest) -> dict[str, Any]:
        try:
            return create_reader_sentiment_report(
                LocalStorage(app_settings.root),
                feedback_paths=request.feedback_paths,
                project_id=request.project_id,
                workspace_path=request.workspace_path,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/feedback/operational-snapshot")
    def feedback_operational_snapshot_endpoint(request: OperationalMetricSnapshotRequest) -> dict[str, Any]:
        try:
            return create_operational_metric_snapshot(
                LocalStorage(app_settings.root),
                feedback_paths=request.feedback_paths,
                project_id=request.project_id,
                workspace_path=request.workspace_path,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/feedback/insight")
    def feedback_insight_endpoint(request: FeedbackInsightRequest) -> dict[str, Any]:
        storage = LocalStorage(app_settings.root)
        try:
            path = analyze_feedback(storage, input_path=request.input_path)
            return {"path": str(path.relative_to(storage.root))}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/feedback/apply-strategy")
    def feedback_apply_strategy_endpoint(request: FeedbackStrategyApplyRequest) -> dict[str, Any]:
        try:
            return apply_feedback_strategy_to_workspace(
                LocalStorage(app_settings.root),
                request.report_path,
                workspace_path=request.workspace_path,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/feedback/backflow-plan")
    def feedback_backflow_plan_endpoint(request: FeedbackBackflowPlanRequest) -> dict[str, Any]:
        try:
            return create_feedback_backflow_plan(
                LocalStorage(app_settings.root),
                feedback_paths=request.feedback_paths,
                project_id=request.project_id,
                workspace_path=request.workspace_path,
                require_human_gate=request.require_human_gate,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/feedback/backflow-apply")
    def feedback_backflow_apply_endpoint(request: FeedbackBackflowApplyRequest) -> dict[str, Any]:
        try:
            return apply_feedback_backflow_plan(
                LocalStorage(app_settings.root),
                plan_path=request.plan_path,
                confirmed=request.confirmed,
                note=request.note,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/feedback/publish-loop")
    def feedback_publish_loop_endpoint(request: PublishFeedbackLoopRequest) -> dict[str, Any]:
        try:
            return process_publish_feedback_loop(
                LocalStorage(app_settings.root),
                feedback_paths=request.feedback_paths,
                project_id=request.project_id,
                workspace_path=request.workspace_path,
                release_package_path=request.release_package_path,
                apply_mkaos_weight_update=request.apply_mkaos_weight_update,
                require_human_gate=request.require_human_gate,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/feedback/reader-simulation")
    def feedback_reader_simulation_endpoint(request: ReaderSimulationRequest) -> dict[str, Any]:
        try:
            return create_reader_simulation_report(
                LocalStorage(app_settings.root),
                draft_path=request.draft_path,
                chapter_text=request.chapter_text,
                project_id=request.project_id,
                workspace_path=request.workspace_path,
                platform=request.platform,
                chapter=request.chapter,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/feedback/real-backflow")
    def feedback_real_backflow_endpoint(request: RealFeedbackBackflowRequest) -> dict[str, Any]:
        try:
            return process_real_feedback_backflow(
                LocalStorage(app_settings.root),
                metrics=request.metrics,
                project_id=request.project_id,
                workspace_path=request.workspace_path,
                platform=request.platform,
                release_package_path=request.release_package_path,
                apply_mkaos_weight_update=request.apply_mkaos_weight_update,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
