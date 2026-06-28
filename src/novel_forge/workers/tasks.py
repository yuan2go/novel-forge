from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from novel_forge.api.product import enqueue_batch_deconstruct, process_batch_item_step, retry_task
from novel_forge.modules.agent_runs import AgentExecutionContext
from novel_forge.modules.chapter_production_bus import recover_chapter_production, resume_chapter_production
from novel_forge.modules.workflow_nodes import run_workflow_scheduler_loop
from novel_forge.storage.local import LocalStorage
from novel_forge.workflows import pipeline

try:
    from novel_forge.workers.celery_app import create_celery_app

    celery_app = create_celery_app()
except RuntimeError:  # pragma: no cover - dependency-gated fallback
    celery_app = None


def _task(*task_args: Any, **task_kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        if celery_app is None:
            return func
        return celery_app.task(*task_args, **task_kwargs)(func)

    return decorator


@_task(name="novel_forge.run_pipeline")
def run_pipeline_task(root: str, sample: bool = False) -> dict[str, str]:
    with _worker_context(root, "run-pipeline") as run:
        run.guard("run_worker_task")
        path = pipeline.run_pipeline(root, sample=sample)
        run.succeed()
        return {"path": _display_path(root, path)}


@_task(name="novel_forge.run_step")
def run_step_task(root: str, step: str, input_path: str | None = None) -> dict[str, str]:
    with _worker_context(root, f"run-step:{step}", input_assets=[input_path] if input_path else []) as run:
        run.guard("run_worker_task")
        path = _run_step(root, step, input_path)
        run.succeed()
        return {"path": _display_path(root, path)}


@_task(name="novel_forge.ingest_many")
def ingest_many_task(
    root: str,
    input_path: str,
    title: str | None = None,
    rights_authorization: str = "unknown",
    license_name: str = "",
    copyright_note: str = "",
    source_url: str = "",
    allow_downstream_generation: bool = False,
) -> dict[str, list[str]]:
    with _worker_context(root, "ingest-many", input_assets=[input_path]) as run:
        run.guard("run_worker_task")
        paths = pipeline.ingest_many(
            root,
            input_path,
            title=title,
            rights_authorization=rights_authorization,
            license_name=license_name,
            copyright_note=copyright_note,
            source_url=source_url,
            allow_downstream_generation=allow_downstream_generation,
        )
        run.succeed()
        return {"paths": [_display_path(root, path) for path in paths]}


@_task(name="novel_forge.batch_deconstruct")
def batch_deconstruct_task(
    root: str,
    input_path: str,
    title: str | None = None,
    rights_authorization: str = "unknown",
    license_name: str = "",
    copyright_note: str = "",
    source_url: str = "",
    allow_downstream_generation: bool = False,
    workspace_path: str | None = None,
    analysis_mode: str = "auto",
) -> dict:
    with _worker_context(root, "batch-deconstruct", input_assets=[input_path], workspace_path=workspace_path) as run:
        run.guard("run_worker_task")
        result = enqueue_batch_deconstruct(
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
        run.succeed()
        return result


@_task(name="novel_forge.batch_item_step")
def batch_item_step_task(
    root: str,
    item_path: str,
    step: str,
    workspace_path: str | None = None,
) -> dict:
    with _worker_context(root, f"batch-item-step:{step}", input_assets=[item_path], workspace_path=workspace_path) as run:
        run.guard("run_worker_task")
        result = process_batch_item_step(root, item_path, step=step, workspace_path=workspace_path, enqueue_next=True)
        run.succeed()
        return result


@_task(name="novel_forge.retry_product_task")
def retry_product_task(
    root: str,
    status_path: str | None = None,
    run_id: str | None = None,
    step: str | None = None,
    workspace_path: str | None = None,
) -> dict:
    with _worker_context(root, "retry-product-task", input_assets=[status_path] if status_path else [], workspace_path=workspace_path) as run:
        run.guard("run_worker_task")
        result = retry_task(root, status_path=status_path, run_id=run_id, step=step, workspace_path=workspace_path)
        run.succeed()
        return result


@_task(name="novel_forge.chapter_production_run")
def chapter_production_run_task(
    root: str,
    run_path: str,
    from_step: str | None = None,
    run_to: str | None = None,
    force: bool = False,
    recover_failed: bool = False,
    clear_pause: bool = True,
    request_id: str = "",
) -> dict:
    operation = "chapter-production-recover" if recover_failed else "chapter-production-resume"
    with _worker_context(root, operation, input_assets=[run_path]) as run:
        run.guard("run_worker_task")
        storage = LocalStorage(root)
        if recover_failed:
            result = recover_chapter_production(storage, run_path, run_to=run_to, force=True)
        else:
            result = resume_chapter_production(storage, run_path, from_step=from_step, run_to=run_to, force=force, clear_pause=clear_pause)
        run.succeed()
        return result


@_task(name="novel_forge.workflow_scheduler_loop")
def workflow_scheduler_loop_task(
    root: str,
    project_id: str | None = None,
    limit: int = 20,
    max_nodes_per_resume: int = 5,
    iterations: int = 1,
    interval_seconds: float = 0.0,
    apply_invalidation: bool = True,
    stop_when_idle: bool = True,
    request_id: str = "",
) -> dict:
    with _worker_context(root, "workflow-scheduler-loop", workspace_path=None) as run:
        run.guard("run_worker_task")
        result = run_workflow_scheduler_loop(
            LocalStorage(root),
            project_id=project_id,
            limit=limit,
            max_nodes_per_resume=max_nodes_per_resume,
            iterations=iterations,
            interval_seconds=interval_seconds,
            apply_invalidation=apply_invalidation,
            stop_when_idle=stop_when_idle,
            run_id=request_id or None,
        )
        run.succeed(output_assets=result.get("task_status_paths", []), token_used=int(result.get("candidate_count", 0) or 0))
        return result


@_task(name="novel_forge.postgres_sync")
def postgres_sync_task(root: str) -> dict:
    with _worker_context(root, "postgres-sync") as run:
        run.guard("run_worker_task")
        result = pipeline.postgres_sync(root)
        run.succeed()
        return result


@_task(name="novel_forge.qdrant_index")
def qdrant_index_task(root: str) -> dict:
    with _worker_context(root, "qdrant-index") as run:
        run.guard("run_worker_task")
        result = pipeline.qdrant_index(root)
        run.succeed()
        return result


@_task(name="novel_forge.minio_sync")
def minio_sync_task(root: str, categories: list[str] | None = None) -> dict:
    with _worker_context(root, "minio-sync") as run:
        run.guard("run_worker_task")
        result = pipeline.minio_sync(root, categories=categories)
        run.succeed()
        return result


def _worker_context(
    root: str,
    operation: str,
    *,
    input_assets: list[str | None] | None = None,
    workspace_path: str | None = None,
) -> AgentExecutionContext:
    return AgentExecutionContext(
        LocalStorage(root),
        agent_key="engineering",
        operation=f"worker:{operation}",
        input_assets=[item for item in input_assets or [] if item],
        output_types=[],
        workspace_path=workspace_path,
        sla_seconds=1800,
    )


def _run_step(root: str, step: str, input_path: str | None) -> Path:
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


def _display_path(root: str, path: Path) -> str:
    try:
        return str(path.relative_to(Path(root).resolve()))
    except ValueError:
        return str(path)
