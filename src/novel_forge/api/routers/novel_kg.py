from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.novel_kg import build_novel_kg, create_novel_kg_snapshot, query_novel_kg
from novel_forge.storage.local import LocalStorage


def create_router(ctx: ProductRouterContext) -> APIRouter:
    app_settings = ctx.app_settings
    models = ctx.models
    globals().update(models)
    router = APIRouter(tags=["product-novel-kg"])
    NovelKGSnapshotRequest = models["NovelKGSnapshotRequest"]

    @router.get("/product/novel-kg/graph")
    def novel_kg_graph(
        project_id: str | None = None,
        workspace_path: str | None = None,
        limit: int = Query(default=1000, ge=1, le=5000),
        include_content_snapshot: bool = False,
    ) -> dict[str, Any]:
        try:
            return build_novel_kg(
                LocalStorage(app_settings.root),
                project_id=project_id,
                workspace_path=workspace_path,
                limit=limit,
                include_content_snapshot=include_content_snapshot,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/novel-kg/snapshot")
    def novel_kg_snapshot(request: NovelKGSnapshotRequest) -> dict[str, Any]:
        try:
            return create_novel_kg_snapshot(
                LocalStorage(app_settings.root),
                project_id=request.project_id,
                workspace_path=request.workspace_path,
                limit=request.limit,
                include_content_snapshot=request.include_content_snapshot,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/novel-kg/query")
    def novel_kg_query(
        snapshot_path: str | None = None,
        project_id: str | None = None,
        workspace_path: str | None = None,
        kind: str | None = None,
        entity_type: str | None = None,
        q: str | None = None,
        source_asset_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        try:
            return query_novel_kg(
                LocalStorage(app_settings.root),
                snapshot_path=snapshot_path,
                project_id=project_id,
                workspace_path=workspace_path,
                kind=kind,
                entity_type=entity_type,
                q=q,
                source_asset_id=source_asset_id,
                limit=limit,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
