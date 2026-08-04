from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import unittest
from unittest.mock import patch

from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.storage.object_store import MinioObjectStore


@dataclass
class _Result:
    version_id: str = "evidence-version-1"


class _Client:
    def __init__(self) -> None:
        self.created: list[str] = []
        self.upload: dict = {}

    def bucket_exists(self, bucket: str) -> bool:
        return bucket in self.created

    def make_bucket(self, bucket: str) -> None:
        self.created.append(bucket)

    def put_object(self, bucket, object_key, body, **kwargs):
        self.upload = {
            "bucket": bucket,
            "object_key": object_key,
            "body": body.read(),
            **kwargs,
        }
        return _Result()


class D0ObjectStoreEvidenceTests(unittest.TestCase):
    def test_canonical_json_hash_retention_and_version_are_in_object_ref(self) -> None:
        client = _Client()
        settings = IndustrialSettings(root=".")
        payload = {"provider_request_id": "request-1", "usage": {"input": 7}}
        canonical = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        content_hash = "sha256:" + hashlib.sha256(canonical).hexdigest()
        with patch(
            "novel_forge.storage.object_store._minio_client",
            return_value=client,
        ):
            store = MinioObjectStore(settings)
            object_ref = store.put_json(
                object_key="d0/run-1/request.json", payload=payload
            )

        self.assertEqual(client.upload["body"], canonical)
        self.assertEqual(client.upload["content_type"], "application/json")
        self.assertEqual(
            client.upload["metadata"],
            {"content-hash": content_hash, "retention-class": "LONG_TERM"},
        )
        self.assertEqual(
            object_ref,
            "minio://novel-forge-artifacts/d0/run-1/request.json"
            f"?versionId=evidence-version-1#content_hash={content_hash}",
        )


if __name__ == "__main__":
    unittest.main()
