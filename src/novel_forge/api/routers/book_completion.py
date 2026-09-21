from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from novel_forge.api.authority_dependencies import build_trusted_principal_resolver
from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.command_kernel.errors import KernelError


class CompletionScope(BaseModel):
    project_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    book_run_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)


class CompletionDecisionRequest(CompletionScope):
    case_id: str = Field(min_length=1)
    source_digest: str = Field(pattern="^sha256:[0-9a-f]{64}$")
    expected_case_version: int = Field(ge=1)
    expected_decision_version: int = Field(ge=0)
    decision: str = Field(pattern="^(ACCEPTED|REJECTED)$")
    rationale: str = Field(min_length=1)
    quality_campaign_id: str = ""
    closure_evidence_id: str = ""


class EditorialEventRequest(CompletionScope):
    expected_version: int = Field(ge=0)
    kind: str = Field(pattern="^(POLICY|SIGNATURE|REVOCATION)$")
    content: dict[str, Any]


def create_router(ctx: ProductRouterContext) -> APIRouter:
    router = APIRouter(prefix="/api/book-completion", tags=["book-completion"])
    authority = ctx.services.book_completion_authority

    def execute(call):
        try:
            return call(build_trusted_principal_resolver().resolve_api_principal())
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KernelError as exc:
            raise HTTPException(
                status_code=409, detail={"code": exc.code, "message": exc.message}
            ) from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/cases")
    def assess(request: CompletionScope) -> dict[str, Any]:
        return execute(
            lambda actor: authority.assess(**request.model_dump(), principal=actor)
        )

    @router.post("/decisions")
    def decide(request: CompletionDecisionRequest) -> dict[str, Any]:
        return execute(
            lambda actor: authority.decide(**request.model_dump(), principal=actor)
        )

    @router.get("/cases/{case_id}")
    def require_case(
        case_id: str, project_id: str, workspace_id: str, book_run_id: str
    ) -> dict[str, Any]:
        return execute(
            lambda actor: authority.require_case(
                case_id=case_id,
                project_id=project_id,
                workspace_id=workspace_id,
                book_run_id=book_run_id,
                principal=actor,
            )
        )

    @router.post("/editorial-events")
    def editorial_event(request: EditorialEventRequest) -> dict[str, Any]:
        from novel_forge.modules.book_authority.editorial import BookEditorialWorkflow
        return execute(lambda actor: BookEditorialWorkflow(authority).record(**request.model_dump(), principal=actor))

    @router.get("/editorial-history")
    def editorial_history(project_id: str, workspace_id: str, book_run_id: str) -> dict[str, Any]:
        from novel_forge.modules.book_authority.editorial import BookEditorialWorkflow
        return execute(lambda actor: BookEditorialWorkflow(authority).history(project_id=project_id, workspace_id=workspace_id, book_run_id=book_run_id, principal=actor))

    return router
