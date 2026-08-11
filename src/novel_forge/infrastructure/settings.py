from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .environment import RuntimeEnvironment


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
    environment: RuntimeEnvironment | str = RuntimeEnvironment.DEVELOPMENT
    storage_authority: str = "postgresql"
    authority_runtime_profile: str = "full"
    database_url: str = ""
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "novel_forge"
    minio_secret_key: str = "novel_forge_secret"
    minio_secure: bool = False
    minio_raw_bucket: str = "novel-forge-raw"
    minio_artifact_bucket: str = "novel-forge-artifacts"
    minio_export_bucket: str = "novel-forge-exports"
    mkaos_fixture_activation_enabled: bool = False
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_cors_origins: tuple[str, ...] = ("http://localhost:3000",)

    def __post_init__(self) -> None:
        environment = RuntimeEnvironment.parse(self.environment)
        authority = self.storage_authority.strip().lower()
        runtime_profile = self.authority_runtime_profile.strip().lower()
        if authority != "postgresql":
            raise ValueError("storage_authority must be postgresql")
        if runtime_profile not in {"full", "track-b-minimal"}:
            raise ValueError("authority_runtime_profile must be full or track-b-minimal")
        if environment.controlled and self.mkaos_fixture_activation_enabled:
            raise ValueError(
                "controlled runtime forbids fixture MKAOS activation"
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
        values = os.environ if env is None else env
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
            database_url=_get(values, file_values, "NOVEL_FORGE_DATABASE_URL", _get(values, file_values, "DATABASE_URL", "")),
            minio_endpoint=_get(values, file_values, "NOVEL_FORGE_MINIO_ENDPOINT", "localhost:9000"),
            minio_access_key=_get(values, file_values, "NOVEL_FORGE_MINIO_ACCESS_KEY", "novel_forge"),
            minio_secret_key=_get(values, file_values, "NOVEL_FORGE_MINIO_SECRET_KEY", "novel_forge_secret"),
            minio_secure=_env_bool(_get(values, file_values, "NOVEL_FORGE_MINIO_SECURE", ""), False),
            minio_raw_bucket=_get(values, file_values, "NOVEL_FORGE_MINIO_RAW_BUCKET", "novel-forge-raw"),
            minio_artifact_bucket=_get(values, file_values, "NOVEL_FORGE_MINIO_ARTIFACT_BUCKET", "novel-forge-artifacts"),
            minio_export_bucket=_get(values, file_values, "NOVEL_FORGE_MINIO_EXPORT_BUCKET", "novel-forge-exports"),
            mkaos_fixture_activation_enabled=_env_bool(
                _get(
                    values,
                    file_values,
                    "NOVEL_FORGE_MKAOS_ALLOW_FIXTURE_ACTIVATION",
                    "false",
                )
            ),
            api_host=_get(values, file_values, "NOVEL_FORGE_API_HOST", "127.0.0.1"),
            api_port=int(_get(values, file_values, "NOVEL_FORGE_API_PORT", "8000")),
            api_cors_origins=_env_list(_get(values, file_values, "NOVEL_FORGE_API_CORS_ORIGINS", "")) or ("http://localhost:3000",),
        )

    def configured_services(self) -> dict[str, bool]:
        return {
            "postgresql": bool(self.database_url),
            "minio": bool(self.minio_endpoint and self.minio_access_key and self.minio_secret_key),
        }


def optional_dependency_status() -> dict[str, bool]:
    modules = {
        "fastapi": "fastapi",
        "uvicorn": "uvicorn",
        "psycopg": "psycopg",
        "minio": "minio",
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
