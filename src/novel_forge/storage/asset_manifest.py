from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from novel_forge.core.constants import DATA_DIRS
from novel_forge.storage.local import LocalStorage

MANIFEST_RELATIVE_PATH = Path("data/indexes/asset-manifest.sqlite")


def asset_manifest_path(storage: LocalStorage) -> Path:
    return storage.root / MANIFEST_RELATIVE_PATH


def rebuild_asset_manifest(storage: LocalStorage) -> Path:
    storage.ensure_layout()
    path = asset_manifest_path(storage)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE IF EXISTS assets")
        connection.execute(
            """
            CREATE TABLE assets (
                path TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                id TEXT,
                type TEXT,
                title TEXT,
                source TEXT,
                tags TEXT,
                version TEXT,
                created_at TEXT,
                updated_at TEXT,
                content_hash TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO assets (
                path, category, id, type, title, source, tags, version,
                created_at, updated_at, content_hash, size_bytes, mtime_ns
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            list(_asset_rows(storage)),
        )
        connection.execute("CREATE INDEX idx_assets_category ON assets(category)")
        connection.execute("CREATE INDEX idx_assets_type ON assets(type)")
        connection.execute("CREATE INDEX idx_assets_source ON assets(source)")
        connection.commit()
    return path


def manifest_counts(storage: LocalStorage) -> dict[str, int]:
    path = asset_manifest_path(storage)
    if not path.exists():
        rebuild_asset_manifest(storage)
    with sqlite3.connect(path) as connection:
        rows = connection.execute("SELECT category, COUNT(*) FROM assets GROUP BY category").fetchall()
    return {str(category): int(count) for category, count in rows}


def _asset_rows(storage: LocalStorage):
    for category in DATA_DIRS:
        for path in storage.list_json(category):
            try:
                data = storage.read_json(path)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            stat = path.stat()
            yield (
                str(path.relative_to(storage.root)),
                category,
                str(data.get("id", "")),
                str(data.get("type", "")),
                str(data.get("title") or data.get("name") or ""),
                str(data.get("source", "")),
                json.dumps(data.get("tags", []), ensure_ascii=False, sort_keys=True),
                str(data.get("version", "")),
                str(data.get("created_at", "")),
                str(data.get("updated_at", "")),
                _content_hash(data),
                stat.st_size,
                stat.st_mtime_ns,
            )


def _content_hash(data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
