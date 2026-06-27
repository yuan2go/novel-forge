from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.evaluation_center import (
    compare_model_runs,
    create_model_benchmark_task,
    create_model_profile,
    create_prompt_regression_report,
    create_prompt_version,
    list_model_evaluation_assets,
    run_model_benchmark,
)
from novel_forge.storage.local import LocalStorage


def create_router(ctx: ProductRouterContext) -> APIRouter:
    app_settings = ctx.app_settings
    models = ctx.models
    globals().update(models)
    router = APIRouter(tags=["product-evaluation"])
    ModelProfileRequest = models["ModelProfileRequest"]
    ModelBenchmarkTaskRequest = models["ModelBenchmarkTaskRequest"]
    ModelBenchmarkRunRequest = models["ModelBenchmarkRunRequest"]
    ModelComparisonRequest = models["ModelComparisonRequest"]
    PromptVersionRequest = models["PromptVersionRequest"]
    PromptRegressionRequest = models["PromptRegressionRequest"]

    @router.get("/product/evaluation/assets")
    def evaluation_assets(project_id: str | None = None, limit: int = Query(default=100, ge=1, le=500)) -> list[dict[str, Any]]:
        try:
            return list_model_evaluation_assets(LocalStorage(app_settings.root), project_id=project_id, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/evaluation/model-profile")
    def model_profile_endpoint(request: ModelProfileRequest) -> dict[str, Any]:
        try:
            return create_model_profile(
                LocalStorage(app_settings.root),
                provider=request.provider,
                model_name=request.model_name,
                task_types=request.task_types,
                status=request.status,
                capabilities=request.capabilities or None,
                cost_profile=request.cost_profile or None,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/evaluation/benchmark-task")
    def benchmark_task_endpoint(request: ModelBenchmarkTaskRequest) -> dict[str, Any]:
        try:
            return create_model_benchmark_task(
                LocalStorage(app_settings.root),
                task_type=request.task_type,
                input_assets=request.input_assets,
                rubric=request.rubric or None,
                expected_output_type=request.expected_output_type,
                prompt_template=request.prompt_template,
                workspace_path=request.workspace_path,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/evaluation/benchmark-run")
    def benchmark_run_endpoint(request: ModelBenchmarkRunRequest) -> dict[str, Any]:
        try:
            return run_model_benchmark(
                LocalStorage(app_settings.root),
                request.task_path,
                provider=request.provider,
                model_name=request.model_name,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/evaluation/compare")
    def compare_endpoint(request: ModelComparisonRequest) -> dict[str, Any]:
        try:
            return compare_model_runs(
                LocalStorage(app_settings.root),
                request.run_paths,
                task_type=request.task_type,
                workspace_path=request.workspace_path,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/evaluation/prompt-version")
    def prompt_version_endpoint(request: PromptVersionRequest) -> dict[str, Any]:
        try:
            return create_prompt_version(
                LocalStorage(app_settings.root),
                prompt_id=request.prompt_id,
                version=request.version,
                task_type=request.task_type,
                template=request.template,
                status=request.status,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/evaluation/prompt-regression")
    def prompt_regression_endpoint(request: PromptRegressionRequest) -> dict[str, Any]:
        try:
            return create_prompt_regression_report(
                LocalStorage(app_settings.root),
                prompt_id=request.prompt_id,
                baseline_version=request.baseline_version,
                candidate_version=request.candidate_version,
                benchmark_runs=request.benchmark_runs,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
