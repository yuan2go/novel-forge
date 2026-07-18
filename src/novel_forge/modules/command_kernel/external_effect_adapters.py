"""External-effect adapters. Calls are intentionally made outside database transactions."""
from __future__ import annotations

import base64
import hashlib
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
    """Typed adapter failure that records whether provider submission may have started."""

    def __init__(self, message: str, *, request_sent: bool) -> None:
        super().__init__(message)
        self.request_sent = request_sent


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
        content = destination.read_bytes()
        return ProviderResult(
            "success",
            f"local-query:{stable_idempotency_key}",
            {
                "object_key": object_key,
                "actual_hash": "sha256:" + hashlib.sha256(content).hexdigest(),
                "actual_size": len(content),
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
