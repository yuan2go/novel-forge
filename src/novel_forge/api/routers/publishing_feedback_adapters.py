from __future__ import annotations

from fastapi import APIRouter, HTTPException

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.publishing_feedback_adapters import (
    build_platform_upload_package,
    cluster_platform_comments,
    create_feedback_mutation_proposal,
    import_platform_metrics,
    publish_platform_upload_package,
    record_platform_receipt,
    resolve_feedback_mutation_proposal,
)
from novel_forge.storage.local import LocalStorage


def create_router(ctx: ProductRouterContext) -> APIRouter:
    app_settings = ctx.app_settings
    models = ctx.models
    globals().update(models)
    router = APIRouter(tags=["product-publishing-feedback-adapters"])
    PlatformUploadPackageRequest = models["PlatformUploadPackageRequest"]
    PlatformReceiptRequest = models["PlatformReceiptRequest"]
    PlatformPublishRequest = models["PlatformPublishRequest"]
    PlatformMetricsImportRequest = models["PlatformMetricsImportRequest"]
    PlatformCommentsClusterRequest = models["PlatformCommentsClusterRequest"]
    FeedbackMutationProposalRequest = models["FeedbackMutationProposalRequest"]
    FeedbackMutationResolveRequest = models["FeedbackMutationResolveRequest"]

    @router.post("/product/publishing-adapters/upload-package")
    def upload_package_endpoint(request: PlatformUploadPackageRequest) -> dict:
        try:
            return build_platform_upload_package(
                LocalStorage(app_settings.root),
                release_package_path=request.release_package_path,
                platform_id=request.platform_id,
                book_metadata=request.book_metadata or None,
                chapter_payloads=request.chapter_payloads or None,
                environment=request.environment,
                envelope=request.envelope or None,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/publishing-adapters/receipt")
    def receipt_endpoint(request: PlatformReceiptRequest) -> dict:
        try:
            return record_platform_receipt(
                LocalStorage(app_settings.root),
                platform_id=request.platform_id,
                platform_book_id=request.platform_book_id,
                platform_chapter_id=request.platform_chapter_id,
                review_status=request.review_status,
                receipt_raw=request.receipt_raw,
                operator_note=request.operator_note,
                upload_package_path=request.upload_package_path,
                environment=request.environment,
                envelope=request.envelope or None,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/publishing-adapters/publish")
    def publish_endpoint(request: PlatformPublishRequest) -> dict:
        try:
            return publish_platform_upload_package(
                LocalStorage(app_settings.root),
                upload_package_path=request.upload_package_path,
                platform_config=request.platform_config,
                environment=request.environment,
                envelope=request.envelope or None,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/feedback-adapters/metrics")
    def metrics_endpoint(request: PlatformMetricsImportRequest) -> dict:
        try:
            return import_platform_metrics(
                LocalStorage(app_settings.root),
                platform_id=request.platform_id,
                chapter_metrics=request.chapter_metrics,
                book_metrics=request.book_metrics,
                environment=request.environment,
                envelope=request.envelope or None,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/feedback-adapters/comments/cluster")
    def comments_cluster_endpoint(request: PlatformCommentsClusterRequest) -> dict:
        try:
            return cluster_platform_comments(
                LocalStorage(app_settings.root),
                platform_id=request.platform_id,
                comments=request.comments,
                environment=request.environment,
                envelope=request.envelope or None,
                persist_issues=request.persist_issues,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/feedback-adapters/mutation-proposal")
    def mutation_proposal_endpoint(request: FeedbackMutationProposalRequest) -> dict:
        try:
            return create_feedback_mutation_proposal(
                LocalStorage(app_settings.root),
                source_feedback_paths=request.source_feedback_paths,
                target_assets=request.target_assets,
                proposed_changes=request.proposed_changes,
                environment=request.environment,
                envelope=request.envelope or None,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/feedback-adapters/mutation-proposal/resolve")
    def mutation_proposal_resolve_endpoint(request: FeedbackMutationResolveRequest) -> dict:
        try:
            return resolve_feedback_mutation_proposal(
                LocalStorage(app_settings.root),
                proposal_ref=request.proposal_ref,
                approved=request.approved,
                actor=request.actor,
                decision_note=request.decision_note,
                create_application_chain=request.create_application_chain,
                environment=request.environment,
                envelope=request.envelope or None,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
