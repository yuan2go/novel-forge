from __future__ import annotations

from fastapi import APIRouter, HTTPException

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.portfolio_os import (
    build_book_potential_scores,
    build_cross_book_similarity_report,
    build_multi_book_scheduler_plan,
    build_resource_allocation_plan,
    create_portfolio_project,
)
from novel_forge.storage.local import LocalStorage


def create_router(ctx: ProductRouterContext) -> APIRouter:
    app_settings = ctx.app_settings
    models = ctx.models
    globals().update(models)
    router = APIRouter(tags=["product-portfolio-os"])
    PortfolioProjectRequest = models["PortfolioProjectRequest"]
    PortfolioScoreRequest = models["PortfolioScoreRequest"]
    PortfolioAllocationRequest = models["PortfolioAllocationRequest"]
    PortfolioSimilarityRequest = models["PortfolioSimilarityRequest"]
    PortfolioSchedulerPlanRequest = models["PortfolioSchedulerPlanRequest"]

    @router.post("/product/portfolio/project")
    def portfolio_project_endpoint(request: PortfolioProjectRequest) -> dict:
        try:
            return create_portfolio_project(
                LocalStorage(app_settings.root),
                title=request.title,
                portfolio_id=request.portfolio_id,
                project_ids=request.project_ids,
                strategy=request.strategy,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/portfolio/scores")
    def portfolio_scores_endpoint(request: PortfolioScoreRequest) -> dict:
        try:
            return build_book_potential_scores(
                LocalStorage(app_settings.root),
                portfolio_ref=request.portfolio_ref,
                project_ids=request.project_ids or None,
                weights=request.weights,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/portfolio/allocation-plan")
    def portfolio_allocation_plan_endpoint(request: PortfolioAllocationRequest) -> dict:
        try:
            return build_resource_allocation_plan(
                LocalStorage(app_settings.root),
                portfolio_ref=request.portfolio_ref,
                project_ids=request.project_ids or None,
                provider_budget=request.provider_budget,
                max_parallel_books=request.max_parallel_books,
                daily_chapter_goal=request.daily_chapter_goal,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/portfolio/cross-book-similarity")
    def portfolio_cross_book_similarity_endpoint(request: PortfolioSimilarityRequest) -> dict:
        try:
            return build_cross_book_similarity_report(
                LocalStorage(app_settings.root),
                portfolio_ref=request.portfolio_ref,
                project_ids=request.project_ids or None,
                medium_threshold=request.medium_threshold,
                high_threshold=request.high_threshold,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/portfolio/scheduler-plan")
    def portfolio_scheduler_plan_endpoint(request: PortfolioSchedulerPlanRequest) -> dict:
        try:
            return build_multi_book_scheduler_plan(
                LocalStorage(app_settings.root),
                portfolio_ref=request.portfolio_ref,
                allocation_ref=request.allocation_ref,
                similarity_ref=request.similarity_ref,
                project_ids=request.project_ids or None,
                provider_budget=request.provider_budget,
                max_parallel_books=request.max_parallel_books,
                daily_chapter_goal=request.daily_chapter_goal,
                environment=request.environment,
                requested_by=request.requested_by,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
