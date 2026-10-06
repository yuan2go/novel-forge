from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from novel_forge.modules.command_kernel.creative_budget_contract import (
    PROVIDER_REALLOCATION_VERSION, PROVIDER_REALLOCATION_POLICY_SCHEMA,
    contract_hash, validate_policy,
)
from novel_forge.modules.command_kernel.creative_budget_reallocation import validate_predecessor, validate_selection
from novel_forge.modules.command_kernel.creative_budget_renewal import carry_forward_usage
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.versioned_policy_repository import policy_hash
from tests.unit.test_creative_budget_contract import provider_campaign_policy
from tests.unit.test_creative_budget_renewal import empty_usage, renewed_policy


def reallocated_policy(previous, usage, *, source="PRODUCTION", target="REFERENCE", calls=1, tokens=100, amount="0.1"):
    policy = deepcopy(previous)
    policy["policy_version"] += ":reallocated"
    policy["authorization"].update(authorization_ref=previous["authorization"]["authorization_ref"] + ":reallocated",
        evidence_hash="sha256:" + "c" * 64)
    plan = policy["comparison_budget"]
    plan.pop("renewal", None)
    plan.update(contract_version=PROVIDER_REALLOCATION_VERSION,
        previous_policy={"policy_version": previous["policy_version"], "policy_hash": policy_hash(previous),
                         "contract_hash": contract_hash(previous["comparison_budget"])},
        reallocation={"authorized_at": (datetime.now(timezone.utc) - timedelta(seconds=2)).isoformat(),
                      "carry_forward": carry_forward_usage(usage)})
    arm = plan["arms"][0]
    for phase, sign in ((source, -1), (target, 1)):
        allocation = arm[phase.lower() + "_allocation"]
        allocation["calls"] += sign * calls
        allocation["tokens"] += sign * tokens
        allocation["priced_usd"] = str(Decimal(allocation["priced_usd"]) + sign * Decimal(amount))
    policy["authorization"]["authorized_cumulative_caps"] = {
        phase: deepcopy(arm[phase.lower() + "_allocation"]) for phase in usage["phases"]}
    return policy


def test_reallocation_keeps_lifetime_caps_and_has_exact_new_definition():
    from novel_forge.modules.authority_handler_runtime.policy_commands import owned_policy_definition
    from novel_forge.modules.command_kernel.service import _validate_json_schema

    previous = provider_campaign_policy()
    policy = reallocated_policy(previous, empty_usage())
    assert validate_policy(policy) == policy
    _validate_json_schema(PROVIDER_REALLOCATION_POLICY_SCHEMA, policy)
    validate_predecessor(policy["comparison_budget"], previous, project_id="project-A")
    validate_selection(policy["comparison_budget"], previous, policy, empty_usage())
    assert policy["comparison_budget"]["shared_total"] == previous["comparison_budget"]["shared_total"]
    assert policy["comparison_budget"]["entitlements"] == previous["comparison_budget"]["entitlements"]
    assert owned_policy_definition(owner="CREATIVE_EXPERIMENT_BUDGET", content=policy,
        application_build_id="fixture", commit_sha="a" * 40)["definition_version"] == "1.7.0"
    assert owned_policy_definition(owner="CREATIVE_EXPERIMENT_BUDGET", content=previous,
        application_build_id="fixture", commit_sha="a" * 40)["definition_version"] == "1.4.0"


@pytest.mark.parametrize("field", ["expires_at", "manifest_hash", "shared_total", "entitlements", "chapter_ranges", "book_id"])
def test_reallocation_cannot_expand_frozen_scope(field):
    previous = provider_campaign_policy()
    plan = reallocated_policy(previous, empty_usage())["comparison_budget"]
    if field in {"chapter_ranges", "book_id"}:
        plan["arms"][0][field] = {"PRODUCTION": [1, 40]} if field == "chapter_ranges" else "other-book"
    elif field == "entitlements":
        plan[field][0]["calls"] += 1
    elif field == "shared_total":
        plan[field]["calls"] += 1
    else:
        plan[field] += ":changed"
    with pytest.raises(KernelError, match="CREATIVE_BUDGET_REALLOCATION_INVALID"):
        validate_predecessor(plan, previous, project_id="project-A")


def test_reallocation_cannot_turn_production_renewal_into_diagnostics():
    previous = renewed_policy(provider_campaign_policy(), empty_usage(), calls=3, tokens=600, amount="1")
    policy = reallocated_policy(previous, empty_usage())
    with pytest.raises(KernelError, match="CREATIVE_BUDGET_REALLOCATION_INVALID"):
        validate_predecessor(policy["comparison_budget"], previous, project_id="project-A")


@pytest.mark.parametrize("change", ["stale_ledger", "permission", "evidence", "future_authorization", "partial_caps"])
def test_selection_rejects_stale_usage_or_unbound_authority(change):
    previous = provider_campaign_policy()
    usage = empty_usage()
    policy = reallocated_policy(previous, usage)
    if change == "stale_ledger":
        usage["reservation_ids"].append("new-held-reservation")
    elif change == "permission":
        policy["authorization"]["business_scope"]["max_chapter_number"] += 1
    elif change == "evidence":
        policy["authorization"]["evidence_hash"] = previous["authorization"]["evidence_hash"]
    elif change == "partial_caps":
        policy["authorization"]["authorized_cumulative_caps"]["PRODUCTION"]["calls"] -= 1
    else:
        policy["comparison_budget"]["reallocation"]["authorized_at"] = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    with pytest.raises(KernelError, match="CREATIVE_BUDGET_REALLOCATION_INVALID"):
        validate_selection(policy["comparison_budget"], previous, policy, usage)


def test_reallocation_never_discards_held_usage_to_zero_a_phase():
    usage = empty_usage()
    usage["reservation_ids"] = ["held-unknown"]
    usage["shared_total"].update(calls_used_or_reserved=1, conservative_tokens=100, priced_usd="0.1")
    usage["phases"]["PRODUCTION"] = deepcopy(usage["shared_total"])
    previous = provider_campaign_policy()
    cap = previous["comparison_budget"]["arms"][0]["production_allocation"]
    policy = reallocated_policy(previous, usage, calls=cap["calls"], tokens=cap["tokens"], amount=cap["priced_usd"])
    with pytest.raises(KernelError, match="CREATIVE_BUDGET_REALLOCATION_INVALID"):
        validate_policy(policy)


def test_model_reference_budget_derives_design_permission_from_native_subject(monkeypatch):
    import novel_forge.modules.command_kernel.creative_budget_runtime as runtime
    import novel_forge.modules.chapter_quality_authority.reference_subject as subjects
    from novel_forge.modules.command_kernel.creative_budget_scope import require_business_scope

    binding = {"subject": {"asset_version_id": "sample", "content_hash": "sha256:" + "a" * 64},
        "author_baseline": {"asset_version_id": "brief", "content_hash": "sha256:" + "b" * 64},
        "policy_hash": "sha256:" + "c" * 64, "producer_contract_hash": "sha256:" + "d" * 64,
        "protocol_version": "model-reference-consensus.v1", "evaluation_version": "v1",
        "dimension": "intent_alignment", "scope": {"scope_type": "BOOK", "book_id": "book-A"},
        "role": "BLIND_EVALUATION"}
    identity = {"operation_name": "quality.model_reference.evaluate", "capability": "model.model_reference_evaluate",
        "command_payload": {"book_id": "book-A", "model_reference": binding},
        "request_payload": {"stage": "model_reference_evaluate", "input": {"model_reference": binding},
            "_production_execution": {"book_id": "book-A", "model_reference": binding,
                                      "execution_binding_domain": "model_reference"}},
        "request_hash": "frozen-request"}

    class Cursor:
        def execute(self, sql, values):
            self.sql = sql
            self.values = values

        def fetchone(self):
            return ({"payload": {"book_id": "book-A"}},)

        def fetchall(self):
            assert self.values == ["project-A", "native-generation", "book_design.propose"]
            return [("source-effect",)]

    def subject(_cursor, *, project_id, binding, allowed_types):
        assert project_id == "project-A" and binding["asset_version_id"] == "sample"
        assert "planning_generation_candidate" in allowed_types
        return {"generation_operation_id": "native-generation", "content": {"generator_operation_name": "book_design.propose"}}

    monkeypatch.setattr(subjects, "require_reference_subject", subject)
    monkeypatch.setattr(runtime, "_effect_identity", lambda _cursor, effect, project: {"native_effect": effect, "project": project})
    monkeypatch.setattr(runtime, "_campaign_scope", lambda *_args, **_kwargs: {
        "phase": "SCREENING", "origin_phase": "DESIGN", "chapter_number": 0, "scope_sources": []})
    policy = provider_campaign_policy()
    scope = runtime._business_scope(Cursor(), identity, project_id="project-A", plan=policy["comparison_budget"])
    assert scope["phase"] == "REFERENCE" and scope["origin_phase"] == "DESIGN" and scope["chapter_number"] == 0
    require_business_scope(policy, scope)
    policy["authorization"]["business_scope"]["design_allowed"] = False
    with pytest.raises(KernelError, match="CREATIVE_BUDGET_BUSINESS_SCOPE_DENIED"):
        require_business_scope(policy, scope)
    identity["request_payload"]["_production_execution"]["book_id"] = "other-book"
    with pytest.raises(KernelError, match="CREATIVE_BUDGET_BUSINESS_SCOPE_UNKNOWN"):
        runtime._business_scope(Cursor(), identity, project_id="project-A", plan=policy["comparison_budget"])
