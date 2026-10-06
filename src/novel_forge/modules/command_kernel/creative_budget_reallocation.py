from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from .creative_budget_renewal import carry_forward_usage
from .errors import KernelError


def _reject(message: str) -> None:
    raise KernelError("CREATIVE_BUDGET_REALLOCATION_INVALID", message)


def validate_reallocation_contract(plan: dict[str, Any]) -> None:
    from .creative_budget_contract import PROVIDER_CAMPAIGN_PHASES, _object, _monetary_allocation

    change = _object(plan["reallocation"], "reallocation", {"authorized_at", "carry_forward"})
    try:
        authorized = datetime.fromisoformat(change["authorized_at"])
        expiry = datetime.fromisoformat(plan["expires_at"])
        if authorized.tzinfo is None or not authorized < expiry:
            raise ValueError("invalid authorization window")
    except (TypeError, ValueError) as exc:
        raise KernelError("CREATIVE_BUDGET_REALLOCATION_INVALID", "Reallocation requires a timezone-aware authorization within the unchanged campaign window") from exc
    if "previous_policy" not in plan:
        _reject("Reallocation requires the exact selected predecessor")
    basis = _object(change["carry_forward"], "carry_forward", {"reservation_ids", "shared_total", "phases", "entitlements"})
    ids = basis["reservation_ids"]
    if not isinstance(ids, list) or any(not isinstance(value, str) or not value for value in ids) or len(set(ids)) != len(ids):
        _reject("Carried reservation identities must be unique")
    phases = _object(basis["phases"], "carry_forward phases", set(PROVIDER_CAMPAIGN_PHASES))
    _monetary_allocation(basis["shared_total"], "carry_forward total", paired=False)
    arm = plan["arms"][0]
    for phase, used in phases.items():
        _monetary_allocation(used, "carry_forward " + phase, paired=False)
        if any(Decimal(str(used[key])) > Decimal(str(arm[phase.lower() + "_allocation"][key])) for key in used):
            _reject("Phase allocations cannot fall below consumed or unresolved reservations")
    if basis["shared_total"]["calls"] != len(ids) or any(
        Decimal(str(basis["shared_total"][key])) != sum(Decimal(str(row[key])) for row in phases.values())
        for key in basis["shared_total"]
    ):
        _reject("Carried phases and reservation identities must match the accounted total")
    historical = basis["entitlements"]
    if not isinstance(historical, list):
        _reject("Carried entitlement usage must be explicit")
    lanes = {(row["provider"], row["authorization_ref"]): row for row in plan["entitlements"]}
    seen = set()
    for row in historical:
        row = _object(row, "carry_forward entitlement", {"provider", "authorization_ref", "calls", "tokens"})
        key = (row["provider"], row["authorization_ref"])
        if (not all(isinstance(value, str) and value.strip() for value in key) or key in seen or key not in lanes
            or any(type(row[field]) is not int or row[field] < 0 or row[field] > lanes[key][field] for field in ("calls", "tokens"))):
            _reject("Carried account usage must fit its unchanged entitlement lane")
        seen.add(key)


def validate_predecessor(plan: dict[str, Any], previous: dict[str, Any], *, project_id: str) -> None:
    from .creative_budget_contract import PROVIDER_CAMPAIGN_VERSION, PROVIDER_REALLOCATION_VERSION, contract_hash
    from novel_forge.storage.versioned_policy_repository import policy_hash

    prior = previous["comparison_budget"]
    if (prior["contract_version"] not in {PROVIDER_CAMPAIGN_VERSION, PROVIDER_REALLOCATION_VERSION}
        or plan["previous_policy"] != {"policy_version": previous["policy_version"],
            "policy_hash": policy_hash(previous), "contract_hash": contract_hash(prior)}):
        _reject("Reallocation must append to the exact selected campaign; a production renewal cannot acquire diagnostic allowance")
    keys = ("experiment_id", "manifest_hash", "accounting_basis", "expires_at", "shared_total", "entitlements")
    arm_keys = ("arm", "project_id", "book_id", "project_total", "chapter_ranges")
    if (any(plan[key] != prior[key] for key in keys)
        or any(plan["arms"][0][key] != prior["arms"][0][key] for key in arm_keys)
        or plan["arms"][0]["project_id"] != project_id):
        _reject("Reallocation cannot change campaign, author scope, expiry, cumulative ceiling or account allowance")


def validate_selection(plan: dict[str, Any], previous: dict[str, Any], content: dict[str, Any], usage: dict[str, Any]) -> None:
    authorization = content["authorization"]
    if any(authorization[key] == previous["authorization"][key] for key in ("authorization_ref", "evidence_hash")):
        _reject("Reallocation requires a new explicit allocation authorization and evidence")
    if authorization["business_scope"] != previous["authorization"]["business_scope"]:
        _reject("Reallocation cannot expand business permissions")
    if not datetime.fromisoformat(plan["reallocation"]["authorized_at"]) <= datetime.now(timezone.utc) < datetime.fromisoformat(plan["expires_at"]):
        _reject("Selection must remain inside the original approved campaign window")
    if plan["reallocation"]["carry_forward"] != carry_forward_usage(usage):
        _reject("Ledger changed after preparation; refresh the native usage snapshot")
    if authorization["authorized_cumulative_caps"] != {
        phase: plan["arms"][0][phase.lower() + "_allocation"] for phase in usage["phases"]
    }:
        _reject("Reallocation authorization must bind every exact phase allocation")
