"""Legacy LocalStorage-to-MinIO import compatibility.

This module is intentionally outside the Authority production roots. It is a
bounded migration/read-compatibility adapter and must not be used as a formal
writer after a slice cuts over to PostgreSQL/Object Store Authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from novel_forge.core.constants import DATA_DIRS
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.storage.local import LocalStorage
from novel_forge.storage.object_store import MinioObjectStore


@dataclass(frozen=True)
class ObjectSyncResult:
    bucket: str
    uploaded: int

    def to_dict(self) -> dict[str, Any]:
        return {"bucket": self.bucket, "uploaded": self.uploaded}


def sync_minio_assets(
    storage: LocalStorage,
    settings: IndustrialSettings,
    categories: list[str] | None = None,
) -> dict[str, Any]:
    selected_categories = categories or list(DATA_DIRS)
    uploaded = 0
    object_store = MinioObjectStore(settings)
    object_store.ensure_buckets()
    for category in selected_categories:
        if category not in DATA_DIRS:
            raise ValueError(f"unknown data category: {category}")
        for path in storage.list_json(category):
            object_store.client.fput_object(
                settings.minio_artifact_bucket,
                object_name_for_path(storage, path),
                str(path),
                metadata={"category": category, "novel-forge-kind": "json-asset"},
            )
            uploaded += 1
    return ObjectSyncResult(settings.minio_artifact_bucket, uploaded).to_dict()


def object_name_for_path(storage: LocalStorage, path: Path) -> str:
    relative = path.relative_to(storage.root)
    return "/".join(relative.parts)


__all__ = ["ObjectSyncResult", "object_name_for_path", "sync_minio_assets"]
