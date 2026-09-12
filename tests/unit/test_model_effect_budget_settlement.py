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
from novel_forge.modules.command_kernel.worker_execution import (
    WorkerFailureClass,
    WorkerFailureClassifier,
)


def _result(*, cost: dict[str, object], input_tokens: int = 1200) -> ModelProviderResult:
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
        _result(
            cost={"amount": "0", "currency": "USD", "source": "not_provided"}
        ),
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
                "measurement": "ESTIMATED",
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


def test_failed_provider_ambiguous_submission_holds_reservation() -> None:
    decision = _model_failed_provider_budget_decision(
        dispatched={
            "outcome": "retryable_failure",
            "provider_evidence": {
                "production_execution": {
                    "process_evidence": {
                        "submission_phase": "PROVIDER_OUTCOME_UNKNOWN",
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
        lambda *_a, **_kw: {"source": "REQUEST", "estimated_total_tokens": 10_000},
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
    assert WorkerFailureClassifier.classify(raised.value) == WorkerFailureClass.RETRYABLE
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
