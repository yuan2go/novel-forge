from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from novel_forge.api.authority_dependencies import build_trusted_principal_resolver
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


class ScreenplayProviderSample(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str = Field(min_length=1)
    source_operation_id: str = Field(min_length=1)
    authorization_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    stage: str
    upstream_sample: dict[str, str] | None = None
    predecessor_operation_id: str = ""


def create_router(ctx: Any) -> APIRouter:
    router = APIRouter(prefix="/product/production/book-authority/runs/{book_run_id}/screenplay/provider-samples", tags=["book-screenplay-sampling"])

    def execute(call):
        try:
            return call(build_trusted_principal_resolver().resolve_api_principal())
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KernelError as exc:
            raise HTTPException(status_code=409, detail={"code": exc.code, "message": exc.message}) from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("", status_code=202)
    def sample(book_run_id: str, request: ScreenplayProviderSample, dry_run: bool = False):
        from novel_forge.modules.book_followup_authority.screenplay_sampling import ScreenplaySampleCommand
        def admit(actor):
            app = ctx.services.book_production.followup
            command = ScreenplaySampleCommand(actor_id=actor.principal_id, **request.model_dump())
            prepared = app.prepare_screenplay_sample(command, principal=actor)
            if prepared["command_payload"]["book_run_id"] != book_run_id:
                raise KernelError("SCREENPLAY_SAMPLE_SCOPE_INVALID", "The exact source belongs to another Book run")
            return prepared if dry_run else app.admit_screenplay_sample(command, principal=actor)
        return execute(admit)

    def require_operation(app, actor, *, book_run_id, project_id, operation_id, permission):
        from novel_forge.modules.book_followup_authority.screenplay import SCREENPLAY_STAGES
        from novel_forge.modules.book_followup_authority.screenplay_sampling import sample_definition_name
        actor.require(permission, project_id)
        with AuthorityUnitOfWork(app.database_url) as uow:
            uow.cursor.execute("SELECT definition_name,status,command_payload->'payload' FROM authority_operation WHERE project_id=%s AND operation_id=%s", [project_id, operation_id])
            row = uow.cursor.fetchone()
            if not row or row[0] not in {sample_definition_name(stage) for stage in SCREENPLAY_STAGES} or row[2].get("book_run_id") != book_run_id:
                raise KernelError("SCREENPLAY_SAMPLE_SCOPE_INVALID", "Resume or query the original exact Book sample")
            uow.cursor.execute("SELECT output.asset_version_id,output.content_hash,version.content FROM authority_operation_output_asset output JOIN authority_asset_version version USING(asset_version_id) WHERE output.operation_id=%s AND output.role='primary' AND output.content_hash=version.content_hash", [operation_id])
            outputs = [{"asset_version_id": item[0], "content_hash": item[1], "content": item[2]} for item in uow.cursor.fetchall()]
        return {"operation_id": operation_id, "status": row[1], "outputs": outputs, "production_eligible": False}

    @router.get("/{operation_id}")
    def query(book_run_id: str, operation_id: str, project_id: str):
        return execute(lambda actor: require_operation(ctx.services.book_production.followup, actor,
            book_run_id=book_run_id, project_id=project_id, operation_id=operation_id, permission="book.authority.query"))

    @router.post("/{operation_id}/run")
    def run(book_run_id: str, operation_id: str, project_id: str):
        from novel_forge.modules.book_followup_authority.application import BookFollowupAdmission
        def resume(actor):
            app = ctx.services.book_production.followup
            require_operation(app, actor, book_run_id=book_run_id, project_id=project_id, operation_id=operation_id, permission="book.authority.execute")
            return app.run_or_recover(BookFollowupAdmission(operation_id=operation_id, project_id=project_id, replayed=True))
        return execute(resume)
    return router
