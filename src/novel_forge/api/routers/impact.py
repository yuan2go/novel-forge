from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.change_impact import create_change_impact_report, list_change_impact_reports
from novel_forge.storage.local import LocalStorage


def create_router(ctx: ProductRouterContext) -> APIRouter:
    app_settings = ctx.app_settings
    models = ctx.models
    globals().update(models)
    router = APIRouter(tags=["product-impact"])
    ChangeImpactRequest = models["ChangeImpactRequest"]

    @router.get("/product/impact/reports")
    def impact_reports(
        project_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        try:
            return list_change_impact_reports(LocalStorage(app_settings.root), project_id=project_id, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/impact/report")
    def impact_report_endpoint(request: ChangeImpactRequest) -> dict[str, Any]:
        try:
            return create_change_impact_report(
                LocalStorage(app_settings.root),
                request.target_path,
                max_depth=request.max_depth,
                project_id=request.project_id,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
