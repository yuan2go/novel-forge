from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.runtime_ledger import (
    create_cost_quality_dashboard,
    list_cost_ledgers,
    trace_timeline_payload,
)
from novel_forge.storage.local import LocalStorage


def create_router(ctx: ProductRouterContext) -> APIRouter:
    app_settings = ctx.app_settings
    models = ctx.models
    globals().update(models)
    router = APIRouter(tags=["product-runtime"])
    RuntimeCostSnapshotRequest = models["RuntimeCostSnapshotRequest"]

    @router.get("/product/runtime/trace-timeline")
    def runtime_trace_timeline(
        trace_id: str | None = None,
        project_id: str | None = None,
        limit: int = Query(default=300, ge=1, le=1000),
    ) -> dict[str, Any]:
        try:
            return trace_timeline_payload(LocalStorage(app_settings.root), trace_id=trace_id, project_id=project_id, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/runtime/cost-ledger")
    def runtime_cost_ledger(
        project_id: str | None = None,
        scope: str | None = None,
        source_type: str | None = None,
        limit: int = Query(default=500, ge=1, le=2000),
    ) -> list[dict[str, Any]]:
        try:
            return list_cost_ledgers(LocalStorage(app_settings.root), project_id=project_id, scope=scope, source_type=source_type, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/runtime/cost-dashboard")
    def runtime_cost_dashboard(
        project_id: str | None = None,
        workspace_path: str | None = None,
        chapter: int | None = None,
    ) -> dict[str, Any]:
        try:
            return create_cost_quality_dashboard(
                LocalStorage(app_settings.root),
                project_id=project_id,
                workspace_path=workspace_path,
                chapter=chapter,
                persist_snapshots=False,
                persist_dashboard=False,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/runtime/cost-snapshot")
    def runtime_cost_snapshot(request: RuntimeCostSnapshotRequest) -> dict[str, Any]:
        try:
            return create_cost_quality_dashboard(
                LocalStorage(app_settings.root),
                project_id=request.project_id,
                workspace_path=request.workspace_path,
                chapter=request.chapter,
                persist_snapshots=request.persist_snapshots,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
