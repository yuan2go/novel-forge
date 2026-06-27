from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.metrics import create_project_metric_snapshot, list_project_metric_snapshots
from novel_forge.storage.local import LocalStorage


def create_router(ctx: ProductRouterContext) -> APIRouter:
    app_settings = ctx.app_settings
    models = ctx.models
    globals().update(models)
    router = APIRouter(tags=["product-metrics"])
    ProjectMetricSnapshotRequest = models["ProjectMetricSnapshotRequest"]

    @router.get("/product/metrics/snapshots")
    def metric_snapshots(project_id: str | None = None, limit: int = Query(default=100, ge=1, le=500)) -> list[dict[str, Any]]:
        try:
            return list_project_metric_snapshots(LocalStorage(app_settings.root), project_id=project_id, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/metrics/snapshot")
    def metric_snapshot_endpoint(request: ProjectMetricSnapshotRequest) -> dict[str, Any]:
        try:
            return create_project_metric_snapshot(
                LocalStorage(app_settings.root),
                project_id=request.project_id,
                workspace_path=request.workspace_path,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
