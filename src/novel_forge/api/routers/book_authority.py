"""PostgreSQL-only Book Authority command and reconciliation entrypoints."""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from novel_forge.api.authority_dependencies import (
    build_book_authority_application,
    build_trusted_principal_resolver,
)
from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.book_authority.production import (
    StartBookProductionCommand,
    SubmitBookChapterCommand,
)
from novel_forge.modules.book_authority.governed_scheduler import (
    PostgresBookAuthorityScheduler,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_preparation import PostgresProductionAssetResolver


def create_router(ctx: ProductRouterContext) -> APIRouter:
    BookAuthorityStartRequest = ctx.models["BookAuthorityStartRequest"]
    BookAuthorityChapterRequest = ctx.models["BookAuthorityChapterRequest"]
    BookAuthorityControlRequest = ctx.models["BookAuthorityControlRequest"]
    router = APIRouter(
        prefix="/product/production/book-authority",
        tags=["product-book-authority"],
    )

    @router.post("/commands", status_code=202)
    def start_book(request: BookAuthorityStartRequest) -> dict[str, Any]:
        try:
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            admission = _application(ctx).start(
                StartBookProductionCommand(
                    project_id=request.project_id,
                    workspace_id=request.workspace_id,
                    book_id=request.book_id,
                    actor_id=principal.principal_id,
                    trace_id=request.trace_id or f"trace:{uuid4()}",
                    correlation_id=request.correlation_id or f"correlation:{uuid4()}",
                    stable_idempotency_key=request.idempotency_key,
                    book_design_version=request.book_design_version,
                    book_plan_version=request.book_plan_version,
                    production_profile_version=request.production_profile_version,
                    longform_context_versions=dict(
                        request.longform_context_versions
                    ),
                    target_chapter_count=request.target_chapter_count,
                    light_recap_cadence=request.light_recap_cadence,
                    formal_recap_cadence=request.formal_recap_cadence,
                ),
                principal=principal,
            )
            return {
                "book_run_id": admission.book_run_id,
                "root_operation_id": admission.root_operation_id,
                "saga_id": admission.saga_id,
                "state": "READY",
                "replayed": admission.replayed,
            }
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/runs/{book_run_id}/chapters", status_code=202)
    def submit_chapter(
        book_run_id: str, request: BookAuthorityChapterRequest
    ) -> dict[str, Any]:
        try:
            authority = _application(ctx)
            book = authority.require(book_run_id)
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            resolver = PostgresProductionAssetResolver(authority.database_url)
            resolved = [
                resolver.resolve_override(
                    project_id=book["project_id"],
                    asset_version_id=asset_version_id,
                )
                for asset_version_id in request.context_asset_version_ids
            ]
            plan = next(
                (
                    item
                    for item in resolved
                    if item.asset_version_id
                    == request.chapter_plan_asset_version_id
                    and item.asset_type == "chapter_plan"
                ),
                None,
            )
            if plan is None:
                raise KernelError(
                    "CHAPTER_PLAN_AUTHORITY_INPUT_REQUIRED",
                    "context assets must contain the requested ChapterPlan version",
                )
            candidates = tuple(
                {
                    "asset_version_id": item.asset_version_id,
                    "asset_type": item.asset_type,
                    "project_id": item.project_id,
                    "content_hash": item.content_hash,
                    "content": item.content,
                    "safe_summary": str(item.content.get("safe_summary") or ""),
                    "structured_facts": list(
                        item.content.get("structured_facts") or []
                    ),
                    "estimated_tokens": int(
                        item.content.get("estimated_tokens") or 1
                    ),
                    "narrative_function": str(
                        item.content.get("narrative_function") or item.asset_type
                    ),
                }
                for item in resolved
            )
            return authority.submit_chapter(
                SubmitBookChapterCommand(
                    book_run_id=book_run_id,
                    chapter_number=request.chapter_number,
                    title=request.title,
                    premise=request.premise,
                    chapter_plan_asset_version_id=plan.asset_version_id,
                    chapter_plan_content_hash=plan.content_hash,
                    context_candidates=candidates,
                    context_version_refs=dict(request.context_version_refs),
                    context_token_budget=request.context_token_budget,
                    preparation_report=dict(request.preparation_report),
                ),
                principal=principal,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/chapter-requests/{chapter_request_id}/reconcile")
    def reconcile_chapter(chapter_request_id: str) -> dict[str, Any]:
        try:
            request = _application(ctx).require_chapter_request(chapter_request_id)
            principal = build_trusted_principal_resolver().resolve_api_principal()
            principal.require("book.authority.execute", request["project_id"])
            return _application(ctx).reconcile_chapter(chapter_request_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/runs/{book_run_id}/tick")
    def tick_book(book_run_id: str) -> dict[str, Any]:
        try:
            authority = _application(ctx)
            book = authority.require(book_run_id)
            principal = build_trusted_principal_resolver().resolve_api_principal()
            principal.require("book.authority.execute", book["project_id"])
            tick = PostgresBookAuthorityScheduler(
                authority, principal=principal
            ).tick(book_run_id)
            return {
                "book_run_id": tick.book_run_id,
                "previous_state": tick.previous_state,
                "state": tick.state,
                "action": tick.action,
                "operation_id": tick.operation_id,
            }
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.get("/runs/{book_run_id}")
    def book_detail(book_run_id: str) -> dict[str, Any]:
        try:
            result = _application(ctx).require(book_run_id)
            principal = build_trusted_principal_resolver().resolve_api_principal()
            principal.require("book.authority.query", result["project_id"])
            return result
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/runs/{book_run_id}/pause")
    def pause_book(
        book_run_id: str, request: BookAuthorityControlRequest
    ) -> dict[str, Any]:
        try:
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            return _application(ctx).pause(
                book_run_id, reason=request.reason, principal=principal
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/runs/{book_run_id}/resume")
    def resume_book(
        book_run_id: str, request: BookAuthorityControlRequest
    ) -> dict[str, Any]:
        try:
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            return _application(ctx).resume(
                book_run_id, reason=request.reason, principal=principal
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    return router


def _application(ctx: ProductRouterContext):
    application = getattr(ctx.services, "book_authority_application", None)
    return application or build_book_authority_application(ctx.app_settings)


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, KernelError):
        return HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": exc.message},
        )
    return HTTPException(status_code=503, detail=str(exc))


__all__ = ["create_router"]
