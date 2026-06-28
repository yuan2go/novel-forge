from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.context_builder import compare_context_bundles, create_context_build_plan, create_context_bundle, list_context_assets
from novel_forge.storage.local import LocalStorage


def create_router(ctx: ProductRouterContext) -> APIRouter:
    app_settings = ctx.app_settings
    models = ctx.models
    globals().update(models)
    router = APIRouter(tags=["product-context"])
    ContextBuildPlanRequest = models["ContextBuildPlanRequest"]
    ContextBundleRequest = models["ContextBundleRequest"]
    ContextBundleDiffRequest = models["ContextBundleDiffRequest"]

    @router.get("/product/context/assets")
    def context_assets(
        project_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        try:
            return list_context_assets(LocalStorage(app_settings.root), project_id=project_id, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/context/build-plan")
    def context_build_plan_endpoint(request: ContextBuildPlanRequest) -> dict[str, Any]:
        try:
            return create_context_build_plan(
                LocalStorage(app_settings.root),
                request.target_path,
                query=request.query,
                top_k=request.top_k,
                token_budget=request.token_budget,
                backend=request.backend,
                context_profile=request.context_profile,
                workspace_path=request.workspace_path,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/context/bundle")
    def context_bundle_endpoint(request: ContextBundleRequest) -> dict[str, Any]:
        try:
            return create_context_bundle(
                LocalStorage(app_settings.root),
                request.build_plan_path,
                max_items=request.max_items,
                selected_asset_paths=request.selected_asset_paths,
                disabled_asset_paths=request.disabled_asset_paths,
                priority_asset_paths=request.priority_asset_paths,
                final_confirmed=request.final_confirmed,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/context/diff")
    def context_bundle_diff_endpoint(request: ContextBundleDiffRequest) -> dict[str, Any]:
        try:
            return compare_context_bundles(
                LocalStorage(app_settings.root),
                request.left_path,
                request.right_path,
                persist=request.persist,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
