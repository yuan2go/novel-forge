"""Trusted PostgreSQL Canon approval API."""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from novel_forge.api.authority_dependencies import build_trusted_principal_resolver
from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.canon_graph.approval_authority import (
    CanonApprovalContext,
    decide_canon_approval,
    list_canon_approvals,
    reopen_canon_approval,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


class CanonApprovalDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str = Field(min_length=1)
    expected_version: int = Field(ge=0)
    decision: str
    reason: str = Field(min_length=1)
    evidence: dict[str, Any] = Field(default_factory=dict)
    edited_payload: dict[str, Any] | None = None
    idempotency_key: str = Field(min_length=1)
    trace_id: str = ""
    correlation_id: str = ""


class CanonApprovalReopenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str = Field(min_length=1)
    expected_version: int = Field(ge=0)
    reason: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    trace_id: str = ""
    correlation_id: str = ""


def create_router(ctx: ProductRouterContext) -> APIRouter:
    router = APIRouter(prefix="/product/canon-authority", tags=["product-canon-authority"])

    @router.get("/approvals")
    def approvals(project_id: str) -> list[dict[str, Any]]:
        try:
            principal = build_trusted_principal_resolver().resolve_api_principal()
            principal.require("canon.authority.query", project_id)
            return list_canon_approvals(ctx.app_settings.database_url, project_id=project_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @router.get("/approvals/{approval_id}")
    def approval(approval_id: str, project_id: str) -> dict[str, Any]:
        try:
            principal = build_trusted_principal_resolver().resolve_api_principal()
            principal.require("canon.authority.query", project_id)
            rows = list_canon_approvals(ctx.app_settings.database_url, project_id=project_id, approval_request_id=approval_id)
            if not rows:
                raise HTTPException(status_code=404, detail="Canon approval not found")
            return rows[0]
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @router.post("/approvals/{approval_id}/decisions")
    def decide(approval_id: str, request: CanonApprovalDecisionRequest) -> dict[str, Any]:
        try:
            principal = build_trusted_principal_resolver().resolve_api_principal()
            principal.require("canon.authority.approve", request.project_id)
            return decide_canon_approval(
                ctx.app_settings.database_url,
                CanonApprovalContext(
                    project_id=request.project_id, principal_id=principal.principal_id,
                    trace_id=request.trace_id or f"trace:{uuid4()}",
                    correlation_id=request.correlation_id or f"correlation:{uuid4()}",
                ),
                approval_request_id=approval_id, expected_version=request.expected_version,
                decision=request.decision, reason=request.reason, evidence=dict(request.evidence),
                edited_payload=request.edited_payload, idempotency_key=request.idempotency_key,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KernelError as exc:
            raise HTTPException(status_code=409, detail={"code": exc.code, "message": exc.message}) from exc

    @router.post("/approvals/{approval_id}/reopen")
    def reopen(approval_id: str, request: CanonApprovalReopenRequest) -> dict[str, Any]:
        try:
            principal = build_trusted_principal_resolver().resolve_api_principal()
            principal.require("canon.authority.approve", request.project_id)
            return reopen_canon_approval(
                ctx.app_settings.database_url,
                CanonApprovalContext(
                    project_id=request.project_id,
                    principal_id=principal.principal_id,
                    trace_id=request.trace_id or f"trace:{uuid4()}",
                    correlation_id=request.correlation_id or f"correlation:{uuid4()}",
                ),
                approval_request_id=approval_id,
                expected_version=request.expected_version,
                reason=request.reason,
                idempotency_key=request.idempotency_key,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KernelError as exc:
            raise HTTPException(
                status_code=409, detail={"code": exc.code, "message": exc.message}
            ) from exc

    @router.post("/operations/{operation_id}/resume", status_code=202)
    def resume(operation_id: str, project_id: str) -> dict[str, Any]:
        try:
            principal = build_trusted_principal_resolver().resolve_api_principal()
            principal.require("canon.authority.approve", project_id)
            with AuthorityUnitOfWork(ctx.app_settings.database_url) as uow:
                state = uow.repositories.attempt_runtime.operation_state(operation_id, project_id)
            if state["status"] == "WAITING_GATE":
                raise HTTPException(status_code=409, detail="Canon approval gate is unresolved")
            return {"root_operation_id": operation_id, "status": state["status"], "worker_queue_visible": True}
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KernelError as exc:
            raise HTTPException(status_code=404, detail={"code": exc.code, "message": exc.message}) from exc

    return router


__all__ = ["create_router"]
