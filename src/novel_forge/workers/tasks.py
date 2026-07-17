"""Compatibility imports for the legacy LocalStorage worker surface.

New production work must enter the PostgreSQL Command Kernel.  The existing
Celery/LocalStorage workers remain available only as an explicit legacy
boundary while callers migrate; their implementation lives in
``legacy_tasks`` so this module cannot become a second rule source.
"""

from novel_forge.workers.legacy_tasks import (
    agent_scheduler_loop_task,
    batch_deconstruct_task,
    batch_item_step_task,
    celery_app,
    chapter_production_run_task,
    ingest_many_task,
    minio_sync_task,
    postgres_sync_task,
    qdrant_index_task,
    retry_product_task,
    run_pipeline_task,
    run_step_task,
    workflow_scheduler_loop_task,
)

__all__ = [
    "agent_scheduler_loop_task",
    "batch_deconstruct_task",
    "batch_item_step_task",
    "celery_app",
    "chapter_production_run_task",
    "ingest_many_task",
    "minio_sync_task",
    "postgres_sync_task",
    "qdrant_index_task",
    "retry_product_task",
    "run_pipeline_task",
    "run_step_task",
    "workflow_scheduler_loop_task",
]
