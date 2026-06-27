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
    router = APIRouter(tags=['product-tasks'])
    TaskRetryRequest = models['TaskRetryRequest']
    TaskCancelRequest = models['TaskCancelRequest']
    TaskControlRequest = models['TaskControlRequest']
    DeadLetterRetryRequest = models['DeadLetterRetryRequest']

    @router.get("/product/tasks")
    def tasks(
        status: str | None = None,
        step: str | None = None,
        task_type: str | None = None,
        project_id: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        try:
            return indexed_task_center(
                app_settings,
                LocalStorage(app_settings.root),
                status=status,
                step=step,
                task_type=task_type,
                project_id=project_id,
                date_from=date_from,
                date_to=date_to,
                offset=offset,
                limit=limit,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/tasks/timeline")
    def task_timeline_endpoint(
        project_id: str | None = None,
        run_id: str | None = None,
        task_type: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> dict[str, Any]:
        try:
            return indexed_task_timeline(
                app_settings,
                LocalStorage(app_settings.root),
                project_id=project_id,
                run_id=run_id,
                task_type=task_type,
                date_from=date_from,
                date_to=date_to,
                offset=offset,
                limit=limit,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/tasks/control")
    def task_control() -> dict[str, Any]:
        try:
            return task_control_status(app_settings)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/tasks/recovery-workbench")
    def task_recovery_workbench_endpoint(project_id: str | None = None) -> dict[str, Any]:
        try:
            return task_recovery_workbench(app_settings, project_id=project_id)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.patch("/product/tasks/control")
    def update_task_control_endpoint(request: TaskControlRequest) -> dict[str, Any]:
        try:
            return update_task_control(app_settings.root, _model_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/tasks/dead-letters")
    def task_dead_letters(limit: int = 100) -> list[dict[str, Any]]:
        try:
            return task_dead_letter_rows(app_settings.root, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/tasks/dead-letters/retry")
    def retry_dead_letter_endpoint(request: DeadLetterRetryRequest) -> dict[str, Any]:
        try:
            task = retry_dead_letter(app_settings.root, request.dead_letter_path)
            return {"mode": "async", "task_id": task.id}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/tasks/cancel")
    def cancel_task_endpoint(request: TaskCancelRequest) -> dict[str, Any]:
        try:
            return cancel_celery_task(request.task_id, terminate=request.terminate, signal=request.signal)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.get("/product/tasks/events")
    async def task_events(
        project_id: str | None = None,
        status: str | None = None,
        step: str | None = None,
        task_type: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        offset: int = 0,
        interval: float = 2.0,
        limit: int = 100,
    ):
        async def event_stream():
            while True:
                payload = indexed_task_center(
                    app_settings,
                    LocalStorage(app_settings.root),
                    status=status,
                    step=step,
                    task_type=task_type,
                    project_id=project_id,
                    date_from=date_from,
                    date_to=date_to,
                    offset=offset,
                    limit=limit,
                )
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                await asyncio.sleep(max(0.5, interval))

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @router.get("/product/tasks/recovery")
    def task_recovery_endpoint(
        status_path: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            return task_recovery_report(LocalStorage(app_settings.root), status_path=status_path, run_id=run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/tasks/retry")
    def retry_task_endpoint(request: TaskRetryRequest) -> dict[str, Any]:
        if request.async_task:
            try:
                task = _enqueue(
                    "retry_product_task",
                    str(app_settings.root),
                    request.status_path,
                    request.run_id,
                    request.step,
                    request.workspace_path,
                )
            except Exception as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            return {"mode": "async", "task_id": task.id}
        try:
            return {"mode": "sync", **retry_task(app_settings.root, request.status_path, request.run_id, request.step, request.workspace_path)}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


    return router
