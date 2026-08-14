"""Command/query API for the Book + BookDesign Track B vertical slice."""
from __future__ import annotations

from typing import Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from novel_forge.api.authority_dependencies import build_trusted_principal_resolver
from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.book_design_authority import (
    BookDesignAuthorityCommand,
    BookDesignSemanticEvaluationCommand,
)
from novel_forge.modules.command_kernel.errors import KernelError


class CreateBookRequest(BaseModel):
    project_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    book_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    service_identity: str = Field(min_length=1)
    production_profile: dict[str, Any]
    runtime_policy: dict[str, Any]
    release_identity: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    schema_version: str = "book-authority.v1"


class ProposeBookDesignRequest(BaseModel):
    project_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    service_identity: str = Field(min_length=1)
    expected_book_version: int = Field(ge=1)
    expected_current_design_asset_version_id: str = ""
    payload: dict[str, Any]
    idempotency_key: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)


class DecideBookDesignRequest(BaseModel):
    project_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    service_identity: str = Field(min_length=1)
    expected_book_version: int = Field(ge=1)
    expected_current_design_asset_version_id: str = ""
    decision: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)


class EvaluateBookDesignRequest(BaseModel):
    project_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    generation_operation_id: str = Field(min_length=1)
    candidate_content_hash: str = Field(pattern=r"^sha256:")
    evaluator_execution_class: str = Field(min_length=1)
    evaluation: dict[str, Any]
    evidence_asset_version_ids: list[str] = Field(default_factory=list)
    idempotency_key: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)


class ActivateBookDesignRequest(BaseModel):
    project_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    service_identity: str = Field(min_length=1)
    expected_book_version: int = Field(ge=1)
    expected_current_design_asset_version_id: str = ""
    reason: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)


def create_router(context: ProductRouterContext) -> APIRouter:
    router = APIRouter(prefix="/authority", tags=["book-design-authority"])
    application = context.services.book_design_authority_application
    query = context.services.book_design_authority_query

    @router.post("/books")
    def create_book(request: CreateBookRequest) -> dict[str, Any]:
        principal = _principal("book_design.authority.execute", request.project_id)
        return _execute(
            application,
            BookDesignAuthorityCommand(
                definition_name="book.create",
                project_id=request.project_id,
                workspace_id=request.workspace_id,
                book_id=request.book_id,
                actor_id=principal.principal_id,
                service_identity=request.service_identity,
                idempotency_key=request.idempotency_key,
                trace_id=request.trace_id,
                correlation_id=request.correlation_id,
                payload={
                    "schema_version": request.schema_version,
                    "title": request.title,
                    "production_profile": request.production_profile,
                    "runtime_policy": request.runtime_policy,
                    "release_identity": request.release_identity,
                },
            ),
            principal,
        )

    @router.get("/books/{book_id}")
    def book_detail(book_id: str, project_id: str) -> dict[str, Any]:
        _principal("book_design.authority.query", project_id)
        return query.require_book(project_id=project_id, book_id=book_id)

    @router.post("/books/{book_id}/design-candidates")
    def propose(book_id: str, request: ProposeBookDesignRequest) -> dict[str, Any]:
        principal = _principal("book_design.authority.execute", request.project_id)
        return _execute(
            application,
            BookDesignAuthorityCommand(
                definition_name="book_design.propose",
                project_id=request.project_id,
                workspace_id=request.workspace_id,
                book_id=book_id,
                actor_id=principal.principal_id,
                service_identity=request.service_identity,
                idempotency_key=request.idempotency_key,
                trace_id=request.trace_id,
                correlation_id=request.correlation_id,
                payload=request.payload,
                expected_book_version=request.expected_book_version,
                expected_current_design_asset_version_id=request.expected_current_design_asset_version_id,
            ),
            principal,
        )

    @router.post("/books/{book_id}/design-candidates/{asset_version_id}/decisions")
    def decide(
        book_id: str, asset_version_id: str, request: DecideBookDesignRequest
    ) -> dict[str, Any]:
        principal = _principal("book_design.authority.execute", request.project_id)
        return _execute(
            application,
            BookDesignAuthorityCommand(
                definition_name="book_design.decide",
                project_id=request.project_id,
                workspace_id=request.workspace_id,
                book_id=book_id,
                actor_id=principal.principal_id,
                service_identity=request.service_identity,
                idempotency_key=request.idempotency_key,
                trace_id=request.trace_id,
                correlation_id=request.correlation_id,
                payload={"decision": request.decision, "reason": request.reason},
                expected_book_version=request.expected_book_version,
                expected_current_design_asset_version_id=request.expected_current_design_asset_version_id,
                target_asset_version_id=asset_version_id,
            ),
            principal,
        )

    @router.post(
        "/books/{book_id}/design-candidates/{asset_version_id}/semantic-evaluations"
    )
    def evaluate(
        book_id: str,
        asset_version_id: str,
        request: EvaluateBookDesignRequest,
    ) -> dict[str, Any]:
        principal = _narrative_evaluator_principal(request.project_id)
        try:
            return application.evaluate_semantics(
                BookDesignSemanticEvaluationCommand(
                    project_id=request.project_id,
                    workspace_id=request.workspace_id,
                    book_id=book_id,
                    actor_id=principal.principal_id,
                    candidate_asset_version_id=asset_version_id,
                    generation_operation_id=request.generation_operation_id,
                    generator_operation_name="book_design.propose",
                    candidate_content_hash=request.candidate_content_hash,
                    evaluator_execution_class=request.evaluator_execution_class,
                    evaluation=request.evaluation,
                    evidence_asset_version_ids=tuple(
                        request.evidence_asset_version_ids
                    ),
                    idempotency_key=request.idempotency_key,
                    trace_id=request.trace_id,
                    correlation_id=request.correlation_id,
                ),
                principal=principal,
            )
        except KernelError as exc:
            status = 409 if exc.code.endswith("CONFLICT") else 422
            raise HTTPException(
                status_code=status,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc

    @router.post("/books/{book_id}/design-candidates/{asset_version_id}/activations")
    def activate(
        book_id: str, asset_version_id: str, request: ActivateBookDesignRequest
    ) -> dict[str, Any]:
        principal = _principal("book_design.authority.execute", request.project_id)
        return _execute(
            application,
            BookDesignAuthorityCommand(
                definition_name="book_design.activate",
                project_id=request.project_id,
                workspace_id=request.workspace_id,
                book_id=book_id,
                actor_id=principal.principal_id,
                service_identity=request.service_identity,
                idempotency_key=request.idempotency_key,
                trace_id=request.trace_id,
                correlation_id=request.correlation_id,
                payload={"reason": request.reason},
                expected_book_version=request.expected_book_version,
                expected_current_design_asset_version_id=request.expected_current_design_asset_version_id,
                target_asset_version_id=asset_version_id,
            ),
            principal,
        )

    @router.get("/books/{book_id}/design-versions")
    def versions(book_id: str, project_id: str) -> list[dict[str, Any]]:
        _principal("book_design.authority.query", project_id)
        return query.list_design_versions(project_id=project_id, book_id=book_id)

    @router.get("/books/{book_id}/outbox")
    def outbox(book_id: str, project_id: str) -> list[dict[str, Any]]:
        _principal("book_design.authority.query", project_id)
        return query.outbox_projection(project_id=project_id, book_id=book_id)

    return router


def _principal(permission: str, project_id: str):
    principal = build_trusted_principal_resolver().resolve_api_principal()
    try:
        principal.require(permission, project_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return principal


def _narrative_evaluator_principal(project_id: str):
    principal = (
        build_trusted_principal_resolver()
        .resolve_narrative_evaluator_principal()
    )
    try:
        principal.require("narrative_design.evaluate", project_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return principal


def _execute(application: Any, command: BookDesignAuthorityCommand, principal: Any) -> dict[str, Any]:
    try:
        return application.execute(command, principal=principal)
    except KernelError as exc:
        status = 409 if exc.code.endswith("CONFLICT") else 422
        raise HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)}) from exc


__all__ = ["create_router"]
