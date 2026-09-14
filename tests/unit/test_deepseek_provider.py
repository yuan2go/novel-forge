from dataclasses import asdict, replace
from io import BytesIO
import json
from urllib.error import HTTPError

import pytest

from novel_forge.modules.production_execution.provider_admission import (
    ProviderRequestEnvelope,
    build_route_token_accounting_contract,
    prepare_provider_admission,
)
from novel_forge.modules.production_execution.routing_catalog import deepseek_candidates
from novel_forge.modules.provider_control.contracts import ProviderInvocationRequest
from novel_forge.modules.provider_control.deepseek import DeepSeekProviderAdapter
from tests.unit.test_provider_token_admission import COMPLETE_COVERAGE


def invocation():
    envelope = ProviderRequestEnvelope(
        "deepseek",
        "deepseek-flash",
        "deepseek-chat-completions-json-v1",
        "Return JSON with a classification of this original brief: a traveler pays a toll.",
        256,
        15,
        "test-effect",
        "low",
        json.dumps(asdict(deepseek_candidates(available=True)[0].pricing)),
    )
    contract = build_route_token_accounting_contract(
        provider=envelope.provider,
        model=envelope.model,
        route_identity="route:deepseek",
        accounting_method="DEEPSEEK_UTF8_BYTES_UPPER_BOUND_V1",
        accounting_evidence_ref="deepseek-byte-v1",
        model_context_limit=10000,
        execution_token_limit=10000,
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


def response(content='{"classification":"fiction"}', finish="stop"):
    return {
        "id": "request-1",
        "model": "deepseek-flash",
        "choices": [
            {
                "finish_reason": finish,
                "message": {
                    "content": content,
                    "reasoning_content": "unretained reasoning",
                },
            }
        ],
        "usage": {
            "prompt_tokens": 80,
            "completion_tokens": 20,
            "prompt_cache_hit_tokens": 64,
            "prompt_cache_miss_tokens": 16,
        },
    }


def adapter(transport):
    return DeepSeekProviderAdapter(
        "test-credential",
        pricing={
            item.model: item.pricing for item in deepseek_candidates(available=True)
        },
        transport=transport,
    )


def test_deepseek_wire_reasoning_json_cache_cost_and_secret_boundary():
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
    assert result.evidence["usage"]["prompt_cache_hit_tokens"] == 64
    assert result.evidence["cost"]["amount"] == "0.000029184"
    assert "test-credential" not in json.dumps(result.evidence)
    assert "unretained reasoning" not in json.dumps(result.evidence)


@pytest.mark.parametrize(
    "status,expected",
    [(429, "retryable_failure"), (401, "final_failure"), (500, "unknown")],
)
def test_http_failures_are_sanitized_without_hidden_retries(status, expected):
    calls = []

    def transport(request, **kwargs):
        calls.append(request)
        raise HTTPError(
            request.full_url, status, "test-credential", {"Retry-After": "7"}, BytesIO()
        )

    result = adapter(transport).invoke(invocation())
    assert result.outcome == expected
    assert len(calls) == 1
    assert result.evidence["retry_after_seconds"] == 7
    assert "test-credential" not in json.dumps(result.evidence)


def test_timeout_is_ambiguous_and_requires_reconciliation():
    def transport(*args, **kwargs):
        raise TimeoutError("test-credential")

    result = adapter(transport).invoke(invocation())
    assert result.outcome == "unknown"
    assert result.evidence["manual_resolution_required"]


def test_invalid_output_retains_billable_usage_and_truncation_is_not_success():
    for content, finish in [
        ("not-json", "stop"),
        ('{"classification":"fiction"}', "length"),
    ]:
        result = adapter(
            lambda *args, **kwargs: BytesIO(
                json.dumps(response(content, finish)).encode()
            )
        ).invoke(invocation())
        assert result.outcome == "final_failure"
        assert result.evidence["usage"]["output_tokens"] == 20
        assert result.evidence["cost"]["amount"] != "0"


def test_changed_reasoning_cannot_bypass_admission():
    request = invocation()
    with pytest.raises(ValueError):
        adapter(lambda *args: pytest.fail("must not send")).invoke(
            replace(
                request,
                request_payload={**request.request_payload, "reasoning_effort": "max"},
            )
        )
