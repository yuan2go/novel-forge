from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.continuity_graph import build_continuity_graph, create_chapter_continuity_report, create_continuity_graph_snapshot
from novel_forge.storage.local import LocalStorage


def create_router(ctx: ProductRouterContext) -> APIRouter:
    app_settings = ctx.app_settings
    models = ctx.models
    globals().update(models)
    router = APIRouter(tags=["product-continuity"])
    ContinuityGraphSnapshotRequest = models["ContinuityGraphSnapshotRequest"]
    ChapterContinuityReportRequest = models["ChapterContinuityReportRequest"]

    @router.get("/product/continuity/graph")
    def continuity_graph(
        project_id: str | None = None,
        workspace_path: str | None = None,
        limit: int = Query(default=500, ge=1, le=2000),
    ) -> dict[str, Any]:
        try:
            return build_continuity_graph(
                LocalStorage(app_settings.root),
                project_id=project_id,
                workspace_path=workspace_path,
                limit=limit,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/continuity/graph-snapshot")
    def continuity_graph_snapshot(request: ContinuityGraphSnapshotRequest) -> dict[str, Any]:
        try:
            return create_continuity_graph_snapshot(
                LocalStorage(app_settings.root),
                project_id=request.project_id,
                workspace_path=request.workspace_path,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/continuity/chapter-report")
    def chapter_continuity_report(request: ChapterContinuityReportRequest) -> dict[str, Any]:
        try:
            return create_chapter_continuity_report(
                LocalStorage(app_settings.root),
                request.draft_path,
                workspace_path=request.workspace_path,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
