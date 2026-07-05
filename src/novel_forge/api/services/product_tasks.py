from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from novel_forge.core.ids import utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.storage.local import LocalStorage

TASK_CONTROL_RELATIVE_PATH = Path("data/indexes/task-control.json")
QUEUE_PRESSURE_RELATIVE_PATH = Path("data/indexes/queue-pressure.json")
DEFAULT_TASK_CONTROL = {"max_concurrent_batches": 1, "max_concurrent_steps": 1}

BatchListFunc = Callable[..., list[dict[str, Any]]]


def task_control_status(settings: Any, *, list_batch_items_func: BatchListFunc | None = None) -> dict[str, Any]:
    root = Path(settings.root).resolve()
    config = read_task_control(root)
    celery = celery_inspection(settings)
    storage = LocalStorage(root)
    trend = record_queue_pressure(root, celery)
    try:
        from novel_forge.modules.runtime_ledger import scheduler_lease_status

        scheduler = scheduler_lease_status(storage)
    except Exception as exc:
        scheduler = {"status": "error", "error": str(exc)}

    failed_batch_items: list[dict[str, Any]] = []
    waiting_handoffs: list[dict[str, Any]] = []
    if list_batch_items_func:
        failed_batch_items = list_batch_items_func(storage, status="failed", limit=25)
        waiting_handoffs = list_batch_items_func(storage, status="waiting_handoff", limit=25)

    return {
        "config": config,
        "celery": celery,
        "queue_trend": trend,
        "scheduler": scheduler,
        "dead_letters": {"count": len(task_dead_letter_rows(root, limit=1000))},
        "failed_batch_items": failed_batch_items,
        "waiting_handoffs": waiting_handoffs,
        "heartbeat": utc_now(),
    }


def update_task_control(root: str | Path, patch: dict[str, Any]) -> dict[str, Any]:
    config = read_task_control(root)
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


def read_task_control(root: str | Path) -> dict[str, int]:
    path = Path(root).resolve() / TASK_CONTROL_RELATIVE_PATH
    if not path.exists():
        return dict(DEFAULT_TASK_CONTROL)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_TASK_CONTROL)
    config = dict(DEFAULT_TASK_CONTROL)
    for key in config:
        try:
            value = int(data.get(key, config[key]))
        except (AttributeError, TypeError, ValueError):
            value = config[key]
        config[key] = max(1, value)
    return config


def record_queue_pressure(root: str | Path, celery: dict[str, Any], max_points: int = 120) -> list[dict[str, Any]]:
    path = Path(root).resolve() / QUEUE_PRESSURE_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except (OSError, json.JSONDecodeError):
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


def celery_app_or_error() -> Any:
    try:
        from novel_forge.workers.tasks import celery_app
    except Exception as exc:
        raise RuntimeError(f"Celery task import failed: {exc}") from exc
    if celery_app is None:
        raise RuntimeError("Celery is not installed or configured")
    return celery_app


def celery_inspection(settings: Any) -> dict[str, Any]:
    try:
        celery_app = celery_app_or_error()
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
            "queue_lengths": redis_queue_lengths(settings),
        }
    return {
        "available": True,
        "healthy": bool(ping),
        "error": "",
        "workers": ping,
        "active_count": sum(len(items) for items in active.values()),
        "reserved_count": sum(len(items) for items in reserved.values()),
        "scheduled_count": sum(len(items) for items in scheduled.values()),
        "queue_lengths": redis_queue_lengths(settings),
    }


def redis_queue_lengths(settings: Any) -> dict[str, Any]:
    try:
        import redis
    except ModuleNotFoundError:
        return {"available": False, "error": "redis dependency is not installed"}
    try:
        broker_url = str(getattr(settings, "celery_broker_url", "") or getattr(settings, "redis_url", ""))
        client = redis.Redis.from_url(broker_url, socket_connect_timeout=0.2, socket_timeout=0.2)
        default_queue = str(getattr(settings, "celery_default_queue", "novel-forge"))
        queues = {
            "celery": int(client.llen("celery")),
            default_queue: int(client.llen(default_queue)),
        }
        return {
            "available": True,
            "queues": queues,
            "idempotency_keys": len(list(client.scan_iter("novel_forge:idempotency:*", count=1000))),
        }
    except Exception as exc:
        return {"available": False, "error": str(exc)}
