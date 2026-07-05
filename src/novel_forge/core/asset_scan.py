from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from novel_forge.core.exception_policy import require_recoverable_asset_scan_error
from novel_forge.storage.local import LocalStorage


def read_json_for_scan(storage: LocalStorage, path: str | Path, *, context: str) -> dict[str, Any]:
    try:
        data = storage.read_json(path)
    except Exception as exc:
        require_recoverable_asset_scan_error(exc, context=context)
        return {}
    return data if isinstance(data, dict) else {}


def iter_json_objects(
    storage: LocalStorage,
    category: str,
    *,
    reverse: bool = False,
    limit: int | None = None,
    context: str,
) -> Iterator[tuple[Path, dict[str, Any]]]:
    paths = list(storage.list_json(category))
    if reverse:
        paths.reverse()
    yielded = 0
    for path in paths:
        data = read_json_for_scan(storage, path, context=context)
        if not data:
            continue
        yield path, data
        yielded += 1
        if limit is not None and yielded >= limit:
            break
