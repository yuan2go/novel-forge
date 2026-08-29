from __future__ import annotations

from types import SimpleNamespace
from dataclasses import replace

import pytest

from novel_forge.modules.command_kernel.external_effect_adapters import (
    ExternalEffectAdapterError,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_runtime import (
    _validated_frozen_provider_capability_profile,
)
from novel_forge.modules.source_import.execution import _SourceGatewayEffectAdapter
from novel_forge.modules.story_planning_runtime.execution import (
    _PlanningGatewayEffectAdapter,
    _planning_budget_capability_profile,
    _planning_budget_settlement,
    _planning_failed_provider_budget_decision,
)
from novel_forge.modules.provider_control.contracts import (
    ProviderCapabilityProfile,
    ProviderControlLevel,
)


class _UnknownAfterSendSession:
    def __init__(self, submission_phase: str) -> None:
        self.submission_phase = submission_phase
        self.gateway = SimpleNamespace(submit=self._submit)
        self.evidence_store = SimpleNamespace(find_record=self._find_record)

    @staticmethod
    def _submit(_request: object) -> object:
        raise RuntimeError("transport response lost after Provider invocation")

    def _find_record(self, _execution_id: str) -> object:
        return SimpleNamespace(raw_evidence={"submission_phase": self.submission_phase})


def _request() -> SimpleNamespace:
    return SimpleNamespace(
        stable_idempotency_key="provider-key",
        capability="model.fixture",
        external_effect_id="effect:1",
        execution_id="execution:1",
        project_id="project:1",
    )


def _profile() -> ProviderCapabilityProfile:
    return ProviderCapabilityProfile(
        provider="production_execution_gateway",
        control_level=ProviderControlLevel.FIXTURE_CONTROLLED,
        supports_request_timeout=True,
        supports_provider_idempotency=True,
        supports_query=True,
        supports_cancel=True,
        supports_callback=False,
        supports_usage_receipt=True,
        supports_cost_receipt=True,
        reconciliation_mode="query",
        real_provider_validation_eligible=False,
    )


def _assert_unknown_after_send(adapter: object) -> None:
    with pytest.raises(ExternalEffectAdapterError) as raised:
        adapter.execute(  # type: ignore[attr-defined]
            stable_idempotency_key="provider-key",
            capability="model.fixture",
            request_payload={"external_effect_id": "effect:1"},
        )
    assert raised.value.request_sent is True


@pytest.mark.parametrize(
    "submission_phase",
    [
        "PROVIDER_INVOKING",
        "PROVIDER_OUTCOME_UNKNOWN",
        "PROVIDER_RESULT_RECORDED",
        "PROCESS_STARTING",
        "PROCESS_OUTCOME_UNKNOWN",
        "PROCESS_RESULT_RECORDED",
    ],
)
def test_planning_gateway_uses_durable_submission_phase_after_lost_response(
    submission_phase: str,
) -> None:
    session = _UnknownAfterSendSession(submission_phase)
    transport = SimpleNamespace(
        provider="provider",
        reconciliation_mode="query",
        capability_profile=SimpleNamespace(),
    )
    adapter = _PlanningGatewayEffectAdapter(
        transport=transport,
        session=session,
        binding=SimpleNamespace(request=_request()),
    )

    _assert_unknown_after_send(adapter)


@pytest.mark.parametrize(
    "submission_phase",
    [
        "PROVIDER_INVOKING",
        "PROVIDER_OUTCOME_UNKNOWN",
        "PROVIDER_RESULT_RECORDED",
        "PROCESS_STARTING",
        "PROCESS_OUTCOME_UNKNOWN",
        "PROCESS_RESULT_RECORDED",
    ],
)
def test_source_gateway_uses_durable_submission_phase_after_lost_response(
    submission_phase: str,
) -> None:
    session = _UnknownAfterSendSession(submission_phase)

    class _Transport:
        provider = "provider"
        reconciliation_mode = "query"
        capability_profile = SimpleNamespace()

        @staticmethod
        def session_for_project(_project_id: str) -> _UnknownAfterSendSession:
            return session

    adapter = _SourceGatewayEffectAdapter(
        transport=_Transport(),  # type: ignore[arg-type]
        binding=SimpleNamespace(request=_request()),
    )

    _assert_unknown_after_send(adapter)


def test_planning_budget_uses_measured_tokens_and_reserved_cost_without_receipt(
) -> None:
    settlement = _planning_budget_settlement(
        usage={"input_tokens": 120, "output_tokens": 30},
        cost={"amount": "0", "currency": "USD", "source": "not_provided"},
        fixture=False,
        supports_usage_receipt=True,
        supports_cost_receipt=False,
        reserved_amount="2",
        reserved_tokens=100_000,
    )

    assert settlement["total_tokens"] == 150
    assert settlement["usage_basis"] == "PROVIDER_USAGE_RECEIPT"
    assert settlement["amount"] == "2"
    assert settlement["cost_basis"] == "RESERVATION_CEILING"


def test_planning_budget_falls_back_to_reservation_for_missing_usage() -> None:
    settlement = _planning_budget_settlement(
        usage={"input_tokens": 0, "output_tokens": 0},
        cost={"amount": "0", "currency": "USD"},
        fixture=False,
        supports_usage_receipt=True,
        supports_cost_receipt=True,
        reserved_amount="2",
        reserved_tokens=100_000,
    )

    assert settlement["total_tokens"] == 100_000
    assert settlement["usage_basis"] == "RESERVATION_CEILING"
    assert settlement["amount"] == "2"
    assert settlement["cost_basis"] == "RESERVATION_CEILING"


def test_planning_scripted_fixture_preserves_authoritative_zero_usage() -> None:
    settlement = _planning_budget_settlement(
        usage={"input_tokens": 0, "output_tokens": 0},
        cost={"amount": "0", "currency": "USD"},
        fixture=True,
        supports_usage_receipt=True,
        supports_cost_receipt=True,
        reserved_amount="2",
        reserved_tokens=100_000,
    )

    assert settlement["total_tokens"] == 0
    assert settlement["usage_basis"] == "FIXTURE_RECEIPT"
    assert settlement["amount"] == "0"
    assert settlement["cost_basis"] == "FIXTURE_RECEIPT"


@pytest.mark.parametrize(
    ("dispatched", "expected_disposition"),
    [
        (
            {
                "outcome": "retryable_failure",
                "provider_evidence": {
                    "request_sent": False,
                    "production_execution": {
                        "process_evidence": {
                            "submission_phase": "PROVIDER_RESULT_RECORDED"
                        }
                    },
                },
            },
            "RELEASE",
        ),
        (
            {
                "outcome": "unknown",
                "provider_evidence": {"request_sent": True},
            },
            "HOLD_UNKNOWN",
        ),
        (
            {
                "outcome": "final_failure",
                "provider_evidence": {
                    "production_execution": {
                        "process_evidence": {
                            "submission_phase": "PROVIDER_OUTCOME_UNKNOWN"
                        }
                    }
                },
            },
            "HOLD_UNKNOWN",
        ),
    ],
)
def test_planning_failed_provider_budget_fail_closed_submission_triage(
    dispatched: dict[str, object], expected_disposition: str
) -> None:
    decision = _planning_failed_provider_budget_decision(
        dispatched=dispatched,
        capability_profile=_profile(),
        reserved_amount="2",
        reserved_tokens=100_000,
    )

    assert decision["disposition"] == expected_disposition


def test_planning_failed_sent_provider_uses_trusted_measurement() -> None:
    decision = _planning_failed_provider_budget_decision(
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
                            "currency": "USD",
                        },
                    }
                },
            },
        },
        capability_profile=_profile(),
        reserved_amount="2",
        reserved_tokens=100_000,
    )

    assert decision["disposition"] == "SETTLE"
    assert decision["measurement_available"] is True
    assert decision["settlement"]["total_tokens"] == 15
    assert decision["settlement"]["amount"] == "0.4"
    assert decision["settlement"]["usage_basis"] == "PROVIDER_USAGE_RECEIPT"
    assert decision["settlement"]["cost_basis"] == "PROVIDER_COST_RECEIPT"


def test_planning_failed_sent_provider_without_measurement_spends_ceiling() -> None:
    decision = _planning_failed_provider_budget_decision(
        dispatched={
            "outcome": "final_failure",
            "provider_evidence": {
                "production_execution": {
                    "process_evidence": {
                        "submission_phase": "PROCESS_RESULT_RECORDED"
                    }
                }
            },
        },
        capability_profile=_profile(),
        reserved_amount="2",
        reserved_tokens=100_000,
    )

    assert decision["disposition"] == "SETTLE"
    assert decision["measurement_available"] is False
    assert decision["settlement"]["total_tokens"] == 100_000
    assert decision["settlement"]["amount"] == "2"
    assert decision["settlement"]["usage_basis"] == "RESERVATION_CEILING"
    assert decision["settlement"]["cost_basis"] == "RESERVATION_CEILING"


def test_planning_replay_uses_first_send_capability_after_profile_drift() -> None:
    frozen = _profile()
    current = replace(
        frozen,
        supports_usage_receipt=False,
        supports_cost_receipt=False,
    )
    adapter = SimpleNamespace(
        provider=frozen.provider,
        capability_profile=current,
    )

    selected = _planning_budget_capability_profile(
        adapter=adapter,  # type: ignore[arg-type]
        recovered_completion={
            "provider_capability_profile": frozen.to_dict(),
        },
    )

    assert selected.supports_usage_receipt is True
    assert selected.supports_cost_receipt is True


def test_succeeded_effect_frozen_capability_profile_is_validated() -> None:
    frozen = _profile()

    validated = _validated_frozen_provider_capability_profile(
        {
            "provider": frozen.provider,
            "reconciliation_mode": frozen.reconciliation_mode,
            "provider_capability_profile": frozen.to_dict(),
        }
    )

    assert validated == frozen.to_dict()


def test_succeeded_effect_without_frozen_capability_fails_closed() -> None:
    with pytest.raises(KernelError) as raised:
        _validated_frozen_provider_capability_profile(
            {
                "provider": "production_execution_gateway",
                "reconciliation_mode": "query",
                "provider_capability_profile": {},
            }
        )

    assert raised.value.code == "EFFECT_PROVIDER_CAPABILITY_MISSING"
