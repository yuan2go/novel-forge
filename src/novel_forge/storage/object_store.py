from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from novel_forge.core.constants import DATA_DIRS
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.storage.local import LocalStorage


@dataclass(frozen=True)
class ObjectSyncResult:
    bucket: str
    uploaded: int

    def to_dict(self) -> dict[str, Any]:
        return {"bucket": self.bucket, "uploaded": self.uploaded}


class MinioObjectStore:
    def __init__(self, settings: IndustrialSettings) -> None:
        self.settings = settings
        self.client = _minio_client(settings)

    def ensure_buckets(self) -> None:
        for bucket in [
            self.settings.minio_raw_bucket,
            self.settings.minio_artifact_bucket,
            self.settings.minio_export_bucket,
        ]:
            if not self.client.bucket_exists(bucket):
                self.client.make_bucket(bucket)

    def put_file(
        self,
        path: Path,
        bucket: str,
        object_name: str,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        self.ensure_buckets()
        result = self.client.fput_object(bucket, object_name, str(path), metadata=metadata)
        return {
            "bucket": bucket,
            "object_name": object_name,
            "etag": getattr(result, "etag", ""),
            "version_id": getattr(result, "version_id", ""),
        }

    def sync_assets(self, storage: LocalStorage, categories: list[str] | None = None) -> ObjectSyncResult:
        selected_categories = categories or list(DATA_DIRS)
        uploaded = 0
        self.ensure_buckets()
        for category in selected_categories:
            if category not in DATA_DIRS:
                raise ValueError(f"unknown data category: {category}")
            for path in storage.list_json(category):
                object_name = object_name_for_path(storage, path)
                self.client.fput_object(
                    self.settings.minio_artifact_bucket,
                    object_name,
                    str(path),
                    metadata={"category": category, "novel-forge-kind": "json-asset"},
                )
                uploaded += 1
        return ObjectSyncResult(self.settings.minio_artifact_bucket, uploaded)


def sync_minio_assets(
    storage: LocalStorage,
    settings: IndustrialSettings,
    categories: list[str] | None = None,
) -> dict[str, Any]:
    return MinioObjectStore(settings).sync_assets(storage, categories).to_dict()


def object_name_for_path(storage: LocalStorage, path: Path) -> str:
    relative = path.relative_to(storage.root)
    return "/".join(relative.parts)


def _minio_client(settings: IndustrialSettings):
    try:
        from minio import Minio
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency-gated path
        raise RuntimeError("MinIO support requires the optional dependency: minio") from exc
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
