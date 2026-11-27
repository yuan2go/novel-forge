from __future__ import annotations

import io
import unittest

from novel_forge.modules.command_kernel.external_effect_adapters import (
    MinioObjectStoreExternalEffectAdapter,
)


class _Missing(RuntimeError):
    code = "NoSuchKey"


class _Object:
    def __init__(self, content: bytes, metadata: dict[str, str]) -> None:
        self.content = content
        self.size = len(content)
        self.metadata = {
            f"x-amz-meta-{key}": value for key, value in metadata.items()
        }


class _Minio:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], _Object] = {}
        self.buckets: set[str] = set()
        self.put_count = 0

    def stat_object(self, bucket: str, key: str) -> _Object:
        try:
            return self.objects[(bucket, key)]
        except KeyError as exc:
            raise _Missing() from exc

    def bucket_exists(self, bucket: str) -> bool:
        return bucket in self.buckets

    def make_bucket(self, bucket: str) -> None:
        self.buckets.add(bucket)

    def put_object(
        self,
        bucket: str,
        key: str,
        body: io.BytesIO,
        *,
        length: int,
        content_type: str,
        metadata: dict[str, str],
    ) -> None:
        del content_type
        content = body.read()
        if len(content) != length:
            raise AssertionError("length mismatch")
        self.objects[(bucket, key)] = _Object(content, metadata)
        self.put_count += 1


class MinioExternalEffectAdapterTests(unittest.TestCase):
    def test_hash_size_and_idempotent_replay_are_enforced(self) -> None:
        client = _Minio()
        adapter = MinioObjectStoreExternalEffectAdapter(
            client, bucket="authority-artifacts"
        )
        payload = {
            "object_key": "projects/p1/output.json",
            "content": "evidence",
            "expected_hash": "sha256:ee8250fb76e094b34b471f13a73dbbe51d1ae142e9df59d7c0d31ec20f0a0a8e",
            "expected_size": 8,
        }
        first = adapter.execute(
            stable_idempotency_key="effect-1",
            capability="object_store.put",
            request_payload=payload,
        )
        replay = adapter.execute(
            stable_idempotency_key="effect-1",
            capability="object_store.put",
            request_payload=payload,
        )
        self.assertEqual(first.outcome, "success")
        self.assertFalse(first.evidence["replayed"])
        self.assertTrue(replay.evidence["replayed"])
        self.assertEqual(client.put_count, 1)

        conflict = adapter.execute(
            stable_idempotency_key="effect-1",
            capability="object_store.put",
            request_payload={
                "object_key": payload["object_key"],
                "content": "different",
            },
        )
        self.assertEqual(conflict.outcome, "final_failure")
        self.assertEqual(conflict.evidence["error"], "object_identity_conflict")

    def test_unsafe_key_and_identity_mismatch_fail_before_write(self) -> None:
        client = _Minio()
        adapter = MinioObjectStoreExternalEffectAdapter(client, bucket="artifacts")
        with self.assertRaisesRegex(Exception, "unsafe object key"):
            adapter.execute(
                stable_idempotency_key="effect-unsafe",
                capability="object_store.put",
                request_payload={"object_key": "../escape", "content": "x"},
            )
        mismatch = adapter.execute(
            stable_idempotency_key="effect-mismatch",
            capability="object_store.put",
            request_payload={
                "object_key": "safe/key",
                "content": "x",
                "expected_size": 2,
            },
        )
        self.assertEqual(mismatch.outcome, "final_failure")
        self.assertEqual(client.put_count, 0)


if __name__ == "__main__":
    unittest.main()
