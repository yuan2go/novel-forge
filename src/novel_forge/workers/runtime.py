from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.schemas import TaskDeadLetter
from novel_forge.storage.local import LocalStorage
from novel_forge.storage.postgres import PostgresAssetStore

try:  # pragma: no cover - exercised only when Celery is installed.
    from celery import Task
except ModuleNotFoundError:  # pragma: no cover - dependency-gated fallback.
    Task = object  # type: ignore[misc,assignment]


class NovelForgeTask(Task):  # type: ignore[misc]
    abstract = True
    acks_late = True
    reject_on_worker_lost = True

    def on_failure(self, exc: BaseException, task_id: str, args: tuple[Any, ...], kwargs: dict[str, Any], einfo: Any) -> None:
        root = _root_from_task_args(args)
        write_dead_letter(
            root=root,
            task_name=str(getattr(self, "name", "")),
            task_id=task_id,
            args=args,
            kwargs=kwargs,
            exc=exc,
            traceback=str(einfo),
            request_headers=getattr(getattr(self, "request", None), "headers", {}) or {},
        )

    def on_success(self, retval: Any, task_id: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        root = _root_from_task_args(args)
        sync_postgres_after_task(root, retval)


def write_dead_letter(
    root: str | Path,
    task_name: str,
    task_id: str,
    args: tuple[Any, ...] | list[Any],
    kwargs: dict[str, Any],
    exc: BaseException,
    traceback: str = "",
    request_headers: dict[str, Any] | None = None,
) -> Path:
    storage = LocalStorage(root)
    storage.ensure_layout()
    headers = request_headers or {}
    dead_letter = TaskDeadLetter(
        title=f"Dead letter: {task_name or task_id}",
        source=task_id,
        tags=["task-dead-letter", "failed", task_name],
        content={
            "task_name": task_name,
            "task_id": task_id,
            "status": "failed",
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "traceback": traceback,
            "payload": {
                "args": _json_safe(args),
                "kwargs": _json_safe(kwargs),
                "headers": _json_safe(headers),
                "idempotency_key": str(headers.get("idempotency_key", "")),
            },
        },
        metadata={"recorded_at": _safe_utc_now()},
        references=[],
    )
    path = storage.write_asset_auto(dead_letter)
    sync_postgres_after_task(root, {"path": str(path)})
    return path


def list_dead_letters(root: str | Path, limit: int = 100) -> list[dict[str, Any]]:
    storage = LocalStorage(root)
    storage.ensure_layout()
    rows = []
    for path in reversed(storage.list_json("runs")):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "task_dead_letter":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        payload = content.get("payload", {}) if isinstance(content.get("payload", {}), dict) else {}
        rows.append(
            {
                "path": _display_path(storage.root, path),
                "id": data.get("id", ""),
                "task_name": content.get("task_name", ""),
                "task_id": content.get("task_id", ""),
                "error_type": content.get("error_type", ""),
                "error_message": content.get("error_message", ""),
                "args": payload.get("args", []),
                "kwargs": payload.get("kwargs", {}),
                "recorded_at": data.get("metadata", {}).get("recorded_at", data.get("updated_at", "")),
            }
        )
        if len(rows) >= limit:
            return rows
    return rows


def sync_postgres_after_task(root: str | Path, retval: Any) -> None:
    settings = IndustrialSettings.from_env(root=root)
    if not settings.database_url:
        return
    storage = LocalStorage(settings.root)
    store = PostgresAssetStore.from_settings(settings)
    try:
        paths = _extract_paths(retval)
        if paths:
            for path in paths:
                store.sync_asset(storage, path)
        else:
            store.sync_from_local(storage)
    except Exception:
        return


def _extract_paths(value: Any) -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key.endswith("path") and isinstance(child, str):
                paths.append(child)
            else:
                paths.extend(_extract_paths(child))
    elif isinstance(value, list):
        for child in value:
            paths.extend(_extract_paths(child))
    elif isinstance(value, str) and value.startswith("data/"):
        paths.append(value)
    return paths


def _root_from_task_args(args: tuple[Any, ...] | list[Any]) -> str | Path:
    if args:
        return Path(str(args[0])).resolve()
    return IndustrialSettings.from_env().root


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except TypeError:
        if isinstance(value, tuple):
            return [_json_safe(item) for item in value]
        if isinstance(value, list):
            return [_json_safe(item) for item in value]
        if isinstance(value, dict):
            return {str(key): _json_safe(item) for key, item in value.items()}
        return str(value)


def _display_path(root: str | Path, path: Path) -> str:
    try:
        return str(path.relative_to(Path(root).resolve()))
    except ValueError:
        return str(path)


def _safe_utc_now() -> str:
    from novel_forge.core.ids import utc_now

    return utc_now()
