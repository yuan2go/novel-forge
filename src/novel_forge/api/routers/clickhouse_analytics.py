from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.clickhouse_analytics import (
    agent_metrics,
    analytics_capabilities,
    analytics_dashboard_snapshot,
    clickhouse_schema_plan,
    clickhouse_online_e2e_smoke,
    cost_metrics,
    evaluation_metrics,
    feedback_metrics,
    migrate_clickhouse,
    quality_trends,
    sync_analytics,
)
from novel_forge.storage.local import LocalStorage


def create_router(ctx: ProductRouterContext) -> APIRouter:
    app_settings = ctx.app_settings
    router = APIRouter(prefix="/product/analytics", tags=["product-analytics"])

    @router.get("/capabilities")
    def capabilities(project_id: str | None = None) -> dict[str, Any]:
        try:
            return analytics_capabilities(LocalStorage(app_settings.root), project_id=project_id or "")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/schema-plan")
    def schema_plan(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return clickhouse_schema_plan(LocalStorage(app_settings.root), persist=bool(payload.get("persist", True)))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/migrate")
    def migrate(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return migrate_clickhouse(LocalStorage(app_settings.root), dry_run=bool(payload.get("dry_run", True)))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/online-smoke")
    def online_smoke(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return clickhouse_online_e2e_smoke(
                LocalStorage(app_settings.root),
                project_id=str(payload.get("project_id") or ""),
                require_online=not bool(payload.get("dry_run", True)),
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/sync")
    def sync(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return sync_analytics(
                LocalStorage(app_settings.root),
                project_id=str(payload.get("project_id") or ""),
                online=payload.get("online") if "online" in payload else None,
                limit=int(payload.get("limit", 2000) or 2000),
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/quality-trends")
    def quality(project_id: str | None = None) -> dict[str, Any]:
        try:
            return quality_trends(LocalStorage(app_settings.root), project_id=project_id or "")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/agent-metrics")
    def agents(project_id: str | None = None) -> dict[str, Any]:
        try:
            return agent_metrics(LocalStorage(app_settings.root), project_id=project_id or "")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/evaluation-metrics")
    def evaluation(project_id: str | None = None) -> dict[str, Any]:
        try:
            return evaluation_metrics(LocalStorage(app_settings.root), project_id=project_id or "")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/cost-metrics")
    def cost(project_id: str | None = None) -> dict[str, Any]:
        try:
            return cost_metrics(LocalStorage(app_settings.root), project_id=project_id or "")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/feedback-metrics")
    def feedback(project_id: str | None = None) -> dict[str, Any]:
        try:
            return feedback_metrics(LocalStorage(app_settings.root), project_id=project_id or "")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/dashboard-snapshot")
    def dashboard_snapshot(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return analytics_dashboard_snapshot(LocalStorage(app_settings.root), project_id=str(payload.get("project_id") or ""))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
