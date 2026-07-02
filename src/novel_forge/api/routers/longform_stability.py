from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.longform_stability import (
    calibrate_longform_extraction,
    longform_os_acceptance_report,
    longform_stability_dashboard,
    model_assisted_longform_extraction,
    upsert_longform_control_asset,
)
from novel_forge.storage.local import LocalStorage


def create_router(ctx: ProductRouterContext) -> APIRouter:
    app_settings = ctx.app_settings
    models = ctx.models
    globals().update(models)
    router = APIRouter(tags=["product-longform-stability"])
    LongformExtractionRequest = models["LongformExtractionRequest"]
    LongformAcceptanceRequest = models["LongformAcceptanceRequest"]
    LongformControlAssetRequest = models["LongformControlAssetRequest"]
    LongformCalibrationRequest = models["LongformCalibrationRequest"]

    @router.get("/product/longform-stability/dashboard")
    def longform_dashboard(project_id: str | None = None, workspace_path: str | None = None, limit: int = 240) -> dict[str, Any]:
        try:
            return longform_stability_dashboard(
                LocalStorage(app_settings.root),
                project_id=project_id,
                workspace_path=workspace_path,
                limit=limit,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/longform-stability/extract")
    def longform_extract(request: LongformExtractionRequest) -> dict[str, Any]:
        try:
            return model_assisted_longform_extraction(
                LocalStorage(app_settings.root),
                request.draft_path,
                workspace_path=request.workspace_path,
                use_model=request.use_model,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/longform-stability/acceptance")
    def longform_acceptance(request: LongformAcceptanceRequest) -> dict[str, Any]:
        try:
            return longform_os_acceptance_report(
                LocalStorage(app_settings.root),
                project_id=request.project_id,
                workspace_path=request.workspace_path,
                persist=request.persist,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/longform-stability/control-asset")
    def longform_control_asset(request: LongformControlAssetRequest) -> dict[str, Any]:
        try:
            return upsert_longform_control_asset(
                LocalStorage(app_settings.root),
                asset_type=request.asset_type,
                title=request.title or "",
                project_id=request.project_id,
                workspace_path=request.workspace_path,
                content=request.content,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/longform-stability/calibrate")
    def longform_calibrate(request: LongformCalibrationRequest) -> dict[str, Any]:
        try:
            return calibrate_longform_extraction(
                LocalStorage(app_settings.root),
                request.draft_path,
                workspace_path=request.workspace_path,
                expected=request.expected,
                use_model=request.use_model,
                persist=request.persist,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
