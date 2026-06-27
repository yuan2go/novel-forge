from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.settings_center import create_local_settings_profile, list_settings_assets
from novel_forge.storage.local import LocalStorage


def create_router(ctx: ProductRouterContext) -> APIRouter:
    app_settings = ctx.app_settings
    models = ctx.models
    globals().update(models)
    router = APIRouter(tags=["product-settings"])
    LocalSettingsProfileRequest = models["LocalSettingsProfileRequest"]

    @router.get("/product/settings/assets")
    def settings_assets(project_id: str | None = None, limit: int = Query(default=100, ge=1, le=500)) -> list[dict[str, Any]]:
        try:
            return list_settings_assets(LocalStorage(app_settings.root), project_id=project_id, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/settings/profile")
    def settings_profile_endpoint(request: LocalSettingsProfileRequest) -> dict[str, Any]:
        try:
            return create_local_settings_profile(
                LocalStorage(app_settings.root),
                title=request.title,
                profile_id=request.profile_id,
                model_routing=request.model_routing,
                storage_config=request.storage_config,
                agent_defaults=request.agent_defaults,
                validation=request.validation,
                status=request.status,
                workspace_path=request.workspace_path,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
