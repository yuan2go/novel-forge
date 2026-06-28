from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from novel_forge.api import product as _product_services
from novel_forge.api.routers._bindings import bind_product_symbols
from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.operations import create_local_ops_drill_report, create_long_chain_acceptance_report, list_operation_reports
from novel_forge.modules.module_completion import module_completion_report
from novel_forge.storage.local import LocalStorage

bind_product_symbols(globals(), _product_services)


def create_router(ctx: ProductRouterContext) -> APIRouter:
    app_settings = ctx.app_settings
    models = ctx.models
    globals().update(models)
    bind_product_symbols(globals(), ctx.services)
    router = APIRouter(tags=['product-system'])
    EventArchiveRequest = models['EventArchiveRequest']
    LocalRestoreRequest = models['LocalRestoreRequest']
    QdrantIndexRequest = models['QdrantIndexRequest']
    QdrantSearchRequest = models['QdrantSearchRequest']
    MinioSyncRequest = models['MinioSyncRequest']
    LocalOpsDrillRequest = models['LocalOpsDrillRequest']
    LongChainAcceptanceRequest = models['LongChainAcceptanceRequest']

    @router.get("/product/system/postgres/strict-check")
    def postgres_strict_check_endpoint(sync: bool = False) -> dict[str, Any]:
        try:
            return postgres_strict_local_prod_check(app_settings, sync=sync, raise_on_failure=False)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/system/health")
    def product_health_endpoint(project_id: str | None = None) -> dict[str, Any]:
        try:
            return project_health_report(app_settings, project_id=project_id)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/system/operation-reports")
    def operation_reports_endpoint(limit: int = Query(default=100, ge=1, le=500)) -> list[dict[str, Any]]:
        try:
            return list_operation_reports(LocalStorage(app_settings.root), limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/system/module-completion")
    def module_completion_endpoint(project_id: str | None = None) -> dict[str, Any]:
        try:
            return module_completion_report(LocalStorage(app_settings.root), project_id=project_id, persist=False)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/system/module-completion/snapshot")
    def module_completion_snapshot_endpoint(project_id: str | None = None) -> dict[str, Any]:
        try:
            return module_completion_report(LocalStorage(app_settings.root), project_id=project_id, persist=True)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/system/failure-drill")
    def failure_drill_endpoint(request: LocalOpsDrillRequest) -> dict[str, Any]:
        try:
            return create_local_ops_drill_report(LocalStorage(app_settings.root), settings=app_settings if request.include_external_services else None)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/system/long-chain-acceptance")
    def long_chain_acceptance_endpoint(request: LongChainAcceptanceRequest) -> dict[str, Any]:
        try:
            return create_long_chain_acceptance_report(
                LocalStorage(app_settings.root),
                project_id=request.project_id,
                chapter_count=request.chapter_count,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/system/backups")
    def create_backup_endpoint() -> dict[str, Any]:
        try:
            return create_local_backup(app_settings)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/system/events/archive")
    def archive_events_endpoint(request: EventArchiveRequest) -> dict[str, Any]:
        try:
            return archive_task_events(app_settings.root, before=request.before, keep_latest=request.keep_latest, confirm=request.confirm)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/system/backups")
    def list_backups_endpoint(limit: int = 20) -> list[dict[str, Any]]:
        try:
            return list_local_backups(app_settings.root, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/system/restore")
    def restore_backup_endpoint(request: LocalRestoreRequest) -> dict[str, Any]:
        try:
            return restore_local_backup(app_settings.root, request.backup_path, confirm=request.confirm)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/qdrant/index")
    def qdrant_index_endpoint(request: QdrantIndexRequest) -> dict[str, Any]:
        try:
            return qdrant_index_operation(
                app_settings.root,
                recreate=bool(request.recreate),
                batch_size=int(request.batch_size),
                resume=not bool(request.no_resume),
                force_reembed=bool(request.force_reembed),
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/qdrant/search")
    def qdrant_search_endpoint(request: QdrantSearchRequest) -> dict[str, Any]:
        try:
            return qdrant_search_operation(
                app_settings.root,
                query=request.query,
                category=request.category,
                asset_type=request.asset_type,
                project_id=request.project_id,
                workspace_path=request.workspace_path,
                tags=request.tags,
                limit=request.limit,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/minio/sync")
    def minio_sync_endpoint(request: MinioSyncRequest) -> dict[str, Any]:
        try:
            return minio_sync_operation(app_settings.root, categories=request.categories or None)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/minio/objects")
    def minio_objects_endpoint(category: str | None = None, limit: int = 100) -> dict[str, Any]:
        try:
            return minio_object_status(app_settings, category=category, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/uploads")
    async def upload_sources(request: Request) -> dict[str, Any]:
        try:
            body = await request.body()
            return receive_uploads(app_settings, body, request.headers.get("content-type", ""))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


    return router
