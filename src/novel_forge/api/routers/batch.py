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
    router = APIRouter(tags=['product-batch'])
    BatchDeconstructRequest = models['BatchDeconstructRequest']
    BatchItemRetryRequest = models['BatchItemRetryRequest']
    BatchItemsBulkRetryRequest = models['BatchItemsBulkRetryRequest']
    BatchItemReviewRequest = models['BatchItemReviewRequest']
    BatchItemContinueRequest = models['BatchItemContinueRequest']
    BatchItemHandoffRequest = models['BatchItemHandoffRequest']

    @router.get("/product/batch/items")
    def batch_items(
        batch_id: str | None = None,
        status: str | None = None,
        project_id: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        try:
            return list_batch_items(LocalStorage(app_settings.root), batch_id=batch_id, status=status, project_id=project_id, offset=offset, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/batch/items/retry")
    def retry_batch_item_endpoint(request: BatchItemRetryRequest) -> dict[str, Any]:
        try:
            return retry_batch_item(app_settings.root, request.item_path, workspace_path=request.workspace_path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/batch/items/retry-bulk")
    def retry_batch_items_bulk_endpoint(request: BatchItemsBulkRetryRequest) -> dict[str, Any]:
        try:
            return retry_batch_items_bulk(app_settings.root, request.item_paths, workspace_path=request.workspace_path)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.patch("/product/batch/items/review")
    def review_batch_item_endpoint(request: BatchItemReviewRequest) -> dict[str, Any]:
        try:
            return review_batch_item(LocalStorage(app_settings.root), _model_data(request))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/batch/items/continue")
    def continue_batch_item_endpoint(request: BatchItemContinueRequest) -> dict[str, Any]:
        try:
            return continue_batch_handoff(app_settings.root, _model_data(request))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/batch/items/handoff/regenerate")
    def regenerate_batch_handoff_endpoint(request: BatchItemHandoffRequest) -> dict[str, Any]:
        try:
            return regenerate_batch_handoff(app_settings.root, _model_data(request))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/batch/items/handoff/void")
    def void_batch_handoff_endpoint(request: BatchItemHandoffRequest) -> dict[str, Any]:
        try:
            return void_batch_handoff(app_settings.root, _model_data(request))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/batch/deconstruct")
    def batch_deconstruct(request: BatchDeconstructRequest) -> dict[str, Any]:
        if request.async_task:
            try:
                task = _enqueue(
                    "batch_deconstruct_task",
                    str(app_settings.root),
                    request.input_path,
                    request.title,
                    request.rights_authorization,
                    request.license_name,
                    request.copyright_note,
                    request.source_url,
                    request.allow_downstream_generation,
                    request.workspace_path,
                    request.analysis_mode,
                )
            except Exception as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            return {"mode": "async", "task_id": task.id}
        try:
            result = run_batch_deconstruct(
                app_settings.root,
                request.input_path,
                title=request.title,
                rights_authorization=request.rights_authorization,
                license_name=request.license_name,
                copyright_note=request.copyright_note,
                source_url=request.source_url,
                allow_downstream_generation=request.allow_downstream_generation,
                workspace_path=request.workspace_path,
                analysis_mode=request.analysis_mode,
            )
            return {"mode": "sync", **result}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


    return router
