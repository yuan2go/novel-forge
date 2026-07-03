from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.editor_chief import build_editor_chief_snapshot
from novel_forge.storage.local import LocalStorage


def create_router(ctx: ProductRouterContext) -> APIRouter:
    app_settings = ctx.app_settings
    router = APIRouter(tags=["product-editor-chief"])

    @router.get("/product/editor-chief/snapshot")
    def editor_chief_snapshot(
        project_id: str | None = None,
        workspace_path: str | None = None,
        limit: int = Query(default=500, ge=50, le=2000),
    ) -> dict[str, Any]:
        try:
            return build_editor_chief_snapshot(
                LocalStorage(app_settings.root),
                project_id=project_id,
                workspace_path=workspace_path,
                limit=limit,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
