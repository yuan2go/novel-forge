"""PostgreSQL-only command and strong-query entrypoints for one chapter."""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query

from novel_forge.api.authority_dependencies import (
    authority_release_identity,
    build_chapter_authority_application,
    build_chapter_authority_query,
)
from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.chapter_authority.orchestrator import SingleChapterRequest
from novel_forge.modules.command_kernel.errors import KernelError


def create_router(ctx: ProductRouterContext) -> APIRouter:
    globals().update(ctx.models)
    AuthorityChapterRunRequest = ctx.models["AuthorityChapterRunRequest"]
    router = APIRouter(
        prefix="/product/production/chapter-authority",
        tags=["product-chapter-authority"],
    )

    @router.post("/run")
    def run_authoritative_chapter(request: AuthorityChapterRunRequest) -> dict[str, Any]:
        try:
            application = _application(ctx)
            build_id, commit_sha = authority_release_identity()
            trace_id = request.trace_id.strip() or f"trace:{uuid4()}"
            correlation_id = request.correlation_id.strip() or f"correlation:{uuid4()}"
            result = application.run(
                SingleChapterRequest(
                    project_id=request.project_id,
                    workspace_id=request.workspace_id,
                    actor_id=request.actor_id,
                    chapter=request.chapter,
                    title=request.title,
                    premise=request.premise,
                    trace_id=trace_id,
                    correlation_id=correlation_id,
                    application_build_id=build_id,
                    commit_sha=commit_sha,
                )
            )
            return application.query.require_run(
                project_id=request.project_id,
                root_operation_id=result.root_operation_id,
            )
        except KernelError as exc:
            status_code = 404 if exc.code == "CHAPTER_RUN_NOT_FOUND" else 409
            raise HTTPException(
                status_code=status_code,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.get("/runs")
    def list_authoritative_chapters(
        project_id: str = Query(..., min_length=1),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        try:
            query = _query(ctx)
            return query.list_runs(project_id=project_id, limit=limit)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.get("/run")
    def authoritative_chapter_detail(
        project_id: str = Query(..., min_length=1),
        root_operation_id: str = Query(..., min_length=1),
    ) -> dict[str, Any]:
        try:
            query = _query(ctx)
            return query.require_run(
                project_id=project_id,
                root_operation_id=root_operation_id,
            )
        except KernelError as exc:
            status_code = 404 if exc.code == "CHAPTER_RUN_NOT_FOUND" else 409
            raise HTTPException(
                status_code=status_code,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    return router


def _application(ctx: ProductRouterContext):
    application = getattr(ctx.services, "chapter_application", None)
    return application or build_chapter_authority_application(ctx.app_settings)


def _query(ctx: ProductRouterContext):
    query = getattr(ctx.services, "chapter_query", None)
    return query or build_chapter_authority_query(ctx.app_settings)


__all__ = ["create_router"]
