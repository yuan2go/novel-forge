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
    router = APIRouter(tags=['product-handoffs'])
    HandoffDeconstructRequest = models['HandoffDeconstructRequest']
    HandoffKnowledgeRequest = models['HandoffKnowledgeRequest']
    GitHubKnowledgeHandoffRequest = models['GitHubKnowledgeHandoffRequest']
    HandoffOutputRequest = models['HandoffOutputRequest']
    HandoffAcceptanceRequest = models['HandoffAcceptanceRequest']
    HandoffRetryRequest = models['HandoffRetryRequest']
    HandoffFailRequest = models['HandoffFailRequest']

    @router.get("/product/handoffs")
    def handoffs(
        project_id: str | None = None,
        status: str | None = None,
        operation: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        try:
            return list_handoffs(
                LocalStorage(app_settings.root),
                project_id=project_id,
                status=status,
                operation=operation,
                limit=limit,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/sources/policies")
    def source_policies(category: str | None = None) -> list[dict[str, Any]]:
        return list_source_policies(category=category)

    @router.get("/product/sources/github")
    def github_knowledge_sources(
        category: str | None = None,
        allowed_pipeline: str | None = None,
        max_risk: str | None = None,
    ) -> list[dict[str, Any]]:
        return list_github_knowledge_sources(category=category, allowed_pipeline=allowed_pipeline, max_risk=max_risk)

    @router.post("/product/handoffs/deconstruct")
    def create_deconstruct_handoff(request: HandoffDeconstructRequest) -> dict[str, Any]:
        try:
            return create_product_deconstruction_handoff(app_settings.root, _model_data(request))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/handoffs/knowledge")
    def create_knowledge_handoff(request: HandoffKnowledgeRequest) -> dict[str, Any]:
        try:
            return create_product_knowledge_handoff(app_settings.root, _model_data(request))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/handoffs/github-knowledge")
    def create_github_knowledge_handoff_endpoint(request: GitHubKnowledgeHandoffRequest) -> dict[str, Any]:
        try:
            return create_github_knowledge_handoff(app_settings.root, _model_data(request))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/handoffs/validate-output")
    def validate_handoff_output_endpoint(request: HandoffOutputRequest) -> dict[str, Any]:
        try:
            return validate_handoff_output(app_settings.root, _model_data(request))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/handoffs/bind-output")
    def bind_handoff_output_endpoint(request: HandoffOutputRequest) -> dict[str, Any]:
        try:
            return bind_handoff_output(app_settings.root, _model_data(request))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/handoffs/acceptance")
    def handoff_acceptance_endpoint(handoff_path: str = Query(...)) -> dict[str, Any]:
        try:
            return handoff_acceptance_status(app_settings.root, handoff_path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.patch("/product/handoffs/acceptance")
    def update_handoff_acceptance_endpoint(request: HandoffAcceptanceRequest) -> dict[str, Any]:
        try:
            return update_handoff_acceptance(app_settings.root, _model_data(request))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/handoffs/fail")
    def fail_handoff_endpoint(request: HandoffFailRequest) -> dict[str, Any]:
        try:
            return fail_handoff(app_settings.root, _model_data(request))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/handoffs/retry")
    def retry_handoff_endpoint(request: HandoffRetryRequest) -> dict[str, Any]:
        try:
            return retry_handoff(app_settings.root, _model_data(request))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


    return router
