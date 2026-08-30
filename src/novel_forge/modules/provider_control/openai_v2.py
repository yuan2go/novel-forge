from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol

from .contracts import (
    ProviderCancellationRequest,
    ProviderCapabilityProfile,
    ProviderControlLevel,
    ProviderInvocationHandle,
    ProviderInvocationRequest,
    ProviderInvocationResult,
    ProviderQueryRequest,
    ProviderReceipt,
)


class OpenAITransportV2(Protocol):

    def execute(self, request: ProviderInvocationRequest) -> Mapping[str, Any]: ...
    def query(self, request: ProviderQueryRequest) -> Mapping[str, Any]: ...
    def cancel(self, request: ProviderCancellationRequest) -> Mapping[str, Any]: ...
    def verify_callback(
        self, body: bytes, headers: Mapping[str, str], *, secret: str
    ) -> ProviderReceipt: ...


class OpenAIProviderAdapterV2:

    provider = "openai"

    def __init__(
        self,
        transport: OpenAITransportV2,
        *,
        supports_query: bool,
        supports_cancel: bool,
        supports_callback: bool,
        supports_cost_receipt: bool,
        provider_idempotency_supported: bool,
        real_provider_validation_eligible: bool = True,
    ) -> None:
        self.transport = transport
        reconciliation_mode = (
            "query" if supports_query else "callback" if supports_callback else "unsupported"
        )
        self.reconciliation_mode = reconciliation_mode
        self.capability_profile = ProviderCapabilityProfile(
            provider=self.provider,
            control_level=ProviderControlLevel.V2_CONTROLLED,
            supports_request_timeout=True,
            supports_provider_idempotency=provider_idempotency_supported,
            supports_query=supports_query,
            supports_cancel=supports_cancel,
            supports_callback=supports_callback,
            supports_usage_receipt=True,
            supports_cost_receipt=supports_cost_receipt,
            reconciliation_mode=reconciliation_mode,
            real_provider_validation_eligible=real_provider_validation_eligible,
        )

    def invoke(self, request: ProviderInvocationRequest) -> ProviderInvocationResult:
        if request.provider != self.provider:
            raise ValueError("provider invocation was routed to the wrong adapter")
        raw = dict(self.transport.execute(request))
        return self._result(raw, request=request)

    def query_v2(self, request: ProviderQueryRequest) -> ProviderInvocationResult:
        if not self.capability_profile.supports_query:
            return ProviderInvocationResult(
                "ambiguous",
                None,
                {"manual_resolution_required": True, "query_supported": False},
                False,
            )
        return self._result(dict(self.transport.query(request)), request=request)

    def cancel_v2(
        self, request: ProviderCancellationRequest
    ) -> ProviderInvocationResult:
        if not self.capability_profile.supports_cancel:
            return ProviderInvocationResult(
                "ambiguous",
                None,
                {"manual_resolution_required": True, "cancel_supported": False},
                False,
            )
        return self._result(dict(self.transport.cancel(request)), request=request)

    def verify_callback(
        self,
        body: bytes,
        headers: Mapping[str, str],
        *,
        secret: str,
    ) -> ProviderReceipt:
        if not self.capability_profile.supports_callback:
            raise ValueError("callback verification is not supported by this route")
        receipt = self.transport.verify_callback(body, headers, secret=secret)
        if not receipt.provider_request_id or not receipt.message_id or not receipt.payload_hash:
            raise ValueError("verified callback receipt is incomplete")
        return receipt

    def _result(
        self,
        raw: dict[str, Any],
        *,
        request: ProviderInvocationRequest | ProviderQueryRequest | ProviderCancellationRequest,
    ) -> ProviderInvocationResult:
        outcome = str(raw.get("outcome") or "")
        request_sent = bool(raw.get("request_sent"))
        provider_request_id = str(raw.get("provider_request_id") or "")
        handle = None
        if provider_request_id:
            handle = ProviderInvocationHandle(
                provider_request_id=provider_request_id,
                provider_correlation_id=str(raw.get("provider_correlation_id") or provider_request_id),
                accepted_at=str(raw.get("accepted_at") or datetime.now(timezone.utc).isoformat()),
                completion_mode=str(raw.get("completion_mode") or "synchronous"),
                query_supported=self.capability_profile.supports_query,
                cancel_supported=self.capability_profile.supports_cancel,
                callback_supported=self.capability_profile.supports_callback,
                idempotency_supported=self.capability_profile.supports_provider_idempotency,
            )
        evidence = raw.get("evidence")
        if not isinstance(evidence, dict):
            raise ValueError("provider SDK result has no evidence object")
        if outcome == "success":
            usage = evidence.get("usage")
            if not isinstance(usage, dict) or any(
                not isinstance(usage.get(key), int) or usage[key] < 0
                for key in ("input_tokens", "output_tokens")
            ):
                raise ValueError("provider usage receipt is malformed")
            if self.capability_profile.supports_cost_receipt:
                cost = evidence.get("cost")
                if not isinstance(cost, dict) or not str(cost.get("currency") or ""):
                    raise ValueError("provider cost receipt is malformed")
        return ProviderInvocationResult(outcome, handle, dict(evidence), request_sent)


class OpenAISdkTransport:

    def __init__(self, client: Any) -> None:
        self.client = client

    def execute(self, request: ProviderInvocationRequest) -> Mapping[str, Any]:
        request_options: dict[str, Any] = {
            "model": request.model,
            "input": json.dumps(
                request.request_payload, ensure_ascii=False, sort_keys=True
            ),
            "timeout": request.timeout_seconds,
            "extra_headers": {"Idempotency-Key": request.stable_idempotency_key},
        }
        raw_max_output_tokens = request.request_payload.get("max_output_tokens")
        if raw_max_output_tokens is not None:
            try:
                max_output_tokens = int(raw_max_output_tokens)
            except (TypeError, ValueError) as exc:
                raise ValueError("Provider request token ceiling is invalid") from exc
            if max_output_tokens <= 0:
                raise ValueError("Provider request token ceiling must be positive")
            request_options["max_output_tokens"] = max_output_tokens
        response = self.client.responses.create(
            **request_options,
        )
        request_id = str(getattr(response, "id", "") or "")
        if not request_id:
            raise ValueError("OpenAI SDK response did not include a request ID")
        text = str(getattr(response, "output_text", "") or "")
        try:
            result = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("OpenAI SDK response was not a JSON object") from exc
        if not isinstance(result, dict):
            raise ValueError("OpenAI SDK response was not a JSON object")
        usage = getattr(response, "usage", None)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        return {
            "outcome": "success",
            "request_sent": True,
            "provider_request_id": request_id,
            "provider_correlation_id": request_id,
            "completion_mode": "synchronous",
            "evidence": {
                "result": result,
                "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
                "cost": {"amount": "0", "currency": "USD", "source": "not_provided"},
                "request_hash": request.request_hash,
            },
        }

    def query(self, request: ProviderQueryRequest) -> Mapping[str, Any]:
        response = self.client.responses.retrieve(request.provider_request_id)
        return self._control_result(response)

    def cancel(self, request: ProviderCancellationRequest) -> Mapping[str, Any]:
        response = self.client.responses.cancel(request.provider_request_id)
        result = dict(self._control_result(response))
        result["outcome"] = (
            "cancelled" if str(getattr(response, "status", "")) == "cancelled"
            else "already_completed"
        )
        return result

    def verify_callback(
        self, body: bytes, headers: Mapping[str, str], *, secret: str
    ) -> ProviderReceipt:
        webhook = self.client.webhooks.unwrap(body.decode("utf-8"), headers, secret=secret)
        data = getattr(webhook, "data", None)
        request_id = str(getattr(data, "id", "") or "")
        message_id = str(getattr(webhook, "id", "") or headers.get("webhook-id") or "")
        outcome = str(getattr(webhook, "type", "") or "")
        normalized_outcome = {
            "response.completed": "success",
            "response.failed": "final_failure",
            "response.cancelled": "cancelled",
        }.get(outcome, "retryable_failure")
        return ProviderReceipt(
            provider_request_id=request_id,
            receipt_id=message_id,
            message_id=message_id,
            outcome=normalized_outcome,
            payload_hash="sha256:" + hashlib.sha256(body).hexdigest(),
            evidence={
                "signature_verified": True,
                "provider": "openai",
                "provider_event_type": outcome,
            },
        )

    @staticmethod
    def _control_result(response: Any) -> Mapping[str, Any]:
        request_id = str(getattr(response, "id", "") or "")
        status = str(getattr(response, "status", "") or "")
        outcome = {
            "completed": "success",
            "failed": "final_failure",
            "cancelled": "cancelled",
        }.get(status, "ambiguous")
        return {
            "outcome": outcome,
            "request_sent": True,
            "provider_request_id": request_id,
            "provider_correlation_id": request_id,
            "completion_mode": "background",
            "evidence": {"provider_status": status},
        }


def build_openai_provider_adapter(api_key: str) -> OpenAIProviderAdapterV2:

    if not api_key:
        raise ValueError("OpenAI adapter requires a resolved credential")
    try:
        from openai import OpenAI
    except ModuleNotFoundError as exc:  # pragma: no cover - optional live boundary
        raise RuntimeError("OpenAI adapter requires the optional openai SDK") from exc
    return OpenAIProviderAdapterV2(
        OpenAISdkTransport(OpenAI(api_key=api_key, max_retries=0)),
        supports_query=True,
        supports_cancel=True,
        supports_callback=False,
        supports_cost_receipt=False,
        provider_idempotency_supported=True,
    )


__all__ = [
    "OpenAIProviderAdapterV2",
    "OpenAISdkTransport",
    "OpenAITransportV2",
    "build_openai_provider_adapter",
]
