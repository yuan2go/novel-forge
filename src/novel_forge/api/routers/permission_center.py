from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.permission_center import (
    create_human_approval_gate,
    create_permission_policy,
    evaluate_permission,
    list_permission_policies,
    permission_center_snapshot,
    resolve_human_approval_gate,
)
from novel_forge.storage.local import LocalStorage


def create_router(ctx: ProductRouterContext) -> APIRouter:
    app_settings = ctx.app_settings
    router = APIRouter(prefix="/product/permission-center", tags=["product-permission-center"])

    def storage() -> LocalStorage:
        return LocalStorage(app_settings.root)

    @router.get("/snapshot")
    def snapshot(project_id: str | None = None, limit: int = Query(default=300, ge=1, le=1000)) -> dict[str, Any]:
        try:
            return permission_center_snapshot(storage(), project_id=project_id or "", limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/policies")
    def policies(project_id: str | None = None, scope: str | None = None, limit: int = Query(default=300, ge=1, le=1000)) -> list[dict[str, Any]]:
        try:
            return list_permission_policies(storage(), project_id=project_id, scope=scope, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/policies")
    async def create_policy(request: Request) -> dict[str, Any]:
        try:
            return create_permission_policy(storage(), await request.json())
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/evaluate")
    async def evaluate(request: Request) -> dict[str, Any]:
        try:
            return evaluate_permission(storage(), await request.json())
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/human-gates")
    async def create_gate(request: Request) -> dict[str, Any]:
        try:
            return create_human_approval_gate(storage(), await request.json())
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/human-gates/{gate_id}/resolve")
    async def resolve_gate(gate_id: str, request: Request) -> dict[str, Any]:
        try:
            return resolve_human_approval_gate(storage(), gate_id, await request.json())
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
