from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from novel_forge.modules.chapter_authority import model_effects
from novel_forge.modules.chapter_authority.contracts import ChapterHandlerRequest
from novel_forge.modules.chapter_authority.model_effects import (
    ExternalEffectChapterModelPort,
    ModelProviderResult,
    _model_failed_provider_budget_decision,
    _model_budget_settlement,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.agent_runtime.harness import canonical_execution_contract_hash
from novel_forge.modules.command_kernel.worker_execution import (
    WorkerFailureClass,
    WorkerFailureClassifier,
)


def _result(
    *, cost: dict[str, object], input_tokens: int = 1200
) -> ModelProviderResult:
    return ModelProviderResult(
        output={"accepted": True},
        provider_id="provider-v2",
        model_id="model-v1",
        prompt_version="prompt-v1",
        skill_version="skill-v1",
        input_tokens=input_tokens,
        output_tokens=300,
        cost_amount=str(cost.get("amount") or "0"),
        currency=str(cost.get("currency") or "USD"),
        real_model_call=True,
        usage_evidence={
            "availability": "AVAILABLE",
            "input_tokens": input_tokens,
            "output_tokens": 300,
        },
        cost_evidence=cost,
    )


def test_real_provider_without_cost_receipt_keeps_reservation_ceiling() -> None:
    amount, tokens, evidence = _model_budget_settlement(
        _result(cost={"amount": "0", "currency": "USD", "source": "not_provided"}),
        reserved_amount="2",
        reserved_tokens=100_000,
        frozen_capability_profile={
            "supports_usage_receipt": True,
            "supports_cost_receipt": False,
        },
    )

    assert amount == "2"
    assert tokens == 1500
    assert evidence == {
        "token_settlement_basis": "PROVIDER_USAGE_RECEIPT",
        "cost_settlement_basis": "RESERVATION_CEILING",
    }


def test_frozen_authoritative_cost_receipt_settles_measured_amount() -> None:
    amount, tokens, evidence = _model_budget_settlement(
        _result(
            cost={
                "availability": "AVAILABLE",
                "measurement": "PROVIDER_REPORTED",
                "provider_billed": True,
                "amount": "0.375",
                "currency": "USD",
                "pricing_snapshot_hash": "sha256:" + "a" * 64,
            }
        ),
        reserved_amount="2",
        reserved_tokens=100_000,
        frozen_capability_profile={
            "supports_usage_receipt": True,
            "supports_cost_receipt": True,
        },
    )

    assert amount == "0.375"
    assert tokens == 1500
    assert evidence == {
        "token_settlement_basis": "PROVIDER_USAGE_RECEIPT",
        "cost_settlement_basis": "PROVIDER_COST_RECEIPT",
    }


def test_missing_real_usage_keeps_token_reservation_ceiling() -> None:
    amount, tokens, evidence = _model_budget_settlement(
        _result(
            cost={"amount": "0", "currency": "USD", "source": "not_provided"},
            input_tokens=0,
        ),
        reserved_amount="2",
        reserved_tokens=100_000,
        frozen_capability_profile={
            "supports_usage_receipt": False,
            "supports_cost_receipt": False,
        },
    )

    assert amount == "2"
    assert tokens == 100_000
    assert evidence == {
        "token_settlement_basis": "RESERVATION_CEILING",
        "cost_settlement_basis": "RESERVATION_CEILING",
    }


def test_failed_sent_provider_without_measurement_spends_frozen_ceiling() -> None:
    decision = _model_failed_provider_budget_decision(
        dispatched={
            "outcome": "final_failure",
            "provider_evidence": {
                "production_execution": {
                    "process_evidence": {
                        "submission_phase": "PROCESS_RESULT_RECORDED",
                    }
                }
            },
        },
        reserved_amount="2",
        reserved_tokens=100_000,
        frozen_capability_profile={
            "supports_usage_receipt": True,
            "supports_cost_receipt": True,
        },
    )

    assert decision == {
        "disposition": "SETTLE",
        "submission_state": "SENT",
        "measurement_available": False,
        "actual_amount": "2",
        "actual_tokens": 100_000,
        "token_settlement_basis": "RESERVATION_CEILING",
        "cost_settlement_basis": "RESERVATION_CEILING",
    }


def test_failed_provider_proven_no_send_releases_reservation() -> None:
    decision = _model_failed_provider_budget_decision(
        dispatched={
            "outcome": "retryable_failure",
            "request_sent": False,
            "provider_evidence": {"request_sent": False},
        },
        reserved_amount="2",
        reserved_tokens=100_000,
        frozen_capability_profile={
            "supports_usage_receipt": True,
            "supports_cost_receipt": True,
        },
    )

    assert decision == {
        "disposition": "RELEASE",
        "submission_state": "NOT_SENT",
    }


@pytest.mark.parametrize("phase", ["PROVIDER_OUTCOME_UNKNOWN", "PROVIDER_RESULT_OBSERVED"])
def test_failed_provider_ambiguous_submission_holds_reservation(phase) -> None:
    decision = _model_failed_provider_budget_decision(
        dispatched={
            "outcome": "retryable_failure",
            "provider_evidence": {
                "production_execution": {
                    "process_evidence": {
                        "submission_phase": phase,
                    }
                }
            },
        },
        reserved_amount="2",
        reserved_tokens=100_000,
        frozen_capability_profile={
            "supports_usage_receipt": True,
            "supports_cost_receipt": True,
        },
    )

    assert decision == {
        "disposition": "HOLD_UNKNOWN",
        "submission_state": "AMBIGUOUS",
    }


def test_failed_sent_provider_invalid_measurement_spends_frozen_ceiling() -> None:
    decision = _model_failed_provider_budget_decision(
        dispatched={
            "outcome": "retryable_failure",
            "provider_evidence": {
                "request_sent": True,
                "production_execution": {
                    "process_evidence": {
                        "submission_phase": "PROVIDER_RESULT_RECORDED",
                        "usage": {
                            "availability": "AVAILABLE",
                            "measurement": "MEASURED",
                            "input_tokens": 12,
                            "output_tokens": 3,
                            "total_tokens": 15,
                        },
                        "cost": {
                            "availability": "AVAILABLE",
                            "amount": "NaN",
                        },
                    }
                },
            },
        },
        reserved_amount="2",
        reserved_tokens=100_000,
        frozen_capability_profile={
            "supports_usage_receipt": True,
            "supports_cost_receipt": True,
        },
    )

    assert decision["disposition"] == "SETTLE"
    assert decision["measurement_available"] is False
    assert decision["actual_amount"] == "2"
    assert decision["actual_tokens"] == 100_000


def test_failed_sent_provider_uses_authoritative_measurement() -> None:
    decision = _model_failed_provider_budget_decision(
        dispatched={
            "outcome": "retryable_failure",
            "provider_evidence": {
                "request_sent": True,
                "production_execution": {
                    "process_evidence": {
                        "submission_phase": "PROVIDER_RESULT_RECORDED",
                        "usage": {
                            "availability": "AVAILABLE",
                            "measurement": "MEASURED",
                            "input_tokens": 12,
                            "output_tokens": 3,
                            "total_tokens": 15,
                        },
                        "cost": {
                            "availability": "AVAILABLE",
                            "provider_billed": True,
                            "amount": "0.4",
                        },
                    }
                },
            },
        },
        reserved_amount="2",
        reserved_tokens=100_000,
        frozen_capability_profile={
            "supports_usage_receipt": True,
            "supports_cost_receipt": True,
        },
    )

    assert decision["disposition"] == "SETTLE"
    assert decision["measurement_available"] is True
    assert decision["actual_amount"] == "0.4"
    assert decision["actual_tokens"] == 15
    assert decision["token_settlement_basis"] == "PROVIDER_USAGE_RECEIPT"
    assert decision["cost_settlement_basis"] == "PROVIDER_COST_RECEIPT"


@pytest.mark.parametrize("completed_effect", [False, True], ids=["new", "replay"])
def test_successful_receipt_is_settled_before_retryable_retrieval_rejection(
    monkeypatch: pytest.MonkeyPatch, completed_effect: bool
) -> None:
    result = replace(
        _result(
            cost={
                "availability": "AVAILABLE",
                "provider_billed": True,
                "amount": "0.375",
                "currency": "USD",
            }
        ),
        output={
            "embedding_model": "wrong-model",
            "embedding_dimensions": 2,
            "vectors": [[1.0, 0.0]],
        },
        model_id="wrong-model",
    )
    adapter = SimpleNamespace(
        provider="provider-v2",
        reconciliation_mode="NONE",
        capability_profile={
            "supports_usage_receipt": False,
            "supports_cost_receipt": False,
        },
    )
    port = ExternalEffectChapterModelPort(
        "postgresql://unit-not-connected",
        adapter=adapter,
        worker_id="worker",
        max_cost_per_call="2",
    )
    request = ChapterHandlerRequest(
        operation_id="operation",
        project_id="project",
        workspace_id="workspace",
        trace_id="trace",
        correlation_id="correlation",
        command={"context_token_budget": 10_000},
        inputs=(),
        attempt_id="attempt",
        fencing_token=1,
        worker_id="worker",
    )
    monkeypatch.setattr(port, "_execution_identity", lambda *_a, **_kw: (1, "worker"))
    monkeypatch.setattr(port, "_request_timeout_seconds", lambda _request: 30)
    model_log = Mock()
    cost_log = Mock()
    monkeypatch.setattr(port, "_record_model_call", model_log)
    monkeypatch.setattr(port, "_ensure_cost_evidence", cost_log)
    monkeypatch.setattr(
        port,
        "completed_effect_result",
        lambda *_a: result if completed_effect else None,
    )
    monkeypatch.setattr(
        model_effects,
        "resolve_provider_token_reservation_contract",
        lambda *_a, **_kw: {"source": "REQUEST", "estimated_total_tokens": 10_000, "accounting_basis": "PRICED", "cost_authorization_ref": ""},
    )
    monkeypatch.setattr(
        model_effects, "read_external_effect_intent", lambda *_a, **_kw: None
    )
    monkeypatch.setattr(
        model_effects,
        "plan_external_effect",
        lambda *_a, **_kw: {
            "external_effect_id": "original-effect",
            "replayed": completed_effect,
            "provider_capability_profile": {
                "supports_usage_receipt": True,
                "supports_cost_receipt": True,
            },
        },
    )
    reserve = Mock(
        return_value={
            "reservation_id": "original-reservation",
            "execution_authorized": not completed_effect,
        }
    )
    dispatch = Mock(
        return_value={"outcome": "success", "provider_evidence": result.to_evidence()}
    )
    settle = Mock()
    monkeypatch.setattr(model_effects, "reserve_provider_budget", reserve)
    monkeypatch.setattr(model_effects, "dispatch_external_effect", dispatch)
    monkeypatch.setattr(model_effects, "settle_provider_budget", settle)
    cursor = Mock()
    cursor.fetchone.return_value = (
        {"embedding_model": "required-model", "embedding_dimensions": 2},
    )
    connection = SimpleNamespace(cursor=lambda: nullcontext(cursor))
    monkeypatch.setattr(
        model_effects,
        "get_database_runtime",
        lambda _url: SimpleNamespace(connection=lambda: nullcontext(connection)),
    )

    with pytest.raises(KernelError) as raised:
        port.invoke(request, stage="retrieval", payload={"texts": ["frozen query"]})

    assert raised.value.code == "RETRIEVAL_EMBEDDING_OUTPUT_IDENTITY_MISMATCH"
    assert (
        WorkerFailureClassifier.classify(raised.value) == WorkerFailureClass.RETRYABLE
    )
    assert cursor.execute.call_args.args[1] == ["project", "original-effect"]
    assert reserve.call_args.args[1].external_effect_id == "original-effect"
    assert dispatch.call_count == int(not completed_effect)
    settle.assert_called_once()
    settlement = settle.call_args.kwargs
    assert settlement["reservation_id"] == "original-reservation"
    assert settlement["project_id"] == "project"
    assert settlement["actual_amount"] == "0.375"
    assert settlement["actual_tokens"] == 1500
    assert settlement["evidence"]["token_settlement_basis"] == "PROVIDER_USAGE_RECEIPT"
    assert settlement["evidence"]["cost_settlement_basis"] == "PROVIDER_COST_RECEIPT"
    model_log.assert_called_once()
    cost_log.assert_called_once()
    assert model_log.call_args.kwargs["external_effect_id"] == "original-effect"
    assert cost_log.call_args.kwargs["external_effect_id"] == "original-effect"


def test_usage_pricing_never_becomes_a_provider_billed_receipt() -> None:
    cost = {
        "availability": "AVAILABLE",
        "source": "usage_pricing",
        "provider_billed": False,
        "measurement": "PRICED_FROM_PROVIDER_USAGE",
        "amount": "0.0007",
        "currency": "USD",
        "pricing_version": "price-v1",
        "pricing_snapshot": {"version": "price-v1"},
    }
    amount, tokens, evidence = _model_budget_settlement(
        _result(cost=cost),
        reserved_amount="2",
        reserved_tokens=100_000,
        frozen_capability_profile={
            "supports_usage_receipt": True,
            "supports_cost_receipt": True,
            "supports_usage_pricing": True,
        },
    )
    assert amount == "0.0007"
    assert tokens == 1500
    assert evidence["cost_settlement_basis"] == "FROZEN_USAGE_PRICING"
    from novel_forge.modules.story_planning_runtime.execution import (
        _planning_budget_settlement,
    )

    measured = _planning_budget_settlement(
        usage={"input_tokens": 1200, "output_tokens": 300, "total_tokens": 1500},
        cost=cost,
        reserved_amount="2",
        reserved_tokens=100_000,
        supports_usage_receipt=True,
        supports_cost_receipt=True,
        fixture=False,
    )
    assert measured["amount"] == "0.0007"
    assert measured["cost_basis"] == "FROZEN_USAGE_PRICING"
    failure = _model_failed_provider_budget_decision(
        dispatched={
            "outcome": "final_failure",
            "request_sent": True,
            "provider_evidence": {
                "production_execution": {
                    "process_evidence": {
                        "submission_phase": "PROVIDER_RESULT_RECORDED",
                        "usage": {
                            "availability": "AVAILABLE",
                            "measurement": "PROVIDER_REPORTED",
                            "input_tokens": 1200,
                            "output_tokens": 300,
                            "total_tokens": 1500,
                        },
                        "cost": cost,
                    }
                }
            },
        },
        reserved_amount="2",
        reserved_tokens=100_000,
        frozen_capability_profile={
            "supports_usage_receipt": True,
            "supports_cost_receipt": True,
            "supports_usage_pricing": True,
        },
    )
    assert failure["actual_amount"] == "0.0007"
    assert failure["cost_settlement_basis"] == "FROZEN_USAGE_PRICING"


def test_missing_billing_proof_cannot_release_a_monetary_reservation() -> None:
    from novel_forge.modules.source_import.execution import _source_budget_settlement
    from novel_forge.modules.story_planning_runtime.execution import (
        _planning_budget_settlement,
    )

    cost = {"availability": "AVAILABLE", "amount": "0.001"}
    usage = {
        "measurement": "PROVIDER_REPORTED",
        "input_tokens": 1200,
        "output_tokens": 300,
        "total_tokens": 1500,
    }
    capabilities = {"supports_usage_receipt": True, "supports_cost_receipt": True}
    amount, tokens, evidence = _model_budget_settlement(
        _result(cost=cost),
        reserved_amount="2",
        reserved_tokens=100_000,
        frozen_capability_profile=capabilities,
    )
    assert (amount, tokens, evidence["cost_settlement_basis"]) == (
        "2",
        1500,
        "RESERVATION_CEILING",
    )
    planning = _planning_budget_settlement(
        usage=usage,
        cost=cost,
        fixture=False,
        supports_usage_receipt=True,
        supports_cost_receipt=True,
        reserved_amount="2",
        reserved_tokens=100_000,
    )
    assert (planning["amount"], planning["cost_basis"]) == ("2", "RESERVATION_CEILING")
    source = _source_budget_settlement(
        usage=usage,
        cost=cost,
        fixture=False,
        capability_profile=capabilities,
        accounting_basis="PRICED",
        reserved_amount="2",
        reserved_tokens=100_000,
        provider_id="provider",
        model_id="model",
        real_model_call=True,
    )
    assert (source["amount"], source["cost_settlement_basis"]) == (
        "2",
        "RESERVATION_CEILING",
    )


@pytest.mark.parametrize("error_code,settlement_calls", [("RUNTIME_DISPATCH_PAUSED", 0), ("EFFECT_EXTERNAL_STATE_UNKNOWN", 1)])
def test_operator_pause_retains_frozen_reservation_without_reclassifying_unknown(monkeypatch, error_code, settlement_calls):
    adapter = SimpleNamespace(provider="provider-v2", reconciliation_mode="NONE", capability_profile={})
    port = ExternalEffectChapterModelPort("postgresql://unit-not-connected", adapter=adapter, worker_id="worker", max_cost_per_call="2")
    request = ChapterHandlerRequest(operation_id="operation", project_id="project", workspace_id="workspace", trace_id="trace",
        correlation_id="correlation", command={"context_token_budget": 10000}, inputs=(), attempt_id="attempt", fencing_token=1, worker_id="worker")
    monkeypatch.setattr(port, "_execution_identity", lambda *_a, **_kw: (1, "worker"))
    monkeypatch.setattr(port, "_request_timeout_seconds", lambda _request: 30)
    monkeypatch.setattr(port, "completed_effect_result", lambda *_a: None)
    monkeypatch.setattr(model_effects, "resolve_provider_token_reservation_contract", lambda *_a, **_kw: {"source": "REQUEST", "estimated_total_tokens": 10000, "accounting_basis": "PRICED", "cost_authorization_ref": ""})
    monkeypatch.setattr(model_effects, "read_external_effect_intent", lambda *_a, **_kw: None)
    monkeypatch.setattr(model_effects, "plan_external_effect", lambda *_a, **_kw: {"external_effect_id": "frozen-effect", "replayed": False})
    reserve = Mock(return_value={"reservation_id": "frozen-reservation", "execution_authorized": True})
    release = Mock()
    settle = Mock()
    monkeypatch.setattr(model_effects, "reserve_provider_budget", reserve)
    monkeypatch.setattr(model_effects, "resolve_provider_budget_failure", release)
    monkeypatch.setattr(model_effects, "settle_provider_budget", settle)
    monkeypatch.setattr(model_effects, "dispatch_external_effect", Mock(side_effect=KernelError(error_code, "controlled boundary")))
    with pytest.raises(KernelError, match=error_code):
        port.invoke(request, stage="retrieval", payload={"texts": ["frozen query"]})
    assert reserve.call_args.args[1].external_effect_id == "frozen-effect"
    assert release.call_count == settlement_calls
    settle.assert_not_called()


def test_agent_provider_input_and_output_limits_are_independently_frozen(monkeypatch):
    contract = {"contract_version": "agent-session-execution-contract.v1",
                "provider_io_policy": "agent-io-budget.v1",
                "budget": {"max_input_tokens": 16000, "max_output_tokens": 32000}}
    digest = canonical_execution_contract_hash(contract)
    request = ChapterHandlerRequest(operation_id="operation", project_id="project", workspace_id="workspace",
        trace_id="trace", correlation_id="correlation", command={"context_token_budget": 16000,
            "book_id": "book", "agent_session_id": "session", "agent_execution_contract": contract,
            "agent_execution_contract_hash": digest}, inputs=(), attempt_id="attempt", fencing_token=1, worker_id="worker")
    captured = {}
    def freeze(**values):
        captured.update(values["request_payload"])
        raise KernelError("CAPTURED_BEFORE_SEND", "Only inspect the frozen Provider request")
    adapter = SimpleNamespace(provider="provider", reconciliation_mode="NONE", capability_profile={},
                              routes={"agent_session": SimpleNamespace(model_context_limit=258400)})
    port = ExternalEffectChapterModelPort("postgresql://unit-not-connected", adapter=adapter, worker_id="worker",
        max_cost_per_call="2", capability_binder=SimpleNamespace(freeze_before_external_effect=freeze))
    monkeypatch.setattr(port, "_execution_identity", lambda *_a, **_kw: (1, "worker"))
    monkeypatch.setattr(port, "_request_timeout_seconds", lambda _request: 30)
    monkeypatch.setattr(model_effects, "read_external_effect_intent", lambda *_a, **_kw: None)
    reservation = Mock(return_value={"source": "FROZEN_REQUEST_INPUT_PLUS_OUTPUT_CEILING",
        "estimated_total_tokens": 48000, "input_token_ceiling": 16000, "max_output_tokens": 32000})
    monkeypatch.setattr(model_effects, "resolve_provider_token_reservation_contract", reservation)
    with pytest.raises(KernelError, match="CAPTURED_BEFORE_SEND"):
        port.invoke(request, stage="agent_session", payload={"execution_contract_hash": digest,
            "execution_contract_summary": {"budget": contract["budget"]}},
            reservation_tokens=16000, provider_output_tokens=32000)
    assert captured["max_output_tokens"] == 32000
    assert captured["_production_execution"]["provider_token_limit"] == 48000
    assert captured["_production_execution"]["agent_io_budget"]["execution_contract_hash"] == digest
    assert reservation.call_args.kwargs["frozen_request_token_ceiling"] == 16000
    assert reservation.call_args.kwargs["requested_output_token_ceiling"] == 32000
    with pytest.raises(KernelError, match="AGENT_EXECUTION_IO_BUDGET_DRIFT"):
        port.invoke(request, stage="agent_session", payload={"execution_contract_hash": digest,
            "execution_contract_summary": {"budget": contract["budget"]}},
            reservation_tokens=16000, provider_output_tokens=32001)
    with pytest.raises(KernelError, match="AGENT_EXECUTION_IO_BUDGET_DRIFT"):
        port.invoke(request, stage="agent_session", payload={"execution_contract_hash": digest,
            "execution_contract_summary": {"budget": contract["budget"]}}, reservation_tokens=16000)
    legacy_contract = {k:v for k,v in contract.items() if k != "provider_io_policy"}
    legacy_hash = canonical_execution_contract_hash(legacy_contract)
    legacy_payload = {"execution_contract_hash": legacy_hash,
                      "execution_contract_summary": {"budget": legacy_contract["budget"]}}
    legacy_request = replace(request, command={**request.command, "agent_execution_contract": legacy_contract,
                                               "agent_execution_contract_hash": legacy_hash})
    with pytest.raises(KernelError, match="AGENT_EXECUTION_IO_BUDGET_DRIFT"):
        port.invoke(legacy_request, stage="agent_session", payload=legacy_payload,
                    reservation_tokens=16000, provider_output_tokens=32000)
    from copy import deepcopy
    legacy_intent = deepcopy(captured)
    legacy_intent.update(max_output_tokens=16000, input=legacy_payload)
    legacy_intent["_production_execution"].pop("agent_io_budget")
    legacy_intent["_production_execution"].update(agent_execution_contract=legacy_contract,
        agent_execution_contract_hash=legacy_hash, provider_token_limit=258400,
        provider_reservation_policy={"source": "FROZEN_REQUEST_INPUT_PLUS_OUTPUT_CEILING",
            "estimated_total_tokens": 32000, "input_token_ceiling": 16000, "max_output_tokens": 16000,
            "accounting_basis": "PRICED", "cost_authorization_ref": ""})
    monkeypatch.setattr(model_effects, "read_external_effect_intent", lambda *_a, **_kw: {
        "request_payload": legacy_intent, "provider": adapter.provider,
        "capability": "model.agent_session", "max_attempts": 2, "provider_capability_profile": {}})
    replay = {}
    def capture_replay(_database, _context, **values):
        replay.update(values["request_payload"])
        raise KernelError("CAPTURED_LEGACY_REPLAY", "Do not send")
    monkeypatch.setattr(model_effects, "plan_external_effect", capture_replay)
    with pytest.raises(KernelError, match="CAPTURED_LEGACY_REPLAY"):
        port.invoke(legacy_request, stage="agent_session", payload=legacy_payload, reservation_tokens=16000)
    assert replay == legacy_intent
    assert replay["max_output_tokens"] == 16000
