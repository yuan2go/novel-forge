from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.api.routers.runtime_request import normalize_product_api_runtime_request
from novel_forge.modules.evaluation_center import (
    compare_model_runs,
    create_benchmark_task_from_generation_run,
    create_evaluation_case,
    create_evaluation_dashboard_snapshot,
    create_evaluation_gate,
    create_evaluation_suite,
    create_model_routing_policy,
    create_model_benchmark_task,
    create_model_profile,
    create_prompt_regression_report,
    create_prompt_version,
    evaluate_asset,
    evaluation_dashboard,
    list_model_evaluation_assets,
    resolve_model_route,
    run_evaluation_suite,
    run_model_benchmark_batch,
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
    ModelBenchmarkBatchRequest = models["ModelBenchmarkBatchRequest"]
    ModelRoutingPolicyRequest = models["ModelRoutingPolicyRequest"]
    PromptVersionRequest = models["PromptVersionRequest"]
    PromptRegressionRequest = models["PromptRegressionRequest"]
    BenchmarkFromGenerationRunRequest = models["BenchmarkFromGenerationRunRequest"]

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

    @router.post("/product/evaluation/benchmark-from-generation-run")
    def benchmark_from_generation_run_endpoint(request: BenchmarkFromGenerationRunRequest) -> dict[str, Any]:
        try:
            return create_benchmark_task_from_generation_run(
                LocalStorage(app_settings.root),
                request.generation_run_path,
                task_type=request.task_type,
                expected_output_type=request.expected_output_type,
                prompt_template=request.prompt_template,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
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

    @router.post("/product/evaluation/benchmark-batch")
    def benchmark_batch_endpoint(request: ModelBenchmarkBatchRequest) -> dict[str, Any]:
        try:
            return run_model_benchmark_batch(
                LocalStorage(app_settings.root),
                task_paths=request.task_paths,
                candidates=request.candidates or None,
                workspace_path=request.workspace_path,
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

    @router.post("/product/evaluation/routing-policy")
    def routing_policy_endpoint(request: ModelRoutingPolicyRequest) -> dict[str, Any]:
        try:
            return create_model_routing_policy(
                LocalStorage(app_settings.root),
                comparison_paths=request.comparison_paths,
                status=request.status,
                workspace_path=request.workspace_path,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/evaluation/route")
    def route_endpoint(task_type: str = "generate", project_id: str | None = None) -> dict[str, Any]:
        try:
            return resolve_model_route(LocalStorage(app_settings.root), task_type=task_type, project_id=project_id)
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

    @router.get("/product/evaluation/suites")
    def suites(project_id: str | None = None, limit: int = Query(default=200, ge=1, le=1000)) -> list[dict[str, Any]]:
        try:
            return [
                row
                for row in list_model_evaluation_assets(LocalStorage(app_settings.root), project_id=project_id, limit=limit)
                if row.get("type") == "evaluation_suite"
            ]
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/evaluation/suite")
    def suite_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return create_evaluation_suite(
                LocalStorage(app_settings.root),
                name=str(payload.get("name") or "Novel OS Quality Suite"),
                target_asset_types=[str(item) for item in payload.get("target_asset_types", [])] if isinstance(payload.get("target_asset_types", []), list) else None,
                metrics=[str(item) for item in payload.get("metrics", [])] if isinstance(payload.get("metrics", []), list) else None,
                status=str(payload.get("status") or "active"),
                project_id=str(payload.get("project_id") or ""),
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/evaluation/case")
    def case_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return create_evaluation_case(
                LocalStorage(app_settings.root),
                suite_id=str(payload.get("suite_id") or "default-novel-os-quality"),
                target_asset_path=str(payload.get("target_asset_path") or ""),
                expected=payload.get("expected") if isinstance(payload.get("expected"), dict) else {},
                status=str(payload.get("status") or "active"),
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/evaluation/run-suite")
    def run_suite_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return run_evaluation_suite(
                LocalStorage(app_settings.root),
                suite_path=payload.get("suite_path") or None,
                target_asset_paths=[str(item) for item in payload.get("target_asset_paths", [])] if isinstance(payload.get("target_asset_paths", []), list) else None,
                project_id=str(payload.get("project_id") or ""),
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/evaluation/evaluate-asset")
    def evaluate_asset_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            runtime_request = normalize_product_api_runtime_request(payload, operation="evaluation.evaluate_asset")
            return evaluate_asset(
                LocalStorage(app_settings.root),
                str(payload.get("target_asset_path") or ""),
                suite_id=str(payload.get("suite_id") or "default-novel-os-quality"),
                project_id=str(payload.get("project_id") or ""),
                create_issue_on_fail=bool(payload.get("create_issue_on_fail", False)),
                human_annotations=payload.get("human_annotations") if isinstance(payload.get("human_annotations"), list) else None,
                model_judge={
                    **(payload.get("model_judge") if isinstance(payload.get("model_judge"), dict) else {}),
                    "environment": runtime_request["environment"],
                    "source_policy": runtime_request["source_policy"],
                    "os_envelope": runtime_request["envelope"],
                },
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/evaluation/evaluate-agent-run")
    def evaluate_agent_run_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
        payload = {**payload, "suite_id": payload.get("suite_id") or "agent-run-quality"}
        return evaluate_asset_endpoint(payload)

    @router.post("/product/evaluation/evaluate-workflow-run")
    def evaluate_workflow_run_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
        payload = {**payload, "suite_id": payload.get("suite_id") or "workflow-run-quality"}
        return evaluate_asset_endpoint(payload)

    @router.post("/product/evaluation/evaluate-context")
    def evaluate_context_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
        payload = {**payload, "suite_id": payload.get("suite_id") or "context-quality"}
        return evaluate_asset_endpoint(payload)

    @router.post("/product/evaluation/evaluate-longform")
    def evaluate_longform_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
        payload = {**payload, "suite_id": payload.get("suite_id") or "longform-quality"}
        return evaluate_asset_endpoint(payload)

    @router.post("/product/evaluation/evaluate-platform-fit")
    def evaluate_platform_fit_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
        payload = {**payload, "suite_id": payload.get("suite_id") or "platform-fit"}
        return evaluate_asset_endpoint(payload)

    @router.post("/product/evaluation/evaluation-gate")
    def evaluation_gate_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return create_evaluation_gate(
                LocalStorage(app_settings.root),
                str(payload.get("target_asset_path") or ""),
                minimum_score=float(payload.get("minimum_score", 0.72) or 0.72),
                project_id=str(payload.get("project_id") or ""),
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/evaluation/regression-report")
    def evaluation_regression_report_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return create_evaluation_dashboard_snapshot(LocalStorage(app_settings.root), project_id=str(payload.get("project_id") or ""))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/evaluation/dashboard")
    def evaluation_dashboard_endpoint(project_id: str | None = None) -> dict[str, Any]:
        try:
            return evaluation_dashboard(LocalStorage(app_settings.root), project_id=project_id or "")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
