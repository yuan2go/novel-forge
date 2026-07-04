from __future__ import annotations

from pathlib import Path
from typing import Any

from .manifest_builder import build_repository_manifest


def validate_repository_request(payload: dict[str, Any]) -> dict[str, Any]:
    source_uri = str(payload.get("source_uri") or payload.get("local_path") or "").strip()
    local_path = str(payload.get("local_path") or "").strip()
    if source_uri.startswith("https://github.com/") and not local_path:
        return {"ok": True, "requires_local_clone": True, "source_uri": source_uri}
    if not local_path:
        raise ValueError("local_path is required unless source_uri is a GitHub URL recorded for later local clone")
    if not Path(local_path).exists():
        raise FileNotFoundError(local_path)
    return {"ok": True, "requires_local_clone": False, "source_uri": source_uri or local_path, "local_path": local_path}


def scan_repository_path(local_path: str | Path, *, repository_id: str = "") -> dict[str, Any]:
    return build_repository_manifest(local_path, repository_id=repository_id)
