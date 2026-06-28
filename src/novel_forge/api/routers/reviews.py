from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from novel_forge.api import product as _product_services
from novel_forge.api.routers._bindings import bind_product_symbols
from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.revision import run_review_rework_loop

bind_product_symbols(globals(), _product_services)


def create_router(ctx: ProductRouterContext) -> APIRouter:
    app_settings = ctx.app_settings
    models = ctx.models
    globals().update(models)
    bind_product_symbols(globals(), ctx.services)
    router = APIRouter(tags=['product-reviews'])
    ReviewRunRequest = models['ReviewRunRequest']
    RevisionPlanRequest = models['RevisionPlanRequest']
    ReviewIssueStatusRequest = models['ReviewIssueStatusRequest']
    RevisionApplyRequest = models['RevisionApplyRequest']
    RevisionReworkLoopRequest = models["RevisionReworkLoopRequest"]

    @router.post("/product/reviews/run")
    def run_review(request: ReviewRunRequest) -> dict[str, Any]:
        try:
            path = (
                pipeline.compare_reviews(app_settings.root, request.draft_path)
                if request.comparison
                else pipeline.review(app_settings.root, request.draft_path)
            )
            outputs = {"review_path": _display_path(app_settings.root, path)}
            storage = LocalStorage(app_settings.root)
            if request.update_workspace:
                workspace_path = pipeline.update_workspace(
                    app_settings.root,
                    input_path=str(path),
                    workspace_path=request.workspace_path,
                    chapter=request.chapter,
                    status="reviewed",
                )
                outputs["workspace_path"] = _display_path(app_settings.root, workspace_path)
                attach_assets_to_project(storage, [path], str(workspace_path), role="review")
            elif request.workspace_path:
                attach_assets_to_project(storage, [path], request.workspace_path, role="review")
            return outputs
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/revisions/plan")
    def create_revision_plan(request: RevisionPlanRequest) -> dict[str, Any]:
        try:
            path = pipeline.revise(app_settings.root, request.review_path)
            storage = LocalStorage(app_settings.root)
            workspace_ref = request.workspace_path or _workspace_ref_from_asset(storage, request.review_path)
            if workspace_ref:
                attach_assets_to_project(storage, [path], workspace_ref, role="revision")
            return {"revision_path": _display_path(app_settings.root, path)}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.patch("/product/reviews/issues")
    def update_review_issue_endpoint(request: ReviewIssueStatusRequest) -> dict[str, Any]:
        try:
            return update_review_issue_status(LocalStorage(app_settings.root), _model_data(request))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/revisions/apply")
    def apply_revision_endpoint(request: RevisionApplyRequest) -> dict[str, Any]:
        try:
            return apply_revision_plan(app_settings.root, _model_data(request))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/revisions/rework-loop")
    def rework_loop_endpoint(request: RevisionReworkLoopRequest) -> dict[str, Any]:
        try:
            return run_review_rework_loop(
                LocalStorage(app_settings.root),
                request.review_path,
                draft_path=request.draft_path,
                issue_indexes=request.issue_indexes,
                context_bundle_path=request.context_bundle_path,
                workspace_path=request.workspace_path,
                human_override=request.human_override,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


    return router
