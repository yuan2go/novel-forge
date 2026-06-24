from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.storage.local import LocalStorage


def resolve_path(root: Path, path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else root / candidate


def read_previous(storage: LocalStorage, category: str, input_path: str | None) -> Any:
    path = resolve_path(storage.root, input_path) if input_path else storage.latest(category)
    return storage.read_asset(path)
