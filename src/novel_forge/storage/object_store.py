from __future__ import annotations

from pathlib import Path
from io import BytesIO
import hashlib
import json
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

    def put_json(self, *, object_key: str, payload: dict[str, Any]) -> str:
        self.ensure_buckets()
        body = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        content_hash = "sha256:" + hashlib.sha256(body).hexdigest()
        result = self.client.put_object(
            self.settings.minio_artifact_bucket,
            object_key,
            BytesIO(body),
            length=len(body),
            content_type="application/json",
            metadata={"content-hash": content_hash, "retention-class": "LONG_TERM"},
        )
        version = str(getattr(result, "version_id", "") or "")
        suffix = f"?versionId={version}" if version else ""
        return (
            f"minio://{self.settings.minio_artifact_bucket}/{object_key}{suffix}"
            f"#content_hash={content_hash}"
        )

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
