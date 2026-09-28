from dataclasses import replace
import hashlib
from io import BytesIO
import json

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.chapter_authority.provider_output_contracts import (
    validate_chapter_provider_output_against_schema,
)
from novel_forge.modules.production_execution.provider_admission import (
    DEEPSEEK_OUTPUT_TOOL,
    DEEPSEEK_STRICT_PROTOCOL,
    ProviderAdmissionReceipt,
    ProviderRequestEnvelope,
    TokenAccountingContract,
    deepseek_strict_tools,
    prepare_provider_admission,
    provider_request_protocol,
    verify_provider_admission,
)
from tests.unit.test_deepseek_provider import adapter, invocation, response
from tests.unit.test_provider_token_admission import COMPLETE_COVERAGE


SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"classification": {"type": "string", "minLength": 1}},
    "required": ["classification"],
    "additionalProperties": False,
}


def strict_invocation():
    request = invocation()
    envelope = replace(
        ProviderRequestEnvelope.from_dict(request.request_payload),
        protocol=DEEPSEEK_STRICT_PROTOCOL,
        output_schema_json=json.dumps(SCHEMA),
    )
    contract = replace(
        TokenAccountingContract.from_dict(
            request.provider_admission["accounting_contract"]
        ),
        serialization_contract=envelope.protocol,
    )
    receipt = prepare_provider_admission(
        envelope, contract, complete_request_coverage=COMPLETE_COVERAGE
    )
    assert receipt.status == "ADMITTED"
    return replace(
        request,
        request_payload=envelope.to_dict(),
        request_hash=envelope.envelope_hash,
        provider_admission=receipt.to_dict(),
    )


def tool_response(arguments='{"classification":"fiction"}'):
    value = response(content=None, finish="tool_calls")
    value["choices"][0]["message"]["tool_calls"] = [
        {
            "id": "tool-1",
            "type": "function",
            "function": {"name": DEEPSEEK_OUTPUT_TOOL, "arguments": arguments},
        }
    ]
    return value


def test_strict_tool_is_explicit_and_identity_bound_without_changing_old_envelopes():
    old = ProviderRequestEnvelope.from_dict(invocation().request_payload)
    assert "output_schema_json" not in old.to_dict()
    assert "output_schema_json" not in old.to_identity_dict()
    request = strict_invocation()
    frozen = ProviderRequestEnvelope.from_dict(request.request_payload)
    assert (
        ProviderRequestEnvelope.from_identity_dict(
            frozen.to_identity_dict(), input_text=frozen.input_text
        )
        == frozen
    )
    changed = replace(
        frozen, output_schema_json=json.dumps({**SCHEMA, "description": "changed"})
    )
    assert changed.envelope_hash != frozen.envelope_hash
    with pytest.raises(ValueError):
        verify_provider_admission(
            changed, ProviderAdmissionReceipt.from_dict(request.provider_admission)
        )
    assert provider_request_protocol("deepseek") == old.protocol
    assert (
        provider_request_protocol("deepseek", output_mode="STRICT_TOOL_V1")
        == frozen.protocol
    )


def test_strict_schema_is_metered_and_over_capacity_is_rejected():
    request = strict_invocation()
    envelope = ProviderRequestEnvelope.from_dict(request.request_payload)
    components = request.provider_admission["component_usage"]
    assert components["structured_output_transport"] > len(
        envelope.output_schema_json.encode()
    )
    contract = TokenAccountingContract.from_dict(
        request.provider_admission["accounting_contract"]
    )
    previous_total = (
        sum(components.values()) - components["structured_output_transport"]
    )
    receipt = prepare_provider_admission(
        envelope,
        replace(contract, execution_token_limit=previous_total),
        complete_request_coverage=COMPLETE_COVERAGE,
    )
    assert receipt.status == "REJECTED"
    assert receipt.reason == "EXECUTION_TOKEN_LIMIT_EXCEEDED"


def test_strict_wire_keeps_reasoning_and_accepts_exact_single_function_arguments():
    captured = []

    def transport(req, **kwargs):
        captured.append((req.full_url, json.loads(req.data)))
        return BytesIO(json.dumps(tool_response()).encode())

    result = adapter(transport).invoke(strict_invocation())
    assert result.outcome == "success"
    url, wire = captured[0]
    assert url == "https://api.deepseek.com/beta/chat/completions"
    assert wire["thinking"] == {"type": "enabled"} and wire["reasoning_effort"] == "low"
    assert "tool_choice" not in wire and "response_format" not in wire
    assert wire["tools"][0]["function"]["strict"] is True
    assert result.evidence["result"] == {"classification": "fiction"}
    assert result.evidence["output_protocol"] == DEEPSEEK_STRICT_PROTOCOL
    raw = result.evidence["structured_output"]
    assert raw["text"] == '{"classification":"fiction"}'
    assert raw["sha256"] == result.evidence["output_text_sha256"]
    assert raw["domain_validation"] == "PENDING"
    assert "unretained reasoning" not in json.dumps(result.evidence)


@pytest.mark.parametrize(
    "variant", ["plain_content", "multiple", "wrong_name", "invalid_json"]
)
def test_strict_output_failures_keep_usage_and_do_not_fallback_to_message_json(variant):
    value = tool_response()
    message = value["choices"][0]["message"]
    if variant == "plain_content":
        value = response()
    elif variant == "multiple":
        message["tool_calls"] *= 2
    elif variant == "wrong_name":
        message["tool_calls"][0]["function"]["name"] = "other_tool"
    else:
        message["tool_calls"][0]["function"]["arguments"] = (
            '{"classification":"fiction"'
        )
    result = adapter(lambda *a, **k: BytesIO(json.dumps(value).encode())).invoke(
        strict_invocation()
    )
    assert result.outcome == "final_failure"
    assert result.evidence["usage"]["total_tokens"] == 100
    assert result.evidence["cost"]["amount"] == "0.000014592"
    rejected = result.evidence["rejected_output"]
    assert rejected["accepted"] is False
    assert (
        rejected["sha256"]
        == "sha256:" + hashlib.sha256(rejected["text"].encode()).hexdigest()
    )


def test_transport_subset_does_not_relax_native_business_schema():
    frozen = json.dumps(SCHEMA)
    projected = deepseek_strict_tools(frozen)[0]["function"]["parameters"]
    assert "minLength" not in projected["properties"]["classification"]
    assert json.loads(frozen)["properties"]["classification"]["minLength"] == 1
    with pytest.raises(KernelError, match=r"classification must contain at least 1 characters"):
        validate_chapter_provider_output_against_schema(
            "test", SCHEMA, {"classification": ""}
        )


@pytest.mark.parametrize(
    "schema",
    [
        {**SCHEMA, "additionalProperties": True},
        {**SCHEMA, "required": []},
        {**SCHEMA, "if": {"type": "object"}},
    ],
)
def test_unsupported_schema_is_rejected_before_transport(schema):
    with pytest.raises(ValueError):
        replace(
            ProviderRequestEnvelope.from_dict(invocation().request_payload),
            protocol=DEEPSEEK_STRICT_PROTOCOL,
            output_schema_json=json.dumps(schema),
        )
