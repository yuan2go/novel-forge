from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.audit_log import (
    build_audit_trail,
    create_audit_export_package,
    create_audit_trail_report,
    list_audit_events,
    record_audit_event,
)
from novel_forge.storage.local import LocalStorage


def create_router(ctx: ProductRouterContext) -> APIRouter:
    app_settings = ctx.app_settings
    router = APIRouter(prefix="/product/audit-log", tags=["product-audit-log"])

    @router.get("/events")
    def events(project_id: str | None = None, trace_id: str | None = None, event_type: str | None = None, limit: int = Query(default=200, ge=1, le=2000)) -> list[dict[str, Any]]:
        try:
            return list_audit_events(LocalStorage(app_settings.root), project_id=project_id, trace_id=trace_id, event_type=event_type, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/record")
    def record(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return record_audit_event(LocalStorage(app_settings.root), **payload)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/trail")
    def trail(project_id: str | None = None, trace_id: str | None = None, limit: int = Query(default=500, ge=1, le=5000)) -> dict[str, Any]:
        try:
            return build_audit_trail(LocalStorage(app_settings.root), project_id=project_id or "", trace_id=trace_id or "", limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/trail-report")
    def trail_report(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return create_audit_trail_report(
                LocalStorage(app_settings.root),
                project_id=str(payload.get("project_id") or ""),
                trace_id=str(payload.get("trace_id") or ""),
                limit=int(payload.get("limit", 500) or 500),
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/export-package")
    def export_package(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        try:
            return create_audit_export_package(
                LocalStorage(app_settings.root),
                project_id=str(payload.get("project_id") or ""),
                trace_id=str(payload.get("trace_id") or ""),
                limit=int(payload.get("limit", 500) or 500),
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
