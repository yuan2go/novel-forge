from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.manuscript_workbench import build_manuscript_workbench
from novel_forge.storage.local import LocalStorage


def create_router(ctx: ProductRouterContext) -> APIRouter:
    app_settings = ctx.app_settings
    router = APIRouter(tags=["product-manuscript"])

    @router.get("/product/manuscript/workbench")
    def manuscript_workbench(
        project_id: str | None = None,
        draft_path: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        try:
            return build_manuscript_workbench(
                LocalStorage(app_settings.root),
                project_id=project_id,
                draft_path=draft_path,
                limit=limit,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
