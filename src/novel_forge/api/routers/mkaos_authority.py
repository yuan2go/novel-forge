from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from novel_forge.api.authority_dependencies import build_trusted_principal_resolver
from novel_forge.api.models import (
    AuthorityMkaosKnowledgeApprovalRequest,
    AuthorityMkaosKnowledgeCandidateRequest,
    AuthorityMkaosKnowledgePackRequest,
)
from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.mkaos_authority import (
    ApproveKnowledgeCandidateCommand,
    BuildKnowledgePackCommand,
    CommitKnowledgeCandidateCommand,
    KnowledgeEvidenceSpan,
    KnowledgePackSelection,
)


def create_router(ctx: ProductRouterContext) -> APIRouter:
    router = APIRouter(tags=["mkaos-authority"])
    application = ctx.services.mkaos_authority_application
    query = ctx.services.mkaos_authority_query

    @router.post("/product/mkaos/knowledge-candidates", status_code=202)
    def commit_candidate(
        request: AuthorityMkaosKnowledgeCandidateRequest,
    ) -> dict[str, Any]:
        principal = _authorize("mkaos.authority.execute", request.project_id)
        try:
            if not request.observation_asset_version_ids:
                raise KernelError(
                    "MKAOS_CANONICAL_OBSERVATION_REQUIRED",
                    "production Candidate admission requires deconstruction Observation AssetVersions; direct SourceChunk mode is MIGRATION_ONLY",
                )
            return application.admit_candidate(
                CommitKnowledgeCandidateCommand(
                    project_id=request.project_id,
                    workspace_id=request.workspace_id,
                    execution_asset_version_id=request.execution_asset_version_id,
                    candidate=request.candidate,
                    evidence_spans=tuple(
                        KnowledgeEvidenceSpan(**span.model_dump())
                        for span in request.evidence_spans
                    ),
                    abstraction_policy_version=request.abstraction_policy_version,
                    actor_id=principal.principal_id,
                    idempotency_key=request.idempotency_key,
                    trace_id=request.trace_id.strip()
                    or f"trace:mkaos-candidate:{request.idempotency_key}",
                    correlation_id=request.correlation_id.strip()
                    or f"correlation:mkaos-candidate:{request.idempotency_key}",
                    observation_asset_version_ids=tuple(
                        request.observation_asset_version_ids
                    ),
                ),
                principal=principal,
            )
        except (KernelError, ValueError) as exc:
            raise _conflict(exc) from exc

    @router.get("/product/mkaos/knowledge-candidates")
    def candidates(
        project_id: str,
        status: str = "",
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        _authorize("mkaos.authority.query", project_id)
        return query.list_candidates(project_id=project_id, status=status, limit=limit)

    @router.post(
        "/product/mkaos/knowledge-candidates/{candidate_asset_version_id}/approve",
        status_code=202,
    )
    def approve_candidate(
        candidate_asset_version_id: str,
        request: AuthorityMkaosKnowledgeApprovalRequest,
    ) -> dict[str, Any]:
        principal = _authorize("mkaos.authority.approve", request.project_id)
        try:
            return application.admit_approval(
                ApproveKnowledgeCandidateCommand(
                    project_id=request.project_id,
                    workspace_id=request.workspace_id,
                    candidate_asset_version_id=candidate_asset_version_id,
                    policy_version=request.policy_version,
                    rationale=request.rationale,
                    actor_id=principal.principal_id,
                    idempotency_key=request.idempotency_key,
                    trace_id=request.trace_id.strip()
                    or f"trace:mkaos-approve:{request.idempotency_key}",
                    correlation_id=request.correlation_id.strip()
                    or f"correlation:mkaos-approve:{request.idempotency_key}",
                ),
                principal=principal,
            )
        except (KernelError, ValueError) as exc:
            raise _conflict(exc) from exc

    @router.get("/product/mkaos/knowledge-cards")
    def cards(
        project_id: str,
        status: str = "",
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        _authorize("mkaos.authority.query", project_id)
        return query.list_cards(project_id=project_id, status=status, limit=limit)

    @router.post("/product/mkaos/knowledge-packs", status_code=202)
    def build_pack(
        request: AuthorityMkaosKnowledgePackRequest,
    ) -> dict[str, Any]:
        principal = _authorize("mkaos.authority.execute", request.project_id)
        try:
            return application.admit_pack(
                BuildKnowledgePackCommand(
                    project_id=request.project_id,
                    workspace_id=request.workspace_id,
                    target_asset_version_id=request.target_asset_version_id,
                    selector_policy_version=request.selector_policy_version,
                    selector_policy_hash=request.selector_policy_hash,
                    selections=tuple(
                        KnowledgePackSelection(
                            knowledge_card_asset_version_id=(
                                item.knowledge_card_asset_version_id
                            ),
                            usage_role=item.usage_role,
                            frozen_weight=Decimal(str(item.frozen_weight)),
                        )
                        for item in request.selections
                    ),
                    actor_id=principal.principal_id,
                    idempotency_key=request.idempotency_key,
                    trace_id=request.trace_id.strip()
                    or f"trace:mkaos-pack:{request.idempotency_key}",
                    correlation_id=request.correlation_id.strip()
                    or f"correlation:mkaos-pack:{request.idempotency_key}",
                    supersedes_pack_asset_version_id=(
                        request.supersedes_pack_asset_version_id
                    ),
                ),
                principal=principal,
            )
        except (KernelError, ValueError) as exc:
            raise _conflict(exc) from exc

    @router.get("/product/mkaos/knowledge-packs")
    def packs(
        project_id: str,
        target_asset_version_id: str = "",
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        _authorize("mkaos.authority.query", project_id)
        return query.list_packs(
            project_id=project_id,
            target_asset_version_id=target_asset_version_id,
            limit=limit,
        )

    @router.get("/product/mkaos/knowledge-packs/{knowledge_pack_id}")
    def pack(knowledge_pack_id: str, project_id: str) -> dict[str, Any]:
        _authorize("mkaos.authority.query", project_id)
        try:
            return query.require_pack(
                project_id=project_id, knowledge_pack_id=knowledge_pack_id
            )
        except KernelError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/product/mkaos/knowledge-packs/{knowledge_pack_id}/diff")
    def pack_diff(
        knowledge_pack_id: str,
        project_id: str,
        against_knowledge_pack_id: str,
    ) -> dict[str, Any]:
        _authorize("mkaos.authority.query", project_id)
        try:
            return query.diff_packs(
                project_id=project_id,
                knowledge_pack_id=knowledge_pack_id,
                against_knowledge_pack_id=against_knowledge_pack_id,
            )
        except KernelError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/product/mkaos/runtime-usage")
    def runtime_usage(
        project_id: str,
        book_id: str = "",
        target_capability_id: str = "",
        result_asset_version_id: str = "",
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        _authorize("mkaos.authority.query", project_id)
        return query.list_runtime_usage(
            project_id=project_id,
            book_id=book_id,
            target_capability_id=target_capability_id,
            result_asset_version_id=result_asset_version_id,
            limit=limit,
        )

    @router.get("/product/mkaos/runtime-selections")
    def runtime_selections(
        project_id: str,
        book_id: str = "",
        target_capability_id: str = "",
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        _authorize("mkaos.authority.query", project_id)
        return query.list_runtime_selections(
            project_id=project_id,
            book_id=book_id,
            target_capability_id=target_capability_id,
            limit=limit,
        )

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
