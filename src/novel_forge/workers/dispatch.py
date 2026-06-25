from __future__ import annotations

import hashlib
import json
from typing import Any

from novel_forge.infrastructure.settings import IndustrialSettings


def enqueue_task(
    task_name: str,
    *args: Any,
    settings: IndustrialSettings | None = None,
    task_kwargs: dict[str, Any] | None = None,
):
    try:
        from novel_forge.workers import tasks
    except Exception as exc:
        raise RuntimeError(f"Celery task import failed: {exc}") from exc
    celery_app = getattr(tasks, "celery_app", None)
    if celery_app is None:
        raise RuntimeError("Celery is not installed or configured")
    task = getattr(tasks, task_name, None)
    if task is None:
        task = celery_app.tasks.get(task_name)
    if task is None:
        raise RuntimeError(f"Celery task is not registered: {task_name}")
    app_settings = settings or IndustrialSettings.from_env(root=args[0] if args else None)
    call_kwargs = task_kwargs or {}
    idempotency_key = _idempotency_key(task_name, args, call_kwargs)
    existing_id = _existing_task_id(app_settings, idempotency_key)
    if existing_id:
        return celery_app.AsyncResult(existing_id)
    result = task.apply_async(
        args=args,
        kwargs=call_kwargs,
        queue=app_settings.celery_default_queue,
        headers={"idempotency_key": idempotency_key},
        soft_time_limit=app_settings.celery_task_soft_time_limit,
        time_limit=app_settings.celery_task_time_limit,
    )
    _remember_task_id(app_settings, idempotency_key, result.id)
    return result


def _idempotency_key(task_name: str, args: tuple[Any, ...], kwargs: dict[str, Any] | None = None) -> str:
    payload = json.dumps({"task": task_name, "args": args, "kwargs": kwargs or {}}, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"novel_forge:idempotency:{digest}"


def _redis_client(settings: IndustrialSettings):
    try:
        import redis
    except ModuleNotFoundError:
        return None
    try:
        return redis.Redis.from_url(settings.redis_url, socket_connect_timeout=0.2, socket_timeout=0.2)
    except Exception:
        return None


def _existing_task_id(settings: IndustrialSettings, key: str) -> str:
    client = _redis_client(settings)
    if client is None:
        return ""
    try:
        value = client.get(key)
    except Exception:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def _remember_task_id(settings: IndustrialSettings, key: str, task_id: str) -> None:
    client = _redis_client(settings)
    if client is None:
        return
    try:
        client.set(key, task_id, ex=settings.celery_idempotency_ttl_seconds, nx=True)
    except Exception:
        return
