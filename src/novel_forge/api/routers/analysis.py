from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.analysis import convert_analysis_report, create_analysis_handoff, list_analysis_reports, run_analysis
from novel_forge.storage.local import LocalStorage


def create_router(ctx: ProductRouterContext) -> APIRouter:
    app_settings = ctx.app_settings
    models = ctx.models
    globals().update(models)
    router = APIRouter(tags=["product-analysis"])
    AnalysisRunRequest = models["AnalysisRunRequest"]
    AnalysisConvertRequest = models["AnalysisConvertRequest"]
    AnalysisHandoffRequest = models["AnalysisHandoffRequest"]

    @router.get("/product/analysis/reports")
    def analysis_reports(
        project_id: str | None = None,
        report_type: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        try:
            return list_analysis_reports(
                LocalStorage(app_settings.root),
                project_id=project_id,
                report_type=report_type,
                limit=limit,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/analysis/run")
    def run_analysis_endpoint(request: AnalysisRunRequest) -> dict[str, Any]:
        data = _model_data(request)
        try:
            return run_analysis(
                LocalStorage(app_settings.root),
                str(data.get("source_path", "")),
                str(data.get("analysis_type", "web_fiction_business")),
                workspace_path=data.get("workspace_path"),
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/analysis/convert")
    def convert_analysis_endpoint(request: AnalysisConvertRequest) -> dict[str, Any]:
        data = _model_data(request)
        try:
            return convert_analysis_report(
                LocalStorage(app_settings.root),
                str(data.get("report_path", "")),
                targets=[str(item) for item in data.get("targets", [])],
                workspace_path=data.get("workspace_path"),
                reuse_scope=str(data.get("reuse_scope") or "project"),
                human_approved=bool(data.get("human_approved", False)),
                approval_note=str(data.get("approval_note") or ""),
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/analysis/handoff")
    def create_analysis_handoff_endpoint(request: AnalysisHandoffRequest) -> dict[str, Any]:
        data = _model_data(request)
        try:
            return create_analysis_handoff(
                LocalStorage(app_settings.root),
                str(data.get("input_path", "")),
                str(data.get("analysis_type", "web_fiction_business")),
                workspace_path=data.get("workspace_path"),
                purpose=str(data.get("purpose") or ""),
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router


def _model_data(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    if hasattr(model, "dict"):
        return model.dict()
    return dict(model)
