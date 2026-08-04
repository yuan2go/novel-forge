from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


def _env_bool(value: str | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_list(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())


@dataclass(frozen=True)
class IndustrialSettings:
    root: Path
    environment: str = "development"
    storage_authority: str = "postgresql"
    authority_runtime_profile: str = "full"
    legacy_write_enabled: bool = False
    silent_legacy_fallback_enabled: bool = False
    database_url: str = ""
    postgres_write_through: bool = False
    postgres_write_strict: bool = False
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    celery_default_queue: str = "novel-forge"
    celery_task_soft_time_limit: int = 30 * 60
    celery_task_time_limit: int = 35 * 60
    celery_idempotency_ttl_seconds: int = 24 * 60 * 60
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    qdrant_collection: str = "novel_forge_assets"
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "novel_forge"
    minio_secret_key: str = "novel_forge_secret"
    minio_secure: bool = False
    minio_raw_bucket: str = "novel-forge-raw"
    minio_artifact_bucket: str = "novel-forge-artifacts"
    minio_export_bucket: str = "novel-forge-exports"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_cors_origins: tuple[str, ...] = ("http://localhost:3000",)
    neo4j_uri: str = ""
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""
    neo4j_enabled: bool = False

    def __post_init__(self) -> None:
        environment = self.environment.strip().lower()
        authority = self.storage_authority.strip().lower()
        runtime_profile = self.authority_runtime_profile.strip().lower()
        if environment not in {"development", "test", "production"}:
            raise ValueError("environment must be development, test, or production")
        if authority not in {"legacy_local", "postgresql"}:
            raise ValueError("storage_authority must be legacy_local or postgresql")
        if runtime_profile not in {"full", "track-b-minimal"}:
            raise ValueError("authority_runtime_profile must be full or track-b-minimal")
        if environment == "production" and authority != "postgresql":
            raise ValueError("production storage authority must be postgresql")
        if authority == "postgresql" and (
            self.legacy_write_enabled
            or self.silent_legacy_fallback_enabled
            or self.postgres_write_through
        ):
            raise ValueError(
                "PostgreSQL authority forbids Legacy writes, dual write, and silent fallback"
            )
        if runtime_profile == "track-b-minimal" and authority != "postgresql":
            raise ValueError("track-b-minimal runtime requires postgresql authority")
        if runtime_profile == "track-b-minimal" and (
            self.legacy_write_enabled or self.silent_legacy_fallback_enabled
        ):
            raise ValueError(
                "track-b-minimal runtime forbids legacy writes and silent fallback"
            )
        object.__setattr__(self, "environment", environment)
        object.__setattr__(self, "storage_authority", authority)
        object.__setattr__(self, "authority_runtime_profile", runtime_profile)

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        root: str | Path | None = None,
    ) -> "IndustrialSettings":
        values = env or os.environ
        cwd = Path.cwd().resolve()
        initial_cwd_file_values = _read_dotenv(cwd / ".env") if root is None else {}
        initial_root = Path(root or _get(values, initial_cwd_file_values, "NOVEL_FORGE_ROOT", ".")).resolve()
        cwd_file_values = _read_dotenv(cwd / ".env") if root is None or _path_is_within(initial_root, cwd) else {}
        root_file_values = _read_dotenv(initial_root / ".env")
        file_values = {**cwd_file_values, **root_file_values}
        resolved_root = Path(root or _get(values, file_values, "NOVEL_FORGE_ROOT", ".")).resolve()
        if resolved_root != initial_root:
            cwd_file_values = _read_dotenv(cwd / ".env") if root is None or _path_is_within(resolved_root, cwd) else {}
            root_file_values = _read_dotenv(resolved_root / ".env")
            file_values = {**cwd_file_values, **root_file_values}
        redis_url = _get(values, file_values, "NOVEL_FORGE_REDIS_URL", _get(values, file_values, "REDIS_URL", "redis://localhost:6379/0"))
        environment = _get(values, file_values, "NOVEL_FORGE_ENVIRONMENT", "development").strip().lower()
        storage_authority = _get(
            values,
            file_values,
            "NOVEL_FORGE_STORAGE_AUTHORITY",
            "postgresql",
        )
        return cls(
            root=resolved_root,
            environment=environment,
            storage_authority=storage_authority,
            authority_runtime_profile=_get(
                values,
                file_values,
                "NOVEL_FORGE_AUTHORITY_RUNTIME_PROFILE",
                "full",
            ),
            legacy_write_enabled=_env_bool(
                _get(values, file_values, "NOVEL_FORGE_LEGACY_WRITE_ENABLED", "false")
            ),
            silent_legacy_fallback_enabled=_env_bool(
                _get(
                    values,
                    file_values,
                    "NOVEL_FORGE_SILENT_LEGACY_FALLBACK_ENABLED",
                    "false",
                )
            ),
            database_url=_get(values, file_values, "NOVEL_FORGE_DATABASE_URL", _get(values, file_values, "DATABASE_URL", "")),
            postgres_write_through=_env_bool(
                _get(values, file_values, "NOVEL_FORGE_POSTGRES_WRITE_THROUGH", "false"),
                False,
            ),
            postgres_write_strict=_env_bool(
                _get(values, file_values, "NOVEL_FORGE_POSTGRES_WRITE_STRICT", ""),
                False,
            ),
            redis_url=redis_url,
            celery_broker_url=_get(values, file_values, "NOVEL_FORGE_CELERY_BROKER_URL", redis_url),
            celery_result_backend=_get(
                values,
                file_values,
                "NOVEL_FORGE_CELERY_RESULT_BACKEND",
                _get(values, file_values, "CELERY_RESULT_BACKEND", "redis://localhost:6379/1"),
            ),
            celery_default_queue=_get(values, file_values, "NOVEL_FORGE_CELERY_DEFAULT_QUEUE", "novel-forge"),
            celery_task_soft_time_limit=int(_get(values, file_values, "NOVEL_FORGE_CELERY_TASK_SOFT_TIME_LIMIT", str(30 * 60))),
            celery_task_time_limit=int(_get(values, file_values, "NOVEL_FORGE_CELERY_TASK_TIME_LIMIT", str(35 * 60))),
            celery_idempotency_ttl_seconds=int(_get(values, file_values, "NOVEL_FORGE_CELERY_IDEMPOTENCY_TTL_SECONDS", str(24 * 60 * 60))),
            qdrant_url=_get(values, file_values, "NOVEL_FORGE_QDRANT_URL", "http://localhost:6333"),
            qdrant_api_key=_get(values, file_values, "NOVEL_FORGE_QDRANT_API_KEY", ""),
            qdrant_collection=_get(values, file_values, "NOVEL_FORGE_QDRANT_COLLECTION", "novel_forge_assets"),
            minio_endpoint=_get(values, file_values, "NOVEL_FORGE_MINIO_ENDPOINT", "localhost:9000"),
            minio_access_key=_get(values, file_values, "NOVEL_FORGE_MINIO_ACCESS_KEY", "novel_forge"),
            minio_secret_key=_get(values, file_values, "NOVEL_FORGE_MINIO_SECRET_KEY", "novel_forge_secret"),
            minio_secure=_env_bool(_get(values, file_values, "NOVEL_FORGE_MINIO_SECURE", ""), False),
            minio_raw_bucket=_get(values, file_values, "NOVEL_FORGE_MINIO_RAW_BUCKET", "novel-forge-raw"),
            minio_artifact_bucket=_get(values, file_values, "NOVEL_FORGE_MINIO_ARTIFACT_BUCKET", "novel-forge-artifacts"),
            minio_export_bucket=_get(values, file_values, "NOVEL_FORGE_MINIO_EXPORT_BUCKET", "novel-forge-exports"),
            api_host=_get(values, file_values, "NOVEL_FORGE_API_HOST", "127.0.0.1"),
            api_port=int(_get(values, file_values, "NOVEL_FORGE_API_PORT", "8000")),
            api_cors_origins=_env_list(_get(values, file_values, "NOVEL_FORGE_API_CORS_ORIGINS", "")) or ("http://localhost:3000",),
            neo4j_uri=_get(values, file_values, "NOVEL_FORGE_NEO4J_URI", ""),
            neo4j_user=_get(values, file_values, "NOVEL_FORGE_NEO4J_USER", "neo4j"),
            neo4j_password=_get(values, file_values, "NOVEL_FORGE_NEO4J_PASSWORD", ""),
            neo4j_enabled=_env_bool(_get(values, file_values, "NOVEL_FORGE_ENABLE_NEO4J", ""), False),
        )

    def configured_services(self) -> dict[str, bool]:
        return {
            "postgresql": bool(self.database_url),
            "redis": bool(self.redis_url),
            "celery": bool(self.celery_broker_url and self.celery_result_backend),
            "qdrant": bool(self.qdrant_url),
            "minio": bool(self.minio_endpoint and self.minio_access_key and self.minio_secret_key),
            "neo4j": bool(self.neo4j_enabled and self.neo4j_uri and self.neo4j_password),
        }


def optional_dependency_status() -> dict[str, bool]:
    modules = {
        "fastapi": "fastapi",
        "uvicorn": "uvicorn",
        "psycopg": "psycopg",
        "celery": "celery",
        "redis": "redis",
        "qdrant_client": "qdrant_client",
        "minio": "minio",
        "neo4j": "neo4j",
    }
    return {name: importlib.util.find_spec(module) is not None for name, module in modules.items()}


def _get(env: Mapping[str, str], file_values: Mapping[str, str], key: str, default: str) -> str:
    return env.get(key, file_values.get(key, default))


def _path_is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _read_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key:
            values[key] = value
    return values
