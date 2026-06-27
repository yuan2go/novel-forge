from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.audit import (
    create_chapter_audit_report,
    create_originality_report,
    create_publish_gate_report,
    create_release_package,
)
from novel_forge.modules.publishing import create_publishing_log, create_publishing_plan, list_publishing_assets
from novel_forge.storage.local import LocalStorage


def create_router(ctx: ProductRouterContext) -> APIRouter:
    app_settings = ctx.app_settings
    models = ctx.models
    globals().update(models)
    router = APIRouter(tags=["product-audit"])
    ChapterAuditRequest = models["ChapterAuditRequest"]
    OriginalityReportRequest = models["OriginalityReportRequest"]
    PublishGateRequest = models["PublishGateRequest"]
    ReleasePackageRequest = models["ReleasePackageRequest"]
    PublishingPlanRequest = models["PublishingPlanRequest"]
    PublishingLogRequest = models["PublishingLogRequest"]

    @router.get("/product/publishing/assets")
    def publishing_assets(project_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        try:
            return list_publishing_assets(LocalStorage(app_settings.root), project_id=project_id, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/audits/chapter")
    def chapter_audit_endpoint(request: ChapterAuditRequest) -> dict[str, Any]:
        storage = LocalStorage(app_settings.root)
        try:
            path = create_chapter_audit_report(
                storage,
                request.draft_path,
                workspace_path=request.workspace_path,
                quality_path=request.quality_path,
                style_path=request.style_path,
                originality_path=request.originality_path,
            )
            return {"path": str(path.relative_to(storage.root)), "chapter_audit_path": str(path.relative_to(storage.root))}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/audits/originality")
    def originality_report_endpoint(request: OriginalityReportRequest) -> dict[str, Any]:
        storage = LocalStorage(app_settings.root)
        try:
            path = create_originality_report(storage, request.draft_path, workspace_path=request.workspace_path)
            return {"path": str(path.relative_to(storage.root)), "originality_report_path": str(path.relative_to(storage.root))}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/publishing/gate")
    def publish_gate_endpoint(request: PublishGateRequest) -> dict[str, Any]:
        storage = LocalStorage(app_settings.root)
        try:
            path = create_publish_gate_report(
                storage,
                request.draft_path,
                workspace_path=request.workspace_path,
                chapter_audit_path=request.chapter_audit_path,
                human_override=request.human_override,
            )
            return {"path": str(path.relative_to(storage.root)), "publish_gate_report_path": str(path.relative_to(storage.root))}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/publishing/release-package")
    def release_package_endpoint(request: ReleasePackageRequest) -> dict[str, Any]:
        storage = LocalStorage(app_settings.root)
        try:
            path = create_release_package(
                storage,
                request.draft_path,
                workspace_path=request.workspace_path,
                publish_gate_path=request.publish_gate_path,
                channel=request.channel,
                human_override=request.human_override,
            )
            return {"path": str(path.relative_to(storage.root)), "release_package_path": str(path.relative_to(storage.root))}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/publishing/plan")
    def publishing_plan_endpoint(request: PublishingPlanRequest) -> dict[str, Any]:
        try:
            return create_publishing_plan(
                LocalStorage(app_settings.root),
                release_package_paths=request.release_package_paths,
                project_id=request.project_id,
                workspace_path=request.workspace_path,
                channel=request.channel,
                cadence=request.cadence,
                start_date=request.start_date,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/publishing/log")
    def publishing_log_endpoint(request: PublishingLogRequest) -> dict[str, Any]:
        try:
            return create_publishing_log(
                LocalStorage(app_settings.root),
                request.release_package_path,
                publishing_plan_path=request.publishing_plan_path,
                channel=request.channel,
                status=request.status,
                external_url=request.external_url,
                rollback_note=request.rollback_note,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
