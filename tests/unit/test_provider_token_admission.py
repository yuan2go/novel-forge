from __future__ import annotations

from dataclasses import replace

import pytest

from novel_forge.modules.production_execution.provider_admission import (
    ProviderRequestEnvelope,
    TokenAccountingContract,
    build_route_token_accounting_contract,
    prepare_provider_admission,
    verify_provider_admission,
)
from novel_forge.modules.source_import.analysis_profiles import (
    derive_corpus_sample_byte_limit,
)


COMPLETE_COVERAGE = (
    "system_runtime_instructions",
    "prompt_template",
    "skill_instructions",
    "tool_policy_and_schemas",
    "structured_output_schema",
    "context_bundle",
    "request_envelope_and_framing",
    "output_reserve",
    "safety_margin",
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
        execution_token_limit=limit,
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


def test_codex_cli_admission_bounds_visible_stdin_without_claiming_final_request():
    contract = build_route_token_accounting_contract(
        provider="codex-cli",
        model="gpt-5.6-sol",
        route_identity="route:codex:1",
        accounting_method="CODEX_CLI_APPLICATION_UTF8_BYTES_UPPER_BOUND_V1",
        accounting_evidence_ref="contract:codex-visible-stdin:v1",
        model_context_limit=1_000_000,
        execution_token_limit=100_000,
        output_reserve=1_000,
        safety_margin=256,
        framing_overhead=16,
    )
    envelope = ProviderRequestEnvelope(
        provider="codex-cli",
        model="gpt-5.6-sol",
        protocol="codex-cli-application-stdin-v1",
        input_text="可见输入",
        max_output_tokens=1_000,
        timeout_seconds=300,
        stable_idempotency_key="codex:visible:1",
    )

    receipt = prepare_provider_admission(
        envelope,
        contract,
        complete_request_coverage=COMPLETE_COVERAGE,
    )

    assert receipt.status == "ADMITTED"
    assert receipt.reason == "ADMITTED_APPLICATION_VISIBLE_ONLY"
    assert receipt.precision == "APPLICATION_VISIBLE_UPPER_BOUND"
    assert receipt.accounting_contract["serialization_contract"] == (
        "codex-cli-application-stdin-v1"
    )
    verify_provider_admission(envelope, receipt)


def test_scripted_route_uses_its_effective_context_for_corpus_sampling() -> None:
    contract = build_route_token_accounting_contract(
        provider="scripted_provider_v2",
        model="scripted-fixture-v2",
        route_identity="route:scripted:source",
        accounting_method="",
        accounting_evidence_ref="",
        model_context_limit=0,
        output_reserve=4_096,
        safety_margin=256,
        framing_overhead=16,
    )

    assert contract.model_context_limit == 262_144
    assert derive_corpus_sample_byte_limit(
        model_context_limit=contract.model_context_limit,
        output_token_reserve=contract.output_reserve,
        token_safety_margin=contract.safety_margin,
        token_framing_overhead=contract.framing_overhead,
    ) == 225_776


def test_complete_admission_counts_exact_envelope_and_reserves_output() -> None:
    receipt = prepare_provider_admission(
        _envelope("x" * 100),
        _contract(),
        input_component_hashes={"context_bundle": "sha256:" + "a" * 64},
        complete_request_coverage=COMPLETE_COVERAGE,
    )

    assert receipt.status == "ADMITTED"
    assert receipt.precision == "PROVEN_UPPER_BOUND"
    assert receipt.component_usage["provider_input"] == 100
    assert receipt.component_usage["request_framing"] == 16
    assert receipt.total_reserved == 212
    assert receipt.envelope_hash == _envelope("x" * 100).envelope_hash
    assert receipt.input_component_hashes["context_bundle"].startswith("sha256:")
    assert "output_reserve" in receipt.complete_request_coverage


def test_exact_fit_and_output_reserve_can_cause_complete_request_overflow() -> None:
    exact = prepare_provider_admission(
        _envelope("x" * 100),
        _contract(limit=212),
        complete_request_coverage=COMPLETE_COVERAGE,
    )
    assert exact.status == "ADMITTED"

    reserve_overflow = replace(_contract(limit=212), output_reserve=128)
    envelope = replace(_envelope("x" * 100), max_output_tokens=128)
    receipt = prepare_provider_admission(
        envelope, reserve_overflow, complete_request_coverage=COMPLETE_COVERAGE
    )
    assert receipt.status == "REJECTED"
    assert receipt.reason == "PROVIDER_CONTEXT_LIMIT_EXCEEDED"


def test_context_can_fit_while_complete_provider_request_is_rejected() -> None:
    receipt = prepare_provider_admission(
        _envelope("x" * 100),
        _contract(limit=180),
        context_bundle_tokens=80,
        complete_request_coverage=COMPLETE_COVERAGE,
    )

    assert receipt.context_bundle_status == "VALID"
    assert receipt.status == "REJECTED"
    assert receipt.reason == "PROVIDER_CONTEXT_LIMIT_EXCEEDED"


def test_execution_policy_limit_is_part_of_provider_admission() -> None:
    receipt = prepare_provider_admission(
        _envelope("x" * 100),
        replace(_contract(limit=512), execution_token_limit=180),
        complete_request_coverage=COMPLETE_COVERAGE,
    )

    assert receipt.status == "REJECTED"
    assert receipt.reason == "EXECUTION_TOKEN_LIMIT_EXCEEDED"
    assert receipt.applicable_limit == 180


def test_v2_admission_rejects_incomplete_request_coverage() -> None:
    receipt = prepare_provider_admission(
        _envelope(),
        _contract(),
        complete_request_coverage=("context_bundle", "output_reserve"),
    )

    assert receipt.status == "REJECTED"
    assert receipt.reason == "PROVIDER_REQUEST_COVERAGE_INCOMPLETE"


def test_unknown_meter_and_route_mismatch_fail_closed() -> None:
    unknown = replace(
        _contract(),
        accounting_method="CHARACTERS_DIVIDED_BY_FOUR",
        precision="UNPROVEN",
        evidence_ref="",
    )
    receipt = prepare_provider_admission(
        _envelope(), unknown, complete_request_coverage=COMPLETE_COVERAGE
    )
    assert receipt.status == "REJECTED"
    assert receipt.reason == "TOKEN_ACCOUNTING_UNPROVEN"

    mismatch = replace(_contract(), model="other-model")
    receipt = prepare_provider_admission(
        _envelope(), mismatch, complete_request_coverage=COMPLETE_COVERAGE
    )
    assert receipt.status == "REJECTED"
    assert receipt.reason == "TOKEN_ACCOUNTING_ROUTE_MISMATCH"


def test_fallback_route_requires_its_own_provider_model_accounting_contract() -> None:
    fallback = build_route_token_accounting_contract(
        provider="other-provider",
        model="fallback-model",
        route_identity="route:fallback:1",
        accounting_method="OPENAI_UTF8_BYTES_UPPER_BOUND_V1",
        accounting_evidence_ref="token-proof:openai-only:v1",
        model_context_limit=512,
        output_reserve=64,
        safety_margin=32,
        framing_overhead=16,
    )
    envelope = replace(
        _envelope(),
        provider="other-provider",
        model="fallback-model",
        protocol="unsupported-provider-envelope-v1",
    )

    receipt = prepare_provider_admission(
        envelope, fallback, complete_request_coverage=COMPLETE_COVERAGE
    )

    assert receipt.status == "REJECTED"
    assert receipt.reason == "TOKEN_ACCOUNTING_UNPROVEN"


def test_serialization_drift_is_rejected_before_dispatch() -> None:
    envelope = _envelope("frozen")
    receipt = prepare_provider_admission(
        envelope, _contract(), complete_request_coverage=COMPLETE_COVERAGE
    )

    verify_provider_admission(envelope, receipt)
    with pytest.raises(ValueError, match="PROVIDER_REQUEST_IDENTITY_DRIFT"):
        verify_provider_admission(_envelope("changed"), receipt)


def test_manifest_identity_excludes_prompt_body_but_reconstructs_exact_envelope() -> (
    None
):
    envelope = _envelope("sensitive governed prompt")
    identity = envelope.to_identity_dict()

    assert "input_text" not in identity
    assert (
        ProviderRequestEnvelope.from_identity_dict(
            identity, input_text="sensitive governed prompt"
        )
        == envelope
    )
    with pytest.raises(ValueError, match="PROVIDER_REQUEST_IDENTITY_DRIFT"):
        ProviderRequestEnvelope.from_identity_dict(identity, input_text="changed")
