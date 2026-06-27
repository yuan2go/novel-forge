from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from novel_forge.api import product as _product_services
from novel_forge.api.routers._bindings import bind_product_symbols
from novel_forge.api.routers.context import ProductRouterContext

bind_product_symbols(globals(), _product_services)


def create_router(ctx: ProductRouterContext) -> APIRouter:
    app_settings = ctx.app_settings
    models = ctx.models
    globals().update(models)
    bind_product_symbols(globals(), ctx.services)
    router = APIRouter(tags=['product-projects'])
    ProjectCreateRequest = models['ProjectCreateRequest']
    ProjectConfigRequest = models['ProjectConfigRequest']
    ProjectDuplicateRequest = models['ProjectDuplicateRequest']
    ProjectScopeAuditRequest = models['ProjectScopeAuditRequest']

    @router.get("/product/projects")
    def projects(include_deleted: bool = False) -> list[dict[str, Any]]:
        return indexed_list_projects(app_settings, LocalStorage(app_settings.root), include_deleted=include_deleted)

    @router.get("/product/series")
    def series(include_deleted: bool = False) -> list[dict[str, Any]]:
        return indexed_list_series(app_settings, LocalStorage(app_settings.root), include_deleted=include_deleted)

    @router.post("/product/projects")
    def create_project(request: ProjectCreateRequest) -> dict[str, Any]:
        try:
            return create_project_with_defaults(app_settings.root, request.title, request.series_title, request.book_number, _model_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.patch("/product/projects/{project_id}/config")
    def update_project(project_id: str, request: ProjectConfigRequest) -> dict[str, Any]:
        storage = LocalStorage(app_settings.root)
        try:
            return update_project_config(storage, project_id, _model_data(request))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/projects/{project_id}/duplicate")
    def duplicate_project_endpoint(project_id: str, request: ProjectDuplicateRequest) -> dict[str, Any]:
        storage = LocalStorage(app_settings.root)
        try:
            return duplicate_project(storage, project_id, _model_data(request))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/projects/{project_id}/archive")
    def archive_project(project_id: str) -> dict[str, Any]:
        storage = LocalStorage(app_settings.root)
        try:
            return transition_project_status(storage, project_id, "archived", "archive")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/projects/{project_id}/pause")
    def pause_project(project_id: str) -> dict[str, Any]:
        storage = LocalStorage(app_settings.root)
        try:
            return transition_project_status(storage, project_id, "paused", "pause")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/projects/{project_id}/restore")
    def restore_project(project_id: str) -> dict[str, Any]:
        storage = LocalStorage(app_settings.root)
        try:
            return transition_project_status(storage, project_id, "active", "restore")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.delete("/product/projects/{project_id}")
    def delete_project(project_id: str) -> dict[str, Any]:
        storage = LocalStorage(app_settings.root)
        try:
            return transition_project_status(storage, project_id, "deleted", "soft-delete")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/projects/{project_id}/assets")
    def project_asset_list(
        project_id: str,
        category: str | None = None,
        asset_type: str | None = Query(default=None, alias="type"),
        keyword: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        storage = LocalStorage(app_settings.root)
        try:
            return indexed_project_assets(
                app_settings,
                storage,
                project_id,
                category=category,
                asset_type=asset_type,
                keyword=keyword,
                limit=limit,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/projects/{project_id}")
    def get_project(project_id: str) -> dict[str, Any]:
        storage = LocalStorage(app_settings.root)
        try:
            return project_detail(storage, project_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/projects/audit/scope")
    def project_scope_audit_endpoint(project_id: str | None = None) -> dict[str, Any]:
        try:
            return project_scope_audit(LocalStorage(app_settings.root), project_id=project_id, repair=False)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/projects/audit/scope")
    def repair_project_scope_audit_endpoint(request: ProjectScopeAuditRequest) -> dict[str, Any]:
        try:
            return project_scope_audit(LocalStorage(app_settings.root), project_id=request.project_id, repair=request.repair)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


    return router
