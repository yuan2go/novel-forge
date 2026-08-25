"""PostgreSQL-only Book Authority command and reconciliation entrypoints."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from novel_forge.api.authority_dependencies import build_trusted_principal_resolver
from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.book_authority.production import (
    StartBookProductionCommand,
    SubmitBookChapterCommand,
)
from novel_forge.modules.book_authority.input_resolver import (
    ResolveBookProductionInputCommand,
)
from novel_forge.modules.book_design_authority import (
    FormationLayerInput,
    StartStoryFormationCommand,
    StoryFormationInput,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_preparation import PostgresProductionAssetResolver


def create_router(ctx: ProductRouterContext) -> APIRouter:
    globals().update(ctx.models)
    BookAuthorityStartRequest = ctx.models["BookAuthorityStartRequest"]
    BookProductionInputResolveRequest = ctx.models["BookProductionInputResolveRequest"]
    StoryFormationStartRequest = ctx.models["StoryFormationStartRequest"]
    StoryFormationControlRequest = ctx.models["StoryFormationControlRequest"]
    StoryFormationBookDesignApprovalRequest = ctx.models[
        "StoryFormationBookDesignApprovalRequest"
    ]
    BookAuthorityChapterRequest = ctx.models["BookAuthorityChapterRequest"]
    BookAuthorityControlRequest = ctx.models["BookAuthorityControlRequest"]
    BookReplanApprovalRequest = ctx.models["BookReplanApprovalRequest"]
    BookReplanReevaluationRequest = ctx.models["BookReplanReevaluationRequest"]
    router = APIRouter(
        prefix="/product/production/book-authority",
        tags=["product-book-authority"],
    )

    @router.post("/books/{book_id}/formation-runs", status_code=202)
    def start_story_formation(
        book_id: str, request: StoryFormationStartRequest
    ) -> dict[str, Any]:
        try:
            composition = _composition(ctx)
            if composition.formation is None:
                raise KernelError(
                    "STORY_FORMATION_RUNTIME_NOT_CONFIGURED",
                    "Story Formation is unavailable in this partial composition",
                )
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            frozen = StoryFormationInput(
                layers=tuple(
                    FormationLayerInput.from_mapping(layer.model_dump())
                    for layer in request.layers
                ),
                book_design_asset_version_id=request.book_design_asset_version_id,
                book_design_content_hash=request.book_design_content_hash,
            )
            admission = composition.formation.admit(
                StartStoryFormationCommand(
                    project_id=request.project_id,
                    workspace_id=request.workspace_id,
                    book_id=book_id,
                    actor_id=principal.principal_id,
                    expected_book_version=request.expected_book_version,
                    stable_idempotency_key=request.idempotency_key,
                    trace_id=request.trace_id or f"trace:{uuid4()}",
                    correlation_id=request.correlation_id
                    or f"correlation:{uuid4()}",
                    frozen_input=frozen,
                ),
                principal=principal,
            )
            return {
                "formation_run_id": admission.formation_run_id,
                "root_operation_id": admission.root_operation_id,
                "runtime_job_id": admission.runtime_job_id,
                "lifecycle": admission.lifecycle,
                "replayed": admission.replayed,
            }
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.get("/formation-runs/{formation_run_id}")
    def story_formation_detail(formation_run_id: str) -> dict[str, Any]:
        try:
            composition = _composition(ctx)
            if composition.formation is None:
                raise KernelError(
                    "STORY_FORMATION_RUNTIME_NOT_CONFIGURED",
                    "Story Formation is unavailable",
                )
            result = composition.formation.require(formation_run_id)
            principal = build_trusted_principal_resolver().resolve_api_principal()
            principal.require("book.authority.query", str(result["project_id"]))
            return result
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/formation-runs/{formation_run_id}/resume", status_code=202)
    def resume_story_formation(
        formation_run_id: str, request: StoryFormationControlRequest
    ) -> dict[str, Any]:
        try:
            composition = _composition(ctx)
            if composition.formation is None:
                raise KernelError(
                    "STORY_FORMATION_RUNTIME_NOT_CONFIGURED",
                    "Story Formation is unavailable",
                )
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            return composition.formation.resume(
                formation_run_id,
                expected_version=request.expected_version,
                principal=principal,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post(
        "/formation-runs/{formation_run_id}/approve-book-design",
        status_code=202,
    )
    def approve_story_formation_book_design(
        formation_run_id: str,
        request: StoryFormationBookDesignApprovalRequest,
    ) -> dict[str, Any]:
        try:
            composition = _composition(ctx)
            if composition.formation is None:
                raise KernelError(
                    "STORY_FORMATION_RUNTIME_NOT_CONFIGURED",
                    "Story Formation is unavailable",
                )
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            return composition.formation.approve_book_design(
                formation_run_id,
                expected_version=request.expected_version,
                asset_version_id=request.book_design_asset_version_id,
                content_hash=request.book_design_content_hash,
                principal=principal,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/formation-runs/{formation_run_id}/abort")
    def abort_story_formation(
        formation_run_id: str, request: StoryFormationControlRequest
    ) -> dict[str, Any]:
        try:
            composition = _composition(ctx)
            if composition.formation is None:
                raise KernelError(
                    "STORY_FORMATION_RUNTIME_NOT_CONFIGURED",
                    "Story Formation is unavailable",
                )
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            return composition.formation.abort(
                formation_run_id,
                expected_version=request.expected_version,
                principal=principal,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/books/{book_id}/production-inputs/resolve")
    def resolve_production_inputs(
        book_id: str, request: BookProductionInputResolveRequest
    ) -> dict[str, Any]:
        try:
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            snapshot = _composition(ctx).input_resolver.resolve(
                ResolveBookProductionInputCommand(
                    project_id=request.project_id,
                    workspace_id=request.workspace_id,
                    book_id=book_id,
                    production_profile=request.production_profile,
                    expected_book_version=request.expected_book_version,
                    narrative_chapter_cursor=request.narrative_chapter_cursor,
                    actor_id=principal.principal_id,
                    idempotency_key=request.idempotency_key,
                    trace_id=request.trace_id or f"trace:{uuid4()}",
                    correlation_id=request.correlation_id or f"correlation:{uuid4()}",
                ),
                principal=principal,
            )
            return snapshot.to_dict()
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/commands", status_code=202)
    def start_book(request: BookAuthorityStartRequest) -> dict[str, Any]:
        try:
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            book_design_version = request.book_design_version
            book_plan_version = request.book_plan_version
            production_profile_version = request.production_profile_version
            longform_context_versions = dict(request.longform_context_versions)
            if request.input_mode == "RESOLVED_AUTHORITY_INPUT":
                snapshot = _composition(ctx).input_resolver.require(
                    request.input_snapshot_id
                )
                if (snapshot.project_id, snapshot.workspace_id, snapshot.book_id) != (
                    request.project_id,
                    request.workspace_id,
                    request.book_id,
                ):
                    raise KernelError(
                        "BOOK_PRODUCTION_INPUT_SNAPSHOT_SCOPE_INVALID",
                        "resolved input snapshot belongs to another Book scope",
                    )
                book_design_version = snapshot.book_design_version
                book_plan_version = snapshot.book_plan_version
                production_profile_version = snapshot.production_profile_version
                longform_context_versions = {
                    "volume_plan_version": snapshot.current_volume_plan_version,
                    "arc_plan_versions": list(
                        snapshot.current_relevant_arc_plan_versions
                    ),
                    "character_state_version": snapshot.character_state_version,
                    "foreshadowing_state_version": snapshot.foreshadowing_state_version,
                    "quality_trend_version": snapshot.quality_trend_version,
                    "reward_ledger_version": snapshot.reward_ledger_version,
                    "promise_ledger_version": snapshot.promise_ledger_version,
                    "reader_segment_version": snapshot.reader_segment_version,
                    "reader_contract_version": snapshot.reader_contract_version,
                    "platform_profile_version": snapshot.platform_profile_version,
                }
            admission = _application(ctx).start(
                StartBookProductionCommand(
                    project_id=request.project_id,
                    workspace_id=request.workspace_id,
                    book_id=request.book_id,
                    actor_id=principal.principal_id,
                    trace_id=request.trace_id or f"trace:{uuid4()}",
                    correlation_id=request.correlation_id or f"correlation:{uuid4()}",
                    stable_idempotency_key=request.idempotency_key,
                    book_design_version=book_design_version,
                    book_plan_version=book_plan_version,
                    production_profile_version=production_profile_version,
                    longform_context_versions=longform_context_versions,
                    target_chapter_count=request.target_chapter_count,
                    light_recap_cadence=request.light_recap_cadence,
                    formal_recap_cadence=request.formal_recap_cadence,
                    input_snapshot_id=request.input_snapshot_id,
                    input_mode=request.input_mode,
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
                    if item.asset_version_id == request.chapter_plan_asset_version_id
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
                    "estimated_tokens": int(item.content.get("estimated_tokens") or 1),
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

    @router.post("/chapter-requests/{chapter_request_id}/accept")
    def accept_chapter(chapter_request_id: str) -> dict[str, Any]:
        try:
            request = _application(ctx).require_chapter_request(chapter_request_id)
            principal = build_trusted_principal_resolver().resolve_api_principal()
            principal.require("book.authority.execute", request["project_id"])
            return _application(ctx).accept_chapter(
                chapter_request_id, principal=principal
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/chapter-requests/{chapter_request_id}/recover")
    def recover_chapter(chapter_request_id: str) -> dict[str, Any]:
        try:
            request = _application(ctx).require_chapter_request(chapter_request_id)
            principal = build_trusted_principal_resolver().resolve_api_principal()
            principal.require("book.authority.execute", request["project_id"])
            return _application(ctx).recover_chapter_submission(
                chapter_request_id, principal=principal
            )
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
            tick = _composition(ctx).tick(book_run_id)
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

    @router.get("/runs/{book_run_id}/progress")
    def book_progress(book_run_id: str) -> dict[str, Any]:
        try:
            book = _application(ctx).require(book_run_id)
            principal = build_trusted_principal_resolver().resolve_api_principal()
            principal.require("book.authority.query", book["project_id"])
            return _composition(ctx).query.progress(
                book_run_id=book_run_id
            ).to_dict()
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.get("/runs/{book_run_id}/corrective-actions")
    def corrective_actions(
        book_run_id: str,
        status: str = "",
        issue_type: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        try:
            book = _application(ctx).require(book_run_id)
            principal = build_trusted_principal_resolver().resolve_api_principal()
            principal.require("book.authority.query", book["project_id"])
            return _composition(ctx).corrective_actions.list(
                project_id=str(book["project_id"]),
                status=status,
                issue_type=issue_type,
                limit=limit,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/runs/{book_run_id}/replans/{replan_id}/approve")
    def approve_replan(
        book_run_id: str,
        replan_id: str,
        request: BookReplanApprovalRequest,
    ) -> dict[str, Any]:
        try:
            book = _application(ctx).require(book_run_id)
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            principal.require("book.authority.approve_replan", book["project_id"])
            return _composition(ctx).approve_replan(
                book_run_id=book_run_id,
                replan_id=replan_id,
                authority_type=request.authority_type,
                authority_version=request.authority_version,
                evidence=dict(request.evidence),
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @router.post("/runs/{book_run_id}/replans/{replan_id}/reevaluate")
    def reevaluate_replan(
        book_run_id: str,
        replan_id: str,
        request: BookReplanReevaluationRequest,
    ) -> dict[str, Any]:
        try:
            book = _application(ctx).require(book_run_id)
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            principal.require("book.authority.execute", book["project_id"])
            return _composition(ctx).reevaluate_replan(
                book_run_id=book_run_id,
                replan_id=replan_id,
                source_recap_asset_version_id=(request.source_recap_asset_version_id),
                deviation_report_asset_version_id=(
                    request.deviation_report_asset_version_id
                ),
                idempotency_key=request.idempotency_key,
                trace_id=request.trace_id or f"trace:{uuid4()}",
                correlation_id=request.correlation_id or f"correlation:{uuid4()}",
            )
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

    @router.post("/runs/{book_run_id}/cancel")
    def cancel_book(
        book_run_id: str, request: BookAuthorityControlRequest
    ) -> dict[str, Any]:
        try:
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            return _application(ctx).cancel(
                book_run_id, reason=request.reason, principal=principal
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KernelError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    return router


def _application(ctx: ProductRouterContext):
    return _composition(ctx).authority


def _composition(ctx: ProductRouterContext):
    return ctx.services.book_production


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, KernelError):
        return HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": exc.message},
        )
    return HTTPException(status_code=503, detail=str(exc))


__all__ = ["create_router"]
