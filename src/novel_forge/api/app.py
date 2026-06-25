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
        from pydantic import BaseModel
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

    class PipelineRunRequest(BaseModel):
        sample: bool = False
        async_task: bool = True

    class StepRunRequest(BaseModel):
        step: str
        input_path: str | None = None
        async_task: bool = True

    class ProjectCreateRequest(BaseModel):
        title: str
        series_title: str | None = None
        book_number: int | None = None

    class ProjectConfigRequest(BaseModel):
        genre: str | None = None
        target_platform: str | None = None
        target_word_count: int | None = None
        update_cadence: str | None = None
        quality_threshold: int | None = None
        audience: str | None = None
        status: str | None = None

    class ProjectDuplicateRequest(BaseModel):
        title: str | None = None
        series_title: str | None = None
        book_number: int | None = None
        copy_references: bool = True

    class BatchDeconstructRequest(BaseModel):
        input_path: str
        title: str | None = None
        rights_authorization: str = "unknown"
        license_name: str = ""
        copyright_note: str = ""
        source_url: str = ""
        allow_downstream_generation: bool = False
        workspace_path: str | None = None
        analysis_mode: str = "auto"
        async_task: bool = True

    class DraftGenerateRequest(BaseModel):
        chapter_plan_path: str | None = None
        workspace_path: str | None = None
        chapter: int | None = None
        update_workspace: bool = True

    class ReviewRunRequest(BaseModel):
        draft_path: str | None = None
        workspace_path: str | None = None
        chapter: int | None = None
        comparison: bool = False
        update_workspace: bool = True

    class RevisionPlanRequest(BaseModel):
        review_path: str | None = None
        workspace_path: str | None = None

    class TaskRetryRequest(BaseModel):
        status_path: str | None = None
        run_id: str | None = None
        step: str | None = None
        workspace_path: str | None = None
        async_task: bool = False

    class TaskCancelRequest(BaseModel):
        task_id: str
        terminate: bool = False
        signal: str = "SIGTERM"

    class TaskControlRequest(BaseModel):
        max_concurrent_batches: int | None = None
        max_concurrent_steps: int | None = None

    class DeadLetterRetryRequest(BaseModel):
        dead_letter_path: str

    class BatchItemRetryRequest(BaseModel):
        item_path: str
        workspace_path: str | None = None

    class BatchItemsBulkRetryRequest(BaseModel):
        item_paths: list[str]
        workspace_path: str | None = None

    class BatchItemReviewRequest(BaseModel):
        item_path: str
        decision: str
        note: str | None = None

    class BatchItemContinueRequest(BaseModel):
        item_path: str
        decomposition_path: str | None = None
        knowledge_path: str | None = None
        workspace_path: str | None = None

    class BatchItemHandoffRequest(BaseModel):
        item_path: str
        reason: str = ""
        workspace_path: str | None = None

    class AssetCollectionRequest(BaseModel):
        title: str
        purpose: str = "task_input"
        asset_paths: list[str]
        tags: list[str] = []
        workspace_path: str | None = None

    class AssetEditRequest(BaseModel):
        path: str
        title: str | None = None
        tags: list[str] | None = None
        status: str | None = None
        notes: str | None = None
        risk_level: str | None = None
        rights_authorization: str | None = None
        license_name: str | None = None
        copyright_note: str | None = None
        source_url: str | None = None
        allow_downstream_generation: bool | None = None

    class AssetContentEditRequest(BaseModel):
        path: str
        content: dict[str, Any]

    class DraftSaveRequest(BaseModel):
        draft_path: str
        text: str
        title: str | None = None
        status: str = "edited"
        workspace_path: str | None = None
        chapter: int | None = None

    class DraftExportRequest(BaseModel):
        draft_path: str
        format: str = "markdown"

    class ReviewIssueStatusRequest(BaseModel):
        review_path: str
        issue_index: int
        status: str
        note: str | None = None

    class RevisionApplyRequest(BaseModel):
        revision_path: str
        draft_path: str | None = None
        workspace_path: str | None = None
        confirmed: bool = False
        review_after: bool = True

    class HandoffDeconstructRequest(BaseModel):
        input_path: str
        genre: str = ""
        target_reader: str = ""
        purpose: str = ""
        workspace_path: str | None = None

    class HandoffKnowledgeRequest(BaseModel):
        input_path: str
        discipline: str = ""
        credibility: str = ""
        scope: str = ""
        project_context: str = ""
        workspace_path: str | None = None

    class GitHubKnowledgeHandoffRequest(BaseModel):
        repo_refs: list[str]
        discipline: str = ""
        credibility: str = "registered GitHub source metadata; license review required before raw access"
        scope: str = ""
        project_context: str = ""
        workspace_path: str | None = None

    class HandoffOutputRequest(BaseModel):
        handoff_path: str
        output_path: str
        mark_completed: bool = True
        workspace_path: str | None = None
        auto_continue_batch: bool = True

    class HandoffAcceptanceRequest(BaseModel):
        handoff_path: str
        check_index: int
        status: str
        note: str | None = None

    class HandoffRetryRequest(BaseModel):
        handoff_path: str
        reason: str = ""
        workspace_path: str | None = None

    class HandoffFailRequest(BaseModel):
        handoff_path: str
        reason: str = ""

    class ProjectScopeAuditRequest(BaseModel):
        project_id: str | None = None
        repair: bool = False

    class LocalRestoreRequest(BaseModel):
        backup_path: str
        confirm: bool = False

    register_product_routes(
        app,
        app_settings,
        {
            "ProjectCreateRequest": ProjectCreateRequest,
            "ProjectConfigRequest": ProjectConfigRequest,
            "ProjectDuplicateRequest": ProjectDuplicateRequest,
            "BatchDeconstructRequest": BatchDeconstructRequest,
            "DraftGenerateRequest": DraftGenerateRequest,
            "ReviewRunRequest": ReviewRunRequest,
            "RevisionPlanRequest": RevisionPlanRequest,
            "TaskRetryRequest": TaskRetryRequest,
            "TaskCancelRequest": TaskCancelRequest,
            "TaskControlRequest": TaskControlRequest,
            "DeadLetterRetryRequest": DeadLetterRetryRequest,
            "BatchItemRetryRequest": BatchItemRetryRequest,
            "BatchItemsBulkRetryRequest": BatchItemsBulkRetryRequest,
            "BatchItemReviewRequest": BatchItemReviewRequest,
            "BatchItemContinueRequest": BatchItemContinueRequest,
            "BatchItemHandoffRequest": BatchItemHandoffRequest,
            "AssetCollectionRequest": AssetCollectionRequest,
            "AssetEditRequest": AssetEditRequest,
            "AssetContentEditRequest": AssetContentEditRequest,
            "DraftSaveRequest": DraftSaveRequest,
            "DraftExportRequest": DraftExportRequest,
            "ReviewIssueStatusRequest": ReviewIssueStatusRequest,
            "RevisionApplyRequest": RevisionApplyRequest,
            "HandoffDeconstructRequest": HandoffDeconstructRequest,
            "HandoffKnowledgeRequest": HandoffKnowledgeRequest,
            "GitHubKnowledgeHandoffRequest": GitHubKnowledgeHandoffRequest,
            "HandoffOutputRequest": HandoffOutputRequest,
            "HandoffAcceptanceRequest": HandoffAcceptanceRequest,
            "HandoffRetryRequest": HandoffRetryRequest,
            "HandoffFailRequest": HandoffFailRequest,
            "ProjectScopeAuditRequest": ProjectScopeAuditRequest,
            "LocalRestoreRequest": LocalRestoreRequest,
        },
    )

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
