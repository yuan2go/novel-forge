from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from novel_forge.api.authority_dependencies import build_trusted_principal_resolver
from novel_forge.api.models import (
    AuthorityDeconstructionObservationCommitRequest,
    AuthoritySourceDocumentRegisterRequest,
    AuthoritySourceReprocessingPlanRequest,
    AuthoritySourceTransformCommitRequest,
)
from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.source_authority import (
    AnalyzerContract,
    CommitDeconstructionObservationCommand,
    CommitSourceTransformCommand,
    ObservationEvidenceSpan,
    ObservationScope,
    PlanSourceReprocessingCommand,
    RegisterSourceDocumentCommand,
    ReprocessingTarget,
    SourceChunkCandidate,
)


def create_router(ctx: ProductRouterContext) -> APIRouter:
    router = APIRouter(tags=["source-authority"])
    application = ctx.services.source_authority_application
    query = ctx.services.source_authority_query

    @router.post("/product/source-governance/documents", status_code=202)
    def register(
        request: AuthoritySourceDocumentRegisterRequest,
    ) -> dict[str, Any]:
        principal = _authorize("source.authority.execute", request.project_id)
        try:
            return application.admit(
                RegisterSourceDocumentCommand(
                    project_id=request.project_id,
                    workspace_id=request.workspace_id,
                    blob_id=request.blob_id,
                    title=request.title,
                    source_kind=request.source_kind,
                    source_uri=request.source_uri,
                    rights_authorization=request.rights_authorization,
                    license_name=request.license_name,
                    copyright_boundary=request.copyright_boundary,
                    actor_id=principal.principal_id,
                    idempotency_key=request.idempotency_key,
                    trace_id=(
                        request.trace_id.strip()
                        or f"trace:source-register:{request.idempotency_key}"
                    ),
                    correlation_id=(
                        request.correlation_id.strip()
                        or f"correlation:source-register:{request.idempotency_key}"
                    ),
                ),
                principal=principal,
            )
        except (KernelError, ValueError) as exc:
            if isinstance(exc, KernelError):
                detail: Any = {"code": exc.code, "message": exc.message}
            else:
                detail = str(exc)
            raise HTTPException(status_code=409, detail=detail) from exc

    @router.get("/product/source-governance/documents")
    def documents(
        project_id: str,
        governance_status: str = "",
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        _authorize("source.authority.query", project_id)
        return query.list_documents(
            project_id=project_id,
            governance_status=governance_status,
            limit=limit,
        )

    @router.get("/product/source-governance/documents/{source_document_id}")
    def document(source_document_id: str, project_id: str) -> dict[str, Any]:
        _authorize("source.authority.query", project_id)
        try:
            return query.require_document(
                project_id=project_id,
                source_document_id=source_document_id,
            )
        except KernelError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post(
        "/product/source-governance/documents/{source_document_id}/transforms",
        status_code=202,
    )
    def commit_transform(
        source_document_id: str,
        request: AuthoritySourceTransformCommitRequest,
    ) -> dict[str, Any]:
        principal = _authorize("source.authority.execute", request.project_id)
        try:
            return application.admit_transform(
                CommitSourceTransformCommand(
                    project_id=request.project_id,
                    workspace_id=request.workspace_id,
                    source_document_id=source_document_id,
                    normalization_version=request.normalization_version,
                    chunking_version=request.chunking_version,
                    chunking_policy_hash=request.chunking_policy_hash,
                    chunks=tuple(
                        SourceChunkCandidate(**chunk.model_dump())
                        for chunk in request.chunks
                    ),
                    actor_id=principal.principal_id,
                    idempotency_key=request.idempotency_key,
                    trace_id=(
                        request.trace_id.strip()
                        or f"trace:source-transform:{request.idempotency_key}"
                    ),
                    correlation_id=(
                        request.correlation_id.strip()
                        or f"correlation:source-transform:{request.idempotency_key}"
                    ),
                ),
                principal=principal,
            )
        except (KernelError, ValueError) as exc:
            detail: Any = (
                {"code": exc.code, "message": exc.message}
                if isinstance(exc, KernelError)
                else str(exc)
            )
            raise HTTPException(status_code=409, detail=detail) from exc

    @router.get(
        "/product/source-governance/documents/{source_document_id}/transforms"
    )
    def transforms(
        source_document_id: str,
        project_id: str,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        _authorize("source.authority.query", project_id)
        return query.list_transforms(
            project_id=project_id,
            source_document_id=source_document_id,
            limit=limit,
        )

    @router.get("/product/source-governance/transforms/{source_transform_id}/chunks")
    def chunks(
        source_transform_id: str,
        project_id: str,
        limit: int = Query(default=500, ge=1, le=10_000),
    ) -> list[dict[str, Any]]:
        _authorize("source.authority.query", project_id)
        return query.list_chunks(
            project_id=project_id,
            source_transform_id=source_transform_id,
            limit=limit,
        )

    @router.post(
        "/product/source-governance/deconstruction-observations",
        status_code=202,
    )
    def commit_observation(
        request: AuthorityDeconstructionObservationCommitRequest,
    ) -> dict[str, Any]:
        principal = _authorize("source.authority.execute", request.project_id)
        try:
            return application.admit_observation(
                CommitDeconstructionObservationCommand(
                    project_id=request.project_id,
                    workspace_id=request.workspace_id,
                    execution_asset_version_id=request.execution_asset_version_id,
                    scope=ObservationScope(**request.scope.model_dump()),
                    analyzer=AnalyzerContract(**request.analyzer.model_dump()),
                    observation=request.observation,
                    evidence_spans=tuple(
                        ObservationEvidenceSpan(**span.model_dump())
                        for span in request.evidence_spans
                    ),
                    input_observation_asset_version_ids=tuple(
                        request.input_observation_asset_version_ids
                    ),
                    evidence_class=request.evidence_class,
                    actor_id=principal.principal_id,
                    idempotency_key=request.idempotency_key,
                    trace_id=request.trace_id.strip()
                    or f"trace:source-observation:{request.idempotency_key}",
                    correlation_id=request.correlation_id.strip()
                    or f"correlation:source-observation:{request.idempotency_key}",
                ),
                principal=principal,
            )
        except (KernelError, ValueError) as exc:
            raise _conflict(exc) from exc

    @router.get("/product/source-governance/deconstruction-observations")
    def observations(
        project_id: str,
        dimension: str = "",
        scale: str = "",
        limit: int = Query(default=100, ge=1, le=1_000),
    ) -> list[dict[str, Any]]:
        _authorize("source.authority.query", project_id)
        return query.list_observations(
            project_id=project_id, dimension=dimension, scale=scale, limit=limit
        )

    @router.post(
        "/product/source-governance/reprocessing-plans", status_code=202
    )
    def plan_reprocessing(
        request: AuthoritySourceReprocessingPlanRequest,
    ) -> dict[str, Any]:
        principal = _authorize("source.authority.execute", request.project_id)
        try:
            return application.admit_reprocessing_plan(
                PlanSourceReprocessingCommand(
                    project_id=request.project_id,
                    workspace_id=request.workspace_id,
                    targets=tuple(
                        ReprocessingTarget(
                            scope=ObservationScope(**target.scope.model_dump()),
                            analyzer=AnalyzerContract(**target.analyzer.model_dump()),
                        )
                        for target in request.targets
                    ),
                    cause_type=request.cause_type,
                    source_transform_id=request.source_transform_id,
                    actor_id=principal.principal_id,
                    idempotency_key=request.idempotency_key,
                    trace_id=request.trace_id.strip()
                    or f"trace:source-reprocessing:{request.idempotency_key}",
                    correlation_id=request.correlation_id.strip()
                    or f"correlation:source-reprocessing:{request.idempotency_key}",
                ),
                principal=principal,
            )
        except (KernelError, ValueError) as exc:
            raise _conflict(exc) from exc

    @router.get("/product/source-governance/reprocessing-plans")
    def reprocessing_plans(
        project_id: str,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        _authorize("source.authority.query", project_id)
        return query.list_reprocessing_plans(project_id=project_id, limit=limit)

    @router.get("/product/source-governance/invalidations")
    def invalidations(
        project_id: str,
        status: str = "OPEN",
        dimension: str = "",
        limit: int = Query(default=100, ge=1, le=1_000),
    ) -> list[dict[str, Any]]:
        _authorize("source.authority.query", project_id)
        try:
            return query.list_invalidations(
                project_id=project_id,
                status=status,
                dimension=dimension,
                limit=limit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/product/source-governance/data-import-admission")
    def data_import_admission(project_id: str) -> dict[str, Any]:
        _authorize("source.authority.query", project_id)
        try:
            return query.data_import_admission(project_id=project_id)
        except (KernelError, ValueError) as exc:
            raise _conflict(exc) from exc

    return router


def _authorize(permission: str, project_id: str):
    principal = build_trusted_principal_resolver().resolve_api_principal()
    try:
        principal.require(permission, project_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return principal


def _conflict(exc: KernelError | ValueError) -> HTTPException:
    detail: Any = (
        {"code": exc.code, "message": exc.message}
        if isinstance(exc, KernelError)
        else str(exc)
    )
    return HTTPException(status_code=409, detail=detail)


__all__ = ["create_router"]
