"""INVARIANT: external calls occur outside database transactions."""

from __future__ import annotations

import base64
import hashlib
from io import BytesIO
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Protocol


@dataclass(frozen=True)
class ProviderResult:
    outcome: str
    provider_correlation_id: str
    evidence: dict[str, Any]
    provider_request_id: str = ""


class ExternalEffectAdapterError(RuntimeError):

    def __init__(
        self,
        message: str,
        *,
        request_sent: bool,
        failure_kind: str = "transport",
    ) -> None:
        super().__init__(message)
        self.request_sent = request_sent
        self.failure_kind = failure_kind


class ExternalEffectAdapter(Protocol):
    provider: str
    reconciliation_mode: str
    capability_profile: Any

    def execute(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
    ) -> ProviderResult: ...

    def query(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
    ) -> ProviderResult: ...

    def cancel(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
        provider_request_id: str,
    ) -> ProviderResult: ...


class FakeDeterministicProvider:
    provider = "fake_deterministic_provider"
    reconciliation_mode = "query"
    capability_profile = {
        "provider": provider, "control_level": "FIXTURE_CONTROLLED",
        "supports_request_timeout": True, "supports_provider_idempotency": True,
        "supports_query": True, "supports_cancel": True, "supports_callback": False,
        "supports_usage_receipt": False, "supports_cost_receipt": False,
        "reconciliation_mode": "query", "real_provider_validation_eligible": False,
        "contract_version": "provider-capability-v2",
    }

    def __init__(self, scenario: str) -> None:
        self.scenario = scenario
        self._effects: dict[str, dict[str, Any]] = {}
        self._lock = Lock()

    def execute(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
    ) -> ProviderResult:
        correlation = f"fake:{stable_idempotency_key}"
        with self._lock:
            if stable_idempotency_key in self._effects:
                evidence = self._effects[stable_idempotency_key]
                return ProviderResult("success", correlation, {**evidence, "replayed": True})
            if self.scenario == "success":
                evidence = {"capability": capability, "applied": True}
                if capability == "object_store.put":
                    evidence.update(
                        {
                            "object_key": request_payload.get("object_key"),
                            "actual_hash": request_payload.get("expected_hash"),
                            "actual_size": request_payload.get("expected_size"),
                        }
                    )
                self._effects[stable_idempotency_key] = evidence
                return ProviderResult("success", correlation, evidence)
            if self.scenario == "retryable_failure":
                return ProviderResult("retryable_failure", correlation, {"retryable": True})
            if self.scenario == "final_failure":
                return ProviderResult("final_failure", correlation, {"final": True})
            if self.scenario == "timeout_before":
                return ProviderResult(
                    "retryable_failure",
                    correlation,
                    {"timeout": True, "side_effect_started": False},
                )
            if self.scenario == "timeout_after":
                evidence = {"timeout": True, "side_effect_applied": True}
                self._effects[stable_idempotency_key] = evidence
                return ProviderResult("unknown", correlation, evidence)
            if self.scenario == "raise_before":
                raise ExternalEffectAdapterError(
                    "provider rejected the request before submission",
                    request_sent=False,
                )
            if self.scenario == "raise_after":
                raise ExternalEffectAdapterError(
                    "provider connection failed after submission",
                    request_sent=True,
                )
            return ProviderResult("unknown", correlation, {"provider_state": "unknown"})

    def query(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
    ) -> ProviderResult:
        correlation = f"fake-query:{stable_idempotency_key}"
        with self._lock:
            if stable_idempotency_key in self._effects:
                return ProviderResult(
                    "success",
                    correlation,
                    {**self._effects[stable_idempotency_key], "queried": True},
                )
        if self.scenario == "not_found":
            return ProviderResult("not_found", correlation, {"found": False})
        if self.scenario == "ambiguous":
            return ProviderResult("ambiguous", correlation, {"matches": "multiple"})
        if self.scenario == "final_failure":
            return ProviderResult("failed_final", correlation, {"provider_failed": True})
        return ProviderResult("ambiguous", correlation, {"provider_state": "unknown"})

    def cancel(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
        provider_request_id: str,
    ) -> ProviderResult:
        del capability, request_payload
        with self._lock:
            existed = self._effects.pop(stable_idempotency_key, None) is not None
        return ProviderResult(
            "cancelled",
            provider_request_id or f"fake-cancel:{stable_idempotency_key}",
            {"cancelled": True, "provider_effect_existed": existed},
        )


class LocalFileObjectStoreAdapter:
    provider = "local_file_object_store"
    reconciliation_mode = "query"
    capability_profile = {
        "provider": provider, "control_level": "FIXTURE_CONTROLLED",
        "supports_request_timeout": True, "supports_provider_idempotency": True,
        "supports_query": True, "supports_cancel": True, "supports_callback": False,
        "supports_usage_receipt": False, "supports_cost_receipt": False,
        "reconciliation_mode": "query", "real_provider_validation_eligible": False,
        "contract_version": "provider-capability-v2",
    }

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def execute(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
    ) -> ProviderResult:
        if capability != "object_store.put":
            return ProviderResult(
                "final_failure",
                f"local:{stable_idempotency_key}",
                {"error": "unsupported_capability"},
            )
        object_key = str(request_payload.get("object_key") or "")
        destination = (self.root / object_key).resolve()
        if self.root not in destination.parents:
            return ProviderResult(
                "final_failure",
                f"local:{stable_idempotency_key}",
                {"error": "object_key_escapes_root"},
            )
        encoded = str(request_payload.get("content_base64") or "")
        if encoded:
            try:
                content = base64.b64decode(encoded, validate=True)
            except ValueError:
                return ProviderResult(
                    "final_failure",
                    f"local:{stable_idempotency_key}",
                    {"error": "invalid_content_base64"},
                )
        elif "content" in request_payload:
            content = str(request_payload.get("content") or "").encode("utf-8")
        else:
            return ProviderResult(
                "final_failure",
                f"local:{stable_idempotency_key}",
                {"error": "content_bytes_missing"},
            )
        expected_hash = str(request_payload.get("expected_hash") or "")
        expected_size = request_payload.get("expected_size")
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
        if (expected_hash and digest != expected_hash) or (
            expected_size is not None and len(content) != expected_size
        ):
            return ProviderResult(
                "final_failure",
                f"local:{stable_idempotency_key}",
                {"error": "content_identity_mismatch"},
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and destination.read_bytes() == content:
            replayed = True
        else:
            destination.write_bytes(content)
            replayed = False
        return ProviderResult(
            "success",
            f"local:{stable_idempotency_key}",
            {
                "object_key": object_key,
                "actual_hash": digest,
                "actual_size": len(content),
                "replayed": replayed,
            },
        )

    def execute_stream(self, *, stable_idempotency_key: str, capability: str, request_payload: dict[str, Any], source_path: Path) -> ProviderResult:
        import os
        import tempfile
        if capability != "object_store.put":
            return ProviderResult("final_failure", stable_idempotency_key, {"error": "unsupported_capability"})
        object_key = str(request_payload.get("object_key") or "")
        destination = (self.root / object_key).resolve()
        if self.root not in destination.parents:
            return ProviderResult("final_failure", stable_idempotency_key, {"error": "object_key_escapes_root"})
        destination.parent.mkdir(parents=True, exist_ok=True)
        handle, name = tempfile.mkstemp(dir=destination.parent, prefix=".upload-")
        digest, size = hashlib.sha256(), 0
        try:
            with os.fdopen(handle, "wb") as output, source_path.open("rb") as source:
                while block := source.read(65536):
                    size += len(block)
                    if size > int(request_payload["expected_size"]):
                        raise ValueError("stream exceeds frozen object size")
                    digest.update(block)
                    output.write(block)
                output.flush()
                os.fsync(output.fileno())
            if "sha256:" + digest.hexdigest() != request_payload["expected_hash"] or size != int(request_payload["expected_size"]):
                raise ValueError("stream differs from frozen object identity")
            try:
                os.link(name, destination)
            except FileExistsError:
                pass
            result = self.query(stable_idempotency_key=stable_idempotency_key, capability=capability, request_payload=request_payload)
            if result.evidence.get("actual_hash") != request_payload["expected_hash"] or result.evidence.get("actual_size") != size:
                return ProviderResult("final_failure", stable_idempotency_key, {"error": "object_identity_conflict"})
            return result
        finally:
            Path(name).unlink(missing_ok=True)

    def query(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
    ) -> ProviderResult:
        object_key = str(request_payload.get("object_key") or "")
        destination = (self.root / object_key).resolve()
        if self.root not in destination.parents or not destination.exists():
            return ProviderResult(
                "not_found",
                f"local-query:{stable_idempotency_key}",
                {"object_key": object_key},
            )
        digest, size = hashlib.sha256(), 0
        with destination.open("rb") as source:
            while block := source.read(65536):
                digest.update(block)
                size += len(block)
        return ProviderResult(
            "success",
            f"local-query:{stable_idempotency_key}",
            {
                "object_key": object_key,
                "actual_hash": "sha256:" + digest.hexdigest(),
                "actual_size": size,
            },
        )

    def cancel(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
        provider_request_id: str,
    ) -> ProviderResult:
        del capability, request_payload
        return ProviderResult(
            "cancelled",
            provider_request_id or f"local-cancel:{stable_idempotency_key}",
            {
                "cancelled": False,
                "reason": "completed local object writes are immutable; compensation required",
            },
        )


class MinioObjectStoreExternalEffectAdapter:

    provider = "minio_object_store"
    reconciliation_mode = "query"
    capability_profile = {
        "provider": provider,
        "control_level": "SELF_HOSTED_CONTROLLED",
        "supports_request_timeout": True,
        "supports_provider_idempotency": True,
        "supports_query": True,
        "supports_cancel": False,
        "supports_callback": False,
        "supports_usage_receipt": False,
        "supports_cost_receipt": False,
        "reconciliation_mode": "query",
        "real_provider_validation_eligible": False,
        "contract_version": "provider-capability-v2",
    }

    def __init__(self, client: Any, *, bucket: str) -> None:
        if not bucket:
            raise ValueError("MinIO object-store bucket is required")
        self.client = client
        self.bucket = bucket

    def execute(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
    ) -> ProviderResult:
        if capability != "object_store.put":
            return ProviderResult(
                "final_failure",
                f"minio:{stable_idempotency_key}",
                {"error": "unsupported_capability"},
            )
        object_key, content, digest = self._payload(request_payload)
        expected_size = request_payload.get("expected_size")
        expected_hash = str(request_payload.get("expected_hash") or "")
        if (expected_hash and expected_hash != digest) or (
            expected_size is not None and int(expected_size) != len(content)
        ):
            return ProviderResult(
                "final_failure",
                f"minio:{stable_idempotency_key}",
                {"error": "content_identity_mismatch"},
            )
        existing = self._stat(object_key)
        if existing is not None:
            metadata = dict(getattr(existing, "metadata", {}) or {})
            existing_hash = str(
                metadata.get("x-amz-meta-content-hash")
                or metadata.get("content-hash")
                or ""
            )
            if existing_hash == digest and int(existing.size) == len(content):
                return self._result(
                    stable_idempotency_key, object_key, digest, len(content), True
                )
            return ProviderResult(
                "final_failure",
                f"minio:{stable_idempotency_key}",
                {"error": "object_identity_conflict", "object_key": object_key},
            )
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)
        self.client.put_object(
            self.bucket,
            object_key,
            BytesIO(content),
            length=len(content),
            content_type="application/octet-stream",
            metadata={
                "content-hash": digest,
                "stable-idempotency-key": stable_idempotency_key,
            },
        )
        return self._result(
            stable_idempotency_key, object_key, digest, len(content), False
        )

    def execute_stream(self, *, stable_idempotency_key: str, capability: str, request_payload: dict[str, Any], source_path: Path) -> ProviderResult:
        if capability != "object_store.put":
            return ProviderResult("final_failure", stable_idempotency_key, {"error": "unsupported_capability"})
        object_key = self._object_key(request_payload)
        digest, size = hashlib.sha256(), 0
        with source_path.open("rb") as source:
            while block := source.read(65536):
                digest.update(block)
                size += len(block)
        identity = "sha256:" + digest.hexdigest()
        if identity != request_payload["expected_hash"] or size != int(request_payload["expected_size"]):
            raise ValueError("stream differs from frozen object identity")
        previous = self.query(stable_idempotency_key=stable_idempotency_key, capability=capability, request_payload=request_payload)
        if previous.outcome == "success":
            if previous.evidence.get("actual_hash") != identity or previous.evidence.get("actual_size") != size:
                return ProviderResult("final_failure", stable_idempotency_key, {"error": "object_identity_conflict"})
            return previous
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)
        with source_path.open("rb") as source:
            self.client.put_object(self.bucket, object_key, source, length=size,
                content_type=str(request_payload.get("media_type") or "application/octet-stream"),
                metadata={"content-hash": identity, "stable-idempotency-key": stable_idempotency_key, "byte-verification": "required"})
        return self.query(stable_idempotency_key=stable_idempotency_key, capability=capability, request_payload=request_payload)

    def query(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
    ) -> ProviderResult:
        del capability
        object_key = self._object_key(request_payload)
        existing = self._stat(object_key)
        if existing is None:
            return ProviderResult(
                "not_found",
                f"minio-query:{stable_idempotency_key}",
                {"bucket": self.bucket, "object_key": object_key},
            )
        metadata = dict(getattr(existing, "metadata", {}) or {})
        digest = str(
            metadata.get("x-amz-meta-content-hash")
            or metadata.get("content-hash")
            or ""
        )
        if (metadata.get("x-amz-meta-byte-verification") or metadata.get("byte-verification")) == "required":
            response = self.client.get_object(self.bucket, object_key)
            verified, byte_size = hashlib.sha256(), 0
            try:
                while block := response.read(65536):
                    verified.update(block)
                    byte_size += len(block)
                    if byte_size > int(request_payload["expected_size"]):
                        break
            finally:
                response.close()
                response.release_conn()
            actual = "sha256:" + verified.hexdigest()
            if (actual != request_payload["expected_hash"] or byte_size != int(request_payload["expected_size"])
                    or actual != digest or byte_size != int(existing.size)):
                return ProviderResult("final_failure", stable_idempotency_key, {"error": "stored_stream_identity_conflict"})
        return self._result(
            stable_idempotency_key,
            object_key,
            digest,
            int(existing.size),
            True,
            query=True,
        )

    def cancel(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
        provider_request_id: str,
    ) -> ProviderResult:
        del capability, request_payload
        return ProviderResult(
            "cancelled",
            provider_request_id or f"minio-cancel:{stable_idempotency_key}",
            {
                "cancelled": False,
                "reason": "committed object versions are immutable; compensation required",
            },
        )

    def _payload(
        self, request_payload: dict[str, Any]
    ) -> tuple[str, bytes, str]:
        object_key = self._object_key(request_payload)
        encoded = str(request_payload.get("content_base64") or "")
        if encoded:
            try:
                content = base64.b64decode(encoded, validate=True)
            except ValueError as exc:
                raise ExternalEffectAdapterError(
                    "invalid object content_base64", request_sent=False
                ) from exc
        elif "content" in request_payload:
            content = str(request_payload.get("content") or "").encode("utf-8")
        else:
            raise ExternalEffectAdapterError(
                "object content bytes are missing", request_sent=False
            )
        return object_key, content, "sha256:" + hashlib.sha256(content).hexdigest()

    @staticmethod
    def _object_key(request_payload: dict[str, Any]) -> str:
        object_key = str(request_payload.get("object_key") or "").strip()
        if (
            not object_key
            or object_key.startswith("/")
            or any(part in {"", ".", ".."} for part in object_key.split("/"))
        ):
            raise ExternalEffectAdapterError(
                "unsafe object key", request_sent=False
            )
        return object_key

    def _stat(self, object_key: str) -> Any | None:
        try:
            return self.client.stat_object(self.bucket, object_key)
        except Exception as exc:
            code = str(getattr(exc, "code", "") or "")
            if code in {"NoSuchKey", "NoSuchObject", "NoSuchBucket"}:
                return None
            raise

    def _result(
        self,
        stable_idempotency_key: str,
        object_key: str,
        digest: str,
        size: int,
        replayed: bool,
        *,
        query: bool = False,
    ) -> ProviderResult:
        prefix = "minio-query" if query else "minio"
        return ProviderResult(
            "success",
            f"{prefix}:{stable_idempotency_key}",
            {
                "bucket": self.bucket,
                "object_key": object_key,
                "actual_hash": digest,
                "actual_size": size,
                "replayed": replayed,
            },
        )
