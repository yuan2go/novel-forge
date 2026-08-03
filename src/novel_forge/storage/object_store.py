from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.infrastructure.settings import IndustrialSettings


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
