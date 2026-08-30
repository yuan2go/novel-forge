from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from novel_forge.api.authority_dependencies import build_trusted_principal_resolver
from novel_forge.api.routers.context import ProductRouterContext


def create_router(ctx: ProductRouterContext) -> APIRouter:
    router = APIRouter(
        prefix="/product/content-intelligence",
        tags=["product-content-intelligence"],
    )
    service = ctx.services.pacing_analysis_service

    def authorize(project_id: str) -> None:
        principal = build_trusted_principal_resolver().resolve_api_principal()
        principal.require("content.authority.query", project_id)

    @router.get("/pacing")
    def pacing(
        project_id: str,
        chapter: int = Query(ge=1),
    ) -> dict[str, object]:
        try:
            authorize(project_id)
            return service.aggregate_at(project_id=project_id, chapter=chapter)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @router.get("/hooks")
    def hooks(
        project_id: str,
        chapter: int = Query(ge=1),
    ) -> dict[str, object]:
        try:
            authorize(project_id)
            return service.hook_analyses_at(project_id=project_id, chapter=chapter)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    return router


__all__ = ["create_router"]
