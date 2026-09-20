from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


_RESULT_RECORDED_PHASES = frozenset(
    {"PROVIDER_RESULT_RECORDED", "PROCESS_RESULT_RECORDED"}
)
_AMBIGUOUS_PHASES = frozenset(
    {
        "PROVIDER_INVOKING",
        "PROVIDER_OUTCOME_UNKNOWN",
        "PROCESS_STARTING",
        "PROCESS_OUTCOME_UNKNOWN",
    }
)


def failed_provider_submission_state(
    dispatched: Mapping[str, Any],
) -> str:

    outcome = str(dispatched.get("outcome") or "unknown").strip().lower()
    if outcome in {"unknown", "ambiguous"}:
        return "AMBIGUOUS"
    provider = dispatched.get("provider_evidence")
    provider = provider if isinstance(provider, Mapping) else {}
    production = provider.get("production_execution")
    process = (
        production.get("process_evidence") if isinstance(production, Mapping) else None
    )
    process = process if isinstance(process, Mapping) else {}
    declared = [
        value
        for value in (
            dispatched.get("request_sent"),
            provider.get("request_sent"),
            process.get("request_sent"),
        )
        if isinstance(value, bool)
    ]
    if declared and any(value != declared[0] for value in declared[1:]):
        return "AMBIGUOUS"
    phase = str(process.get("submission_phase") or "").strip().upper()
    measured = failed_provider_measurement(dispatched) is not None
    if declared:
        if declared[0]:
            return "AMBIGUOUS" if phase in _AMBIGUOUS_PHASES else "SENT"
        if measured or phase in (
            _RESULT_RECORDED_PHASES | _AMBIGUOUS_PHASES
        ):
            return "AMBIGUOUS"
        return "NOT_SENT"
    if any(
        str(value).strip().lower() in {"unknown", "not_established"}
        for value in (
            dispatched.get("request_sent"),
            provider.get("request_sent"),
            process.get("request_sent"),
        )
        if value is not None
    ):
        return "AMBIGUOUS"
    if phase in _AMBIGUOUS_PHASES:
        return "AMBIGUOUS"
    if measured or phase in _RESULT_RECORDED_PHASES:
        return "SENT"
    return "AMBIGUOUS"


def failed_provider_budget_decision(
    *,
    dispatched: Mapping[str, Any],
    reserved_amount: str | None,
    reserved_tokens: int,
    frozen_capability_profile: Mapping[str, Any],
) -> dict[str, Any]:
    submission_state = failed_provider_submission_state(dispatched)
    if submission_state == "NOT_SENT":
        return {"disposition": "RELEASE", "submission_state": submission_state}
    if submission_state == "AMBIGUOUS":
        return {
            "disposition": "HOLD_UNKNOWN",
            "submission_state": submission_state,
        }
    measurement = failed_provider_measurement(dispatched)
    usage_authoritative = bool(
        measurement is not None
        and frozen_capability_profile.get("supports_usage_receipt") is True
    )
    cost_authoritative = bool(
        measurement is not None
        and reserved_amount is not None
        and frozen_capability_profile.get("supports_cost_receipt") is True
        and measurement[1].get("provider_billed") is True
        and measurement[1].get("source") not in {"usage_pricing", "usage_pricing_upper_bound"}
    )
    usage_priced = bool(
        measurement is not None
        and usage_authoritative
        and reserved_amount is not None
        and frozen_capability_profile.get("supports_usage_pricing") is True
        and measurement[1].get("source") in {"usage_pricing", "usage_pricing_upper_bound"}
        and measurement[1].get("pricing_version")
        and measurement[1].get("pricing_snapshot")
    )
    legacy_pricing = bool(
        measurement is not None
        and usage_authoritative and reserved_amount is not None
        and frozen_capability_profile.get("supports_cost_receipt") is True
        and measurement[1].get("measurement") == "ESTIMATED"
        and measurement[1].get("pricing_ref") and measurement[1].get("pricing_snapshot_hash")
        and measurement[1].get("calculation_basis")
    )
    measurement_authoritative = usage_authoritative and (
        cost_authoritative or usage_priced or legacy_pricing or reserved_amount is None
    )
    if usage_authoritative:
        assert measurement is not None
        usage, _cost = measurement
        actual_tokens = int(usage.get("total_tokens") or 0) or int(
            usage.get("input_tokens") or 0
        ) + int(usage.get("output_tokens") or 0)
    else:
        actual_tokens = reserved_tokens
    if cost_authoritative or usage_priced or legacy_pricing:
        assert measurement is not None
        _usage, cost = measurement
        actual_amount: str | None = str(cost.get("amount") or "0")
    else:
        actual_amount = reserved_amount
    decision = {
        "disposition": "SETTLE",
        "submission_state": submission_state,
        "measurement_available": measurement_authoritative,
        "actual_amount": actual_amount,
        "actual_tokens": actual_tokens,
        "token_settlement_basis": (
            "PROVIDER_USAGE_RECEIPT" if usage_authoritative else "RESERVATION_CEILING"
        ),
        "cost_settlement_basis": (
            "PROVIDER_COST_RECEIPT"
            if cost_authoritative
            else "LEGACY_PRICING_ESTIMATE" if legacy_pricing
            else "FROZEN_USAGE_PRICING" if usage_priced
            else (
                "ACCOUNT_ENTITLEMENT_UNKNOWN"
                if reserved_amount is None
                else "RESERVATION_CEILING"
            )
        ),
    }
    if reserved_amount is None:
        decision.update(
            {"accounting_basis": "ACCOUNT_ENTITLEMENT", "cost_status": "UNKNOWN"}
        )
    return decision


def failed_provider_measurement(
    dispatched: Mapping[str, Any],
) -> tuple[Mapping[str, Any], Mapping[str, Any]] | None:
    provider = dispatched.get("provider_evidence")
    production = (
        provider.get("production_execution") if isinstance(provider, Mapping) else None
    )
    process = (
        production.get("process_evidence") if isinstance(production, Mapping) else None
    )
    usage = process.get("usage") if isinstance(process, Mapping) else None
    cost = process.get("cost") if isinstance(process, Mapping) else None
    if (
        not isinstance(usage, Mapping)
        or not isinstance(cost, Mapping)
        or str(usage.get("availability") or "").upper() != "AVAILABLE"
        or str(usage.get("measurement") or "").upper() not in {"MEASURED", "PROVIDER_REPORTED"}
        or str(cost.get("availability") or "").upper() != "AVAILABLE"
    ):
        return None
    token_values: list[int] = []
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        value = usage.get(key)
        if value is None or value == "":
            token_values.append(0)
            continue
        if isinstance(value, bool):
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        if parsed < 0:
            return None
        token_values.append(parsed)
    measured_tokens = max(token_values[2], token_values[0] + token_values[1])
    if measured_tokens <= 0:
        return None
    try:
        measured_amount = Decimal(str(cost.get("amount") or ""))
    except (InvalidOperation, ValueError):
        return None
    if not measured_amount.is_finite() or measured_amount < 0:
        return None
    return {**dict(usage), "total_tokens": measured_tokens}, cost
