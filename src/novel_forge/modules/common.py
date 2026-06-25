from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from novel_forge.storage.local import LocalStorage


def resolve_path(root: Path, path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else root / candidate


def read_previous(storage: LocalStorage, category: str, input_path: str | None) -> Any:
    path = resolve_path(storage.root, input_path) if input_path else storage.latest(category)
    return storage.read_asset(path)


def run_metadata(
    operation: str,
    input_asset: Any,
    provider: str = "local-rules",
    model: str = "local-rules",
    prompt_version: str = "prompt-v1",
    schema_version: str = "0.1.0",
) -> dict[str, Any]:
    payload = input_asset.to_dict() if hasattr(input_asset, "to_dict") else {}
    content = payload.get("content", {}) if isinstance(payload, dict) else {}
    return {
        "operation": operation,
        "provider": provider,
        "model": model,
        "prompt_version": prompt_version,
        "schema_version": schema_version,
        "input_snapshot": {
            "asset_id": getattr(input_asset, "id", ""),
            "asset_type": getattr(input_asset, "type", ""),
            "title": getattr(input_asset, "title", ""),
            "content_hash": hashlib.sha256(
                json.dumps(content, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest(),
        },
    }
