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
    router = APIRouter(tags=['product-assets'])
    AssetCollectionRequest = models['AssetCollectionRequest']
    AssetEditRequest = models['AssetEditRequest']
    AssetContentEditRequest = models['AssetContentEditRequest']
    AssetTypedEditRequest = models['AssetTypedEditRequest']

    @router.get("/product/assets/detail")
    def product_asset_detail(path: str = Query(...)) -> dict[str, Any]:
        storage = LocalStorage(app_settings.root)
        try:
            return asset_detail(storage, path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.patch("/product/assets/detail")
    def edit_product_asset(request: AssetEditRequest) -> dict[str, Any]:
        storage = LocalStorage(app_settings.root)
        try:
            return update_asset_metadata(storage, request.path, _model_data(request))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.patch("/product/assets/content")
    def edit_product_asset_content(request: AssetContentEditRequest) -> dict[str, Any]:
        storage = LocalStorage(app_settings.root)
        try:
            return update_asset_content(storage, request.path, request.content)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.patch("/product/assets/typed")
    def edit_product_typed_asset(request: AssetTypedEditRequest) -> dict[str, Any]:
        storage = LocalStorage(app_settings.root)
        try:
            return update_typed_asset_fields(storage, request.path, request.fields)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/assets/versions")
    def asset_versions(path: str = Query(...)) -> dict[str, Any]:
        try:
            return asset_versions_and_diff(LocalStorage(app_settings.root), path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/assets/graph")
    def asset_graph(path: str = Query(...), depth: int = 1) -> dict[str, Any]:
        try:
            return asset_reference_graph(LocalStorage(app_settings.root), path, depth=depth)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/assets/collections")
    def create_asset_collection(request: AssetCollectionRequest) -> dict[str, Any]:
        try:
            return save_asset_collection(LocalStorage(app_settings.root), _model_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


    return router
