from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.longform_recap import evaluate_recap_trigger, list_longform_recap_reports, run_longform_recap
from novel_forge.storage.local import LocalStorage


def create_router(ctx: ProductRouterContext) -> APIRouter:
    router = APIRouter(tags=["product-longform-recap"])
    app_settings = ctx.app_settings

    @router.get("/product/longform-recap/reports")
    def recap_reports(project_id: str | None = None, limit: int = Query(default=100, ge=1, le=500)) -> list[dict[str, Any]]:
        return list_longform_recap_reports(LocalStorage(app_settings.root), project_id=project_id, limit=limit)

    @router.post("/product/longform-recap/trigger")
    async def recap_trigger(request: Request) -> dict[str, Any]:
        payload = await request.json()
        return evaluate_recap_trigger(
            LocalStorage(app_settings.root),
            project_id=str(payload.get("project_id") or "local-system"),
            workspace_path=str(payload.get("workspace_path") or ""),
            chapter_count=payload.get("chapter_count") if isinstance(payload.get("chapter_count"), int) else None,
            volume_end=bool(payload.get("volume_end")),
            major_setting_change=bool(payload.get("major_setting_change")),
            blocking_issue_threshold=int(payload.get("blocking_issue_threshold", 3) or 3),
        )

    @router.post("/product/longform-recap/run")
    async def recap_run(request: Request) -> dict[str, Any]:
        return run_longform_recap(LocalStorage(app_settings.root), await request.json())

    return router
