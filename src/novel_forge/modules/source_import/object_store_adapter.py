"""INVARIANT: In-memory payload injection for governed Blob ExternalEffects.

The ExternalEffect intent stores only the immutable object identity. Source bytes
are reloaded from the frozen Git object on retry and are never serialized into
PostgreSQL request JSON.
"""
from __future__ import annotations

import base64
import hashlib
from typing import Any

from novel_forge.modules.command_kernel.external_effect_adapters import ProviderResult


class SourceImportObjectStoreAdapter:
    production_execution_gateway_backed = True

    def __init__(self, delegate: Any, *, content: bytes) -> None:
        self.delegate = delegate
        self.content = bytes(content)
        self.provider = str(delegate.provider)
        self.reconciliation_mode = str(delegate.reconciliation_mode)
        self.capability_profile = delegate.capability_profile

    def execute(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
    ) -> ProviderResult:
        digest = "sha256:" + hashlib.sha256(self.content).hexdigest()
        if (
            digest != request_payload.get("expected_hash")
            or len(self.content) != request_payload.get("expected_size")
        ):
            return ProviderResult(
                "final_failure",
                f"source-import:{stable_idempotency_key}",
                {"error": "reloaded_source_identity_mismatch"},
            )
        return self.delegate.execute(
            stable_idempotency_key=stable_idempotency_key,
            capability=capability,
            request_payload={
                **request_payload,
                "content_base64": base64.b64encode(self.content).decode("ascii"),
            },
        )

    def query(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
    ) -> ProviderResult:
        return self.delegate.query(
            stable_idempotency_key=stable_idempotency_key,
            capability=capability,
            request_payload=request_payload,
        )

    def cancel(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
        provider_request_id: str,
    ) -> ProviderResult:
        return self.delegate.cancel(
            stable_idempotency_key=stable_idempotency_key,
            capability=capability,
            request_payload=request_payload,
            provider_request_id=provider_request_id,
        )


__all__ = ["SourceImportObjectStoreAdapter"]
