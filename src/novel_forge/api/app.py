from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.api.product import postgres_strict_local_prod_check, register_product_routes
from novel_forge.modules.common import resolve_path
from novel_forge.storage.local import LocalStorage
from novel_forge.storage.postgres import PostgresAssetStore
from novel_forge.workflows import pipeline


def create_app(settings: IndustrialSettings | None = None):
    try:
        from fastapi import FastAPI, HTTPException, Query
        from fastapi.middleware.cors import CORSMiddleware
        from novel_forge.api.models import product_model_map
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency-gated path
        raise RuntimeError("FastAPI support requires optional dependencies: fastapi and uvicorn[standard]") from exc

    app_settings = settings or IndustrialSettings.from_env()
    postgres_strict_local_prod_check(app_settings, sync=True)
    app = FastAPI(
        title="Novel Forge API",
        version="5.0.0",
        description="Industrial backend API for Novel Forge V5 assets and workflows.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(app_settings.api_cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    models = product_model_map()
    globals().update(models)
    PipelineRunRequest = models["PipelineRunRequest"]
    StepRunRequest = models["StepRunRequest"]
    register_product_routes(app, app_settings, models)

    @app.get("/health")
    def health() -> dict[str, Any]:
        return pipeline.industrial_status(app_settings.root)

    @app.get("/assets")
    def assets(
        category: str | None = None,
        asset_type: str | None = Query(default=None, alias="type"),
        tag: list[str] | None = Query(default=None),
        keyword: str | None = None,
        limit: int = 50,
        rank: str = "path",
    ) -> list[dict[str, Any]]:
        if app_settings.database_url:
            try:
                rows = PostgresAssetStore(app_settings.database_url).list_assets(
                    category=category,
                    asset_type=asset_type,
                    tags=tag or [],
                    keyword=keyword,
                    limit=limit,
                )
                return [_api_asset_row_from_index(row) for row in rows]
            except Exception:
                pass
        try:
            return pipeline.search_assets(
                app_settings.root,
                category=category,
                asset_type=asset_type,
                tags=tag or [],
                keyword=keyword,
                limit=limit,
                rank=rank,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/assets/{asset_path:path}")
    def asset_detail(asset_path: str) -> dict[str, Any]:
        storage = LocalStorage(app_settings.root)
        try:
            path = resolve_path(storage.root, asset_path).resolve()
            path.relative_to(storage.root)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"invalid asset path: {asset_path}") from exc
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="asset not found")
        try:
            data = storage.read_json(path)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not isinstance(data, dict):
            raise HTTPException(status_code=400, detail="asset JSON must be an object")
        return data

    @app.get("/vector/search")
    def vector_search(
        query: str,
        category: str | None = None,
        asset_type: str | None = Query(default=None, alias="type"),
        tag: list[str] | None = Query(default=None),
        limit: int = 50,
        backend: str = "local",
    ) -> list[dict[str, Any]]:
        try:
            if backend == "qdrant":
                return pipeline.qdrant_search(
                    app_settings.root,
                    query=query,
                    category=category,
                    asset_type=asset_type,
                    tags=tag or [],
                    limit=limit,
                )
            if backend != "local":
                raise ValueError("backend must be local or qdrant")
            return pipeline.vector_search_assets(
                app_settings.root,
                query=query,
                category=category,
                asset_type=asset_type,
                tags=tag or [],
                limit=limit,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/pipeline/run")
    def run_pipeline(request: PipelineRunRequest) -> dict[str, Any]:
        if request.async_task:
            try:
                task = _enqueue("run_pipeline_task", str(app_settings.root), request.sample)
            except Exception as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            return {"mode": "async", "task_id": task.id}
        try:
            path = pipeline.run_pipeline(app_settings.root, sample=request.sample)
            return {"mode": "sync", "path": _display_path(app_settings.root, path)}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/tasks/run-step")
    def run_step(request: StepRunRequest) -> dict[str, Any]:
        if request.async_task:
            try:
                task = _enqueue("run_step_task", str(app_settings.root), request.step, request.input_path)
            except Exception as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            return {"mode": "async", "task_id": task.id}
        try:
            path = _run_step_sync(app_settings.root, request.step, request.input_path)
            return {"mode": "sync", "path": _display_path(app_settings.root, path)}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/tasks/{task_id}")
    def task_status(task_id: str) -> dict[str, Any]:
        try:
            from novel_forge.workers.tasks import celery_app
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if celery_app is None:
            raise HTTPException(status_code=503, detail="Celery is not installed or configured")
        result = celery_app.AsyncResult(task_id)
        return {
            "task_id": task_id,
            "state": result.state,
            "ready": result.ready(),
            "successful": result.successful() if result.ready() else False,
            "result": result.result if result.ready() and result.successful() else None,
            "error": str(result.result) if result.ready() and not result.successful() else "",
        }

    return app


def _api_asset_row_from_index(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload", {}) if isinstance(row.get("payload", {}), dict) else {}
    content = payload.get("content", {}) if isinstance(payload.get("content", {}), dict) else {}
    metadata = payload.get("metadata", {}) if isinstance(payload.get("metadata", {}), dict) else {}
    return {
        "path": row.get("path", ""),
        "category": row.get("category", ""),
        "id": row.get("id", ""),
        "type": row.get("type", ""),
        "title": row.get("title", ""),
        "source": row.get("source", ""),
        "tags": row.get("tags", []),
        "score": payload.get("score"),
        "risk_level": payload.get("risk_level") or metadata.get("risk_level", ""),
        "asset_status": metadata.get("asset_status", ""),
        "updated_at": payload.get("updated_at", ""),
        "summary": _content_preview(content),
        "ranker": "postgres-index",
        "index_source": "postgres",
    }


def _content_preview(content: dict[str, Any]) -> str:
    for key in ["text", "summary", "logline", "objective", "hook"]:
        value = content.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())[:220]
    return ""


def _enqueue(task_name: str, *args: Any):
    from novel_forge.workers.dispatch import enqueue_task

    return enqueue_task(task_name, *args)


def _run_step_sync(root: Path, step: str, input_path: str | None):
    allowed = {
        "clean": pipeline.clean,
        "decompose": pipeline.decompose,
        "extract-knowledge": pipeline.extract_knowledge,
        "build-materials": pipeline.build_materials,
        "generate-topic": pipeline.generate_topic,
        "generate-world": pipeline.generate_world,
        "generate-characters": pipeline.generate_characters,
        "generate-outline": pipeline.generate_outline,
        "generate-chapter-plan": pipeline.generate_chapter_plan,
        "draft": pipeline.draft,
        "review": pipeline.review,
        "revise": pipeline.revise,
        "analyze-feedback": pipeline.analyze_feedback,
    }
    if step not in allowed:
        raise ValueError(f"unsupported step: {step}")
    return allowed[step](root, input_path)


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


try:
    app = create_app()
except RuntimeError:  # pragma: no cover - optional dependency boundary
    app = None
