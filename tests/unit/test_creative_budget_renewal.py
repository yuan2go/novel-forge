from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from novel_forge.modules.command_kernel.creative_budget_contract import (
    PROVIDER_RENEWAL_VERSION, PROVIDER_RENEWAL_POLICY_SCHEMA, PROVIDER_CAMPAIGN_PHASES,
    contract_hash, validate_policy,
)
from novel_forge.modules.command_kernel.creative_budget_renewal import carry_forward_usage
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.versioned_policy_repository import policy_hash
from tests.unit.test_creative_budget_contract import provider_campaign_policy


def renewed_policy(previous, usage, *, calls=3, tokens=600, amount="1", allocations=None):
    basis = carry_forward_usage(usage)
    policy = deepcopy(previous)
    policy["policy_version"] += ":renewed"
    policy["authorization"].update(authorization_ref=previous["authorization"]["authorization_ref"] + ":renewed",
        evidence_hash="sha256:" + "b" * 64, business_scope={"source_allowed": False, "design_allowed": True, "max_chapter_number": 2})
    plan = policy["comparison_budget"]
    plan.update(contract_version=PROVIDER_RENEWAL_VERSION,
        previous_policy={"policy_version": previous["policy_version"], "policy_hash": policy_hash(previous),
                         "contract_hash": contract_hash(previous["comparison_budget"])},
        renewal={"authorized_at": (datetime.now(timezone.utc) - timedelta(seconds=2)).isoformat(),
            "additional_total": {"calls": calls, "tokens": tokens, "priced_usd": amount}, "carry_forward": basis},
        expires_at=(datetime.now(timezone.utc) + timedelta(hours=24)).isoformat())
    additions = allocations or {"PRODUCTION": plan["renewal"]["additional_total"]}
    phases = deepcopy(basis["phases"])
    for phase, addition in additions.items():
        for key in ("calls", "tokens"):
            phases[phase][key] += addition[key]
        phases[phase]["priced_usd"] = str(Decimal(phases[phase]["priced_usd"]) + Decimal(addition["priced_usd"]))
    total = {key: sum(row[key] for row in phases.values()) for key in ("calls", "tokens")}
    total["priced_usd"] = str(sum(Decimal(row["priced_usd"]) for row in phases.values()))
    plan["shared_total"] = total
    plan["arms"][0].update(project_total=deepcopy(total), chapter_ranges={"PRODUCTION": [1, 2]},
        **{phase.lower() + "_allocation": value for phase, value in phases.items()})
    plan["entitlements"] = deepcopy(basis["entitlements"]) + [{"provider": "codex-cli",
        "authorization_ref": policy["authorization"]["authorization_ref"], "calls": calls, "tokens": tokens}]
    policy["authorization"]["authorized_cumulative_caps"] = deepcopy(phases)
    return policy


def empty_usage():
    empty = {"calls_used_or_reserved": 0, "conservative_tokens": 0, "priced_usd": "0"}
    return {"reservation_ids": [], "shared_total": deepcopy(empty), "entitlements": [],
            "phases": {phase: deepcopy(empty) for phase in PROVIDER_CAMPAIGN_PHASES}}


def test_renewal_schema_has_distinct_definition_and_keeps_v4_immutable():
    from novel_forge.modules.authority_handler_runtime.policy_commands import owned_policy_definition
    from novel_forge.modules.command_kernel.service import _validate_json_schema
    policy = renewed_policy(provider_campaign_policy(), empty_usage())
    assert validate_policy(policy) == policy
    _validate_json_schema(PROVIDER_RENEWAL_POLICY_SCHEMA, policy)
    definition = owned_policy_definition(owner="CREATIVE_EXPERIMENT_BUDGET", content=policy,
        application_build_id="fixture", commit_sha="a" * 40)
    assert definition["definition_version"] == "1.6.0"
    assert owned_policy_definition(owner="CREATIVE_EXPERIMENT_BUDGET", content=provider_campaign_policy(),
        application_build_id="fixture", commit_sha="a" * 40)["definition_version"] == "1.4.0"


@pytest.mark.parametrize("change", ["window", "baseline", "diagnostics", "old_lane", "additional", "no_predecessor"])
def test_renewal_rejects_unbound_window_history_and_diagnostic_credit(change):
    policy = renewed_policy(provider_campaign_policy(), empty_usage())
    plan = policy["comparison_budget"]
    if change == "window":
        plan["renewal"]["authorized_at"] = plan["expires_at"]
    elif change == "baseline":
        plan["renewal"]["carry_forward"]["reservation_ids"] = ["forged-reservation"]
    elif change == "diagnostics":
        plan["arms"][0]["calibration_allocation"] = plan["arms"][0]["production_allocation"]
        plan["arms"][0]["production_allocation"] = {"calls": 0, "tokens": 0, "priced_usd": "0"}
    elif change == "old_lane":
        plan["renewal"]["carry_forward"]["entitlements"] = [{**plan["entitlements"][0], "calls": 1}]
    elif change == "additional":
        plan["renewal"]["additional_total"]["tokens"] += 1
    else:
        plan.pop("previous_policy")
    with pytest.raises((KernelError, ValueError)):
        validate_policy(policy)


def test_zero_token_settlement_still_carries_its_used_call():
    from novel_forge.modules.command_kernel.service import _validate_json_schema
    usage = empty_usage()
    usage["reservation_ids"] = ["old-zero-token-call"]
    usage["shared_total"]["calls_used_or_reserved"] = 1
    usage["phases"]["DESIGN"]["calls_used_or_reserved"] = 1
    usage["entitlements"] = [{"provider": "codex-cli", "authorization_ref": "old-entitlement", "calls": 1, "tokens": 0}]
    policy = renewed_policy(provider_campaign_policy(), usage)
    assert validate_policy(policy) == policy
    _validate_json_schema(PROVIDER_RENEWAL_POLICY_SCHEMA, policy)


def test_released_historical_diagnostic_credit_cannot_authorize_new_diagnostics():
    from novel_forge.modules.command_kernel.creative_budget_runtime import _check_limits
    before = empty_usage()
    before["reservation_ids"] = ["historical-diagnostic"]
    before["shared_total"].update(calls_used_or_reserved=1, conservative_tokens=100, priced_usd="0.1")
    before["phases"]["CALIBRATION"].update(before["shared_total"])
    policy = renewed_policy(provider_campaign_policy(), before)
    after = empty_usage()
    after.update(project_id="project-A", project_total=deepcopy(after["shared_total"]),
                 renewal_usage=deepcopy(after["shared_total"]))
    with pytest.raises(KernelError, match="CREATIVE_BUDGET_RENEWAL_SCOPE_DENIED"):
        _check_limits(policy, after, phase="CALIBRATION", tokens=100, calls=1, amount=Decimal("0.1"))
