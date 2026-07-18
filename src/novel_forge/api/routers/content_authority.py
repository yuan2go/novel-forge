"""PostgreSQL-only command/query surface for Content Authority Operations."""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query

from novel_forge.api.authority_dependencies import (
    build_content_authority_application,
    build_content_authority_query,
    build_trusted_principal_resolver,
)
from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.command_kernel.cancellation import CancelCommand, request_cancellation
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.content_authority import ContentOperationRequest
from novel_forge.modules.production_preparation import PostgresProductionAssetResolver
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


def create_router(ctx: ProductRouterContext) -> APIRouter:
    globals().update(ctx.models)
    ContentAuthorityCommandRequest = ctx.models["ContentAuthorityCommandRequest"]
    AuthorityOperationControlRequest = ctx.models["AuthorityOperationControlRequest"]
    router = APIRouter(prefix="/product/content-authority", tags=["product-content-authority"])

    @router.post("/commands", status_code=202)
    def admit_content_operation(request: ContentAuthorityCommandRequest) -> dict[str, Any]:
        try:
            principal = build_trusted_principal_resolver().resolve_api_principal(
                claimed_actor_id=request.actor_id
            )
            principal.require("content.authority.execute", request.project_id)
            resolver = PostgresProductionAssetResolver(_application(ctx).database_url)
            inputs = tuple(
                {
                    "asset_version_id": resolved.asset_version_id,
                    "content_hash": resolved.content_hash,
                }
                for resolved in (
                    resolver.resolve_override(
                        project_id=request.project_id,
                        asset_version_id=asset_version_id,
                    )
                    for asset_version_id in request.input_asset_version_ids
                )
            )
            trace_id = request.trace_id.strip() or f"trace:{uuid4()}"
            correlation_id = request.correlation_id.strip() or f"correlation:{uuid4()}"
            result = _application(ctx).admit(
                ContentOperationRequest(
                    definition_name=request.definition_name,
                    project_id=request.project_id,
                    workspace_id=request.workspace_id,
                    actor_id=principal.principal_id,
                    trace_id=trace_id,
                    correlation_id=correlation_id,
                    idempotency_key=request.idempotency_key,
                    payload=dict(request.payload),
                    input_assets=inputs,
                    approval=dict(request.approval) if request.approval is not None else None,
                ),
                principal=principal,
            )
            base = f"/product/content-authority/operations/{result.operation_id}"
            return {
                "operation_id": result.operation_id,
                "project_id": result.project_id,
                "status": "READY",
                "replayed": result.replayed,
                "query_url": f"{base}?project_id={request.project_id}",
                "control_url": base,
            }
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KernelError as exc:
            raise HTTPException(status_code=409, detail={"code": exc.code, "message": exc.message}) from exc
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.get("/operations")
    def list_operations(
        project_id: str = Query(..., min_length=1),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        principal = build_trusted_principal_resolver().resolve_api_principal()
        principal.require("content.authority.query", project_id)
        return _query(ctx).list_operations(project_id=project_id, limit=limit)

    @router.get("/operations/{operation_id}")
    def operation_detail(operation_id: str, project_id: str = Query(..., min_length=1)) -> dict[str, Any]:
        principal = build_trusted_principal_resolver().resolve_api_principal()
        principal.require("content.authority.query", project_id)
        return _query(ctx).require_operation(project_id=project_id, operation_id=operation_id)

    @router.post("/operations/{operation_id}/cancel", status_code=202)
    def cancel_operation(
        operation_id: str, request: AuthorityOperationControlRequest
    ) -> dict[str, Any]:
        principal = build_trusted_principal_resolver().resolve_api_principal(
            claimed_actor_id=request.actor_id
        )
        principal.require("content.authority.cancel", request.project_id)
        with AuthorityUnitOfWork(_application(ctx).database_url) as uow:
            state = uow.repositories.attempt_runtime.operation_state(operation_id, request.project_id)
        result = request_cancellation(
            _application(ctx).database_url,
            CancelCommand(
                operation_id=operation_id,
                project_id=request.project_id,
                actor_id=principal.principal_id,
                reason=request.reason,
                expected_version=int(state["version"]),
                idempotency_key=request.idempotency_key,
                trace_id=request.trace_id.strip() or f"trace:{uuid4()}",
                correlation_id=request.correlation_id.strip() or f"correlation:{uuid4()}",
            ),
        )
        return {**result, "status": "CANCELLATION_REQUESTED"}

    @router.post("/operations/{operation_id}/recover", status_code=202)
    def recover_operation(
        operation_id: str, request: AuthorityOperationControlRequest
    ) -> dict[str, Any]:
        principal = build_trusted_principal_resolver().resolve_api_principal(
            claimed_actor_id=request.actor_id
        )
        principal.require("content.authority.recover", request.project_id)
        detail = _query(ctx).require_operation(
            project_id=request.project_id, operation_id=operation_id
        )
        if detail["status"] not in {"READY", "FAILED_RETRYABLE", "EXECUTING", "SUCCEEDED"}:
            raise HTTPException(status_code=409, detail="operation is not recoverable")
        return {
            "operation_id": operation_id,
            "project_id": request.project_id,
            "status": detail["status"],
            "recovery": "WORKER_QUEUE_VISIBLE" if detail["status"] != "SUCCEEDED" else "ALREADY_COMPLETE",
        }

    return router


def _application(ctx: ProductRouterContext):
    application = getattr(ctx.services, "content_authority_application", None)
    return application or build_content_authority_application(ctx.app_settings)


def _query(ctx: ProductRouterContext):
    query = getattr(ctx.services, "content_authority_query", None)
    return query or build_content_authority_query(ctx.app_settings)


__all__ = ["create_router"]
