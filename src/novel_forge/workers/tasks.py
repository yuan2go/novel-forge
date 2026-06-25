from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from novel_forge.api.product import enqueue_batch_deconstruct, process_batch_item_step, retry_task
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
    path = pipeline.run_pipeline(root, sample=sample)
    return {"path": _display_path(root, path)}


@_task(name="novel_forge.run_step")
def run_step_task(root: str, step: str, input_path: str | None = None) -> dict[str, str]:
    path = _run_step(root, step, input_path)
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
    return enqueue_batch_deconstruct(
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


@_task(name="novel_forge.batch_item_step")
def batch_item_step_task(
    root: str,
    item_path: str,
    step: str,
    workspace_path: str | None = None,
) -> dict:
    return process_batch_item_step(root, item_path, step=step, workspace_path=workspace_path, enqueue_next=True)


@_task(name="novel_forge.retry_product_task")
def retry_product_task(
    root: str,
    status_path: str | None = None,
    run_id: str | None = None,
    step: str | None = None,
    workspace_path: str | None = None,
) -> dict:
    return retry_task(root, status_path=status_path, run_id=run_id, step=step, workspace_path=workspace_path)


@_task(name="novel_forge.postgres_sync")
def postgres_sync_task(root: str) -> dict:
    return pipeline.postgres_sync(root)


@_task(name="novel_forge.qdrant_index")
def qdrant_index_task(root: str) -> dict:
    return pipeline.qdrant_index(root)


@_task(name="novel_forge.minio_sync")
def minio_sync_task(root: str, categories: list[str] | None = None) -> dict:
    return pipeline.minio_sync(root, categories=categories)


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
