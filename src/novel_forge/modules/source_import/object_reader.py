from __future__ import annotations

import hashlib
from pathlib import Path
import re
from typing import Any


def _verify(content: bytes, *, expected_hash: str, expected_size: int) -> bytes:
    actual_hash = "sha256:" + hashlib.sha256(content).hexdigest()
    if actual_hash != expected_hash or len(content) != expected_size:
        raise ValueError("object-store read differs from the verified Blob identity")
    return content


class LocalObjectStoreReader:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def read(self, *, object_key: str, expected_hash: str, expected_size: int) -> bytes:
        destination = (self.root / object_key).resolve()
        if self.root not in destination.parents or not destination.is_file():
            raise ValueError("object-store key is unavailable or escapes its root")
        return _verify(
            destination.read_bytes(),
            expected_hash=expected_hash,
            expected_size=expected_size,
        )


class MinioObjectStoreReader:
    def __init__(self, client: Any, *, bucket: str) -> None:
        if not bucket:
            raise ValueError("MinIO object-store bucket is required")
        self.client = client
        self.bucket = bucket

    def read(self, *, object_key: str, expected_hash: str, expected_size: int) -> bytes:
        if (
            not object_key
            or object_key.startswith("/")
            or any(part in {"", ".", ".."} for part in object_key.split("/"))
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", expected_hash)
        ):
            raise ValueError("unsafe object-store read identity")
        response = self.client.get_object(self.bucket, object_key)
        try:
            content = response.read()
        finally:
            response.close()
            response.release_conn()
        return _verify(
            content,
            expected_hash=expected_hash,
            expected_size=expected_size,
        )


__all__ = ["LocalObjectStoreReader", "MinioObjectStoreReader"]
