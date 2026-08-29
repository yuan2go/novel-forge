from __future__ import annotations

from novel_forge.modules.chapter_authority.model_effects import (
    ModelProviderResult,
    _model_failed_provider_budget_decision,
    _model_budget_settlement,
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
