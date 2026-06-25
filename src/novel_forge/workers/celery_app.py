from __future__ import annotations

from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.workers.runtime import NovelForgeTask


def create_celery_app(settings: IndustrialSettings | None = None):
    try:
        from celery import Celery
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency-gated path
        raise RuntimeError("Celery support requires optional dependencies: celery[redis] and redis") from exc

    app_settings = settings or IndustrialSettings.from_env()
    app = Celery(
        "novel_forge",
        broker=app_settings.celery_broker_url,
        backend=app_settings.celery_result_backend,
        include=["novel_forge.workers.tasks"],
    )
    app.Task = NovelForgeTask
    app.conf.update(
        task_track_started=True,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        task_default_queue=app_settings.celery_default_queue,
        task_routes={"novel_forge.*": {"queue": app_settings.celery_default_queue}},
        task_soft_time_limit=app_settings.celery_task_soft_time_limit,
        task_time_limit=app_settings.celery_task_time_limit,
        result_expires=60 * 60 * 24,
        timezone="UTC",
        novel_forge_root=str(app_settings.root),
    )
    return app
