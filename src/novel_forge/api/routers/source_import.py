"""Product-level Source import commands and operational queries."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from novel_forge.api.authority_dependencies import build_trusted_principal_resolver
from novel_forge.api.models import (
    ProductSourceImportRequest,
    ProductSourceReprocessingApplyRequest,
)
from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.source_import import (
    ApplyReprocessingPlanCommand,
    CreateSourceImportCommand,
)
from novel_forge.modules.source_import.domain import SourceImportPolicy
from novel_forge.modules.source_import.profiling import (
    SourceAnalysisOverride,
    SourceContentType,
    SourceIntelligencePolicy,
)


def create_router(ctx: ProductRouterContext) -> APIRouter:
    router = APIRouter(prefix="/product/source-imports", tags=["source-import"])
    application = ctx.services.source_import_application
    query = ctx.services.source_import_query

    @router.post("", status_code=202)
    def create_import(request: ProductSourceImportRequest) -> dict[str, Any]:
        return _create(request, mode="IMPORT")

    @router.post("/preview", status_code=202)
    def preview_import(request: ProductSourceImportRequest) -> dict[str, Any]:
        return _create(request, mode="PREVIEW")

    def _create(request: ProductSourceImportRequest, *, mode: str) -> dict[str, Any]:
        principal = _authorize("source.authority.execute", request.project_id)
        try:
            policy = SourceImportPolicy(
                **{
                    **request.policy.model_dump(),
                    "include_globs": tuple(request.policy.include_globs),
                    "exclude_globs": tuple(request.policy.exclude_globs),
                    "extension_allowlist": tuple(request.policy.extension_allowlist),
                }
            )
            intelligence_policy = SourceIntelligencePolicy(
                **request.intelligence_policy.model_dump()
            )
            override = (
                SourceAnalysisOverride(
                    logical_document_scope_hash=(
                        request.analysis_override.logical_document_scope_hash
                    ),
                    content_type=SourceContentType(
                        request.analysis_override.content_type
                    ),
                    reason=request.analysis_override.reason,
                    decision_ref=request.analysis_override.decision_ref,
                )
                if request.analysis_override is not None
                else None
            )
            return application.create_import(
                CreateSourceImportCommand(
                    project_id=request.project_id,
                    workspace_id=request.workspace_id,
                    source_type=request.source.type,
                    repository_url=request.source.repository,
                    requested_ref=request.source.ref,
                    policy=policy,
                    intelligence_policy=intelligence_policy,
                    analysis_override=override,
                    mode=mode,
                    rights_authorization=request.rights_authorization,
                    license_name=request.license_name,
                    copyright_boundary=request.copyright_boundary,
                    actor_id=principal.principal_id,
                    idempotency_key=request.idempotency_key,
                    trace_id=(
                        request.trace_id.strip()
                        or f"trace:source-import:{request.idempotency_key}"
                    ),
                    correlation_id=(
                        request.correlation_id.strip()
                        or f"correlation:source-import:{request.idempotency_key}"
                    ),
                ),
                principal=principal,
            )
        except (KernelError, ValueError) as exc:
            raise _http_error(exc) from exc

    @router.get("")
    def list_imports(
        project_id: str,
        status: str = "",
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        principal = _authorize("source.authority.query", project_id)
        return query.list_imports(
            project_id=project_id,
            status=status,
            limit=limit,
            principal=principal,
        )

    @router.get("/{import_job_id}")
    def import_status(import_job_id: str, project_id: str) -> dict[str, Any]:
        principal = _authorize("source.authority.query", project_id)
        try:
            return query.import_job(
                project_id=project_id,
                import_job_id=import_job_id,
                principal=principal,
            )
        except KernelError as exc:
            raise _http_error(exc, not_found=True) from exc

    @router.get("/{import_job_id}/preview")
    def preview_status(import_job_id: str, project_id: str) -> dict[str, Any]:
        principal = _authorize("source.authority.query", project_id)
        try:
            return query.preview(
                project_id=project_id,
                import_job_id=import_job_id,
                principal=principal,
            )
        except KernelError as exc:
            raise _http_error(exc, not_found=True) from exc

    @router.get("/{import_job_id}/files")
    def import_files(import_job_id: str, project_id: str) -> list[dict[str, Any]]:
        principal = _authorize("source.authority.query", project_id)
        try:
            return query.files(
                project_id=project_id,
                import_job_id=import_job_id,
                principal=principal,
            )
        except KernelError as exc:
            raise _http_error(exc, not_found=True) from exc

    @router.get("/{import_job_id}/work")
    def import_work(import_job_id: str, project_id: str) -> list[dict[str, Any]]:
        principal = _authorize("source.authority.query", project_id)
        try:
            return query.work(
                project_id=project_id,
                import_job_id=import_job_id,
                principal=principal,
            )
        except KernelError as exc:
            raise _http_error(exc, not_found=True) from exc

    @router.get("/{import_job_id}/downstream")
    def downstream(import_job_id: str, project_id: str) -> dict[str, Any]:
        principal = _authorize("source.authority.query", project_id)
        try:
            return query.downstream_status(
                project_id=project_id,
                import_job_id=import_job_id,
                principal=principal,
            )
        except KernelError as exc:
            raise _http_error(exc, not_found=True) from exc

    @router.post("/{import_job_id}/resume", status_code=202)
    def resume(import_job_id: str, project_id: str) -> dict[str, Any]:
        principal = _authorize("source.authority.execute", project_id)
        try:
            return application.resume_import(
                project_id=project_id,
                import_job_id=import_job_id,
                principal=principal,
            )
        except KernelError as exc:
            raise _http_error(exc) from exc

    @router.post("/reprocessing/apply", status_code=202)
    def apply_reprocessing(
        request: ProductSourceReprocessingApplyRequest,
    ) -> dict[str, Any]:
        principal = _authorize("source.authority.execute", request.project_id)
        try:
            return application.apply_reprocessing_plan(
                ApplyReprocessingPlanCommand(
                    project_id=request.project_id,
                    workspace_id=request.workspace_id,
                    reprocessing_plan_asset_version_id=(
                        request.reprocessing_plan_asset_version_id
                    ),
                    actor_id=principal.principal_id,
                    idempotency_key=request.idempotency_key,
                    trace_id=(
                        request.trace_id.strip()
                        or f"trace:reprocessing:{request.idempotency_key}"
                    ),
                    correlation_id=(
                        request.correlation_id.strip()
                        or f"correlation:reprocessing:{request.idempotency_key}"
                    ),
                ),
                principal=principal,
            )
        except (KernelError, ValueError) as exc:
            raise _http_error(exc) from exc

    @router.get("/reprocessing/{plan_asset_version_id}")
    def reprocessing_status(
        plan_asset_version_id: str, project_id: str
    ) -> dict[str, Any]:
        principal = _authorize("source.authority.query", project_id)
        try:
            return query.reprocessing_plan(
                project_id=project_id,
                plan_asset_version_id=plan_asset_version_id,
                principal=principal,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router


def _authorize(permission: str, project_id: str):
    principal = build_trusted_principal_resolver().resolve_api_principal()
    try:
        principal.require(permission, project_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return principal


def _http_error(exc: Exception, *, not_found: bool = False) -> HTTPException:
    if isinstance(exc, KernelError):
        return HTTPException(
            status_code=404 if not_found else 409,
            detail={"code": exc.code, "message": exc.message},
        )
    return HTTPException(status_code=422, detail=str(exc))


__all__ = ["create_router"]
