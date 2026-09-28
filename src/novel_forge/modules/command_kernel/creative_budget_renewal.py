from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from .errors import KernelError


def _reject(message: str) -> None:
    raise KernelError("CREATIVE_BUDGET_RENEWAL_INVALID", message)


def usage_allocation(usage: dict[str, Any]) -> dict[str, Any]:
    return {"calls": usage["calls_used_or_reserved"], "tokens": usage["conservative_tokens"],
            "priced_usd": str(usage["priced_usd"])}


def carry_forward_usage(usage: dict[str, Any]) -> dict[str, Any]:
    return {"reservation_ids": list(usage["reservation_ids"]),
            "shared_total": usage_allocation(usage["shared_total"]),
            "phases": {phase: usage_allocation(value) for phase, value in usage["phases"].items()},
            "entitlements": deepcopy(usage["entitlements"])}


def validate_renewal_contract(plan: dict[str, Any]) -> None:
    from .creative_budget_contract import PROVIDER_CAMPAIGN_PHASES, _object, _monetary_allocation
    renewal = _object(plan["renewal"], "renewal", {"authorized_at", "additional_total", "carry_forward"})
    try:
        authorized = datetime.fromisoformat(renewal["authorized_at"])
        expiry = datetime.fromisoformat(plan["expires_at"])
        if authorized.tzinfo is None or not authorized < expiry:
            raise ValueError("invalid authorization window")
    except (TypeError, ValueError) as exc:
        raise KernelError("CREATIVE_BUDGET_RENEWAL_INVALID", "Renewal requires its original timezone-aware authorization window") from exc
    if "previous_policy" not in plan:
        _reject("Renewal requires the exact previous native policy")
    extra = _monetary_allocation(renewal["additional_total"], "additional_total")
    if not extra["calls"] or not extra["tokens"]:
        _reject("Renewal requires a positive finite call and token allowance")
    basis = _object(renewal["carry_forward"], "carry_forward", {"reservation_ids", "shared_total", "phases", "entitlements"})
    ids = basis["reservation_ids"]
    if not isinstance(ids, list) or any(not isinstance(value, str) or not value for value in ids) or len(set(ids)) != len(ids):
        _reject("Carry-forward reservation identities must be unique")
    phases = _object(basis["phases"], "carry_forward phases", set(PROVIDER_CAMPAIGN_PHASES))
    for name, value in [("total", basis["shared_total"]), *phases.items()]:
        _monetary_allocation(value, "carry_forward " + name, paired=False)
    if basis["shared_total"]["calls"] != len(ids):
        _reject("Carry-forward calls must match their accounted reservations")
    arm = plan["arms"][0]
    for key in extra:
        historical = Decimal(str(basis["shared_total"][key]))
        if historical != sum(Decimal(str(row[key])) for row in phases.values()):
            _reject("Carry-forward phases must sum to their total")
        if Decimal(str(plan["shared_total"][key])) != historical + Decimal(str(extra[key])):
            _reject("Renewal cumulative ceiling must equal historical usage plus explicit new allowance")
        for phase, used in phases.items():
            cap = Decimal(str(arm[phase.lower() + "_allocation"][key]))
            floor = Decimal(str(used[key]))
            if cap < floor or phase not in {"DESIGN", "PRODUCTION", "REPAIR"} and cap != floor:
                _reject("Renewal may add only design, production and repair allowance; historical usage stays accounted")
    lanes = {(lane["provider"], lane["authorization_ref"]): lane for lane in plan["entitlements"]}
    historical_lanes = basis["entitlements"]
    if not isinstance(historical_lanes, list):
        _reject("Carry-forward entitlement lanes must be explicit")
    identities = set()
    for lane in historical_lanes:
        lane = _object(lane, "carry_forward entitlement", {"provider", "authorization_ref", "calls", "tokens"})
        key = (lane["provider"], lane["authorization_ref"])
        if (not all(isinstance(value, str) and value for value in key) or key in identities
                or any(type(lane[field]) is not int or lane[field] < 0 for field in ("calls", "tokens"))
                or lanes.get(key) != lane):
            _reject("Historical entitlement lanes retain only their frozen consumed or reserved amount")
        identities.add(key)
    for key, lane in lanes.items():
        if key not in identities and any(lane[field] > extra[field] for field in ("calls", "tokens")):
            _reject("New entitlement lanes cannot exceed the shared new allowance")


def validate_predecessor(plan: dict[str, Any], previous: dict[str, Any], *, project_id: str) -> None:
    from .creative_budget_contract import PROVIDER_BUDGET_VERSIONS, contract_hash
    from novel_forge.storage.versioned_policy_repository import policy_hash
    prior = previous["comparison_budget"]
    if (prior["contract_version"] not in PROVIDER_BUDGET_VERSIONS
            or plan["previous_policy"] != {"policy_version": previous["policy_version"],
                "policy_hash": policy_hash(previous), "contract_hash": contract_hash(prior)}):
        _reject("Renewal must append to its exact native predecessor")
    if (any(plan[key] != prior[key] for key in ("experiment_id", "manifest_hash", "accounting_basis"))
            or len(prior["arms"]) != 1
            or any(plan["arms"][0][key] != prior["arms"][0][key] for key in ("project_id", "book_id", "arm"))
            or plan["arms"][0]["project_id"] != project_id):
        _reject("Renewal cannot replace campaign, manifest, project or Book identity")


def validate_selection(plan: dict[str, Any], previous: dict[str, Any], content: dict[str, Any], usage: dict[str, Any]) -> None:
    authorization = content["authorization"]
    if any(authorization[key] == previous["authorization"][key] for key in ("authorization_ref", "evidence_hash")):
        _reject("Renewal requires a new explicit author authorization and evidence")
    now = datetime.now(timezone.utc)
    if not datetime.fromisoformat(plan["renewal"]["authorized_at"]) <= now < datetime.fromisoformat(plan["expires_at"]):
        _reject("New policy selection must be inside the original approved window")
    if plan["renewal"]["carry_forward"] != carry_forward_usage(usage):
        _reject("Ledger changed after renewal preparation; refresh the native carry-forward snapshot")
    if authorization["authorized_cumulative_caps"] != {
            phase: plan["arms"][0][phase.lower() + "_allocation"] for phase in usage["phases"]}:
        _reject("Renewal approval must bind the exact cumulative phase allocations")
    old_refs = {(lane["provider"], lane["authorization_ref"]) for lane in usage["entitlements"]}
    if any(lane["authorization_ref"] != authorization["authorization_ref"]
            for lane in plan["entitlements"] if (lane["provider"], lane["authorization_ref"]) not in old_refs):
        _reject("New entitlement lanes require this renewal's explicit authorization")


def check_window(plan: dict[str, Any], usage: dict[str, Any], *, calls: int, tokens: int, amount: Decimal | None) -> None:
    window = usage["renewal_usage"]
    limit = plan["renewal"]["additional_total"]
    if (window["calls_used_or_reserved"] + calls > limit["calls"]
            or window["conservative_tokens"] + tokens > limit["tokens"]
            or Decimal(window["priced_usd"]) + (amount or Decimal(0)) > Decimal(limit["priced_usd"])):
        raise KernelError("CREATIVE_BUDGET_RENEWAL_EXHAUSTED", "New-window usage cannot exceed its explicit additional allowance")
