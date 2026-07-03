from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.provider_fallback import approve_provider_fallback, preview_provider_fallback, resolve_provider_fallback
from novel_forge.storage.local import LocalStorage


def create_router(ctx: ProductRouterContext) -> APIRouter:
    router = APIRouter(tags=["product-provider-fallback"])
    app_settings = ctx.app_settings

    @router.post("/product/provider-fallback/preview")
    async def provider_fallback_preview(request: Request) -> dict[str, Any]:
        return preview_provider_fallback(LocalStorage(app_settings.root), await request.json())

    @router.post("/product/provider-fallback/approve")
    async def provider_fallback_approve(request: Request) -> dict[str, Any]:
        return approve_provider_fallback(LocalStorage(app_settings.root), await request.json())

    @router.post("/product/provider-fallback/resolve")
    async def provider_fallback_resolve(request: Request) -> dict[str, Any]:
        return resolve_provider_fallback(LocalStorage(app_settings.root), await request.json())

    return router
