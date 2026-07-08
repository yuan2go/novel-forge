from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from novel_forge.core.ids import utc_now
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.chapter_production_bus import (
    cancel_chapter_production,
    chapter_production_run_detail,
    list_chapter_production_runs,
    mark_chapter_production_celery_task,
    pause_chapter_production,
    recover_chapter_production,
    resume_chapter_production,
    start_chapter_production,
)
from novel_forge.modules.long_planning import create_long_form_macro_plan, list_long_form_macro_plans
from novel_forge.modules.change_impact import mark_downstream_assets_stale
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
    ChapterProductionControlRequest = models["ChapterProductionControlRequest"]
    ChapterProductionRecoverRequest = models["ChapterProductionRecoverRequest"]
    ProductionInvalidateRequest = models["ProductionInvalidateRequest"]
    LongFormMacroPlanRequest = models["LongFormMacroPlanRequest"]

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

    @router.get("/product/production/macro-plans")
    def macro_plans(
        project_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        try:
            return list_long_form_macro_plans(LocalStorage(app_settings.root), project_id=project_id, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/production/macro-plan")
    def macro_plan_endpoint(request: LongFormMacroPlanRequest) -> dict[str, Any]:
        try:
            return create_long_form_macro_plan(
                LocalStorage(app_settings.root),
                workspace_path=request.workspace_path,
                source_path=request.source_path,
                target_word_count=request.target_word_count,
                volume_count=request.volume_count,
                chapters_per_volume=request.chapters_per_volume,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/production/chapter-run")
    def chapter_run(path: str = Query(...)) -> dict[str, Any]:
        try:
            return chapter_production_run_detail(LocalStorage(app_settings.root), path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/production/chapter-run/start")
    def start_chapter_run_endpoint(request: ChapterProductionRunRequest) -> dict[str, Any]:
        try:
            if request.async_task:
                storage = LocalStorage(app_settings.root)
                run = start_chapter_production(
                    storage,
                    outline_path=request.outline_path,
                    chapter_plan_path=request.chapter_plan_path,
                    workspace_path=request.workspace_path,
                    chapter=request.chapter,
                    run_to=request.run_to,
                    execute=False,
                    execution_mode="celery",
                    environment=request.environment,
                    os_envelope=request.os_envelope,
                    source_policy=request.source_policy,
                    require_external_provider_proof=request.require_external_provider_proof,
                )
                task = _enqueue_chapter_production_task(app_settings, run["path"], run_to=request.run_to)
                detail = mark_chapter_production_celery_task(storage, run["path"], task.id)
                return {"mode": "async", "task_id": task.id, **detail}
            return start_chapter_production(
                LocalStorage(app_settings.root),
                outline_path=request.outline_path,
                chapter_plan_path=request.chapter_plan_path,
                workspace_path=request.workspace_path,
                chapter=request.chapter,
                run_to=request.run_to,
                environment=request.environment,
                os_envelope=request.os_envelope,
                source_policy=request.source_policy,
                require_external_provider_proof=request.require_external_provider_proof,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/production/chapter-run/resume")
    def resume_chapter_run_endpoint(request: ChapterProductionResumeRequest) -> dict[str, Any]:
        try:
            if request.async_task:
                task = _enqueue_chapter_production_task(
                    app_settings,
                    request.run_path,
                    from_step=request.from_step,
                    run_to=request.run_to,
                    force=request.force,
                    clear_pause=True,
                )
                detail = mark_chapter_production_celery_task(LocalStorage(app_settings.root), request.run_path, task.id)
                return {"mode": "async", "task_id": task.id, **detail}
            return resume_chapter_production(
                LocalStorage(app_settings.root),
                request.run_path,
                from_step=request.from_step,
                run_to=request.run_to,
                force=request.force,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/production/chapter-run/pause")
    def pause_chapter_run_endpoint(request: ChapterProductionControlRequest) -> dict[str, Any]:
        try:
            return pause_chapter_production(LocalStorage(app_settings.root), request.run_path, reason=request.reason)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/production/chapter-run/cancel")
    def cancel_chapter_run_endpoint(request: ChapterProductionControlRequest) -> dict[str, Any]:
        try:
            detail = cancel_chapter_production(LocalStorage(app_settings.root), request.run_path, reason=request.reason)
            task_id = str(detail.get("celery_task_id") or detail.get("control", {}).get("celery_task_id", ""))
            revoke = _revoke_celery_task(task_id, terminate=request.terminate, signal=request.signal) if task_id else {"attempted": False, "ok": True}
            return {**detail, "celery_revoke": revoke}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/production/chapter-run/recover")
    def recover_chapter_run_endpoint(request: ChapterProductionRecoverRequest) -> dict[str, Any]:
        try:
            if request.async_task:
                task = _enqueue_chapter_production_task(
                    app_settings,
                    request.run_path,
                    run_to=request.run_to,
                    force=request.force,
                    recover_failed=True,
                )
                detail = mark_chapter_production_celery_task(LocalStorage(app_settings.root), request.run_path, task.id)
                return {"mode": "async", "task_id": task.id, **detail}
            return recover_chapter_production(
                LocalStorage(app_settings.root),
                request.run_path,
                run_to=request.run_to,
                force=request.force,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/production/invalidate-downstream")
    def invalidate_downstream_endpoint(request: ProductionInvalidateRequest) -> dict[str, Any]:
        try:
            return mark_downstream_assets_stale(
                LocalStorage(app_settings.root),
                request.target_path,
                max_depth=request.max_depth,
                project_id=request.project_id,
                reason=request.reason,
                apply=request.apply,
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


def _enqueue_chapter_production_task(
    app_settings: IndustrialSettings,
    run_path: str,
    *,
    from_step: str | None = None,
    run_to: str | None = None,
    force: bool = False,
    recover_failed: bool = False,
    clear_pause: bool = False,
):
    try:
        from novel_forge.workers.dispatch import enqueue_task
    except Exception as exc:
        raise RuntimeError(f"Celery dispatch import failed: {exc}") from exc
    return enqueue_task(
        "chapter_production_run_task",
        str(app_settings.root),
        run_path,
        from_step,
        run_to,
        force,
        recover_failed,
        clear_pause,
        settings=app_settings,
        task_kwargs={"request_id": utc_now()},
    )


def _revoke_celery_task(task_id: str, *, terminate: bool = False, signal: str = "SIGTERM") -> dict[str, Any]:
    if not task_id:
        return {"attempted": False, "ok": True}
    try:
        from novel_forge.workers.tasks import celery_app
        if celery_app is None:
            raise RuntimeError("Celery is not installed or configured")
        celery_app.control.revoke(task_id, terminate=terminate, signal=signal)
        return {"attempted": True, "ok": True, "task_id": task_id, "terminate": terminate, "signal": signal}
    except Exception as exc:
        return {"attempted": True, "ok": False, "task_id": task_id, "error": str(exc)}
