"""PostgreSQL-only command and strong-query entrypoints for one chapter."""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query

from novel_forge.api.authority_dependencies import (
    authority_release_identity,
    build_chapter_authority_application,
    build_chapter_authority_query,
    build_production_preparation_service,
    build_trusted_principal_resolver,
)
from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.chapter_authority.orchestrator import SingleChapterRequest
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_runtime import (
    cancel_operation_external_effects,
)
from novel_forge.modules.command_kernel.cancellation import CancelCommand, request_cancellation
from novel_forge.modules.production_preparation import ProductionPreparationRequest
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


def create_router(ctx: ProductRouterContext) -> APIRouter:
    globals().update(ctx.models)
    AuthorityChapterRunRequest = ctx.models["AuthorityChapterRunRequest"]
    AuthorityChapterCommandRequest = ctx.models["AuthorityChapterCommandRequest"]
    AuthorityOperationControlRequest = ctx.models["AuthorityOperationControlRequest"]
    router = APIRouter(
        prefix="/product/production/chapter-authority",
        tags=["product-chapter-authority"],
    )

    @router.post("/commands", status_code=202)
    def admit_authoritative_chapter(
        request: AuthorityChapterCommandRequest,
    ) -> dict[str, Any]:
        try:
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            principal.require("chapter.authority.execute", request.project_id)
            preparation = build_production_preparation_service(ctx.app_settings).prepare(
                ProductionPreparationRequest(
                    project_id=request.project_id,
                    workspace_id=request.workspace_id,
                    chapter=request.chapter,
                    idempotency_key=request.idempotency_key,
                    title_override=request.title_override,
                    premise_override=request.premise_override,
                    explicit_asset_version_overrides=dict(
                        request.explicit_asset_version_overrides
                    ),
                    requested_quality_profile=request.requested_quality_profile,
                    requested_platform_profile=request.requested_platform_profile,
                    operator_decision=dict(request.operator_decision),
                    context_token_budget=request.context_token_budget,
                )
            )
            if preparation.command is None:
                raise KernelError(
                    "PRODUCTION_PREPARATION_BLOCKED",
                    str(
                        {
                            "missing": preparation.report.missing_required_asset_types,
                            "blocked": preparation.report.blocked_assets,
                            "repair_actions": preparation.report.repair_actions,
                        }
                    ),
                )
            build_id, commit_sha = authority_release_identity()
            trace_id = request.trace_id.strip() or f"trace:{uuid4()}"
            correlation_id = request.correlation_id.strip() or f"correlation:{uuid4()}"
            command = preparation.command
            admission = _application(ctx).admit(
                SingleChapterRequest(
                    project_id=command.project_id,
                    workspace_id=command.workspace_id,
                    actor_id=principal.principal_id,
                    chapter=command.chapter,
                    title=command.title,
                    premise=command.premise,
                    trace_id=trace_id,
                    correlation_id=correlation_id,
                    application_build_id=build_id,
                    commit_sha=commit_sha,
                    context_candidates=command.context_candidates,
                    context_version_refs=command.context_version_refs,
                    context_token_budget=command.context_token_budget,
                    preparation_report=command.preparation_report,
                    idempotency_key=command.idempotency_key,
                ),
                principal=principal,
            )
            return {
                "root_operation_id": admission.root_operation_id,
                "saga_id": admission.saga_id,
                "status": admission.status,
                "replayed": admission.replayed,
                "query_url": (
                    "/product/production/chapter-authority/run"
                    f"?project_id={request.project_id}"
                    f"&root_operation_id={admission.root_operation_id}"
                ),
                "control_url": (
                    "/product/production/chapter-authority/operations/"
                    f"{admission.root_operation_id}"
                ),
                "preparation": {
                    "decision": preparation.report.decision,
                    "context_digest": preparation.report.context_digest,
                    "selected_asset_version_ids": list(
                        preparation.report.selected_asset_version_ids
                    ),
                },
            }
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KernelError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.post("/run")
    def run_authoritative_chapter(request: AuthorityChapterRunRequest) -> dict[str, Any]:
        try:
            application = _application(ctx)
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            principal.require("chapter.authority.execute", request.project_id)
            build_id, commit_sha = authority_release_identity()
            trace_id = request.trace_id.strip() or f"trace:{uuid4()}"
            correlation_id = request.correlation_id.strip() or f"correlation:{uuid4()}"
            result = application.run(
                SingleChapterRequest(
                    project_id=request.project_id,
                    workspace_id=request.workspace_id,
                    actor_id=principal.principal_id,
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
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
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
            principal = build_trusted_principal_resolver().resolve_api_principal()
            principal.require("chapter.authority.query", project_id)
            query = _query(ctx)
            return query.list_runs(project_id=project_id, limit=limit)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.post("/operations/{root_operation_id}/cancel", status_code=202)
    def cancel_authoritative_chapter(
        root_operation_id: str,
        request: AuthorityOperationControlRequest,
    ) -> dict[str, Any]:
        try:
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            principal.require("chapter.authority.cancel", request.project_id)
            with AuthorityUnitOfWork(_application(ctx).database_url) as uow:
                state = uow.repositories.attempt_runtime.operation_state(
                    root_operation_id, request.project_id
                )
            trace_id = request.trace_id.strip() or f"trace:{uuid4()}"
            correlation_id = request.correlation_id.strip() or f"correlation:{uuid4()}"
            result = request_cancellation(
                _application(ctx).database_url,
                CancelCommand(
                    operation_id=root_operation_id,
                    project_id=request.project_id,
                    actor_id=principal.principal_id,
                    reason=request.reason,
                    expected_version=int(state["version"]),
                    idempotency_key=request.idempotency_key,
                    trace_id=trace_id,
                    correlation_id=correlation_id,
                ),
            )
            effect_results = cancel_operation_external_effects(
                _application(ctx).database_url,
                root_operation_id=root_operation_id,
                project_id=request.project_id,
                actor_id=principal.principal_id,
                trace_id=trace_id,
                correlation_id=correlation_id,
                adapters=_application(ctx).external_effect_adapters,
            )
            return {
                **result,
                "status": "CANCELLATION_REQUESTED",
                "external_effect_cancellations": list(effect_results),
            }
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KernelError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.get("/run")
    def authoritative_chapter_detail(
        project_id: str = Query(..., min_length=1),
        root_operation_id: str = Query(..., min_length=1),
    ) -> dict[str, Any]:
        try:
            principal = build_trusted_principal_resolver().resolve_api_principal()
            principal.require("chapter.authority.query", project_id)
            query = _query(ctx)
            return query.require_run(
                project_id=project_id,
                root_operation_id=root_operation_id,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
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
