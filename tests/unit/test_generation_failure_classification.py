import json

import pytest

from novel_forge.modules.production_execution.provider_protocol_failure import (
    observed_provider_failure,
    codex_completed_turn,
)
from novel_forge.modules.production_execution.backends import parse_codex_jsonl_evidence
from novel_forge.modules.story_planning_runtime.execution import (
    _planning_budget_settlement,
)
from tests.unit.test_codex_execution_evidence import _entitlement


@pytest.mark.parametrize(
    "message,code,phase",
    [
        (
            "stream disconnected before completion: error decoding response body",
            "PROVIDER_STREAM_INTERRUPTED",
            "RESPONSE_STREAM",
        ),
        ("401 unauthorized", "PROVIDER_AUTH_FAILED", "AUTHENTICATION"),
        ("429 too many requests", "PROVIDER_RATE_LIMITED", "PROVIDER_ADMISSION"),
        (
            "failed to connect: connection refused",
            "PROVIDER_CONNECTION_FAILED",
            "CONNECTION",
        ),
        ("503 service unavailable", "PROVIDER_UNAVAILABLE", "PROVIDER_ADMISSION"),
    ],
)
def test_observed_failures_keep_cause_and_recovery_boundary(message, code, phase):
    failure = observed_provider_failure(
        json.dumps({"type": "turn.failed", "error": {"message": message}}),
        status="FAILED",
    )
    assert failure["error_code"] == code
    assert failure["phase"] == phase
    assert failure["stage"] == phase
    if "error decoding response body" in message:
        assert failure["cause_code"] == "CODEX_RESPONSE_BODY_DECODE_FAILED"
        assert failure["provider_error_code"] == "PROVIDER_STREAM_INTERRUPTED"
    assert failure["causes"][0]["message"] == message
    assert failure["recovery_action"] and failure["scope"] and failure["exit_condition"]
    assert failure["remote_outcome"] == "UNESTABLISHED"


@pytest.mark.parametrize(
    "status,code",
    [
        ("START_FAILED", "PROCESS_START_FAILURE"),
        ("TIMED_OUT", "PROVIDER_RESPONSE_TIMEOUT"),
        ("ORPHANED", "GENERATION_PARENT_EXITED"),
    ],
)
def test_supervisor_phase_has_its_own_code(status, code):
    assert observed_provider_failure("", status=status)["error_code"] == code


def test_completed_turn_without_usage_keeps_unknown_accounting_and_valid_tool_boundary():
    stdout = json.dumps({"type": "turn.completed"})
    assert codex_completed_turn(stdout)
    evidence = parse_codex_jsonl_evidence(
        stdout,
        model_id="codex-test",
        account_entitlement=_entitlement(),
        allowed_tools=("model.provider.invoke",),
    )
    assert evidence["usage"]["measurement"] == "UNKNOWN"
    assert evidence["usage"]["total_tokens"] is None
    assert evidence["cost"]["measurement"] == "UNKNOWN"
    assert evidence["terminal_event_observed"]
    assert evidence["unauthorized_tools"] == []
    settlement = _planning_budget_settlement(
        usage=evidence["usage"],
        cost=evidence["cost"],
        fixture=False,
        supports_usage_receipt=True,
        supports_cost_receipt=False,
        reserved_amount=None,
        reserved_tokens=1000,
    )
    assert settlement["usage"]["total_tokens"] is None
    assert settlement["usage"]["conservative_reserved_tokens"] == 1000
    assert settlement["usage_basis"] == "RESERVATION_CEILING"


def test_missing_terminal_cannot_be_disguised_as_missing_usage():
    stdout = json.dumps(
        {"type": "turn.failed", "error": {"message": "stream disconnected"}}
    )
    assert not codex_completed_turn(stdout)
    with pytest.raises(ValueError, match="no completed terminal turn"):
        parse_codex_jsonl_evidence(
            stdout,
            model_id="codex-test",
            account_entitlement=_entitlement(),
            allowed_tools=("model.provider.invoke",),
        )
