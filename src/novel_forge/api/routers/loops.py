from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.loop_kernel import cancel_loop_run, get_loop_run, list_loop_runs
from novel_forge.modules.production_kernel import dispatch_production_operation
from novel_forge.storage.local import LocalStorage


def create_router(ctx: ProductRouterContext) -> APIRouter:
    router = APIRouter(tags=["product-loops"])
    app_settings = ctx.app_settings

    @router.get("/product/loops")
    def loop_runs(
        project_id: str | None = None,
        status: str | None = None,
        loop_type: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return list_loop_runs(LocalStorage(app_settings.root), project_id=project_id, status=status, loop_type=loop_type, limit=limit)

    @router.get("/product/loops/{loop_ref:path}")
    def loop_run_detail(loop_ref: str) -> dict[str, Any]:
        return get_loop_run(LocalStorage(app_settings.root), loop_ref)

    @router.post("/product/loops/run")
    async def run_loop_endpoint(request: Request) -> dict[str, Any]:
        return dispatch_production_operation(LocalStorage(app_settings.root), "loop.run", **(await request.json()))

    @router.post("/product/loops/cancel")
    async def cancel_loop_endpoint(request: Request) -> dict[str, Any]:
        payload = await request.json()
        return cancel_loop_run(LocalStorage(app_settings.root), payload.get("loop_ref") or payload.get("loop_run_path") or payload.get("loop_run_id"), reason=str(payload.get("reason") or ""))

    return router
