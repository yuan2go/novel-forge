from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.chapter_production_bus import (
    chapter_production_run_detail,
    list_chapter_production_runs,
    resume_chapter_production,
    start_chapter_production,
)
from novel_forge.modules.production_chain import (
    create_chapter_plan_version,
    create_draft_version,
    create_generation_run,
    create_outline_version,
    list_production_versions,
)
from novel_forge.storage.local import LocalStorage


def create_router(ctx: ProductRouterContext) -> APIRouter:
    app_settings = ctx.app_settings
    models = ctx.models
    globals().update(models)
    router = APIRouter(tags=["product-production-chain"])
    OutlineVersionRequest = models["OutlineVersionRequest"]
    ChapterPlanVersionRequest = models["ChapterPlanVersionRequest"]
    DraftVersionRequest = models["DraftVersionRequest"]
    GenerationRunRequest = models["GenerationRunRequest"]
    ChapterProductionRunRequest = models["ChapterProductionRunRequest"]
    ChapterProductionResumeRequest = models["ChapterProductionResumeRequest"]

    @router.get("/product/production/versions")
    def production_versions(
        project_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        try:
            return list_production_versions(LocalStorage(app_settings.root), project_id=project_id, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/production/chapter-runs")
    def chapter_runs(
        project_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        try:
            return list_chapter_production_runs(LocalStorage(app_settings.root), project_id=project_id, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/production/chapter-run")
    def chapter_run(path: str = Query(...)) -> dict[str, Any]:
        try:
            return chapter_production_run_detail(LocalStorage(app_settings.root), path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/production/chapter-run/start")
    def start_chapter_run_endpoint(request: ChapterProductionRunRequest) -> dict[str, Any]:
        try:
            return start_chapter_production(
                LocalStorage(app_settings.root),
                outline_path=request.outline_path,
                chapter_plan_path=request.chapter_plan_path,
                workspace_path=request.workspace_path,
                chapter=request.chapter,
                run_to=request.run_to,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/production/chapter-run/resume")
    def resume_chapter_run_endpoint(request: ChapterProductionResumeRequest) -> dict[str, Any]:
        try:
            return resume_chapter_production(
                LocalStorage(app_settings.root),
                request.run_path,
                from_step=request.from_step,
                run_to=request.run_to,
                force=request.force,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/production/outline-version")
    def outline_version_endpoint(request: OutlineVersionRequest) -> dict[str, Any]:
        try:
            return create_outline_version(
                LocalStorage(app_settings.root),
                request.outline_path,
                change_summary=request.change_summary,
                status=request.status,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/production/chapter-plan-version")
    def chapter_plan_version_endpoint(request: ChapterPlanVersionRequest) -> dict[str, Any]:
        try:
            return create_chapter_plan_version(
                LocalStorage(app_settings.root),
                request.chapter_plan_path,
                change_summary=request.change_summary,
                status=request.status,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/production/draft-version")
    def draft_version_endpoint(request: DraftVersionRequest) -> dict[str, Any]:
        try:
            return create_draft_version(
                LocalStorage(app_settings.root),
                request.draft_path,
                change_summary=request.change_summary,
                status=request.status,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/production/generation-run")
    def generation_run_endpoint(request: GenerationRunRequest) -> dict[str, Any]:
        try:
            return create_generation_run(
                LocalStorage(app_settings.root),
                request.input_path,
                request.context_bundle_path,
                output_path=request.output_path,
                provider=request.provider,
                model=request.model,
                prompt_version=request.prompt_version,
                status=request.status,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
