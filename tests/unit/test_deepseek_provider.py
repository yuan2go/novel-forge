from dataclasses import asdict, replace
from datetime import datetime, timezone
from io import BytesIO
import json
from urllib.error import HTTPError, URLError

import pytest

from novel_forge.modules.production_execution.provider_admission import (
    ProviderRequestEnvelope,
    build_route_token_accounting_contract,
    prepare_provider_admission,
)
from novel_forge.modules.production_execution.routing_catalog import (
    deepseek_candidates,
    deepseek_expected_price_multiplier,
    deepseek_pricing_period,
)
from novel_forge.modules.provider_control.contracts import (
    ProviderCancellationRequest,
    ProviderInvocationRequest,
)
from novel_forge.modules.provider_control.deepseek import DeepSeekProviderAdapter
from tests.unit.test_provider_token_admission import COMPLETE_COVERAGE


OFF_PEAK = datetime(2026, 9, 16, 5, 0, tzinfo=timezone.utc)
PEAK = datetime(2026, 9, 16, 2, 0, tzinfo=timezone.utc)


def invocation(*, model="deepseek-flash", reasoning="low", pricing=None):
    candidate = next(
        item
        for item in deepseek_candidates(available=True)
        if item.model == model and item.reasoning == reasoning
    )
    envelope = ProviderRequestEnvelope(
        "deepseek",
        model,
        "deepseek-chat-completions-json-v1",
        "Return JSON with a classification of this original brief: a traveler pays a toll.",
        256,
        15,
        "test-effect",
        reasoning,
        json.dumps(asdict(pricing or candidate.pricing)),
    )
    contract = build_route_token_accounting_contract(
        provider=envelope.provider,
        model=envelope.model,
        route_identity="route:deepseek",
        accounting_method="DEEPSEEK_UTF8_BYTES_UPPER_BOUND_V1",
        accounting_evidence_ref="deepseek-byte-v1",
        model_context_limit=10_000,
        execution_token_limit=10_000,
        output_reserve=256,
        safety_margin=256,
        framing_overhead=32,
    )
    receipt = prepare_provider_admission(
        envelope, contract, complete_request_coverage=COMPLETE_COVERAGE
    )
    return ProviderInvocationRequest(
        "deepseek",
        envelope.model,
        "source.content.classify",
        "source.content.classify",
        envelope.stable_idempotency_key,
        envelope.to_dict(),
        envelope.envelope_hash,
        15,
        "trace",
        "correlation",
        "operation",
        "effect",
        "reservation",
        receipt.to_dict(),
    )


def response(
    content='{"classification":"fiction"}',
    finish="stop",
    *,
    created=OFF_PEAK,
    model="deepseek-flash",
):
    return {
        "id": "request-1",
        "object": "chat.completion",
        "created": int(created.timestamp()),
        "model": model,
        "system_fingerprint": "fp_test",
        "choices": [
            {
                "index": 0,
                "finish_reason": finish,
                "logprobs": None,
                "message": {
                    "role": "assistant",
                    "content": content,
                    "reasoning_content": "unretained reasoning",
                    "tool_calls": None,
                },
            }
        ],
        "usage": {
            "prompt_tokens": 80,
            "completion_tokens": 20,
            "total_tokens": 100,
            "prompt_tokens_details": {"cached_tokens": 64},
            "prompt_cache_hit_tokens": 64,
            "prompt_cache_miss_tokens": 16,
            "completion_tokens_details": {"reasoning_tokens": 12},
        },
    }


def adapter(transport, *, clock=lambda: OFF_PEAK):
    return DeepSeekProviderAdapter(
        "test-credential",
        pricing={
            item.model: item.pricing for item in deepseek_candidates(available=True)
        },
        transport=transport,
        clock=clock,
    )


@pytest.mark.parametrize("finish, outcome", [("stop", "success"), ("length", "final_failure")])
def test_missing_usage_preserves_only_complete_content_without_fabricated_cost(finish, outcome):
    payload = response(finish=finish)
    del payload["usage"]
    result = adapter(lambda *args, **kwargs: BytesIO(json.dumps(payload).encode())).invoke(invocation())
    assert result.outcome == outcome
    assert result.evidence["result"] == {"classification": "fiction"}
    assert result.evidence["usage"]["availability"] == "UNAVAILABLE"
    assert result.evidence["usage"]["total_tokens"] is None
    assert result.evidence["cost"]["measurement"] == "UNKNOWN"
    assert "amount" not in result.evidence["cost"]
    if finish == "length":
        assert result.evidence["failure_class"] == "OUTPUT_CAPACITY_EXCEEDED"


def test_catalog_uses_current_models_capabilities_and_peak_reservation_prices():
    candidates = deepseek_candidates(available=True)
    assert [
        (item.model, item.reasoning, item.pricing.input_miss_per_million)
        for item in candidates
    ] == [
        ("deepseek-flash", "low", ".3"),
        ("deepseek-v4-pro", "high", "1.32"),
        ("deepseek-v4-pro", "max", "1.32"),
    ]
    assert {item.context_limit for item in candidates} == {1_000_000}
    assert {item.output_limit for item in candidates} == {384_000}
    assert {item.capability_version for item in candidates} == {
        "deepseek-official-2026-09-16"
    }
    assert [item.model_revision for item in candidates] == [
        "DeepSeek-V4.1-Flash",
        "DeepSeek-V4-Pro-0813",
        "DeepSeek-V4-Pro-0813",
    ]
    assert all("scheduled-peak-ceiling" in item.pricing.version for item in candidates)
    assert {item.estimated_price_multiplier for item in candidates} == {"1"}


@pytest.mark.parametrize(
    "instant,period,multiplier",
    [
        (datetime(2026, 9, 14, 0, 59, tzinfo=timezone.utc), "OFF_PEAK", "0.5"),
        (datetime(2026, 9, 14, 1, 0, tzinfo=timezone.utc), "PEAK", "1"),
        (datetime(2026, 9, 14, 4, 0, tzinfo=timezone.utc), "OFF_PEAK", "0.5"),
        (datetime(2026, 9, 14, 6, 0, tzinfo=timezone.utc), "PEAK", "1"),
        (datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc), "OFF_PEAK", "0.5"),
        (datetime(2026, 9, 19, 2, 0, tzinfo=timezone.utc), "OFF_PEAK", "0.5"),
    ],
)
def test_catalog_price_estimate_uses_the_official_utc_schedule(
    instant, period, multiplier
):
    assert deepseek_pricing_period(instant) == period
    assert deepseek_expected_price_multiplier(instant) == multiplier
    assert {
        item.estimated_price_multiplier
        for item in deepseek_candidates(available=True, estimated_at=instant)
    } == {multiplier}


def test_catalog_price_estimate_requires_an_aware_decision_time():
    with pytest.raises(ValueError, match="DEEPSEEK_PRICING_TIMEZONE_REQUIRED"):
        deepseek_candidates(available=True, estimated_at=datetime(2026, 9, 14, 1))


def test_off_peak_usage_is_priced_separately_from_provider_bill():
    seen = []

    def transport(request, **kwargs):
        seen.append((request, kwargs))
        return BytesIO(json.dumps(response()).encode())

    result = adapter(transport).invoke(invocation())
    wire, options = seen[0]
    payload = json.loads(wire.data)
    assert wire.full_url == "https://api.deepseek.com/chat/completions"
    assert payload["thinking"] == {"type": "enabled"}
    assert payload["reasoning_effort"] == "low"
    assert payload["response_format"] == {"type": "json_object"}
    assert options["timeout"] == 15
    assert result.outcome == "success"
    assert result.evidence["model_id"] == "deepseek-flash"
    assert result.evidence["model_revision"] == "DeepSeek-V4.1-Flash"
    assert result.evidence["served_model_id"] == "deepseek-flash"
    assert result.evidence["served_model_identity_hash"].startswith("sha256:")
    assert result.evidence["usage"] == {
        "availability": "AVAILABLE",
        "measurement": "PROVIDER_REPORTED",
        "input_tokens": 80,
        "output_tokens": 20,
        "total_tokens": 100,
        "prompt_cache_hit_tokens": 64,
        "prompt_cache_miss_tokens": 16,
        "cache_usage_status": "OBSERVED",
        "reasoning_tokens": 12,
    }
    cost = result.evidence["cost"]
    assert cost["amount"] == "0.000014592"
    assert cost["reservation_ceiling_amount"] == "0.000029184"
    assert cost["source"] == "usage_pricing"
    assert cost["measurement"] == "PRICED_FROM_PROVIDER_USAGE"
    assert cost["estimated"] is True
    assert cost["provider_billed"] is False
    assert cost["provider_billed_amount"] is None
    assert cost["pricing_period"] == "OFF_PEAK"
    assert cost["pricing_time_basis"] == "PROVIDER_CREATED_ASSUMPTION"
    assert cost["pricing_snapshot_hash"].startswith("sha256:")
    assert "test-credential" not in json.dumps(result.evidence)
    assert "unretained reasoning" not in json.dumps(result.evidence)


def test_peak_usage_uses_the_reserved_peak_ceiling():
    result = adapter(
        lambda *args, **kwargs: BytesIO(json.dumps(response(created=PEAK)).encode()),
        clock=lambda: PEAK,
    ).invoke(invocation())
    assert result.evidence["cost"]["amount"] == "0.000029184"
    assert result.evidence["cost"]["pricing_period"] == "PEAK"
    assert result.evidence["cost"]["measurement"] == "PRICED_FROM_PROVIDER_USAGE"


def test_boundary_crossing_uses_peak_upper_bound():
    instants = iter(
        [
            datetime(2026, 9, 16, 5, 59, 59, tzinfo=timezone.utc),
            datetime(2026, 9, 16, 6, 0, 1, tzinfo=timezone.utc),
        ]
    )
    result = adapter(
        lambda *args, **kwargs: BytesIO(
            json.dumps(
                response(created=datetime(2026, 9, 16, 5, 59, 59, tzinfo=timezone.utc))
            ).encode()
        ),
        clock=lambda: next(instants),
    ).invoke(invocation())
    assert result.evidence["cost"]["amount"] == "0.000029184"
    assert result.evidence["cost"]["pricing_period"] == "BOUNDARY_CROSSING"
    assert result.evidence["cost"]["measurement"] == "ESTIMATED_UPPER_BOUND"
    assert result.evidence["cost"]["pricing_time_basis"] == "PEAK_CEILING"


def test_frozen_pricing_must_match_the_configured_catalog():
    configured = deepseek_candidates(available=True)[0].pricing
    cheaper = replace(configured, input_miss_per_million=".01")
    with pytest.raises(ValueError, match="DEEPSEEK_FROZEN_PRICING_DRIFT"):
        adapter(lambda *args, **kwargs: pytest.fail("must not send")).invoke(
            invocation(pricing=cheaper)
        )


@pytest.mark.parametrize(
    "status,expected,submission,manual",
    [
        (429, "retryable_failure", "REJECTED_BEFORE_EXECUTION", False),
        (503, "retryable_failure", "REJECTED_BEFORE_EXECUTION", False),
        (401, "final_failure", "REJECTED_BEFORE_EXECUTION", False),
        (408, "unknown", "UNKNOWN", True),
        (500, "unknown", "UNKNOWN", True),
    ],
)
def test_http_failures_are_sanitized_without_hidden_retries(
    status, expected, submission, manual
):
    calls = []

    def transport(request, **kwargs):
        calls.append(request)
        raise HTTPError(
            request.full_url, status, "test-credential", {"Retry-After": "7"}, BytesIO()
        )

    result = adapter(transport).invoke(invocation())
    assert result.outcome == expected
    assert len(calls) == 1
    assert result.evidence["submission_state"] == submission
    assert result.evidence["manual_resolution_required"] is manual
    assert result.evidence["retry_after_seconds"] == 7
    assert "test-credential" not in json.dumps(result.evidence)


def test_http_failure_without_retry_after_headers_is_sanitized():
    def transport(request, **kwargs):
        raise HTTPError(request.full_url, 503, "secret", None, BytesIO())

    result = adapter(transport).invoke(invocation())
    assert result.outcome == "retryable_failure"
    assert result.evidence["retry_after_seconds"] is None
    assert "secret" not in json.dumps(result.evidence)


@pytest.mark.parametrize(
    "code,failure",
    [
        ("context_length_exceeded", "CONTEXT_OVERFLOW"),
        ("invalid_json_schema", "SCHEMA_REJECTION"),
        ("unknown", "CONTRACT_REJECTION"),
    ],
)
def test_contract_failure_classification_never_persists_remote_error_text(
    code, failure
):
    def transport(request, **kwargs):
        raise HTTPError(
            request.full_url,
            400,
            "private",
            {},
            BytesIO(
                json.dumps(
                    {
                        "error": {
                            "code": code,
                            "message": "private credential and source text",
                        },
                    }
                ).encode()
            ),
        )

    result = adapter(transport).invoke(invocation())
    assert result.evidence["failure_class"] == failure
    assert "private" not in json.dumps(result.evidence)


def test_provider_aborted_response_preserves_paid_usage():
    result = adapter(
        lambda *args, **kwargs: BytesIO(json.dumps(response(finish="aborted")).encode())
    ).invoke(invocation())
    assert result.outcome == "final_failure"
    assert result.evidence["failure_class"] == "CANCELLED"
    assert result.evidence["usage"]["total_tokens"] == 100
    assert result.evidence["cost"]["amount"]


@pytest.mark.parametrize("raised", [TimeoutError("secret"), URLError("secret")])
def test_transport_ambiguity_fails_closed(raised):
    def transport(*args, **kwargs):
        raise raised

    result = adapter(transport).invoke(invocation())
    assert result.outcome == "unknown"
    assert result.evidence["submission_state"] == "UNKNOWN"
    assert result.evidence["manual_resolution_required"]
    assert "secret" not in json.dumps(result.evidence)


def test_missing_required_cache_usage_is_an_ambiguous_receipt():
    malformed = response()
    del malformed["usage"]["prompt_cache_hit_tokens"]
    result = adapter(
        lambda *args, **kwargs: BytesIO(json.dumps(malformed).encode())
    ).invoke(invocation())
    assert result.outcome == "unknown"
    assert result.evidence["failure_class"] == "MALFORMED_PROVIDER_RECEIPT"
    assert "cost" not in result.evidence


def test_stale_provider_created_timestamp_is_an_ambiguous_receipt():
    stale = response(created=datetime(2026, 9, 15, 5, 0, tzinfo=timezone.utc))
    result = adapter(
        lambda *args, **kwargs: BytesIO(json.dumps(stale).encode())
    ).invoke(invocation())
    assert result.outcome == "unknown"
    assert result.evidence["failure_class"] == "MALFORMED_PROVIDER_RECEIPT"


@pytest.mark.parametrize(
    "content,finish,outcome,failure",
    [
        ("not-json", "stop", "final_failure", "MALFORMED_STRUCTURED_OUTPUT"),
        (
            '{"classification":"fiction"}',
            "length",
            "final_failure",
            "OUTPUT_CAPACITY_EXCEEDED",
        ),
        (
            "",
            "content_filter",
            "final_failure",
            "POLICY_REJECTION",
        ),
        (
            "",
            "insufficient_system_resource",
            "retryable_failure",
            "PROVIDER_UNAVAILABLE",
        ),
    ],
)
def test_terminal_response_failure_retains_billable_usage(
    content, finish, outcome, failure
):
    result = adapter(
        lambda *args, **kwargs: BytesIO(json.dumps(response(content, finish)).encode())
    ).invoke(invocation())
    assert result.outcome == outcome
    assert result.evidence["failure_class"] == failure
    assert result.evidence["usage"]["output_tokens"] == 20
    assert result.evidence["cost"]["amount"] != "0"
    import hashlib
    assert result.evidence["rejected_output"] == {
        "text": content, "sha256": "sha256:" + hashlib.sha256(content.encode()).hexdigest(),
        "source": "PROVIDER_MESSAGE_CONTENT", "accepted": False,
    }
    assert "unretained reasoning" not in json.dumps(result.evidence)



def test_two_top_level_objects_remain_failed_with_exact_parser_location_and_cost():
    raw = '{"type":"json_object"}\n{"classification":"fiction"}'
    result = adapter(
        lambda *args, **kwargs: BytesIO(json.dumps(response(raw)).encode())
    ).invoke(invocation())
    assert result.outcome == "final_failure"
    assert result.evidence["failure_class"] == "MALFORMED_STRUCTURED_OUTPUT"
    assert result.evidence["result"] == {}
    assert result.evidence["structured_output_error"] == {
        "code": "JSON_SYNTAX_ERROR", "message": "Extra data",
        "line": 2, "column": 1, "offset": 23,
    }
    assert result.evidence["rejected_output"]["text"] == raw
    assert result.evidence["rejected_output"]["accepted"] is False
    assert result.evidence["usage"]["total_tokens"] == 100
    assert result.evidence["cost"]["amount"] == "0.000014592"
    assert "unretained reasoning" not in json.dumps(result.evidence)


def test_malformed_message_shape_is_an_ambiguous_receipt():
    malformed = response()
    malformed["choices"][0]["message"] = []
    result = adapter(
        lambda *args, **kwargs: BytesIO(json.dumps(malformed).encode())
    ).invoke(invocation())
    assert result.outcome == "unknown"
    assert result.evidence["failure_class"] == "MALFORMED_PROVIDER_RECEIPT"


def test_changed_reasoning_cannot_bypass_admission():
    request = invocation()
    with pytest.raises(ValueError):
        adapter(lambda *args, **kwargs: pytest.fail("must not send")).invoke(
            replace(
                request,
                request_payload={**request.request_payload, "reasoning_effort": "max"},
            )
        )


def test_cancellation_truthfully_reports_no_upstream_control():
    result = adapter(lambda *args, **kwargs: pytest.fail("must not send")).cancel_v2(
        ProviderCancellationRequest(
            "request-1", "test-effect", "operator requested", "trace", "correlation"
        )
    )
    assert result.outcome == "ambiguous"
    assert result.request_sent is False
    assert result.evidence == {
        "cancel_supported": False,
        "upstream_cancellation": "UNSUPPORTED",
        "manual_resolution_required": True,
    }
