from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from novel_forge.api.routers._bindings import bind_product_symbols
from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.creative_assets import (
    create_creative_asset,
    creative_asset_schema,
    list_creative_assets,
    list_creative_libraries,
)
from novel_forge.modules.standards import create_quality_score_report
from novel_forge.modules.style import create_style_decomposition_report, create_style_review_report, style_drift_trend
from novel_forge.storage.local import LocalStorage


def create_router(ctx: ProductRouterContext) -> APIRouter:
    app_settings = ctx.app_settings
    models = ctx.models
    globals().update(models)
    bind_product_symbols(globals(), ctx.services)
    router = APIRouter(tags=["product-libraries"])
    CreativeAssetCreateRequest = models["CreativeAssetCreateRequest"]
    StyleDecomposeRequest = models["StyleDecomposeRequest"]
    StyleReviewRequest = models["StyleReviewRequest"]
    QualityScoreRequest = models["QualityScoreRequest"]

    @router.get("/product/libraries/creative")
    @router.get("/product/creative-assets/libraries")
    def creative_libraries(
        project_id: str | None = None,
        include_global: bool = True,
        limit_per_library: int = Query(default=12, ge=1, le=100),
    ) -> list[dict[str, Any]]:
        try:
            return list_creative_libraries(
                LocalStorage(app_settings.root),
                project_id=project_id,
                include_global=include_global,
                limit_per_library=limit_per_library,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/libraries/creative/schema")
    @router.get("/product/creative-assets/schema")
    def creative_libraries_schema() -> dict[str, Any]:
        return creative_asset_schema()

    @router.get("/product/libraries/creative/{library_key}")
    @router.get("/product/creative-assets/libraries/{library_key}")
    def creative_library_assets(
        library_key: str,
        project_id: str | None = None,
        include_global: bool = True,
        keyword: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        try:
            return list_creative_assets(
                LocalStorage(app_settings.root),
                library_key,
                project_id=project_id,
                include_global=include_global,
                keyword=keyword,
                limit=limit,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/libraries/creative/assets")
    @router.post("/product/creative-assets")
    def create_creative_asset_endpoint(request: CreativeAssetCreateRequest) -> dict[str, Any]:
        try:
            return create_creative_asset(LocalStorage(app_settings.root), _model_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/styles/decompose")
    def style_decompose_endpoint(request: StyleDecomposeRequest) -> dict[str, Any]:
        storage = LocalStorage(app_settings.root)
        try:
            path = create_style_decomposition_report(storage, request.source_path, workspace_path=request.workspace_path)
            return {"path": str(path.relative_to(storage.root))}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/styles/review")
    def style_review_endpoint(request: StyleReviewRequest) -> dict[str, Any]:
        storage = LocalStorage(app_settings.root)
        try:
            path = create_style_review_report(
                storage,
                request.draft_path,
                style_profile_path=request.style_profile_path,
                workspace_path=request.workspace_path,
            )
            return {"path": str(path.relative_to(storage.root))}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/styles/trend")
    def style_trend_endpoint(project_id: str | None = None, limit: int = Query(default=50, ge=1, le=500)) -> dict[str, Any]:
        try:
            return style_drift_trend(LocalStorage(app_settings.root), project_id=project_id, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/quality/score")
    def quality_score_endpoint(request: QualityScoreRequest) -> dict[str, Any]:
        storage = LocalStorage(app_settings.root)
        try:
            path = create_quality_score_report(storage, request.target_path, workspace_path=request.workspace_path)
            return {"path": str(path.relative_to(storage.root))}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
