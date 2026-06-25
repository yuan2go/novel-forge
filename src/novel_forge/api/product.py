from __future__ import annotations

import asyncio
import difflib
import hashlib
import html
import json
import shutil
import zipfile
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any

from novel_forge.core.constants import DATA_DIRS
from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.modules.ingestion.service import discover_source_files
from novel_forge.modules.source_intake import (
    create_github_source_note,
    list_github_knowledge_sources,
    list_source_policies,
)
from novel_forge.agents import enforce_agent_action
from novel_forge.api.health import assemble_project_health_report
from novel_forge.schemas import AssetCollection, BatchTaskItem, DraftChapter, ProjectWorkspaceState, validate_common_fields
from novel_forge.storage.object_store import MinioObjectStore
from novel_forge.storage.local import LocalStorage
from novel_forge.storage.postgres import PostgresAssetStore
from novel_forge.workflows import pipeline
from novel_forge.workflows.status import build_recovery_instruction, execute_task

PRODUCT_STEPS = [
    "ingest",
    "clean",
    "decompose",
    "extract-knowledge",
    "build-materials",
    "generate-topic",
    "generate-world",
    "generate-characters",
    "generate-outline",
    "generate-chapter-plan",
    "draft",
    "review",
    "revise",
]

DEFAULT_PROJECT_CONFIG = {
    "genre": "",
    "target_platform": "",
    "target_word_count": 0,
    "update_cadence": "",
    "quality_threshold": 80,
    "audience": "",
    "status": "active",
}

PROJECT_STATUSES = {"active", "paused", "archived", "deleted"}
ASSET_STATUSES = {"active", "draft", "needs_review", "approved", "archived", "blocked"}
RISK_LEVELS = {"low", "medium", "high", "unknown"}
REVIEW_ISSUE_STATUSES = {"open", "accepted", "ignored", "fixed"}
BATCH_REVIEW_DECISIONS = {"approved", "rejected", "needs_revision"}
BATCH_ANALYSIS_MODES = {"auto", "claude_code"}
HANDOFF_ACCEPTANCE_STATUSES = {"pending", "accepted", "needs_fix", "rejected"}
TASK_CONTROL_RELATIVE_PATH = Path("data/indexes/task-control.json")
QUEUE_PRESSURE_RELATIVE_PATH = Path("data/indexes/queue-pressure.json")
DEFAULT_TASK_CONTROL = {"max_concurrent_batches": 1, "max_concurrent_steps": 1}
EXPORT_FORMATS = {"markdown", "docx", "epub"}
BATCH_PIPELINE_STEPS = ["ingest", "clean", "decompose", "extract-knowledge", "build-materials"]
BATCH_CLAUDE_STEPS = ["ingest", "clean", "claude-handoff"]


def register_product_routes(app: Any, app_settings: Any, models: dict[str, Any]) -> None:
    from fastapi import HTTPException, Query, Request
    from fastapi.responses import StreamingResponse

    @app.middleware("http")
    async def postgres_index_sync_middleware(request: Request, call_next):
        response = await call_next(request)
        if request.method in {"POST", "PATCH", "DELETE"} and response.status_code < 500:
            _sync_postgres_best_effort(app_settings)
        return response

    ProjectCreateRequest = models["ProjectCreateRequest"]
    ProjectConfigRequest = models["ProjectConfigRequest"]
    ProjectDuplicateRequest = models["ProjectDuplicateRequest"]
    BatchDeconstructRequest = models["BatchDeconstructRequest"]
    DraftGenerateRequest = models["DraftGenerateRequest"]
    ReviewRunRequest = models["ReviewRunRequest"]
    RevisionPlanRequest = models["RevisionPlanRequest"]
    TaskRetryRequest = models["TaskRetryRequest"]
    TaskCancelRequest = models["TaskCancelRequest"]
    TaskControlRequest = models["TaskControlRequest"]
    DeadLetterRetryRequest = models["DeadLetterRetryRequest"]
    BatchItemRetryRequest = models["BatchItemRetryRequest"]
    BatchItemsBulkRetryRequest = models["BatchItemsBulkRetryRequest"]
    BatchItemReviewRequest = models["BatchItemReviewRequest"]
    BatchItemContinueRequest = models["BatchItemContinueRequest"]
    BatchItemHandoffRequest = models["BatchItemHandoffRequest"]
    AssetCollectionRequest = models["AssetCollectionRequest"]
    AssetEditRequest = models["AssetEditRequest"]
    AssetContentEditRequest = models["AssetContentEditRequest"]
    DraftSaveRequest = models["DraftSaveRequest"]
    DraftExportRequest = models["DraftExportRequest"]
    ReviewIssueStatusRequest = models["ReviewIssueStatusRequest"]
    RevisionApplyRequest = models["RevisionApplyRequest"]
    HandoffDeconstructRequest = models["HandoffDeconstructRequest"]
    HandoffKnowledgeRequest = models["HandoffKnowledgeRequest"]
    GitHubKnowledgeHandoffRequest = models["GitHubKnowledgeHandoffRequest"]
    HandoffOutputRequest = models["HandoffOutputRequest"]
    HandoffAcceptanceRequest = models["HandoffAcceptanceRequest"]
    HandoffRetryRequest = models["HandoffRetryRequest"]
    HandoffFailRequest = models["HandoffFailRequest"]
    ProjectScopeAuditRequest = models["ProjectScopeAuditRequest"]
    LocalRestoreRequest = models["LocalRestoreRequest"]

    @app.get("/product/projects")
    def projects(include_deleted: bool = False) -> list[dict[str, Any]]:
        return indexed_list_projects(app_settings, LocalStorage(app_settings.root), include_deleted=include_deleted)

    @app.get("/product/series")
    def series(include_deleted: bool = False) -> list[dict[str, Any]]:
        return indexed_list_series(app_settings, LocalStorage(app_settings.root), include_deleted=include_deleted)

    @app.post("/product/projects")
    def create_project(request: ProjectCreateRequest) -> dict[str, Any]:
        try:
            path = pipeline.init_workspace(app_settings.root, request.title, request.series_title, request.book_number)
            return project_detail(LocalStorage(app_settings.root), str(path))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.patch("/product/projects/{project_id}/config")
    def update_project(project_id: str, request: ProjectConfigRequest) -> dict[str, Any]:
        storage = LocalStorage(app_settings.root)
        try:
            return update_project_config(storage, project_id, _model_data(request))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/product/projects/{project_id}/duplicate")
    def duplicate_project_endpoint(project_id: str, request: ProjectDuplicateRequest) -> dict[str, Any]:
        storage = LocalStorage(app_settings.root)
        try:
            return duplicate_project(storage, project_id, _model_data(request))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/product/projects/{project_id}/archive")
    def archive_project(project_id: str) -> dict[str, Any]:
        storage = LocalStorage(app_settings.root)
        try:
            return transition_project_status(storage, project_id, "archived", "archive")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/product/projects/{project_id}/pause")
    def pause_project(project_id: str) -> dict[str, Any]:
        storage = LocalStorage(app_settings.root)
        try:
            return transition_project_status(storage, project_id, "paused", "pause")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/product/projects/{project_id}/restore")
    def restore_project(project_id: str) -> dict[str, Any]:
        storage = LocalStorage(app_settings.root)
        try:
            return transition_project_status(storage, project_id, "active", "restore")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/product/projects/{project_id}")
    def delete_project(project_id: str) -> dict[str, Any]:
        storage = LocalStorage(app_settings.root)
        try:
            return transition_project_status(storage, project_id, "deleted", "soft-delete")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/product/projects/{project_id}/assets")
    def project_asset_list(
        project_id: str,
        category: str | None = None,
        asset_type: str | None = Query(default=None, alias="type"),
        keyword: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        storage = LocalStorage(app_settings.root)
        try:
            return indexed_project_assets(
                app_settings,
                storage,
                project_id,
                category=category,
                asset_type=asset_type,
                keyword=keyword,
                limit=limit,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/product/projects/{project_id}")
    def get_project(project_id: str) -> dict[str, Any]:
        storage = LocalStorage(app_settings.root)
        try:
            return project_detail(storage, project_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/product/projects/audit/scope")
    def project_scope_audit_endpoint(project_id: str | None = None) -> dict[str, Any]:
        try:
            return project_scope_audit(LocalStorage(app_settings.root), project_id=project_id, repair=False)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/product/projects/audit/scope")
    def repair_project_scope_audit_endpoint(request: ProjectScopeAuditRequest) -> dict[str, Any]:
        try:
            return project_scope_audit(LocalStorage(app_settings.root), project_id=request.project_id, repair=request.repair)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/product/tasks")
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

    @app.get("/product/tasks/timeline")
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

    @app.get("/product/tasks/control")
    def task_control() -> dict[str, Any]:
        try:
            return task_control_status(app_settings)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/product/tasks/recovery-workbench")
    def task_recovery_workbench_endpoint(project_id: str | None = None) -> dict[str, Any]:
        try:
            return task_recovery_workbench(app_settings, project_id=project_id)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.patch("/product/tasks/control")
    def update_task_control_endpoint(request: TaskControlRequest) -> dict[str, Any]:
        try:
            return update_task_control(app_settings.root, _model_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/product/tasks/dead-letters")
    def task_dead_letters(limit: int = 100) -> list[dict[str, Any]]:
        try:
            return task_dead_letter_rows(app_settings.root, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/product/tasks/dead-letters/retry")
    def retry_dead_letter_endpoint(request: DeadLetterRetryRequest) -> dict[str, Any]:
        try:
            task = retry_dead_letter(app_settings.root, request.dead_letter_path)
            return {"mode": "async", "task_id": task.id}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/product/tasks/cancel")
    def cancel_task_endpoint(request: TaskCancelRequest) -> dict[str, Any]:
        try:
            return cancel_celery_task(request.task_id, terminate=request.terminate, signal=request.signal)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/product/tasks/events")
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

    @app.get("/product/tasks/recovery")
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

    @app.post("/product/tasks/retry")
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

    @app.get("/product/assets/detail")
    def product_asset_detail(path: str = Query(...)) -> dict[str, Any]:
        storage = LocalStorage(app_settings.root)
        try:
            return asset_detail(storage, path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.patch("/product/assets/detail")
    def edit_product_asset(request: AssetEditRequest) -> dict[str, Any]:
        storage = LocalStorage(app_settings.root)
        try:
            return update_asset_metadata(storage, request.path, _model_data(request))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.patch("/product/assets/content")
    def edit_product_asset_content(request: AssetContentEditRequest) -> dict[str, Any]:
        storage = LocalStorage(app_settings.root)
        try:
            return update_asset_content(storage, request.path, request.content)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/product/assets/versions")
    def asset_versions(path: str = Query(...)) -> dict[str, Any]:
        try:
            return asset_versions_and_diff(LocalStorage(app_settings.root), path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/product/assets/graph")
    def asset_graph(path: str = Query(...), depth: int = 1) -> dict[str, Any]:
        try:
            return asset_reference_graph(LocalStorage(app_settings.root), path, depth=depth)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/product/assets/collections")
    def create_asset_collection(request: AssetCollectionRequest) -> dict[str, Any]:
        try:
            return save_asset_collection(LocalStorage(app_settings.root), _model_data(request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/product/handoffs")
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

    @app.get("/product/sources/policies")
    def source_policies(category: str | None = None) -> list[dict[str, Any]]:
        return list_source_policies(category=category)

    @app.get("/product/sources/github")
    def github_knowledge_sources(
        category: str | None = None,
        allowed_pipeline: str | None = None,
        max_risk: str | None = None,
    ) -> list[dict[str, Any]]:
        return list_github_knowledge_sources(category=category, allowed_pipeline=allowed_pipeline, max_risk=max_risk)

    @app.post("/product/handoffs/deconstruct")
    def create_deconstruct_handoff(request: HandoffDeconstructRequest) -> dict[str, Any]:
        try:
            return create_product_deconstruction_handoff(app_settings.root, _model_data(request))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/product/handoffs/knowledge")
    def create_knowledge_handoff(request: HandoffKnowledgeRequest) -> dict[str, Any]:
        try:
            return create_product_knowledge_handoff(app_settings.root, _model_data(request))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/product/handoffs/github-knowledge")
    def create_github_knowledge_handoff_endpoint(request: GitHubKnowledgeHandoffRequest) -> dict[str, Any]:
        try:
            return create_github_knowledge_handoff(app_settings.root, _model_data(request))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/product/handoffs/validate-output")
    def validate_handoff_output_endpoint(request: HandoffOutputRequest) -> dict[str, Any]:
        try:
            return validate_handoff_output(app_settings.root, _model_data(request))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/product/handoffs/bind-output")
    def bind_handoff_output_endpoint(request: HandoffOutputRequest) -> dict[str, Any]:
        try:
            return bind_handoff_output(app_settings.root, _model_data(request))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/product/handoffs/acceptance")
    def handoff_acceptance_endpoint(handoff_path: str = Query(...)) -> dict[str, Any]:
        try:
            return handoff_acceptance_status(app_settings.root, handoff_path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.patch("/product/handoffs/acceptance")
    def update_handoff_acceptance_endpoint(request: HandoffAcceptanceRequest) -> dict[str, Any]:
        try:
            return update_handoff_acceptance(app_settings.root, _model_data(request))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/product/handoffs/fail")
    def fail_handoff_endpoint(request: HandoffFailRequest) -> dict[str, Any]:
        try:
            return fail_handoff(app_settings.root, _model_data(request))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/product/handoffs/retry")
    def retry_handoff_endpoint(request: HandoffRetryRequest) -> dict[str, Any]:
        try:
            return retry_handoff(app_settings.root, _model_data(request))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/product/system/postgres/strict-check")
    def postgres_strict_check_endpoint(sync: bool = False) -> dict[str, Any]:
        try:
            return postgres_strict_local_prod_check(app_settings, sync=sync, raise_on_failure=False)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/product/system/health")
    def product_health_endpoint(project_id: str | None = None) -> dict[str, Any]:
        try:
            return project_health_report(app_settings, project_id=project_id)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/product/system/backups")
    def create_backup_endpoint() -> dict[str, Any]:
        try:
            return create_local_backup(app_settings)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/product/system/backups")
    def list_backups_endpoint(limit: int = 20) -> list[dict[str, Any]]:
        try:
            return list_local_backups(app_settings.root, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/product/system/restore")
    def restore_backup_endpoint(request: LocalRestoreRequest) -> dict[str, Any]:
        try:
            return restore_local_backup(app_settings.root, request.backup_path, confirm=request.confirm)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/product/uploads")
    async def upload_sources(request: Request) -> dict[str, Any]:
        try:
            body = await request.body()
            return receive_uploads(app_settings, body, request.headers.get("content-type", ""))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/product/batch/items")
    def batch_items(
        batch_id: str | None = None,
        status: str | None = None,
        project_id: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        try:
            return list_batch_items(LocalStorage(app_settings.root), batch_id=batch_id, status=status, project_id=project_id, offset=offset, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/product/batch/items/retry")
    def retry_batch_item_endpoint(request: BatchItemRetryRequest) -> dict[str, Any]:
        try:
            return retry_batch_item(app_settings.root, request.item_path, workspace_path=request.workspace_path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/product/batch/items/retry-bulk")
    def retry_batch_items_bulk_endpoint(request: BatchItemsBulkRetryRequest) -> dict[str, Any]:
        try:
            return retry_batch_items_bulk(app_settings.root, request.item_paths, workspace_path=request.workspace_path)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.patch("/product/batch/items/review")
    def review_batch_item_endpoint(request: BatchItemReviewRequest) -> dict[str, Any]:
        try:
            return review_batch_item(LocalStorage(app_settings.root), _model_data(request))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/product/batch/items/continue")
    def continue_batch_item_endpoint(request: BatchItemContinueRequest) -> dict[str, Any]:
        try:
            return continue_batch_handoff(app_settings.root, _model_data(request))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/product/batch/items/handoff/regenerate")
    def regenerate_batch_handoff_endpoint(request: BatchItemHandoffRequest) -> dict[str, Any]:
        try:
            return regenerate_batch_handoff(app_settings.root, _model_data(request))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/product/batch/items/handoff/void")
    def void_batch_handoff_endpoint(request: BatchItemHandoffRequest) -> dict[str, Any]:
        try:
            return void_batch_handoff(app_settings.root, _model_data(request))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/product/batch/deconstruct")
    def batch_deconstruct(request: BatchDeconstructRequest) -> dict[str, Any]:
        if request.async_task:
            try:
                task = _enqueue(
                    "batch_deconstruct_task",
                    str(app_settings.root),
                    request.input_path,
                    request.title,
                    request.rights_authorization,
                    request.license_name,
                    request.copyright_note,
                    request.source_url,
                    request.allow_downstream_generation,
                    request.workspace_path,
                    request.analysis_mode,
                )
            except Exception as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            return {"mode": "async", "task_id": task.id}
        try:
            result = run_batch_deconstruct(
                app_settings.root,
                request.input_path,
                title=request.title,
                rights_authorization=request.rights_authorization,
                license_name=request.license_name,
                copyright_note=request.copyright_note,
                source_url=request.source_url,
                allow_downstream_generation=request.allow_downstream_generation,
                workspace_path=request.workspace_path,
                analysis_mode=request.analysis_mode,
            )
            return {"mode": "sync", **result}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/product/drafts")
    def drafts(project_id: str | None = None) -> dict[str, Any]:
        try:
            return draft_workbench(LocalStorage(app_settings.root), project_id=project_id)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/product/drafts/editor")
    def draft_editor_endpoint(path: str = Query(...)) -> dict[str, Any]:
        try:
            return draft_editor(LocalStorage(app_settings.root), path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/product/drafts/generate")
    def generate_draft(request: DraftGenerateRequest) -> dict[str, Any]:
        try:
            path = pipeline.draft(app_settings.root, request.chapter_plan_path)
            outputs = {"draft_path": _display_path(app_settings.root, path)}
            storage = LocalStorage(app_settings.root)
            if request.update_workspace:
                workspace_path = pipeline.update_workspace(
                    app_settings.root,
                    input_path=str(path),
                    workspace_path=request.workspace_path,
                    chapter=request.chapter,
                    status="drafted",
                )
                outputs["workspace_path"] = _display_path(app_settings.root, workspace_path)
                attach_assets_to_project(storage, [path], str(workspace_path), role="draft")
            elif request.workspace_path:
                attach_assets_to_project(storage, [path], request.workspace_path, role="draft")
            return outputs
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/product/drafts/save")
    def save_draft_endpoint(request: DraftSaveRequest) -> dict[str, Any]:
        try:
            return save_draft_edit(app_settings.root, _model_data(request))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/product/drafts/diff")
    def draft_diff_endpoint(base_path: str, target_path: str) -> dict[str, Any]:
        try:
            return draft_diff(LocalStorage(app_settings.root), base_path, target_path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/product/drafts/export")
    def export_draft_endpoint(request: DraftExportRequest) -> dict[str, Any]:
        try:
            return export_draft(app_settings.root, request.draft_path, request.format)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/product/reviews/run")
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

    @app.post("/product/revisions/plan")
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

    @app.patch("/product/reviews/issues")
    def update_review_issue_endpoint(request: ReviewIssueStatusRequest) -> dict[str, Any]:
        try:
            return update_review_issue_status(LocalStorage(app_settings.root), _model_data(request))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/product/revisions/apply")
    def apply_revision_endpoint(request: RevisionApplyRequest) -> dict[str, Any]:
        try:
            return apply_revision_plan(app_settings.root, _model_data(request))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


def list_projects(storage: LocalStorage, include_deleted: bool = False) -> list[dict[str, Any]]:
    storage.ensure_layout()
    projects = []
    for path in reversed(storage.list_json("workspaces")):
        data = storage.read_json(path)
        if not isinstance(data, dict):
            continue
        summary = _project_summary(storage, path, data)
        if not include_deleted and summary["project_config"].get("status") == "deleted":
            continue
        projects.append(summary)
    return projects


def indexed_list_projects(settings: Any, storage: LocalStorage, include_deleted: bool = False) -> list[dict[str, Any]]:
    store = _postgres_store(settings)
    if store:
        try:
            rows = []
            for row in store.list_projects(include_deleted=include_deleted):
                data = row.get("payload", {})
                if not isinstance(data, dict):
                    continue
                rows.append({**_project_summary(storage, storage.root / row["workspace_path"], data), "index_source": "postgres"})
            return rows
        except Exception:
            if getattr(settings, "postgres_write_strict", False):
                raise
    return [{**row, "index_source": "json"} for row in list_projects(storage, include_deleted=include_deleted)]


def list_series(storage: LocalStorage, include_deleted: bool = False) -> list[dict[str, Any]]:
    return _series_from_projects(list_projects(storage, include_deleted=include_deleted))


def indexed_list_series(settings: Any, storage: LocalStorage, include_deleted: bool = False) -> list[dict[str, Any]]:
    return _series_from_projects(indexed_list_projects(settings, storage, include_deleted=include_deleted))


def _series_from_projects(projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for project in projects:
        series_title = str(project.get("series_title") or "Standalone")
        grouped.setdefault(series_title, []).append(project)

    rows = []
    for series_title, projects in grouped.items():
        ordered_projects = sorted(
            projects,
            key=lambda item: (
                item.get("book_number") is None,
                item.get("book_number") or 0,
                str(item.get("title", "")),
            ),
        )
        book_numbers = {item.get("book_number") for item in ordered_projects if item.get("book_number") is not None}
        rows.append(
            {
                "series_title": series_title,
                "book_count": len(book_numbers) or len(ordered_projects),
                "project_count": len(ordered_projects),
                "latest_updated_at": max((str(item.get("updated_at", "")) for item in ordered_projects), default=""),
                "projects": [
                    {
                        "project_id": item.get("project_id", ""),
                        "title": item.get("title", ""),
                        "book_number": item.get("book_number"),
                        "status": item.get("status", ""),
                        "path": item.get("path", ""),
                        "chapter_count": item.get("chapter_count", 0),
                        "open_issue_count": item.get("open_issue_count", 0),
                    }
                    for item in ordered_projects
                ],
            }
        )
    return sorted(rows, key=lambda item: str(item["series_title"]).lower())


def project_detail(storage: LocalStorage, project_id_or_path: str) -> dict[str, Any]:
    path = _workspace_path_by_id_or_path(storage, project_id_or_path)
    data = storage.read_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"workspace JSON must be an object: {path}")
    return {
        **_project_summary(storage, path, data),
        "content": data.get("content", {}),
        "metadata": data.get("metadata", {}),
        "references": data.get("references", []),
        "assets": project_assets(storage, project_id_or_path, limit=20),
    }


def transition_project_status(
    storage: LocalStorage,
    project_id_or_path: str,
    status: str,
    action: str,
    reason: str = "",
) -> dict[str, Any]:
    if status not in PROJECT_STATUSES:
        raise ValueError(f"project status must be one of: {', '.join(sorted(PROJECT_STATUSES))}")
    path = _workspace_path_by_id_or_path(storage, project_id_or_path)
    data = storage.read_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"workspace JSON must be an object: {path}")
    current_status = _project_config(data).get("status", "active")
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    config = _project_config(data)
    config["status"] = status
    content["project_config"] = config
    data["content"] = content
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    metadata["project_status"] = status
    metadata["status"] = status
    if status == "deleted":
        metadata["deleted_at"] = utc_now()
    elif status == "active":
        metadata.pop("deleted_at", None)
    data["metadata"] = metadata
    _record_lifecycle_event(data, action, current_status, status, reason)
    data["updated_at"] = utc_now()
    storage.write_json(path, data)
    return project_detail(storage, str(path))


def duplicate_project(storage: LocalStorage, project_id_or_path: str, patch: dict[str, Any]) -> dict[str, Any]:
    path = _workspace_path_by_id_or_path(storage, project_id_or_path)
    data = storage.read_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"workspace JSON must be an object: {path}")
    content = json.loads(json.dumps(data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}))
    metadata = json.loads(json.dumps(data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}))
    old_project_id = str(content.get("project_id", data.get("id", "")))
    title = str(patch.get("title") or f"{data.get('title') or data.get('name') or 'Project'} Copy")
    series_title = patch.get("series_title", metadata.get("series_title", ""))
    book_number = patch.get("book_number", metadata.get("book_number"))
    new_project_id = make_id("project", f"{series_title or title}:book-{book_number}" if book_number is not None else title)

    memory = content.get("memory", {}) if isinstance(content.get("memory", {}), dict) else {}
    memory["series_title"] = series_title or ""
    memory["book_number"] = book_number
    content["memory"] = memory
    content["project_id"] = new_project_id
    config = _project_config(data)
    config["status"] = "active"
    content["project_config"] = config

    metadata.update(
        {
            "project_id": new_project_id,
            "series_title": series_title or "",
            "book_number": book_number,
            "project_status": "active",
            "status": "active",
            "duplicated_from_project_id": old_project_id,
            "duplicated_from_workspace_path": _display_path(storage.root, path),
        }
    )
    metadata.pop("deleted_at", None)
    references = [str(item) for item in data.get("references", [])] if patch.get("copy_references", True) else []
    duplicated = ProjectWorkspaceState(
        title=title,
        source=old_project_id,
        tags=_dedupe_list([*data.get("tags", []), "project", "duplicated"]),
        content=content,
        metadata=metadata,
        references=references,
    )
    duplicated_dict = duplicated.to_dict()
    _record_lifecycle_event(duplicated_dict, "duplicate", "none", "active", f"duplicated from {old_project_id}")
    duplicated_asset = ProjectWorkspaceState.from_dict(duplicated_dict)
    new_path = storage.write_asset("workspaces", duplicated_asset)
    return project_detail(storage, str(new_path))


def update_project_config(storage: LocalStorage, project_id_or_path: str, patch: dict[str, Any]) -> dict[str, Any]:
    path = _workspace_path_by_id_or_path(storage, project_id_or_path)
    data = storage.read_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"workspace JSON must be an object: {path}")
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    config = _project_config(data)
    for key, value in patch.items():
        if key in DEFAULT_PROJECT_CONFIG and value is not None:
            if key == "status" and value not in PROJECT_STATUSES:
                raise ValueError(f"project status must be one of: {', '.join(sorted(PROJECT_STATUSES))}")
            config[key] = value
    content["project_config"] = config
    data["content"] = content
    data["updated_at"] = utc_now()
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    metadata["project_status"] = config.get("status", "active")
    metadata["status"] = config.get("status", "active")
    metadata["target_platform"] = config.get("target_platform", "")
    metadata["quality_threshold"] = config.get("quality_threshold", 80)
    data["metadata"] = metadata
    _record_lifecycle_event(data, "config", "", config.get("status", "active"), "project config updated")
    storage.write_json(path, data)
    return project_detail(storage, str(path))


def project_assets(
    storage: LocalStorage,
    project_id_or_path: str,
    category: str | None = None,
    asset_type: str | None = None,
    keyword: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    if limit < 1:
        raise ValueError("limit must be greater than zero")
    project = _project_identity(storage, project_id_or_path)
    categories = [category] if category else list(DATA_DIRS)
    keyword_lower = keyword.lower() if keyword else ""
    if category and category not in DATA_DIRS:
        raise ValueError(f"unknown data category: {category}")
    rows = []
    for item_category in categories:
        for path in reversed(storage.list_json(item_category)):
            data = storage.read_json(path)
            if not isinstance(data, dict):
                continue
            if asset_type and data.get("type") != asset_type:
                continue
            if keyword_lower and keyword_lower not in _asset_search_text(data):
                continue
            if not _belongs_to_project(data, path, project):
                continue
            rows.append(_project_asset_row(storage, path, item_category, data, index_source="json"))
            if len(rows) >= limit:
                return rows
    return rows


def indexed_project_assets(
    settings: Any,
    storage: LocalStorage,
    project_id_or_path: str,
    category: str | None = None,
    asset_type: str | None = None,
    keyword: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    store = _postgres_store(settings)
    if store:
        try:
            project = _project_identity(storage, project_id_or_path)
            records = store.list_payload_records(
                asset_type=asset_type,
                category=category,
                project_id=project["project_id"],
                limit=max(limit * 20, 500),
            )
            if not records:
                records = store.list_payload_records(asset_type=asset_type, category=category, limit=max(limit * 20, 500))
            rows = []
            keyword_lower = keyword.lower() if keyword else ""
            for record in records:
                data = record.get("payload", {})
                if not isinstance(data, dict):
                    continue
                path = storage.root / str(record.get("path", ""))
                if keyword_lower and keyword_lower not in _asset_search_text(data):
                    continue
                if not _belongs_to_project(data, path, project):
                    continue
                rows.append(
                    _project_asset_row(
                        storage,
                        path,
                        str(record.get("category", "")),
                        data,
                        index_source="postgres",
                    )
                )
                if len(rows) >= limit:
                    return rows
            return rows
        except Exception:
            if getattr(settings, "postgres_write_strict", False):
                raise
    return project_assets(storage, project_id_or_path, category=category, asset_type=asset_type, keyword=keyword, limit=limit)


def attach_assets_to_project(
    storage: LocalStorage,
    asset_paths: list[str | Path],
    project_id_or_path: str,
    role: str = "",
) -> list[str]:
    project = _project_identity(storage, project_id_or_path)
    attached: list[str] = []
    for asset_path in asset_paths:
        path = resolve_path(storage.root, asset_path).resolve()
        path.relative_to(storage.root)
        if not path.exists() or not path.is_file():
            continue
        data = storage.read_json(path)
        if not isinstance(data, dict):
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        metadata.update(
            {
                "project_id": project["project_id"],
                "workspace_id": project["workspace_id"],
                "workspace_path": project["workspace_path"],
                "project_asset_role": role or str(data.get("type", "")),
                "project_attached_at": utc_now(),
            }
        )
        data["metadata"] = metadata
        references = [str(item) for item in data.get("references", [])]
        for ref in [project["workspace_id"], project["project_id"]]:
            if ref and ref not in references:
                references.append(ref)
        data["references"] = references
        data["updated_at"] = utc_now()
        storage.write_json(path, data)
        attached.append(_display_path(storage.root, path))
    _add_workspace_references(storage, project, attached)
    return attached


def project_scope_audit(storage: LocalStorage, project_id: str | None = None, repair: bool = False) -> dict[str, Any]:
    storage.ensure_layout()
    selected_project = _project_identity(storage, project_id) if project_id else None
    projects = [_project_identity(storage, _display_path(storage.root, path)) for path in storage.list_json("workspaces")]
    project_by_id = {project["project_id"]: project for project in projects}
    project_by_workspace = {project["workspace_path"]: project for project in projects}
    project_by_workspace.update({project["workspace_id"]: project for project in projects if project.get("workspace_id")})
    single_project = projects[0] if len(projects) == 1 else None

    records = _asset_records(storage)
    by_id = {record["id"]: record for record in records if record["id"]}
    by_path = {record["path"]: record for record in records if record["path"]}
    issues: list[dict[str, Any]] = []
    repairs: list[dict[str, str]] = []

    for record in records:
        data = record["data"]
        current_project_id, current_workspace_path = _record_project_scope(storage, record)
        inferred = _infer_record_project(record, by_id, by_path, project_by_id, project_by_workspace)
        if not inferred and single_project and record["type"] != "project_workspace_state":
            inferred = single_project
        if selected_project and current_project_id and current_project_id != selected_project["project_id"]:
            continue
        if selected_project and not current_project_id and inferred and inferred["project_id"] != selected_project["project_id"]:
            continue

        if record["type"] != "project_workspace_state" and not current_project_id:
            issue = {
                "kind": "unscoped_asset",
                "severity": "warning",
                "path": record["path"],
                "id": record["id"],
                "type": record["type"],
                "title": record["title"],
                "project_id": "",
                "workspace_path": "",
                "inferred_project_id": inferred["project_id"] if inferred else "",
                "inferred_workspace_path": inferred["workspace_path"] if inferred else "",
                "repairable": bool(inferred),
                "message": "asset has no project_id/workspace_path metadata",
            }
            issues.append(issue)
            if repair and inferred:
                attached = attach_assets_to_project(storage, [record["path"]], inferred["workspace_path"], role=_project_role_for_asset(record))
                if attached:
                    repairs.append({"kind": "attach_unscoped_asset", "path": record["path"], "project_id": inferred["project_id"]})
                current_project_id = inferred["project_id"]
                current_workspace_path = inferred["workspace_path"]

        if current_project_id:
            linked_project_ids = _linked_project_ids(record, by_id, by_path)
            mismatched = sorted(project_id for project_id in linked_project_ids if project_id and project_id != current_project_id)
            if mismatched:
                issues.append(
                    {
                        "kind": "cross_project_lineage",
                        "severity": "error",
                        "path": record["path"],
                        "id": record["id"],
                        "type": record["type"],
                        "title": record["title"],
                        "project_id": current_project_id,
                        "workspace_path": current_workspace_path,
                        "linked_project_ids": mismatched,
                        "repairable": False,
                        "message": "asset links to assets from another project; inspect lineage before repair",
                    }
                )

        if record["type"] == "claude_code_handoff":
            handoff_project_id, handoff_workspace = _record_project_scope(storage, record)
            if not handoff_project_id and inferred:
                handoff_project_id = inferred["project_id"]
                handoff_workspace = inferred["workspace_path"]
            issues.extend(
                _audit_handoff_outputs(
                    storage,
                    record,
                    by_id,
                    by_path,
                    handoff_project_id,
                    handoff_workspace,
                    repair,
                    repairs,
                )
            )
        if record["type"] == "batch_task_item":
            item_project_id, item_workspace = _record_project_scope(storage, record)
            if not item_project_id and inferred:
                item_project_id = inferred["project_id"]
                item_workspace = inferred["workspace_path"]
            issues.extend(
                _audit_batch_item_handoff_scope(
                    storage,
                    record,
                    by_path,
                    item_project_id,
                    item_workspace,
                    repair,
                    repairs,
                )
            )

    repaired_paths = {repair_row["path"] for repair_row in repairs}
    if repair and repaired_paths:
        # Re-run once so the caller receives the remaining issue set after automatic repairs.
        refreshed = project_scope_audit(storage, project_id=project_id, repair=False)
        refreshed["repairs"] = repairs
        refreshed["summary"]["repaired_count"] = len(repairs)
        return refreshed
    summary = {
        "issue_count": len(issues),
        "repaired_count": len(repairs),
        "unscoped_count": sum(1 for issue in issues if issue["kind"] == "unscoped_asset"),
        "cross_project_count": sum(1 for issue in issues if issue["kind"] == "cross_project_lineage"),
        "handoff_mismatch_count": sum(1 for issue in issues if issue["kind"] in {"handoff_output_mismatch", "batch_handoff_scope_mismatch"}),
        "repairable_count": sum(1 for issue in issues if issue.get("repairable")),
    }
    return {
        "project_id": selected_project["project_id"] if selected_project else "",
        "workspace_path": selected_project["workspace_path"] if selected_project else "",
        "repair": repair,
        "summary": summary,
        "issues": issues,
        "repairs": repairs,
    }


def _record_project_scope(storage: LocalStorage, record: dict[str, Any]) -> tuple[str, str]:
    data = record["data"]
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    if data.get("type") == "project_workspace_state":
        return str(content.get("project_id") or data.get("id") or ""), record["path"]
    project_id = str(metadata.get("project_id") or content.get("project_id") or "")
    workspace_path = str(metadata.get("workspace_path") or "")
    if not workspace_path and metadata.get("workspace_id"):
        try:
            workspace_path = _project_identity(storage, str(metadata.get("workspace_id")))["workspace_path"]
        except Exception:
            workspace_path = ""
    return project_id, workspace_path


def _infer_record_project(
    record: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
    by_path: dict[str, dict[str, Any]],
    project_by_id: dict[str, dict[str, Any]],
    project_by_workspace: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    candidates: dict[str, dict[str, Any]] = {}
    for value in _scope_reference_values(record["data"]):
        if value in project_by_id:
            project = project_by_id[value]
            candidates[project["project_id"]] = project
            continue
        if value in project_by_workspace:
            project = project_by_workspace[value]
            candidates[project["project_id"]] = project
            continue
        linked = by_id.get(value) or by_path.get(value)
        if linked:
            project_id, workspace_path = _project_scope_from_record_data(linked)
            if project_id and workspace_path:
                candidates[project_id] = {"project_id": project_id, "workspace_path": workspace_path}
    if len(candidates) == 1:
        return next(iter(candidates.values()))
    return None


def _project_scope_from_record_data(record: dict[str, Any]) -> tuple[str, str]:
    data = record["data"]
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    if data.get("type") == "project_workspace_state":
        return str(content.get("project_id") or data.get("id") or ""), record["path"]
    return str(metadata.get("project_id") or content.get("project_id") or ""), str(metadata.get("workspace_path") or "")


def _scope_reference_values(data: dict[str, Any]) -> set[str]:
    values = {str(item) for item in data.get("references", []) if str(item).strip()} if isinstance(data.get("references", []), list) else set()
    source = str(data.get("source", ""))
    if source:
        values.add(source)
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    for key in ["project_id", "workspace_id", "workspace_path", "handoff_id", "handoff_path", "batch_item_id"]:
        if metadata.get(key):
            values.add(str(metadata[key]))
        if content.get(key):
            values.add(str(content[key]))
    for item in content.get("output_paths", []) if isinstance(content.get("output_paths", []), list) else []:
        if str(item).strip():
            values.add(str(item))
    source_asset = content.get("source_asset", {}) if isinstance(content.get("source_asset", {}), dict) else {}
    for key in ["id", "path"]:
        if source_asset.get(key):
            values.add(str(source_asset[key]))
    for item in content.get("input_files", []) if isinstance(content.get("input_files", []), list) else []:
        if isinstance(item, dict) and item.get("path"):
            values.add(str(item["path"]))
    for item in content.get("bound_outputs", []) if isinstance(content.get("bound_outputs", []), list) else []:
        if isinstance(item, dict):
            for key in ["id", "path"]:
                if item.get(key):
                    values.add(str(item[key]))
    return values


def _linked_project_ids(record: dict[str, Any], by_id: dict[str, dict[str, Any]], by_path: dict[str, dict[str, Any]]) -> set[str]:
    linked_project_ids: set[str] = set()
    for value in _scope_reference_values(record["data"]):
        linked = by_id.get(value) or by_path.get(value)
        if not linked:
            continue
        project_id, _workspace = _project_scope_from_record_data(linked)
        if project_id:
            linked_project_ids.add(project_id)
    return linked_project_ids


def _project_role_for_asset(record: dict[str, Any]) -> str:
    if record["type"] == "claude_code_handoff":
        return "claude-handoff"
    if record["type"] in {"decomposition_report", "knowledge_card", "material_card"}:
        return "deconstruction"
    return str(record["type"] or "asset")


def _audit_handoff_outputs(
    storage: LocalStorage,
    handoff_record: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
    by_path: dict[str, dict[str, Any]],
    project_id: str,
    workspace_path: str,
    repair: bool,
    repairs: list[dict[str, str]],
) -> list[dict[str, Any]]:
    if not project_id or not workspace_path:
        return []
    content = handoff_record["data"].get("content", {}) if isinstance(handoff_record["data"].get("content", {}), dict) else {}
    outputs: list[str] = []
    output_paths = content.get("output_paths", []) if isinstance(content.get("output_paths", []), list) else []
    outputs.extend(str(item) for item in output_paths if str(item).strip())
    for item in content.get("bound_outputs", []) if isinstance(content.get("bound_outputs", []), list) else []:
        if isinstance(item, dict):
            outputs.extend(str(item.get(key)) for key in ["path", "id"] if item.get(key))
    issues = []
    for output_ref in _dedupe_list(outputs):
        output_record = by_path.get(output_ref) or by_id.get(output_ref)
        if not output_record:
            continue
        output_project_id, output_workspace = _project_scope_from_record_data(output_record)
        if output_project_id == project_id and output_workspace == workspace_path:
            continue
        issue = {
            "kind": "handoff_output_mismatch",
            "severity": "error" if output_project_id and output_project_id != project_id else "warning",
            "path": output_record["path"],
            "id": output_record["id"],
            "type": output_record["type"],
            "title": output_record["title"],
            "project_id": output_project_id,
            "workspace_path": output_workspace,
            "expected_project_id": project_id,
            "expected_workspace_path": workspace_path,
            "handoff_path": handoff_record["path"],
            "repairable": True,
            "message": "handoff output is not attached to the same project as the handoff",
        }
        issues.append(issue)
        if repair:
            attached = attach_assets_to_project(storage, [output_record["path"]], workspace_path, role=f"handoff-output:{output_record['type']}")
            if attached:
                repairs.append({"kind": "repair_handoff_output_scope", "path": output_record["path"], "project_id": project_id})
    return issues


def _audit_batch_item_handoff_scope(
    storage: LocalStorage,
    item_record: dict[str, Any],
    by_path: dict[str, dict[str, Any]],
    project_id: str,
    workspace_path: str,
    repair: bool,
    repairs: list[dict[str, str]],
) -> list[dict[str, Any]]:
    if not project_id or not workspace_path:
        return []
    content = item_record["data"].get("content", {}) if isinstance(item_record["data"].get("content", {}), dict) else {}
    issues = []
    output_paths = content.get("output_paths", []) if isinstance(content.get("output_paths", []), list) else []
    output_refs = [str(content.get("handoff_path", "")), *[str(item) for item in output_paths if str(item).strip()]]
    for output_ref in _dedupe_list(output_refs):
        output_record = by_path.get(output_ref)
        if not output_record:
            continue
        output_project_id, output_workspace = _project_scope_from_record_data(output_record)
        if output_project_id == project_id and output_workspace == workspace_path:
            continue
        issue = {
            "kind": "batch_handoff_scope_mismatch",
            "severity": "error" if output_project_id and output_project_id != project_id else "warning",
            "path": output_record["path"],
            "id": output_record["id"],
            "type": output_record["type"],
            "title": output_record["title"],
            "project_id": output_project_id,
            "workspace_path": output_workspace,
            "expected_project_id": project_id,
            "expected_workspace_path": workspace_path,
            "batch_item_path": item_record["path"],
            "repairable": True,
            "message": "batch item output is not attached to the same project as the item",
        }
        issues.append(issue)
        if repair:
            role = "claude-handoff" if output_record["type"] == "claude_code_handoff" else _project_role_for_asset(output_record)
            attached = attach_assets_to_project(storage, [output_record["path"]], workspace_path, role=role)
            if attached:
                repairs.append({"kind": "repair_batch_output_scope", "path": output_record["path"], "project_id": project_id})
    return issues


def task_center(
    storage: LocalStorage,
    status: str | None = None,
    step: str | None = None,
    task_type: str | None = None,
    project_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    if limit < 1:
        raise ValueError("limit must be greater than zero")
    if offset < 0:
        raise ValueError("offset must not be negative")
    events = []
    runs = []
    project_paths = {item["path"] for item in project_assets(storage, project_id, limit=10000)} if project_id else None
    for path in reversed(storage.list_json("runs")):
        data = storage.read_json(path)
        if not isinstance(data, dict):
            continue
        asset_type = data.get("type", "")
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if asset_type == "task_status":
            row = {
                "path": _display_path(storage.root, path),
                "id": data.get("id", ""),
                "run_id": content.get("run_id", data.get("source", "")),
                "step": content.get("step", ""),
                "status": content.get("status", ""),
                "input_paths": content.get("input_paths", []),
                "output_paths": content.get("output_paths", []),
                "error_message": content.get("error_message", ""),
                "recorded_at": data.get("metadata", {}).get("recorded_at", data.get("updated_at", "")),
            }
            if project_paths is not None and not _task_touches_project(row, project_paths):
                continue
            events.append(_task_event(storage, path, data, content))
        elif asset_type == "claude_code_handoff":
            event = _handoff_task_event(storage, path, data)
            if project_paths is not None and not _task_touches_project(event, project_paths):
                continue
            events.append(event)
        elif asset_type == "workflow_run":
            runs.append(
                {
                    "path": _display_path(storage.root, path),
                    "id": data.get("id", ""),
                    "title": data.get("title", ""),
                    "status": content.get("status", ""),
                    "outputs": content.get("outputs", []),
                    "task_statuses": content.get("task_statuses", []),
                    "updated_at": data.get("updated_at", ""),
                }
            )
    events = _filter_task_events(events, task_type=task_type, date_from=date_from, date_to=date_to)
    tasks, total_tasks = _latest_task_rows(events, status=status, step=step, offset=offset, limit=limit)
    return {
        "tasks": tasks,
        "workflow_runs": runs[:limit],
        "summary": _task_summary(tasks, runs),
        "steps": PRODUCT_STEPS,
        "timeline": _task_timeline_payload(events, limit=limit),
        "recovery": failed_recovery_reports(storage, tasks),
        "index_source": "json",
        "page": {"offset": offset, "limit": limit, "total": total_tasks},
    }


def indexed_task_center(
    settings: Any,
    storage: LocalStorage,
    status: str | None = None,
    step: str | None = None,
    task_type: str | None = None,
    project_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    store = _postgres_store(settings)
    if store:
        try:
            project_paths = {item["path"] for item in indexed_project_assets(settings, storage, project_id, limit=10000)} if project_id else None
            events = []
            for row in store.list_task_statuses(limit=max(limit * 20, 1000)):
                data = row.get("payload", {})
                if not isinstance(data, dict):
                    continue
                task = _task_row_from_payload(storage, str(row.get("path", "")), data)
                if project_paths is not None and not _task_touches_project(task, project_paths):
                    continue
                events.append(_task_event_from_row(task))
            for record in store.list_payload_records(asset_type="claude_code_handoff", category="runs", limit=max(limit * 5, 200)):
                data = record.get("payload", {})
                if not isinstance(data, dict):
                    continue
                path = storage.root / str(record.get("path", ""))
                event = _handoff_task_event(storage, path, data)
                if project_paths is not None and not _task_touches_project(event, project_paths):
                    continue
                events.append(event)
            runs = []
            for record in store.list_payload_records(asset_type="workflow_run", category="runs", limit=max(limit * 2, 100)):
                data = record.get("payload", {})
                if not isinstance(data, dict):
                    continue
                content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
                run = {
                    "path": str(record.get("path", "")),
                    "id": data.get("id", ""),
                    "title": data.get("title", ""),
                    "status": content.get("status", ""),
                    "outputs": content.get("outputs", []),
                    "task_statuses": content.get("task_statuses", []),
                    "updated_at": data.get("updated_at", ""),
                    "index_source": "postgres",
                }
                if project_paths is not None and not _task_touches_project(run, project_paths):
                    continue
                runs.append(run)
                if len(runs) >= limit:
                    break
            events = _filter_task_events(events, task_type=task_type, date_from=date_from, date_to=date_to)
            tasks, total_tasks = _latest_task_rows(events, status=status, step=step, offset=offset, limit=limit)
            timeline = _task_timeline_payload(events, limit=limit)
            return {
                "tasks": tasks,
                "workflow_runs": runs,
                "summary": _task_summary(tasks, runs),
                "steps": PRODUCT_STEPS,
                "timeline": timeline,
                "recovery": failed_recovery_reports(storage, tasks),
                "index_source": "postgres",
                "page": {"offset": offset, "limit": limit, "total": total_tasks},
            }
        except Exception:
            if getattr(settings, "postgres_write_strict", False):
                raise
    return task_center(
        storage,
        status=status,
        step=step,
        task_type=task_type,
        project_id=project_id,
        date_from=date_from,
        date_to=date_to,
        offset=offset,
        limit=limit,
    )


def task_timeline(
    storage: LocalStorage,
    project_id: str | None = None,
    run_id: str | None = None,
    task_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    offset: int = 0,
    limit: int = 200,
) -> dict[str, Any]:
    if limit < 1:
        raise ValueError("limit must be greater than zero")
    project_paths = {item["path"] for item in project_assets(storage, project_id, limit=10000)} if project_id else None
    events = []
    for path in storage.list_json("runs"):
        data = storage.read_json(path)
        if not isinstance(data, dict) or data.get("type") != "task_status":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        event = _task_event(storage, path, data, content)
        if run_id and event["run_id"] != run_id:
            continue
        if project_paths is not None and not _task_touches_project(event, project_paths):
            continue
        events.append(event)
    events = _filter_task_events(events, task_type=task_type, date_from=date_from, date_to=date_to)
    payload = _task_timeline_payload(events[offset:], limit=limit)
    payload["page"] = {"offset": offset, "limit": limit, "total": len(events)}
    return payload


def indexed_task_timeline(
    settings: Any,
    storage: LocalStorage,
    project_id: str | None = None,
    run_id: str | None = None,
    task_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    offset: int = 0,
    limit: int = 200,
) -> dict[str, Any]:
    center = indexed_task_center(
        settings,
        storage,
        project_id=project_id,
        task_type=task_type,
        date_from=date_from,
        date_to=date_to,
        offset=0,
        limit=max(limit + offset, 200),
    )
    events = center["timeline"]["events"]
    if run_id:
        events = [event for event in events if event["run_id"] == run_id]
    payload = _task_timeline_payload(events[offset:], limit=limit)
    payload["page"] = {"offset": offset, "limit": limit, "total": len(events)}
    return payload


def task_control_status(settings: Any) -> dict[str, Any]:
    config = _read_task_control(settings.root)
    celery = _celery_inspection(settings)
    storage = LocalStorage(settings.root)
    trend = _record_queue_pressure(settings.root, celery)
    return {
        "config": config,
        "celery": celery,
        "queue_trend": trend,
        "dead_letters": {"count": len(task_dead_letter_rows(settings.root, limit=1000))},
        "failed_batch_items": list_batch_items(storage, status="failed", limit=25),
        "waiting_handoffs": list_batch_items(storage, status="waiting_handoff", limit=25),
        "heartbeat": utc_now(),
    }


def task_recovery_workbench(settings: Any, project_id: str | None = None) -> dict[str, Any]:
    storage = LocalStorage(settings.root)
    center = indexed_task_center(settings, storage, status="failed", project_id=project_id, limit=100)
    return {
        "heartbeat": utc_now(),
        "project_id": project_id or "",
        "control": task_control_status(settings),
        "failed_tasks": center["tasks"],
        "recovery": center["recovery"],
        "failed_batch_items": list_batch_items(storage, status="failed", project_id=project_id, limit=100),
        "waiting_handoffs": list_batch_items(storage, status="waiting_handoff", project_id=project_id, limit=100),
        "dead_letters": task_dead_letter_rows(settings.root, limit=100),
    }


def project_health_report(settings: Any, project_id: str | None = None) -> dict[str, Any]:
    storage = LocalStorage(settings.root)
    task_status = indexed_task_center(settings, storage, project_id=project_id, limit=100)
    failed_status = indexed_task_center(settings, storage, status="failed", project_id=project_id, limit=20)
    audit = project_scope_audit(storage, project_id=project_id, repair=False)
    handoffs = list_handoffs(storage, project_id=project_id, limit=500)
    assets = indexed_project_assets(settings, storage, project_id, limit=10000) if project_id else []
    local_counts = storage.counts()
    strict = postgres_strict_local_prod_check(settings, sync=False, raise_on_failure=False)
    control = task_control_status(settings)
    return assemble_project_health_report(
        project_id=project_id or "",
        task_status=task_status,
        failed_status=failed_status,
        audit=audit,
        handoffs=handoffs,
        assets=assets,
        local_counts=local_counts,
        postgres=strict,
        control=control,
        backups=list_local_backups(settings.root, limit=5),
    )


def update_task_control(root: str | Path, patch: dict[str, Any]) -> dict[str, Any]:
    config = _read_task_control(root)
    for key in ["max_concurrent_batches", "max_concurrent_steps"]:
        if patch.get(key) is not None:
            value = int(patch[key])
            if value < 1:
                raise ValueError(f"{key} must be at least 1")
            config[key] = value
    path = Path(root).resolve() / TASK_CONTROL_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return config


def _record_queue_pressure(root: str | Path, celery: dict[str, Any], max_points: int = 120) -> list[dict[str, Any]]:
    path = Path(root).resolve() / QUEUE_PRESSURE_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except Exception:
        data = []
    if not isinstance(data, list):
        data = []
    queue_lengths = celery.get("queue_lengths", {}) if isinstance(celery.get("queue_lengths", {}), dict) else {}
    queues = queue_lengths.get("queues", {}) if isinstance(queue_lengths.get("queues", {}), dict) else {}
    snapshot = {
        "recorded_at": utc_now(),
        "healthy": bool(celery.get("healthy")),
        "active_count": int(celery.get("active_count", 0) or 0),
        "reserved_count": int(celery.get("reserved_count", 0) or 0),
        "scheduled_count": int(celery.get("scheduled_count", 0) or 0),
        "queue_total": sum(int(value or 0) for value in queues.values()),
        "queues": queues,
    }
    data.append(snapshot)
    data = data[-max_points:]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data


def cancel_celery_task(task_id: str, terminate: bool = False, signal: str = "SIGTERM") -> dict[str, Any]:
    if not task_id.strip():
        raise ValueError("task_id must not be empty")
    celery_app = _celery_app_or_error()
    celery_app.control.revoke(task_id, terminate=terminate, signal=signal)
    return {"task_id": task_id, "revoked": True, "terminate": terminate, "signal": signal}


def task_dead_letter_rows(root: str | Path, limit: int = 100) -> list[dict[str, Any]]:
    from novel_forge.workers.runtime import list_dead_letters

    return list_dead_letters(root, limit=limit)


def retry_dead_letter(root: str | Path, dead_letter_path: str):
    storage = LocalStorage(root)
    path = resolve_path(storage.root, dead_letter_path).resolve()
    path.relative_to(storage.root)
    data = storage.read_json(path)
    if not isinstance(data, dict) or data.get("type") != "task_dead_letter":
        raise ValueError(f"dead_letter_path must point to a task_dead_letter asset: {dead_letter_path}")
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    payload = content.get("payload", {}) if isinstance(content.get("payload", {}), dict) else {}
    task_name = str(content.get("task_name", ""))
    args = payload.get("args", [])
    kwargs = payload.get("kwargs", {})
    if not task_name:
        raise ValueError("dead letter has no task_name")
    if not isinstance(args, list):
        args = []
    if not isinstance(kwargs, dict):
        kwargs = {}
    from novel_forge.workers.dispatch import enqueue_task

    return enqueue_task(task_name, *args, task_kwargs=kwargs)


def receive_uploads(settings: Any, body: bytes, content_type: str) -> dict[str, Any]:
    fields, files = _parse_multipart(body, content_type)
    if not files:
        raise ValueError("multipart upload must include at least one file")
    allow_downstream = fields.get("allow_downstream_generation", "false").lower() in {"1", "true", "yes", "on"}
    authorization = fields.get("rights_authorization", "unknown")
    if allow_downstream and authorization == "unknown":
        raise ValueError(
            "upload source compliance gate: allow_downstream_generation requires "
            "owned/licensed/public_domain/permission_granted/test_fixture authorization"
        )
    root = Path(settings.root).resolve()
    upload_id = make_id("upload", fields.get("title") or "sources")
    upload_dir = root / "data" / "uploads" / upload_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    seen_hashes: dict[str, str] = {}
    items = []
    for index, file_item in enumerate(files):
        filename = _safe_filename(file_item["filename"] or f"upload-{index + 1}.txt")
        path = _unique_upload_path(upload_dir, filename)
        data = file_item["content"]
        path.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        duplicate_of = seen_hashes.get(digest, "")
        if not duplicate_of:
            seen_hashes[digest] = _display_path(root, path)
        minio = _try_minio_upload(settings, root, path, upload_id)
        items.append(
            {
                "filename": filename,
                "path": _display_path(root, path),
                "format": path.suffix.lower().lstrip(".") or "unknown",
                "size_bytes": len(data),
                "sha256": digest,
                "duplicate": bool(duplicate_of),
                "duplicate_of": duplicate_of,
                "preview": _upload_preview(data),
                "minio": minio,
            }
        )
    rights = _rights_payload(
        authorization,
        fields.get("license_name", ""),
        fields.get("copyright_note", ""),
        fields.get("source_url", ""),
        allow_downstream,
    )
    rights["source_policy"] = {
        "allowed_pipeline": ["ingest", "clean", "manual_handoff"] if allow_downstream else ["metadata_only", "manual_review"],
        "license_gate": "passed" if authorization != "unknown" else "manual_review_required",
        "raw_storage_boundary": "operator-uploaded local source; preserve abstraction boundary",
    }
    manifest = {
        "upload_id": upload_id,
        "created_at": utc_now(),
        "input_path": _display_path(root, upload_dir),
        "fields": fields,
        "items": items,
        "rights": rights,
    }
    (upload_dir / "upload-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def failed_recovery_reports(storage: LocalStorage, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reports = []
    for task in tasks:
        if task.get("status") != "failed":
            continue
        try:
            reports.append(task_recovery_report(storage, status_path=str(task.get("path", ""))))
        except Exception:
            continue
    return reports


def task_recovery_report(
    storage: LocalStorage,
    status_path: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    task = _find_task_status(storage, status_path=status_path, run_id=run_id)
    run_events = _run_events(storage, task["run_id"])
    run_log = [
        {
            "step": event["step"],
            "status": event["status"],
            "input_paths": event["input_paths"],
            "output_paths": event["output_paths"],
            "error_message": event["error_message"],
            "recorded_at": event["recorded_at"],
            "status_asset": event["path"],
        }
        for event in run_events
    ]
    error_message = task.get("error_message", "")
    return {
        "run_id": task["run_id"],
        "failed_step": task["step"],
        "failed_status_path": task["path"],
        "input_paths": task["input_paths"],
        "output_paths": task["output_paths"],
        "error_message": error_message,
        "recovery_instruction": build_recovery_instruction(run_log, error_message),
        "retry_request": {
            "status_path": task["path"],
            "run_id": task["run_id"],
            "step": task["step"],
            "async_task": False,
        },
        "run_log": run_log,
    }


def retry_task(
    root: str | Path,
    status_path: str | None = None,
    run_id: str | None = None,
    step: str | None = None,
    workspace_path: str | None = None,
) -> dict[str, Any]:
    storage = LocalStorage(root)
    storage.ensure_layout()
    task = _find_task_status(storage, status_path=status_path, run_id=run_id, step=step)
    retry_run_id = make_id("workflow_run", f"retry {task['run_id']} {task['step']}")
    input_paths = [str(item) for item in task.get("input_paths", [])]
    output, status_paths = execute_task(
        storage,
        retry_run_id,
        task["step"],
        input_paths,
        lambda: _execute_retry_step(root, task["step"], input_paths),
    )
    if workspace_path and isinstance(output, Path):
        attach_assets_to_project(storage, [output], workspace_path, role=f"retry-{task['step']}")
    _annotate_retry_statuses(storage, status_paths, task)
    return {
        "retry_run_id": retry_run_id,
        "retried_step": task["step"],
        "original_status_path": task["path"],
        "output_path": _display_path(Path(root).resolve(), output) if isinstance(output, Path) else "",
        "status_paths": [_display_path(storage.root, path) for path in status_paths],
    }


def asset_detail(storage: LocalStorage, asset_path: str) -> dict[str, Any]:
    path = resolve_path(storage.root, asset_path).resolve()
    try:
        path.relative_to(storage.root)
    except ValueError as exc:
        raise ValueError(f"asset path escapes project root: {asset_path}") from exc
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"asset not found: {asset_path}")
    data = storage.read_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"asset JSON must be an object: {asset_path}")
    return {
        "path": _display_path(storage.root, path),
        "asset": data,
        "lineage": {
            "source": data.get("source", ""),
            "references": data.get("references", []),
            "reference_assets": _reference_assets(storage, data),
        },
        "summary": _asset_summary(data),
    }


def update_asset_metadata(storage: LocalStorage, asset_path: str, patch: dict[str, Any]) -> dict[str, Any]:
    path = resolve_path(storage.root, asset_path).resolve()
    try:
        path.relative_to(storage.root)
    except ValueError as exc:
        raise ValueError(f"asset path escapes project root: {asset_path}") from exc
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"asset not found: {asset_path}")
    data = storage.read_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"asset JSON must be an object: {asset_path}")
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}

    title = patch.get("title")
    if title is not None:
        cleaned_title = str(title).strip()
        if not cleaned_title:
            raise ValueError("title must not be empty")
        data["title"] = cleaned_title
        data["name"] = cleaned_title
    if patch.get("tags") is not None:
        if not isinstance(patch["tags"], list):
            raise ValueError("tags must be a list")
        data["tags"] = _dedupe_list([str(tag).strip() for tag in patch["tags"] if str(tag).strip()])
    if patch.get("status") is not None:
        status = str(patch["status"]).strip()
        if status not in ASSET_STATUSES:
            raise ValueError(f"asset status must be one of: {', '.join(sorted(ASSET_STATUSES))}")
        metadata["asset_status"] = status
    if patch.get("notes") is not None:
        metadata["operator_notes"] = str(patch["notes"]).strip()
    if patch.get("risk_level") is not None:
        risk_level = str(patch["risk_level"]).strip()
        if risk_level not in RISK_LEVELS:
            raise ValueError(f"risk_level must be one of: {', '.join(sorted(RISK_LEVELS))}")
        metadata["risk_level"] = risk_level
        if data.get("type") == "review_report":
            data["risk_level"] = risk_level
    rights_patch = {
        "authorization": patch.get("rights_authorization"),
        "license": patch.get("license_name"),
        "copyright_boundary": patch.get("copyright_note"),
        "source_url": patch.get("source_url"),
        "allow_downstream_generation": patch.get("allow_downstream_generation"),
    }
    if any(value is not None for value in rights_patch.values()):
        rights = metadata.get("rights", {}) if isinstance(metadata.get("rights", {}), dict) else {}
        for key, value in rights_patch.items():
            if value is not None:
                rights[key] = value if isinstance(value, bool) else str(value).strip()
        metadata["rights"] = rights

    metadata["edited_at"] = utc_now()
    data["metadata"] = metadata
    data["updated_at"] = utc_now()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    storage.write_json(path, data)
    return asset_detail(storage, str(path))


def update_asset_content(storage: LocalStorage, asset_path: str, content: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(content, dict):
        raise ValueError("content must be an object")
    path = _resolve_asset_file(storage, asset_path)
    data = storage.read_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"asset JSON must be an object: {asset_path}")
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    metadata["content_edited_at"] = utc_now()
    data["content"] = content
    data["metadata"] = metadata
    data["updated_at"] = utc_now()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    storage.write_json(path, data)
    return asset_detail(storage, str(path))


def asset_versions_and_diff(storage: LocalStorage, asset_path: str) -> dict[str, Any]:
    path = _resolve_asset_file(storage, asset_path)
    current_data = storage.read_json(path)
    if not isinstance(current_data, dict):
        raise ValueError(f"asset JSON must be an object: {asset_path}")
    versions = [_asset_version_row(storage, path, current_data, "current")]
    versions.extend(_backup_version_rows(storage, path))
    versions = sorted(versions, key=lambda item: item["updated_at"], reverse=True)

    diff_payload: dict[str, Any] = {"from_path": "", "to_path": versions[0]["path"], "unified_diff": ""}
    if len(versions) > 1:
        previous_path = resolve_path(storage.root, versions[1]["path"]).resolve()
        previous_data = storage.read_json(previous_path)
        diff_payload = {
            "from_path": versions[1]["path"],
            "to_path": versions[0]["path"],
            "unified_diff": _json_unified_diff(previous_data, current_data, versions[1]["path"], versions[0]["path"]),
        }
    return {
        "path": _display_path(storage.root, path),
        "current_hash": versions[0]["sha256"],
        "versions": versions,
        "diff": diff_payload,
    }


def asset_reference_graph(storage: LocalStorage, asset_path: str, depth: int = 1) -> dict[str, Any]:
    path = _resolve_asset_file(storage, asset_path)
    data = storage.read_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"asset JSON must be an object: {asset_path}")
    depth = min(max(int(depth), 0), 3)
    records = _asset_records(storage)
    by_id = {record["id"]: record for record in records if record["id"]}
    by_path = {record["path"]: record for record in records}
    by_path.update({str(record["absolute_path"]): record for record in records})
    start_id = str(data.get("id", ""))
    if not start_id:
        raise ValueError(f"asset has no id: {asset_path}")

    nodes: dict[str, dict[str, Any]] = {}
    edge_keys: set[tuple[str, str, str]] = set()
    edges: list[dict[str, str]] = []
    queue: list[tuple[str, int]] = [(start_id, 0)]
    visited: set[tuple[str, int]] = set()

    while queue:
        node_id, level = queue.pop(0)
        if (node_id, level) in visited:
            continue
        visited.add((node_id, level))
        record = by_id.get(node_id)
        if not record:
            continue
        nodes[node_id] = _graph_node(record)
        if level >= depth:
            continue

        outgoing = _linked_records(record["data"], by_id, by_path)
        for target in outgoing:
            if target["id"] == node_id:
                continue
            _add_graph_edge(edges, edge_keys, node_id, target["id"], "references")
            queue.append((target["id"], level + 1))

        for candidate in records:
            candidate_id = candidate["id"]
            if not candidate_id or candidate_id == node_id:
                continue
            incoming = _linked_records(candidate["data"], by_id, by_path)
            if any(target["id"] == node_id for target in incoming):
                _add_graph_edge(edges, edge_keys, candidate_id, node_id, "referenced_by")
                queue.append((candidate_id, level + 1))

    return {
        "path": _display_path(storage.root, path),
        "start_id": start_id,
        "depth": depth,
        "nodes": sorted(nodes.values(), key=lambda item: item["path"]),
        "edges": edges,
    }


def save_asset_collection(storage: LocalStorage, request: dict[str, Any]) -> dict[str, Any]:
    title = str(request.get("title") or "").strip()
    if not title:
        raise ValueError("title must not be empty")
    requested_paths = request.get("asset_paths", [])
    if not isinstance(requested_paths, list) or not requested_paths:
        raise ValueError("asset_paths must be a non-empty list")

    asset_paths: list[str] = []
    asset_ids: list[str] = []
    for item in requested_paths:
        path = _resolve_asset_file(storage, str(item))
        data = storage.read_json(path)
        if not isinstance(data, dict):
            raise ValueError(f"asset JSON must be an object: {item}")
        asset_paths.append(_display_path(storage.root, path))
        asset_id = str(data.get("id", ""))
        if asset_id:
            asset_ids.append(asset_id)

    purpose = str(request.get("purpose") or "task_input").strip() or "task_input"
    metadata: dict[str, Any] = {
        "created_from": "asset-workbench",
        "item_count": len(asset_paths),
    }
    references = _dedupe_list(asset_ids)
    workspace_path = request.get("workspace_path")
    if workspace_path:
        project = _project_identity(storage, str(workspace_path))
        metadata.update(
            {
                "project_id": project["project_id"],
                "workspace_id": project["workspace_id"],
                "workspace_path": project["workspace_path"],
                "project_asset_role": "asset-collection",
            }
        )
        references = _dedupe_list([*references, project["workspace_id"], project["project_id"]])

    collection = AssetCollection(
        title=title,
        source="asset-workbench",
        tags=_dedupe_list(["asset-collection", purpose, *[str(tag) for tag in request.get("tags", []) if str(tag).strip()]]),
        content={
            "purpose": purpose,
            "asset_paths": asset_paths,
            "asset_ids": _dedupe_list(asset_ids),
            "item_count": len(asset_paths),
        },
        metadata=metadata,
        references=references,
    )
    path = storage.write_asset_auto(collection)
    if workspace_path:
        attach_assets_to_project(storage, [path], str(workspace_path), role="asset-collection")
    return asset_detail(storage, str(path))


def list_handoffs(
    storage: LocalStorage,
    project_id: str | None = None,
    status: str | None = None,
    operation: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    if limit < 1:
        raise ValueError("limit must be greater than zero")
    project = _project_identity(storage, project_id) if project_id else None
    rows = []
    skipped = 0
    for path in reversed(storage.list_json("runs")):
        data = storage.read_json(path)
        if not isinstance(data, dict) or data.get("type") != "claude_code_handoff":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if status and content.get("status") != status:
            continue
        if operation and content.get("operation") != operation:
            continue
        if project and not _belongs_to_project(data, path, project):
            continue
        rows.append(_handoff_row(storage, path, data))
        if len(rows) >= limit:
            return rows
    return rows


def create_product_deconstruction_handoff(root: str | Path, request: dict[str, Any]) -> dict[str, Any]:
    input_path = str(request.get("input_path") or "").strip()
    if not input_path:
        raise ValueError("input_path must not be empty")
    _source_compliance_gate(LocalStorage(root), input_path, "hot_novel_deconstruction")
    path = pipeline.claude_deconstruct(
        root,
        input_path=input_path,
        genre=str(request.get("genre") or ""),
        target_reader=str(request.get("target_reader") or ""),
        purpose=str(request.get("purpose") or ""),
    )
    storage = LocalStorage(root)
    workspace_path = request.get("workspace_path") or _workspace_ref_from_asset(storage, input_path)
    if workspace_path:
        attach_assets_to_project(storage, [path], str(workspace_path), role="claude-handoff")
    return asset_detail(storage, str(path))


def create_product_knowledge_handoff(root: str | Path, request: dict[str, Any]) -> dict[str, Any]:
    input_path = str(request.get("input_path") or "").strip()
    if not input_path:
        raise ValueError("input_path must not be empty")
    _source_compliance_gate(LocalStorage(root), input_path, "multidisciplinary_knowledge_parse")
    path = pipeline.claude_knowledge(
        root,
        input_path=input_path,
        discipline=str(request.get("discipline") or ""),
        credibility=str(request.get("credibility") or ""),
        scope=str(request.get("scope") or ""),
        project_context=str(request.get("project_context") or ""),
    )
    storage = LocalStorage(root)
    workspace_path = request.get("workspace_path") or _workspace_ref_from_asset(storage, input_path)
    if workspace_path:
        attach_assets_to_project(storage, [path], str(workspace_path), role="claude-handoff")
    return asset_detail(storage, str(path))


def create_github_knowledge_handoff(root: str | Path, request: dict[str, Any]) -> dict[str, Any]:
    refs = request.get("repo_refs", [])
    if not isinstance(refs, list):
        raise ValueError("repo_refs must be a list")
    storage = LocalStorage(root)
    storage.ensure_layout()
    source_note_path, sources = create_github_source_note(
        storage,
        [str(ref) for ref in refs],
        discipline=str(request.get("discipline") or ""),
        project_context=str(request.get("project_context") or ""),
    )
    handoff_path = pipeline.claude_knowledge(
        root,
        input_path=str(source_note_path),
        discipline=str(request.get("discipline") or ""),
        credibility=str(request.get("credibility") or "registered GitHub source metadata; license review required before raw access"),
        scope=str(request.get("scope") or "convert licensed or metadata-only GitHub research sources into story-safe knowledge cards"),
        project_context=str(request.get("project_context") or ""),
    )
    _annotate_github_knowledge_handoff(storage, handoff_path, source_note_path, sources)
    workspace_path = request.get("workspace_path")
    if workspace_path:
        attach_assets_to_project(storage, [source_note_path], str(workspace_path), role="github-source-note")
        attach_assets_to_project(storage, [handoff_path], str(workspace_path), role="claude-handoff")
    return {
        "source_note": asset_detail(storage, str(source_note_path)),
        "handoff": asset_detail(storage, str(handoff_path)),
        "sources": sources,
        "source_count": len(sources),
    }


def validate_handoff_output(root: str | Path, request: dict[str, Any]) -> dict[str, Any]:
    storage = LocalStorage(root)
    storage.ensure_layout()
    handoff_path = _resolve_handoff_file(storage, str(request.get("handoff_path", "")))
    output_path = _resolve_asset_file(storage, str(request.get("output_path", "")))
    return _validate_handoff_output_assets(storage, handoff_path, output_path)


def bind_handoff_output(root: str | Path, request: dict[str, Any]) -> dict[str, Any]:
    storage = LocalStorage(root)
    storage.ensure_layout()
    handoff_path = _resolve_handoff_file(storage, str(request.get("handoff_path", "")))
    output_path = _resolve_asset_file(storage, str(request.get("output_path", "")))
    validation = _validate_handoff_output_assets(storage, handoff_path, output_path)
    if not validation["valid"]:
        raise ValueError("; ".join(validation["errors"]))

    handoff = storage.read_json(handoff_path)
    output = storage.read_json(output_path)
    if not isinstance(handoff, dict) or not isinstance(output, dict):
        raise ValueError("handoff and output assets must be JSON objects")
    workspace_path = _workspace_ref_from_request_or_assets(storage, request, handoff_path, output_path)
    if workspace_path:
        attach_assets_to_project(storage, [handoff_path], str(workspace_path), role="claude-handoff")
        attach_assets_to_project(storage, [output_path], str(workspace_path), role=f"handoff-output:{output.get('type', '')}")
        handoff = storage.read_json(handoff_path)
        output = storage.read_json(output_path)
        if not isinstance(handoff, dict) or not isinstance(output, dict):
            raise ValueError("handoff and output assets must be JSON objects after project attachment")
    content = handoff.get("content", {}) if isinstance(handoff.get("content", {}), dict) else {}
    metadata = handoff.get("metadata", {}) if isinstance(handoff.get("metadata", {}), dict) else {}
    output_display = _display_path(storage.root, output_path)
    now = utc_now()
    bound_outputs = content.get("bound_outputs", []) if isinstance(content.get("bound_outputs", []), list) else []
    bound_outputs.append(
        {
            "path": output_display,
            "id": output.get("id", ""),
            "type": output.get("type", ""),
            "title": output.get("title") or output.get("name", ""),
            "validated": True,
            "bound_at": now,
        }
    )
    output_paths = _dedupe_list([*[str(item) for item in content.get("output_paths", []) if str(item).strip()], output_display])
    content["output_paths"] = output_paths
    content["bound_outputs"] = _dedupe_bound_outputs(bound_outputs)
    content["output_validation"] = validation
    content["acceptance_statuses"] = _merge_handoff_acceptance_statuses(
        content,
        auto_accept_schema=validation["valid"],
        note="output bound and schema/type validation passed" if validation["valid"] else "",
    )
    if request.get("mark_completed", True):
        content["status"] = "completed"
        content["completed_at"] = now
    metadata["bound_output_at"] = now
    metadata["last_bound_output_path"] = output_display
    metadata["last_bound_output_type"] = output.get("type", "")
    handoff["content"] = content
    handoff["metadata"] = metadata
    handoff["references"] = _dedupe_list([*[str(ref) for ref in handoff.get("references", [])], output_display, str(output.get("id", ""))])
    handoff["updated_at"] = now
    _write_validated_json(storage, handoff_path, handoff)
    continued = None
    if request.get("auto_continue_batch", True):
        continued = _auto_continue_bound_batch_handoff(root, storage, handoff_path, output_path, output)
    return {
        "validation": validation,
        "handoff": asset_detail(storage, str(handoff_path)),
        "output": asset_detail(storage, str(output_path)),
        "continued_batch_item": continued,
    }


def handoff_acceptance_status(root: str | Path, handoff_path_value: str) -> dict[str, Any]:
    storage = LocalStorage(root)
    storage.ensure_layout()
    handoff_path = _resolve_handoff_file(storage, handoff_path_value)
    data = storage.read_json(handoff_path)
    if not isinstance(data, dict):
        raise ValueError(f"handoff JSON must be an object: {handoff_path}")
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    statuses = _merge_handoff_acceptance_statuses(content)
    if statuses != content.get("acceptance_statuses"):
        content["acceptance_statuses"] = statuses
        data["content"] = content
        data["updated_at"] = utc_now()
        _write_validated_json(storage, handoff_path, data)
    return _handoff_acceptance_payload(storage, handoff_path, storage.read_json(handoff_path))


def update_handoff_acceptance(root: str | Path, request: dict[str, Any]) -> dict[str, Any]:
    status = str(request.get("status", "")).strip()
    if status not in HANDOFF_ACCEPTANCE_STATUSES:
        raise ValueError(f"acceptance status must be one of: {', '.join(sorted(HANDOFF_ACCEPTANCE_STATUSES))}")
    storage = LocalStorage(root)
    storage.ensure_layout()
    handoff_path = _resolve_handoff_file(storage, str(request.get("handoff_path", "")))
    data = storage.read_json(handoff_path)
    if not isinstance(data, dict):
        raise ValueError(f"handoff JSON must be an object: {handoff_path}")
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    statuses = _merge_handoff_acceptance_statuses(content)
    index = int(request.get("check_index", -1))
    if index < 0 or index >= len(statuses):
        raise ValueError("check_index is out of range")
    statuses[index] = {
        **statuses[index],
        "status": status,
        "note": str(request.get("note") or ""),
        "updated_at": utc_now(),
    }
    content["acceptance_statuses"] = statuses
    if status in {"needs_fix", "rejected"}:
        content["status"] = "failed"
        content["status_reason"] = statuses[index]["note"] or f"acceptance check {index} {status}"
    elif statuses and all(item.get("status") == "accepted" for item in statuses):
        if content.get("bound_outputs"):
            content["status"] = "completed"
            content["completed_at"] = utc_now()
        else:
            content["status"] = "in_progress"
    else:
        content["status"] = "in_progress"
    data["content"] = content
    data["updated_at"] = utc_now()
    _write_validated_json(storage, handoff_path, data)
    return _handoff_acceptance_payload(storage, handoff_path, storage.read_json(handoff_path))


def fail_handoff(root: str | Path, request: dict[str, Any]) -> dict[str, Any]:
    storage = LocalStorage(root)
    storage.ensure_layout()
    handoff_path = _resolve_handoff_file(storage, str(request.get("handoff_path", "")))
    reason = str(request.get("reason") or "operator marked handoff failed")
    data = storage.read_json(handoff_path)
    if not isinstance(data, dict):
        raise ValueError(f"handoff JSON must be an object: {handoff_path}")
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    content["status"] = "failed"
    content["status_reason"] = reason
    metadata["failed_at"] = utc_now()
    metadata["status_reason"] = reason
    data["content"] = content
    data["metadata"] = metadata
    data["updated_at"] = utc_now()
    _write_validated_json(storage, handoff_path, data)
    return asset_detail(storage, str(handoff_path))


def retry_handoff(root: str | Path, request: dict[str, Any]) -> dict[str, Any]:
    storage = LocalStorage(root)
    storage.ensure_layout()
    old_path = _resolve_handoff_file(storage, str(request.get("handoff_path", "")))
    old = storage.read_json(old_path)
    if not isinstance(old, dict):
        raise ValueError(f"handoff JSON must be an object: {old_path}")
    content = old.get("content", {}) if isinstance(old.get("content", {}), dict) else {}
    source_asset = content.get("source_asset", {}) if isinstance(content.get("source_asset", {}), dict) else {}
    source_path = str(source_asset.get("path") or "")
    if not source_path:
        raise ValueError("handoff has no source_asset.path to retry from")
    operation = str(content.get("operation") or "")
    if operation == "hot_novel_deconstruction":
        payload = content.get("handoff_packet", {}).get("payload", {}) if isinstance(content.get("handoff_packet", {}), dict) else {}
        new_path = pipeline.claude_deconstruct(
            root,
            input_path=source_path,
            genre=str(payload.get("genre", "")) if isinstance(payload, dict) else "",
            target_reader=str(payload.get("target_reader", "")) if isinstance(payload, dict) else "",
            purpose=str(request.get("reason") or "retry handoff after failed acceptance"),
        )
    elif operation == "multidisciplinary_knowledge_parse":
        payload = content.get("handoff_packet", {}).get("payload", {}) if isinstance(content.get("handoff_packet", {}), dict) else {}
        new_path = pipeline.claude_knowledge(
            root,
            input_path=source_path,
            discipline=str(payload.get("discipline", "")) if isinstance(payload, dict) else "",
            credibility=str(payload.get("credibility", "")) if isinstance(payload, dict) else "",
            scope=str(payload.get("scope", "")) if isinstance(payload, dict) else "",
            project_context=str(payload.get("project_context", "")) if isinstance(payload, dict) else "",
        )
    else:
        raise ValueError(f"unsupported handoff retry operation: {operation}")
    workspace_ref = request.get("workspace_path") or _workspace_ref_from_asset(storage, str(old_path))
    if workspace_ref:
        attach_assets_to_project(storage, [new_path], str(workspace_ref), role="claude-handoff")
    _mark_handoff_status(
        storage,
        _display_path(storage.root, old_path),
        "superseded",
        [],
        str(old.get("id", "")),
        reason=str(request.get("reason") or "handoff retried"),
    )
    new_data = storage.read_json(new_path)
    if isinstance(new_data, dict):
        new_metadata = new_data.get("metadata", {}) if isinstance(new_data.get("metadata", {}), dict) else {}
        new_metadata["retry_of_handoff_id"] = old.get("id", "")
        new_metadata["retry_of_handoff_path"] = _display_path(storage.root, old_path)
        new_metadata["retry_reason"] = str(request.get("reason") or "")
        new_data["metadata"] = new_metadata
        new_data["updated_at"] = utc_now()
        _write_validated_json(storage, new_path, new_data)
    return {
        "previous": asset_detail(storage, str(old_path)),
        "handoff": asset_detail(storage, str(new_path)),
    }


def _handoff_acceptance_payload(storage: LocalStorage, path: Path, data: dict[str, Any]) -> dict[str, Any]:
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    statuses = content.get("acceptance_statuses", []) if isinstance(content.get("acceptance_statuses", []), list) else []
    accepted = sum(1 for item in statuses if isinstance(item, dict) and item.get("status") == "accepted")
    failed = sum(1 for item in statuses if isinstance(item, dict) and item.get("status") in {"needs_fix", "rejected"})
    return {
        "handoff_path": _display_path(storage.root, path),
        "handoff_id": data.get("id", ""),
        "status": content.get("status", ""),
        "checks": statuses,
        "summary": {
            "total": len(statuses),
            "accepted": accepted,
            "failed": failed,
            "pending": len(statuses) - accepted - failed,
            "complete": bool(statuses) and accepted == len(statuses),
        },
    }


def _merge_handoff_acceptance_statuses(content: dict[str, Any], auto_accept_schema: bool = False, note: str = "") -> list[dict[str, Any]]:
    checks = [str(item) for item in content.get("acceptance_checks", []) if str(item).strip()] if isinstance(content.get("acceptance_checks", []), list) else []
    existing = content.get("acceptance_statuses", []) if isinstance(content.get("acceptance_statuses", []), list) else []
    by_check = {str(item.get("check", "")): item for item in existing if isinstance(item, dict)}
    statuses = []
    for index, check in enumerate(checks):
        current = by_check.get(check, {})
        status = str(current.get("status") or "pending")
        if status not in HANDOFF_ACCEPTANCE_STATUSES:
            status = "pending"
        if auto_accept_schema and index == 0:
            status = "accepted"
        statuses.append(
            {
                "index": index,
                "check": check,
                "status": status,
                "note": str(current.get("note") or (note if auto_accept_schema and index == 0 else "")),
                "updated_at": str(current.get("updated_at") or (utc_now() if auto_accept_schema and index == 0 else "")),
            }
        )
    return statuses


def _auto_continue_bound_batch_handoff(
    root: str | Path,
    storage: LocalStorage,
    handoff_path: Path,
    output_path: Path,
    output: dict[str, Any],
) -> dict[str, Any] | None:
    handoff = storage.read_json(handoff_path)
    if not isinstance(handoff, dict):
        return None
    content = handoff.get("content", {}) if isinstance(handoff.get("content", {}), dict) else {}
    batch_item = content.get("batch_item", {}) if isinstance(content.get("batch_item", {}), dict) else {}
    item_path = str(batch_item.get("path") or "")
    if not item_path:
        return None
    request: dict[str, Any] = {"item_path": item_path}
    if output.get("type") == "decomposition_report":
        request["decomposition_path"] = _display_path(storage.root, output_path)
    elif output.get("type") == "knowledge_card":
        request["knowledge_path"] = _display_path(storage.root, output_path)
    else:
        return None
    workspace_ref = _workspace_ref_from_asset(storage, _display_path(storage.root, handoff_path))
    if workspace_ref:
        request["workspace_path"] = workspace_ref
    try:
        return continue_batch_handoff(root, request)
    except Exception as exc:
        fail_handoff(root, {"handoff_path": _display_path(storage.root, handoff_path), "reason": f"auto-continue failed: {exc}"})
        return {"status": "failed", "error": str(exc), "item_path": item_path}


def _validate_handoff_output_assets(storage: LocalStorage, handoff_path: Path, output_path: Path) -> dict[str, Any]:
    handoff = storage.read_json(handoff_path)
    output = storage.read_json(output_path)
    if not isinstance(handoff, dict) or handoff.get("type") != "claude_code_handoff":
        raise ValueError(f"handoff_path must point to a claude_code_handoff asset: {handoff_path}")
    if not isinstance(output, dict):
        raise ValueError(f"output asset JSON must be an object: {output_path}")
    content = handoff.get("content", {}) if isinstance(handoff.get("content", {}), dict) else {}
    expected_type = str(content.get("expected_output_type", "")).strip()
    actual_type = str(output.get("type", "")).strip()
    errors: list[str] = []
    warnings: list[str] = []
    if not expected_type:
        errors.append("handoff expected_output_type is empty")
    if expected_type and actual_type != expected_type:
        errors.append(f"output type mismatch: expected {expected_type}, got {actual_type or 'empty'}")
    agent_runtime = content.get("agent_runtime", {}) if isinstance(content.get("agent_runtime", {}), dict) else {}
    if agent_runtime and actual_type:
        try:
            _enforce_handoff_output_policy(agent_runtime, actual_type)
        except PermissionError as exc:
            errors.append(f"agent runtime: {exc}")
    schema_errors = validate_common_fields(output)
    if schema_errors:
        errors.extend(f"output schema: {error}" for error in schema_errors)
    references = {str(ref) for ref in output.get("references", []) if str(ref).strip()} if isinstance(output.get("references", []), list) else set()
    handoff_refs = {str(handoff.get("id", "")), _display_path(storage.root, handoff_path)}
    if not references.intersection(handoff_refs):
        errors.append("output must reference the handoff id or path")
    semantic = _semantic_handoff_output_quality(storage, handoff, handoff_path, output)
    errors.extend(semantic["errors"])
    warnings.extend(semantic["warnings"])
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "semantic_quality": semantic,
        "handoff_path": _display_path(storage.root, handoff_path),
        "handoff_id": handoff.get("id", ""),
        "expected_output_type": expected_type,
        "expected_output_dir": content.get("expected_output_dir", ""),
        "output_path": _display_path(storage.root, output_path),
        "output_id": output.get("id", ""),
        "actual_output_type": actual_type,
    }


def _enforce_handoff_output_policy(agent_runtime: dict[str, Any], actual_type: str) -> None:
    tool_by_type = {
        "knowledge_card": "write_knowledge_card",
        "decomposition_report": "write_decomposition_report",
        "material_card": "write_material_card",
        "draft_chapter": "write_draft_chapter",
        "review_report": "write_review_report",
        "revision_plan": "write_revision_plan",
    }
    enforce_agent_action(agent_runtime, tool_by_type.get(actual_type, f"write_{actual_type}"), actual_type)


def _semantic_handoff_output_quality(storage: LocalStorage, handoff: dict[str, Any], handoff_path: Path, output: dict[str, Any]) -> dict[str, Any]:
    output_type = str(output.get("type", ""))
    content = output.get("content", {}) if isinstance(output.get("content", {}), dict) else {}
    metadata = output.get("metadata", {}) if isinstance(output.get("metadata", {}), dict) else {}
    handoff_content = handoff.get("content", {}) if isinstance(handoff.get("content", {}), dict) else {}
    errors: list[str] = []
    warnings: list[str] = []
    checks: list[dict[str, Any]] = []

    boundary = str(metadata.get("copyright_boundary", ""))
    boundary_ok = "abstract" in boundary.lower() or "structure" in boundary.lower() or "transform" in boundary.lower()
    checks.append({"name": "copyright_boundary", "ok": boundary_ok, "message": boundary or "missing"})
    if not boundary_ok:
        errors.append("semantic quality: output must declare an abstract/structure/transformed copyright boundary")

    if output_type == "knowledge_card":
        principles = content.get("principles", [])
        ok = isinstance(principles, list) and len([item for item in principles if str(item).strip()]) >= 1
        checks.append({"name": "knowledge_principles", "ok": ok, "message": "knowledge_card needs at least one usable principle"})
        if not ok:
            errors.append("semantic quality: knowledge_card principles must contain at least one non-empty principle")
        if handoff_content.get("source_acquisition_policy", {}).get("license_review_required") or handoff.get("metadata", {}).get("license_review_required"):
            license_status = str(metadata.get("license_review_status", ""))
            raw_text_used = bool(metadata.get("raw_text_used", False))
            ok = bool(license_status) and not raw_text_used
            checks.append({"name": "license_review", "ok": ok, "message": license_status or "missing license_review_status"})
            if not ok:
                errors.append("semantic quality: GitHub/external knowledge output must record license_review_status and raw_text_used=false")
    elif output_type == "decomposition_report":
        for key in [
            "commercial_patterns",
            "narrative_patterns",
            "character_mechanisms",
            "conflict_patterns",
            "emotion_curve",
            "hook_patterns",
        ]:
            value = content.get(key, [])
            ok = isinstance(value, list) and any(str(item).strip() for item in value)
            checks.append({"name": key, "ok": ok, "message": "non-empty abstract pattern list required"})
            if not ok:
                errors.append(f"semantic quality: decomposition_report {key} must be non-empty")
    elif output_type == "material_card":
        do_not_copy = content.get("do_not_copy", [])
        usable = content.get("usable_patterns", [])
        ok = isinstance(do_not_copy, list) and bool(do_not_copy) and isinstance(usable, list) and bool(usable)
        checks.append({"name": "material_reuse_boundary", "ok": ok, "message": "material_card requires usable_patterns and do_not_copy"})
        if not ok:
            errors.append("semantic quality: material_card must contain usable_patterns and do_not_copy")

    overlap = _source_overlap_check(storage, handoff, handoff_path, output)
    checks.append(overlap)
    if not overlap["ok"]:
        errors.append(str(overlap["message"]))
    return {"ok": not errors, "errors": errors, "warnings": warnings, "checks": checks}


def _source_overlap_check(storage: LocalStorage, handoff: dict[str, Any], handoff_path: Path, output: dict[str, Any]) -> dict[str, Any]:
    content = handoff.get("content", {}) if isinstance(handoff.get("content", {}), dict) else {}
    source_asset = content.get("source_asset", {}) if isinstance(content.get("source_asset", {}), dict) else {}
    source_path = str(source_asset.get("path") or "")
    if not source_path:
        return {"name": "source_overlap", "ok": True, "message": "no source path recorded"}
    try:
        source = storage.read_json(resolve_path(storage.root, source_path))
    except Exception:
        return {"name": "source_overlap", "ok": True, "message": "source unavailable for overlap check"}
    if not isinstance(source, dict):
        return {"name": "source_overlap", "ok": True, "message": "source unavailable for overlap check"}
    source_text = _plain_text(source.get("content", {}))
    if len(source_text) < 80:
        return {"name": "source_overlap", "ok": True, "message": "source too short for phrase overlap check"}
    output_text = json.dumps(output.get("content", {}), ensure_ascii=False)
    phrase = _first_long_phrase_overlap(source_text, output_text)
    if phrase:
        return {
            "name": "source_overlap",
            "ok": False,
            "message": f"semantic quality: output appears to copy a long source phrase near handoff {handoff.get('id', '')}: {phrase[:40]}",
        }
    return {"name": "source_overlap", "ok": True, "message": "no long source phrase overlap detected"}


def _plain_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_plain_text(child) for child in value.values())
    if isinstance(value, list):
        return " ".join(_plain_text(child) for child in value)
    if isinstance(value, str):
        return " ".join(value.split())
    return ""


def _first_long_phrase_overlap(source_text: str, output_text: str, phrase_length: int = 28) -> str:
    compact_source = "".join(source_text.split())
    compact_output = "".join(output_text.split())
    if len(compact_source) < phrase_length or len(compact_output) < phrase_length:
        return ""
    for index in range(0, max(0, len(compact_source) - phrase_length + 1), max(1, phrase_length // 2)):
        phrase = compact_source[index : index + phrase_length]
        if phrase and phrase in compact_output:
            return phrase
    return ""


def _resolve_handoff_file(storage: LocalStorage, handoff_path: str) -> Path:
    path = _resolve_asset_file(storage, handoff_path)
    data = storage.read_json(path)
    if not isinstance(data, dict) or data.get("type") != "claude_code_handoff":
        raise ValueError(f"handoff_path must point to a claude_code_handoff asset: {handoff_path}")
    return path


def _dedupe_bound_outputs(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_path: dict[str, dict[str, Any]] = {}
    for item in items:
        path = str(item.get("path", "")).strip()
        if path:
            by_path[path] = item
    return list(by_path.values())


def _source_compliance_gate(storage: LocalStorage, input_path: str, operation: str) -> None:
    try:
        data = storage.read_json(resolve_path(storage.root, input_path))
    except Exception:
        return
    if not isinstance(data, dict):
        return
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    rights = _source_rights_for_asset(storage, data)
    asset_type = str(data.get("type", ""))
    if asset_type not in {"source_document", "cleaned_text", "knowledge_card", "asset_collection"}:
        return
    authorization = str(rights.get("authorization", metadata.get("license_review_status", "")) or "unknown")
    allow = bool(rights.get("allow_downstream_generation", False))
    allowed_authorizations = {"owned", "licensed", "public_domain", "permission_granted", "test_fixture"}
    if authorization in allowed_authorizations:
        return
    if asset_type == "knowledge_card" and metadata.get("license_review_status") and metadata.get("raw_text_used") is False:
        return
    raise ValueError(
        f"source compliance gate blocked {operation}: {input_path} has authorization={authorization!r} "
        f"and allow_downstream_generation={allow}; record license/source policy before creating a handoff"
    )


def _source_rights_for_asset(storage: LocalStorage, data: dict[str, Any]) -> dict[str, Any]:
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    rights = metadata.get("rights", {}) if isinstance(metadata.get("rights", {}), dict) else {}
    if rights:
        return rights
    references = [str(item) for item in data.get("references", []) if str(item).strip()] if isinstance(data.get("references", []), list) else []
    for ref in [str(data.get("source", "")), *references]:
        if not ref:
            continue
        for category in DATA_DIRS:
            for path in storage.list_json(category):
                try:
                    candidate = storage.read_json(path)
                except Exception:
                    continue
                if not isinstance(candidate, dict):
                    continue
                if ref not in {str(candidate.get("id", "")), _display_path(storage.root, path)}:
                    continue
                candidate_metadata = candidate.get("metadata", {}) if isinstance(candidate.get("metadata", {}), dict) else {}
                candidate_rights = candidate_metadata.get("rights", {}) if isinstance(candidate_metadata.get("rights", {}), dict) else {}
                if candidate_rights:
                    return candidate_rights
    return {}


def _annotate_github_knowledge_handoff(
    storage: LocalStorage,
    handoff_path: Path,
    source_note_path: Path,
    sources: list[dict[str, Any]],
) -> None:
    data = storage.read_json(handoff_path)
    if not isinstance(data, dict):
        raise ValueError(f"handoff JSON must be an object: {handoff_path}")
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    instructions = content.get("instructions", []) if isinstance(content.get("instructions", []), list) else []
    checks = content.get("acceptance_checks", []) if isinstance(content.get("acceptance_checks", []), list) else []
    content["external_source_refs"] = sources
    content["source_acquisition_policy"] = {
        "mode": "registered_github_sources",
        "source_note_path": _display_path(storage.root, source_note_path),
        "license_review_required": True,
        "fetch_boundary": "use official GitHub repository access only after license review; do not crawl unrelated websites",
        "raw_storage_boundary": "metadata-only by default; do not store raw forum/user content or protected novel text as reusable assets",
        "output_boundary": "KnowledgeCard must contain abstract principles, constraints, conflict generators, and review checks",
    }
    instructions.extend(
        [
            "Before using any GitHub repository content, verify the repository license and record the result in the KnowledgeCard metadata.",
            "Use README, dataset cards, papers, schemas, aggregate statistics, and permitted examples before raw corpus text.",
            "For non-commercial, unclear, forum, comment, or crawler-tool sources, extract only aggregate patterns or risk rules; do not import raw text into production assets.",
            "Do not store user identifiers, forum posts, protected web-novel prose, or crawler output as reusable material.",
        ]
    )
    checks.extend(
        [
            "KnowledgeCard metadata includes source_ids, source_urls, license_review_status, and raw_text_used=false unless an explicit license permits it.",
            "Output contains story-safe concepts, constraints, conflict generators, or review checks instead of raw repository text.",
            "High-risk forum, dialogue, and crawler-tool sources are used only for aggregate feedback/risk analysis.",
        ]
    )
    content["instructions"] = _dedupe_list([str(item) for item in instructions if str(item).strip()])
    content["acceptance_checks"] = _dedupe_list([str(item) for item in checks if str(item).strip()])
    metadata.update(
        {
            "source_kind": "github_source_registry",
            "source_note_path": _display_path(storage.root, source_note_path),
            "source_ids": [source["id"] for source in sources],
            "source_urls": [source["url"] for source in sources],
            "license_review_required": True,
        }
    )
    data["content"] = content
    data["metadata"] = metadata
    data["references"] = _dedupe_list(
        [
            *[str(ref) for ref in data.get("references", [])],
            _display_path(storage.root, source_note_path),
            *[source["repo"] for source in sources],
        ]
    )
    data["updated_at"] = utc_now()
    _write_validated_json(storage, handoff_path, data)


def _normalize_batch_analysis_mode(value: str) -> str:
    mode = str(value or "auto").strip() or "auto"
    if mode not in BATCH_ANALYSIS_MODES:
        raise ValueError(f"analysis_mode must be one of: {', '.join(sorted(BATCH_ANALYSIS_MODES))}")
    return mode


def create_batch_deconstruct_items(
    root: str | Path,
    input_path: str,
    title: str | None = None,
    rights_authorization: str = "unknown",
    license_name: str = "",
    copyright_note: str = "",
    source_url: str = "",
    allow_downstream_generation: bool = False,
    workspace_path: str | None = None,
    analysis_mode: str = "auto",
) -> dict[str, Any]:
    storage = LocalStorage(root)
    storage.ensure_layout()
    analysis_mode = _normalize_batch_analysis_mode(analysis_mode)
    source_paths = _batch_source_files(storage.root, input_path)
    batch_id = make_id("batch", title or Path(input_path).stem or "deconstruct")
    rights = _rights_payload(
        rights_authorization,
        license_name,
        copyright_note,
        source_url,
        allow_downstream_generation,
    )
    item_paths = []
    items = []
    for index, source_path in enumerate(source_paths):
        item_path = _write_batch_item(
            storage,
            batch_id=batch_id,
            item_index=index,
            source_path=source_path,
            status="pending",
            steps=[{"step": "queued", "status": "completed"}],
            rights=rights,
            workspace_path=workspace_path,
            title=title,
            analysis_mode=analysis_mode,
        )
        item_paths.append(_display_path(storage.root, item_path))
        items.append(_batch_item_row(storage, item_path, storage.read_json(item_path)))
    return {"batch_id": batch_id, "processed": len(items), "queued": len(items), "item_paths": item_paths, "items": items}


def enqueue_batch_deconstruct(
    root: str | Path,
    input_path: str,
    title: str | None = None,
    rights_authorization: str = "unknown",
    license_name: str = "",
    copyright_note: str = "",
    source_url: str = "",
    allow_downstream_generation: bool = False,
    workspace_path: str | None = None,
    analysis_mode: str = "auto",
) -> dict[str, Any]:
    created = create_batch_deconstruct_items(
        root,
        input_path,
        title=title,
        rights_authorization=rights_authorization,
        license_name=license_name,
        copyright_note=copyright_note,
        source_url=source_url,
        allow_downstream_generation=allow_downstream_generation,
        workspace_path=workspace_path,
        analysis_mode=analysis_mode,
    )
    from novel_forge.workers.dispatch import enqueue_task

    tasks = []
    for item_path in created["item_paths"]:
        task = enqueue_task("batch_item_step_task", str(Path(root).resolve()), item_path, "ingest", workspace_path)
        tasks.append({"item_path": item_path, "task_id": task.id, "step": "ingest"})
    return {**created, "mode": "async-item-step", "tasks": tasks}


def run_batch_deconstruct(
    root: str | Path,
    input_path: str,
    title: str | None = None,
    rights_authorization: str = "unknown",
    license_name: str = "",
    copyright_note: str = "",
    source_url: str = "",
    allow_downstream_generation: bool = False,
    workspace_path: str | None = None,
    analysis_mode: str = "auto",
) -> dict[str, Any]:
    created = create_batch_deconstruct_items(
        root,
        input_path,
        title=title,
        rights_authorization=rights_authorization,
        license_name=license_name,
        copyright_note=copyright_note,
        source_url=source_url,
        allow_downstream_generation=allow_downstream_generation,
        workspace_path=workspace_path,
        analysis_mode=analysis_mode,
    )
    storage = LocalStorage(root)
    items = []
    for item_path_value in created["item_paths"]:
        item_path = resolve_path(storage.root, item_path_value).resolve()
        item = _process_batch_source(
            root,
            item_path,
            title=title,
            rights_authorization=rights_authorization,
            license_name=license_name,
            copyright_note=copyright_note,
            source_url=source_url,
            allow_downstream_generation=allow_downstream_generation,
            workspace_path=workspace_path,
        )
        items.append(item)
    succeeded = sum(1 for item in items if item["status"] == "completed")
    waiting = sum(1 for item in items if item["status"] == "waiting_handoff")
    failed = sum(1 for item in items if item["status"] == "failed")
    return {
        "batch_id": created["batch_id"],
        "processed": len(items),
        "succeeded": succeeded,
        "waiting_handoff": waiting,
        "failed": failed,
        "analysis_mode": analysis_mode,
        "items": items,
    }


def list_batch_items(
    storage: LocalStorage,
    batch_id: str | None = None,
    status: str | None = None,
    project_id: str | None = None,
    offset: int = 0,
    limit: int = 100,
) -> list[dict[str, Any]]:
    if limit < 1:
        raise ValueError("limit must be greater than zero")
    if offset < 0:
        raise ValueError("offset must not be negative")
    project = _project_identity(storage, project_id) if project_id else None
    rows = []
    skipped = 0
    for path in reversed(storage.list_json("runs")):
        data = storage.read_json(path)
        if not isinstance(data, dict) or data.get("type") != "batch_task_item":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if batch_id and content.get("batch_id") != batch_id:
            continue
        if status and content.get("status") != status:
            continue
        if project and not _belongs_to_project(data, path, project):
            continue
        if skipped < offset:
            skipped += 1
            continue
        rows.append(_batch_item_row(storage, path, data))
        if len(rows) >= limit:
            return rows
    return rows


def retry_batch_item(root: str | Path, item_path: str, workspace_path: str | None = None) -> dict[str, Any]:
    storage = LocalStorage(root)
    storage.ensure_layout()
    path = resolve_path(storage.root, item_path).resolve()
    path.relative_to(storage.root)
    data = storage.read_json(path)
    if not isinstance(data, dict) or data.get("type") != "batch_task_item":
        raise ValueError(f"item_path must point to a batch_task_item asset: {item_path}")
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    rights = metadata.get("rights", {}) if isinstance(metadata.get("rights", {}), dict) else {}
    content["retry_count"] = int(content.get("retry_count", 0)) + 1
    data["content"] = content
    storage.write_json(path, data)
    return _process_batch_source(
        root,
        path,
        title=None,
        rights_authorization=str(rights.get("authorization", "unknown")),
        license_name=str(rights.get("license", "")),
        copyright_note=str(rights.get("copyright_boundary", "")),
        source_url=str(rights.get("source_url", "")),
        allow_downstream_generation=bool(rights.get("allow_downstream_generation", False)),
        workspace_path=workspace_path or metadata.get("workspace_path"),
    )


def retry_batch_items_bulk(root: str | Path, item_paths: list[str], workspace_path: str | None = None) -> dict[str, Any]:
    results = []
    for item_path in item_paths:
        try:
            row = retry_batch_item(root, item_path, workspace_path=workspace_path)
            results.append({"item_path": item_path, "status": "retried", "result": row})
        except Exception as exc:
            results.append({"item_path": item_path, "status": "failed", "error": str(exc)})
    return {
        "requested": len(item_paths),
        "succeeded": sum(1 for item in results if item["status"] == "retried"),
        "failed": sum(1 for item in results if item["status"] == "failed"),
        "results": results,
    }


def review_batch_item(storage: LocalStorage, request: dict[str, Any]) -> dict[str, Any]:
    decision = str(request.get("decision", "")).strip()
    if decision not in BATCH_REVIEW_DECISIONS:
        raise ValueError(f"decision must be one of: {', '.join(sorted(BATCH_REVIEW_DECISIONS))}")
    path = resolve_path(storage.root, str(request.get("item_path", ""))).resolve()
    path.relative_to(storage.root)
    data = storage.read_json(path)
    if not isinstance(data, dict) or data.get("type") != "batch_task_item":
        raise ValueError(f"item_path must point to a batch_task_item asset: {request.get('item_path', '')}")
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    review_gate = {
        "decision": decision,
        "note": str(request.get("note") or ""),
        "reviewed_at": utc_now(),
    }
    content["review_status"] = decision
    content["review_note"] = review_gate["note"]
    metadata["review_gate"] = review_gate
    data["content"] = content
    data["metadata"] = metadata
    data["tags"] = _dedupe_list([*data.get("tags", []), f"review-{decision}"])
    data["updated_at"] = utc_now()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    storage.write_json(path, data)
    return _batch_item_row(storage, path, storage.read_json(path))


def continue_batch_handoff(root: str | Path, request: dict[str, Any]) -> dict[str, Any]:
    storage = LocalStorage(root)
    storage.ensure_layout()
    item_path = _resolve_batch_item_path(storage, str(request.get("item_path", "")))
    data = storage.read_json(item_path)
    if not isinstance(data, dict):
        raise ValueError(f"batch item JSON must be an object: {item_path}")
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    if content.get("analysis_mode") != "claude_code":
        raise ValueError("batch item is not in claude_code analysis mode")
    output_paths = [str(item) for item in content.get("output_paths", []) if str(item)]

    decomposition_path = _optional_output_path(storage, request.get("decomposition_path"), "decomposition_report")
    knowledge_path = _optional_output_path(storage, request.get("knowledge_path"), "knowledge_card")
    handoff_id = str(content.get("handoff_id", ""))
    if not knowledge_path:
        knowledge_path = _find_batch_manual_output(storage, data, "knowledge_card")
    if not decomposition_path:
        decomposition_path = _find_batch_manual_output(storage, data, "decomposition_report")
    if not knowledge_path and decomposition_path:
        knowledge_path = pipeline.extract_knowledge(root, _display_path(storage.root, decomposition_path))
    if not knowledge_path:
        raise FileNotFoundError("no KnowledgeCard found; provide knowledge_path or create a linked knowledge_card")

    workspace_ref = _workspace_ref_from_request_or_assets(
        storage,
        request,
        item_path,
        content.get("handoff_path"),
        decomposition_path,
        knowledge_path,
    ) or metadata.get("workspace_path")
    handoff_path_value = str(content.get("handoff_path", ""))
    if workspace_ref and handoff_path_value:
        attach_assets_to_project(storage, [handoff_path_value], str(workspace_ref), role="claude-handoff")
    attach_targets = [path for path in [decomposition_path, knowledge_path] if path]
    if workspace_ref and attach_targets:
        attach_assets_to_project(storage, attach_targets, str(workspace_ref), role="deconstruction")

    material_path = pipeline.build_materials(root, _display_path(storage.root, knowledge_path))
    if workspace_ref:
        attach_assets_to_project(storage, [material_path], str(workspace_ref), role="deconstruction")
    output_paths = _dedupe_list(
        [
            *output_paths,
            *[_display_path(storage.root, path) for path in [decomposition_path, knowledge_path] if path],
            _display_path(storage.root, material_path),
        ]
    )
    steps = content.get("steps", []) if isinstance(content.get("steps", []), list) else []
    if decomposition_path:
        steps = _set_step(steps, "handoff-output", "completed", output_path=_display_path(storage.root, decomposition_path))
    steps = _set_step(steps, "knowledge-output", "completed", output_path=_display_path(storage.root, knowledge_path))
    steps = _set_step(steps, "build-materials", "completed", output_path=_display_path(storage.root, material_path))
    content.update(
        {
            "status": "completed",
            "steps": steps,
            "output_paths": output_paths,
            "error_message": "",
            "handoff_status": "completed",
            "completed_at": utc_now(),
        }
    )
    data["content"] = content
    data["updated_at"] = utc_now()
    _write_validated_json(storage, item_path, data)
    _mark_handoff_status(storage, str(content.get("handoff_path", "")), "completed", output_paths, handoff_id)
    return _batch_item_row(storage, item_path, storage.read_json(item_path))


def regenerate_batch_handoff(root: str | Path, request: dict[str, Any]) -> dict[str, Any]:
    storage = LocalStorage(root)
    storage.ensure_layout()
    item_path = _resolve_batch_item_path(storage, str(request.get("item_path", "")))
    data = storage.read_json(item_path)
    if not isinstance(data, dict):
        raise ValueError(f"batch item JSON must be an object: {item_path}")
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    if content.get("analysis_mode") != "claude_code":
        raise ValueError("batch item is not in claude_code analysis mode")
    _mark_handoff_status(storage, str(content.get("handoff_path", "")), "superseded", [], str(content.get("handoff_id", "")), reason=str(request.get("reason", "")))
    output_paths = [str(item) for item in content.get("output_paths", []) if str(item)]
    cleaned_path = _batch_previous_output(output_paths, "claude-handoff")
    handoff_path = pipeline.claude_deconstruct(
        root,
        input_path=cleaned_path,
        purpose="regenerated batch deconstruction handoff; previous handoff was superseded",
    )
    workspace_ref = request.get("workspace_path") or metadata.get("workspace_path")
    if workspace_ref:
        attach_assets_to_project(storage, [handoff_path], str(workspace_ref), role="claude-handoff")
    _annotate_batch_handoff(storage, handoff_path, item_path, content, metadata)
    output_paths = _dedupe_list([*output_paths, _display_path(storage.root, handoff_path)])
    steps = _set_step(content.get("steps", []) if isinstance(content.get("steps", []), list) else [], "claude-handoff", "completed", output_path=_display_path(storage.root, handoff_path))
    content.update(
        {
            "status": "waiting_handoff",
            "steps": steps,
            "output_paths": output_paths,
            "error_message": "",
        }
    )
    data["content"] = content
    data["updated_at"] = utc_now()
    _write_validated_json(storage, item_path, data)
    _record_batch_handoff_on_item(storage, item_path, handoff_path)
    return _batch_item_row(storage, item_path, storage.read_json(item_path))


def void_batch_handoff(root: str | Path, request: dict[str, Any]) -> dict[str, Any]:
    storage = LocalStorage(root)
    storage.ensure_layout()
    item_path = _resolve_batch_item_path(storage, str(request.get("item_path", "")))
    data = storage.read_json(item_path)
    if not isinstance(data, dict):
        raise ValueError(f"batch item JSON must be an object: {item_path}")
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    if content.get("analysis_mode") != "claude_code":
        raise ValueError("batch item is not in claude_code analysis mode")
    reason = str(request.get("reason") or "handoff voided by operator")
    _mark_handoff_status(storage, str(content.get("handoff_path", "")), "superseded", [], str(content.get("handoff_id", "")), reason=reason)
    steps = _set_step(content.get("steps", []) if isinstance(content.get("steps", []), list) else [], "claude-handoff", "failed", error_message=reason)
    content.update(
        {
            "status": "failed",
            "steps": steps,
            "error_message": reason,
            "handoff_status": "superseded",
            "completed_at": utc_now(),
        }
    )
    data["content"] = content
    data["updated_at"] = utc_now()
    _write_validated_json(storage, item_path, data)
    return _batch_item_row(storage, item_path, storage.read_json(item_path))


def _resolve_batch_item_path(storage: LocalStorage, item_path: str) -> Path:
    path = resolve_path(storage.root, item_path).resolve()
    path.relative_to(storage.root)
    data = storage.read_json(path)
    if not isinstance(data, dict) or data.get("type") != "batch_task_item":
        raise ValueError(f"item_path must point to a batch_task_item asset: {item_path}")
    return path


def _optional_output_path(storage: LocalStorage, value: Any, expected_type: str) -> Path | None:
    if not value:
        return None
    path = resolve_path(storage.root, str(value)).resolve()
    path.relative_to(storage.root)
    data = storage.read_json(path)
    if not isinstance(data, dict) or data.get("type") != expected_type:
        raise ValueError(f"{expected_type} path expected: {value}")
    return path


def _find_batch_manual_output(storage: LocalStorage, item_data: dict[str, Any], expected_type: str) -> Path | None:
    content = item_data.get("content", {}) if isinstance(item_data.get("content", {}), dict) else {}
    item_id = str(item_data.get("id", ""))
    handoff_id = str(content.get("handoff_id", ""))
    handoff_path = str(content.get("handoff_path", ""))
    category = "knowledge" if expected_type == "knowledge_card" else "decompositions"
    for path in reversed(storage.list_json(category)):
        data = storage.read_json(path)
        if not isinstance(data, dict) or data.get("type") != expected_type:
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        references = {str(item) for item in data.get("references", []) if str(item)}
        if (
            item_id in references
            or handoff_id in references
            or metadata.get("batch_item_id") == item_id
            or metadata.get("handoff_id") == handoff_id
            or metadata.get("handoff_path") == handoff_path
        ):
            return path
    return None


def _mark_handoff_status(
    storage: LocalStorage,
    handoff_path: str,
    status: str,
    output_paths: list[str],
    handoff_id: str = "",
    reason: str = "",
) -> None:
    if not handoff_path:
        return
    try:
        path = resolve_path(storage.root, handoff_path).resolve()
        path.relative_to(storage.root)
        data = storage.read_json(path)
    except Exception:
        return
    if not isinstance(data, dict) or data.get("type") != "claude_code_handoff":
        return
    if handoff_id and data.get("id") != handoff_id:
        return
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    content["status"] = status
    if output_paths:
        content["output_paths"] = output_paths
    if reason:
        content["status_reason"] = reason
    metadata[f"{status}_at"] = utc_now()
    if reason:
        metadata["status_reason"] = reason
    data["content"] = content
    data["metadata"] = metadata
    data["updated_at"] = utc_now()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    storage.write_json(path, data)


def _batch_source_files(root: Path, input_path: str) -> list[Path]:
    path = resolve_path(root, input_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"input path not found: {path}")
    if path.is_file():
        return [path]
    files = discover_source_files(path)
    if not files:
        raise ValueError(f"no supported source files found under {path}")
    return files


def _write_batch_item(
    storage: LocalStorage,
    batch_id: str,
    item_index: int,
    source_path: Path,
    status: str,
    steps: list[dict[str, Any]],
    rights: dict[str, Any],
    workspace_path: str | None,
    title: str | None = None,
    analysis_mode: str = "auto",
) -> Path:
    analysis_mode = _normalize_batch_analysis_mode(analysis_mode)
    metadata: dict[str, Any] = {
        "source_name": source_path.name,
        "rights": rights,
        "recorded_at": utc_now(),
    }
    references: list[str] = []
    if workspace_path:
        project = _project_identity(storage, workspace_path)
        metadata.update(
            {
                "project_id": project["project_id"],
                "workspace_id": project["workspace_id"],
                "workspace_path": project["workspace_path"],
                "project_asset_role": "batch-item",
            }
        )
        references.extend([project["workspace_id"], project["project_id"]])
    item = BatchTaskItem(
        title=f"Batch item {item_index + 1}: {source_path.name}",
        source=batch_id,
        tags=["batch-task-item", status],
        content={
            "batch_id": batch_id,
            "item_index": item_index,
            "source_path": _display_path(storage.root, source_path),
            "source_name": source_path.name,
            "title": title or "",
            "status": status,
            "steps": steps,
            "output_paths": [],
            "error_message": "",
            "retry_count": 0,
            "execution_mode": "claude-code-handoff" if analysis_mode == "claude_code" else "item-step",
            "analysis_mode": analysis_mode,
            "handoff_path": "",
            "handoff_id": "",
            "handoff_status": "",
            "handoff_generation": 0,
            "handoff_history": [],
        },
        metadata=metadata,
        references=[ref for ref in references if ref],
    )
    return storage.write_asset("runs", item)


def _process_batch_source(
    root: str | Path,
    item_path: Path,
    title: str | None,
    rights_authorization: str,
    license_name: str,
    copyright_note: str,
    source_url: str,
    allow_downstream_generation: bool,
    workspace_path: str | None,
) -> dict[str, Any]:
    row: dict[str, Any] = {}
    data = LocalStorage(root).read_json(item_path)
    content = data.get("content", {}) if isinstance(data, dict) and isinstance(data.get("content", {}), dict) else {}
    for step in _batch_steps(content):
        row = process_batch_item_step(root, str(item_path), step=step, workspace_path=workspace_path, enqueue_next=False)
        if row.get("status") in {"failed", "waiting_handoff"}:
            break
    return row


def _batch_steps(content: dict[str, Any]) -> list[str]:
    return BATCH_CLAUDE_STEPS if content.get("analysis_mode") == "claude_code" else BATCH_PIPELINE_STEPS


def _next_batch_step(steps: list[dict[str, Any]], content: dict[str, Any]) -> str:
    completed = {str(step.get("step", "")) for step in steps if step.get("status") == "completed"}
    for step in _batch_steps(content):
        if step not in completed:
            return step
    return ""


def process_batch_item_step(
    root: str | Path,
    item_path: str,
    step: str | None = None,
    workspace_path: str | None = None,
    enqueue_next: bool = True,
) -> dict[str, Any]:
    storage = LocalStorage(root)
    storage.ensure_layout()
    resolved_item_path = resolve_path(storage.root, item_path).resolve()
    resolved_item_path.relative_to(storage.root)
    data = storage.read_json(resolved_item_path)
    if not isinstance(data, dict) or data.get("type") != "batch_task_item":
        raise ValueError(f"item_path must point to a batch_task_item asset: {item_path}")
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    rights = metadata.get("rights", {}) if isinstance(metadata.get("rights", {}), dict) else {}
    steps = content.get("steps", []) if isinstance(content.get("steps", []), list) else []
    allowed_steps = _batch_steps(content)
    current_step = step or _next_batch_step(steps, content)
    if current_step not in allowed_steps:
        raise ValueError(f"unsupported batch step: {current_step}")
    if _step_completed(steps, current_step):
        next_step = _next_step_after(current_step, steps, content)
        if next_step and enqueue_next:
            _enqueue_batch_item_step(root, _display_path(storage.root, resolved_item_path), next_step, workspace_path or metadata.get("workspace_path"))
        return _batch_item_row(storage, resolved_item_path, data)

    output_paths = [str(item) for item in content.get("output_paths", []) if str(item)]
    steps = _set_step(steps, current_step, "running")
    _update_batch_item_status(storage, resolved_item_path, "running", steps, output_paths, "")
    try:
        output = _run_batch_pipeline_step(
            root,
            current_step,
            content,
            output_paths,
            rights,
            resolved_item_path,
            metadata,
        )
        output_display = _display_path(storage.root, output)
        output_paths = _dedupe_list([*output_paths, output_display])
        workspace_ref = workspace_path or metadata.get("workspace_path")
        if workspace_ref:
            project_role = "claude-handoff" if current_step == "claude-handoff" else "deconstruction"
            attach_assets_to_project(storage, [output], str(workspace_ref), role=project_role)
        steps = _set_step(steps, current_step, "completed", output_path=output_display)
        next_step = _next_step_after(current_step, steps, content)
        final_status = "waiting_handoff" if current_step == "claude-handoff" else ("pending" if next_step else "completed")
        _update_batch_item_status(storage, resolved_item_path, final_status, steps, output_paths, "")
        if current_step == "claude-handoff":
            _record_batch_handoff_on_item(storage, resolved_item_path, output)
        if next_step and enqueue_next:
            task = _enqueue_batch_item_step(root, _display_path(storage.root, resolved_item_path), next_step, workspace_ref)
            data = storage.read_json(resolved_item_path)
            if isinstance(data, dict):
                content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
                content["next_task_id"] = task.id
                data["content"] = content
                storage.write_json(resolved_item_path, data)
    except Exception as exc:
        error_message = f"{type(exc).__name__}: {exc}"
        steps = _set_step(steps, current_step, "failed", error_message=error_message)
        _update_batch_item_status(storage, resolved_item_path, "failed", steps, output_paths, error_message)
    return _batch_item_row(storage, resolved_item_path, storage.read_json(resolved_item_path))


def _run_batch_pipeline_step(
    root: str | Path,
    step: str,
    content: dict[str, Any],
    output_paths: list[str],
    rights: dict[str, Any],
    item_path: Path,
    metadata: dict[str, Any],
) -> Path:
    if step == "ingest":
        return pipeline.ingest(
            root,
            str(content.get("source_path", "")),
            title=str(content.get("title") or "") or None,
            rights_authorization=str(rights.get("authorization", "unknown")),
            license_name=str(rights.get("license", "")),
            copyright_note=str(rights.get("copyright_boundary", "")),
            source_url=str(rights.get("source_url", "")),
            allow_downstream_generation=bool(rights.get("allow_downstream_generation", False)),
        )
    previous = _batch_previous_output(output_paths, step)
    if step == "clean":
        return pipeline.clean(root, previous)
    if step == "claude-handoff":
        return _create_batch_claude_handoff(root, item_path, content, output_paths, metadata)
    if step == "decompose":
        return pipeline.decompose(root, previous)
    if step == "extract-knowledge":
        return pipeline.extract_knowledge(root, previous)
    if step == "build-materials":
        return pipeline.build_materials(root, previous)
    raise ValueError(f"unsupported batch step: {step}")


def _create_batch_claude_handoff(
    root: str | Path,
    item_path: Path,
    content: dict[str, Any],
    output_paths: list[str],
    metadata: dict[str, Any],
) -> Path:
    storage = LocalStorage(root)
    cleaned_path = _batch_previous_output(output_paths, "claude-handoff")
    workspace_path = metadata.get("workspace_path")
    path = pipeline.claude_deconstruct(
        root,
        input_path=cleaned_path,
        genre=str(metadata.get("genre", "")),
        target_reader=str(metadata.get("target_reader", "")),
        purpose="batch deconstruction handoff; produce a DecompositionReport and/or a KnowledgeCard, then continue the batch item",
    )
    if workspace_path:
        attach_assets_to_project(storage, [path], str(workspace_path), role="claude-handoff")
    _annotate_batch_handoff(storage, path, item_path, content, metadata)
    return path


def _annotate_batch_handoff(
    storage: LocalStorage,
    handoff_path: Path,
    item_path: Path,
    item_content: dict[str, Any],
    item_metadata: dict[str, Any],
) -> None:
    handoff = storage.read_json(handoff_path)
    item = storage.read_json(item_path)
    if not isinstance(handoff, dict) or not isinstance(item, dict):
        return
    content = handoff.get("content", {}) if isinstance(handoff.get("content", {}), dict) else {}
    metadata = handoff.get("metadata", {}) if isinstance(handoff.get("metadata", {}), dict) else {}
    content["batch_item"] = {
        "path": _display_path(storage.root, item_path),
        "id": item.get("id", ""),
        "batch_id": item_content.get("batch_id", ""),
        "item_index": item_content.get("item_index", 0),
        "source_path": item_content.get("source_path", ""),
    }
    content["expected_manual_outputs"] = [
        {
            "type": "decomposition_report",
            "required_reference": item.get("id", ""),
            "output_dir": "data/decompositions",
        },
        {
            "type": "knowledge_card",
            "required_reference": item.get("id", ""),
            "output_dir": "data/knowledge",
        },
    ]
    instructions = content.get("instructions", []) if isinstance(content.get("instructions", []), list) else []
    instructions.extend(
        [
            "When the manual analysis is complete, write the output asset path back through the Batch item continue action.",
            "Reference the batch item id or this handoff id in generated DecompositionReport/KnowledgeCard assets.",
        ]
    )
    content["instructions"] = _dedupe_list([str(item) for item in instructions if str(item).strip()])
    metadata.update(
        {
            "batch_id": item_content.get("batch_id", ""),
            "batch_item_id": item.get("id", ""),
            "batch_item_path": _display_path(storage.root, item_path),
            "project_id": item_metadata.get("project_id", metadata.get("project_id", "")),
            "workspace_id": item_metadata.get("workspace_id", metadata.get("workspace_id", "")),
            "workspace_path": item_metadata.get("workspace_path", metadata.get("workspace_path", "")),
            "project_asset_role": "claude-handoff",
        }
    )
    references = _dedupe_list(
        [
            *[str(ref) for ref in handoff.get("references", [])],
            str(item.get("id", "")),
            _display_path(storage.root, item_path),
            str(item_metadata.get("project_id", "")),
            str(item_metadata.get("workspace_id", "")),
        ]
    )
    handoff["content"] = content
    handoff["metadata"] = metadata
    handoff["references"] = [ref for ref in references if ref]
    handoff["updated_at"] = utc_now()
    errors = validate_common_fields(handoff)
    if errors:
        raise ValueError("; ".join(errors))
    storage.write_json(handoff_path, handoff)


def _batch_previous_output(output_paths: list[str], step: str) -> str:
    required_category = {
        "clean": "raw",
        "claude-handoff": "cleaned",
        "decompose": "cleaned",
        "extract-knowledge": "decompositions",
        "build-materials": "knowledge",
    }.get(step, "")
    for output in reversed(output_paths):
        if Path(output).parts[-2:-1] == (required_category,):
            return output
    raise FileNotFoundError(f"batch step {step} has no previous {required_category} output")


def _set_step(
    steps: list[dict[str, Any]],
    step: str,
    status: str,
    output_path: str = "",
    error_message: str = "",
) -> list[dict[str, Any]]:
    updated = []
    seen = False
    for item in steps:
        if not isinstance(item, dict) or item.get("step") != step:
            updated.append(item)
            continue
        next_item = {**item, "status": status}
        if output_path:
            next_item["output_path"] = output_path
        if error_message:
            next_item["error_message"] = error_message
        updated.append(next_item)
        seen = True
    if not seen:
        next_item = {"step": step, "status": status}
        if output_path:
            next_item["output_path"] = output_path
        if error_message:
            next_item["error_message"] = error_message
        updated.append(next_item)
    return updated


def _step_completed(steps: list[dict[str, Any]], step: str) -> bool:
    return any(isinstance(item, dict) and item.get("step") == step and item.get("status") == "completed" for item in steps)


def _next_step_after(step: str, steps: list[dict[str, Any]], content: dict[str, Any]) -> str:
    pipeline_steps = _batch_steps(content)
    try:
        index = pipeline_steps.index(step)
    except ValueError:
        return ""
    for next_step in pipeline_steps[index + 1 :]:
        if not _step_completed(steps, next_step):
            return next_step
    return ""


def _enqueue_batch_item_step(root: str | Path, item_path: str, step: str, workspace_path: str | None):
    from novel_forge.workers.dispatch import enqueue_task

    return enqueue_task("batch_item_step_task", str(Path(root).resolve()), item_path, step, workspace_path)


def _update_batch_item_status(
    storage: LocalStorage,
    item_path: Path,
    status: str,
    steps: list[dict[str, Any]],
    output_paths: list[str],
    error_message: str,
) -> None:
    data = storage.read_json(item_path)
    if not isinstance(data, dict):
        return
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    content.update(
        {
            "status": status,
            "steps": steps,
            "output_paths": output_paths,
            "error_message": error_message,
            "completed_at": utc_now() if status in {"completed", "failed"} else "",
        }
    )
    data["content"] = content
    data["tags"] = _dedupe_list(["batch-task-item", status, *[str(tag) for tag in data.get("tags", [])]])
    data["updated_at"] = utc_now()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    storage.write_json(item_path, data)


def _write_validated_json(storage: LocalStorage, path: Path, data: dict[str, Any]) -> None:
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    storage.write_json(path, data)


def _record_batch_handoff_on_item(storage: LocalStorage, item_path: Path, handoff_path: Path) -> None:
    data = storage.read_json(item_path)
    handoff = storage.read_json(handoff_path)
    if not isinstance(data, dict) or not isinstance(handoff, dict):
        return
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    history = content.get("handoff_history", []) if isinstance(content.get("handoff_history", []), list) else []
    generation = int(content.get("handoff_generation", 0)) + 1
    history.append(
        {
            "path": _display_path(storage.root, handoff_path),
            "id": handoff.get("id", ""),
            "status": handoff.get("content", {}).get("status", "pending") if isinstance(handoff.get("content", {}), dict) else "pending",
            "created_at": handoff.get("created_at", ""),
            "generation": generation,
        }
    )
    content.update(
        {
            "handoff_path": _display_path(storage.root, handoff_path),
            "handoff_id": handoff.get("id", ""),
            "handoff_status": "pending",
            "handoff_generation": generation,
            "handoff_history": history,
        }
    )
    data["content"] = content
    data["updated_at"] = utc_now()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    storage.write_json(item_path, data)


def _batch_item_row(storage: LocalStorage, path: Path, data: dict[str, Any]) -> dict[str, Any]:
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    outputs = content.get("output_paths", []) if isinstance(content.get("output_paths", []), list) else []
    by_key = {Path(str(item)).parent.name: str(item) for item in outputs}
    return {
        "path": _display_path(storage.root, path),
        "id": data.get("id", ""),
        "batch_id": content.get("batch_id", data.get("source", "")),
        "item_index": content.get("item_index", 0),
        "source_path": content.get("source_path", ""),
        "source_name": content.get("source_name", data.get("metadata", {}).get("source_name", "")),
        "status": content.get("status", ""),
        "steps": content.get("steps", []),
        "output_paths": outputs,
        "error_message": content.get("error_message", ""),
        "retry_count": content.get("retry_count", 0),
        "analysis_mode": content.get("analysis_mode", "auto"),
        "handoff_path": content.get("handoff_path", ""),
        "handoff_id": content.get("handoff_id", ""),
        "handoff_status": content.get("handoff_status", ""),
        "handoff_generation": content.get("handoff_generation", 0),
        "handoff_history": content.get("handoff_history", []),
        "review_status": content.get("review_status", ""),
        "review_gate": data.get("metadata", {}).get("review_gate", {}),
        "raw": by_key.get("raw", ""),
        "cleaned": by_key.get("cleaned", ""),
        "decomposition": by_key.get("decompositions", ""),
        "knowledge": by_key.get("knowledge", ""),
        "material": by_key.get("materials", ""),
        "updated_at": data.get("updated_at", ""),
    }


def _handoff_row(storage: LocalStorage, path: Path, data: dict[str, Any]) -> dict[str, Any]:
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    source_asset = content.get("source_asset", {}) if isinstance(content.get("source_asset", {}), dict) else {}
    manual = content.get("manual_execution", {}) if isinstance(content.get("manual_execution", {}), dict) else {}
    return {
        "path": _display_path(storage.root, path),
        "id": data.get("id", ""),
        "title": data.get("title") or data.get("name", ""),
        "operation": content.get("operation", ""),
        "skill": content.get("skill", ""),
        "status": content.get("status", ""),
        "runtime": content.get("runtime", ""),
        "runtime_model": content.get("runtime_model", ""),
        "source_asset_id": source_asset.get("id", data.get("source", "")),
        "source_path": source_asset.get("path", ""),
        "expected_output_type": content.get("expected_output_type", ""),
        "expected_output_dir": content.get("expected_output_dir", ""),
        "validation_command": manual.get("validation_command", "make validate"),
        "input_files": content.get("input_files", []),
        "acceptance_checks": content.get("acceptance_checks", []),
        "project_id": metadata.get("project_id", ""),
        "workspace_path": metadata.get("workspace_path", ""),
        "updated_at": data.get("updated_at", ""),
    }


def draft_workbench(storage: LocalStorage, project_id: str | None = None) -> dict[str, Any]:
    return {
        "chapter_plans": _asset_rows(storage, "chapter_plans", project_id=project_id),
        "drafts": _asset_rows(storage, "drafts", project_id=project_id),
        "reviews": _asset_rows(storage, "reviews", asset_type="review_report", project_id=project_id),
        "revision_plans": _asset_rows(storage, "reviews", asset_type="revision_plan", project_id=project_id),
        "workspace": [project_detail(storage, project_id)] if project_id else list_projects(storage)[:1],
    }


def draft_editor(storage: LocalStorage, draft_path: str) -> dict[str, Any]:
    path = resolve_path(storage.root, draft_path).resolve()
    path.relative_to(storage.root)
    data = storage.read_json(path)
    if not isinstance(data, dict) or data.get("type") != "draft_chapter":
        raise ValueError(f"draft_path must point to a draft_chapter asset: {draft_path}")
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    return {
        "path": _display_path(storage.root, path),
        "id": data.get("id", ""),
        "title": data.get("title") or data.get("name", ""),
        "chapter": content.get("chapter", ""),
        "text": content.get("text", ""),
        "version_index": metadata.get("version_index", 0),
        "root_draft_id": metadata.get("root_draft_id", data.get("id", "")),
        "status": metadata.get("draft_status", "draft"),
        "updated_at": data.get("updated_at", ""),
    }


def save_draft_edit(root: str | Path, request: dict[str, Any]) -> dict[str, Any]:
    storage = LocalStorage(root)
    storage.ensure_layout()
    path = resolve_path(storage.root, request.get("draft_path", "")).resolve()
    path.relative_to(storage.root)
    data = storage.read_json(path)
    if not isinstance(data, dict) or data.get("type") != "draft_chapter":
        raise ValueError(f"draft_path must point to a draft_chapter asset: {request.get('draft_path', '')}")
    text = str(request.get("text", ""))
    if not text.strip():
        raise ValueError("draft text must not be empty")
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    root_draft_id = str(metadata.get("root_draft_id") or data.get("id", ""))
    version_index = _next_draft_version_index(storage, root_draft_id)
    title = str(request.get("title") or data.get("title") or data.get("name") or f"Draft v{version_index}").strip()
    previous_text = str(content.get("text", ""))
    asset = DraftChapter(
        title=title,
        source=str(data.get("id", "")),
        tags=_dedupe_list([*data.get("tags", []), "draft", "manual-edit", f"v{version_index}"]),
        content={
            **content,
            "text": text,
            "chapter": request.get("chapter") or content.get("chapter", 1),
            "copyright_boundary": content.get("copyright_boundary", "operator-edited original draft"),
            "edit_summary": _text_diff_summary(previous_text, text),
        },
        metadata={
            **metadata,
            "draft_status": request.get("status", "edited"),
            "version_index": version_index,
            "root_draft_id": root_draft_id,
            "previous_draft_id": data.get("id", ""),
            "previous_draft_path": _display_path(storage.root, path),
            "edited_at": utc_now(),
        },
        references=_dedupe_list([str(data.get("id", "")), *[str(item) for item in data.get("references", [])]]),
    )
    new_path = storage.write_asset("drafts", asset)
    workspace_path = request.get("workspace_path")
    if workspace_path:
        attach_assets_to_project(storage, [new_path], str(workspace_path), role="draft-edit")
        pipeline.update_workspace(root, input_path=str(new_path), workspace_path=str(workspace_path), chapter=request.get("chapter"), status=str(request.get("status", "edited")))
    return {"draft_path": _display_path(storage.root, new_path), "editor": draft_editor(storage, str(new_path))}


def draft_diff(storage: LocalStorage, base_path: str, target_path: str) -> dict[str, Any]:
    base = draft_editor(storage, base_path)
    target = draft_editor(storage, target_path)
    base_lines = str(base["text"]).splitlines()
    target_lines = str(target["text"]).splitlines()
    lines = list(
        difflib.unified_diff(
            base_lines,
            target_lines,
            fromfile=base["path"],
            tofile=target["path"],
            lineterm="",
        )
    )
    return {
        "base_path": base["path"],
        "target_path": target["path"],
        "diff": "\n".join(lines),
        "summary": _text_diff_summary(str(base["text"]), str(target["text"])),
    }


def export_draft(root: str | Path, draft_path: str, export_format: str = "markdown") -> dict[str, Any]:
    export_format = export_format.lower()
    if export_format not in EXPORT_FORMATS:
        raise ValueError(f"format must be one of: {', '.join(sorted(EXPORT_FORMATS))}")
    storage = LocalStorage(root)
    editor = draft_editor(storage, draft_path)
    export_dir = storage.root / "data" / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    slug = _safe_filename(str(editor["title"] or editor["id"]))
    if export_format == "markdown":
        path = export_dir / f"{slug}.md"
        path.write_text(f"# {editor['title']}\n\n{editor['text']}\n", encoding="utf-8")
    elif export_format == "docx":
        path = export_dir / f"{slug}.docx"
        _write_minimal_docx(path, str(editor["title"]), str(editor["text"]))
    else:
        path = export_dir / f"{slug}.epub"
        _write_minimal_epub(path, str(editor["title"]), str(editor["text"]))
    return {
        "format": export_format,
        "path": _display_path(storage.root, path),
        "size_bytes": path.stat().st_size,
    }


def update_review_issue_status(storage: LocalStorage, request: dict[str, Any]) -> dict[str, Any]:
    path = resolve_path(storage.root, request.get("review_path", "")).resolve()
    path.relative_to(storage.root)
    data = storage.read_json(path)
    if not isinstance(data, dict) or data.get("type") != "review_report":
        raise ValueError(f"review_path must point to a review_report asset: {request.get('review_path', '')}")
    status = str(request.get("status", ""))
    if status not in REVIEW_ISSUE_STATUSES:
        raise ValueError(f"issue status must be one of: {', '.join(sorted(REVIEW_ISSUE_STATUSES))}")
    index = int(request.get("issue_index", -1))
    issues = data.get("issues", [])
    if not isinstance(issues, list) or index < 0 or index >= len(issues) or not isinstance(issues[index], dict):
        raise ValueError("issue_index is out of range")
    issues[index] = {
        **issues[index],
        "status": status,
        "operator_note": str(request.get("note") or ""),
        "status_updated_at": utc_now(),
    }
    data["issues"] = issues
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    metadata["issue_status_summary"] = _issue_status_summary(issues)
    data["metadata"] = metadata
    data["updated_at"] = utc_now()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    storage.write_json(path, data)
    return asset_detail(storage, str(path))


def apply_revision_plan(root: str | Path, request: dict[str, Any]) -> dict[str, Any]:
    storage = LocalStorage(root)
    storage.ensure_layout()
    revision_path = resolve_path(storage.root, request.get("revision_path", "")).resolve()
    revision_path.relative_to(storage.root)
    revision = storage.read_json(revision_path)
    if not isinstance(revision, dict) or revision.get("type") != "revision_plan":
        raise ValueError(f"revision_path must point to a revision_plan asset: {request.get('revision_path', '')}")
    review = _review_for_revision(storage, revision)
    draft = _draft_for_revision(storage, review, request.get("draft_path"))
    preview = _revision_preview(draft, revision, review)
    if not request.get("confirmed", False):
        return {
            "mode": "confirmation_required",
            "requires_confirmation": True,
            "revision_path": _display_path(storage.root, revision_path),
            "draft_path": draft["path"],
            "preview": preview,
        }

    draft_data = draft["asset"]
    content = draft_data.get("content", {}) if isinstance(draft_data.get("content", {}), dict) else {}
    original_text = str(content.get("text", ""))
    revised_text = _apply_revision_text(original_text, revision, review)
    version_index = _next_draft_version_index(storage, str(draft_data.get("metadata", {}).get("root_draft_id") or draft_data.get("id", "")))
    revised = DraftChapter(
        title=f"{draft_data.get('title') or draft_data.get('name') or 'Draft'} revised v{version_index}",
        source=str(draft_data.get("id", "")),
        tags=_dedupe_list([*draft_data.get("tags", []), "draft", "revised", f"v{version_index}"]),
        content={
            **content,
            "text": revised_text,
            "copyright_boundary": content.get("copyright_boundary", "revision generated from project review plan"),
            "revision_applied": {
                "revision_plan_id": revision.get("id", ""),
                "review_id": review.get("id", ""),
                "steps": revision.get("content", {}).get("steps", []),
            },
            "edit_summary": _text_diff_summary(original_text, revised_text),
        },
        metadata={
            **(draft_data.get("metadata", {}) if isinstance(draft_data.get("metadata", {}), dict) else {}),
            "draft_status": "revised",
            "version_index": version_index,
            "root_draft_id": draft_data.get("metadata", {}).get("root_draft_id", draft_data.get("id", "")),
            "previous_draft_id": draft_data.get("id", ""),
            "revision_plan_id": revision.get("id", ""),
            "review_id": review.get("id", ""),
            "confirmed_at": utc_now(),
        },
        references=_dedupe_list([str(draft_data.get("id", "")), str(revision.get("id", "")), str(review.get("id", "")), *[str(item) for item in draft_data.get("references", [])]]),
    )
    revised_path = storage.write_asset("drafts", revised)
    workspace_path = request.get("workspace_path") or _workspace_ref_from_asset(storage, draft["path"])
    if workspace_path:
        attach_assets_to_project(storage, [revised_path], str(workspace_path), role="revision-draft")
        pipeline.update_workspace(root, input_path=str(revised_path), workspace_path=str(workspace_path), status="revised")
    after_review_path = None
    after_score = None
    if request.get("review_after", True):
        after_review_path = pipeline.review(root, str(revised_path))
        after_data = storage.read_json(after_review_path)
        after_score = after_data.get("score") if isinstance(after_data, dict) else None
        if workspace_path:
            attach_assets_to_project(storage, [after_review_path], str(workspace_path), role="revision-review")
    return {
        "mode": "applied",
        "requires_confirmation": False,
        "draft_path": _display_path(storage.root, revised_path),
        "after_review_path": _display_path(storage.root, after_review_path) if after_review_path else "",
        "score_before": review.get("score"),
        "score_after": after_score,
        "target_score": revision.get("content", {}).get("target_score"),
        "preview": preview,
    }


def _asset_rows(
    storage: LocalStorage,
    category: str,
    asset_type: str | None = None,
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    project = _project_identity(storage, project_id) if project_id else None
    rows = []
    for path in reversed(storage.list_json(category)):
        data = storage.read_json(path)
        if not isinstance(data, dict):
            continue
        if asset_type and data.get("type") != asset_type:
            continue
        if project and not _belongs_to_project(data, path, project):
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        rows.append(
            {
                "path": _display_path(storage.root, path),
                "id": data.get("id", ""),
                "type": data.get("type", ""),
                "title": data.get("title") or data.get("name", ""),
                "source": data.get("source", ""),
                "chapter": content.get("chapter", ""),
                "score": data.get("score"),
                "risk_level": data.get("risk_level") or data.get("metadata", {}).get("risk_level", ""),
                "asset_status": data.get("metadata", {}).get("asset_status", ""),
                "updated_at": data.get("updated_at", ""),
                "summary": _content_preview(content),
                "tags": data.get("tags", []),
            }
        )
    return rows


def _project_asset_row(
    storage: LocalStorage,
    path: Path,
    category: str,
    data: dict[str, Any],
    index_source: str = "json",
) -> dict[str, Any]:
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    return {
        "path": _display_path(storage.root, path),
        "id": data.get("id", ""),
        "category": category,
        "type": data.get("type", ""),
        "title": data.get("title") or data.get("name", ""),
        "source": data.get("source", ""),
        "chapter": content.get("chapter", ""),
        "score": data.get("score"),
        "risk_level": data.get("risk_level") or metadata.get("risk_level", ""),
        "asset_status": metadata.get("asset_status", ""),
        "project_role": metadata.get("project_asset_role", ""),
        "updated_at": data.get("updated_at", ""),
        "tags": data.get("tags", []),
        "index_source": index_source,
    }


def _project_summary(storage: LocalStorage, path: Path, data: dict[str, Any]) -> dict[str, Any]:
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    memory = content.get("memory", {}) if isinstance(content.get("memory", {}), dict) else {}
    threads = content.get("continuity_threads", {}) if isinstance(content.get("continuity_threads", {}), dict) else {}
    chapter_states = content.get("chapter_states", []) if isinstance(content.get("chapter_states", []), list) else []
    open_issues = content.get("open_issues", []) if isinstance(content.get("open_issues", []), list) else []
    config = _project_config(data)
    return {
        "path": _display_path(storage.root, path),
        "id": data.get("id", ""),
        "project_id": content.get("project_id", ""),
        "title": data.get("title") or data.get("name", ""),
        "series_title": memory.get("series_title", data.get("metadata", {}).get("series_title", "")),
        "book_number": memory.get("book_number", data.get("metadata", {}).get("book_number")),
        "chapter_count": len(chapter_states),
        "latest_chapter": data.get("metadata", {}).get("latest_chapter", 0),
        "open_hook_count": len(threads.get("open_hooks", [])) if isinstance(threads, dict) else 0,
        "open_issue_count": len(open_issues),
        "updated_at": data.get("updated_at", ""),
        "status": config.get("status", "active"),
        "project_config": config,
    }


def _workspace_path_by_id_or_path(storage: LocalStorage, project_id_or_path: str) -> Path:
    candidate = resolve_path(storage.root, project_id_or_path).resolve()
    try:
        candidate.relative_to(storage.root)
        if candidate.exists():
            return candidate
    except ValueError:
        pass
    for path in storage.list_json("workspaces"):
        data = storage.read_json(path)
        if not isinstance(data, dict):
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if project_id_or_path in {data.get("id"), content.get("project_id")}:
            return path
    raise FileNotFoundError(f"project workspace not found: {project_id_or_path}")


def _project_identity(storage: LocalStorage, project_id_or_path: str | None) -> dict[str, Any]:
    if not project_id_or_path:
        path = storage.latest("workspaces")
    else:
        path = _workspace_path_by_id_or_path(storage, project_id_or_path)
    data = storage.read_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"workspace JSON must be an object: {path}")
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    return {
        "path": path,
        "workspace_path": _display_path(storage.root, path),
        "workspace_id": str(data.get("id", "")),
        "project_id": str(content.get("project_id", data.get("id", ""))),
        "references": {str(item) for item in data.get("references", []) if str(item).strip()},
        "chapter_asset_ids": _workspace_chapter_asset_ids(content),
    }


def _project_config(data: dict[str, Any]) -> dict[str, Any]:
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    raw_config = content.get("project_config", {}) if isinstance(content.get("project_config", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    return {
        **DEFAULT_PROJECT_CONFIG,
        **{
            "target_platform": metadata.get("target_platform", DEFAULT_PROJECT_CONFIG["target_platform"]),
            "quality_threshold": metadata.get("quality_threshold", DEFAULT_PROJECT_CONFIG["quality_threshold"]),
            "status": metadata.get("project_status", DEFAULT_PROJECT_CONFIG["status"]),
        },
        **raw_config,
    }


def _workspace_chapter_asset_ids(content: dict[str, Any]) -> set[str]:
    states = content.get("chapter_states", []) if isinstance(content.get("chapter_states", []), list) else []
    ids: set[str] = set()
    for state in states:
        if not isinstance(state, dict):
            continue
        for key in ["asset_id", "draft_asset_id", "review_asset_id"]:
            value = state.get(key)
            if isinstance(value, str) and value:
                ids.add(value)
    return ids


def _belongs_to_project(data: dict[str, Any], path: Path, project: dict[str, Any]) -> bool:
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    references = {str(item) for item in data.get("references", []) if str(item).strip()}
    identity_values = {project["project_id"], project["workspace_id"], project["workspace_path"]}
    if data.get("id") == project["workspace_id"] or content.get("project_id") == project["project_id"]:
        return True
    if metadata.get("project_id") == project["project_id"]:
        return True
    if metadata.get("workspace_path") == project["workspace_path"]:
        return True
    if data.get("id") in project["references"] or data.get("id") in project["chapter_asset_ids"]:
        return True
    if references.intersection(identity_values):
        return True
    return False


def _task_touches_project(task: dict[str, Any], project_paths: set[str]) -> bool:
    touched = {str(item) for item in task.get("input_paths", [])}
    touched.update(str(item) for item in task.get("output_paths", []))
    touched.add(str(task.get("path", "")))
    return bool(touched.intersection(project_paths))


def _task_event(storage: LocalStorage, path: Path, data: dict[str, Any], content: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": _display_path(storage.root, path),
        "id": data.get("id", ""),
        "run_id": content.get("run_id", data.get("source", "")),
        "step": content.get("step", ""),
        "status": content.get("status", ""),
        "task_type": "workflow",
        "input_paths": content.get("input_paths", []),
        "output_paths": content.get("output_paths", []),
        "error_message": content.get("error_message", ""),
        "recorded_at": data.get("metadata", {}).get("recorded_at", data.get("updated_at", "")),
        "message": _task_message(content),
    }


def _handoff_task_event(storage: LocalStorage, path: Path, data: dict[str, Any]) -> dict[str, Any]:
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    source_asset = content.get("source_asset", {}) if isinstance(content.get("source_asset", {}), dict) else {}
    operation = str(content.get("operation") or "claude_handoff")
    status = str(content.get("status") or "pending")
    output_paths = content.get("output_paths", []) if isinstance(content.get("output_paths", []), list) else []
    input_paths = []
    source_path = str(source_asset.get("path") or data.get("source") or "")
    if source_path:
        input_paths.append(source_path)
    input_files = content.get("input_files", []) if isinstance(content.get("input_files", []), list) else []
    for item in input_files:
        if isinstance(item, dict) and item.get("role") == "source_asset" and item.get("path"):
            input_paths.append(str(item["path"]))
    event_content = {
        "step": f"handoff:{operation}",
        "status": status,
        "output_paths": output_paths,
        "error_message": content.get("status_reason", metadata.get("status_reason", "")),
    }
    return {
        "path": _display_path(storage.root, path),
        "id": data.get("id", ""),
        "run_id": data.get("id", ""),
        "step": event_content["step"],
        "status": status,
        "task_type": "handoff",
        "input_paths": _dedupe_list(input_paths),
        "output_paths": output_paths,
        "error_message": event_content["error_message"],
        "recorded_at": metadata.get(f"{status}_at", data.get("updated_at", data.get("created_at", ""))),
        "message": _task_message(event_content),
        "operation": operation,
        "expected_output_type": content.get("expected_output_type", ""),
        "project_id": metadata.get("project_id", ""),
        "workspace_path": metadata.get("workspace_path", ""),
    }


def _task_row_from_payload(storage: LocalStorage, path: str, data: dict[str, Any]) -> dict[str, Any]:
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    return {
        "path": path,
        "id": data.get("id", ""),
        "run_id": content.get("run_id", data.get("source", "")),
        "step": content.get("step", ""),
        "status": content.get("status", ""),
        "task_type": "workflow",
        "input_paths": content.get("input_paths", []),
        "output_paths": content.get("output_paths", []),
        "error_message": content.get("error_message", ""),
        "recorded_at": data.get("metadata", {}).get("recorded_at", data.get("updated_at", "")),
        "index_source": "postgres" if path else "json",
    }


def _task_event_from_row(row: dict[str, Any]) -> dict[str, Any]:
    content = {
        "step": row.get("step", ""),
        "status": row.get("status", ""),
        "output_paths": row.get("output_paths", []),
        "error_message": row.get("error_message", ""),
    }
    return {
        "path": row.get("path", ""),
        "id": row.get("id", ""),
        "run_id": row.get("run_id", ""),
        "step": row.get("step", ""),
        "status": row.get("status", ""),
        "task_type": row.get("task_type", "workflow"),
        "input_paths": row.get("input_paths", []),
        "output_paths": row.get("output_paths", []),
        "error_message": row.get("error_message", ""),
        "recorded_at": row.get("recorded_at", ""),
        "message": _task_message(content),
    }


def _latest_task_rows(
    events: list[dict[str, Any]],
    status: str | None = None,
    step: str | None = None,
    offset: int = 0,
    limit: int = 100,
) -> tuple[list[dict[str, Any]], int]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for event in events:
        key = (
            str(event.get("task_type", "workflow")),
            str(event.get("run_id", "")),
            str(event.get("step", "")),
        )
        grouped.setdefault(key, []).append(event)
    rows = []
    for grouped_events in grouped.values():
        ordered = sorted(grouped_events, key=lambda item: (item["recorded_at"], _status_order(item["status"]), item["path"]))
        latest = {**ordered[-1], "event_count": len(grouped_events)}
        if status and latest.get("status") != status:
            continue
        if step and latest.get("step") != step:
            continue
        rows.append(latest)
    ordered_rows = sorted(rows, key=lambda item: (item["recorded_at"], _status_order(item["status"]), item["path"]), reverse=True)
    return ordered_rows[offset : offset + limit], len(ordered_rows)


def _filter_task_events(
    events: list[dict[str, Any]],
    task_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict[str, Any]]:
    filtered = []
    for event in events:
        if task_type and event.get("task_type") != task_type:
            continue
        recorded_at = str(event.get("recorded_at", ""))
        if date_from and recorded_at and recorded_at < date_from:
            continue
        if date_to and recorded_at and recorded_at > date_to:
            continue
        filtered.append(event)
    return filtered


def _task_timeline_payload(events: list[dict[str, Any]], limit: int) -> dict[str, Any]:
    events = sorted(events, key=lambda item: (item["recorded_at"], _status_order(item["status"]), item["path"]))[-limit:]
    runs = _timeline_runs(events)
    return {
        "events": events,
        "runs": runs,
        "summary": {
            "event_count": len(events),
            "run_count": len(runs),
            "failed_count": sum(1 for event in events if event["status"] == "failed"),
            "latest_at": events[-1]["recorded_at"] if events else "",
        },
    }


def _task_message(content: dict[str, Any]) -> str:
    step = content.get("step", "")
    status = content.get("status", "")
    if status == "failed":
        return f"{step} failed: {content.get('error_message', '')}"
    if status == "completed":
        outputs = content.get("output_paths", [])
        return f"{step} completed with {len(outputs) if isinstance(outputs, list) else 0} output(s)"
    if status == "superseded":
        return f"{step} superseded"
    if status == "in_progress":
        return f"{step} in progress"
    return f"{step} {status}"


def _timeline_runs(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        grouped.setdefault(str(event.get("run_id", "")), []).append(event)
    runs = []
    for run_id, run_events in grouped.items():
        by_step: dict[str, str] = {}
        for event in sorted(run_events, key=lambda item: (item["recorded_at"], _status_order(item["status"]), item["path"])):
            by_step[str(event.get("step", ""))] = str(event.get("status", ""))
        total = max(1, len(by_step))
        completed = sum(1 for status in by_step.values() if status in {"completed", "superseded"})
        failed = [step for step, status in by_step.items() if status == "failed"]
        running = [step for step, status in by_step.items() if status in {"running", "in_progress"}]
        if failed:
            status = "failed"
        elif running:
            status = "running"
        elif completed == total:
            status = "completed"
        else:
            status = "pending"
        runs.append(
            {
                "run_id": run_id,
                "status": status,
                "progress_percent": round((completed / total) * 100, 2),
                "completed_steps": completed,
                "total_steps": total,
                "failed_steps": failed,
                "latest_event_at": max(event["recorded_at"] for event in run_events),
            }
        )
    return sorted(runs, key=lambda item: item["latest_event_at"], reverse=True)


def _run_events(storage: LocalStorage, run_id: str) -> list[dict[str, Any]]:
    events = []
    for path in storage.list_json("runs"):
        data = storage.read_json(path)
        if not isinstance(data, dict) or data.get("type") != "task_status":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if content.get("run_id", data.get("source", "")) == run_id:
            events.append(_task_event(storage, path, data, content))
    return sorted(events, key=lambda item: (item["recorded_at"], _status_order(item["status"]), item["path"]))


def _find_task_status(
    storage: LocalStorage,
    status_path: str | None = None,
    run_id: str | None = None,
    step: str | None = None,
) -> dict[str, Any]:
    if status_path:
        path = resolve_path(storage.root, status_path).resolve()
        path.relative_to(storage.root)
        data = storage.read_json(path)
        if not isinstance(data, dict) or data.get("type") != "task_status":
            raise ValueError(f"status_path must point to a task_status asset: {status_path}")
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        return _task_event(storage, path, data, content)
    candidates = []
    for path in storage.list_json("runs"):
        data = storage.read_json(path)
        if not isinstance(data, dict) or data.get("type") != "task_status":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        event = _task_event(storage, path, data, content)
        if run_id and event["run_id"] != run_id:
            continue
        if step and event["step"] != step:
            continue
        if event["status"] == "failed":
            candidates.append(event)
    if not candidates:
        raise FileNotFoundError("no matching failed task_status asset found")
    return sorted(candidates, key=lambda item: (item["recorded_at"], _status_order(item["status"]), item["path"]))[-1]


def _status_order(status: str) -> int:
    return {"pending": 0, "in_progress": 1, "running": 1, "failed": 2, "superseded": 3, "completed": 4}.get(status, 9)


def _execute_retry_step(root: str | Path, step: str, input_paths: list[str]) -> Path:
    input_path = input_paths[0] if input_paths else None
    if step == "ingest":
        if not input_path:
            raise ValueError("retrying ingest requires an input path")
        return pipeline.ingest(root, input_path)
    if step == "clean":
        return pipeline.clean(root, input_path)
    if step == "decompose":
        return pipeline.decompose(root, input_path)
    if step == "extract-knowledge":
        return pipeline.extract_knowledge(root, input_path)
    if step == "build-materials":
        return pipeline.build_materials(root, input_path)
    if step in {"generate-topic", "topic-development"}:
        return pipeline.generate_topic(root, input_path)
    if step == "generate-world":
        return pipeline.generate_world(root, input_path)
    if step == "generate-characters":
        return pipeline.generate_characters(root, input_path)
    if step == "generate-outline":
        return pipeline.generate_outline(root, input_path)
    if step == "generate-chapter-plan":
        return pipeline.generate_chapter_plan(root, input_path)
    if step == "draft":
        return pipeline.draft(root, input_path)
    if step == "review":
        return pipeline.review(root, input_path)
    if step == "compare-reviews":
        return pipeline.compare_reviews(root, input_path)
    if step == "revise":
        return pipeline.revise(root, input_path)
    if step == "import-feedback":
        if not input_path:
            raise ValueError("retrying import-feedback requires an input path")
        return pipeline.import_feedback(root, input_path)
    if step == "analyze-feedback":
        return pipeline.analyze_feedback(root, input_path)
    if step == "init-workspace":
        return pipeline.init_workspace(root)
    if step.startswith("update-workspace"):
        asset_path = input_paths[0] if input_paths else None
        workspace_path = input_paths[1] if len(input_paths) > 1 else None
        status = "reviewed" if "review" in step else "drafted"
        return pipeline.update_workspace(root, input_path=asset_path, workspace_path=workspace_path, status=status)
    raise ValueError(f"unsupported retry step: {step}")


def _annotate_retry_statuses(storage: LocalStorage, status_paths: list[Path], original_task: dict[str, Any]) -> None:
    for path in status_paths:
        data = storage.read_json(path)
        if not isinstance(data, dict):
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        metadata.update(
            {
                "retry_of_status_path": original_task.get("path", ""),
                "retry_of_run_id": original_task.get("run_id", ""),
                "retry_of_step": original_task.get("step", ""),
            }
        )
        data["metadata"] = metadata
        storage.write_json(path, data)


def _add_workspace_references(storage: LocalStorage, project: dict[str, Any], asset_paths: list[str]) -> None:
    if not asset_paths:
        return
    path = project["path"]
    data = storage.read_json(path)
    if not isinstance(data, dict):
        return
    references = [str(item) for item in data.get("references", []) if str(item).strip()]
    for asset_path in asset_paths:
        try:
            asset_data = storage.read_json(resolve_path(storage.root, asset_path))
        except Exception:
            continue
        if isinstance(asset_data, dict):
            asset_id = str(asset_data.get("id", ""))
            if asset_id and asset_id not in references:
                references.append(asset_id)
    data["references"] = references
    data["updated_at"] = utc_now()
    storage.write_json(path, data)


def _workspace_ref_from_asset(storage: LocalStorage, asset_path: str | None) -> str | None:
    if not asset_path:
        return None
    try:
        data = storage.read_json(resolve_path(storage.root, asset_path))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    return metadata.get("workspace_path") or metadata.get("workspace_id") or metadata.get("project_id")


def _workspace_ref_from_request_or_assets(storage: LocalStorage, request: dict[str, Any], *asset_paths: str | Path | None) -> str | None:
    request_ref = request.get("workspace_path")
    if request_ref:
        return str(request_ref)
    for asset_path in asset_paths:
        if asset_path:
            ref = _workspace_ref_from_asset(storage, _display_path(storage.root, resolve_path(storage.root, asset_path)))
            if ref:
                return str(ref)
    return None


def _task_summary(tasks: list[dict[str, Any]], runs: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for task in tasks:
        status = str(task.get("status", "unknown"))
        counts[status] = counts.get(status, 0) + 1
    return {
        "task_count": len(tasks),
        "workflow_run_count": len(runs),
        "by_status": counts,
    }


def _resolve_asset_file(storage: LocalStorage, asset_path: str) -> Path:
    path = resolve_path(storage.root, asset_path).resolve()
    try:
        path.relative_to(storage.root)
    except ValueError as exc:
        raise ValueError(f"asset path escapes project root: {asset_path}") from exc
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"asset not found: {asset_path}")
    return path


def _asset_version_row(storage: LocalStorage, path: Path, data: dict[str, Any], kind: str) -> dict[str, Any]:
    text = json.dumps(data, ensure_ascii=False, sort_keys=True)
    return {
        "path": _display_path(storage.root, path),
        "kind": kind,
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "size_bytes": path.stat().st_size,
        "updated_at": str(data.get("updated_at", "")),
        "title": data.get("title") or data.get("name", ""),
        "type": data.get("type", ""),
    }


def _backup_version_rows(storage: LocalStorage, path: Path) -> list[dict[str, Any]]:
    try:
        relative = path.relative_to(storage.root)
    except ValueError:
        return []
    backup_parent = storage.data_root / "backups" / relative.parent
    if not backup_parent.exists():
        return []
    rows = []
    for backup_path in sorted(backup_parent.glob(f"{path.stem}.*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            data = storage.read_json(backup_path)
        except Exception:
            continue
        if isinstance(data, dict):
            rows.append(_asset_version_row(storage, backup_path, data, "backup"))
    return rows


def _json_unified_diff(before: Any, after: Any, from_path: str, to_path: str) -> str:
    before_lines = json.dumps(before, ensure_ascii=False, indent=2, sort_keys=True).splitlines()
    after_lines = json.dumps(after, ensure_ascii=False, indent=2, sort_keys=True).splitlines()
    return "\n".join(difflib.unified_diff(before_lines, after_lines, fromfile=from_path, tofile=to_path, lineterm=""))


def _asset_records(storage: LocalStorage) -> list[dict[str, Any]]:
    records = []
    for category in DATA_DIRS:
        for path in storage.list_json(category):
            try:
                data = storage.read_json(path)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            records.append(
                {
                    "id": str(data.get("id", "")),
                    "path": _display_path(storage.root, path),
                    "absolute_path": path,
                    "category": category,
                    "type": data.get("type", ""),
                    "title": data.get("title") or data.get("name", ""),
                    "data": data,
                }
            )
    return records


def _graph_node(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": record["id"],
        "path": record["path"],
        "category": record["category"],
        "type": record["type"],
        "title": record["title"],
    }


def _add_graph_edge(
    edges: list[dict[str, str]],
    edge_keys: set[tuple[str, str, str]],
    source: str,
    target: str,
    relation: str,
) -> None:
    key = (source, target, relation)
    if key in edge_keys:
        return
    edge_keys.add(key)
    edges.append({"source": source, "target": target, "relation": relation})


def _linked_records(
    data: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
    by_path: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    linked = []
    seen: set[str] = set()
    for value in _asset_link_values(data):
        record = by_id.get(value) or by_path.get(value)
        if not record or not record["id"] or record["id"] in seen:
            continue
        linked.append(record)
        seen.add(record["id"])
    return linked


def _asset_link_values(value: Any) -> set[str]:
    links: set[str] = set()
    if isinstance(value, dict):
        for child in value.values():
            links.update(_asset_link_values(child))
    elif isinstance(value, list):
        for child in value:
            links.update(_asset_link_values(child))
    elif isinstance(value, str) and value.strip():
        links.add(value.strip())
    return links


def _reference_assets(storage: LocalStorage, data: dict[str, Any]) -> list[dict[str, Any]]:
    references = {str(item) for item in data.get("references", []) if str(item).strip()}
    source = str(data.get("source", ""))
    if source:
        references.add(source)
    matches = []
    for category in ["raw", "cleaned", "decompositions", "knowledge", "materials", "topics", "worlds", "characters", "outlines", "chapter_plans", "drafts", "reviews", "feedback", "workspaces", "runs"]:
        for path in storage.list_json(category):
            try:
                candidate = storage.read_json(path)
            except Exception:
                continue
            if not isinstance(candidate, dict):
                continue
            if candidate.get("id") in references:
                matches.append(
                    {
                        "path": _display_path(storage.root, path),
                        "id": candidate.get("id", ""),
                        "type": candidate.get("type", ""),
                        "title": candidate.get("title") or candidate.get("name", ""),
                    }
                )
    return matches


def _asset_summary(data: dict[str, Any]) -> dict[str, Any]:
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    return {
        "id": data.get("id", ""),
        "type": data.get("type", ""),
        "title": data.get("title") or data.get("name", ""),
        "tags": data.get("tags", []),
        "source": data.get("source", ""),
        "chapter": content.get("chapter", ""),
        "score": data.get("score"),
        "risk_level": data.get("risk_level") or metadata.get("risk_level", ""),
        "asset_status": metadata.get("asset_status", ""),
        "operator_notes": metadata.get("operator_notes", ""),
        "rights": metadata.get("rights", {}),
        "preview": _content_preview(content),
    }


def _asset_search_text(data: dict[str, Any]) -> str:
    payload = {
        "id": data.get("id", ""),
        "type": data.get("type", ""),
        "title": data.get("title", ""),
        "name": data.get("name", ""),
        "source": data.get("source", ""),
        "tags": data.get("tags", []),
        "content": data.get("content", {}),
        "metadata": data.get("metadata", {}),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True).lower()


def _content_preview(content: dict[str, Any]) -> str:
    for key in ["text", "summary", "logline", "objective", "hook"]:
        value = content.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())[:220]
    return ""


def _display_path(root: str | Path, path: Path) -> str:
    resolved_root = Path(root).resolve()
    try:
        return str(path.relative_to(resolved_root))
    except ValueError:
        return str(path)


def _postgres_store(settings: Any) -> PostgresAssetStore | None:
    database_url = getattr(settings, "database_url", "")
    if not database_url:
        if getattr(settings, "postgres_write_strict", False):
            raise RuntimeError("NOVEL_FORGE_POSTGRES_WRITE_STRICT is enabled but DATABASE_URL is empty")
        return None
    try:
        return PostgresAssetStore(database_url)
    except Exception as exc:
        if getattr(settings, "postgres_write_strict", False):
            raise RuntimeError(f"PostgreSQL store initialization failed in strict mode: {exc}") from exc
        return None


def _sync_postgres_best_effort(settings: Any, paths: list[str | Path] | None = None) -> dict[str, Any]:
    store = _postgres_store(settings)
    if not store:
        return {"enabled": False, "synced": 0, "error": ""}
    storage = LocalStorage(settings.root)
    try:
        if paths:
            synced = 0
            for path in paths:
                if store.sync_asset(storage, path):
                    synced += 1
            return {"enabled": True, "synced": synced, "error": ""}
        result = store.sync_from_local(storage)
        return {"enabled": True, "synced": result.assets, "error": ""}
    except Exception as exc:
        if getattr(settings, "postgres_write_strict", False):
            raise
        return {"enabled": True, "synced": 0, "error": str(exc)}


def postgres_strict_local_prod_check(settings: Any, sync: bool = False, raise_on_failure: bool = True) -> dict[str, Any]:
    strict = bool(getattr(settings, "postgres_write_strict", False))
    write_through = bool(getattr(settings, "postgres_write_through", False))
    database_url = str(getattr(settings, "database_url", "") or "")
    checks: list[dict[str, Any]] = []
    errors: list[str] = []
    result: dict[str, Any] = {
        "strict": strict,
        "write_through": write_through,
        "database_url_configured": bool(database_url),
        "ready": True,
        "checks": checks,
        "sync": {},
        "errors": errors,
    }
    if not strict:
        checks.append({"name": "strict_mode", "ok": True, "message": "PostgreSQL strict mode disabled"})
        if database_url and sync:
            try:
                store = PostgresAssetStore(database_url)
                store.initialize()
                local_storage = LocalStorage(settings.root)
                sync_result = store.sync_from_local(local_storage).to_dict()
                result["sync"] = sync_result
                checks.append(
                    {
                        "name": "startup_backfill",
                        "ok": True,
                        "message": "Local JSON assets synced into PostgreSQL for indexed reads",
                        "counts": sync_result,
                    }
                )
            except Exception as exc:
                errors.append(str(exc))
                checks.append({"name": "startup_backfill", "ok": False, "message": str(exc)})
        return result
    if not database_url:
        errors.append("DATABASE_URL or NOVEL_FORGE_DATABASE_URL must be set when strict mode is enabled")
        result["ready"] = False
    if not write_through:
        errors.append("NOVEL_FORGE_POSTGRES_WRITE_THROUGH must remain enabled in strict mode")
        result["ready"] = False
    if not result["ready"]:
        if raise_on_failure:
            raise RuntimeError("; ".join(errors))
        return result
    try:
        store = PostgresAssetStore(database_url)
        store.initialize()
        checks.append({"name": "schema", "ok": True, "message": "PostgreSQL schema initialized"})
        if sync:
            local_storage = LocalStorage(settings.root)
            sync_result = store.sync_from_local(local_storage).to_dict()
            result["sync"] = sync_result
            checks.append({"name": "backfill", "ok": True, "message": "Local JSON assets synced into PostgreSQL", "counts": sync_result})
            indexed_total = len(store.list_assets(limit=max(sync_result.get("assets", 0) + 10, 100)))
            local_total = sum(local_storage.counts().values())
            consistent = indexed_total >= local_total
            checks.append(
                {
                    "name": "index_consistency",
                    "ok": consistent,
                    "message": f"indexed assets {indexed_total}, local assets {local_total}",
                    "counts": {"indexed": indexed_total, "local": local_total},
                }
            )
            if not consistent:
                errors.append(f"PostgreSQL index is incomplete: indexed {indexed_total}, local {local_total}")
                result["ready"] = False
    except Exception as exc:
        errors.append(str(exc))
        result["ready"] = False
        checks.append({"name": "postgres", "ok": False, "message": str(exc)})
    if not result["ready"] and raise_on_failure:
        raise RuntimeError("; ".join(errors))
    return result


def create_local_backup(settings: Any) -> dict[str, Any]:
    root = Path(settings.root).resolve()
    backup_dir = root / "data" / "backups" / "local-prod"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = utc_now().replace(":", "").replace("-", "")
    backup_path = backup_dir / f"novel-forge-local-prod-{stamp}.zip"
    manifest = {
        "created_at": utc_now(),
        "root": str(root),
        "kind": "local_prod_backup",
        "includes": ["data", ".env", ".env.example", "docker-compose.yml", "pyproject.toml"],
        "external_services": {
            "postgres": {
                "configured": bool(getattr(settings, "database_url", "")),
                "backup_boundary": "use docker compose exec postgres pg_dump for database-level dump if strict Postgres is primary",
            },
            "minio": {
                "configured": bool(getattr(settings, "minio_endpoint", "")),
                "backup_boundary": "object copies are represented by local metadata; use mc mirror for bucket-level backup",
            },
            "qdrant": {
                "configured": bool(getattr(settings, "qdrant_url", "")),
                "backup_boundary": "vector index can be rebuilt from assets; use Qdrant snapshots for production volume backup",
            },
        },
    }
    with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("backup-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        for rel in [".env", ".env.example", "docker-compose.yml", "pyproject.toml", "Makefile"]:
            path = root / rel
            if path.exists() and path.is_file():
                archive.write(path, rel)
        data_root = root / "data"
        if data_root.exists():
            for path in data_root.rglob("*"):
                if not path.is_file():
                    continue
                try:
                    relative = path.relative_to(root)
                except ValueError:
                    continue
                if relative.parts[:3] == ("data", "backups", "local-prod"):
                    continue
                archive.write(path, str(relative))
    return {
        "path": _display_path(root, backup_path),
        "size_bytes": backup_path.stat().st_size,
        "manifest": manifest,
    }


def list_local_backups(root: str | Path, limit: int = 20) -> list[dict[str, Any]]:
    folder = Path(root).resolve() / "data" / "backups" / "local-prod"
    if not folder.exists():
        return []
    rows = []
    for path in sorted(folder.glob("*.zip"), key=lambda item: item.stat().st_mtime, reverse=True)[:limit]:
        rows.append(
            {
                "path": _display_path(root, path),
                "size_bytes": path.stat().st_size,
                "created_at": utc_now_from_mtime(path),
            }
        )
    return rows


def restore_local_backup(root: str | Path, backup_path_value: str, confirm: bool = False) -> dict[str, Any]:
    if not confirm:
        raise ValueError("restore requires confirm=true")
    root_path = Path(root).resolve()
    backup_path = resolve_path(root_path, backup_path_value).resolve()
    backup_path.relative_to(root_path)
    if not backup_path.exists() or backup_path.suffix != ".zip":
        raise FileNotFoundError(f"backup zip not found: {backup_path_value}")
    restored: list[str] = []
    with zipfile.ZipFile(backup_path, "r") as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            target = root_path / member.filename
            target = target.resolve()
            target.relative_to(root_path)
            if not _restore_member_allowed(member.filename):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as destination:
                shutil.copyfileobj(source, destination)
            restored.append(member.filename)
    return {"backup_path": _display_path(root_path, backup_path), "restored_count": len(restored), "restored": restored[:200]}


def _restore_member_allowed(filename: str) -> bool:
    path = Path(filename)
    if path.is_absolute() or ".." in path.parts:
        return False
    return path.parts[:1] == ("data",) or filename in {".env", ".env.example", "docker-compose.yml", "pyproject.toml", "Makefile", "backup-manifest.json"}


def utc_now_from_mtime(path: Path) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def _record_lifecycle_event(data: dict[str, Any], action: str, from_status: str, to_status: str, reason: str = "") -> None:
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    events = metadata.get("lifecycle_events", []) if isinstance(metadata.get("lifecycle_events", []), list) else []
    events.append(
        {
            "action": action,
            "from_status": from_status,
            "to_status": to_status,
            "reason": reason,
            "at": utc_now(),
        }
    )
    metadata["lifecycle_events"] = events
    data["metadata"] = metadata


def _rights_payload(
    authorization: str,
    license_name: str,
    copyright_note: str,
    source_url: str,
    allow_downstream_generation: bool,
) -> dict[str, Any]:
    return {
        "authorization": authorization,
        "license": license_name,
        "copyright_boundary": copyright_note or "recorded source; do not copy protected expression",
        "source_url": source_url,
        "allow_downstream_generation": allow_downstream_generation,
    }


def _read_task_control(root: str | Path) -> dict[str, int]:
    path = Path(root).resolve() / TASK_CONTROL_RELATIVE_PATH
    if not path.exists():
        return dict(DEFAULT_TASK_CONTROL)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return dict(DEFAULT_TASK_CONTROL)
    config = dict(DEFAULT_TASK_CONTROL)
    for key in config:
        try:
            value = int(data.get(key, config[key]))
        except Exception:
            value = config[key]
        config[key] = max(1, value)
    return config


def _celery_app_or_error() -> Any:
    try:
        from novel_forge.workers.tasks import celery_app
    except Exception as exc:
        raise RuntimeError(f"Celery task import failed: {exc}") from exc
    if celery_app is None:
        raise RuntimeError("Celery is not installed or configured")
    return celery_app


def _celery_inspection(settings: Any) -> dict[str, Any]:
    try:
        celery_app = _celery_app_or_error()
    except Exception as exc:
        return {
            "available": False,
            "healthy": False,
            "error": str(exc),
            "workers": {},
            "active_count": 0,
            "reserved_count": 0,
            "scheduled_count": 0,
            "queue_lengths": {},
        }
    try:
        inspector = celery_app.control.inspect(timeout=0.5)
        ping = inspector.ping() or {}
        active = inspector.active() or {}
        reserved = inspector.reserved() or {}
        scheduled = inspector.scheduled() or {}
    except Exception as exc:
        return {
            "available": True,
            "healthy": False,
            "error": str(exc),
            "workers": {},
            "active_count": 0,
            "reserved_count": 0,
            "scheduled_count": 0,
            "queue_lengths": _redis_queue_lengths(settings),
        }
    return {
        "available": True,
        "healthy": bool(ping),
        "error": "",
        "workers": ping,
        "active_count": sum(len(items) for items in active.values()),
        "reserved_count": sum(len(items) for items in reserved.values()),
        "scheduled_count": sum(len(items) for items in scheduled.values()),
        "queue_lengths": _redis_queue_lengths(settings),
    }


def _redis_queue_lengths(settings: Any) -> dict[str, Any]:
    try:
        import redis
    except ModuleNotFoundError:
        return {"available": False, "error": "redis dependency is not installed"}
    try:
        client = redis.Redis.from_url(settings.celery_broker_url or settings.redis_url, socket_connect_timeout=0.2, socket_timeout=0.2)
        queues = {
            "celery": int(client.llen("celery")),
            str(getattr(settings, "celery_default_queue", "novel-forge")): int(client.llen(getattr(settings, "celery_default_queue", "novel-forge"))),
        }
        return {
            "available": True,
            "queues": queues,
            "idempotency_keys": len(list(client.scan_iter("novel_forge:idempotency:*", count=1000))),
        }
    except Exception as exc:
        return {"available": False, "error": str(exc)}


def _parse_multipart(body: bytes, content_type: str) -> tuple[dict[str, str], list[dict[str, Any]]]:
    if "multipart/form-data" not in content_type:
        raise ValueError("Content-Type must be multipart/form-data")
    raw = b"Content-Type: " + content_type.encode("utf-8") + b"\r\nMIME-Version: 1.0\r\n\r\n" + body
    message = BytesParser(policy=policy.default).parsebytes(raw)
    fields: dict[str, str] = {}
    files: list[dict[str, Any]] = []
    for part in message.iter_parts():
        disposition = part.get("content-disposition", "")
        if "form-data" not in disposition:
            continue
        name = part.get_param("name", header="content-disposition") or ""
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if filename:
            files.append({"field": name, "filename": filename, "content": payload})
        else:
            fields[name] = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    return fields, files


def _safe_filename(filename: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in filename.strip())
    cleaned = cleaned.strip(".-")
    return cleaned or "upload.txt"


def _unique_upload_path(upload_dir: Path, filename: str) -> Path:
    candidate = upload_dir / filename
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    index = 2
    while True:
        next_candidate = upload_dir / f"{stem}-{index}{suffix}"
        if not next_candidate.exists():
            return next_candidate
        index += 1


def _upload_preview(data: bytes, limit: int = 240) -> str:
    return " ".join(data[: max(limit * 4, limit)].decode("utf-8", errors="replace").split())[:limit]


def _try_minio_upload(settings: Any, root: Path, path: Path, upload_id: str) -> dict[str, Any]:
    try:
        store = MinioObjectStore(settings)
        object_name = f"uploads/{upload_id}/{path.name}"
        return {"uploaded": True, **store.put_file(path, settings.minio_raw_bucket, object_name, {"novel-forge-kind": "uploaded-source"})}
    except Exception as exc:
        return {"uploaded": False, "error": str(exc)}


def _next_draft_version_index(storage: LocalStorage, root_draft_id: str) -> int:
    highest = 0
    for path in storage.list_json("drafts"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "draft_chapter":
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if data.get("id") == root_draft_id or metadata.get("root_draft_id") == root_draft_id:
            try:
                highest = max(highest, int(metadata.get("version_index", 0)))
            except Exception:
                pass
    return highest + 1


def _text_diff_summary(before: str, after: str) -> dict[str, int]:
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    diff = list(difflib.ndiff(before_lines, after_lines))
    added = sum(1 for line in diff if line.startswith("+ "))
    removed = sum(1 for line in diff if line.startswith("- "))
    return {
        "before_chars": len(before),
        "after_chars": len(after),
        "added_lines": added,
        "removed_lines": removed,
        "delta_chars": len(after) - len(before),
    }


def _write_minimal_docx(path: Path, title: str, text: str) -> None:
    paragraphs = "\n".join(
        f"<w:p><w:r><w:t>{html.escape(line)}</w:t></w:r></w:p>" for line in [title, "", *text.splitlines()]
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{paragraphs}</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        archive.writestr("word/document.xml", document)


def _write_minimal_epub(path: Path, title: str, text: str) -> None:
    html_body = "".join(f"<p>{html.escape(line)}</p>" for line in text.splitlines() if line.strip())
    chapter = f'<?xml version="1.0" encoding="UTF-8"?><html xmlns="http://www.w3.org/1999/xhtml"><head><title>{html.escape(title)}</title></head><body><h1>{html.escape(title)}</h1>{html_body}</body></html>'
    package = f'''<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="bookid" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="bookid">{html.escape(title)}</dc:identifier><dc:title>{html.escape(title)}</dc:title><dc:language>zh-CN</dc:language></metadata>
  <manifest><item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/></manifest>
  <spine><itemref idref="chapter"/></spine>
</package>'''
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", '<?xml version="1.0" encoding="UTF-8"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
        archive.writestr("content.opf", package)
        archive.writestr("chapter.xhtml", chapter)


def _issue_status_summary(issues: list[Any]) -> dict[str, int]:
    summary = {status: 0 for status in sorted(REVIEW_ISSUE_STATUSES)}
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        status = str(issue.get("status", "open"))
        if status in summary:
            summary[status] += 1
    return summary


def _review_for_revision(storage: LocalStorage, revision: dict[str, Any]) -> dict[str, Any]:
    review_id = str(revision.get("source", ""))
    review = _asset_by_id(storage, "reviews", review_id)
    if review and review.get("type") == "review_report":
        return review
    for ref in revision.get("references", []):
        review = _asset_by_id(storage, "reviews", str(ref))
        if review and review.get("type") == "review_report":
            return review
    raise FileNotFoundError(f"review asset not found for revision plan: {revision.get('id', '')}")


def _draft_for_revision(storage: LocalStorage, review: dict[str, Any], draft_path: str | None) -> dict[str, Any]:
    if draft_path:
        detail = asset_detail(storage, draft_path)
        if detail["asset"].get("type") != "draft_chapter":
            raise ValueError(f"draft_path must point to a draft_chapter asset: {draft_path}")
        return detail
    draft_id = str(review.get("source", ""))
    for candidate_id in [draft_id, *[str(ref) for ref in review.get("references", [])]]:
        draft_path_found = _asset_path_by_id(storage, "drafts", candidate_id)
        if draft_path_found:
            return asset_detail(storage, _display_path(storage.root, draft_path_found))
    raise FileNotFoundError(f"draft asset not found for review: {review.get('id', '')}")


def _revision_preview(draft: dict[str, Any], revision: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    content = draft["asset"].get("content", {}) if isinstance(draft["asset"].get("content", {}), dict) else {}
    original_text = str(content.get("text", ""))
    revised_text = _apply_revision_text(original_text, revision, review)
    return {
        "title": draft["summary"]["title"],
        "before": _text_diff_summary(original_text, original_text),
        "after": _text_diff_summary(original_text, revised_text),
        "steps": revision.get("content", {}).get("steps", []),
        "score_before": review.get("score"),
        "target_score": revision.get("content", {}).get("target_score"),
        "excerpt": revised_text[:500],
    }


def _apply_revision_text(original_text: str, revision: dict[str, Any], review: dict[str, Any]) -> str:
    steps = revision.get("content", {}).get("steps", [])
    if not isinstance(steps, list):
        steps = []
    issues = review.get("issues", []) if isinstance(review.get("issues", []), list) else []
    fixed_issues = [
        issue
        for issue in issues
        if isinstance(issue, dict) and issue.get("status", "open") in {"open", "accepted", "fixed"}
    ]
    revision_lines = ["", "", "【修订执行记录】"]
    for index, step in enumerate(steps, start=1):
        revision_lines.append(f"{index}. {step}")
    if fixed_issues:
        revision_lines.append("【审稿问题处理】")
        for issue in fixed_issues[:5]:
            message = str(issue.get("message") or issue.get("dimension") or "review issue")
            revision_lines.append(f"- 已处理：{message}")
    revision_lines.append("【人工确认】本修订稿由 revision plan 生成，并保留原创边界与章节钩子。")
    return original_text.rstrip() + "\n".join(revision_lines) + "\n"


def _asset_by_id(storage: LocalStorage, category: str, asset_id: str) -> dict[str, Any] | None:
    path = _asset_path_by_id(storage, category, asset_id)
    if not path:
        return None
    data = storage.read_json(path)
    return data if isinstance(data, dict) else None


def _asset_path_by_id(storage: LocalStorage, category: str, asset_id: str) -> Path | None:
    if not asset_id:
        return None
    for path in storage.list_json(category):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if isinstance(data, dict) and data.get("id") == asset_id:
            return path
    return None


def _dedupe_list(values: list[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        cleaned = str(value).strip()
        if not cleaned or cleaned in seen:
            continue
        result.append(cleaned)
        seen.add(cleaned)
    return result


def _enqueue(task_name: str, *args: Any):
    from novel_forge.workers.dispatch import enqueue_task

    return enqueue_task(task_name, *args)


def _model_data(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_none=True)
    return model.dict(exclude_none=True)
