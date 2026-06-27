from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from novel_forge.api import product as _product_services
from novel_forge.api.routers._bindings import bind_product_symbols
from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.drafting import service as drafting_service

bind_product_symbols(globals(), _product_services)


def create_router(ctx: ProductRouterContext) -> APIRouter:
    app_settings = ctx.app_settings
    models = ctx.models
    globals().update(models)
    bind_product_symbols(globals(), ctx.services)
    router = APIRouter(tags=['product-drafts'])
    DraftGenerateRequest = models['DraftGenerateRequest']
    DraftSaveRequest = models['DraftSaveRequest']
    DraftExportRequest = models['DraftExportRequest']
    PublishExportRequest = models['PublishExportRequest']

    @router.get("/product/drafts")
    def drafts(project_id: str | None = None) -> dict[str, Any]:
        try:
            return draft_workbench(LocalStorage(app_settings.root), project_id=project_id)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/drafts/editor")
    def draft_editor_endpoint(path: str = Query(...)) -> dict[str, Any]:
        try:
            return draft_editor(LocalStorage(app_settings.root), path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/drafts/generate")
    def generate_draft(request: DraftGenerateRequest) -> dict[str, Any]:
        try:
            storage = LocalStorage(app_settings.root)
            path = drafting_service.draft(storage, request.chapter_plan_path, workspace_path=request.workspace_path)
            outputs = {"draft_path": _display_path(app_settings.root, path)}
            if request.update_workspace:
                workspace_path = pipeline.update_workspace(
                    app_settings.root,
                    input_path=str(path),
                    workspace_path=request.workspace_path,
                    chapter=request.chapter,
                    status="drafted",
                )
                outputs["workspace_path"] = _display_path(app_settings.root, workspace_path)
                attach_assets_to_project(storage, [path], str(workspace_path), role="draft")
            elif request.workspace_path:
                attach_assets_to_project(storage, [path], request.workspace_path, role="draft")
            return outputs
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/drafts/save")
    def save_draft_endpoint(request: DraftSaveRequest) -> dict[str, Any]:
        try:
            return save_draft_edit(app_settings.root, _model_data(request))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/drafts/diff")
    def draft_diff_endpoint(base_path: str, target_path: str) -> dict[str, Any]:
        try:
            return draft_diff(LocalStorage(app_settings.root), base_path, target_path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/drafts/export")
    def export_draft_endpoint(request: DraftExportRequest) -> dict[str, Any]:
        try:
            return export_draft(app_settings.root, request.draft_path, request.format)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/drafts/publish-record")
    def publish_export_endpoint(request: PublishExportRequest) -> dict[str, Any]:
        try:
            return create_publish_record(app_settings.root, request.export_path, channel=request.channel, note=request.note)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


    return router
