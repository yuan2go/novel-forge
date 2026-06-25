from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from novel_forge.core.constants import DATA_DIRS
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.storage.local import LocalStorage

POSTGRES_SCHEMA_VERSION = "20260625_0001_initial_industrial_schema"

POSTGRES_SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS nf_schema_migrations (
        migration_id TEXT PRIMARY KEY,
        applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS nf_assets (
        path TEXT PRIMARY KEY,
        category TEXT NOT NULL,
        asset_id TEXT NOT NULL,
        asset_type TEXT NOT NULL,
        title TEXT NOT NULL,
        source TEXT NOT NULL,
        project_id TEXT NOT NULL DEFAULT '',
        workspace_path TEXT NOT NULL DEFAULT '',
        tags TEXT[] NOT NULL DEFAULT '{}',
        version TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        payload JSONB NOT NULL,
        size_bytes BIGINT NOT NULL,
        mtime_ns BIGINT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        indexed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS nf_asset_versions (
        version_id BIGSERIAL PRIMARY KEY,
        path TEXT NOT NULL,
        asset_id TEXT NOT NULL,
        asset_type TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        payload JSONB NOT NULL,
        recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (path, content_hash)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS nf_task_statuses (
        status_asset_id TEXT PRIMARY KEY,
        path TEXT NOT NULL DEFAULT '',
        run_id TEXT NOT NULL,
        step TEXT NOT NULL,
        status TEXT NOT NULL,
        input_paths TEXT[] NOT NULL DEFAULT '{}',
        output_paths TEXT[] NOT NULL DEFAULT '{}',
        error_message TEXT NOT NULL DEFAULT '',
        payload JSONB NOT NULL,
        recorded_at TEXT NOT NULL,
        indexed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "ALTER TABLE nf_task_statuses ADD COLUMN IF NOT EXISTS path TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE nf_assets ADD COLUMN IF NOT EXISTS project_id TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE nf_assets ADD COLUMN IF NOT EXISTS workspace_path TEXT NOT NULL DEFAULT ''",
    """
    CREATE TABLE IF NOT EXISTS nf_projects (
        project_id TEXT PRIMARY KEY,
        workspace_asset_id TEXT NOT NULL,
        workspace_path TEXT NOT NULL UNIQUE,
        title TEXT NOT NULL,
        series_title TEXT NOT NULL DEFAULT '',
        book_number INTEGER,
        status TEXT NOT NULL DEFAULT 'active',
        config JSONB NOT NULL,
        payload JSONB NOT NULL,
        updated_at TEXT NOT NULL,
        indexed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_nf_assets_category ON nf_assets(category)",
    "CREATE INDEX IF NOT EXISTS idx_nf_assets_type ON nf_assets(asset_type)",
    "CREATE INDEX IF NOT EXISTS idx_nf_assets_project ON nf_assets(project_id, workspace_path)",
    "CREATE INDEX IF NOT EXISTS idx_nf_assets_tags ON nf_assets USING GIN(tags)",
    "CREATE INDEX IF NOT EXISTS idx_nf_asset_versions_asset_id ON nf_asset_versions(asset_id)",
    "CREATE INDEX IF NOT EXISTS idx_nf_task_statuses_run_step ON nf_task_statuses(run_id, step)",
    "CREATE INDEX IF NOT EXISTS idx_nf_task_statuses_status ON nf_task_statuses(status)",
    "CREATE INDEX IF NOT EXISTS idx_nf_projects_status ON nf_projects(status)",
    "CREATE INDEX IF NOT EXISTS idx_nf_projects_series ON nf_projects(series_title, book_number)",
    f"INSERT INTO nf_schema_migrations (migration_id) VALUES ('{POSTGRES_SCHEMA_VERSION}') ON CONFLICT (migration_id) DO NOTHING",
]


@dataclass(frozen=True)
class PostgresSyncResult:
    assets: int
    versions: int
    task_statuses: int
    projects: int

    def to_dict(self) -> dict[str, int]:
        return {
            "assets": self.assets,
            "versions": self.versions,
            "task_statuses": self.task_statuses,
            "projects": self.projects,
        }


class PostgresAssetStore:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("database_url must not be empty")
        self.database_url = database_url

    @classmethod
    def from_settings(cls, settings: IndustrialSettings) -> "PostgresAssetStore":
        return cls(settings.database_url)

    def initialize(self) -> None:
        with _connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                for statement in POSTGRES_SCHEMA_STATEMENTS:
                    cursor.execute(statement)

    def migration_status(self) -> dict[str, Any]:
        self.initialize()
        with _connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT migration_id, applied_at FROM nf_schema_migrations ORDER BY applied_at ASC")
                rows = cursor.fetchall()
        applied = [{"migration_id": row[0], "applied_at": str(row[1])} for row in rows]
        applied_ids = {row["migration_id"] for row in applied}
        return {
            "current": POSTGRES_SCHEMA_VERSION,
            "applied": applied,
            "ok": POSTGRES_SCHEMA_VERSION in applied_ids,
            "missing": [] if POSTGRES_SCHEMA_VERSION in applied_ids else [POSTGRES_SCHEMA_VERSION],
        }

    def sync_from_local(self, storage: LocalStorage) -> PostgresSyncResult:
        self.initialize()
        asset_count = 0
        version_count = 0
        task_status_count = 0
        project_count = 0
        with _connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                for category in DATA_DIRS:
                    for path in storage.list_json(category):
                        data = storage.read_json(path)
                        if not isinstance(data, dict):
                            continue
                        record = _asset_record(storage, category, path, data)
                        cursor.execute(_UPSERT_ASSET_SQL, record)
                        asset_count += 1
                        cursor.execute(_INSERT_VERSION_SQL, _version_record(record))
                        if cursor.rowcount:
                            version_count += 1
                        if data.get("type") == "task_status":
                            cursor.execute(_UPSERT_TASK_STATUS_SQL, _task_status_record(storage, path, data))
                            task_status_count += 1
                        if data.get("type") == "project_workspace_state":
                            cursor.execute(_UPSERT_PROJECT_SQL, _project_record(storage, path, data))
                            project_count += 1
        return PostgresSyncResult(asset_count, version_count, task_status_count, project_count)

    def sync_asset(self, storage: LocalStorage, path: str | Path) -> bool:
        self.initialize()
        resolved = storage.root / path if not Path(path).is_absolute() else Path(path)
        if not resolved.exists() or not resolved.is_file():
            return False
        category = _category_for_path(storage, resolved)
        if not category:
            return False
        data = storage.read_json(resolved)
        if not isinstance(data, dict):
            return False
        record = _asset_record(storage, category, resolved, data)
        with _connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(_UPSERT_ASSET_SQL, record)
                cursor.execute(_INSERT_VERSION_SQL, _version_record(record))
                if data.get("type") == "task_status":
                    cursor.execute(_UPSERT_TASK_STATUS_SQL, _task_status_record(storage, resolved, data))
                if data.get("type") == "project_workspace_state":
                    cursor.execute(_UPSERT_PROJECT_SQL, _project_record(storage, resolved, data))
        return True

    def list_assets(
        self,
        category: str | None = None,
        asset_type: str | None = None,
        project_id: str | None = None,
        tags: list[str] | None = None,
        keyword: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if limit < 1:
            raise ValueError("limit must be greater than zero")
        clauses: list[str] = []
        params: list[Any] = []
        if category:
            clauses.append("category = %s")
            params.append(category)
        if asset_type:
            clauses.append("asset_type = %s")
            params.append(asset_type)
        if project_id:
            clauses.append("project_id = %s")
            params.append(project_id)
        if tags:
            clauses.append("tags @> %s")
            params.append([str(tag) for tag in tags])
        if keyword:
            clauses.append("(title ILIKE %s OR source ILIKE %s OR payload::text ILIKE %s)")
            like = f"%{keyword}%"
            params.extend([like, like, like])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        sql = f"""
            SELECT path, category, asset_id, asset_type, title, source, project_id, workspace_path,
                   tags, version, content_hash, indexed_at, payload
            FROM nf_assets
            {where}
            ORDER BY indexed_at DESC, path ASC
            LIMIT %s
        """
        with _connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                rows = cursor.fetchall()
        return [
            {
                "path": row[0],
                "category": row[1],
                "id": row[2],
                "type": row[3],
                "title": row[4],
                "source": row[5],
                "project_id": row[6],
                "workspace_path": row[7],
                "tags": list(row[8] or []),
                "version": row[9],
                "content_hash": row[10],
                "indexed_at": str(row[11]),
                "payload": row[12],
            }
            for row in rows
        ]

    def list_projects(self, include_deleted: bool = False, limit: int = 500) -> list[dict[str, Any]]:
        clauses = [] if include_deleted else ["status <> 'deleted'"]
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with _connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT project_id, workspace_asset_id, workspace_path, title, series_title,
                           book_number, status, config, payload, updated_at, indexed_at
                    FROM nf_projects
                    {where}
                    ORDER BY indexed_at DESC, workspace_path ASC
                    LIMIT %s
                    """,
                    [limit],
                )
                rows = cursor.fetchall()
        return [
            {
                "project_id": row[0],
                "workspace_asset_id": row[1],
                "workspace_path": row[2],
                "path": row[2],
                "title": row[3],
                "series_title": row[4],
                "book_number": row[5],
                "status": row[6],
                "config": row[7],
                "payload": row[8],
                "updated_at": row[9],
                "indexed_at": str(row[10]),
            }
            for row in rows
        ]

    def list_task_statuses(
        self,
        status: str | None = None,
        step: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = %s")
            params.append(status)
        if step:
            clauses.append("step = %s")
            params.append(step)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with _connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT status_asset_id, path, run_id, step, status, input_paths, output_paths,
                           error_message, payload, recorded_at, indexed_at
                    FROM nf_task_statuses
                    {where}
                    ORDER BY indexed_at DESC, status_asset_id ASC
                    LIMIT %s
                    """,
                    params,
                )
                rows = cursor.fetchall()
        return [
            {
                "id": row[0],
                "path": row[1],
                "run_id": row[2],
                "step": row[3],
                "status": row[4],
                "input_paths": list(row[5] or []),
                "output_paths": list(row[6] or []),
                "error_message": row[7],
                "payload": row[8],
                "recorded_at": row[9],
                "indexed_at": str(row[10]),
            }
            for row in rows
        ]

    def list_payload_records(
        self,
        asset_type: str | None = None,
        category: str | None = None,
        project_id: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        rows = self.list_assets(category=category, asset_type=asset_type, project_id=project_id, limit=limit)
        return [
            {
                "path": row["path"],
                "category": row["category"],
                "payload": row["payload"],
                "indexed_at": row["indexed_at"],
            }
            for row in rows
        ]


def sync_postgres_from_local(storage: LocalStorage, settings: IndustrialSettings) -> dict[str, int]:
    return PostgresAssetStore.from_settings(settings).sync_from_local(storage).to_dict()


def postgres_available(settings: IndustrialSettings) -> bool:
    if not settings.database_url:
        return False
    try:
        store = PostgresAssetStore.from_settings(settings)
        with _connect(store.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        return True
    except Exception:
        return False


def _connect(database_url: str):
    try:
        import psycopg
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency-gated path
        raise RuntimeError("PostgreSQL support requires the optional dependency: psycopg[binary]") from exc
    return psycopg.connect(database_url, connect_timeout=1)


def _jsonb(value: Any) -> Any:
    try:
        from psycopg.types.json import Jsonb
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency-gated path
        raise RuntimeError("PostgreSQL support requires the optional dependency: psycopg[binary]") from exc
    return Jsonb(value)


def _asset_record(storage: LocalStorage, category: str, path: Path, data: dict[str, Any]) -> dict[str, Any]:
    stat = path.stat()
    title = str(data.get("title") or data.get("name") or "")
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    return {
        "path": str(path.relative_to(storage.root)),
        "category": category,
        "asset_id": str(data.get("id", "")),
        "asset_type": str(data.get("type", "")),
        "title": title,
        "source": str(data.get("source", "")),
        "project_id": str(metadata.get("project_id") or content.get("project_id") or ""),
        "workspace_path": str(metadata.get("workspace_path") or ""),
        "tags": [str(tag) for tag in data.get("tags", [])],
        "version": str(data.get("version", "")),
        "content_hash": _content_hash(data),
        "payload": _jsonb(data),
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "created_at": str(data.get("created_at", "")),
        "updated_at": str(data.get("updated_at", "")),
    }


def _category_for_path(storage: LocalStorage, path: Path) -> str:
    try:
        relative = path.relative_to(storage.data_root)
    except ValueError:
        return ""
    if len(relative.parts) < 2:
        return ""
    category = relative.parts[0]
    return category if category in DATA_DIRS else ""


def _version_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": record["path"],
        "asset_id": record["asset_id"],
        "asset_type": record["asset_type"],
        "content_hash": record["content_hash"],
        "payload": record["payload"],
    }


def _project_record(storage: LocalStorage, path: Path, data: dict[str, Any]) -> dict[str, Any]:
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    memory = content.get("memory", {}) if isinstance(content.get("memory", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    config = content.get("project_config", {}) if isinstance(content.get("project_config", {}), dict) else {}
    status = str(config.get("status") or metadata.get("project_status") or metadata.get("status") or "active")
    return {
        "project_id": str(content.get("project_id", data.get("id", ""))),
        "workspace_asset_id": str(data.get("id", "")),
        "workspace_path": str(path.relative_to(storage.root)),
        "title": str(data.get("title") or data.get("name") or ""),
        "series_title": str(memory.get("series_title", metadata.get("series_title", "")) or ""),
        "book_number": _int_or_none(memory.get("book_number", metadata.get("book_number"))),
        "status": status,
        "config": _jsonb(config),
        "payload": _jsonb(data),
        "updated_at": str(data.get("updated_at", "")),
    }


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except Exception:
        return None


def _task_status_record(storage: LocalStorage, path: Path, data: dict[str, Any]) -> dict[str, Any]:
    content = data.get("content", {})
    if not isinstance(content, dict):
        content = {}
    return {
        "status_asset_id": str(data.get("id", "")),
        "path": str(path.relative_to(storage.root)),
        "run_id": str(content.get("run_id", data.get("source", ""))),
        "step": str(content.get("step", "")),
        "status": str(content.get("status", "")),
        "input_paths": [str(item) for item in content.get("input_paths", [])],
        "output_paths": [str(item) for item in content.get("output_paths", [])],
        "error_message": str(content.get("error_message", "")),
        "payload": _jsonb(data),
        "recorded_at": str(data.get("metadata", {}).get("recorded_at", data.get("updated_at", ""))),
    }


def _content_hash(data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


_UPSERT_ASSET_SQL = """
    INSERT INTO nf_assets (
        path, category, asset_id, asset_type, title, source, project_id, workspace_path, tags, version,
        content_hash, payload, size_bytes, mtime_ns, created_at, updated_at, indexed_at
    )
    VALUES (
        %(path)s, %(category)s, %(asset_id)s, %(asset_type)s, %(title)s, %(source)s,
        %(project_id)s, %(workspace_path)s, %(tags)s, %(version)s, %(content_hash)s, %(payload)s, %(size_bytes)s,
        %(mtime_ns)s, %(created_at)s, %(updated_at)s, NOW()
    )
    ON CONFLICT (path) DO UPDATE SET
        category = EXCLUDED.category,
        asset_id = EXCLUDED.asset_id,
        asset_type = EXCLUDED.asset_type,
        title = EXCLUDED.title,
        source = EXCLUDED.source,
        project_id = EXCLUDED.project_id,
        workspace_path = EXCLUDED.workspace_path,
        tags = EXCLUDED.tags,
        version = EXCLUDED.version,
        content_hash = EXCLUDED.content_hash,
        payload = EXCLUDED.payload,
        size_bytes = EXCLUDED.size_bytes,
        mtime_ns = EXCLUDED.mtime_ns,
        created_at = EXCLUDED.created_at,
        updated_at = EXCLUDED.updated_at,
        indexed_at = NOW()
"""

_INSERT_VERSION_SQL = """
    INSERT INTO nf_asset_versions (path, asset_id, asset_type, content_hash, payload)
    VALUES (%(path)s, %(asset_id)s, %(asset_type)s, %(content_hash)s, %(payload)s)
    ON CONFLICT (path, content_hash) DO NOTHING
"""

_UPSERT_TASK_STATUS_SQL = """
    INSERT INTO nf_task_statuses (
        status_asset_id, path, run_id, step, status, input_paths, output_paths,
        error_message, payload, recorded_at, indexed_at
    )
    VALUES (
        %(status_asset_id)s, %(path)s, %(run_id)s, %(step)s, %(status)s,
        %(input_paths)s, %(output_paths)s, %(error_message)s, %(payload)s,
        %(recorded_at)s, NOW()
    )
    ON CONFLICT (status_asset_id) DO UPDATE SET
        path = EXCLUDED.path,
        run_id = EXCLUDED.run_id,
        step = EXCLUDED.step,
        status = EXCLUDED.status,
        input_paths = EXCLUDED.input_paths,
        output_paths = EXCLUDED.output_paths,
        error_message = EXCLUDED.error_message,
        payload = EXCLUDED.payload,
        recorded_at = EXCLUDED.recorded_at,
        indexed_at = NOW()
"""

_UPSERT_PROJECT_SQL = """
    INSERT INTO nf_projects (
        project_id, workspace_asset_id, workspace_path, title, series_title,
        book_number, status, config, payload, updated_at, indexed_at
    )
    VALUES (
        %(project_id)s, %(workspace_asset_id)s, %(workspace_path)s, %(title)s,
        %(series_title)s, %(book_number)s, %(status)s, %(config)s, %(payload)s,
        %(updated_at)s, NOW()
    )
    ON CONFLICT (project_id) DO UPDATE SET
        workspace_asset_id = EXCLUDED.workspace_asset_id,
        workspace_path = EXCLUDED.workspace_path,
        title = EXCLUDED.title,
        series_title = EXCLUDED.series_title,
        book_number = EXCLUDED.book_number,
        status = EXCLUDED.status,
        config = EXCLUDED.config,
        payload = EXCLUDED.payload,
        updated_at = EXCLUDED.updated_at,
        indexed_at = NOW()
"""
