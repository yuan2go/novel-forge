from __future__ import annotations

from dataclasses import replace

import pytest

from novel_forge.modules.production_execution.provider_admission import (
    ProviderRequestEnvelope,
    TokenAccountingContract,
    prepare_provider_admission,
    verify_provider_admission,
)


def _contract(*, limit: int = 512) -> TokenAccountingContract:
    return TokenAccountingContract(
        provider="openai",
        model="gpt-test",
        route_identity="route:test:1",
        meter_identity="openai-byte-token-upper-bound",
        meter_version="v1",
        accounting_method="OPENAI_UTF8_BYTES_UPPER_BOUND_V1",
        precision="PROVEN_UPPER_BOUND",
        evidence_ref="token-proof:openai-byte-fallback:v1",
        serialization_contract="openai-responses-text-envelope-v1",
        model_context_limit=limit,
        output_reserve=64,
        safety_margin=32,
        framing_overhead=16,
    )


def _envelope(text: str = "hello") -> ProviderRequestEnvelope:
    return ProviderRequestEnvelope(
        provider="openai",
        model="gpt-test",
        protocol="openai-responses-text-envelope-v1",
        input_text=text,
        max_output_tokens=64,
        timeout_seconds=30,
        stable_idempotency_key="stable:1",
    )


def test_complete_admission_counts_exact_envelope_and_reserves_output() -> None:
    receipt = prepare_provider_admission(_envelope("x" * 100), _contract())

    assert receipt.status == "ADMITTED"
    assert receipt.precision == "PROVEN_UPPER_BOUND"
    assert receipt.component_usage["provider_input"] == 100
    assert receipt.component_usage["request_framing"] == 16
    assert receipt.total_reserved == 212
    assert receipt.envelope_hash == _envelope("x" * 100).envelope_hash


def test_context_can_fit_while_complete_provider_request_is_rejected() -> None:
    receipt = prepare_provider_admission(
        _envelope("x" * 100),
        _contract(limit=180),
        context_bundle_tokens=80,
    )

    assert receipt.context_bundle_status == "VALID"
    assert receipt.status == "REJECTED"
    assert receipt.reason == "PROVIDER_CONTEXT_LIMIT_EXCEEDED"


def test_unknown_meter_and_route_mismatch_fail_closed() -> None:
    unknown = replace(
        _contract(),
        accounting_method="CHARACTERS_DIVIDED_BY_FOUR",
        precision="UNPROVEN",
        evidence_ref="",
    )
    receipt = prepare_provider_admission(_envelope(), unknown)
    assert receipt.status == "REJECTED"
    assert receipt.reason == "TOKEN_ACCOUNTING_UNPROVEN"

    mismatch = replace(_contract(), model="other-model")
    receipt = prepare_provider_admission(_envelope(), mismatch)
    assert receipt.status == "REJECTED"
    assert receipt.reason == "TOKEN_ACCOUNTING_ROUTE_MISMATCH"


def test_serialization_drift_is_rejected_before_dispatch() -> None:
    envelope = _envelope("frozen")
    receipt = prepare_provider_admission(envelope, _contract())

    verify_provider_admission(envelope, receipt)
    with pytest.raises(ValueError, match="PROVIDER_REQUEST_IDENTITY_DRIFT"):
        verify_provider_admission(_envelope("changed"), receipt)
