from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from email.utils import parsedate_to_datetime
import hashlib
import json
import math
import socket
import time
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from novel_forge.modules.production_execution.cost_routing import (
    PricingSnapshot,
    snapshot_hash,
)
from novel_forge.modules.production_execution.routing_catalog import (
    deepseek_expected_price_multiplier,
    deepseek_model_revision,
    deepseek_model_routing_available,
    deepseek_pricing_period,
)
from novel_forge.modules.production_execution.provider_admission import (
    DEEPSEEK_OUTPUT_TOOL,
    DEEPSEEK_STRICT_PROTOCOL,
    deepseek_strict_tools,
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
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not api_key.strip() or not pricing:
            raise ValueError("DEEPSEEK_CREDENTIAL_AND_PRICING_REQUIRED")
        self._api_key = api_key
        self.pricing = dict(pricing)
        self._transport = transport or build_opener(_NoRedirect()).open
        self._clock = clock or (lambda: datetime.now(timezone.utc))
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
        if (
            envelope.protocol
            not in {"deepseek-chat-completions-json-v1", DEEPSEEK_STRICT_PROTOCOL}
            or envelope.model not in self.pricing
            or not deepseek_model_routing_available(envelope.model)
            or envelope.reasoning_effort
            not in {
                "low",
                "high",
                "max",
                "none",
            }
        ):
            raise ValueError("DEEPSEEK_MODEL_OR_REASONING_NOT_ADMITTED")
        if not envelope.pricing_policy_json:
            raise ValueError("DEEPSEEK_FROZEN_PRICING_REQUIRED")
        price = PricingSnapshot(**json.loads(envelope.pricing_policy_json))
        if price != self.pricing[envelope.model]:
            raise ValueError("DEEPSEEK_FROZEN_PRICING_DRIFT")
        if price.accounting_basis != "PRICED" or price.currency != "USD":
            raise ValueError("DEEPSEEK_PRICING_CONTRACT_INVALID")
        requested_model_revision = deepseek_model_revision(envelope.model)
        submitted_at = self._clock()
        if submitted_at.tzinfo is None:
            raise ValueError("DEEPSEEK_CLOCK_TIMEZONE_REQUIRED")
        if (
            not datetime.fromisoformat(price.effective_from)
            <= submitted_at
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
        strict_output = envelope.protocol == DEEPSEEK_STRICT_PROTOCOL
        if strict_output:
            body.pop("response_format")
            body["tools"] = deepseek_strict_tools(envelope.output_schema_json)
        wire = Request(
            "https://api.deepseek.com/beta/chat/completions"
            if strict_output
            else "https://api.deepseek.com/chat/completions",
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
            retry_after = _retry_after(
                exc.headers.get("Retry-After", "") if exc.headers else ""
            )
            failure = {
                400: "CONTRACT_REJECTION",
                401: "AUTHENTICATION_FAILED",
                402: "PROVIDER_BUDGET_EXHAUSTED",
                403: "POLICY_REJECTION",
                408: "TIMEOUT",
                422: "CONTRACT_REJECTION",
                429: "RATE_LIMIT",
                503: "PROVIDER_UNAVAILABLE",
            }.get(status, "PROVIDER_UNAVAILABLE")
            if status in {400, 422}:
                failure = _contract_failure(exc)
            outcome = (
                "retryable_failure"
                if status in {429, 503}
                else "unknown"
                if status == 408 or status >= 500
                else "final_failure"
            )
            return self._failure(
                outcome,
                failure,
                started,
                http_status=status,
                failure_cause=_safe_cause(exc),
                retry_after_seconds=retry_after,
                submission_state=(
                    "UNKNOWN" if outcome == "unknown" else "REJECTED_BEFORE_EXECUTION"
                ),
            )
        except (TimeoutError, socket.timeout) as exc:
            return self._failure("unknown", "TIMEOUT", started, failure_cause=_safe_cause(exc))
        except URLError as exc:
            return self._failure("unknown", "TRANSIENT_NETWORK", started, failure_cause=_safe_cause(exc))
        except (ValueError, OSError) as exc:
            return self._failure("unknown", "MALFORMED_PROVIDER_RECEIPT", started, failure_cause=_safe_cause(exc))
        try:
            return self._completed(
                content,
                request,
                price,
                requested_model_revision,
                submitted_at,
                started,
            )
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            return self._failure("unknown", "MALFORMED_PROVIDER_RECEIPT", started, failure_cause=_safe_cause(exc))

    def _completed(
        self,
        content: Mapping[str, Any],
        request: ProviderInvocationRequest,
        price: PricingSnapshot,
        requested_model_revision: str,
        submitted_at: datetime,
        started: float,
    ) -> ProviderInvocationResult:
        usage = content.get("usage")
        input_tokens = output_tokens = total_tokens = cached = missed = reasoning_tokens = None
        if usage is not None:
            input_tokens = usage["prompt_tokens"]
            output_tokens = usage["completion_tokens"]
            total_tokens = usage["total_tokens"]
            cached = usage["prompt_cache_hit_tokens"]
            missed = usage["prompt_cache_miss_tokens"]
            if any(
                type(value) is not int or value < 0
                for value in (
                    input_tokens,
                    output_tokens,
                    total_tokens,
                    cached,
                    missed,
                )
            ):
                raise ValueError("DEEPSEEK_USAGE_INVALID")
            if (
                cached + missed != input_tokens
                or input_tokens + output_tokens != total_tokens
            ):
                raise ValueError("DEEPSEEK_CACHE_USAGE_INVALID")
            reasoning_tokens = dict(usage.get("completion_tokens_details") or {}).get(
                "reasoning_tokens"
            )
            if reasoning_tokens is not None and (
                type(reasoning_tokens) is not int
                or reasoning_tokens < 0
                or reasoning_tokens > output_tokens
            ):
                raise ValueError("DEEPSEEK_REASONING_USAGE_INVALID")
        request_id = content["id"]
        served_model = content["model"]
        system_fingerprint = content["system_fingerprint"]
        if (
            not isinstance(request_id, str)
            or not request_id
            or not isinstance(served_model, str)
            or not served_model
            or not isinstance(system_fingerprint, str)
            or not system_fingerprint
            or content["object"] != "chat.completion"
        ):
            raise ValueError("DEEPSEEK_RESPONSE_IDENTITY_REQUIRED")
        created = content["created"]
        if type(created) is not int or created <= 0:
            raise ValueError("DEEPSEEK_RESPONSE_TIME_INVALID")
        provider_created_at = datetime.fromtimestamp(created, timezone.utc)
        completed_at = self._clock()
        if completed_at.tzinfo is None:
            raise ValueError("DEEPSEEK_CLOCK_TIMEZONE_REQUIRED")
        if (
            abs((provider_created_at - submitted_at).total_seconds()) > 300
            or provider_created_at < datetime.fromisoformat(price.effective_from)
            or provider_created_at >= datetime.fromisoformat(price.effective_until)
        ):
            raise ValueError("DEEPSEEK_RESPONSE_TIME_INVALID")
        choice = content["choices"][0]
        if not isinstance(choice, Mapping) or not isinstance(
            choice.get("message"), Mapping
        ):
            raise ValueError("DEEPSEEK_MESSAGE_INVALID")
        raw_text = choice["message"].get("content")
        if raw_text is not None and not isinstance(raw_text, str):
            raise ValueError("DEEPSEEK_MESSAGE_INVALID")
        text = raw_text or ""
        strict_output = (
            request.request_payload.get("protocol") == DEEPSEEK_STRICT_PROTOCOL
        )
        tool_error = ""
        if strict_output:
            calls = choice["message"].get("tool_calls")
            tool = calls[0] if isinstance(calls, list) and len(calls) == 1 else None
            function = tool.get("function") if isinstance(tool, Mapping) else None
            if (
                not isinstance(function, Mapping)
                or tool.get("type") != "function"
                or function.get("name") != DEEPSEEK_OUTPUT_TOOL
                or not isinstance(function.get("arguments"), str)
            ):
                tool_error = "STRUCTURED_TOOL_CALL_REQUIRED"
                text = json.dumps(
                    {"content": raw_text, "tool_calls": calls}, ensure_ascii=False
                )
            else:
                text = function["arguments"]
        finish_reason = choice.get("finish_reason")
        failure = {
            "stop": "",
            "length": "OUTPUT_CAPACITY_EXCEEDED",
            "content_filter": "POLICY_REJECTION",
            "insufficient_system_resource": "PROVIDER_UNAVAILABLE",
            "aborted": "CANCELLED",
        }.get(finish_reason)
        if strict_output and finish_reason == "tool_calls":
            failure = tool_error
        elif strict_output and not failure:
            failure = tool_error or "STRUCTURED_TOOL_CALL_REQUIRED"
        if failure is None:
            raise ValueError("DEEPSEEK_FINISH_REASON_INVALID")
        structured_output_error = None
        try:
            output = json.loads(text)
            if not isinstance(output, dict):
                output = {}
                structured_output_error = {"code": "JSON_OBJECT_REQUIRED"}
                if not failure:
                    failure = "MALFORMED_STRUCTURED_OUTPUT"
        except json.JSONDecodeError as exc:
            output = {}
            structured_output_error = {
                "code": "JSON_SYNTAX_ERROR",
                "message": exc.msg,
                "line": exc.lineno,
                "column": exc.colno,
                "offset": exc.pos,
            }
            if not failure:
                failure = "MALFORMED_STRUCTURED_OUTPUT"
        amount = reservation_ceiling = None
        pricing_period = pricing_time_basis = measurement = "UNKNOWN"
        pricing_multiplier = None
        if usage is not None:
            reservation_ceiling = price.amount(input_tokens, output_tokens, cached)
            price_periods = {
                deepseek_pricing_period(value)
                for value in (submitted_at, provider_created_at, completed_at)
            }
            if len(price_periods) > 1:
                amount = reservation_ceiling
                pricing_period = "BOUNDARY_CROSSING"
                pricing_time_basis = "PEAK_CEILING"
                measurement = "ESTIMATED_UPPER_BOUND"
                pricing_multiplier = Decimal("1")
            else:
                pricing_period = price_periods.pop()
                pricing_time_basis = "PROVIDER_CREATED_ASSUMPTION"
                measurement = "PRICED_FROM_PROVIDER_USAGE"
                pricing_multiplier = Decimal(
                    deepseek_expected_price_multiplier(provider_created_at)
                )
                amount = reservation_ceiling * pricing_multiplier
        pricing_snapshot = asdict(price)
        served_model_identity_hash = snapshot_hash(
            {
                "provider": self.provider,
                "requested_model_id": request.model,
                "requested_model_revision": requested_model_revision,
                "served_model_id": served_model,
                "system_fingerprint": system_fingerprint,
            }
        )
        evidence = {
            "result": output,
            **(
                {
                    "output_protocol": DEEPSEEK_STRICT_PROTOCOL,
                    "structured_output_tool": DEEPSEEK_OUTPUT_TOOL,
                    "structured_output": {
                        "source": ("PROVIDER_TOOL_CONTRACT_FAILURE" if tool_error
                                   else "PROVIDER_TOOL_ARGUMENTS"),
                        "text": text,
                        "sha256": "sha256:" + hashlib.sha256(text.encode()).hexdigest(),
                        "domain_validation": "PENDING",
                    },
                    "output_schema_hash": "sha256:"
                    + hashlib.sha256(
                        str(request.request_payload["output_schema_json"]).encode()
                    ).hexdigest(),
                    "output_text_sha256": "sha256:"
                    + hashlib.sha256(text.encode()).hexdigest(),
                }
                if strict_output
                else {}
            ),
            **(
                {"structured_output_error": structured_output_error}
                if structured_output_error
                else {}
            ),
            "provider_id": self.provider,
            "model_id": request.model,
            "model_revision": requested_model_revision,
            "served_model_id": served_model,
            "system_fingerprint": system_fingerprint,
            "served_model_identity_hash": served_model_identity_hash,
            "reasoning_effort": request.request_payload.get("reasoning_effort"),
            "request_hash": request.request_hash,
            "real_model_call": True,
            "fixture_protocol_only": False,
            "production_verified": False,
            "latency_seconds": time.monotonic() - started,
            "usage": {
                "availability": "AVAILABLE" if usage is not None else "UNAVAILABLE",
                "measurement": "PROVIDER_REPORTED" if usage is not None else "UNKNOWN",
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "prompt_cache_hit_tokens": cached,
                "prompt_cache_miss_tokens": missed,
                "cache_usage_status": "OBSERVED" if usage is not None else "UNKNOWN",
                "reasoning_tokens": reasoning_tokens,
            },
            "cost": {
                "amount": format(amount.normalize(), "f"),
                "reservation_ceiling_amount": format(
                    reservation_ceiling.normalize(), "f"
                ),
                "currency": price.currency,
                "source": "usage_pricing",
                "availability": "AVAILABLE",
                "measurement": measurement,
                "estimated": True,
                "provider_billed": False,
                "accounting_basis": price.accounting_basis,
                "pricing_version": price.version,
                "pricing_period": pricing_period,
                "pricing_multiplier": str(pricing_multiplier),
                "pricing_time_basis": pricing_time_basis,
                "provider_created_at": provider_created_at.isoformat(),
                "provider_billed_amount": None,
                "pricing_snapshot_hash": snapshot_hash(pricing_snapshot),
                "pricing_snapshot": pricing_snapshot,
            } if usage is not None else {
                "availability": "UNAVAILABLE", "measurement": "UNKNOWN",
                "reason": "provider_completed_content_without_usage",
                "accounting_basis": price.accounting_basis,
            },
            "finish_reason": finish_reason,
            "failure_class": failure,
        }
        if failure:
            # SECURITY: Retain final content only, never transport headers or hidden reasoning.
            evidence["rejected_output"] = {
                "text": text,
                "sha256": "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "source": "PROVIDER_TOOL_ARGUMENTS_OR_REJECTED_MESSAGE"
                if strict_output
                else "PROVIDER_MESSAGE_CONTENT",
                "accepted": False,
            }
        outcome = (
            "retryable_failure"
            if finish_reason == "insufficient_system_resource"
            else "final_failure"
            if failure
            else "success"
        )
        return ProviderInvocationResult(
            outcome,
            ProviderInvocationHandle(
                request_id,
                request_id,
                provider_created_at.isoformat(),
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
        seconds = float(value)
        return max(0, seconds) if math.isfinite(seconds) else None
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


def _safe_cause(error):
    chain = []
    seen = set()
    while isinstance(error, BaseException) and id(error) not in seen:
        seen.add(id(error))
        item = {"exception_type": type(error).__name__}
        for key in ("errno", "code"):
            value = getattr(error, key, None)
            if type(value) is int:
                item[key] = value
        chain.append(item)
        error = error.__cause__ or error.__context__ or getattr(error, "reason", None)
    return json.dumps(chain, sort_keys=True)


def _contract_failure(response: HTTPError) -> str:
    try:
        payload = json.loads(response.read(65536))
        error = payload.get("error") or {}
        code = str(error.get("code") or "").lower()
        message = str(error.get("message") or "").lower()
    except (OSError, ValueError, AttributeError, TypeError):
        return "CONTRACT_REJECTION"
    if code in {"context_length_exceeded", "max_context_length_exceeded"} or (
        "context" in message and any(word in message for word in ("exceed", "maximum"))
    ):
        return "CONTEXT_OVERFLOW"
    if code in {"invalid_json_schema", "invalid_response_format"}:
        return "SCHEMA_REJECTION"
    return "CONTRACT_REJECTION"
