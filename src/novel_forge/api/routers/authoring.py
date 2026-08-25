"""Query-only authoring workbench over PostgreSQL authority evidence."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from novel_forge.api.authority_dependencies import build_trusted_principal_resolver
from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.command_kernel.errors import KernelError


def create_router(ctx: ProductRouterContext) -> APIRouter:
    router = APIRouter(prefix="/product/authoring", tags=["product-authoring"])

    @router.get("/books/{book_id}/recent-trail")
    def recent_trail(
        book_id: str,
        project_id: str = Query(..., min_length=1),
        through_chapter: int = Query(..., ge=1),
        limit: int = Query(default=8, ge=1, le=50),
    ) -> dict[str, Any]:
        return _read(
            ctx,
            project_id,
            lambda: ctx.services.authoring_query.recent_trail(
                project_id=project_id,
                book_id=book_id,
                through_chapter=through_chapter,
                limit=limit,
            ),
        )

    @router.get("/books/{book_id}/hook-debt")
    def hook_debt(
        book_id: str,
        project_id: str = Query(..., min_length=1),
        through_chapter: int = Query(..., ge=1),
    ) -> dict[str, Any]:
        return _read(
            ctx,
            project_id,
            lambda: ctx.services.authoring_query.hook_debt(
                project_id=project_id,
                book_id=book_id,
                through_chapter=through_chapter,
            ),
        )

    @router.get("/chapters/{root_operation_id}/workspace")
    def chapter_workspace(
        root_operation_id: str,
        project_id: str = Query(..., min_length=1),
    ) -> dict[str, Any]:
        return _read(
            ctx,
            project_id,
            lambda: ctx.services.authoring_query.chapter_transaction_workspace(
                project_id=project_id,
                root_operation_id=root_operation_id,
            ),
        )

    return router


def _read(ctx: ProductRouterContext, project_id: str, query: Any) -> dict[str, Any]:
    try:
        principal = build_trusted_principal_resolver().resolve_api_principal()
        principal.require("chapter.authority.query", project_id)
        if ctx.services.authoring_query is None:
            raise RuntimeError("PostgreSQL Authoring query is not composed")
        return dict(query())
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except KernelError as exc:
        status_code = 404 if exc.code.endswith("MISSING") else 409
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


__all__ = ["create_router"]
