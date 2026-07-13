"""External-effect adapters. Calls are intentionally made outside database transactions."""
from __future__ import annotations

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


class ExternalEffectAdapter(Protocol):
    provider: str

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


class FakeDeterministicProvider:
    provider = "fake_deterministic_provider"

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


class LocalFileObjectStoreAdapter:
    provider = "local_file_object_store"

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
        content = str(request_payload.get("content") or "").encode("utf-8")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and destination.read_bytes() == content:
            replayed = True
        else:
            destination.write_bytes(content)
            replayed = False
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
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
