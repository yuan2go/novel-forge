from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import socket
import time
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from novel_forge.modules.production_execution.cost_routing import PricingSnapshot
from novel_forge.modules.production_execution.provider_admission import (
    ProviderAdmissionReceipt,
    ProviderRequestEnvelope,
    verify_provider_admission,
)
from .contracts import (
    ProviderCancellationRequest,
    ProviderCapabilityProfile,
    ProviderControlLevel,
    ProviderInvocationHandle,
    ProviderInvocationRequest,
    ProviderInvocationResult,
    ProviderQueryRequest,
)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


class DeepSeekProviderAdapter:
    provider = "deepseek"

    def __init__(
        self,
        api_key: str,
        *,
        pricing: Mapping[str, PricingSnapshot],
        transport: Callable[..., Any] | None = None,
    ) -> None:
        if not api_key.strip() or not pricing:
            raise ValueError("DEEPSEEK_CREDENTIAL_AND_PRICING_REQUIRED")
        self._api_key = api_key
        self.pricing = dict(pricing)
        self._transport = transport or build_opener(_NoRedirect()).open
        self.capability_profile = ProviderCapabilityProfile(
            provider=self.provider,
            control_level=ProviderControlLevel.V2_CONTROLLED,
            supports_request_timeout=True,
            supports_provider_idempotency=False,
            supports_query=False,
            supports_cancel=False,
            supports_callback=False,
            supports_usage_receipt=True,
            supports_cost_receipt=False,
            reconciliation_mode="unsupported",
            real_provider_validation_eligible=True,
            durable_intent_required=True,
            supports_usage_pricing=True,
        )

    def invoke(self, request: ProviderInvocationRequest) -> ProviderInvocationResult:
        envelope = ProviderRequestEnvelope.from_dict(request.request_payload)
        if request.provider != self.provider or envelope.provider != self.provider:
            raise ValueError("DEEPSEEK_PROVIDER_IDENTITY_DRIFT")
        if not request.provider_admission:
            raise ValueError("PROVIDER_ADMISSION_REQUIRED")
        verify_provider_admission(
            envelope, ProviderAdmissionReceipt.from_dict(request.provider_admission)
        )
        if (
            request.request_hash != envelope.envelope_hash
            or request.model != envelope.model
            or request.stable_idempotency_key != envelope.stable_idempotency_key
            or request.timeout_seconds != envelope.timeout_seconds
        ):
            raise ValueError("PROVIDER_REQUEST_IDENTITY_DRIFT")
        if envelope.model not in self.pricing or envelope.reasoning_effort not in {
            "low",
            "high",
            "max",
            "none",
        }:
            raise ValueError("DEEPSEEK_MODEL_OR_REASONING_NOT_ADMITTED")
        if not envelope.pricing_policy_json:
            raise ValueError("DEEPSEEK_FROZEN_PRICING_REQUIRED")
        price = PricingSnapshot(**json.loads(envelope.pricing_policy_json))
        if price.accounting_basis != "PRICED" or price.currency != "USD":
            raise ValueError("DEEPSEEK_PRICING_CONTRACT_INVALID")
        now = datetime.now(timezone.utc)
        if (
            not datetime.fromisoformat(price.effective_from)
            <= now
            < datetime.fromisoformat(price.effective_until)
        ):
            raise ValueError("DEEPSEEK_PRICING_EXPIRED")
        body: dict[str, Any] = {
            "model": envelope.model,
            "messages": [{"role": "user", "content": envelope.input_text}],
            "max_tokens": envelope.max_output_tokens,
            "response_format": {"type": "json_object"},
            "thinking": {
                "type": "disabled" if envelope.reasoning_effort == "none" else "enabled"
            },
            "stream": False,
        }
        if envelope.reasoning_effort != "none":
            body["reasoning_effort"] = envelope.reasoning_effort
        wire = Request(
            "https://api.deepseek.com/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode(),
            method="POST",
            headers={
                "Authorization": "Bearer " + self._api_key,
                "Content-Type": "application/json",
            },
        )
        started = time.monotonic()
        try:
            with self._transport(wire, timeout=envelope.timeout_seconds) as response:
                raw = response.read(16_000_001)
                if len(raw) > 16_000_000:
                    return self._failure(
                        "unknown", "RESPONSE_CAPACITY_EXCEEDED", started
                    )
                content = json.loads(raw)
        except HTTPError as exc:
            status = exc.code
            retry_after = _retry_after(exc.headers.get("Retry-After", ""))
            failure = {
                400: "CONTRACT_REJECTION",
                401: "AUTHENTICATION_FAILED",
                402: "PROVIDER_BUDGET_EXHAUSTED",
                403: "POLICY_REJECTION",
                422: "CONTRACT_REJECTION",
                429: "RATE_LIMIT",
                503: "PROVIDER_UNAVAILABLE",
            }.get(status, "PROVIDER_UNAVAILABLE")
            outcome = (
                "retryable_failure"
                if status in {429, 503}
                else "unknown"
                if status >= 500
                else "final_failure"
            )
            return self._failure(
                outcome,
                failure,
                started,
                http_status=status,
                retry_after_seconds=retry_after,
                submission_state="REJECTED_BEFORE_EXECUTION"
                if status < 500 or status == 503
                else "UNKNOWN",
            )
        except (TimeoutError, socket.timeout):
            return self._failure("unknown", "TIMEOUT", started)
        except URLError:
            return self._failure("unknown", "TRANSIENT_NETWORK", started)
        except (ValueError, OSError):
            return self._failure("unknown", "MALFORMED_PROVIDER_RECEIPT", started)
        try:
            return self._completed(content, request, price, started)
        except (ValueError, TypeError, KeyError, IndexError):
            return self._failure("unknown", "MALFORMED_PROVIDER_RECEIPT", started)

    def _completed(
        self,
        content: Mapping[str, Any],
        request: ProviderInvocationRequest,
        price: PricingSnapshot,
        started: float,
    ) -> ProviderInvocationResult:
        usage = content["usage"]
        input_tokens = usage["prompt_tokens"]
        output_tokens = usage["completion_tokens"]
        cached = usage.get("prompt_cache_hit_tokens")
        missed = usage.get("prompt_cache_miss_tokens")
        if any(
            type(value) is not int or value < 0
            for value in (input_tokens, output_tokens)
        ):
            raise ValueError("DEEPSEEK_USAGE_INVALID")
        cache_known = type(cached) is int and type(missed) is int
        if cache_known and (min(cached, missed) < 0 or cached + missed != input_tokens):
            raise ValueError("DEEPSEEK_CACHE_USAGE_INVALID")
        request_id = str(content["id"])
        served_model = str(content["model"])
        if not request_id or not served_model:
            raise ValueError("DEEPSEEK_RESPONSE_IDENTITY_REQUIRED")
        choice = content["choices"][0]
        text = str(choice["message"].get("content") or "")
        failure = ""
        if choice.get("finish_reason") == "length":
            failure = "OUTPUT_CAPACITY_EXCEEDED"
        elif choice.get("finish_reason") != "stop":
            failure = "POLICY_REJECTION"
        try:
            output = json.loads(text)
            if not isinstance(output, dict):
                failure = "MALFORMED_STRUCTURED_OUTPUT"
        except ValueError:
            failure, output = "MALFORMED_STRUCTURED_OUTPUT", {}
        evidence = {
            "result": output,
            "provider_id": self.provider,
            "model_id": request.model,
            "served_model_id": served_model,
            "reasoning_effort": request.request_payload.get("reasoning_effort"),
            "request_hash": request.request_hash,
            "real_model_call": True,
            "fixture_protocol_only": False,
            "production_verified": False,
            "latency_seconds": time.monotonic() - started,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "prompt_cache_hit_tokens": cached if cache_known else None,
                "prompt_cache_miss_tokens": missed if cache_known else None,
                "cache_usage_status": "OBSERVED" if cache_known else "UNKNOWN",
                "reasoning_tokens": dict(
                    usage.get("completion_tokens_details") or {}
                ).get("reasoning_tokens"),
            },
            "cost": {
                "amount": str(
                    price.amount(
                        input_tokens, output_tokens, cached if cache_known else 0
                    )
                ),
                "currency": price.currency,
                "source": "usage_pricing_upper_bound",
                "availability": "AVAILABLE",
                "measurement": "ESTIMATED_UPPER_BOUND",
                "estimated": True,
                "provider_billed": False,
                "pricing_version": price.version,
                "provider_billed_amount": None,
                "pricing_snapshot": {key: value for key, value in vars(price).items()},
            },
            "finish_reason": choice.get("finish_reason"),
            "failure_class": failure,
        }
        return ProviderInvocationResult(
            "final_failure" if failure else "success",
            ProviderInvocationHandle(
                request_id,
                request_id,
                datetime.now(timezone.utc).isoformat(),
                "synchronous",
                False,
                False,
                False,
                False,
            ),
            evidence,
            True,
        )

    @staticmethod
    def _failure(
        outcome: str, failure: str, started: float, **evidence: Any
    ) -> ProviderInvocationResult:
        return ProviderInvocationResult(
            outcome,
            None,
            {
                "provider_id": "deepseek",
                "failure_class": failure,
                "latency_seconds": time.monotonic() - started,
                "submission_state": "UNKNOWN",
                "manual_resolution_required": outcome == "unknown",
                **evidence,
            },
            True,
        )

    def query_v2(self, request: ProviderQueryRequest) -> ProviderInvocationResult:
        return ProviderInvocationResult(
            "ambiguous",
            None,
            {"query_supported": False, "manual_resolution_required": True},
            False,
        )

    def cancel_v2(
        self, request: ProviderCancellationRequest
    ) -> ProviderInvocationResult:
        return ProviderInvocationResult(
            "ambiguous",
            None,
            {
                "cancel_supported": False,
                "upstream_cancellation": "UNSUPPORTED",
                "manual_resolution_required": True,
            },
            False,
        )


def _retry_after(value: str) -> float | None:
    if not value:
        return None
    try:
        return max(0, float(value))
    except ValueError:
        try:
            return max(
                0,
                (
                    parsedate_to_datetime(value) - datetime.now(timezone.utc)
                ).total_seconds(),
            )
        except (TypeError, ValueError):
            return None
